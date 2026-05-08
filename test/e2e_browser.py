#!/usr/bin/env python3
"""
Browser E2E Test for Gemini Local Agent Extension

Requirements:
  - pip install websocket-client
  - A Chromium/Chrome browser running with:
    --remote-debugging-port=9223
    --remote-allow-origins='*'
    --load-extension=/path/to/.output/chrome-mv3

Usage:
  python3 test/e2e_browser.py

This test connects via Chrome DevTools Protocol (CDP) to verify:
  1. Extension service worker loads correctly
  2. Content script injects on gemini.google.com
  3. State machine initializes (settling -> paused)
  4. Background script has chrome.runtime.connectNative available
  5. Storage sync works
"""

import json
import sys
import time
import urllib.request
import websocket


class CDPClient:
    """Minimal Chrome DevTools Protocol client using flat session mode."""

    def __init__(self, port: int):
        with urllib.request.urlopen(f"http://localhost:{port}/json/version") as resp:
            data = json.loads(resp.read())
            self.ws_url = data["webSocketDebuggerUrl"]
        self.ws = websocket.create_connection(self.ws_url)
        self._msg_id = 0

    def send(self, method: str, params: dict | None = None, session_id: str | None = None) -> int:
        self._msg_id += 1
        msg: dict = {"id": self._msg_id, "method": method}
        if params:
            msg["params"] = params
        if session_id:
            msg["sessionId"] = session_id
        self.ws.send(json.dumps(msg))
        return self._msg_id

    def recv(self, expected_id: int | None = None, timeout: float = 10.0) -> dict | None:
        self.ws.settimeout(timeout)
        for _ in range(100):
            try:
                resp = json.loads(self.ws.recv())
                if expected_id is not None and resp.get("id") == expected_id:
                    return resp
                if expected_id is None:
                    return resp
            except websocket.WebSocketTimeoutException:
                break
        return None

    def drain_events(self, timeout: float = 2.0) -> list[dict]:
        """Drain all pending events/messages."""
        self.ws.settimeout(timeout)
        events = []
        for _ in range(50):
            try:
                events.append(json.loads(self.ws.recv()))
            except (websocket.WebSocketTimeoutException, Exception):
                break
        return events

    def close(self):
        self.ws.close()


def find_target(cdp: CDPClient, predicate) -> dict | None:
    """Find a target matching the predicate."""
    msg_id = cdp.send("Target.getTargets")
    resp = cdp.recv(msg_id)
    if not resp or "result" not in resp:
        return None
    for t in resp["result"]["targetInfos"]:
        if predicate(t):
            return t
    return None


def attach_to_target(cdp: CDPClient, target_id: str) -> str | None:
    """Attach to a target and return the session ID (flat mode)."""
    cdp.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
    for _ in range(10):
        resp = cdp.recv()
        if resp and resp.get("method") == "Target.attachedToTarget":
            return resp["params"]["sessionId"]
        if resp and resp.get("id") == cdp._msg_id and "result" in resp:
            return resp["result"].get("sessionId")
    return None


def evaluate(cdp: CDPClient, session_id: str, expression: str, await_promise: bool = False) -> dict:
    """Evaluate JavaScript in a target session."""
    msg_id = cdp.send(
        "Runtime.evaluate",
        {"expression": expression, "returnByValue": True, "awaitPromise": await_promise},
        session_id=session_id,
    )
    resp = cdp.recv(msg_id)
    if resp and "error" in resp:
        raise RuntimeError(f"Runtime.evaluate error: {resp['error']}")
    return resp["result"]["result"] if resp and "result" in resp else {}


