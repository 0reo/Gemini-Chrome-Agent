"""Drive Gemini composer: Quill insert + InputEvent + Send poll."""

from __future__ import annotations

import json
import time

from .harness import BrowserSession, page_eval

# Keep in sync with ACTION_BLOCK_SELECTOR in entrypoints/content.ts
ACTION_BLOCK_SELECTOR_JS = "'pre code, code, pre code.language-json, pre code.hljs'"


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
              const busy = document.querySelector(
                'mat-spinner, [aria-busy="true"], .loading-response, .thinking');
              const send = document.querySelector('button[aria-label="Send message"]');
              return { busy: !!busy, sendPe: send ? getComputedStyle(send).pointerEvents : 'none' };
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
      const before = (el.innerText || el.textContent || '').trim().length;
      if (before > 0) {
        document.execCommand('selectAll', false, undefined);
        document.execCommand('delete', false, undefined);
      }
      const after = (el.innerText || el.textContent || '').trim().length;
      return {
        ok: true,
        cleared: before > 0,
        len: after,
        qlBlank: el.classList.contains('ql-blank'),
      };
    })()"""


def wait_composer_clear(sess: BrowserSession, timeout_s: float = 15.0) -> bool:
    deadline = time.time() + timeout_s
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
            return True
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
    if not wait_composer_ready(sess):
        return {"ok": False, "reason": "composer_not_ready"}
    wait_gemini_idle(sess)
    if not wait_composer_clear(sess):
        return {"ok": False, "reason": "composer_not_clear"}
    payload = json.dumps(text)
    insert_js = f"""(() => {{
      const el = document.querySelector('.ql-editor.textarea') || document.querySelector('.ql-editor');
      if (!el) return {{ ok: false, reason: 'no_composer' }};
      el.focus();
      const existing = (el.innerText || el.textContent || '').trim();
      if (existing.length > 0) {{
        document.execCommand('selectAll', false, undefined);
        document.execCommand('delete', false, undefined);
      }}
      document.execCommand('insertText', false, {payload});
      return {{
        ok: true,
        composerLen: (el.innerText || el.textContent || '').trim().length,
        qlBlank: el.classList.contains('ql-blank'),
      }};
    }})()"""
    click_js = """(() => {
      const findBtn = () => document.querySelector('button[aria-label="Send message"]');
      const ready = (btn) => btn && getComputedStyle(btn).pointerEvents !== 'none';
      const el = document.querySelector('.ql-editor.textarea') || document.querySelector('.ql-editor');
      if (!el) return { ok: false, reason: 'no_composer' };
      const len = (el.innerText || el.textContent || '').trim().length;
      const sendBtn = findBtn();
      if (sendBtn && len > 0 && ready(sendBtn)) {
        sendBtn.click();
        return { ok: true, sent: true, composerLen: len };
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

    for attempt in range(2):
        if attempt > 0:
            wait_composer_clear(sess)
            wait_gemini_idle(sess)
        inserted = page_eval(sess, insert_js).get("value") or {}
        if not inserted.get("ok"):
            return inserted if inserted else {"ok": False, "reason": "insert_failed"}
        deadline = time.time() + timeout_s
        val: dict = {"ok": False, "sent": False, "reason": "send_not_armed"}
        while time.time() < deadline:
            val = page_eval(sess, click_js).get("value") or val
            if val.get("sent"):
                time.sleep(3)
                return val
            time.sleep(0.15)
        if attempt == 0:
            continue
        return val
    return {"ok": False, "reason": "send_exhausted"}


def click_new_chat(sess: BrowserSession) -> bool:
    r = page_eval(
        sess,
        """(() => {
          const byAria = document.querySelector(
            'button[aria-label="New chat"], a[aria-label="New chat"], button[aria-label="New Chat"]');
          if (byAria) { byAria.click(); return { ok: true, via: 'aria' }; }
          const el = [...document.querySelectorAll('a,button')].find(e =>
            /new chat/i.test((e.textContent||'') + (e.getAttribute('aria-label')||'')));
          if (el) { el.click(); return { ok: true, via: 'text' }; }
          location.href = 'https://gemini.google.com/app';
          return { ok: true, via: 'navigate' };
        })()""",
    )
    val = r.get("value") or {}
    if val.get("ok"):
        time.sleep(3)
    return bool(val.get("ok"))


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


def _gemini_said_count(sess: BrowserSession) -> int:
    r = page_eval(
        sess,
        """(() => (document.body.innerText.match(/Gemini said/g) || []).length)()""",
    )
    return int(r.get("value") or 0)


def wait_for_gemini_reply(
    sess: BrowserSession,
    timeout_s: float = 120.0,
    baseline_said: int | None = None,
) -> bool:
    """Wait until a new model turn appears (Gemini said count increases)."""
    if baseline_said is None:
        baseline_said = _gemini_said_count(sess)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _gemini_said_count(sess) > baseline_said:
            return True
        time.sleep(2.0)
    return False


def wait_for_action_codeblock(
    sess: BrowserSession,
    must_contain: str,
    timeout_s: float = 300.0,
    poll_s: float = 3.0,
) -> list[dict]:
    """Wait until a model code block with valid action JSON appears (stage 1)."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = page_eval(
            sess,
            f"""(() => {{
              const needle = {json.dumps(must_contain)};
              return [...document.querySelectorAll('pre code, code')]
                .filter(b => {{
                  const t = b.textContent || '';
                  if (!t.includes('"action"') || !t.includes(needle)) return false;
                  try {{
                    JSON.parse(t.trim());
                    return true;
                  }} catch {{ return false; }}
                }})
                .map(b => ({{
                  tag: b.tagName,
                  parent: b.parentElement?.tagName,
                  snippet: (b.textContent||'').slice(0, 150),
                }}));
            }})()""",
        )
        val = r.get("value") or []
        if val:
            return val
        time.sleep(poll_s)
    return []
