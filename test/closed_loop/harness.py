"""CDP session management: one debug Brave, one Gemini tab."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# test/e2e_browser.py
_TEST_DIR = Path(__file__).resolve().parent.parent
if str(_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_TEST_DIR))

from e2e_browser import CDPClient, attach_to_target, evaluate, find_target  # noqa: E402

DEFAULT_PORT = 9222
HOST_LOG = "/tmp/gemini_host.log"
SETTLING_WAIT_S = 6
DEFAULT_COOLDOWN_WAIT_S = 16


def _is_gemini_app_page(target: dict) -> bool:
    url = target.get("url", "")
    return target.get("type") == "page" and url.startswith("https://gemini.google.com/")


@dataclass
class BrowserSession:
    cdp: CDPClient
    port: int
    sw_target: dict
    page_target: dict
    sw_sess: str
    page_sess: str
    ext_id: str

    def close(self) -> None:
        self.cdp.close()


def cdp_is_up(port: int = DEFAULT_PORT) -> bool:
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def ensure_cdp(port: int = DEFAULT_PORT) -> None:
    if not cdp_is_up(port):
        raise RuntimeError(
            f"CDP not listening on :{port}. Start debug Brave:\n"
            "  ./scripts/launch-debug-brave.sh"
        )


def close_extra_gemini_tabs(cdp: CDPClient) -> int:
    """Close duplicate gemini.google.com page targets; keep the first."""
    msg_id = cdp.send("Target.getTargets")
    resp = cdp.recv(msg_id)
    if not resp or "result" not in resp:
        return 0
    pages = [
        t
        for t in resp["result"]["targetInfos"]
        if _is_gemini_app_page(t)
    ]
    # Keep the active chat tab (longer /app/<id> URL), not a bare /app shell.
    pages.sort(key=lambda t: len(t.get("url", "")), reverse=True)
    closed = 0
    for t in pages[1:]:
        tid = t["targetId"]
        mid = cdp.send("Target.closeTarget", {"targetId": tid})
        cdp.recv(mid, timeout=3.0)
        closed += 1
        time.sleep(0.3)
    cdp.drain_events(timeout=0.3)
    return closed


def connect(port: int = DEFAULT_PORT) -> BrowserSession:
    ensure_cdp(port)
    cdp = CDPClient(port)
    close_extra_gemini_tabs(cdp)

    sw = find_target(
        cdp,
        lambda t: t["type"] == "service_worker" and "chrome-extension://" in t.get("url", ""),
    )
    page = find_target(cdp, _is_gemini_app_page)
    if not sw:
        cdp.close()
        raise RuntimeError("Extension service worker not found — load .output/chrome-mv3")
    if not page:
        cdp.close()
        raise RuntimeError("No gemini.google.com tab — open or navigate to Gemini")

    sw_sess = attach_to_target(cdp, sw["targetId"])
    page_sess = attach_to_target(cdp, page["targetId"])
    if not sw_sess or not page_sess:
        cdp.close()
        raise RuntimeError("CDP attach failed")

    cdp.send("Runtime.enable", session_id=sw_sess)
    cdp.send("Runtime.enable", session_id=page_sess)
    cdp.send("Log.enable", session_id=page_sess)

    ext_id = sw["url"].split("/")[2]
    return BrowserSession(cdp, port, sw, page, sw_sess, page_sess, ext_id)


def reconnect_gemini_page(sess: BrowserSession) -> None:
    sess.cdp.drain_events(timeout=0.3)
    page = find_target(sess.cdp, _is_gemini_app_page)
    if not page:
        raise RuntimeError("No gemini.google.com tab — open Gemini in debug Brave")
    sess.page_target = page
    new_sess = attach_to_target(sess.cdp, page["targetId"])
    if new_sess:
        sess.page_sess = new_sess
        sess.cdp.send("Runtime.enable", session_id=sess.page_sess)
        sess.cdp.send("Log.enable", session_id=sess.page_sess)


def reload_extension(sess: BrowserSession) -> None:
    # SW dies on reload — do not wait for evaluate result (would timeout).
    sess.cdp.drain_events(timeout=0.2)
    mid = sess.cdp.send(
        "Runtime.evaluate",
        {"expression": "chrome.runtime.reload()"},
        session_id=sess.sw_sess,
    )
    try:
        sess.cdp.recv(mid, timeout=2.0)
    except Exception:
        pass
    time.sleep(3)
    sw = None
    for _ in range(20):
        sess.cdp.drain_events(timeout=0.2)
        sw = find_target(
            sess.cdp,
            lambda t: t["type"] == "service_worker" and sess.ext_id in t.get("url", ""),
        )
        if sw:
            break
        time.sleep(0.5)
    if not sw:
        raise RuntimeError("Service worker not found after extension reload")
    sess.sw_target = sw
    new_sw = attach_to_target(sess.cdp, sw["targetId"])
    if not new_sw:
        raise RuntimeError("Failed to reattach to extension service worker after reload")
    sess.sw_sess = new_sw
    sess.cdp.send("Runtime.enable", session_id=sess.sw_sess)
    time.sleep(1)
    reconnect_gemini_page(sess)


def _console_text_from_event(evt: dict) -> str:
    if evt.get("method") != "Runtime.consoleAPICalled":
        return ""
    args = evt.get("params", {}).get("args", [])
    return " ".join(a.get("value", "") for a in args if a.get("type") == "string")


def wait_gemini_content_script(sess: BrowserSession, timeout_s: float = 30.0) -> None:
    """Wait for [Gemini Agent] content script init log after navigation/reload."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for evt in sess.cdp.drain_events(timeout=0.4):
            text = _console_text_from_event(evt)
            if "[Gemini Agent]" in text and "Content script loaded" in text:
                time.sleep(0.5)
                return
        time.sleep(0.3)
    raise RuntimeError("Gemini content script did not load (no console init log)")


