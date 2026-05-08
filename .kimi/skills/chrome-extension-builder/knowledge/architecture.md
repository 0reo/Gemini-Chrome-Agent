# Chrome Extension Architecture Reference

## Table of Contents
1. [Extension Contexts](#1-extension-contexts)
2. [Lifecycle & Events](#2-lifecycle--events)
3. [Communication Patterns](#3-communication-patterns)
4. [Content Security Policy](#4-content-security-policy)
5. [MV2 → MV3 Migration](#5-mv2--mv3-migration)
6. [Storage Architecture](#6-storage-architecture)
7. [Permissions Model](#7-permissions-model)

---

## 1. Extension Contexts

Chrome extensions run in multiple isolated JavaScript contexts. Understanding context boundaries is critical.

### Popup (Browser Action)
- **Triggered**: User clicks the extension icon
- **Lifecycle**: Created when opened, destroyed when closed — do NOT store state here
- **Has DOM**: Yes (own HTML document)
- **chrome.* access**: Full (except `chrome.devtools`)
- **Can access page DOM**: No (use content scripts for that)
- **Window object**: Yes

### Content Script
- **Triggered**: Page load matching `matches` patterns in manifest, or programmatic injection
- **Lifecycle**: Tied to the page's lifetime
- **Has DOM**: Yes — the **host page's DOM** (shared)
- **chrome.* access**: Limited — only: `chrome.runtime`, `chrome.storage`, `chrome.i18n`, `chrome.identity` (partial), `chrome.alarms`
- **Can talk to page JS**: Via `window.postMessage()` or shared DOM (not directly — different JS worlds)
- **Isolated world**: Yes — runs in an isolated JS context from page scripts (use `world: "MAIN"` in `executeScript` to share the page's JS context)

### Background Service Worker
- **Triggered**: Browser events (install, alarm, message, network request, etc.)
- **Lifecycle**: Ephemeral — spun up on demand, terminated when idle (~30s). **Never store state in variables** — use `chrome.storage`.
- **Has DOM**: No
- **chrome.* access**: Full
- **Persistent**: No (MV3 removed persistent background pages)
- **Common mistake**: Assuming it stays alive. Always re-initialize state from storage on every event.

### Options Page
- Full extension page (`chrome-extension://id/options.html`)
- Full chrome.* access
- Persistent while tab is open

### Side Panel (Chrome 114+)
- Persistent panel on the right side of the browser
- Requires `"sidePanel"` permission
- Full chrome.* access, persists while user keeps it open
- Register: `"side_panel": { "default_path": "sidepanel.html" }`

### DevTools Panel
- Only accessible when DevTools is open
- Access to `chrome.devtools.*` APIs
- Cannot use most other chrome.* APIs
- Register via devtools page: `"devtools_page": "devtools.html"`

---

## 2. Lifecycle & Events

### Extension Install / Update
```js
// service-worker.js
chrome.runtime.onInstalled.addListener(({ reason }) => {
  if (reason === "install") {
    // First install — set defaults
    chrome.storage.local.set({ enabled: true });
  }
  if (reason === "update") {
    // Extension updated
  }
});
```

### Service Worker Keepalive Pattern
Service workers can be terminated at any time. For long-running operations:
```js
// Use chrome.alarms to wake the service worker periodically
chrome.alarms.create("keepAlive", { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "keepAlive") { /* no-op, just keeps it alive */ }
});
```
> Note: Even with alarms, do not rely on in-memory state. Always persist to `chrome.storage`.

### Tab Events
```js
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete") {
    // Page finished loading
  }
});

chrome.tabs.onActivated.addListener(({ tabId }) => {
  // User switched to this tab
});
```

---

## 3. Communication Patterns

### Popup ↔ Service Worker (one-time message)
```js
// popup.js — send
chrome.runtime.sendMessage({ action: "fetchData", url: "..." }, (response) => {
  console.log(response.data);
});

// service-worker.js — receive
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "fetchData") {
    fetch(message.url).then(r => r.json()).then(data => {
      sendResponse({ data });
    });
    return true; // CRITICAL: return true for async sendResponse
  }
});
```

### Popup → Content Script (via tabs)
```js
// popup.js
const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
chrome.tabs.sendMessage(tab.id, { action: "highlight" }, (response) => {
  if (chrome.runtime.lastError) {
    console.warn("No content script on this page");
  }
});
```

### Content Script → Service Worker
```js
// content.js
chrome.runtime.sendMessage({ action: "save", data: extractedData }, (response) => {
  console.log("Saved:", response.ok);
});
```

### Long-lived connections (ports)
```js
// content.js — connect
const port = chrome.runtime.connect({ name: "pageStream" });
port.onMessage.addListener((msg) => console.log(msg));
port.postMessage({ type: "start" });

// service-worker.js — accept
chrome.runtime.onConnect.addListener((port) => {
  if (port.name === "pageStream") {
    port.onMessage.addListener((msg) => {
      port.postMessage({ status: "received", msg });
    });
  }
});
```

### Content Script ↔ Page JavaScript
Since content scripts run in an isolated world from page JS, use `window.postMessage`:
```js
// content.js → page
window.postMessage({ source: "my-extension", type: "init" }, "*");

// page JS → content script listener
window.addEventListener("message", (event) => {
  if (event.source !== window) return;
  if (event.data.source !== "my-extension") return;
  // handle
});
```

---

## 4. Content Security Policy

### Default CSP (MV3)
MV3 enforces a strict default CSP for extension pages:
```
script-src 'self'; object-src 'self'
```
This means:
- No inline scripts (`<script>alert()</script>`) — use external `.js` files
- No `eval()`, `new Function()`, `setTimeout("string")`
- No external CDN scripts (use local copies)

### Custom CSP in manifest
```json
"content_security_policy": {
  "extension_pages": "script-src 'self'; object-src 'self'",
  "sandbox": "sandbox allow-scripts; script-src 'self' 'unsafe-eval'"
}
```
> Use `sandbox` pages (registered as `"sandbox": { "pages": ["sandbox.html"] }`) if you absolutely need `eval` — e.g., for a template engine. Sandboxed pages cannot use chrome.* APIs.

### Content Script CSP
Content scripts inherit the **host page's CSP**, not the extension's. This affects what can run in the page DOM context.

---

## 5. MV2 → MV3 Migration

| MV2 | MV3 Equivalent |
|---|---|
| `"manifest_version": 2` | `"manifest_version": 3` |
| `"browser_action"` | `"action"` |
| `"page_action"` | `"action"` |
| `"background": { "scripts": [...] }` | `"background": { "service_worker": "sw.js" }` |
| `"background": { "persistent": true }` | Not available — use `chrome.storage` + events |
| `chrome.browserAction.*` | `chrome.action.*` |
| `chrome.pageAction.*` | `chrome.action.*` |
| `webRequestBlocking` | Use `declarativeNetRequest` instead |
| `XMLHttpRequest` in background | `fetch()` in service worker |
| Remotely hosted code | Must bundle all code locally |
| `chrome.tabs.executeScript()` | `chrome.scripting.executeScript()` |
| `chrome.tabs.insertCSS()` | `chrome.scripting.insertCSS()` |

### Deprecated APIs to avoid
- `chrome.extension.getBackgroundPage()` — gone
- `chrome.extension.sendRequest()` — use `chrome.runtime.sendMessage()`
- `chrome.tabs.sendRequest()` — use `chrome.tabs.sendMessage()`

---

## 6. Storage Architecture

### chrome.storage.local
- Up to 10MB (unlimited with `"unlimitedStorage"` permission)
- Persists across sessions
- Accessible from all extension contexts
- Not synced

### chrome.storage.sync
- Up to 100KB total, 8KB per item
- Synced across user's Chrome instances (if signed in)
- Up to 512 items, 1800 write operations/hour

### chrome.storage.session (Chrome 102+)
- In-memory, cleared when browser closes
- Up to 10MB
- Shared across all extension contexts in a session

### When to use what
```
Sensitive / large data → chrome.storage.local
User preferences → chrome.storage.sync (keep small)
Temporary state → chrome.storage.session
Never → localStorage (not accessible from service workers)
```

---

## 7. Permissions Model

### Declared vs. Optional Permissions
```json
{
  "permissions": ["storage", "activeTab"],
  "optional_permissions": ["history", "bookmarks"],
  "host_permissions": ["https://api.example.com/*"],
  "optional_host_permissions": ["https://*/*"]
}
```

Request optional permissions at runtime:
```js
chrome.permissions.request({
  permissions: ["history"],
  origins: ["https://*/*"]
}, (granted) => {
  if (granted) { /* use the permission */ }
});
```

### Least Privilege Principle
- Use `"activeTab"` instead of `"<all_urls>"` when you only need the current tab
- Use `"scripting"` + `"activeTab"` instead of broad host permissions for injection
- Chrome Web Store reviewers check for over-broad permissions

### Host Permissions
```json
"host_permissions": [
  "https://api.myservice.com/*",   // specific domain
  "https://*.example.com/*",       // subdomain wildcard
  "<all_urls>"                      // all URLs (requires justification in store)
]
```
