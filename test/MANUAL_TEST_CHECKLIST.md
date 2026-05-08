# Manual Test Checklist

Use this checklist when verifying the Gemini Chrome Agent on the real Gemini web app.

## Prerequisites

- [ ] Extension built: `npm run build` completed successfully
- [ ] Extension loaded in Brave: `brave://extensions/` → Load unpacked → select `.output/chrome-mv3/`
- [ ] Native Messaging host configured: `./setup.sh` run with correct Extension ID
- [ ] Log server running: `python3 log_server.py` (optional, for log forwarding)

---

## 1. Basic Connectivity

- [ ] Open `brave://extensions/` and verify the extension is enabled
- [ ] Click the extension icon → popup appears with "Paused" status
- [ ] Click "Resume Agent" → status changes to "Active"
- [ ] Open `gemini.google.com`
- [ ] Verify content script loads (check DevTools console for `[Gemini Agent] Content script loaded`)
- [ ] Verify background script connects to host (check `background.js` console for "Connecting to native host...")

## 2. Pause / Resume

- [ ] Press `Alt+Shift+K` → popup status toggles
- [ ] Click popup toggle button → status toggles
- [ ] Verify state persists across page reloads

## 3. Payload Detection & Execution

- [ ] Ask Gemini: "Run a shell command: `echo hello_from_agent`"
- [ ] Wait for Gemini to output a JSON code block with `"action": "run_shell"`
- [ ] Verify the payload is detected and forwarded to host
- [ ] Verify the response (`hello_from_agent`) is injected back into the input box
- [ ] Verify auto-send triggers (or manually click Send)

## 4. Deduplication

- [ ] Send the same payload twice in rapid succession
- [ ] Verify the second payload is ignored (check logs for "Deduplication: payload rejected")

## 5. Cooldown & Rate Limiting

- [ ] Send 6 payloads within 1 minute
- [ ] Verify the 6th payload auto-pauses the agent (rate limit: 5/min)
- [ ] Wait 15 seconds after a payload execution
- [ ] Verify cooldown ends and agent resumes

## 6. Settling Period (Refresh Guard)

- [ ] Load a Gemini conversation with historical JSON blocks
- [ ] Refresh the page
- [ ] Verify historical blocks are NOT re-executed during the first 5 seconds

## 7. Settings Persistence

- [ ] Open popup → Advanced → change Cooldown to 10s
- [ ] Close and reopen popup → verify setting persisted
- [ ] Change Rate Limit to 3/min
- [ ] Verify the new rate limit is enforced

## 8. Log Export

- [ ] Execute a few payloads to generate logs
- [ ] Open popup → click "Export Logs"
- [ ] Verify a JSON file downloads with log entries
- [ ] Click "Clear Logs" → verify logs are cleared

## 9. Error Handling

- [ ] Ask Gemini to output an invalid action (e.g., `"action": "unknown_action"`)
- [ ] Verify the host returns an error response
- [ ] Verify the error is handled gracefully (no crash, no infinite loop)

## 10. New Actions (Protocol v2)

- [ ] Test `git_status` — ask Gemini to check git status of a repo
- [ ] Test `list_files` — ask Gemini to list a directory
- [ ] Test `run_python` — ask Gemini to run Python code
- [ ] Verify all responses include `id`, `status`, `meta.duration_ms`

## 11. Service Worker Keepalive

- [ ] Leave the Gemini tab open for 2+ minutes
- [ ] Send a new payload
- [ ] Verify the background script reconnects to the host if needed

---

## Expected Results

All checks should pass. If any fail:
1. Check `docs/DEBUGGING.md` for the relevant failure mode
2. Export logs from the popup and inspect
3. Check `/tmp/gemini_host.log` for host-side errors
