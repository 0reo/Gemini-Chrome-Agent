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

**Model:** use **Flash** or **Thinking**, not **Pro** — the harness calls `ensure_fast_model()` before
prompts (faster replies, fewer refusals on rigid JSON-only instructions). If auto-select fails, pick
Flash/Thinking manually in the Gemini model menu, then re-run.

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

`gemini_ui.send_prompt()` uses Quill `execCommand('insertText')`, `InputEvent('input')`, and polls Send
`pointer-events` (not `disabled`). See `live-browser-driving.md`.

## Tab hygiene

- Reuse CDP `:9222`; do not launch a second Brave if the port is up.
- Exactly one `gemini.google.com` tab per run (`harness.close_extra_gemini_tabs`).

## Rerun latest (product)

Popup **Rerun last action** sends `{ type: 'RERUN_LATEST' }` to the content script. The harness uses
`window.postMessage({ __gla: 'rerun-latest' }, '*')`. Only the **last** valid action block in document
order is dispatched; older blocks in the thread are never auto-run.

## False greens

Post-load synthetic `<pre><code>` injection does **not** prove load-time JSON on screen at refresh.
Use `load_historical_skip` and real Gemini turns for that.
