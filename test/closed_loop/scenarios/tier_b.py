"""Tier B: real Gemini multi-turn closed loop."""

from __future__ import annotations

import os
import tempfile
import time
import uuid

from ..gemini_ui import (
    ensure_fast_model,
    ensure_fresh_chat,
    send_until_action,
    wait_for_thread_marker,
)
from ..harness import (
    connect,
    evaluate,
    host_log_offset,
    log_step,
    reload_gemini_tab,
    set_agent_active,
)
from ..pipeline_assert import (
    PipelineFailure,
    TurnContext,
    assert_not_paused,
    assert_turn_complete,
    wait_cooldown,
)


_GEMINI_JSON_RULE = (
    "Gemini Local Agent is active. Respond with ONLY one json code block — "
    'valid JSON with an "action" field. No other text.'
)


def _prompt_shell(marker: str) -> str:
    return (
        f"{_GEMINI_JSON_RULE}\n"
        f'Execute now: {{"action":"run_shell","command":"echo {marker}"}}'
    )


def _prompt_write(path: str, content: str) -> str:
    return (
        f"{_GEMINI_JSON_RULE}\n"
        f'Execute now: {{"action":"write_file","filepath":"{path}","content":"{content}"}}'
    )


def _prompt_read(path: str) -> str:
    return (
        f"{_GEMINI_JSON_RULE}\n"
        f'Execute now: {{"action":"read_file","filepath":"{path}"}}'
    )


def _prepare_gemini_session(sess) -> None:
    # Do not reload the extension here — it kills the SW CDP session mid-flight.
    # Reload the Gemini tab so the content script is definitely injected on this target.
    log_step("prepare: reload_gemini_tab")
    reload_gemini_tab(sess)
    log_step("prepare: set_agent_active")
    set_agent_active(sess)
    # Faster turns for E2E (does not change committed CONFIG defaults)
    log_step("prepare: relax storage throttles for E2E")
    evaluate(
        sess.cdp,
        sess.sw_sess,
        "new Promise(r => chrome.storage.local.set({ cooldownSeconds: 2, maxPerMinute: 60, settlingSeconds: 0 }, r))",
        await_promise=True,
    )
    from ..gemini_ui import wait_composer_clear, wait_composer_ready, wait_gemini_idle

    log_step("prepare: ensure_fresh_chat")
    ensure_fresh_chat(sess)
    log_step("prepare: wait_gemini_idle")
    if not wait_gemini_idle(sess, timeout_s=60.0):
        reload_gemini_tab(sess)
        ensure_fresh_chat(sess)
        if not wait_gemini_idle(sess, timeout_s=60.0):
            raise PipelineFailure("setup", "Gemini still generating before session start")
    log_step("prepare: wait_composer_clear")
    if not wait_composer_clear(sess, timeout_s=60.0):
        raise PipelineFailure("setup", "composer not clear before session start")
    if not wait_composer_ready(sess, timeout_s=30.0):
        raise PipelineFailure("setup", "Gemini composer not ready after new chat")
    time.sleep(2)
    log_step("prepare: ensure_fast_model")
    model = ensure_fast_model(sess)
    if not model.get("ok"):
        raise PipelineFailure(
            "setup",
            f"select Flash or Thinking (not Pro) in Gemini UI: {model}",
        )

    log_step("prepare: session ready")


def run_shell_roundtrip(port: int) -> None:
    sess = connect(port)
    try:
        _prepare_gemini_session(sess)
        marker = f"gla_b1_{uuid.uuid4().hex[:8]}"
        offset = host_log_offset()
        prompt = _prompt_shell(marker)
        log_step(f"shell_roundtrip: turn1 send (marker={marker})")
        send_until_action(sess, prompt, marker, retries=3)
        ctx = TurnContext(marker=marker, host_log_offset=offset)
        log_step("shell_roundtrip: assert_turn_complete")
        assert_turn_complete(sess, ctx)
        print(f"PASS shell_roundtrip ({marker})")
    finally:
        sess.close()


