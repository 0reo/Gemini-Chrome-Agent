"""CDP session management: one debug Brave, one Gemini tab."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
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

_VERBOSE = False


def set_verbose(enabled: bool) -> None:
    global _VERBOSE
    _VERBOSE = enabled


def log_step(msg: str) -> None:
    if not _VERBOSE:
        return
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

_ACTION_LOG_MARKERS: dict[str, str] = {
    "read_file": "Reading file:",
    "write_file": "Writing file:",
    "run_shell": "Executing shell command:",
    "run_python": "Running Python code",
    "git_status": "Git status",
    "git_diff": "Git diff",
    "list_files": "Listing files:",
}


def _recv_timeout_expected(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in ("timed out", "timeout", "disconnect", "closed", "connection")
    )


def host_log_offset() -> int:
    """Character offset into the host log (not byte count)."""
    try:
        with open(HOST_LOG, encoding="utf-8") as fh:
            return len(fh.read())
    except OSError:
        return 0


def capture_failure_artifacts(port: int, label: str) -> str | None:
    """Save a screenshot + composer/send/thread state when a scenario fails, so a failed run is
    never blind (Rule 0 / #17). Attaches to the existing tab WITHOUT reloading (preserves the
    failure state). Best-effort: never raises — a capture error must not mask the real failure."""
    import base64

    out_dir = Path("/tmp/closed_loop_failures")
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
    stamp = time.strftime("%H%M%S")
    saved: list[str] = []
    cdp = None
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        cdp = CDPClient(port)
        page = find_target(cdp, _is_gemini_app_page)
        if not page:
            return None
        page_sess = attach_to_target(cdp, page["targetId"])
        try:
            cdp.send("Page.enable", session_id=page_sess)
            mid = cdp.send("Page.captureScreenshot", {"format": "png"}, session_id=page_sess)
            data = (cdp.recv(mid, timeout=10.0) or {}).get("result", {}).get("data")
            if data:
                png = out_dir / f"{safe}_{stamp}.png"
                png.write_bytes(base64.b64decode(data))
                saved.append(str(png))
        except Exception as exc:  # capture must not mask the real failure
            log_step(f"capture: screenshot failed ({exc})")
        try:
            state = evaluate(cdp, page_sess, """(() => {
              const ed = document.querySelector('.ql-editor.textarea') || document.querySelector('.ql-editor');
              const send = document.querySelector('button[aria-label="Send message"]');
              return {
                url: location.href,
                composerLen: ed ? (ed.innerText||'').trim().length : null,
                composerText: ed ? (ed.innerText||'').slice(0, 300) : null,
                qlBlank: ed ? ed.classList.contains('ql-blank') : null,
                sendPointerEvents: send ? getComputedStyle(send).pointerEvents : 'no-send-button',
                sendDisabled: send ? send.disabled : null,
                userQueries: document.querySelectorAll('user-query').length,
                modelResponses: document.querySelectorAll('model-response').length,
                threadHasSystemResult: document.body.innerText.includes('System Result'),
              };
            })()""").get("value")
            js = out_dir / f"{safe}_{stamp}.json"
            js.write_text(json.dumps(state, indent=2))
            saved.append(str(js))
        except Exception as exc:
            log_step(f"capture: DOM state failed ({exc})")
    except Exception as exc:
        log_step(f"capture: could not attach for artifacts ({exc})")
        return None
    finally:
        if cdp is not None:
            try:
                cdp.close()
            except Exception:
                pass
    if saved:
        print(f"  ↳ failure artifacts: {', '.join(saved)}", file=sys.stderr)
    return out_dir.as_posix() if saved else None


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
    log_step(f"connect: attaching CDP on :{port}")
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
        mid = cdp.send("Target.createTarget", {"url": "https://gemini.google.com/app"})
        try:
            cdp.recv(mid, timeout=15.0)
        except RuntimeError as exc:
            if not _recv_timeout_expected(exc):
                raise
        time.sleep(4.0)
        page = find_target(cdp, _is_gemini_app_page)
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
    log_step(f"connect: ready (ext={ext_id[:8]}…, page={page.get('url', '')[:60]})")
    return BrowserSession(cdp, port, sw, page, sw_sess, page_sess, ext_id)


def reconnect_gemini_page(sess: BrowserSession) -> None:
    log_step("reconnect_gemini_page: re-attaching to Gemini tab")
    sess.cdp.drain_events(timeout=0.3)
    deadline = time.time() + 20.0
    page = None
    while time.time() < deadline:
        page = find_target(sess.cdp, _is_gemini_app_page)
        if page:
            break
        time.sleep(0.5)
    if not page:
        raise RuntimeError("No gemini.google.com tab — open Gemini in debug Brave")
    sess.page_target = page
    new_sess = attach_to_target(sess.cdp, page["targetId"])
    if not new_sess:
        raise RuntimeError(
            "reconnect_gemini_page: attach_to_target returned None (stale session)"
        )
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
    except RuntimeError as exc:
        if not _recv_timeout_expected(exc):
            raise
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
    log_step("wait_gemini_content_script: waiting for content script init")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for evt in sess.cdp.drain_events(timeout=0.4):
            text = _console_text_from_event(evt)
            if "[Gemini Agent]" in text and "Content script loaded" in text:
                time.sleep(0.5)
                log_step("wait_gemini_content_script: content script ready")
                return
        time.sleep(0.3)
    raise RuntimeError("Gemini content script did not load (no console init log)")


def reload_gemini_tab(sess: BrowserSession) -> None:
    """Full page reload so MV3 content script injects on the active Gemini tab."""
    log_step("reload_gemini_tab: starting page reload")
    sess.cdp.drain_events(timeout=0.2)
    mid = sess.cdp.send("Page.reload", session_id=sess.page_sess)
    try:
        sess.cdp.recv(mid, timeout=20.0)
    except RuntimeError as exc:
        if not _recv_timeout_expected(exc):
            raise
    time.sleep(2.0)
    reconnect_gemini_page(sess)
    wait_gemini_content_script(sess)
    time.sleep(SETTLING_WAIT_S)
    log_step("reload_gemini_tab: complete")


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
    action_marker = _ACTION_LOG_MARKERS.get(command_substring)
    n = 0
    for line in chunk.splitlines():
        if action_marker:
            if action_marker in line:
                n += 1
        elif "Executing shell command:" in line and command_substring in line:
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
    try:
        raw = evaluate(sess.cdp, sess.page_sess, expression, await_promise=await_promise)
    except RuntimeError as exc:
        if "CDP evaluate timed out" not in str(exc):
            raise
        log_step("page_eval: CDP timeout — reconnecting Gemini page and retrying once")
        reconnect_gemini_page(sess)
        raw = evaluate(sess.cdp, sess.page_sess, expression, await_promise=await_promise)
    if isinstance(raw, dict) and "value" in raw:
        return {"value": raw["value"]}
    return {"value": raw}
