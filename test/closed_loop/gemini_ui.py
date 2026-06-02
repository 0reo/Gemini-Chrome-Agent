"""Drive Gemini composer: Quill insert + InputEvent + Send poll."""

from __future__ import annotations

import json
import os
import time

from .harness import BrowserSession, log_step, page_eval

# Keep in sync with ACTION_BLOCK_SELECTOR in entrypoints/content.ts
ACTION_BLOCK_SELECTOR_JS = "'pre code, code, pre code.language-json, pre code.hljs'"


def _fresh_chat_url() -> str:
    """Where ensure_fresh_chat lands a new thread.

    Tier B must run *inside the gem* — bare Gemini (/app) refuses local-agent
    shell actions because the model's safety layer fires; the gem's identical
    instructions, delivered as *system instructions*, suppress that refusal
    (verified live 2026-06-02: the same run_shell prompt → `action:error` on
    /app, clean emission + full host roundtrip under the gem). Set GLA_GEM_URL
    (or GLA_GEM_ID) to the debug profile's "Gemini Local Agent" gem; without it
    the harness falls back to /app and shell scenarios will hit the refusal.
    """
    url = os.environ.get("GLA_GEM_URL", "").strip()
    if url:
        return url
    gem_id = os.environ.get("GLA_GEM_ID", "").strip()
    if gem_id:
        return f"https://gemini.google.com/gem/{gem_id}"
    return "https://gemini.google.com/app"


def trigger_rerun_latest(sess: BrowserSession) -> dict:
    """Trigger rerun via the content script's window.postMessage listener (single channel)."""
    try:
        result = page_eval(
            sess,
            "(() => { window.postMessage({ __gla: 'rerun-latest' }, '*'); return { ok: true, via: 'postMessage' }; })()",
        )
    except Exception as exc:
        return {"ok": False, "reason": "postMessage_failed", "error": str(exc)}
    val = result.get("value")
    if not val:
        return {"ok": False, "reason": "postMessage_no_result"}
    return val


def audit_action_dom(sess: BrowserSession) -> dict:
    """Find elements containing \"action\" and check scanner selector coverage."""
    r = page_eval(
        sess,
        f"""(() => {{
          const scannerSel = {ACTION_BLOCK_SELECTOR_JS};
          const scanned = new Set([...document.querySelectorAll(scannerSel)]);
          const lines = [];
          const uncoveredWithAction = [];
          const walk = (root) => {{
            const nodes = root.querySelectorAll
              ? [...root.querySelectorAll('*')].filter(el => {{
                  const t = el.textContent || '';
                  return t.includes('"action"') && t.length < 8000;
                }})
              : [];
            return nodes;
          }};
          const candidates = walk(document.body).slice(0, 40);
          for (const el of candidates) {{
            const inScan = scanned.has(el) || [...scanned].some(s => s.contains(el) || el.contains(s));
            const row = {{
              tag: el.tagName,
              parent: el.parentElement?.tagName,
              className: (el.className || '').toString().slice(0, 80),
              inScanner: inScan,
              snippet: (el.textContent || '').slice(0, 100),
            }};
            lines.push(JSON.stringify(row));
            if (!inScan && (el.textContent||'').includes('"action"')) {{
              uncoveredWithAction.push(row);
            }}
          }}
          return {{
            lines,
            uncoveredWithAction,
            scannedCount: scanned.size,
            candidateCount: candidates.length,
          }};
        }})()""",
    )
    return r.get("value") or {"lines": [], "uncoveredWithAction": []}


