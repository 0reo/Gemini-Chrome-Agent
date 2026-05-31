---
name: chrome-extension-builder
description: >
  Build, scaffold, debug, and publish Chrome browser extensions from scratch or existing code. Use this skill whenever the user mentions Chrome extension, browser extension, manifest.json, content script, background service worker, popup UI, browser action, web extension, Plasmo, CRXJS, Chrome Web Store, extension permissions, chrome.* APIs, or wants to add browser functionality via an extension. Also trigger for tasks like inject a script into a webpage, build a browser tool, make something that works on every page, or automate browser tasks.
license: MIT
metadata:
  author: Amit Acharya
  version: "1.0.0"
  category: browser-extension-development
---

# Chrome Extension Builder

A complete skill for building, debugging, and publishing Chrome browser extensions using Manifest V3.

## Quick Decision Guide

| What you need | Where to go |
|---|---|
| Scaffold a new extension | → [Workflow: Scaffold](#workflow-scaffold-a-new-extension) |
| Understand Manifest V3 | → `knowledge/manifest-v3-overview.md` |
| Understand architecture | → `knowledge/architecture.md` |
| Use a specific Chrome API | → `knowledge/chrome-apis-reference.md` |
| Security & CSP best practices | → `knowledge/security-csp.md` |
| Debug issues | → `knowledge/debugging-guide.md` |
| Publish to Chrome Web Store | → `knowledge/publishing-guide.md` |
| Starter template code | → `templates/` folder |
| Auto-scaffold script | → `scripts/scaffold.sh` |

---

## Workflow: Scaffold a New Extension

**Step 1 — Identify the extension type**

Ask the user (or infer from context) which type they need:
- **Popup** — UI in a small window when clicking the toolbar icon
- **Content Script** — Runs code injected into web pages
- **Background Service Worker** — Persistent logic, no UI
- **DevTools Panel** — Panel inside Chrome DevTools
- **Options Page** — Settings page accessible from extension menu
- **Side Panel** — Persistent panel on the right side (Chrome 114+)
- **Combo** — Most real-world extensions combine multiple types

**Step 2 — Read the manifest template**

Always start from `templates/manifest-v3.json` and customize. Manifest V3 is required for all new Chrome extensions. **Do not use Manifest V2.**

Key manifest fields to configure:
```json
{
  "manifest_version": 3,
  "name": "Your Extension",
  "version": "1.0.0",
  "description": "What it does",
  "permissions": [],
  "host_permissions": [],
  "action": {},
  "background": {},
  "content_scripts": []
}
```

**Step 3 — Scaffold the file structure**

Run `scripts/scaffold.sh <extension-name> <type>` OR create manually:

```
my-extension/
├── manifest.json          ← Required. The brain of the extension.
├── popup/
│   ├── popup.html         ← Popup UI (if needed)
│   ├── popup.css
│   └── popup.js
├── content/
│   └── content.js         ← Injected into web pages (if needed)
├── background/
│   └── service-worker.js  ← Background logic (if needed)
├── options/
│   ├── options.html       ← Settings page (if needed)
│   └── options.js
├── icons/
│   ├── icon16.png
│   ├── icon48.png
│   └── icon128.png
└── _locales/              ← i18n (optional)
    └── en/
        └── messages.json
```

**Step 4 — Apply the correct permissions**

Only request what you actually need. Chrome will reject or warn users about over-privileged extensions. Read `knowledge/chrome-apis-reference.md` → "Permissions Reference" section for the full list.

Common patterns:
- Read/modify current tab → `"activeTab"`
- Access all URLs → `"<all_urls>"` in `host_permissions`
- Store data → `"storage"`
- Make network requests from background → list in `host_permissions`
- Read clipboard → `"clipboardRead"` / `"clipboardWrite"`

**Step 5 — Write code per context**

Each extension context has strict rules. See `knowledge/architecture.md` for full details.

| Context | Can access DOM? | Can use chrome.* APIs? | Has window? |
|---|---|---|---|
| Popup | Own DOM only | Yes | Yes |
| Content Script | Page's DOM | Limited subset | Page's window |
| Service Worker | No | Full | No |
| Options Page | Own DOM | Yes | Yes |

**Step 6 — Test locally**

1. Open `chrome://extensions`
2. Enable **Developer Mode** (top-right toggle)
3. Click **Load unpacked** → select your extension folder
4. Test and reload after changes
5. Check console: popup → right-click icon → Inspect; service worker → click "Service Worker" link

**Step 7 — Debug issues**

See `knowledge/debugging-guide.md` for common errors and fixes.

**Step 8 — Package and publish**

See `knowledge/publishing-guide.md` for Chrome Web Store submission checklist.

---

## Key Principles

**Security first**: Never use `eval()`, `innerHTML` with untrusted input, or `unsafe-eval` in your Content Security Policy. Use `textContent` and DOM APIs instead.

**Message passing**: Popup and content scripts cannot directly share state. Use `chrome.runtime.sendMessage()` / `chrome.tabs.sendMessage()`. The service worker acts as the broker.

**MV3 migration**: If you encounter MV2 code (uses `background.scripts`, `browser_action`, `webRequestBlocking`), update it. See `knowledge/architecture.md` → "MV2 → MV3 Migration".

**Storage**: Use `chrome.storage.local` (not `localStorage`) for persistence across contexts.

---

## Common Patterns (Quick Reference)

### Send a message from popup to content script
```js
// popup.js
const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
chrome.tabs.sendMessage(tab.id, { action: "doSomething" }, (response) => {
  console.log(response);
});
```

### Listen in content script
```js
// content.js
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "doSomething") {
    // do it
    sendResponse({ success: true });
  }
  return true; // keep channel open for async
});
```

### Store and retrieve data
```js
// Set
await chrome.storage.local.set({ key: value });

// Get
const result = await chrome.storage.local.get(["key"]);
console.log(result.key);
```

### Inject a script into the active tab (from popup/background)
```js
const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
await chrome.scripting.executeScript({
  target: { tabId: tab.id },
  files: ["content/content.js"]
});
```
> Requires `"scripting"` permission and `"activeTab"` or host permissions.

---

## Reference Files

Read these when you need deep knowledge on a specific topic:

- `knowledge/architecture.md` — Extension contexts, lifecycle, MV2→MV3 migration
- `knowledge/chrome-apis.md` — Full chrome.* API usage guide with examples
- `knowledge/debugging.md` — Error messages, CSP issues, service worker gotchas
- `knowledge/publishing.md` — Chrome Web Store submission, review policies, versioning

## Templates

Ready-to-use starter code in `templates/`:
- `manifest-v3.json` — Base manifest template
- `popup.html` — Popup UI starter
- `content.js` — Content script starter with message listener
- `service-worker.js` — Background service worker starter
- `options.html` — Options page starter

## Scripts

- `scripts/scaffold.sh` — Auto-generate extension folder structure
- `scripts/package.sh` — Zip extension for Chrome Web Store upload
- `scripts/validate.sh` — Lint manifest.json and check for common issues