def reload_gemini_tab(sess: BrowserSession) -> None:
    """Full page reload so MV3 content script injects on the active Gemini tab."""
    sess.cdp.drain_events(timeout=0.2)
    mid = sess.cdp.send("Page.reload", session_id=sess.page_sess)
    try:
        sess.cdp.recv(mid, timeout=20.0)
    except Exception:
        pass
    time.sleep(2.0)
    reconnect_gemini_page(sess)
    wait_gemini_content_script(sess)
    time.sleep(SETTLING_WAIT_S)


def read_storage(sess: BrowserSession) -> dict:
    expr = (
        "new Promise((r)=>chrome.storage.local.get("
        "['isAgentPaused','autoSubmit','cooldownSeconds','maxPerMinute','settlingSeconds'],r))"
    )
    val = evaluate(sess.cdp, sess.sw_sess, expr, await_promise=True)
    return val.get("value") or {}


def set_agent_active(sess: BrowserSession) -> None:
    evaluate(
        sess.cdp,
        sess.sw_sess,
        "new Promise(r => chrome.storage.local.set({ isAgentPaused: false }, r))",
        await_promise=True,
    )


def host_log_tail(marker: str | None = None, lines: int = 40) -> str:
    try:
        with open(HOST_LOG, encoding="utf-8") as fh:
            content = fh.read()
    except FileNotFoundError:
        return ""
    if not marker:
        return "\n".join(content.splitlines()[-lines:])
    return "\n".join(l for l in content.splitlines() if marker in l)


def host_exec_count(command_substring: str, after_index: int = 0) -> int:
    try:
        with open(HOST_LOG, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        return 0
    chunk = text[after_index:]
    n = 0
    for line in chunk.splitlines():
        if "Executing shell command:" in line and command_substring in line:
            n += 1
    return n


def drain_agent_console(sess: BrowserSession, timeout: float = 0.5) -> list[str]:
    out: list[str] = []
    for evt in sess.cdp.drain_events(timeout=timeout):
        if evt.get("method") != "Runtime.consoleAPICalled":
            continue
        args = evt["params"].get("args", [])
        text = " ".join(a.get("value", "") for a in args if a.get("type") == "string")
        if "[Gemini Agent]" in text:
            out.append(text.strip())
    return out


def content_script_token(sess: BrowserSession) -> str:
    r = page_eval(sess, "(() => document.documentElement.dataset.glaAgentReady || '')()")
    return str(r.get("value") or "")


def wait_content_script(
    sess: BrowserSession,
    timeout_s: float = 20.0,
    previous_token: str | None = None,
) -> None:
    """Wait until content script sets dataset.glaAgentReady (new token after extension reload)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        token = content_script_token(sess)
        if token and token != (previous_token or ""):
            time.sleep(0.5)
            return
        time.sleep(0.5)
    raise RuntimeError("content script not ready (dataset.glaAgentReady)")


def inject_synthetic_block(sess: BrowserSession, payload_json: str) -> None:
    escaped = json.dumps(payload_json)
    evaluate(
        sess.cdp,
        sess.page_sess,
        f"""(() => {{
          const pre = document.createElement('pre');
          const code = document.createElement('code');
          code.className = 'language-json';
          code.textContent = {escaped};
          pre.appendChild(code);
          document.body.appendChild(pre);
          return true;
        }})()""",
    )


def page_eval(sess: BrowserSession, expression: str, await_promise: bool = False) -> dict:
    raw = evaluate(sess.cdp, sess.page_sess, expression, await_promise=await_promise)
    if isinstance(raw, dict) and "value" in raw:
        return {"value": raw["value"]}
    return {"value": raw}