def ensure_fast_model(sess: BrowserSession) -> dict:
    """Prefer Gemini Flash or Thinking over Pro (faster, more reliable for E2E)."""
    r = page_eval(
        sess,
        """(() => {
          const prefer = (label) => {
            const t = (label || '').toLowerCase();
            if (/\\bpro\\b/.test(t) && !/flash/.test(t)) return false;
            return /flash/.test(t) || /thinking/.test(t) || /2\\.5\\s*flash/.test(t);
          };
          const clickEl = (el) => { try { el.click(); return true; } catch { return false; } };
          const all = [...document.querySelectorAll('button, [role="menuitem"], [role="option"], li, span')];
          const labels = all.map(el => ({
            el,
            text: ((el.getAttribute('aria-label') || '') + ' ' + (el.textContent || '')).trim(),
          }));
          const current = labels.find(x => /gemini/i.test(x.text) && x.text.length < 80);
          if (current && prefer(current.text)) {
            return { ok: true, already: true, model: current.text.slice(0, 60) };
          }
          const opener = [...document.querySelectorAll('button')].find(b => {
            const t = ((b.getAttribute('aria-label') || '') + ' ' + (b.textContent || '')).toLowerCase();
            return /model|gemini\\s*\\d|switch model|choose model/.test(t);
          });
          if (opener) clickEl(opener);
          const pick = labels.find(x => prefer(x.text) && x.text.length < 60);
          if (pick) {
            clickEl(pick.el);
            return { ok: true, selected: pick.text.slice(0, 60) };
          }
          return { ok: false, reason: 'no_flash_or_thinking_option', current: current?.text?.slice(0, 60) };
        })()""",
    )
    val = r.get("value") or {"ok": False}
    if val.get("ok") and not val.get("already"):
        time.sleep(1.5)
    return val


