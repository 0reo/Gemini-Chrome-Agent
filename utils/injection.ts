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
 * Two subtleties, both verified against the live Gemini DOM:
 *  - Gemini gates Send via `pointer-events: none`, NOT the native `disabled`
 *    property (which stays false even when the box is empty). So readiness is
 *    tested via computed pointer-events, not `button.disabled`.
 *  - After injection, Quill updates its model on a microtask and Angular arms
 *    the button a tick later — Send is never ready synchronously. We poll on a
 *    short, bounded schedule that ONLY reads state (no event dispatching, so no
 *    main-thread spam — that spam was the old freeze), and give up after a hard
 *    deadline, leaving the text in the box for manual submit.
 */
export function triggerSend(): void {
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

  const isReady = (btn: HTMLButtonElement): boolean =>
    !btn.disabled &&
    btn.getAttribute('aria-disabled') !== 'true' &&
    getComputedStyle(btn).pointerEvents !== 'none';

  const deadline = Date.now() + CONFIG.SEND_READY_TIMEOUT_MS;

  const attemptClick = (): void => {
    const btn = findButton();
    if (btn && isReady(btn)) {
      btn.click();
      info('Auto-submitted response');
      return;
    }
    if (Date.now() < deadline) {
      window.setTimeout(attemptClick, CONFIG.SEND_POLL_INTERVAL_MS);
    } else {
      warn('Send button did not arm before timeout; response left in input for manual submit');
    }
  };

  attemptClick();
}
