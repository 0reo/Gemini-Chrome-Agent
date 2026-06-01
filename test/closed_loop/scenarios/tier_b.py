"""Tier B: real Gemini multi-turn closed loop."""

from __future__ import annotations

import os
import tempfile
import time
import uuid

from ..gemini_ui import (
    click_new_chat,
    ensure_fast_model,
    prompt_visible_in_thread,
    send_prompt,
    wait_for_action_codeblock,
    wait_for_thread_marker,
)
from ..harness import (
    connect,
    evaluate,
    reload_gemini_tab,
    set_agent_active,
)
from ..pipeline_assert import (
    PipelineFailure,
    TurnContext,
    assert_turn_complete,
    wait_cooldown,
)


def _host_offset() -> int:
    try:
        return os.path.getsize("/tmp/gemini_host.log")
    except OSError:
        return 0


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
    reload_gemini_tab(sess)
    set_agent_active(sess)
    # Faster turns for E2E (does not change committed CONFIG defaults)
    evaluate(
        sess.cdp,
        sess.sw_sess,
        "new Promise(r => chrome.storage.local.set({ cooldownSeconds: 2, maxPerMinute: 60, settlingSeconds: 0 }, r))",
        await_promise=True,
    )
    from ..gemini_ui import wait_composer_ready, wait_gemini_idle

    click_new_chat(sess)
    wait_gemini_idle(sess)
    if not wait_composer_ready(sess, timeout_s=30.0):
        raise PipelineFailure("setup", "Gemini composer not ready after new chat")
    time.sleep(2)
    model = ensure_fast_model(sess)
    if not model.get("ok"):
        raise PipelineFailure(
            "setup",
            f"select Flash or Thinking (not Pro) in Gemini UI: {model}",
        )


def run_shell_roundtrip(port: int) -> None:
    sess = connect(port)
    try:
        _prepare_gemini_session(sess)
        marker = f"gla_b1_{uuid.uuid4().hex[:8]}"
        offset = _host_offset()
        prompt = _prompt_shell(marker)
        from ..gemini_ui import _gemini_said_count, wait_for_gemini_reply

        baseline = _gemini_said_count(sess)
        sent = send_prompt(sess, prompt, timeout_s=45.0)
        if not sent.get("sent"):
            raise PipelineFailure("setup", f"could not send prompt: {sent}")

        if not wait_for_gemini_reply(sess, timeout_s=120.0, baseline_said=baseline):
            raise PipelineFailure("stage1", "Gemini did not start a reply")
        blocks = wait_for_action_codeblock(sess, marker, timeout_s=300.0)
        if not blocks:
            raise PipelineFailure(
                "stage1",
                f"Gemini did not emit action JSON with marker {marker}",
            )
        ctx = TurnContext(marker=marker, host_log_offset=offset)
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
        offset = _host_offset()

        sent1 = send_prompt(sess, _prompt_write(path, content), timeout_s=45.0)
        if not sent1.get("sent"):
            raise PipelineFailure("setup", f"write prompt not sent: {sent1}")
        blocks = wait_for_action_codeblock(sess, "write_file", timeout_s=180.0)
        if not blocks or not any(run_id in (b.get("snippet") or "") for b in blocks):
            raise PipelineFailure("stage1", "write_file JSON block not emitted")
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
        wait_cooldown(TurnContext(marker=run_id, host_log_offset=offset))
        from ..gemini_ui import wait_composer_clear, wait_gemini_idle

        wait_gemini_idle(sess, timeout_s=45.0)
        wait_composer_clear(sess)

        offset2 = _host_offset()
        sent2 = send_prompt(sess, _prompt_read(path), timeout_s=45.0)
        if not sent2.get("sent"):
            raise PipelineFailure("setup", f"read prompt not sent: {sent2}")
        blocks2 = wait_for_action_codeblock(sess, "read_file", timeout_s=120.0)
        if not blocks2:
            raise PipelineFailure("stage1", "read_file JSON block not emitted")
        from ..harness import host_exec_count

        deadline = time.time() + 60.0
        while time.time() < deadline:
            if host_exec_count("read_file", offset2) >= 1:
                break
            time.sleep(1.0)
        else:
            raise PipelineFailure("stage4", "read_file not executed by host")
        if not wait_for_thread_marker(sess, content, timeout_s=30.0):
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
        offset = _host_offset()

        m1 = f"gla_chain_{run_id}"
        sent = send_prompt(
            sess,
            f'Reply with ONLY a json code block: {{"action":"run_shell","command":"uname -a | head -1 > {path} && echo {m1}"}}',
            timeout_s=45.0,
        )
        if not sent.get("sent"):
            raise PipelineFailure("setup", "turn1 send failed")
        blocks = wait_for_action_codeblock(sess, m1, timeout_s=180.0)
        if not blocks:
            raise PipelineFailure("stage1", f"turn1 JSON missing marker {m1}")
        ctx1 = TurnContext(marker=m1, host_log_offset=offset)
        assert_turn_complete(sess, ctx1)
        wait_cooldown(ctx1)
        from ..gemini_ui import wait_composer_clear, wait_gemini_idle

        wait_gemini_idle(sess, timeout_s=45.0)
        wait_composer_clear(sess)

        # Turn 2: read file
        offset2 = _host_offset()
        sent2 = send_prompt(sess, _prompt_read(path), timeout_s=45.0)
        if not sent2.get("sent"):
            raise PipelineFailure("setup", "turn2 send failed")
        wait_for_action_codeblock(sess, "read_file", timeout_s=120.0)
        if not wait_for_thread_marker(sess, "Linux", timeout_s=90.0):
            # fallback: any non-empty read result
            if not wait_for_thread_marker(sess, "System Result", timeout_s=30.0):
                raise PipelineFailure("stage5", "read turn did not return System Result")
        print(f"PASS agent_chain ({run_id})")
    finally:
        sess.close()


TIER_B = {
    "shell_roundtrip": run_shell_roundtrip,
    "file_roundtrip": run_file_roundtrip,
    "agent_chain": run_agent_chain,
}