def wait_composer_ready(sess: BrowserSession, timeout_s: float = 20.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = page_eval(
            sess,
            """(() => {
              const el = document.querySelector('.ql-editor.textarea')
                || document.querySelector('.ql-editor')
                || document.querySelector('rich-textarea .ql-editor');
              return !!el;
            })()""",
        )
        if r.get("value"):
            return True
        time.sleep(0.5)
    return False


def wait_gemini_idle(sess: BrowserSession, timeout_s: float = 30.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = page_eval(
            sess,
            """(() => {
              const responses = [...document.querySelectorAll('model-response')];
              const latest = responses.length ? responses[responses.length - 1] : null;
              const streaming = latest && latest.querySelector(
                '.processing-state-visible, mat-spinner, .thinking, [aria-busy="true"], .loading-response');
              const send = document.querySelector('button[aria-label="Send message"]')
                || document.querySelector('button.send');
              return {
                busy: !!streaming,
                sendPe: send ? getComputedStyle(send).pointerEvents : 'none',
                responseCount: responses.length,
              };
            })()""",
        )
        v = r.get("value") or {}
        if not v.get("busy"):
            return True
        time.sleep(0.5)
    return False


def _clear_composer_js() -> str:
    """Clear leftover System Result / prior text (matches utils/injection.ts)."""
    return """(() => {
      const el = document.querySelector('.ql-editor.textarea') || document.querySelector('.ql-editor');
      if (!el) return { ok: false, reason: 'no_composer' };
      el.focus();
      for (let i = 0; i < 3; i++) {
        const len = (el.innerText || el.textContent || '').trim().length;
        if (len === 0 || el.classList.contains('ql-blank')) break;
        document.execCommand('selectAll', false, undefined);
        document.execCommand('delete', false, undefined);
      }
      const after = (el.innerText || el.textContent || '').trim().length;
      return {
        ok: true,
        len: after,
        qlBlank: el.classList.contains('ql-blank'),
      };
    })()"""


def _try_flush_composer_send(sess: BrowserSession) -> None:
    """If a prior System Result left text armed in Quill, submit it so turn 2 can type."""
    page_eval(
        sess,
        """(() => {
          const findBtn = () => document.querySelector('button.send')
            || document.querySelector('button[aria-label="Send message"]')
            || [...document.querySelectorAll('button')].find(b =>
              (b.className||'').toString().split(/\\s+/).includes('send'));
          const btn = findBtn();
          const el = document.querySelector('.ql-editor.textarea') || document.querySelector('.ql-editor');
          if (btn && el && getComputedStyle(btn).pointerEvents !== 'none') {
            btn.click();
          }
        })()""",
    )
    time.sleep(2.0)


def wait_composer_clear(sess: BrowserSession, timeout_s: float = 15.0) -> bool:
    log_step("wait_composer_clear: waiting for blank composer")
    deadline = time.time() + timeout_s
    flushed = False
    while time.time() < deadline:
        page_eval(sess, _clear_composer_js())
        r = page_eval(
            sess,
            """(() => {
              const el = document.querySelector('.ql-editor') || document.querySelector('.ql-editor.textarea');
              if (!el) return false;
              const len = (el.innerText || el.textContent || '').trim().length;
              return el.classList.contains('ql-blank') || len === 0;
            })()""",
        )
        if r.get("value"):
            log_step("wait_composer_clear: composer blank")
            return True
        if not flushed:
            _try_flush_composer_send(sess)
            flushed = True
        time.sleep(0.5)
    return False


def send_prompt(
    sess: BrowserSession,
    text: str,
    timeout_s: float = 25.0,
    thread_needle: str | None = None,
) -> dict:
    """Insert prompt into Quill and click Send when armed."""
    del thread_needle  # reserved for callers; thread verified via wait_for_* helpers
    preview = text[:60].replace("\n", " ")
    log_step(f"send_prompt: start ({preview!r}…)")
    if not wait_composer_ready(sess):
        return {"ok": False, "reason": "composer_not_ready"}
    wait_gemini_idle(sess)
    if not wait_composer_clear(sess):
        return {"ok": False, "reason": "composer_not_clear"}
    payload = json.dumps(text)
    snippet = json.dumps(text[-80:])  # unique tail (path/marker), NOT the shared preamble
    insert_js = f"""(() => {{
      const el = document.querySelector('.ql-editor.textarea') || document.querySelector('.ql-editor');
      if (!el) return {{ ok: false, reason: 'no_composer' }};
      el.focus();
      // Gemini's new-input-ui composer arms/submits off Quill's MODEL, and execCommand no longer
      // updates the model (DOM/model desync — #16). Set the model via the Quill API so Send arms.
      let q = null, node = el;
      for (let i = 0; i < 6 && node; i++) {{ if (node.__quill) {{ q = node.__quill; break; }} node = node.parentElement; }}
      if (q && q.setText) {{
        // 'user' source is REQUIRED: it makes Quill emit text-change as user input, which is
        // what arms Gemini's Send button on new-input-ui. Default 'api' syncs the model but
        // leaves Send disabled (#16).
        q.setText({payload}, 'user');
        try {{ q.setSelection(q.getLength(), 0); }} catch (e) {{}}
      }} else {{
        // fallback (old UI / no quill instance): place a caret, then execCommand
        try {{
          const sel = window.getSelection();
          const range = document.createRange();
          range.selectNodeContents(el);
          range.collapse(false);
          sel.removeAllRanges();
          sel.addRange(range);
        }} catch (e) {{}}
        if ((el.innerText || el.textContent || '').trim().length > 0) {{
          document.execCommand('selectAll', false, undefined);
          document.execCommand('delete', false, undefined);
        }}
        document.execCommand('insertText', false, {payload});
      }}
      return {{
        ok: true,
        via: q ? 'quill' : 'execCommand',
        composerLen: (el.innerText || el.textContent || '').trim().length,
        qlBlank: el.classList.contains('ql-blank'),
      }};
    }})()"""
    click_js = """(() => {
      const findBtn = () => {
        const sels = [
          'button[aria-label="Send message"]',
          'button[aria-label*="Send"]',
          'button[mattooltip*="Send"]',
          'button[data-testid="send-button"]',
          'button.send-button',
          'button.send',
          'button[class*=" send"]',
        ];
        for (const s of sels) {
          const b = document.querySelector(s);
          if (b) return b;
        }
        return [...document.querySelectorAll('button')].find(b => {
          const label = ((b.getAttribute('aria-label') || '') + ' ' + (b.textContent || '')).toLowerCase();
          if (label.includes('send')) return true;
          return (b.className || '').toString().split(/\\s+/).includes('send');
        }) || null;
      };
      const ready = (btn) => btn && getComputedStyle(btn).pointerEvents !== 'none';
      const el = document.querySelector('.ql-editor.textarea') || document.querySelector('.ql-editor');
      if (!el) return { ok: false, reason: 'no_composer' };
      const len = (el.innerText || el.textContent || '').trim().length;
      const sendBtn = findBtn();
      if (sendBtn && len > 0 && ready(sendBtn)) {
        sendBtn.click();
        return { ok: true, clicked: true, composerLen: len };
      }
      return {
        ok: false,
        sent: false,
        reason: 'send_not_armed',
        pe: sendBtn ? getComputedStyle(sendBtn).pointerEvents : 'no-btn',
        qlBlank: el.classList.contains('ql-blank'),
        composerLen: len,
      };
    })()"""

    submit_enter_js = f"""(() => {{
      const el = document.querySelector('.ql-editor.textarea') || document.querySelector('.ql-editor');
      if (!el) return {{ ok: false, reason: 'no_composer' }};
      const beforeLen = (el.innerText || el.textContent || '').trim().length;
      if (beforeLen === 0) return {{ ok: false, reason: 'composer_empty' }};
      el.focus();
      el.dispatchEvent(new KeyboardEvent('keydown', {{
        key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true,
      }}));
      el.dispatchEvent(new KeyboardEvent('keypress', {{
        key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true,
      }}));
      el.dispatchEvent(new KeyboardEvent('keyup', {{
        key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true, cancelable: true,
      }}));
      const afterLen = (el.innerText || el.textContent || '').trim().length;
      const inThread = document.body.innerText.includes({snippet});
      return {{
        ok: true,
        sent: afterLen < beforeLen || inThread,
        via: 'enter',
        beforeLen,
        afterLen,
        inThread,
      }};
    }})()"""

    # A send is only "sent" when the composer ACTUALLY clears (the message left the box). Matching
    # thread text is a false positive (the prompt's preamble repeats every turn); a click that "ran"
    # proves nothing. So success = composer emptied. (Rule 5 / driving-layer twin of #15.)
    cleared_check_js = """(() => {
      const el = document.querySelector('.ql-editor.textarea') || document.querySelector('.ql-editor');
      if (!el) return { composerEmpty: false, composerLen: -1 };
      const len = (el.innerText || el.textContent || '').trim().length;
      return { composerEmpty: len === 0 || el.classList.contains('ql-blank'), composerLen: len };
    })()"""

    for attempt in range(2):
        if attempt > 0:
            wait_composer_clear(sess)
            wait_gemini_idle(sess)
        inserted = page_eval(sess, insert_js).get("value") or {}
        if not inserted.get("ok"):
            return inserted if inserted else {"ok": False, "reason": "insert_failed"}
        log_step(f"send_prompt: inserted ({inserted.get('composerLen', '?')} chars)")
        if not inserted.get("composerLen"):
            if attempt == 0:
                log_step("send_prompt: 0 chars inserted; retrying with fresh focus")
                continue
            log_step("send_prompt: 0 chars inserted after retry; failing")
            return {"ok": False, "sent": False, "reason": "insert_empty"}
        deadline = time.time() + timeout_s
        clicked = False
        tried_enter = False
        while time.time() < deadline:
            cleared = page_eval(sess, cleared_check_js).get("value") or {}
            if cleared.get("composerEmpty"):
                via = "enter" if tried_enter else "click"
                log_step(f"send_prompt: submit CONFIRMED via {via} (composer cleared)")
                time.sleep(2)
                return {"ok": True, "sent": True, "via": f"verified-{via}"}
            if not clicked:
                c = page_eval(sess, click_js).get("value") or {}
                if c.get("clicked"):
                    clicked = True
                    log_step("send_prompt: clicked Send; verifying it actually submits")
            if not tried_enter and time.time() > deadline - timeout_s * 0.5:
                page_eval(sess, submit_enter_js)
                tried_enter = True
                log_step("send_prompt: click did not submit yet; tried Enter")
            time.sleep(0.25)
        log_step(
            "send_prompt: submit NOT confirmed — composer never cleared "
            f"(clicked={clicked}, enter={tried_enter}); the message did NOT send"
        )
        if attempt == 0:
            continue
        return {
            "ok": False, "sent": False, "reason": "submit_not_confirmed",
            "clicked": clicked, "triedEnter": tried_enter,
        }
    return {"ok": False, "sent": False, "reason": "send_exhausted"}


def _recover_for_retry(sess: BrowserSession) -> None:
    """Best-effort: settle Gemini and clear the composer before a re-send."""
    wait_gemini_idle(sess, timeout_s=30.0)
    wait_composer_clear(sess, timeout_s=15.0)
    time.sleep(2)


def send_until_action(
    sess: BrowserSession,
    text: str,
    action_or_marker: str,
    *,
    retries: int = 3,
    reply_timeout_s: float = 60.0,
    action_timeout_s: float = 90.0,
    validate=None,
) -> list:
    """Send `text` and wait for Gemini to emit an action codeblock matching
    `action_or_marker`, re-sending the SAME prompt up to `retries` times.

    The live model intermittently doesn't reply, or replies without the JSON
    action block. Each retry is logged loudly ('send-retry N/R: ...'). ONLY the
    send/await-emit step is retried here — callers keep their downstream host-gated
    assertions un-retried, so a genuinely broken pipeline still fails the scenario
    (no false greens). Returns the matching blocks; raises PipelineFailure when exhausted.
    """
    from .pipeline_assert import PipelineFailure  # sibling module; local import avoids cycle

    last = "unknown"
    for attempt in range(1, retries + 1):
        baseline = _model_reply_count(sess)
        sent = send_prompt(sess, text, timeout_s=45.0)
        if not sent.get("sent"):
            last = f"send not confirmed ({sent.get('reason')})"
        elif not wait_for_gemini_reply(sess, timeout_s=reply_timeout_s, baseline_said=baseline):
            last = "Gemini did not reply"
        else:
            blocks = wait_for_action_codeblock(sess, action_or_marker, timeout_s=action_timeout_s)
            if blocks and (validate is None or validate(blocks)):
                if attempt > 1:
                    log_step(f"send-retry: emitted {action_or_marker!r} on attempt {attempt}/{retries}")
                return blocks
            last = f"no action block for {action_or_marker!r}"
        log_step(f"send-retry {attempt}/{retries}: {last}")
        if attempt < retries:
            _recover_for_retry(sess)
    raise PipelineFailure(
        "stage1", f"Gemini did not emit {action_or_marker!r} after {retries} sends ({last})"
    )


def click_new_chat(sess: BrowserSession) -> bool:
    target = _fresh_chat_url()
    # A configured gem must be entered by URL: the sidebar "New chat" control
    # leaves the gem and drops back to bare Gemini (/app), where shell actions
    # are refused. Navigating to the gem URL opens a fresh thread under it.
    if "/gem/" in target:
        page_eval(sess, f"location.href = {json.dumps(target)};")
        time.sleep(3)
        return True
    r = page_eval(
        sess,
        """(() => {
          const clickEl = (el) => { try { el.click(); return true; } catch { return false; } };
          const sidebar = document.querySelector('button[aria-label="Open sidebar"]');
          if (sidebar && getComputedStyle(sidebar).pointerEvents !== 'none') clickEl(sidebar);
          const selectors = [
            'button[aria-label="New chat"]',
            'a[aria-label="New chat"]',
            'button[aria-label="New Chat"]',
            'a[aria-label="New Chat"]',
            'button[aria-label*="New chat"]',
          ];
          for (const s of selectors) {
            const el = document.querySelector(s);
            if (el && clickEl(el)) return { ok: true, via: 'aria', sel: s };
          }
          const el = [...document.querySelectorAll('a,button,[role="button"]')].find(e =>
            /new chat/i.test((e.textContent||'') + (e.getAttribute('aria-label')||'')));
          if (el && clickEl(el)) return { ok: true, via: 'text' };
          location.href = 'https://gemini.google.com/app';
          return { ok: true, via: 'navigate' };
        })()""",
    )
    val = r.get("value") or {}
    if val.get("ok"):
        time.sleep(3)
    return bool(val.get("ok"))


def _response_count(sess: BrowserSession) -> int:
    r = page_eval(
        sess,
        """(() => document.querySelectorAll('model-response').length)()""",
    )
    return int(r.get("value") or 0)


def ensure_fresh_chat(sess: BrowserSession) -> None:
    """Start a clean chat thread (no stale model-response nodes)."""
    target = _fresh_chat_url()
    for attempt in range(3):
        click_new_chat(sess)
        if _response_count(sess) == 0:
            return
        page_eval(sess, f"location.href = {json.dumps(target)};")
        time.sleep(4)
    if _response_count(sess) > 0:
        raise PipelineFailure(
            "setup",
            f"could not start fresh Gemini chat ({_response_count(sess)} stale responses)",
        )


def prompt_visible_in_thread(sess: BrowserSession, needle: str, timeout_s: float = 25.0) -> bool:
    import json as _json

    snippet = _json.dumps(needle)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = page_eval(
            sess,
            f"""(() => document.body.innerText.includes({snippet}))()""",
        )
        if r.get("value"):
            return True
        time.sleep(1.0)
    return False


def stage5_probe(sess: BrowserSession) -> dict:
    r = page_eval(
        sess,
        """(() => {
          const ed = document.querySelector('.ql-editor') || document.querySelector('[contenteditable="true"]');
          const send = document.querySelector('button[aria-label="Send message"]');
          const codes = [...document.querySelectorAll('pre code, code')]
            .filter(c => (c.textContent||'').includes('"action"'))
            .map(c => (c.textContent||'').slice(0, 120));
          return {
            threadHasSystemResult: document.body.innerText.includes('System Result'),
            composerText: ed ? (ed.innerText || ed.textContent || '').slice(0, 200) : null,
            composerBlank: ed ? ed.classList.contains('ql-blank') : null,
            sendPointerEvents: send ? getComputedStyle(send).pointerEvents : 'no-send-button',
            codeBlocks: codes,
            url: location.href,
          };
        })()""",
    )
    return r.get("value") or {}


def wait_for_thread_marker(
    sess: BrowserSession,
    marker: str,
    timeout_s: float = 90.0,
    poll_s: float = 3.0,
) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = page_eval(
            sess,
            f"""(() => {{
              const t = document.body.innerText;
              return t.includes({json.dumps(marker)});
            }})()""",
        )
        if r.get("value"):
            return True
        time.sleep(poll_s)
    return False


def _model_reply_count(sess: BrowserSession) -> int:
    """Count model reply turns structurally via <model-response> elements.

    Do NOT scrape the localized "Gemini said" string: under a gem the reply is
    attributed "<GemName> said" (e.g. "Gemini Local Agent said"), which contains
    no "Gemini said" substring — so a text match silently never increments and
    every send looks like "Gemini did not reply" (false stage-1 failure). The
    element count is attribution-agnostic and also can't collide with the user's
    own "You said" turns.
    """
    r = page_eval(
        sess,
        """(() => document.querySelectorAll('model-response').length)()""",
    )
    return int(r.get("value") or 0)


def wait_for_gemini_reply(
    sess: BrowserSession,
    timeout_s: float = 120.0,
    baseline_said: int | None = None,
) -> bool:
    """Wait until a new model turn appears (model-response count increases)."""
    if baseline_said is None:
        baseline_said = _model_reply_count(sess)
    log_step(f"wait_for_gemini_reply: waiting (baseline={baseline_said})")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _model_reply_count(sess) > baseline_said:
            log_step("wait_for_gemini_reply: new reply detected")
            return True
        time.sleep(2.0)
    return False


def _action_json_probe_js(must_contain: str) -> str:
    """JS that finds action JSON blocks (matches content.ts selector + tolerant parse)."""
    needle = json.dumps(must_contain)
    selector = ACTION_BLOCK_SELECTOR_JS
    return f"""(() => {{
      const needle = {needle};
      const parseAction = (raw) => {{
        const t = (raw || '').trim();
        if (!t.includes('"action"') || !t.includes(needle)) return false;
        const attempts = [t, t.replace(/^JSON\\s*/i, '').trim()];
        const brace = t.match(/\\{{[\\s\\S]*\\}}/);
        if (brace) attempts.push(brace[0]);
        for (const s of attempts) {{
          try {{
            const o = JSON.parse(s);
            if (o && typeof o.action === 'string') return true;
          }} catch {{}}
        }}
        return false;
      }};
      const seen = new Set();
      const out = [];
      for (const b of document.querySelectorAll({selector})) {{
        if (seen.has(b)) continue;
        seen.add(b);
        if (!parseAction(b.textContent)) continue;
        out.push({{
          tag: b.tagName,
          parent: b.parentElement?.tagName,
          snippet: (b.textContent||'').slice(0, 150),
        }});
      }}
      for (const pre of document.querySelectorAll('pre')) {{
        if (seen.has(pre)) continue;
        seen.add(pre);
        if (!parseAction(pre.textContent)) continue;
        out.push({{
          tag: pre.tagName,
          parent: pre.parentElement?.tagName,
          snippet: (pre.textContent||'').slice(0, 150),
        }});
      }}
      return out;
    }})()"""


def wait_for_action_codeblock(
    sess: BrowserSession,
    must_contain: str,
    timeout_s: float = 300.0,
    poll_s: float = 3.0,
) -> list[dict]:
    """Wait until a model code block with valid action JSON appears (stage 1)."""
    probe = _action_json_probe_js(must_contain)
    log_step(f"wait_for_action_codeblock: waiting for action JSON ({must_contain!r})")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = page_eval(sess, probe)
        val = r.get("value") or []
        if val:
            log_step(f"wait_for_action_codeblock: found {len(val)} block(s)")
            return val
        time.sleep(poll_s)
    return []