def run_tests(cdp_port: int = 9223) -> bool:
    print("=" * 60)
    print("Gemini Local Agent — Browser E2E Test")
    print("=" * 60 + "\n")

    try:
        cdp = CDPClient(cdp_port)
    except Exception as e:
        print(f"FAIL: Cannot connect to CDP on port {cdp_port}: {e}")
        print("Hint: Launch browser with --remote-debugging-port=9223 --remote-allow-origins='*'")
        return False

    print(f"[1/6] Connected to browser CDP ({cdp.ws_url})\n")

    # Find extension service worker
    # If extension ID provided as arg, use it; otherwise auto-detect
    known_id = sys.argv[2] if len(sys.argv) > 2 else None
    
    if known_id:
        sw_target = find_target(
            cdp, lambda t: t["type"] == "service_worker" and known_id in t.get("url", "")
        )
    else:
        # Auto-detect: look for any service worker from a chrome-extension
        sw_target = find_target(
            cdp, lambda t: t["type"] == "service_worker" and "chrome-extension://" in t.get("url", "")
        )
    
    if not sw_target:
        print("FAIL: Extension service worker not found.")
        print("Hint: Load the unpacked extension with --load-extension=.output/chrome-mv3")
        cdp.close()
        return False
    ext_id = sw_target["url"].split("/")[2]
    print(f"[2/6] Found extension service worker (ID: {ext_id})")

    sw_session = attach_to_target(cdp, sw_target["targetId"])
    if not sw_session:
        print("FAIL: Could not attach to service worker.")
        cdp.close()
        return False
    print(f"       Attached (session: {sw_session})\n")

    # Enable Runtime and test background script
    cdp.send("Runtime.enable", session_id=sw_session)
    time.sleep(0.3)

    bg_check = evaluate(
        cdp,
        sw_session,
        """
        (() => ({
            hasChromeRuntime: typeof chrome !== 'undefined',
            hasConnectNative: typeof chrome?.runtime?.connectNative === 'function',
            hasOnMessage: typeof chrome?.runtime?.onMessage !== 'undefined',
            extensionId: chrome?.runtime?.id || 'N/A',
        }))()
        """,
    )
    print(f"[3/6] Background script check:")
    for k, v in bg_check.get("value", {}).items():
        status = "PASS" if v is True else "INFO" if v != "N/A" else "WARN"
        print(f"       [{status}] {k}: {v}")
    print()

    # Find Gemini page
    gemini_target = find_target(
        cdp, lambda t: t["type"] == "page" and "gemini.google.com" in t.get("url", "")
    )
    if not gemini_target:
        print("WARN: No Gemini tab found. Creating one would require Page.navigate.")
        cdp.close()
        return False
    print(f"[4/6] Found Gemini page: {gemini_target['url']}")

    page_session = attach_to_target(cdp, gemini_target["targetId"])
    if not page_session:
        print("FAIL: Could not attach to Gemini page.")
        cdp.close()
        return False
    print(f"       Attached (session: {page_session})\n")

    cdp.send("Runtime.enable", session_id=page_session)
    time.sleep(0.3)

    # Check page state
    page_state = evaluate(
        cdp,
        page_session,
        """
        (() => ({
            url: window.location.href,
            title: document.title,
            readyState: document.readyState,
        }))()
        """,
    )
    print(f"[5/6] Page state: {json.dumps(page_state.get('value', {}), indent=2)}")

    # Reload to trigger content script and capture logs
    print("\n[6/6] Reloading page to capture content script initialization...")
    cdp.send("Page.reload", session_id=page_session)
    time.sleep(3)

    logs = []
    for evt in cdp.drain_events(timeout=1.0):
        if evt.get("method") == "Runtime.consoleAPICalled":
            args = evt["params"].get("args", [])
            text = " ".join([a.get("value", "") for a in args if a.get("type") == "string"])
            if text.strip():
                logs.append(text.strip())

    print(f"       Captured {len(logs)} console messages:")
    agent_logs = [l for l in logs if "agent" in l.lower() or "gla" in l.lower()]
    for log in agent_logs[:10]:
        print(f"         {log[:120]}")

    # Verify expected log patterns
    checks = {
        "content_script_loaded": any("Content script loaded" in l for l in agent_logs),
        "state_transition": any("State transition" in l for l in agent_logs),
        "storage_sync": any("pause state synced" in l for l in agent_logs),
    }

    print("\n" + "=" * 60)
    print("Results:")
    all_pass = True
    for name, passed in checks.items():
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {name}")

    # Overall background check
    bg_pass = bg_check.get("value", {}).get("hasConnectNative", False)
    if bg_pass:
        print(f"  [PASS] background.connectNative available")
    else:
        print(f"  [FAIL] background.connectNative not available")
        all_pass = False

    print("=" * 60)
    print(f"\nOverall: {'ALL TESTS PASSED' if all_pass else 'SOME TESTS FAILED'}")

    cdp.close()
    return all_pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9223
    success = run_tests(port)
    sys.exit(0 if success else 1)
