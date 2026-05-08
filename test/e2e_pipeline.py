#!/usr/bin/env python3
"""
Native Messaging Pipeline E2E Test

Verifies the full chain: popup → background script → native host → response

Usage:
  python3 test/e2e_pipeline.py [cdp_port] [extension_id]

If extension_id is not provided, the script will attempt to auto-detect it
by looking for a popup page with "Gemini Local Agent" in the title.
"""

import json
import sys
import time
import urllib.request
import websocket


class CDPClient:
    def __init__(self, port: int):
        with urllib.request.urlopen(f"http://localhost:{port}/json/version") as resp:
            data = json.loads(resp.read())
            self.ws_url = data["webSocketDebuggerUrl"]
        self.ws = websocket.create_connection(self.ws_url)
        self._msg_id = 0

    def send(self, method: str, params=None, session_id=None) -> int:
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method}
        if params:
            msg["params"] = params
        if session_id:
            msg["sessionId"] = session_id
        self.ws.send(json.dumps(msg))
        return self._msg_id

    def recv(self, expected_id=None, timeout=10.0):
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

    def close(self):
        self.ws.close()


def get_all_targets(cdp: CDPClient) -> list[dict]:
    msg_id = cdp.send("Target.getTargets")
    resp = cdp.recv(msg_id)
    if resp and "result" in resp:
        return resp["result"]["targetInfos"]
    return []


def find_our_extension(cdp: CDPClient, known_id: str | None = None) -> str | None:
    """Find the Gemini Local Agent extension ID."""
    targets = get_all_targets(cdp)

    # Strategy 1: If known_id provided, verify it exists
    if known_id:
        for t in targets:
            if known_id in t.get("url", ""):
                return known_id

    # Strategy 2: Look for popup.html targets and check their title
    for t in targets:
        url = t.get("url", "")
        if "popup.html" in url and "chrome-extension://" in url:
            ext_id = url.split("/")[2]
            # Verify by checking if title contains "Gemini"
            if "gemini" in t.get("title", "").lower():
                return ext_id

    # Strategy 3: Check all chrome-extension targets
    ext_ids = set()
    for t in targets:
        url = t.get("url", "")
        if "chrome-extension://" in url:
            ext_id = url.split("/")[2]
            ext_ids.add(ext_id)

    # If only one extension is loaded, use it
    if len(ext_ids) == 1:
        return ext_ids.pop()

    # Strategy 4: Open each popup and check the title
    for ext_id in ext_ids:
        test_url = f"chrome-extension://{ext_id}/popup.html"
        cdp.send("Target.createTarget", {"url": test_url})
        time.sleep(1.5)

        # Re-check targets
        new_targets = get_all_targets(cdp)
        for nt in new_targets:
            if test_url in nt.get("url", ""):
                title = nt.get("title", "").lower()
                if "gemini" in title or "agent" in title:
                    return ext_id

    return None


def read_host_log(path="/tmp/gemini_host.log") -> str:
    try:
        with open(path, "r") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def attach_to_target(cdp: CDPClient, target_id: str) -> str | None:
    cdp.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
    for _ in range(10):
        resp = cdp.recv()
        if resp and resp.get("method") == "Target.attachedToTarget":
            return resp["params"]["sessionId"]
        if resp and resp.get("id") == cdp._msg_id and "result" in resp:
            return resp["result"].get("sessionId")
    return None


