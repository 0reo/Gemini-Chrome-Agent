#!/usr/bin/env python3
"""One-shot pipeline diagnosis for the Gemini Chrome Agent.

Reads LIVE runtime state across the 5 pipeline stages and prints a per-stage verdict, so you diagnose
by evidence instead of guessing from source (see the skill's Four Rules). Read-only by default; pass
--probe to also inject a real run_shell payload and verify it round-trips.

Run from the repo root, against a debug Brave started by scripts/launch-debug-brave.sh (CDP :9222):
    python3 .agents/skills/debugging-gemini-agent/scripts/diagnose.py [port] [--probe]

It reuses test/e2e_browser.py's CDP client, so no extra dependencies beyond what that test needs.
"""
import os
import sys
import time

# Locate the repo's test/ dir (which holds e2e_browser.py) by walking up from this script.
_here = os.path.dirname(os.path.abspath(__file__))
_root = _here
for _ in range(8):
    if os.path.isfile(os.path.join(_root, "test", "e2e_browser.py")):
        break
    _root = os.path.dirname(_root)
sys.path.insert(0, os.path.join(_root, "test"))

try:
    from e2e_browser import CDPClient, attach_to_target, evaluate, find_target  # type: ignore
except Exception as exc:  # pragma: no cover - import guard
    print(f"FAIL: could not import test/e2e_browser.py ({exc}).")
    print("      Run from the repo root; ensure test/e2e_browser.py exists.")
    sys.exit(2)

HOST_LOG = "/tmp/gemini_host.log"
PROBE_CMD = "echo gla_diagnose_probe"
PROBE_MARKER = "gla_diagnose_probe"


def _val(cdp, sess, expr, await_promise=False):
    try:
        return evaluate(cdp, sess, expr, await_promise=await_promise).get("value")
    except Exception as exc:
        return {"__error": str(exc)}


