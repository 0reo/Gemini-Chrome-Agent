---
phase: 01
title: Trustworthy closed-loop Tier B — prove the multi-turn Gemini agent loop
wave_plan:
  - wave: 1   # assertion + harness correctness (parallel-safe; all in test/closed_loop/)
    tasks: [T1, T2, T3, T4, T5, T6]
  - wave: 2   # live verification (depends on wave 1)
    tasks: [T7]
files_modified:
  - test/closed_loop/scenarios/tier_b.py
  - test/closed_loop/scenarios/rerun_latest.py
  - test/closed_loop/pipeline_assert.py
  - test/closed_loop/gemini_ui.py
  - test/closed_loop/harness.py
autonomous: false   # T7 needs a logged-in live Gemini (Smart Mode approval likely)
requirements:
  - REQ-TB1: every per-turn Tier B/C assertion proves real execution via a host-log offset gate, never a needle present before the turn ran
  - REQ-TB2: the harness raises on CDP/reload/attach failures instead of swallowing them
  - REQ-TB3: rerun-latest fires exactly one channel and can report failure
  - REQ-TB4: `--tier B` passes against real Gemini with captured per-turn evidence, assertions UNWEAKENED
---

# Phase 01 — Trustworthy closed-loop Tier B

## Why this exists (read before starting)

A review found that Cursor's `--tier B` "3/3 passed" is largely a **false green**. Only
`shell_roundtrip` (single-turn, fresh chat, host-log gate) is soundly asserted. The two multi-turn
scenarios — the actual "Gemini reads files / chains turns" behavior — assert on markers that are
**already in the thread from turn 1**, so they pass even if the read turn never executes. The harness
also swallows CDP/reload errors and the rerun test double-fires. Net: the multi-turn loop is *unproven*,
and a test claims to cover it but cannot fail.

