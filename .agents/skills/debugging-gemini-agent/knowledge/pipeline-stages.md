# Pipeline stages — failure modes & evidence

The closed loop, with the exact code locations and the runtime evidence that proves each stage ran.
Walk this **backward** from stage 5 when diagnosing "nothing happened" (see the decision tree in SKILL.md).

---

## Stage 1 — DETECT  (`entrypoints/content.ts` → `scanForPayloads`)

A `MutationObserver` on `document.body` debounces, then `scanForPayloads()` walks `pre code, code`
nodes, keeps ones whose text contains `"action"`, `JSON.parse`s them, and validates via
`isValidPayload()` (8 actions: `run_shell`, `write_file`, `read_file`, `list_files`, `git_status`,
`git_diff`, `run_python`, `attach_files`).

**Evidence (page console):** every scan ends with
`dbgAgent('B', … 'scan complete', { state, settling, blockCount, withAction, executed })`.
- `withAction === 0` → the JSON is **not in a `<pre><code>`/`<code>` node**, or doesn't contain `"action"`.
  Gemini sometimes renders inline or wraps differently while streaming. **This is a detection bug.**
- `withAction > 0` but `executed === 0` → detection worked; a **guard** (stage 2) dropped it, or it was
  invalid (`invalid payload` dbg line).

**Common real cause:** the user copied prose around the JSON, or Gemini emitted it inline (no code
fence). No `<pre><code>` → never detected.

---

## Stage 2 — GUARDS  (state machine in `content.ts`, constants in `utils/config.ts`)

| Guard | Constant / mechanism | Default | Silent drop when… | Console line |
|-------|----------------------|---------|-------------------|--------------|
| Historical block | `blocksPresentAtLoad` (WeakSet of elements) | n/a | the block was already in the DOM when the content script loaded (chat history, page refresh, extension reload) | `historical block skip` |
| Settling | `SETTLING_PERIOD_MS` | 5000 ms | payload is in the DOM within 5 s of script load | `Settling: ignored historical payload` |
| Cooldown | `COOLDOWN_MS` | 15000 ms | another payload ran in the last 15 s (state = `cooldown`, scans skipped) | `scan skipped {state:'cooldown'}` |
| Rate limit | `MAX_PER_MINUTE` | 5 | >5 executions in a minute → **auto-pauses** and writes `isAgentPaused:true` | `Rate limit hit … Auto-pausing` |
| Dedup | `PAYLOAD_TTL_MS` (in-memory `Map`, TTL-cleaned) | 60000 ms | the *same payload hash* ran within the last 60 s; the `Map` is empty again after a reinjection of the content script | `dedup skip` |
| Paused | `isAgentPaused` (storage) | — | toggled via `Alt+Shift+K` / popup, or auto-set by rate limit | `scan skipped {paused:true}` |

**Read the truth, don't guess** (run in the **service-worker** context — `chrome.*` is `undefined` on
the Gemini page's main world, so a page-context read throws `chrome is undefined`, not the answer):
```js
chrome.storage.local.get(['isAgentPaused','autoSubmit','cooldownSeconds','maxPerMinute','settlingSeconds'])
```
`isAgentPaused !== true` means **not paused** — do not claim "paused" without this read. If there's no
service-worker target to read from, the SW is asleep (wake it via the SW link) or the extension isn't loaded.

### The load-time trap — the failure that actually bit (verify against current code)
The strongest match for *"Gemini wrote the JSON, then nothing happened"* is a block that was **already on
screen when the content script loaded** — e.g. the user refreshed the tab, the extension reloaded, or
they navigated back to a chat that already contained the block. `recordBlocksPresentAtLoad()` adds every
such block to the `blocksPresentAtLoad` WeakSet; `scanForPayloads()` then skips it (`historical block
skip`) so history isn't auto-replayed. **By design it can therefore never run** — even while armed and
unpaused. The 5 s settling window suppresses the same blocks for the first 5 s on top of that.

> History worth knowing: an earlier version did this differently — `markExistingBlocks()` called
> `markPayloadProcessed()`, poisoning the **dedup** `Map` at load, which suppressed a matching payload
> until its TTL expired. That was reworked to the element-identity WeakSet above (uncommitted in the
> working tree as of this writing). **Confirm the live behavior in `content.ts` + `dedup.ts` before you
> rely on either description** — both files are being actively edited, and this skill's own first rule is
> *don't trust a prior account over the running code.*

**To reproduce this you MUST recreate the load condition:** have the JSON block present in the DOM
*before* the content script runs (reload the tab with the block visible, or test on the user's actual
chat). A block you inject *after* load (the obvious CDP probe) is a brand-new element, not in
`blocksPresentAtLoad`, past the settling window — so it runs fine and gives you a **false green**.

---

## Stage 3 — ROUTE  (`entrypoints/background.ts`, MV3 service worker)

`content.ts` does `browser.runtime.sendMessage({type:'SEND_TO_HOST', payload})`. The SW holds a
`connectNative('com.local.gemini_agent')` port and forwards it; the response comes back as
`HOST_RESPONSE` routed to the stored `lastActiveTabId` (persisted in `browser.storage.session` so it
survives SW sleep).

