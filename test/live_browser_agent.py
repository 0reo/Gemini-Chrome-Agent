#!/usr/bin/env python3
"""Live CDP test: do NOT force pause; exercise extension on real Gemini."""
import json
import sys
import time

from e2e_browser import CDPClient, attach_to_target, evaluate, find_target


def drain_agent_logs(cdp: CDPClient, timeout: float = 0.5) -> list[str]:
    out = []
    for evt in cdp.drain_events(timeout=timeout):
        if evt.get("method") != "Runtime.consoleAPICalled":
            continue
        args = evt["params"].get("args", [])
        text = " ".join(a.get("value", "") for a in args if a.get("type") == "string")
        if "[Gemini Agent]" in text or "[Background]" in text:
            out.append(text.strip())
    return out


def main(port: int = 9222) -> int:
    cdp = CDPClient(port)
    sw = find_target(cdp, lambda t: t["type"] == "service_worker" and "chrome-extension://" in t.get("url", ""))
    page = find_target(cdp, lambda t: t["type"] == "page" and "gemini.google.com" in t.get("url", ""))
    if not sw or not page:
        print("FAIL: need extension SW + gemini page on CDP", port)
        return 1

    sw_sess = attach_to_target(cdp, sw["targetId"])
    page_sess = attach_to_target(cdp, page["targetId"])
    for sid in (sw_sess, page_sess):
        cdp.send("Runtime.enable", session_id=sid)
        cdp.send("Log.enable", session_id=sid)

    storage = evaluate(
        cdp,
        sw_sess,
        "new Promise(r => chrome.storage.local.get(['isAgentPaused','autoSubmit'], r))",
        await_promise=True,
    )
    print("=== STORAGE (unchanged) ===")
    print(json.dumps(storage.get("value"), indent=2))

    login = evaluate(
        cdp,
        page_sess,
        """(() => ({
          url: location.href,
          hasComposer: !!document.querySelector('.ql-editor,[contenteditable="true"]'),
          signIn: [...document.querySelectorAll('a,button')].some(e => /sign in/i.test((e.textContent||'')+(e.getAttribute('aria-label')||'')))
        }))()""",
    )
    print("=== LOGIN ===")
    print(json.dumps(login.get("value"), indent=2))
    if login.get("value", {}).get("signIn"):
        print("FAIL: not signed in — ask user to sign in to debug profile")
        cdp.close()
        return 1

    # --- Test 1: synthetic pre/code (armed, no pause toggle) ---
    print("\n=== TEST 1: synthetic JSON block (wait for armed) ===")
    time.sleep(6)  # settling period after any reload
    evaluate(cdp, page_sess, "document.querySelectorAll('pre').forEach(p => p.remove())")
    evaluate(
        cdp,
        page_sess,
        """(() => {
          const pre = document.createElement('pre');
          const code = document.createElement('code');
          code.className = 'language-json';
          code.textContent = '{"action":"run_shell","command":"echo gla_live_test_1"}';
          pre.appendChild(code);
          document.body.appendChild(pre);
          return true;
        })()""",
    )
    time.sleep(8)
    logs1 = drain_agent_logs(cdp, 1.0)
    dom1 = evaluate(
        cdp,
        page_sess,
        """(() => ({
          bodyHas: document.body.innerText.includes('gla_live_test_1'),
          systemResult: document.body.innerText.includes('System Result'),
          preCodeCount: document.querySelectorAll('pre code, code').length
        }))()""",
    )
    print("DOM:", json.dumps(dom1.get("value")))
    for line in logs1[-20:]:
        print(" ", line[:220])

    # --- Test 2: markExistingBlocks — reload with JSON already in DOM ---
    print("\n=== TEST 2: markExisting on reload (JSON present at load) ===")
    evaluate(
        cdp,
        page_sess,
        """(() => {
          sessionStorage.setItem('gla_test_payload', '{"action":"run_shell","command":"echo gla_live_test_2"}');
          return true;
        })()""",
    )
    evaluate(
        cdp,
        page_sess,
        """(() => {
          const pre = document.createElement('pre');
          const code = document.createElement('code');
          code.textContent = sessionStorage.getItem('gla_test_payload');
          pre.appendChild(code);
          document.documentElement.setAttribute('data-gla-pending-pre', pre.outerHTML);
          return true;
        })""",
    )
    cdp.send("Page.reload", session_id=page_sess)
    time.sleep(2)
    evaluate(
        cdp,
        page_sess,
        """(() => {
          const html = document.documentElement.getAttribute('data-gla-pending-pre');
          if (html) {
            const wrap = document.createElement('div');
            wrap.innerHTML = html;
            document.body.appendChild(wrap.firstElementChild);
            document.documentElement.removeAttribute('data-gla-pending-pre');
          }
          return { inserted: !!html };
        })()""",
    )
    time.sleep(8)
    logs2 = drain_agent_logs(cdp, 1.0)
    dom2 = evaluate(
        cdp,
        page_sess,
        """(() => ({
          bodyHas2: document.body.innerText.includes('gla_live_test_2'),
          markedOnly: !document.body.innerText.includes('gla_live_test_2')
        }))()""",
    )
    print("DOM:", json.dumps(dom2.get("value")))
    for line in logs2:
        if any(k in line for k in ("Recorded", "historical", "dedup", "Executing", "settling", "dispatch")):
            print(" ", line[:220])

    print("\n=== TEST 2b: NEW block after load (simulates fresh Gemini output) ===")
    time.sleep(6)
    evaluate(
        cdp,
        page_sess,
        """(() => {
          const pre = document.createElement('pre');
          const code = document.createElement('code');
          code.textContent = '{"action":"run_shell","command":"echo gla_live_test_2b"}';
          pre.appendChild(code);
          document.body.appendChild(pre);
          return true;
        })()""",
    )
    time.sleep(8)
    logs2b = drain_agent_logs(cdp, 1.0)
    dom2b = evaluate(
        cdp,
        page_sess,
        "document.body.innerText.includes('gla_live_test_2b')",
    )
    print("DOM 2b output:", dom2b.get("value"))
    for line in logs2b:
        if "Executing" in line or "historical" in line:
            print(" ", line[:220])

    # --- Test 3: ask Gemini for JSON (real UI) ---
    print("\n=== TEST 3: prompt Gemini for action JSON ===")
    prompt = (
        'Reply with ONLY a fenced json code block containing exactly: '
        '{"action":"run_shell","command":"echo gla_live_gemini"}'
    )
    sent = evaluate(
        cdp,
        page_sess,
        f"""(() => {{
          const el = document.querySelector('.ql-editor') || document.querySelector('[contenteditable="true"]');
          if (!el) return {{ ok: false, reason: 'no composer' }};
          el.focus();
          document.execCommand('selectAll', false, null);
          document.execCommand('insertText', false, {json.dumps(prompt)});
          const btn = document.querySelector('button[aria-label="Send message"]');
          const pe = btn ? getComputedStyle(btn).pointerEvents : 'none';
          if (btn && pe !== 'none') {{ btn.click(); return {{ ok: true, sent: true }}; }}
          return {{ ok: true, sent: false, pe }};
        }})()""",
    )
    print("PROMPT:", json.dumps(sent.get("value")))
    if not sent.get("value", {}).get("sent"):
        print("WARN: could not click send — check composer manually")

    for _ in range(24):
        time.sleep(5)
        blocks = evaluate(
            cdp,
            page_sess,
            """(() => {
              const blocks = [...document.querySelectorAll('pre code, code')];
              const hits = blocks.filter(b => (b.textContent||'').includes('"action"'));
              return hits.map(b => ({
                parent: b.parentElement?.tagName,
                classes: b.className,
                len: (b.textContent||'').length,
                snippet: (b.textContent||'').slice(0, 100)
              }));
            })()""",
        )
        val = blocks.get("value") or []
        if val:
            print("GEMINI CODE BLOCKS:", json.dumps(val, indent=2))
            break
    time.sleep(10)
    logs3 = drain_agent_logs(cdp, 1.5)
    dom3 = evaluate(
        cdp,
        page_sess,
        """(() => ({
          bodyHas3: document.body.innerText.includes('gla_live_gemini'),
          systemResult: document.body.innerText.includes('System Result'),
          allCode: document.querySelectorAll('pre code, code').length
        }))()""",
    )
    print("DOM after Gemini:", json.dumps(dom3.get("value")))
    for line in logs3[-25:]:
        print(" ", line[:220])

    log_path = "/home/oreo/Development/Gemini-Chrome-Agent/.cursor/debug-866d96.log"
    try:
        with open(log_path, encoding="utf-8") as f:
            print(f"\n=== DEBUG LOG ({sum(1 for _ in open(log_path))} lines) ===")
            f.seek(0)
            for line in f.readlines()[-10:]:
                print(" ", line.rstrip()[:200])
    except FileNotFoundError:
        print("\n=== DEBUG LOG: empty/missing ===")

    cdp.close()
    ok = dom1.get("value", {}).get("bodyHas") or dom3.get("value", {}).get("bodyHas3")
    print("\nOVERALL:", "PASS" if ok else "FAIL — no command output in page")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 9222))
