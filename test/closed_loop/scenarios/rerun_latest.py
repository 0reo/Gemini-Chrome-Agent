"""Tier C: rerun latest action block only."""

from __future__ import annotations

import os
import time

from ..gemini_ui import trigger_rerun_latest
from ..harness import (
    connect,
    host_exec_count,
    inject_synthetic_block,
    reload_extension,
    reload_gemini_tab,
    set_agent_active,
)
from ..pipeline_assert import PipelineFailure, assert_single_host_execution, wait_cooldown, TurnContext


def _host_offset() -> int:
    try:
        return os.path.getsize("/tmp/gemini_host.log")
    except OSError:
        return 0


def run_rerun_latest(port: int) -> None:
    sess = connect(port)
    try:
        reload_extension(sess)
        reload_gemini_tab(sess)
        set_agent_active(sess)
        time.sleep(2)
        marker = "gla_rerun_latest_once"
        payload = f'{{"action":"run_shell","command":"echo {marker}"}}'
        offset = _host_offset()
        inject_synthetic_block(sess, payload)
        time.sleep(12)
        first = host_exec_count(marker, offset)
        if first < 1:
            raise PipelineFailure("stage4", "initial inject did not reach host")
        ctx = TurnContext(marker=marker, host_log_offset=offset)
        wait_cooldown(ctx)

        offset2 = _host_offset()
        ret = trigger_rerun_latest(sess)
        if not ret.get("ok"):
            raise PipelineFailure("trigger", f"rerun trigger failed: {ret}")
        time.sleep(12)
        total = host_exec_count(marker, offset)
        if total < 2:
            raise PipelineFailure("stage4", f"rerun did not execute (count={total}, expected >=2)")
        # No third execution after cooldown
        assert_single_host_execution(sess, marker, offset2, wait_after_first_s=18.0)
        print("PASS rerun_latest")
    finally:
        sess.close()
