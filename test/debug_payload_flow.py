#!/usr/bin/env python3
"""CDP repro: inject action JSON on Gemini and observe extension behavior."""
import json
import sys
import time
import urllib.request

from e2e_browser import CDPClient, attach_to_target, evaluate, find_target


def drain_console(cdp: CDPClient, label: str) -> list[str]:
    logs = []
    for evt in cdp.drain_events(timeout=1.0):
        if evt.get("method") != "Runtime.consoleAPICalled":
            continue
        args = evt["params"].get("args", [])
        text = " ".join(a.get("value", "") for a in args if a.get("type") == "string")
        if text.strip():
            logs.append(f"[{label}] {text.strip()}")
    return logs


def main(port: int = 9222) -> int:
    cdp = CDPClient(port)
    sw = find_target(cdp, lambda t: t["type"] == "service_worker" and "chrome-extension://" in t.get("url", ""))
    page = find_target(cdp, lambda t: t["type"] == "page" and "gemini.google.com" in t.get("url", ""))
    if not sw or not page:
        print("FAIL: missing SW or gemini page")
        return 1

    sw_sess = attach_to_target(cdp, sw["targetId"])
    page_sess = attach_to_target(cdp, page["targetId"])
    cdp.send("Runtime.enable", session_id=sw_sess)
    cdp.send("Runtime.enable", session_id=page_sess)
    cdp.send("Log.enable", session_id=sw_sess)
    cdp.send("Log.enable", session_id=page_sess)

    storage = evaluate(
        cdp,
        sw_sess,
        """
        new Promise((resolve) => {
          chrome.storage.local.get(['isAgentPaused', 'autoSubmit'], resolve);
        })
        """,
        await_promise=True,
    )
    print("STORAGE:", json.dumps(storage.get("value"), indent=2))

    evaluate(
        cdp,
        sw_sess,
        """
        new Promise((resolve) => {
          chrome.storage.local.set({ isAgentPaused: false }, resolve);
        })
        """,
        await_promise=True,
    )
    print("Set isAgentPaused=false")
    evaluate(cdp, page_sess, "document.querySelectorAll('pre').forEach(p => p.remove())")
    cdp.send("Page.reload", session_id=page_sess)
    time.sleep(4)

    result = evaluate(
        cdp,
        page_sess,
        """
        (() => {
          const pre = document.createElement('pre');
          const code = document.createElement('code');
          code.className = 'language-json';
          code.textContent = '{"action":"run_shell","command":"echo gla_cdp_debug_test"}';
          pre.appendChild(code);
          document.body.appendChild(pre);
          return { injected: true };
        })()
        """,
    )
    print("INJECT:", result.get("value"))

    time.sleep(6)
    logs = drain_console(cdp, "any")
    print("CONSOLE (agent/background):")
    for line in logs:
        if any(x in line for x in ("Gemini Agent", "Background", "inject", "HOST", "route", "paused")):
            print(" ", line[:240])

    dom = evaluate(
        cdp,
        page_sess,
        """
        (() => {
          const el = document.querySelector('.ql-editor') || document.querySelector('[contenteditable="true"]');
          const t = el ? (el.innerText || el.textContent || '') : '';
          const bodyHas = document.body.innerText.includes('System Result');
          const bodyHasOutput = document.body.innerText.includes('gla_cdp');
          const sendBtn = document.querySelector('button[aria-label="Send message"]');
          const pe = sendBtn ? getComputedStyle(sendBtn).pointerEvents : 'no-btn';
          return {
            composerHasSystemResult: t.includes('System Result'),
            composerPreview: t.slice(0, 200),
            bodyHasSystemResult: bodyHas,
            bodyHasOutput: bodyHasOutput,
            sendPointerEvents: pe,
            qlEditors: document.querySelectorAll('.ql-editor').length,
          };
        })()
        """,
    )
    print("DOM:", json.dumps(dom.get("value"), indent=2))

    log_path = "/home/oreo/Development/Gemini-Chrome-Agent/.cursor/debug-866d96.log"
    try:
        with open(log_path, encoding="utf-8") as f:
            lines = f.readlines()
        print(f"DEBUG FILE ({len(lines)} lines):")
        for line in lines[-15:]:
            print(" ", line.rstrip()[:240])
    except FileNotFoundError:
        print("DEBUG FILE: missing (no ingest logs from extension)")

    cdp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 9222))
