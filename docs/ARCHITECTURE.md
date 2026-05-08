# Gemini Chrome Agent — Architecture

## High-Level Overview

The Gemini Chrome Agent is a three-tier system that bridges the Google Gemini web interface to your local Ubuntu machine, allowing the LLM to execute shell commands, read and write files, and run Python scripts autonomously.

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Gemini UI     │────▶│ Chrome Extension │────▶│   Python Host   │
│ (gemini.google) │◄────│  (WXT + TS)      │◄────│   (host.py)     │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │
                               ▼
                        ┌──────────────┐
                        │  Shell / FS  │
                        │  / Git / Py  │
                        └──────────────┘
```

| Tier | Technology | Responsibility |
|------|-----------|----------------|
| **Frontend** | TypeScript content script (`content.ts`) | Scrapes Gemini chat DOM for JSON action payloads |
| **Middleware** | TypeScript background service worker (`background.ts`) | Maintains Native Messaging port to the host; routes requests/responses |
| **Backend** | Python 3 (`host.py`) | Executes shell commands, file I/O, git ops, and Python scripts |

There is **no network server** and **no external API**. Communication between the browser and the OS happens through Chrome's [Native Messaging](https://developer.chrome.com/docs/extensions/mv3/nativeMessaging/) API over stdin/stdout.

---

## Data Flow

A single autonomous loop looks like this:

```
1. Gemini generates a response containing a JSON code block:
   {"action": "run_shell", "command": "uname -a", "id": "abc-123"}

2. content.ts (MutationObserver) detects the new <pre><code> block,
   validates the JSON, deduplicates it, and transitions state.

3. content.ts sends an ExtensionMessage to background.ts:
   {type: "SEND_TO_HOST", payload: {...}}

4. background.ts persists the sender tab ID in chrome.storage.session,
   forwards the payload over the Native Messaging port to host.py.

5. host.py reads the 4-byte length-prefixed JSON frame from stdin,
   executes the action (e.g., subprocess.run), builds a HostResponse,
   and writes the response back as a length-prefixed JSON frame to stdout.

6. background.ts receives the HostResponse, looks up lastActiveTabId
   from session storage, and sends the response to content.ts via
   chrome.tabs.sendMessage.

7. content.ts receives the HOST_RESPONSE, calls injectResponse() to
   paste "System Result:\n<output>" into Gemini's chat input box, then
   calls triggerSend() to auto-click the Send button.

8. Gemini sees the system result and continues the conversation.
```

---

## File Structure and Responsibilities

### `entrypoints/background.ts` — Service Worker

- **Native Messaging bridge**: Opens and maintains `browser.runtime.connectNative(CONFIG.NATIVE_HOST_NAME)`.
- **Tab routing**: Persists `lastActiveTabId` in `chrome.storage.session` so responses can be routed correctly even after the service worker sleeps and wakes up (Manifest V3).
- **Request queue**: Tracks pending requests with a 60-second timeout per request ID.
- **Fallback broadcast**: If the stored tab is closed or unreachable, falls back to broadcasting to the most recently active `*://gemini.google.com/*` tab.
- **Reconnection**: If the native port is missing when a message arrives, it reconnects automatically.

### `entrypoints/content.ts` — DOM Observation & State Machine

- **MutationObserver**: Watches `document.body` for new `<pre><code>` blocks (childList, subtree, characterData).
- **Debounced scanning**: Scans DOM `SCAN_DEBOUNCE_MS` (250ms) after mutations stop, to avoid processing partially-streamed JSON.
- **State machine**: Enforces the agent lifecycle (see below).
- **Keyboard shortcut**: `Alt+Shift+K` toggles pause/resume by flipping `isAgentPaused` in `chrome.storage.local`.
- **Rate limiting**: Tracks executions per minute; auto-pauses if `MAX_PER_MINUTE` (5) is exceeded.
- **Settling guard**: On page load, calls `markExistingBlocks()` to mark all already-present action blocks as processed, preventing immediate re-execution of historical payloads.

### `utils/injection.ts` — Input Injection & Send Trigger

