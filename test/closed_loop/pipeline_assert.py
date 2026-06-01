"""Per-stage pipeline assertions (runtime evidence)."""

from __future__ import annotations

import time
from dataclasses import dataclass

from . import harness as h
from .gemini_ui import stage5_probe
from .harness import BrowserSession, DEFAULT_COOLDOWN_WAIT_S, host_exec_count, host_log_tail, log_step


@dataclass
class TurnContext:
    marker: str
    host_log_offset: int = 0
    cooldown_wait_s: float = 4.0


class PipelineFailure(Exception):
    def __init__(self, stage: str, detail: str):
        super().__init__(f"[{stage}] {detail}")
        self.stage = stage
        self.detail = detail


def assert_not_paused(sess: BrowserSession) -> None:
    storage = h.read_storage(sess)
    if storage.get("isAgentPaused") is True:
        raise PipelineFailure("stage2", f"agent is paused: {storage}")


def assert_turn_complete(sess: BrowserSession, ctx: TurnContext) -> None:
    """Assert stages 3–5 for a turn identified by shell command marker."""
    assert_not_paused(sess)

    deadline = time.time() + 90.0
    host_ok = False
    while time.time() < deadline:
        if host_exec_count(ctx.marker, ctx.host_log_offset) >= 1:
            host_ok = True
            break
        time.sleep(1.0)
    if not host_ok:
        tail = host_log_tail(ctx.marker)
        raise PipelineFailure(
            "stage4",
            f"host never executed command containing '{ctx.marker}'. log:\n{tail[:500]}",
        )
    log_step(f"assert_turn_complete: stage4 host executed marker {ctx.marker!r}")

    # stage 5: per-turn marker in thread (after host gate — not generic System Result)
    deadline = time.time() + 30.0
    while time.time() < deadline:
        r = h.page_eval(
            sess,
            f"""(() => {{
              const t = document.body.innerText;
              return t.includes({__import__('json').dumps(ctx.marker)});
            }})()""",
        )
        if r.get("value"):
            log_step(f"assert_turn_complete: stage5 thread has marker {ctx.marker!r}")
            return
        time.sleep(1.0)

    probe = stage5_probe(sess)
    raise PipelineFailure(
        "stage5",
        f"thread missing marker '{ctx.marker}' after host execution: {probe}",
    )


def wait_cooldown(ctx: TurnContext) -> None:
    time.sleep(ctx.cooldown_wait_s)


def assert_single_host_execution(
    sess: BrowserSession,
    command_substring: str,
    host_offset: int,
    wait_after_first_s: float = 20.0,
) -> None:
    """Tier A2: exactly one execution, none after cooldown window."""
    deadline = time.time() + 15.0
    first = 0
    while time.time() < deadline:
        first = host_exec_count(command_substring, host_offset)
        if first >= 1:
            break
        time.sleep(1.0)
    if first < 1:
        raise PipelineFailure("stage4", f"no execution for {command_substring}")

    time.sleep(wait_after_first_s)
    after = host_exec_count(command_substring, host_offset)
    if after > first:
        raise PipelineFailure(
            "stage2",
            f"loop detected: {first} -> {after} executions of {command_substring}",
        )
