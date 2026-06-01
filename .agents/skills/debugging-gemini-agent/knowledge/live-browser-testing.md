# Closed-loop end-to-end test plan

Goal: prove the **whole agent loop** works — a multi-stage back-and-forth where Gemini emits an action,
the extension executes it, the result is injected + auto-sent, and Gemini *consumes that result and emits
the next action* — across several turns and several action types. "A synthetic block executed once" is
**not** this test and must never be reported as if it were (that false green is the recurring failure).

> Companion: `live-browser-driving.md` is the *mechanics* (launch, attach, probes, tab hygiene). This
> file is the *scenario plan*. Run the loop on **one** debug Brave + **one** Gemini tab (reuse, never
> spawn — see Tab & window hygiene), agent **active** (`isAgentPaused:false`), auto-submit **on**.

## Watch all four surfaces at once (a turn is only "done" when they agree)
- Page DevTools console (Gemini tab): `[Gemini Agent] Executing action` + `scan complete {withAction,executed}`
- Service-worker console: `[Background]` routing
- `tail -f /tmp/gemini_host.log`: `message received {action,id}` + the result
- Live DOM: a new `System Result:` turn (auto-sent), composer cleared, `.ql-editor` lost `ql-blank`

## Timing traps that make a WORKING loop look broken (rule these out before "it's broken")
These are the most likely reasons a multi-stage loop stalls — none are detection/inject bugs:
- **Cooldown 15 s (`COOLDOWN_MS`)** — after each executed action, scans are skipped for 15 s. If Gemini
  emits the next action quickly, it sits unscanned until cooldown ends. A loop that "pauses between
  steps" is usually this. For testing, lower `COOLDOWN_MS` (e.g. 2000) in `utils/config.ts` or pace turns.
- **Rate limit 5/min (`MAX_PER_MINUTE`)** — the 6th action in a minute **auto-pauses** the agent
  (`isAgentPaused:true`, console `Auto-pausing`). A loop that "dies after ~5 steps" is this. Raise it for
  multi-step tests, and read storage to confirm (don't guess).
- **Dedup 60 s (`PAYLOAD_TTL_MS`)** — an identical action (same fields) within 60 s is dropped. Make each
  turn's command distinct (or expect the skip).
- **Settling 5 s + historical-block skip** — anything in the DOM at script load never runs. Do **not**
  reload the tab mid-loop; if you must, wait out settling and re-prompt.

### Relax throttling for testing — at runtime, NEVER by editing committed defaults
`content.ts` `loadSettings()` reads `cooldownSeconds` / `maxPerMinute` / `settlingSeconds` from
`storage.local` and applies them over the `CONFIG` defaults (live, via `storage.onChanged`; also the
popup sliders). So a multi-stage test can run without the 15 s cooldown / 5-per-minute pause throttling it
— **without touching `utils/config.ts`**. Do NOT lower the committed defaults: they are the anti-runaway
guard for real use (Gemini's own output re-triggering actions). Instead, from the **service-worker**
context:
```js
// loosen for a test run
chrome.storage.local.set({ cooldownSeconds: 2, maxPerMinute: 60, settlingSeconds: 2 });
// restore real guards when done
chrome.storage.local.remove(['cooldownSeconds','maxPerMinute','settlingSeconds']);
```
If you *can't* relax them, pace turns: wait > 15 s between actions and keep the chain ≤ 5 actions/min, or
a real, working loop will look broken.

## The scenario — a real read→compute→write→verify task (6 chained turns)
Drive Gemini (via gem prompt that emits exactly one action JSON per turn and continues from each
`System Result:`) through a task that exercises the loop end-to-end, e.g.:

| Turn | Action | Example | Pass evidence |
|------|--------|---------|---------------|
| 1 | `run_shell` | `ls` the repo root | host log + `System Result:` listing auto-sent; Gemini emits turn 2 |
| 2 | `read_file` | read a known file | file contents injected + sent; Gemini reacts |
| 3 | `run_python` | compute from that content | python output injected + sent |
| 4 | `write_file` | write a result file | success result; file exists on disk |
| 5 | `git_diff` | show the change | diff injected + sent |
| 6 | `attach_files` | attach the written file | file uploaded into Gemini's composer |

The loop **passes** only if all six chain with no manual nudging beyond cooldown pacing, no rate-limit
pause within the step count, and each `System Result:` is both auto-sent **and consumed** by Gemini's
next turn.

## Gemini model for closed-loop / multi-turn tests

Use **Flash** or **Thinking**, not **Pro** — Pro is slower and more likely to add prose around JSON.
The closed-loop harness (`test/closed_loop/gemini_ui.ensure_fast_model`) tries to select Flash/Thinking
via the model menu before Tier B scenarios; pick it manually if the UI changed.

## Two ways to drive it
- **Manual (truest):** paste a prompt that makes Gemini emit the turn-1 JSON, then watch it chain live.
  This is the only way to see real Gemini renderer + real model continuation behavior.
- **Scripted (CDP), repeatable:** extend `test/live_browser_agent.py` — per turn: inject the *user-side*
  prompt into the composer (`execCommand('insertText')` then dispatch an `input` event to arm Send →
  `triggerSend`), wait for Gemini's action block, then assert host-log + injected `System Result:` before
  advancing. Count host executions per marker to catch re-fire loops (cf. `loop_dedup_browser.py`).

## Localize the break (when "the whole thing" fails)
- **Stalls after turn N** → cooldown / rate-limit first (read storage `isAgentPaused`; console
  `scan skipped` / `Auto-pausing`). This is the most common "multi-stage broken."
- **Action ran, but Gemini didn't continue** → the `System Result:` was injected + sent, but the model
  didn't emit the next action → **gem-prompt / model behavior, not the extension.** Confirm the result is
  a real sent turn (`document.body.innerText`), then look at `docs/GEM_PROMPT.md`, not the pipeline.
- **Action never ran** → walk the pipeline backward with `scripts/diagnose.py` and the SKILL decision tree.
- **Works synthetically, fails on real Gemini** → inspect the real code-block node (renderer split /
  inline / streaming): `[...document.querySelectorAll('pre code, code')].map(n=>n.textContent.slice(0,80))`.

## Definition of done
A full multi-turn task (≥ the 6 turns above, mixing ≥4 action types) completes end-to-end against **real**
Gemini, every `System Result:` auto-sent and consumed, no manual intervention beyond cooldown pacing, no
unintended rate-limit pause — verified by host-log + DOM evidence at each turn, not by the composer alone.
