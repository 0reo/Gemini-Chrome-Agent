# Gemini Chrome Agent — Debugging Guide

## Quick Diagnostic Checklist

| Symptom | First Check |
|---------|-------------|
| Nothing happens when Gemini outputs JSON | Is the agent paused? Check popup badge or DevTools console. |
| Host not found error | Run `./setup.sh` and verify Extension ID. |
| Service worker shows "Inactive" | Click the service worker link in `brave://extensions/` to wake it. |
| Injection seems to work but message isn't sent | Check if Send button is disabled; trigger input events manually. |

---

## "Extension not connecting to host"

### Symptoms
- Background console shows: `Specified native messaging host not found.`
- `port.onDisconnect` fires immediately with a runtime error.

### Checklist

1. **Host manifest exists and is valid**
   ```bash
   cat com.local.gemini_agent.json
   ```
   Ensure:
   - `"path"` points to the absolute path of `host.py`.
   - `"allowed_origins"` contains your exact Extension ID (e.g., `chrome-extension://abc123/`).

2. **Symlink is in the correct NativeMessagingHosts directory**
   ```bash
   ls -la ~/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts/
   # or for Chrome:
   ls -la ~/.config/google-chrome/NativeMessagingHosts/
   ```
   The symlink should point to `com.local.gemini_agent.json` in the project root.

3. **Extension ID whitelist match**
   The Extension ID shown in `brave://extensions/` must exactly match the ID in `allowed_origins`. If you reload the extension and the ID changes, re-run `./setup.sh`.

4. **`host.py` is executable**
   ```bash
   chmod +x host.py
   ```
   The shebang (`#!/usr/bin/env python3`) must also resolve to a valid Python 3 interpreter.

5. **Test the host directly from the background console**
   In the service worker DevTools console:
   ```js
   const port = browser.runtime.connectNative('com.local.gemini_agent');
   port.onMessage.addListener(m => console.log('Host says:', m));
   port.onDisconnect.addListener(() => console.log('Disconnected', browser.runtime.lastError));
   port.postMessage({id: 'test-1', action: 'run_shell', command: 'echo hello'});
   ```

---

## "Phantom duplicates"

### Symptoms
- The same payload executes multiple times.
- Gemini receives multiple identical "System Result" injections.

### Root Cause
The deduplication cache (`utils/dedup.ts`) is an in-memory `Map` keyed by payload hash. It can miss duplicates if:
1. The payload fields arrive in a different order (hash is sorted-key canonical, so this is handled).
2. The content script was reinjected (page refresh, extension reload) — the Map is recreated empty.
3. The `id` field differs between otherwise identical payloads.

### How to inspect
Open DevTools on the Gemini tab and look for:
```
[Gemini Agent] Deduplication: payload rejected {hash: "a1b2c3", action: "run_shell"}
```
If you see the same payload dispatched twice with different hashes, the `id` or a field is changing.

### How to clear the processed cache
The dedup cache is not exposed to the popup. To clear it:
1. **Refresh the Gemini tab** — the content script is reinjected with a fresh Map.
2. **Or**, open DevTools Console on the Gemini tab and run (if you have access to the content script scope):
   ```js
   // Only works if you attach to the content script context
   clearProcessedPayloads();
   ```
   > Note: This function exists in `utils/dedup.ts` but is not globally exposed in production builds.

3. **For development**, you can temporarily add `window._clearDedup = clearProcessedPayloads;` in `content.ts` to expose it.

---

## "Refresh cascade"

### Symptoms
- Immediately after loading Gemini, the agent executes a batch of old payloads from chat history.
- Rapid-fire "System Result" messages appear before you've sent any new prompt.

### Root Cause
Without the settling period, the MutationObserver would detect all historical `<pre><code>` blocks present in the DOM at page-load time and treat them as new. The `markExistingBlocks()` function scans the DOM on startup and marks all valid action blocks as processed, but if Gemini lazy-loads conversation history *after* the initial scan, those blocks appear as "new mutations" and trigger execution.

### How the settling guard works

1. **On load**, `content.ts` sets `state = 'settling'`.
2. **`markExistingBlocks()`** runs once immediately, marking visible blocks as processed.
3. The **MutationObserver** is active, but `scanForPayloads()` checks `isSettling()`:
   ```ts
   if (settling) {
     info('Settling: ignored historical payload', ...);
     continue;
   }
   ```
4. After `SETTLING_PERIOD_MS` (5000ms), state transitions to `armed` and new payloads are accepted.

### Fix / Mitigation
- **Wait 5 seconds** after the page loads before sending a prompt that generates actions.
- If Gemini loads history asynchronously *after* the 5-second window, the payload will be treated as new. In this case, **pause the agent immediately on load** and resume it only after the conversation is stable.
- You can increase `SETTLING_PERIOD_MS` in `utils/config.ts` if your connection is slow.

---

## "Service worker sleeps"

### Symptoms
- The first message after a long idle period works, but subsequent messages fail.
- Background console shows: `Could not establish connection. Receiving end does not exist.`
- `lastActiveTabId` is stale.

