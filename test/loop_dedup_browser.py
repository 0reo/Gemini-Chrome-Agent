#!/usr/bin/env python3
"""Verify a static JSON block executes once across cooldown (no re-run loop)."""
import json
import sys
import time

from e2e_browser import CDPClient, attach_to_target, evaluate, find_target


def count_executions(cdp: CDPClient, page_sess: str) -> int:
    n = 0
    for evt in cdp.drain_events(timeout=0.2):
        if evt.get("method") != "Runtime.consoleAPICalled":
            continue
        args = evt["params"].get("args", [])
        text = " ".join(a.get("value", "") for a in args if a.get("type") == "string")
        if "[Gemini Agent] Executing action" in text and "gla_loop_test" in text:
            n += 1
    return n


def main(port: int = 9222) -> int:
    cdp = CDPClient(port)
    page = find_target(cdp, lambda t: t["type"] == "page" and "gemini.google.com" in t.get("url", ""))
    if not page:
        print("FAIL: no gemini page")
        return 1
    sess = attach_to_target(cdp, page["targetId"])
    cdp.send("Runtime.enable", session_id=sess)
    cdp.send("Log.enable", session_id=sess)

    evaluate(cdp, sess, "document.querySelectorAll('pre').forEach(p => p.remove())")
    time.sleep(6)  # armed after settling
    evaluate(
        cdp,
        sess,
        """(() => {
          const pre = document.createElement('pre');
          const code = document.createElement('code');
          code.textContent = '{"action":"run_shell","command":"echo gla_loop_test"}';
          pre.appendChild(code);
          document.body.appendChild(pre);
          return true;
        })()""",
    )
    time.sleep(8)
    first = count_executions(cdp, sess)
    time.sleep(20)  # past default 15s cooldown
    second = count_executions(cdp, sess)
    cdp.close()
    print(json.dumps({"firstWindow": first, "afterCooldown": second}))
    if first >= 1 and second == 0:
        print("PASS: single execution, no loop after cooldown")
        return 0
    print("FAIL: expected 1+ exec then 0; got loop if afterCooldown > 0")
    return 1


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 9222))
