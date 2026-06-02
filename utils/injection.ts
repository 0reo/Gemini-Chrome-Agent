import { CONFIG } from './config';
import { info, warn, error } from './logger';

/**
 * Check if the user is currently typing in the given input element.
 * Returns true if the element is focused and has user-typed content.
 */
function isUserActivelyTyping(el: HTMLElement): boolean {
  // Element must be the currently focused element
  if (document.activeElement !== el) return false;

  const text = getElementText(el);
  // If empty or only whitespace, user isn't actively typing
  if (!text || text.trim().length === 0) return false;

  // If the text is only a previous system result, the user didn't type it
  if (text.trimStart().startsWith('System Result:')) return false;

  return true;
}

function getElementText(el: HTMLElement): string {
  if (el instanceof HTMLTextAreaElement) {
    return el.value;
  }
  return el.innerText || el.textContent || '';
}

/** Inject raw text into Gemini's composer (Quill). Returns true if handed to the page composer. */
export function injectText(fullText: string): boolean {
  const editor = (document.querySelector('.ql-editor.textarea')
    || document.querySelector('.ql-editor')
    || document.querySelector('[role="textbox"][contenteditable="true"]')
    || document.querySelector('rich-textarea [contenteditable="true"]')
    || document.querySelector('textarea')) as HTMLElement | null;
  if (!editor) {
    error('Could not find any injectable input element');
    return false;
  }
  // CRITICAL: do not overwrite what the user is actively typing.
  if (isUserActivelyTyping(editor)) {
    warn('Injection skipped: user is actively typing in the input');
    return false;
  }
  // Gemini's new-input-ui composer arms/submits off Quill's MODEL, and execCommand no longer
  // updates the model from this isolated content-script world (DOM/model desync — issue #16).
  // Hand the text to the MAIN-world bridge (entrypoints/uploader.content.ts), which can call
  // Quill's API directly. triggerSend() then clicks once the synced model arms the button.
  window.postMessage({ __gla: 'quill-set', text: fullText }, '*');
  info('Text dispatched to page composer (Quill MAIN-world bridge)');
  return true;
}

export function injectResponse(data: { output?: string; error?: string; message?: string }): boolean {
  const outputText = data?.output || data?.error || data?.message || 'Command completed.';
  return injectText(`System Result:\n${outputText}`);
}

/**
 * Click Gemini's Send button once it becomes ready.
 *
 * Subtleties, all verified against the live Gemini DOM:
 *  - Gemini gates Send via `pointer-events: none`, NOT the native `disabled`
 *    property (which stays false even when the box is empty). So readiness is
 *    tested via computed pointer-events, not `button.disabled`.
 *  - After injection, Quill updates its model on a microtask and Angular arms
 *    the button a tick later — Send is never ready synchronously.
 *  - **Auto-submit is usually requested mid-generation (issue #18).** The
 *    content script scans + executes the action block and injects the System
 *    Result while Gemini is *still finishing its turn*: the composer shows the
 *    Stop button, and the real Send button does not exist (let alone arm) until
 *    generation completes ~seconds later (measured: arm at ~4.9s). So we wait
 *    out generation (no click while a Stop button is present) rather than racing
 *    a fixed timeout from injection.
 *  - **A single synthetic click intermittently does not submit** on this Angular
 *    composer (#18). So we don't fire-and-forget: we click when armed, then
 *    confirm the composer actually cleared, and re-click every SEND_READY_TIMEOUT_MS
 *    until it does — bounded by SEND_ABSOLUTE_CAP_MS, after which the result is
 *    left for manual submit.
 *  - Poll ONLY reads state (no event dispatching, so no main-thread spam — that
 *    spam was the old freeze).
 */
export function triggerSend(): void {
  info('triggerSend: awaiting Send (waits out generation, retries until submitted)');
  const buttonSelectors = [
    'button[aria-label="Send message"]',
    'button[aria-label*="Send"]',
    'button[mattooltip*="Send"]',
    'button[data-testid="send-button"]',
    'button.send-button',
    'button[aria-label*="send"]',
  ];

  const findButton = (): HTMLButtonElement | null => {
    for (const selector of buttonSelectors) {
      const btn = document.querySelector<HTMLButtonElement>(selector);
      if (btn) return btn;
    }
    return (
      Array.from(document.querySelectorAll('button')).find((btn) => {
        const label = (btn.getAttribute('aria-label') || btn.innerText || '').toLowerCase();
        return label.includes('send');
      }) as HTMLButtonElement | undefined
    ) || null;
  };

  // Gemini is still producing its turn while a Stop button is present; the Send
  // button only (re)appears once generation finishes.
  const isGenerating = (): boolean =>
    Array.from(document.querySelectorAll('button')).some((btn) =>
      /stop/i.test(btn.getAttribute('aria-label') || ''));

  const isReady = (btn: HTMLButtonElement): boolean =>
    !btn.disabled &&
    btn.getAttribute('aria-disabled') !== 'true' &&
    getComputedStyle(btn).pointerEvents !== 'none';

  // Read the SAME composer element injectText writes to (its selector chain), so
  // a cleared-composer success check can't read an unrelated empty .ql-editor and
  // log a false "submitted" while the result is actually stuck elsewhere.
  const composerText = (): string => {
    const e = (document.querySelector('.ql-editor.textarea')
      || document.querySelector('.ql-editor')
      || document.querySelector('[role="textbox"][contenteditable="true"]')
      || document.querySelector('rich-textarea [contenteditable="true"]')
      || document.querySelector('textarea')) as HTMLElement | null;
    if (e instanceof HTMLTextAreaElement) return e.value.trim();
    return (e?.innerText || e?.textContent || '').trim();
  };

  const absoluteDeadline = Date.now() + CONFIG.SEND_ABSOLUTE_CAP_MS;
  // Timestamp of the last click; null = not clicked yet. A single synthetic click
  // on Gemini's Angular composer intermittently does NOT submit, so we re-click if
  // the composer hasn't cleared within SEND_READY_TIMEOUT_MS, until it does (#18).
  let lastClickAt: number | null = null;

  const attemptClick = (): void => {
    // Hard terminator checked OUTSIDE the try so a recurring DOM exception can
    // never spin past the cap.
    if (Date.now() > absoluteDeadline) {
      let diag = `clicked=${lastClickAt !== null}`;
      try {
        diag += `, generating=${isGenerating()}, sendFound=${!!findButton()}, composerLen=${composerText().length}`;
      } catch { /* best-effort diagnostics only */ }
      warn(`Auto-submit gave up (absolute cap); response left in input for manual submit [${diag}]`);
      return;
    }
    let done = false;
    try {
      // Success: a prior click cleared the composer — the result was submitted.
      if (lastClickAt !== null && composerText().length === 0) {
        info('Auto-submitted response');
        done = true;
      } else if (!isGenerating()) {
        // While Gemini is still generating, the Send button is absent — wait it
        // out (do not consume the retry budget on legitimate generation time).
        const btn = findButton();
        const now = Date.now();
        if (btn && isReady(btn) && (lastClickAt === null || now - lastClickAt > CONFIG.SEND_READY_TIMEOUT_MS)) {
          btn.click();
          lastClickAt = now;
        }
      }
    } catch (e) {
      warn(`triggerSend: error in poll loop — ${(e as Error)?.message || e}; rescheduling`);
    }
    if (done) return;
    window.setTimeout(attemptClick, CONFIG.SEND_POLL_INTERVAL_MS);
  };

  attemptClick();
}