- **`injectResponse(data)`**: Injects the host response into Gemini's chat input box.
  - Tries four strategies in order:
    1. `rich-textarea [contenteditable="true"]`
    2. `[role="textbox"][contenteditable="true"]`
    3. `.ql-editor`
    4. `<textarea>`
  - Uses `DataTransfer` paste simulation for React-compatible state updates.
  - Falls back to `document.execCommand('insertText')` and direct `innerText` assignment.
  - Dispatches `input`, `change`, `compositionend`, `keyup`, `keydown` events to nudge React re-renders.
- **`triggerSend(isPaused)`**: Polls for the Send button every `SEND_POLL_INTERVAL_MS` (200ms) up to `MAX_SEND_ATTEMPTS` (50). Uses selector list + heuristic text/aria-label matching. Triggers input events between attempts to enable the button.

### `utils/dedup.ts` — Payload Deduplication

- Maintains an in-memory `Map<string, number>` of hashed payloads → timestamps.
- **`hashPayload()`**: Canonical JSON stringification with sorted keys, then a fast JS string hash (DJB2 variant).
- **`isRecentlyProcessed()`**: Returns true if the hash exists and is younger than `PAYLOAD_TTL_MS` (60s). Performs lazy cleanup every `CLEANUP_INTERVAL_MS` (5s).
- **`markPayloadProcessed()`**: Explicitly marks a payload as seen (used by `markExistingBlocks`).
- **`clearProcessedPayloads()`**: Clears the entire dedup cache.

### `utils/protocol.ts` — Payload Validation & ID Generation

- **`generateId()`**: Creates a time-random composite ID (`Date.now().toString(36) + random`).
- **`isValidPayload()`**: Type-guards unknown objects against the 7 supported actions and their required fields.
- **`createRequestPayload()` / `createSuccessResponse()` / `createErrorResponse()`**: Factory helpers for Protocol v2 messages.

### `utils/logger.ts` — Structured Logging

- Three simultaneous sinks:
  1. **Console**: `console.log` / `warn` / `error` with `[Gemini Agent]` prefix.
  2. **Log server**: `fetch` to `CONFIG.LOG_SERVER_URL` (`http://localhost:9999/log?m=...`) for remote log capture.
  3. **Local storage**: Buffers up to `LOG_BUFFER_SIZE` (1000) entries in `chrome.storage.local` under `agentLogs`.
- Exports `debug`, `info`, `warn`, `error`, `getLogs()`, `clearLogs()`.

### `host.py` — Native Messaging Host

- Reads **4-byte little-endian length prefix** (`struct.pack('@I', len)`) from stdin, then reads that many bytes as JSON.
- Writes responses using the same length-prefix protocol.
- **Actions implemented**:
  - `run_shell` — `subprocess.run(command, shell=True, timeout=30)`
  - `write_file` — creates directories, writes UTF-8 text
  - `read_file` — reads UTF-8 text, expands `~`
  - `list_files` — `os.listdir` or descriptive error
  - `git_status` / `git_diff` — runs `git` in the specified directory
  - `run_python` — writes inline code to a temp file, executes with `sys.executable`
- **Safety**: Truncates output to 1MB to prevent breaking the native messaging frame format. Returns placeholder text when stdout+stderr are empty.
- **Logging**: Writes structured logs to `/tmp/gemini_host.log`.

---

## State Machine

The content script enforces a strict state machine to prevent runaway execution loops.

```
                    ┌─────────────┐
         ┌─────────▶│   PAUSED    │◄────────┐
         │          │  (initial)  │         │
         │          └──────┬──────┘         │
         │                 │ resume          │ rate limit
         │                 ▼                 │
         │          ┌─────────────┐          │
         │          │  SETTLING   │──────────┘
         │          │  (~5s)      │
         │          └──────┬──────┘
         │                 │ after SETTLING_PERIOD_MS
         │                 ▼
         │          ┌─────────────┐
         └─────────│    ARMED    │◄────────┐
            pause   │  (scanning) │         │
                    └──────┬──────┘         │
                           │ payload found   │
                           ▼                 │
                    ┌─────────────┐          │
                    │  COOLDOWN   │──────────┘
                    │  (~15s)     │
                    └─────────────┘
```