**The fix principle (apply everywhere):** a turn's success is proven by the **native host log**, gated by
an offset captured *immediately before that turn's prompt is sent* (`host_exec_count(<action-or-marker>,
offset) >= 1`). A thread/DOM check may only use a needle that can **only** exist as output of the action
(host-produced text), never an echo of the prompt and never a generic string like `System Result` that a
prior turn already produced.

## HARD CONSTRAINTS — do not violate (AGENTS.md)

- **Do NOT weaken any extension safety guard** (cooldown `COOLDOWN_MS`, rate-limit `MAX_PER_MINUTE`
  auto-pause, settling, dedup, `blocksPresentAtLoad`, `executedBlocks`) and **do NOT lower their committed
  defaults in `utils/config.ts`** to make a test pass. Relax throttling for a test run via **storage only**
  (`chrome.storage.local.set({cooldownSeconds, maxPerMinute, settlingSeconds})`), then restore.
- **Do NOT make an assertion pass by removing the check.** If a scenario fails, fix the harness or the
  extension so the real pipeline works — a deliberately broken pipeline MUST still make Tier B FAIL.
- Touch only the files in `files_modified`. The extension code (`entrypoints/`, `utils/`) is out of scope
  except for genuine pipeline bugs surfaced by a now-honest test (raise it before changing it).

---

## Workflow & GitLab discipline (MANDATORY — commit as you go, do NOT batch)

This work is tracked by **#15** (harness false-greens / swallowed errors) and **#7** (verify Tier B
end-to-end). Do not repeat the one-giant-commit mistake from the prior session.

- **Prereq:** ensure `wxt-migration` is pushed to `origin` first (local is currently ahead) so the branch
  and MR have the correct base.
- **Branch:** create `fix/trustworthy-tier-b` off `wxt-migration`. Open a **Draft merge request targeting
  `wxt-migration`** at the first push, so review happens incrementally. (It reaches `master` later via the
  existing integration MR !1.)
- **One logical commit per task** (T1–T7), pushed as you finish each — never a single squash at the end.
  Each commit keeps the tree green for what it touches (`npm run compile` clean). Suggested messages
  (reference the issue every time):
  - T1 `fix(test): gate file_roundtrip read turn on host log, not stale prompt echo (Refs #15)`
  - T2 `fix(test): require real read execution in agent_chain turn 2 (Refs #15)`
  - T3 `fix(test): turn-scope assert_turn_complete stage-5 via host-log offset (Refs #15)`
  - T4 `fix(test): single-channel rerun trigger with reportable failure (Refs #15)`
  - T5 `fix(test): stop swallowing CDP/reload/attach errors; fix host-log offset (Refs #15)`
  - T6 `fix(test): honor idle/composer-clear waits before sends (Refs #15)`
  - T7 `test: verify Tier B multi-turn loop end-to-end against live Gemini (Closes #15, Closes #7)`
- **Work items:** link #15 and #7 in the MR description. Keep `Refs #N` (non-closing) on the wave-1
  commits so the issues stay open until the loop is *actually proven*; only T7 (or the MR) uses
  `Closes #15` / `Closes #7`.
- **Review discussion:** for T7, **post the captured per-turn evidence** (host-log marker lines + System
  Result snippets) as an MR comment so the live result is reviewable, not merely asserted. Request review,
  respond to threads, and resolve them before marking the MR ready.
- If any task surfaces a genuine *extension* bug (not a test bug), file a new GitLab issue for it and
  reference it — don't silently fix outside `files_modified`.

---

## Wave 1 — make the assertions and harness honest

### T1 — Fix `file_roundtrip` read-turn false-green
<read_first>
- test/closed_loop/scenarios/tier_b.py  (run_file_roundtrip, ~lines 121-163)
- test/closed_loop/harness.py  (host_exec_count L227, host_log_tail L216)
- test/closed_loop/gemini_ui.py  (wait_for_action_codeblock L376)
</read_first>
<action>
In `run_file_roundtrip`, the read turn currently does:
`wait_for_action_codeblock(sess, "read_file", ...)` (return discarded) then
`wait_for_thread_marker(sess, content, ...)` — but `content` (`gla_file_content_<run_id>`) is already in
the thread from the turn-1 write prompt, so it passes unconditionally. Replace the read-turn verification
(the block after `offset2 = _host_offset()` and `send_prompt(... _prompt_read ...)`) with:
1. `blocks2 = wait_for_action_codeblock(sess, "read_file", timeout_s=120.0)` and
   `if not blocks2: raise PipelineFailure("stage1", "read_file JSON block not emitted")`.
2. A host-log gate bound to `offset2`: poll up to 60s until
   `host_exec_count("read_file", offset2) >= 1`; on timeout
   `raise PipelineFailure("stage4", "read_file not executed by host")`.
3. A result needle that only the read can produce: assert the file's content appears in the thread AFTER
   the read executed — poll `wait_for_thread_marker(sess, content, timeout_s=30.0)` ONLY after the stage-4
   gate has passed (so the gate, not the stale prompt echo, is what proves execution). Keep the
   `content` thread check as a secondary signal, never the sole gate.
Do not remove the existing turn-1 write-turn host-log gate (it is already correct).
</action>
<acceptance_criteria>
- `grep -n 'host_exec_count("read_file", offset2)' test/closed_loop/scenarios/tier_b.py` → match
- `grep -n 'if not blocks2' test/closed_loop/scenarios/tier_b.py` → match (codeblock return checked)
- In run_file_roundtrip, `wait_for_thread_marker(sess, content` is no longer the only post-read assertion
  (a `PipelineFailure("stage4"` for read_file precedes it) — verify by reading the function
- `python3 -m test.closed_loop.run --scenario file_roundtrip` still PASSES on a working pipeline (run in T7)
</acceptance_criteria>

### T2 — Fix `agent_chain` turn-2 false-green (remove the stale "System Result" fallback)
<read_first>
- test/closed_loop/scenarios/tier_b.py  (run_agent_chain, ~lines 166-205)
- test/closed_loop/harness.py  (host_exec_count, host_log_tail)
</read_first>
<action>
In `run_agent_chain` turn 2, the code does `wait_for_action_codeblock(sess, "read_file", ...)` (return
discarded), then `wait_for_thread_marker(sess, "Linux", ...)` with a fallback to
`wait_for_thread_marker(sess, "System Result", ...)`. The "System Result" fallback always passes (turn 1
already produced one). Replace turn-2 verification with:
1. `blocks2 = wait_for_action_codeblock(sess, "read_file", timeout_s=120.0)`;
   `if not blocks2: raise PipelineFailure("stage1", "turn2 read_file JSON missing")`.
2. host-log gate on `offset2`: poll until `host_exec_count("read_file", offset2) >= 1` else
   `raise PipelineFailure("stage4", "turn2 read_file not executed")`.
3. Require the uname output as the read result: `if not wait_for_thread_marker(sess, "Linux",
   timeout_s=60.0): raise PipelineFailure("stage5", "read turn did not return uname output")`.
**Delete the `"System Result"` fallback entirely.**
</action>
<acceptance_criteria>
- `run_agent_chain` in tier_b.py contains NO `wait_for_thread_marker(sess, "System Result"` — verify
  `grep -n 'wait_for_thread_marker(sess, "System Result"' test/closed_loop/scenarios/tier_b.py` → no match
- `grep -n 'host_exec_count("read_file", offset2)' test/closed_loop/scenarios/tier_b.py` → match (now 2, with T1)
- turn-2 codeblock return is checked (`if not blocks2` present in run_agent_chain)
</acceptance_criteria>

### T3 — Make `assert_turn_complete` stage-5 turn-scoped (kill thread contamination)
<read_first>
- test/closed_loop/pipeline_assert.py  (TurnContext L14, assert_turn_complete L33-71)
- test/closed_loop/harness.py  (host_exec_count, host_log_tail)
</read_first>
<action>
`assert_turn_complete` stage 5 currently passes when `document.body.innerText` contains both
`"System Result"` and `ctx.marker` — both can be present from a prior turn in a multi-turn thread. Make
the primary proof the host log, not the DOM:
1. Add stage-4 gating inside `assert_turn_complete`: require
   `host_exec_count(ctx.marker, ctx.host_log_offset) >= 1` (poll with timeout) before stage 5; raise
   `PipelineFailure("stage4", ...)` on timeout.
2. Stage 5 must require `ctx.marker` (per-run unique) in the thread — keep the marker check, but DROP the
   reliance on the generic `'System Result'` substring as proof (it is satisfied by any earlier turn).
   The unique marker appearing in the thread *after* the stage-4 host gate is the sound signal.
</action>
<acceptance_criteria>
- `assert_turn_complete` calls `host_exec_count(ctx.marker, ctx.host_log_offset)` —
  `grep -n 'host_exec_count(ctx.marker, ctx.host_log_offset)' test/closed_loop/pipeline_assert.py` → match
- stage-5 no longer treats a bare `'System Result'` presence as sufficient proof (verify by reading: the
  raise path requires the host gate to have passed first)
- `TurnContext` carries `host_log_offset` (already present) and it is used in the gate
</acceptance_criteria>

### T4 — `rerun_latest`: single trigger channel + reportable failure
<read_first>
- test/closed_loop/gemini_ui.py  (trigger_rerun_latest L14-38)
- test/closed_loop/scenarios/rerun_latest.py  (run_rerun_latest)
- entrypoints/content.ts  (RERUN_LATEST + __gla:'rerun-latest' listeners — read only, do not change)
</read_first>
<action>
`trigger_rerun_latest` currently fires BOTH `window.postMessage({__gla:'rerun-latest'})` AND
`chrome.tabs.sendMessage({type:'RERUN_LATEST'})`, and every JS path resolves `{ok:true}` (it discards
`chrome.runtime.lastError`). Two problems: (a) the content script's two listeners both call
`rerunLatestAction()`, so the "no extra execution" assertion in `run_rerun_latest` cannot distinguish one
fire from two; (b) the trigger can never report failure. Fix:
1. Use ONE channel only — `window.postMessage({ __gla: 'rerun-latest' }, '*')`. Remove the
   `chrome.tabs.sendMessage` path.
2. Make failure reportable: if the page eval throws or returns nothing, return `{"ok": false, ...}` and in
   `run_rerun_latest` `raise PipelineFailure("trigger", ...)` when `not ret.get("ok")`.
</action>
<acceptance_criteria>
- `grep -n 'chrome.tabs.sendMessage' test/closed_loop/gemini_ui.py` → no match (single channel)
- `grep -n '"ok": false' test/closed_loop/gemini_ui.py` → match (failure reportable)
- `run_rerun_latest` raises on trigger failure — `grep -n 'PipelineFailure' test/closed_loop/scenarios/rerun_latest.py` → match
- the no-extra-execution assertion still uses a host-log offset gate (`assert_single_host_execution` / `host_exec_count`)
</acceptance_criteria>

### T5 — Stop swallowing CDP/reload/attach errors in the harness
<read_first>
- test/closed_loop/harness.py  (reconnect_gemini_page L116, reload_extension L129, reload_gemini_tab L184, host_exec_count L227)
</read_first>
<action>
1. `reload_extension` (L129) and `reload_gemini_tab` (L184): replace `except Exception: pass` around
   `cdp.recv(...)` with: catch ONLY the expected timeout/disconnect (e.g. `except RuntimeError as e:` and
   re-raise unless `str(e)` matches `timed out`/`timeout`/`disconnect`/`closed`). Any other exception must
   propagate.
2. `reconnect_gemini_page` (L116): if `attach_to_target(...)` returns `None`,
   `raise RuntimeError("reconnect_gemini_page: attach_to_target returned None (stale session)")` instead of
   silently leaving `sess.page_sess` pointing at the dead session.
3. `host_exec_count` (L227): the offset is a **character** index into the decoded log string, but callers
   pass `os.path.getsize()` (a **byte** count). Make offsets character-based: capture the offset as
   `len(open(LOG).read())` (or have a single `_host_offset()` helper do so) and slice
   `text[after_index:]` consistently. Fix `_host_offset()` in tier_b.py too if it uses `getsize`.
</action>
<acceptance_criteria>
- `grep -nA2 'def reload_extension' test/closed_loop/harness.py` shows NO `except Exception:\n        pass`
  (specific exception + re-raise instead); same for `reload_gemini_tab`
- `grep -n 'reconnect_gemini_page: attach' test/closed_loop/harness.py` → match (raises on None)
- the host-log offset is character-based: `grep -n 'os.path.getsize' test/closed_loop/harness.py test/closed_loop/scenarios/tier_b.py` → no match used as a log offset (or replaced by `len(...read())`)
</acceptance_criteria>

### T6 — Honor `wait_gemini_idle` / `wait_composer_clear` return values
<read_first>
- test/closed_loop/scenarios/tier_b.py  (call sites of wait_gemini_idle / wait_composer_clear)
- test/closed_loop/gemini_ui.py  (wait_gemini_idle L142, wait_composer_clear L182 — both return bool)
</read_first>
<action>
At every call site in `_prepare_gemini_session`, `run_file_roundtrip`, and `run_agent_chain`, both
`wait_gemini_idle(...)` and `wait_composer_clear(...)` currently discard their `False`-on-timeout return.
Bind and check each: `if not wait_gemini_idle(sess, ...): raise PipelineFailure("setup", "Gemini still
generating before next send")` and likewise for `wait_composer_clear` ("composer not clear before next
send"). A dirty composer can re-dispatch stale JSON and cause a false green.
</action>
<acceptance_criteria>
- `grep -nc 'if not wait_gemini_idle(' test/closed_loop/scenarios/tier_b.py` → ≥ 1
- `grep -nc 'if not wait_composer_clear(' test/closed_loop/scenarios/tier_b.py` → ≥ 1
- no bare `wait_gemini_idle(sess` / `wait_composer_clear(sess` statement-line remains unguarded in tier_b.py
</acceptance_criteria>

---

## Wave 2 — prove it for real

### T7 — Run Tier B against real Gemini and confirm a GENUINE pass  (autonomous: false)
<read_first>
- .agents/skills/debugging-gemini-agent/knowledge/closed-loop-scenarios.md
- .agents/skills/debugging-gemini-agent/knowledge/live-browser-driving.md  (tab hygiene, send mechanics)
- docs/GEM_PROMPT.md  (the gem must emit one action JSON per turn and continue from System Result)
</read_first>
<action>
Pre-flight: ensure ONE debug Brave is up on CDP :9222 (if `curl -s http://127.0.0.1:9222/json/version`
fails, run `./scripts/launch-debug-brave.sh`), logged into Google, ONE Gemini tab, agent active
(`isAgentPaused:false`), and the gem/Flash-or-Thinking model selected (Tier B prefers Flash/Thinking, not
Pro). Then `npm run build`. Run, in order:
- `python3 -m test.closed_loop.run --tier A`   (must stay 5/5)
- `python3 -m test.closed_loop.run --scenario rerun_latest`   (Tier C)
- `python3 -m test.closed_loop.run --tier B`   (shell_roundtrip, file_roundtrip, agent_chain)
For EACH Tier B turn, capture the evidence in the run output / `tail /tmp/gemini_host.log`: the host log
`Executing ...` line with the per-turn marker AND the new `System Result:` appearing in the thread. All
three Tier B scenarios must PASS with the now-honest (T1–T3) assertions. If a scenario fails, fix the
harness driving or a genuine extension bug (raise it first) and re-run — DO NOT weaken the assertions or
the guards to force green. If live network is blocked (Smart Mode), request approval; if it cannot be
granted, STOP and report exactly which scenario/turn is unverified and why (do not claim a pass you did
not observe).
</action>
<acceptance_criteria>
- `npm run compile` exits 0; `npm run test` (vitest) is 50/50
- `python3 -m test.closed_loop.run --tier A` exits 0 (5/5)
- `python3 -m test.closed_loop.run --tier B` exits 0 and prints PASS for shell_roundtrip, file_roundtrip,
  AND agent_chain
- the run captured, per Tier B turn, a host-log marker line + a System Result in the thread (paste the
  evidence into the work summary)
- assertions were NOT weakened (the T1–T6 acceptance_criteria still hold) and no extension guard / config
  default was changed
</acceptance_criteria>

---

## must_haves (goal-backward verification)

- [ ] No Tier B/Tier C assertion can pass on a needle that exists *before* the turn executes — every
      per-turn proof is a `host_exec_count(<marker>, offset) >= 1` gate plus a post-execution output needle.
- [ ] `agent_chain` and `file_roundtrip` read turns FAIL if `read_file` does not actually execute
      (the old stale-needle/fallback shortcuts are gone).
- [ ] The harness raises (never silently swallows) on `Page.reload`/SW-reload/attach failures.
- [ ] `trigger_rerun_latest` fires exactly one channel and can return `ok:false`; the Tier C scenario
      raises on trigger failure.
- [ ] `--tier B` passes against real Gemini with per-turn host-log + System Result evidence pasted into the
      summary, with every assertion UNWEAKENED and no extension guard/config default changed.
- [ ] `npm run compile` 0, `npm run test` 50/50, `--tier A` 5/5 all still green.

## Verification (run at the end)
```bash
npm run compile && npm run test            # tsc clean + vitest 50/50
python3 -m test.closed_loop.run --tier A   # 5/5
python3 -m test.closed_loop.run --scenario rerun_latest
python3 -m test.closed_loop.run --tier B   # 3/3, with captured per-turn evidence
git diff --stat utils/config.ts entrypoints/  # MUST be empty (no guard/default changes)
```