### Root Cause
Manifest V3 service workers are ephemeral. Chrome/Brave terminates them after ~30 seconds of inactivity. The Native Messaging port is also closed. When a new response arrives from `host.py`, the service worker may need to wake up and re-establish the port.

### How the extension handles it

1. **`browser.storage.session`** persists `lastActiveTabId` across sleep/wake cycles.
2. **Automatic reconnection**: In `background.ts`, if `port` is null when a `SEND_TO_HOST` message arrives, `connectToHost()` is called again.
3. **`browser.runtime.onConnect` listener**: Provides a keepalive hook. External long-lived ports (e.g., from the popup) keep the service worker alive while they are connected.

### How to verify
1. Go to `brave://extensions/`, find the extension, click **service worker**.
2. In the console, run:
   ```js
   browser.storage.session.get('lastActiveTabId').then(console.log);
   ```
3. Let the worker go inactive (close DevTools, wait 30–60s).
4. Trigger a new payload. The worker should wake, reconnect to the native host, and route the response using the stored tab ID.

### If reconnection fails
- The fallback `broadcastToGeminiTabs()` queries all `*://gemini.google.com/*` tabs and sends to the last one.
- If you have multiple Gemini tabs, the response may go to the wrong one. Keep only one Gemini tab open.

---

## "Injection fails"

### Symptoms
- The host executes successfully (log shows output), but Gemini's input box remains empty or the text appears garbled.
- Auto-send does not happen.

### Checklist

1. **Verify selectors match the current Gemini DOM**
   Open DevTools on the Gemini tab and test:
   ```js
   document.querySelector('rich-textarea [contenteditable="true"]');
   document.querySelector('[role="textbox"][contenteditable="true"]');
   document.querySelector('.ql-editor');
   document.querySelector('textarea');
   ```
   One of these must return a non-null element. If Google has updated their DOM, update the selectors in `utils/injection.ts`.

2. **Try manual paste**
   In `injectIntoContentEditable`, the primary mechanism is a simulated `ClipboardEvent('paste')`. Some React frameworks block synthetic paste events. Try manually pasting into the input box — if that works but the script fails, the framework may be intercepting synthetic events.

3. **Verify input element is focused and editable**
   If the input is inside a Shadow DOM or iframe, `document.querySelector` from the content script won't find it. Gemini currently does not use Shadow DOM for the chat input, but this should be verified if injection suddenly breaks.

4. **Check `triggerSend()`**
   The Send button polling uses these selectors:
   ```js
   'button[aria-label="Send message"]'
   'button[aria-label*="Send"]'
   'button[mattooltip*="Send"]'
   'button[data-testid="send-button"]'
   'button.send-button'
   'button[aria-label*="send"]'
   ```
   If the button is disabled until text is entered, the input events dispatched by `injectResponse` may not be sufficient. Run `triggerInputEvents()` manually in the console to force-enable it.

5. **Use `test/test_injection.html`**
   Open this file directly in a browser tab (no extension needed). It simulates the three input types and runs the exact injection strategies from `utils/injection.ts`. If a strategy fails here, it will also fail on Gemini.

---

## "No logs"

### Symptoms
- DevTools console is empty of `[Gemini Agent]` messages.
- `/tmp/gemini_host.log` is empty or not updating.
- `log_server.py` shows no incoming requests.

### Checklist

1. **Is `log_server.py` running?**
   ```bash
   python3 log_server.py
   # Should print: Log server running at http://localhost:9999/
   ```
   The logger silently catches fetch failures, so if the server is down, you won't see errors — just missing logs.

2. **CORS blocks**
   The log server sends `Access-Control-Allow-Origin: *` on all responses. If you see CORS errors in the Gemini tab's DevTools console, verify the server is responding correctly:
   ```bash
   curl -I http://localhost:9999/
   ```

3. **CSP blocks**
   Some pages have a strict Content Security Policy that blocks `fetch` to `localhost`. Check the Network tab in DevTools for blocked `log?m=...` requests.

4. **Extension console vs page console**
   - `[Gemini Agent]` logs from `content.ts` appear in the **page DevTools console** (F12 on the Gemini tab).
   - `[Background]` logs from `background.ts` appear in the **service worker console** (`brave://extensions/` → service worker link).

5. **Host logs**
   ```bash
   tail -f /tmp/gemini_host.log
   ```
   If this file doesn't exist, the host has never been launched by the browser, or the Python process lacks write permissions to `/tmp`.

---

## How to Export Logs

### From the popup
The popup (`entrypoints/popup/main.ts`) currently shows status and a toggle button, but does not display logs. To view logs programmatically:

1. **From the background console:**
   ```js
   browser.storage.local.get('agentLogs').then(r => console.log(r.agentLogs));
   ```

2. **From the page console (content script context):**
   ```js
   // If you have injected a helper or are in the content script scope:
   browser.storage.local.get('agentLogs').then(r => console.table(r.agentLogs));
   ```

3. **From `log_server.py` output:**
   ```bash
   cat /tmp/gemini_agent_console.log
   ```