| State | Meaning | Transitions |
|-------|---------|-------------|
| `paused` | Agent is idle. No scanning, no injection. **Default on startup** unless the user has previously set `isAgentPaused: false`. | → `settling` on initial resume; → `armed` on subsequent unpause via storage listener |
| `settling` | Page just loaded. DOM is scanned, but existing/historical payloads are ignored. Only used on initial load, not when toggling pause mid-session. | → `armed` after `SETTLING_PERIOD_MS` (5s) |
| `armed` | Active scanning. New valid payloads are dispatched to the host. | → `cooldown` on execution; → `paused` on user toggle |
| `cooldown` | Just executed a payload. Scanner is disabled to prevent duplicate processing. | → `armed` after `COOLDOWN_MS` (15s) |

> **Note:** `cooldown` and `paused` both stop the MutationObserver scanner, but only `paused` blocks response injection.  
> The type system also defines an `error` state (`AgentState`), but it is not actively used in the current state machine transitions.

---

## Protocol v2 Format

All messages between the extension and `host.py` use **Protocol v2**: length-prefixed JSON with UUID correlation and a `meta` envelope.

### Request (Extension → Host)

```json
{
  "id": "lmnopq-rstuv",
  "action": "run_shell",
  "command": "uname -a",
  "meta": {}
}
```

### Response (Host → Extension)

**Success:**
```json
{
  "id": "lmnopq-rstuv",
  "status": "success",
  "output": "Linux ...",
  "code": 0,
  "meta": {"duration_ms": 42}
}
```

**Error:**
```json
{
  "id": "lmnopq-rstuv",
  "status": "error",
  "error": "Command timed out after 30 seconds.",
  "meta": {"duration_ms": 30001}
}
```

**Fatal Error:**
```json
{
  "id": "lmnopq-rstuv",
  "status": "fatal_error",
  "error": "...",
  "meta": {"duration_ms": 0}
}
```

### Field Reference

| Field | Type | Presence | Description |
|-------|------|----------|-------------|
| `id` | `string` | Always | Correlation ID. Generated by `generateId()` in the content script or protocol layer. |
| `action` | `string` | Request only | One of: `run_shell`, `write_file`, `read_file`, `list_files`, `git_status`, `git_diff`, `run_python` |
| `status` | `string` | Response only | `success`, `error`, or `fatal_error` |
| `output` | `string` | Response (success) | Command/file stdout or file contents |
| `message` | `string` | Response (success) | Human-readable success message (e.g., "File written.") |
| `error` | `string` | Response (error) | Human-readable error description |
| `code` | `number` | Response (optional) | Exit code from subprocess |
| `meta` | `object` | Always | Extension-defined metadata. Currently always contains `duration_ms`. |

### Native Messaging Frame Encoding

On the wire, messages are **not raw JSON**. They are framed as:

```
[4 bytes: uint32 little-endian length][N bytes: UTF-8 JSON]
```

Example in Python:

```python
import struct, json

def send_message(msg_dict):
    encoded = json.dumps(msg_dict).encode('utf-8')
    sys.stdout.buffer.write(struct.pack('@I', len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
```

This framing is handled automatically by Chrome's Native Messaging API on the extension side, and by `get_message()` / `send_message()` in `host.py`.

---

## Build & Extension Model

This project uses [WXT](https://wxt.dev/) as the extension framework:

- `wxt.config.ts` defines the Manifest V3 metadata (permissions, host matches).
- `entrypoints/background.ts` compiles to the service worker.
- `entrypoints/content.ts` compiles to a content script injected on `*://gemini.google.com/*`.
- `entrypoints/popup/` provides a browser-action popup for pause/resume toggling.
- `utils/*.ts` are shared TypeScript modules.

There is **no runtime dependency** on WXT in the built extension — it is a static output of JS and HTML loaded as an unpacked extension.