def run_pipeline_test(cdp_port: int = 9222, known_ext_id: str | None = None) -> bool:
    print("=" * 60)
    print("Native Messaging Pipeline E2E Test")
    print("=" * 60 + "\n")

    try:
        cdp = CDPClient(cdp_port)
    except Exception as e:
        print(f"FAIL: Cannot connect to CDP on port {cdp_port}: {e}")
        return False

    print(f"[1/5] Connected to browser CDP ({cdp.ws_url})\n")

    # Find our extension
    our_ext = find_our_extension(cdp, known_ext_id)
    if not our_ext:
        print("FAIL: Could not find Gemini Local Agent extension.")
        print("Hint: Load it at brave://extensions/ → Load unpacked → .output/chrome-mv3/")
        cdp.close()
        return False

    print(f"[2/5] Extension ID: {our_ext}")

    # Open popup to wake service worker
    popup_url = f"chrome-extension://{our_ext}/popup.html"
    cdp.send("Target.createTarget", {"url": popup_url})
    time.sleep(2)

    popup_target = None
    for t in get_all_targets(cdp):
        if popup_url in t.get("url", ""):
            popup_target = t
            break

    if not popup_target:
        print("FAIL: Could not open popup page")
        cdp.close()
        return False

    popup_session = attach_to_target(cdp, popup_target["targetId"])
    if not popup_session:
        print("FAIL: Could not attach to popup")
        cdp.close()
        return False

    print(f"       Popup attached (session: {popup_session})")

    cdp.send("Runtime.enable", session_id=popup_session)
    time.sleep(0.5)

    # Verify APIs
    msg_id = cdp.send(
        "Runtime.evaluate",
        {
            "expression": """
                (() => ({
                    hasChromeRuntime: typeof chrome !== 'undefined',
                    hasConnectNative: typeof chrome?.runtime?.connectNative === 'function',
                    extensionId: chrome?.runtime?.id || 'N/A',
                }))()
            """,
            "returnByValue": True,
        },
        session_id=popup_session,
    )
    resp = cdp.recv(msg_id)
    apis = resp["result"]["result"]["value"]
    print(f"       APIs: {json.dumps(apis, indent=2)}")

    if not apis.get("hasConnectNative"):
        print("FAIL: connectNative not available in popup context")
        print("This usually means the extension ID in the host manifest doesn't match.")
        cdp.close()
        return False

    # Read initial host log
    initial_log = read_host_log()
    print(f"\n[3/5] Host log size before: {len(initial_log)} bytes")

    # Send test payload
    test_id = f"pipeline-{int(time.time() * 1000)}"
    print(f"       Test ID: {test_id}")

    msg_id = cdp.send(
        "Runtime.evaluate",
        {
            "expression": f"""
                (async () => {{
                    const payload = {{
                        action: 'run_shell',
                        command: 'echo "pipeline_ok"',
                        id: '{test_id}'
                    }};
                    return new Promise((resolve) => {{
                        chrome.runtime.sendMessage(
                            {{ type: 'SEND_TO_HOST', payload }},
                            (resp) => resolve({{ callbackFired: true, resp }})
                        );
                        setTimeout(() => resolve({{ callbackFired: false }}), 1500);
                    }});
                }})()
            """,
            "returnByValue": True,
            "awaitPromise": True,
        },
        session_id=popup_session,
    )
    resp = cdp.recv(msg_id)
    send_result = resp["result"]["result"]["value"]
    print(f"       Send result: {json.dumps(send_result, indent=2)}")

    time.sleep(2)

    # Check host log
    new_log = read_host_log()
    delta = new_log[len(initial_log):]
    print(f"\n[4/5] Host log size after: {len(new_log)} bytes")
    print(f"       New content: {len(delta)} bytes")

    # Parse results
    found_received = test_id in delta and "Received message" in delta
    found_executed = test_id in delta and "Executing shell command" in delta
    found_response = test_id in delta and "Sent response" in delta
    found_success = "'status': 'success'" in delta and test_id in delta

    # Print relevant log lines
    relevant_lines = [l for l in delta.split("\n") if test_id in l]
    print(f"       Relevant log lines ({len(relevant_lines)}):")
    for line in relevant_lines[:3]:
        print(f"         {line[:140]}")

    # Check Gemini tab for response
    print(f"\n[5/5] Checking Gemini tab for injected response...")
    print("       Note: Injection requires the message to originate from the Gemini tab")
    print("       (so sender.tab.id is set). Popup-originated messages use broadcast fallback.")
    
    gemini_target = None
    for t in get_all_targets(cdp):
        if t.get("type") == "page" and "gemini.google.com" in t.get("url", ""):
            gemini_target = t
            break

    response_injected = False
    if gemini_target:
        gemini_session = attach_to_target(cdp, gemini_target["targetId"])
        if gemini_session:
            cdp.send("Runtime.enable", session_id=gemini_session)
            time.sleep(0.3)

            msg_id = cdp.send(
                "Runtime.evaluate",
                {
                    "expression": """
                        (() => {
                            // Check if response text was injected into the chat input
                            const inputs = document.querySelectorAll('textarea, input[type="text"]');
                            for (const el of inputs) {
                                if (el.value && el.value.includes('pipeline_ok')) {
                                    return { found: true, element: el.tagName, value: el.value };
                                }
                            }
                            return { found: false, inputCount: inputs.length };
                        })()
                    """,
                    "returnByValue": True,
                },
                session_id=gemini_session,
            )
            resp = cdp.recv(msg_id)
            inject_check = resp["result"]["result"]["value"]
            response_injected = inject_check.get("found", False)
            print(f"       Injection check: {json.dumps(inject_check, indent=2)}")

    print(f"\n{'=' * 60}")
    print("Results:")
    checks = {
        "host_received": found_received,
        "host_executed": found_executed,
        "host_responded": found_response,
        "response_success": found_success,
    }
    # Injection from popup is expected to fail because sender.tab is undefined
    # In real usage, messages originate from the content script in the Gemini tab
    optional_checks = {
        "response_injected": response_injected,
    }

    all_pass = True
    for name, passed in checks.items():
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_pass = False
        print(f"  [{status}] {name}")

    for name, passed in optional_checks.items():
        status = "PASS" if passed else "INFO"
        print(f"  [{status}] {name} (optional — requires Gemini-tab origin)")

    print("=" * 60)
    print(f"\nOverall: {'ALL TESTS PASSED' if all_pass else 'SOME TESTS FAILED'}")

    cdp.close()
    return all_pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9222
    ext_id = sys.argv[2] if len(sys.argv) > 2 else None
    success = run_pipeline_test(port, ext_id)
    sys.exit(0 if success else 1)
