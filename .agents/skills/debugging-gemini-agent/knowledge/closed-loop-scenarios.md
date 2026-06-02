# Closed-loop scenario runner

Automated multi-turn tests live in `test/closed_loop/`. Run from repo root after
`npm run build` and `./scripts/launch-debug-brave.sh` (CDP **:9222**, one Gemini tab).

## CLI

```bash
python3 -m test.closed_loop.run --tier A          # fast pipeline regressions
python3 -m test.closed_loop.run --tier B          # real Gemini (login required)
python3 -m test.closed_loop.run --tier C          # rerun-latest product behavior
python3 -m test.closed_loop.run --scenario smoke
python3 -m test.closed_loop.run --list
```

npm aliases: `test:closed-loop`, `test:closed-loop:live`, `test:browser:smoke`.

## Tier A (no model)

| ID | Proves |
|----|--------|
| `smoke` | `e2e_browser.py` — SW, content script, connectNative |
| `loop_no_rerun` | One synthetic block → exactly one host execution (no re-scan loop) |
| `load_historical_skip` | JSON in DOM at content-script init → no auto-run |
| `synthetic_happy` | Post-load inject reaches host (wiring only; not load-time case) |
| `dom_audit` | No `"action"` nodes outside scanner selectors |

## Tier B (Gemini + GEM_PROMPT)

**Run inside the gem — this is mandatory for shell actions.** Set `GLA_GEM_ID` (the
debug profile's "Gemini Local Agent" gem id, e.g. `48811f87bd5f`) or `GLA_GEM_URL`
before running; `ensure_fresh_chat()` then opens threads under `…/gem/<id>` instead of
bare `…/app`. **Without it, `run_shell` scenarios get a false negative:** on bare Gemini
the model's safety layer refuses local-agent shell actions and emits
`{"action":"error","message":"shell execution disabled"}` (or `status:refused`) — *not* a
pipeline bug. The **same prompt under the gem emits the action cleanly and roundtrips to
the host** (verified live 2026-06-02). The gem delivers `GEM_PROMPT.md` as *system
instructions*, whose authority suppresses the refusal that an inline chat rule cannot.
Find the id at `gemini.google.com/gems/view` → the gem card's `/gem/<id>` link.

```bash
GLA_GEM_ID=48811f87bd5f python3 -m test.closed_loop.run --tier B
```

**Model:** use **Flash** or **Thinking**, not **Pro** — the harness calls `ensure_fast_model()` before
prompts (faster replies). The model choice does *not* substitute for the gem: Flash on bare
`/app` still refuses shell actions. If auto-select fails, pick Flash/Thinking manually, then re-run.

| ID | Turns | Actions |
|----|-------|---------|
| `shell_roundtrip` | 1 | `run_shell` with unique marker |
| `file_roundtrip` | 2 | `write_file` then `read_file` under `/tmp/gla_e2e_*` |
| `agent_chain` | 2 | shell writes file, read back |

Between turns the harness waits **16s** (cooldown) and asserts stages 3–5 via host log +
`System Result` in thread text (not composer-only).

## Tier C

| ID | Behavior |
|----|----------|
| `rerun_latest` | Historical block skipped; `postMessage({ __gla: 'rerun-latest' })` or popup **Rerun last action** runs the **last** JSON block once |

## Stage assertions (Tier B)

1. **Detect** — `pre code` / `code` with `"action"` in thread
2. **Guards** — not historical / dedup / paused for *new* blocks
3. **Route** — host log `Executing …`
4. **Execute** — marker in host log
5. **Inject+Send** — `System Result` + marker in `document.body.innerText`

## Composer driving (harness)

`gemini_ui.send_prompt()` writes the composer via Quill `setText(text,'user')` (the MAIN-world
`'user'`-source path that arms Send; execCommand is a fallback for the old UI) and polls Send
`pointer-events` (not `disabled`). See `live-browser-driving.md`.

**Turn/reply detection must be structural, not text.** Count `<model-response>` elements
(`gemini_ui._model_reply_count`), never scrape `"Gemini said"`: inside a gem the reply is
attributed `"<GemName> said"` (e.g. `"Gemini Local Agent said"`) — a `"Gemini said"` match never
increments, so every send falsely reads as "Gemini did not reply" (a stage-1 false negative that
*looks* like a model refusal but is a harness bug). Action-block detection (`pre code` + marker) is
already structural and gem-safe.

## Tab hygiene

- Reuse CDP `:9222`; do not launch a second Brave if the port is up.
- Exactly one `gemini.google.com` tab per run (`harness.close_extra_gemini_tabs`).

## Rerun latest (product)

Popup **Rerun last action** sends `{ type: 'RERUN_LATEST' }` to the content script. The harness uses
`window.postMessage({ __gla: 'rerun-latest' }, '*')`. Only the **last** valid action block in document
order is dispatched; older blocks in the thread are never auto-run.

## Reloading & observing the live extension (hard-won)

- **Rebuild ≠ reload. Brave caches the unpacked content script.** `npm run build` updates
  `.output/chrome-mv3/content-scripts/content.js`, but a running debug Brave keeps the OLD content
  script — `chrome.runtime.reload()` and hard page reloads (Page.reload / navigate / `location.href`) do
  **not** reliably pick up new content-script code. To load a content-script change you must **relaunch**:
  `pkill -f "user-data-dir=.*gla-debug-profile"`, wait for `:9222` to free, then
  `./scripts/launch-debug-brave.sh`. **Always prove the new build is live** (unique marker log, below)
  before trusting any "the fix didn't work" result.
- **Content-script logs are ISOLATED-world; the MCP only sees MAIN-world.** `brave-debug` MCP
  `evaluate_script`/`list_console_messages` run in / read the page MAIN world (hence they can touch
  `__quill`). To read the content script's `[Gemini Agent]` logs, capture via the harness CDP:
  `for evt in sess.cdp.drain_events(...): _console_text_from_event(evt)` on the page session. Add a
  temporary `info('[marker] …')` to triggerSend/handlers to confirm which build is running.
- **SW-context settings:** `autoSubmit`/cooldown/paused live in `chrome.storage.local`, readable only in
  the service worker — use `harness.read_storage(sess)` (evaluates in `sess.sw_sess`). `autoSubmit` unset
  ⇒ ON (`autoSubmit !== false`).

## False greens

Post-load synthetic `<pre><code>` injection does **not** prove load-time JSON on screen at refresh.
Use `load_historical_skip` and real Gemini turns for that.

**Stage-5 "System Result in `body.innerText`" passes on a STUCK composer.** The composer's text is part of
`document.body.innerText`, so an injected-but-**unsent** System Result satisfies a `body.innerText`
check — it cannot tell "auto-submitted into the thread" from "left armed in the composer." This is why
Tier B never caught the auto-submit stall (#18); the harness also sends each turn itself. Verify real
auto-submit only via a hands-off **autonomous chain** (seed once, all System Results self-submit), and
check the result became its **own turn** (a new `<user-query>`/`<model-response>`), not just present text.
