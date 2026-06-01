"""Tier A: pipeline regressions without Gemini model."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from ..harness import (
    BrowserSession,
    connect,
    host_exec_count,
    inject_synthetic_block,
    read_storage,
    reload_extension,
    reload_gemini_tab,
    set_agent_active,
)
from ..pipeline_assert import PipelineFailure, assert_single_host_execution


def _host_offset() -> int:
    try:
        return os.path.getsize("/tmp/gemini_host.log")
    except OSError:
        return 0


def run_smoke(port: int) -> None:
    repo = Path(__file__).resolve().parents[3]
    e2e = repo / "test" / "e2e_browser.py"
    proc = subprocess.run(
        [sys.executable, str(e2e), str(port)],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    if proc.returncode != 0:
        raise PipelineFailure("setup", "e2e_browser.py smoke failed")


def run_loop_no_rerun(port: int) -> None:
    sess = connect(port)
    try:
        reload_extension(sess)
        reload_gemini_tab(sess)
        set_agent_active(sess)
        offset = _host_offset()
        marker = "gla_loop_once_only"
        inject_synthetic_block(sess, f'{{"action":"run_shell","command":"echo {marker}"}}')
        time.sleep(8)
        assert_single_host_execution(sess, marker, offset, wait_after_first_s=20.0)
        print("PASS loop_no_rerun")
    finally:
        sess.close()


def run_load_historical_skip(port: int) -> None:
    sess = connect(port)
    try:
        reload_extension(sess)
        reload_gemini_tab(sess)
        set_agent_active(sess)
        time.sleep(6)
        payload = '{"action":"run_shell","command":"echo gla_historical_skip"}'
        inject_synthetic_block(sess, payload)
        offset = _host_offset()
        # Extension reload re-inits content script; block stays in DOM as historical
        reload_extension(sess)
        time.sleep(8)
        count = host_exec_count("gla_historical_skip", offset)
        if count > 0:
            raise PipelineFailure(
                "stage2",
                f"historical block ran on reload (expected skip), count={count}",
            )
        # Block should still be detectable in DOM
        from ..harness import page_eval

        r = page_eval(
            sess,
            """(() => {
              return [...document.querySelectorAll('pre code, code')]
                .some(c => (c.textContent||'').includes('gla_historical_skip'));
            })()""",
        )
        if not r.get("value"):
            raise PipelineFailure("stage1", "historical block missing from DOM after reload")
        print("PASS load_historical_skip")
    finally:
        sess.close()


def run_synthetic_happy(port: int) -> None:
    sess = connect(port)
    try:
        reload_extension(sess)
        reload_gemini_tab(sess)
        set_agent_active(sess)
        time.sleep(2)
        offset = _host_offset()
        marker = "gla_synthetic_happy"
        inject_synthetic_block(sess, f'{{"action":"run_shell","command":"echo {marker}"}}')
        time.sleep(10)
        if host_exec_count(marker, offset) < 1:
            raise PipelineFailure("stage4", "synthetic happy path did not reach host")
        print("PASS synthetic_happy (pipeline wiring only — not user's load-time case)")
    finally:
        sess.close()


TIER_A = {
    "smoke": run_smoke,
    "loop_no_rerun": run_loop_no_rerun,
    "load_historical_skip": run_load_historical_skip,
    "synthetic_happy": run_synthetic_happy,
}