def main(port: int = 9222, probe: bool = False) -> int:
    try:
        cdp = CDPClient(port)
    except Exception as exc:
        print(f"FAIL: cannot connect to CDP on :{port} ({exc}).")
        print("      Start the debug browser: ./scripts/launch-debug-brave.sh")
        print("      If it IS running, check for port contention: ss -tlnp | grep", port)
        return 1

    sw = find_target(cdp, lambda t: t["type"] == "service_worker" and "chrome-extension://" in t.get("url", ""))
    page = find_target(cdp, lambda t: t["type"] == "page" and "gemini.google.com" in t.get("url", ""))

    print(f"=== Gemini Chrome Agent — live diagnosis (CDP :{port}) ===")
    print(f"[setup] service worker : {'FOUND' if sw else 'MISSING — extension not loaded / SW asleep'}")
    print(f"[setup] gemini page    : {'FOUND' if page else 'MISSING — open gemini.google.com'}")
    if not page:
        print("\nVERDICT: cannot diagnose without a Gemini tab. Open one and re-run.")
        cdp.close()
        return 1

    page_sess = attach_to_target(cdp, page["targetId"])
    cdp.send("Runtime.enable", session_id=page_sess)
    sw_sess = attach_to_target(cdp, sw["targetId"]) if sw else None
    if sw_sess:
        cdp.send("Runtime.enable", session_id=sw_sess)

    # ---- Stage 2: guards / pause state (read the TRUTH, never infer it) ----
    # chrome.* APIs exist only in extension contexts. Read storage from the SERVICE-WORKER target;
    # the Gemini page's main world has no `chrome`, so a page-context read throws `chrome is undefined`.
    store_expr = (
        "new Promise((r)=>chrome.storage.local.get("
        "['isAgentPaused','autoSubmit','cooldownSeconds','maxPerMinute','settlingSeconds'],r))"
    )
    storage = _val(cdp, sw_sess, store_expr, await_promise=True) if sw_sess else None
    paused = bool(storage.get("isAgentPaused")) if isinstance(storage, dict) and "__error" not in storage else None
    print("\n[stage 2] storage:", storage if sw_sess else "UNREADABLE — no service-worker target")
    if not sw_sess:
        print("[stage 2] SW asleep or extension not loaded — wake it (brave://extensions/ → service worker) "
              "to read pause/guard state. Cannot confirm paused; do NOT assume either way.")
    elif paused is True:
        print("[stage 2] PAUSED — agent will not scan. Resume (Alt+Shift+K / popup) before expecting action.")
    elif paused is False:
        print("[stage 2] not paused (isAgentPaused=false).")
    else:
        print("[stage 2] storage read failed; inspect the raw value above.")

    # ---- Stage 5 FIRST: did it already succeed? ----
    stage5_expr = """
    (() => {
      const ed = document.querySelector('.ql-editor') || document.querySelector('[contenteditable="true"]');
      const send = document.querySelector('button[aria-label="Send message"]');
      return {
        threadHasSystemResult: document.body.innerText.includes('System Result'),
        composerText: ed ? (ed.innerText || ed.textContent || '').slice(0,160) : null,
        composerBlank: ed ? ed.classList.contains('ql-blank') : null,
        sendPointerEvents: send ? getComputedStyle(send).pointerEvents : 'no-send-button',
        codeBlocks: [...document.querySelectorAll('pre code, code')]
          .map(n => (n.textContent||'').slice(0,80)).filter(t => t.includes('action')),
        url: location.href,
      };
    })()
    """
    s5 = _val(cdp, page_sess, stage5_expr)
    print("\n[stage 5] DOM state:", s5)
    if isinstance(s5, dict) and s5.get("threadHasSystemResult"):
        print("[stage 5] A 'System Result:' is present in the thread — a run reached stage 5 here.")
        print("          CONFIRM it corresponds to the USER's payload (not a prior turn or your own test")
        print("          echo) before concluding it worked. A successful run auto-sends and clears the")
        print("          composer, so success can look like 'nothing happened' — but do not assume it.")

    # ---- Stage 4: host log ----
    print("\n[stage 4] host log:", HOST_LOG)
    try:
        with open(HOST_LOG, encoding="utf-8") as fh:
            tail = fh.readlines()[-8:]
        if tail:
            for ln in tail:
                print("   ", ln.rstrip()[:200])
        else:
            print("    (empty) — host launched but processed nothing")
    except FileNotFoundError:
        print("    MISSING — host has never been launched by the browser (extension-ID / manifest / symlink).")

    if not probe:
        print("\n(Read-only pass. Re-run with --probe to inject a real payload and verify the round trip.)")
        cdp.close()
        return 0

    # ---- Optional active probe: inject a real run_shell block, then re-check stages 4 & 5 ----
    if paused:
        print("\n[probe] skipped: agent is paused. Resume first, then re-run with --probe.")
        cdp.close()
        return 0
    print("\n[probe] injecting a real <pre><code> run_shell payload …")
    _val(cdp, page_sess, f"""
    (() => {{
      const pre=document.createElement('pre'); const code=document.createElement('code');
      code.className='language-json';
      code.textContent='{{"action":"run_shell","command":"{PROBE_CMD}"}}';
      pre.appendChild(code); document.body.appendChild(pre); return true;
    }})()
    """)
    deadline = time.time() + 12
    host_ok = dom_ok = False
    while time.time() < deadline:
        time.sleep(2)
        try:
            with open(HOST_LOG, encoding="utf-8") as fh:
                if PROBE_MARKER in fh.read():
                    host_ok = True
        except FileNotFoundError:
            pass
        s5b = _val(cdp, page_sess, stage5_expr)
        if isinstance(s5b, dict) and PROBE_MARKER in (s5b.get("composerText") or ""):
            dom_ok = True
        if isinstance(s5b, dict) and s5b.get("threadHasSystemResult"):
            dom_ok = True
        if host_ok and dom_ok:
            break
    print(f"[probe] host received payload : {'YES' if host_ok else 'NO (stage 1-3 broke — see console surfaces)'}")
    print(f"[probe] result reached the DOM: {'YES' if dom_ok else 'NO (stage 5 inject/send — check ql-blank + Send pointer-events)'}")
    print("[probe] FALSE-GREEN WARNING: this injects a FRESH post-load block — it tests the happy path,")
    print("        NOT the user's 'JSON already on screen at load' condition. A green here does NOT mean")
    print("        the user's bug is absent. To reproduce a load-time guard (historical-block-skip),")
    print("        put the block in the DOM and RELOAD the tab, then re-run without --probe.")
    print("[probe] note: the injected <pre> stays in the page DOM; reload the tab to clear it.")
    cdp.close()
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    do_probe = "--probe" in args
    args = [a for a in args if a != "--probe"]
    p = int(args[0]) if args else 9222
    sys.exit(main(p, do_probe))