**Evidence (service-worker console — `brave://extensions/` → "service worker" link):** `[Background]` lines.

**Failure modes:**
- **SW inactive/asleep:** MV3 terminates the worker after ~30 s idle. First message after idle may show
  `Could not establish connection. Receiving end does not exist.` Click the SW link to wake it; the code
  re-calls `connectToHost()` when `port` is null. Verify: `browser.storage.session.get('lastActiveTabId')`.
- **Native messaging broken:** `Specified native messaging host not found.` → extension-ID / manifest /
  symlink mismatch. See "Native messaging" below and `docs/DEBUGGING.md`.
- **Multiple Gemini tabs:** the fallback `broadcastToGeminiTabs()` may route the response to the wrong
  tab. Keep one Gemini tab open while debugging.

---

## Stage 4 — EXECUTE  (`host.py`, native messaging host)

Persistent Python process, length-prefixed JSON over stdin/stdout. Dispatches on `action`, executes,
returns stdout/stderr/exit (1 MB `truncate_output` cap; `attach_files` streams base64 chunks instead).

**Evidence:** `tail -f /tmp/gemini_host.log` → `message received {action, id}` then the result line.
- **No `message received`** → the payload never reached the host (a stage 1–3 problem, not the host).
- **`message received` but no follow-up / a traceback** → host-side bug (command error, file path, crash).
- **Host log file absent** → host never launched by the browser (ID/manifest/symlink), or no `/tmp` write perm.

Reproduce host behavior in isolation, no browser:
```bash
python3 main.py run_shell "echo hello"      # or write_file / read_file / interactive (JSON REPL)
```

### Native messaging gotcha (the silent one)
On Linux the **unpacked extension ID is derived from the `--load-extension` absolute path**. The path
`<repo>/.output/chrome-mv3` (**NO trailing slash**) hashes to `pggfgfolmomlhlnabkfboiiojdkhapoh`, the exact
ID `com.local.gemini_agent.json` is locked to. A different path, or a trailing slash, yields a different
ID → native messaging breaks with no obvious error. `scripts/launch-debug-brave.sh` already loads from
that exact path; if you load the extension by hand, match it or re-run `setup.sh` with the new ID.

---

## Stage 5 — INJECT + SEND  (`utils/injection.ts`, `entrypoints/content.ts` HOST_RESPONSE handler)

The SW's `HOST_RESPONSE` → `injectResponse(data)` → `injectText()` puts `System Result: …` into the
composer; if `autoSubmit !== false`, `triggerSend()` fires.

**On success the result is auto-sent into the thread and the composer clears** — so the only visible
artifact is a new `System Result:` turn, **not** text sitting in the box. That means a successful run can
*look* like "nothing happened." It also means the inverse mistake is easy: concluding "it worked" because
*your* synthetic test sent a result, while the user's real payload never ran. Confirm against the user's
actual chat, not a test you injected.

**Check, in order:**
1. **Did it already send?** `document.body.innerText.includes('System Result')`, or look for a new
   conversation turn / URL. If yes → it ran; verify it's the user's payload and not your own test echo.
   (In the motivating incident an assistant *assumed* this was the answer and was wrong — the payload had
   actually been dropped by a load-time guard, stage 2. Confirm; don't assume.)
2. **Quill model, not just pixels.** Gemini's composer is a **Quill editor (Angular Material)**. Raw DOM
   mutation (`innerText`, `insertNode`) shows text but leaves Quill's model empty → the `.ql-editor`
   keeps its `ql-blank` class → Send never arms. Injection MUST use `document.execCommand('insertText')`.
   Probe: after injecting, `.ql-editor` should **lose** `ql-blank`.
3. **Send gate is `pointer-events`, not `disabled`.** Gemini's Send button keeps `disabled === false`
   (and `aria-disabled` null) even when empty; it gates clicks with CSS `pointer-events: none`. A
   `!btn.disabled` check is meaningless — it always "clicks" and silently no-ops. Readiness is
   `getComputedStyle(btn).pointerEvents !== 'none'`. If it stays `none` after injection, step 2 failed.
4. **Input-hijack guard / auto-submit.** `injectText()` returns `false` if the user is actively typing
   (so the agent doesn't send the user's half-finished text). Callers must honor that return value before
   `triggerSend()`. Auto-submit can also be turned off in the popup (`autoSubmit:false`) — then the
   result is left in the composer **on purpose** for manual send.

Send selectors (in `triggerSend`): `button[aria-label="Send message"]`, `…[aria-label*="Send"]`,
`…[mattooltip*="Send"]`, `…[data-testid="send-button"]`, `button.send-button`, `…[aria-label*="send"]`.
Input selectors: `rich-textarea [contenteditable="true"]`, `[role="textbox"][contenteditable="true"]`,
`.ql-editor`, `textarea`.

> These selectors and the Quill/`pointer-events` facts are the **un-unit-testable** layer — re-verify
> them live whenever Google ships a UI change. Unit-test mocks will happily pass while the real page breaks.