4. **Copy-paste from DevTools:**
   Filter the console for `[Gemini Agent]` and `[Background]`, right-click → **Save as...**.

---

## How to Use `mock_gemini.html` for Rapid Testing

`test/mock_gemini.html` is a self-contained testbed that simulates the Gemini chat UI and replicates the content script's state machine, deduplication, and payload detection logic.

### Usage

1. **Open the file in a browser** (no server needed):
   ```bash
   # From project root
   open test/mock_gemini.html        # macOS
   xdg-open test/mock_gemini.html    # Linux
   ```

2. **Controls sidebar:**
   - **Preset selector**: Choose one of the 7 actions.
   - **Custom payload**: Paste your own JSON.
   - **Simulate streaming**: When checked, the JSON is appended character-by-character to mimic Gemini's streaming renderer.
   - **Inject JSON**: Adds a `<pre><code>` block to the chat area.
   - **Simulate history load**: Injects all 7 sample payloads at once (tests settling/dedup).

3. **Observe the log console:**
   The bottom panel shows what the content script would do:
   - `Payload dispatched` — passed validation and dedup, would be sent to background.
   - `Payload deduplicated` — hash matched a recently processed entry.
   - `Settling: ignored historical payload` — caught by the settling guard.

4. **State controls:**
   - Click **Resume** to transition from `paused` → `settling` → `armed`.
   - Stats track detected, dispatched, deduped, and ignored counts.

### When to use it
- Testing new actions or protocol changes without risking real execution.
- Reproducing race conditions between streaming and scanning.
- Verifying deduplication behavior with rapid repeated payloads.

---

## How to Run Protocol Unit Tests

The protocol framing logic (length-prefix encode/decode) is tested in `test/test_protocol.py`.

### Run the tests

```bash
cd /home/oreo/Development/Gemini-Chrome-Agent
python3 -m unittest test.test_protocol -v
```

### What is covered

| Test Class | Cases |
|------------|-------|
| `TestFrameEncoding` | Simple dict, empty dict, Unicode payload |
| `TestFrameDecoding` | Roundtrip, multiple sequential frames, EOF, truncated headers, truncated bodies, invalid length, malformed JSON |
| `TestLargePayloadHandling` | Exact 1MB limit, over-limit truncation, multibyte UTF-8 characters, `None` handling |

### Adding new tests

If you modify `host.py`'s framing or truncation logic, mirror the change in `test/test_protocol.py` (the `encode_frame`, `decode_frame`, and `truncate_output` helpers are intentionally duplicated so the tests have zero external dependencies).

```python
# Example: test a new edge case
class TestNewBehavior(unittest.TestCase):
    def test_negative_length(self):
        # ...
```

---

## How to Run Browser E2E Tests

`test/e2e_browser.py` connects to a real Chromium/Chrome instance via the Chrome DevTools Protocol (CDP) to verify the full extension pipeline in a live browser.

### Prerequisites

```bash
pip install websocket-client
```

### Launch a test browser with the extension

```bash
# Use Playwright's cached Chromium or your system Chrome
CHROME="$HOME/.cache/ms-playwright/chromium-1222/chrome-linux64/chrome"
# Or: CHROME="/usr/bin/google-chrome"

xvfb-run -a --server-args="-screen 0 1280x720x24" \
  "$CHROME" \
    --remote-debugging-port=9223 \
    --remote-allow-origins='*' \
    --load-extension="/path/to/project/.output/chrome-mv3" \
    --user-data-dir=/tmp/gla-test-profile \
    --no-first-run \
    --no-sandbox \
    --disable-setuid-sandbox \
    https://gemini.google.com
```

> **Why `xvfb-run`?** On a headless Linux server, Chrome needs a virtual display. On a desktop with a real display, you can omit `xvfb-run`.

> **Why `--remote-allow-origins='*'`?** Chrome blocks WebSocket CDP connections from unknown origins by default. This flag allows the test script to connect.

### Run the test

```bash
python3 test/e2e_browser.py
# Or with a custom CDP port:
python3 test/e2e_browser.py 9224
```

### What is covered

| Check | Description |
|-------|-------------|
| Service worker load | Extension background script registers correctly |
| `chrome.runtime.connectNative` | Native Messaging API is available |
| `chrome.runtime.onMessage` | Message passing API is available |
| Content script injection | Content script loads on `gemini.google.com` |
| State machine | Transitions from `settling` → `paused` correctly |
| Storage sync | Reads `paused` state from `chrome.storage.local` |

### Interpreting results

- **PASS** — The extension is fully functional in the browser.
- **FAIL: Cannot connect to CDP** — Browser not running with `--remote-debugging-port=9223` or wrong port.
- **FAIL: Extension service worker not found** — Extension not loaded; verify `--load-extension` path.
- **FAIL: content_script_loaded / state_transition / storage_sync** — Content script has a runtime error; check the browser console for stack traces.
- **FAIL: background.connectNative** — Manifest issue or browser restriction on `nativeMessaging` permission.