def run_file_roundtrip(port: int) -> None:
    sess = connect(port)
    run_id = uuid.uuid4().hex[:8]
    path = os.path.join(tempfile.gettempdir(), f"gla_e2e_{run_id}.txt")
    content = f"gla_file_content_{run_id}"
    try:
        _prepare_gemini_session(sess)
        offset = host_log_offset()

        log_step(f"file_roundtrip: turn1 write ({path})")
        send_until_action(
            sess, _prompt_write(path, content), "write_file", retries=3,
            validate=lambda bs: any(run_id in (b.get("snippet") or "") for b in bs),
        )
        deadline = time.time() + 60.0
        while time.time() < deadline:
            from ..harness import host_log_tail

            if run_id in host_log_tail() and "write_file" in host_log_tail():
                break
            time.sleep(1.0)
        else:
            raise PipelineFailure("stage4", "write_file not seen in host log")
        if not wait_for_thread_marker(sess, "System Result", timeout_s=60.0):
            raise PipelineFailure("stage5", "write_file System Result missing")
        log_step("file_roundtrip: turn1 complete, cooldown before read")
        wait_cooldown(TurnContext(marker=run_id, host_log_offset=offset, cooldown_wait_s=6.0))
        from ..gemini_ui import wait_composer_clear

        deadline = time.time() + 120.0
        while time.time() < deadline:
            if wait_composer_clear(sess, timeout_s=8.0):
                break
            time.sleep(2.0)
        else:
            raise PipelineFailure("setup", "composer not clear before read send")
        time.sleep(3)

        offset2 = host_log_offset()
        log_step("file_roundtrip: turn2 read")
        send_until_action(sess, _prompt_read(path), "read_file", retries=3)
        from ..harness import host_exec_count

        deadline = time.time() + 60.0
        while time.time() < deadline:
            if host_exec_count("read_file", offset2) >= 1:
                break
            time.sleep(1.0)
        else:
            raise PipelineFailure("stage4", "read_file not executed by host")
        deadline = time.time() + 90.0
        while time.time() < deadline:
            if wait_for_thread_marker(sess, content, timeout_s=5.0, poll_s=1.0):
                break
            time.sleep(1.0)
        else:
            raise PipelineFailure("stage5", f"read output missing content {content}")
        print(f"PASS file_roundtrip ({path})")
    finally:
        sess.close()


def run_agent_chain(port: int) -> None:
    sess = connect(port)
    run_id = uuid.uuid4().hex[:8]
    path = os.path.join(tempfile.gettempdir(), f"gla_chain_{run_id}.txt")
    try:
        _prepare_gemini_session(sess)
        offset = host_log_offset()

        m1 = f"gla_chain_{run_id}"
        from ..gemini_ui import wait_composer_clear

        log_step(f"agent_chain: turn1 shell (marker={m1})")
        send_until_action(
            sess,
            f"{_GEMINI_JSON_RULE}\n"
            f'Execute now: {{"action":"run_shell","command":"uname -a | head -1 > {path} && echo {m1}"}}',
            m1, retries=3,
        )
        ctx1 = TurnContext(marker=m1, host_log_offset=offset, cooldown_wait_s=4.0)
        log_step("agent_chain: turn1 assert_turn_complete")
        assert_turn_complete(sess, ctx1)
        if not wait_for_thread_marker(sess, "System Result", timeout_s=30.0):
            raise PipelineFailure("stage5", "turn1 System Result missing")
        wait_cooldown(ctx1)
        deadline = time.time() + 120.0
        while time.time() < deadline:
            if wait_composer_clear(sess, timeout_s=8.0):
                break
            time.sleep(2.0)
        else:
            raise PipelineFailure("setup", "composer not clear before turn2 send")
        time.sleep(3)

        set_agent_active(sess)
        assert_not_paused(sess)
        # Turn 2: read file
        offset2 = host_log_offset()
        log_step("agent_chain: turn2 read")
        send_until_action(sess, _prompt_read(path), "read_file", retries=3)
        from ..harness import host_exec_count

        deadline = time.time() + 60.0
        while time.time() < deadline:
            if host_exec_count("read_file", offset2) >= 1:
                break
            time.sleep(1.0)
        else:
            raise PipelineFailure("stage4", "turn2 read_file not executed")
        set_agent_active(sess)
        assert_not_paused(sess)
        try:
            with open(path) as f:
                expected = f.read().strip()
        except OSError as exc:
            raise PipelineFailure("stage5", f"chain file missing after read gate: {exc}") from exc
        if "linux" not in expected.lower():
            raise PipelineFailure(
                "stage5",
                f"chain file missing uname output: {expected[:80]!r}",
            )
        needle = "GNU/Linux"
        deadline = time.time() + 120.0
        while time.time() < deadline:
            if wait_for_thread_marker(sess, needle, timeout_s=3.0, poll_s=1.0):
                break
            wait_composer_clear(sess, timeout_s=8.0)
            assert_not_paused(sess)
            time.sleep(1.0)
        else:
            raise PipelineFailure("stage5", "read turn did not return uname output")
        print(f"PASS agent_chain ({run_id})")
    finally:
        sess.close()


TIER_B = {
    "shell_roundtrip": run_shell_roundtrip,
    "file_roundtrip": run_file_roundtrip,
    "agent_chain": run_agent_chain,
}
