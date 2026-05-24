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

export function injectResponse(data: { output?: string; error?: string; message?: string }): boolean {
  const outputText = data?.output || data?.error || data?.message || 'Command completed.';
  const fullText = `System Result:\n${outputText}`;

  const strategies = [
    () => injectIntoContentEditable(document.querySelector('rich-textarea [contenteditable="true"]'), fullText),
    () => injectIntoContentEditable(document.querySelector('[role="textbox"][contenteditable="true"]'), fullText),
    () => injectIntoContentEditable(document.querySelector('.ql-editor'), fullText),
    () => injectIntoTextarea(document.querySelector('textarea'), fullText),
  ];

  for (const strategy of strategies) {
    try {
      const result = strategy();
      if (result === 'injected') {
        info('Response injected successfully');
        return true;
      }
      if (result === 'skipped_user_typing') {
        warn('Response not injected: user is actively typing in the input');
        return false;
      }
    } catch (e) {
      warn('Injection strategy failed', { error: (e as Error).message });
    }
  }

  error('Could not find any injectable input element');
  return false;
}

type InjectionResult = 'injected' | 'skipped_user_typing' | false;

function injectIntoContentEditable(element: Element | null, text: string): InjectionResult {
  if (!element) return false;
  const el = element as HTMLElement;

  // CRITICAL: Do not overwrite what the user is currently typing
  if (isUserActivelyTyping(el)) {
    return 'skipped_user_typing';
  }

  // Gemini's input is a Quill editor. Quill keeps its own document model and
  // syncs it from the DOM via a MutationObserver, so directly mutating the DOM
  // (range.insertNode, setting innerText) leaves Quill's model empty — the text
  // shows on screen but the Send button never arms. execCommand routes through
  // the browser's native editing pipeline, firing the beforeinput/input events
  // Quill listens to, which updates its model. selectAll+delete first so any
  // leftover content is replaced cleanly (a bare selectAll+insertText corrupts
  // the first character against Quill).
  el.focus();
  document.execCommand('selectAll', false, undefined);
  document.execCommand('delete', false, undefined);
  document.execCommand('insertText', false, text);

  return 'injected';
}

function injectIntoTextarea(element: Element | null, text: string): InjectionResult {
  if (!element) return false;
  const el = element as HTMLTextAreaElement;

  // CRITICAL: Do not overwrite what the user is currently typing
  if (isUserActivelyTyping(el)) {
    return 'skipped_user_typing';
  }

  el.focus();
  el.value = text;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  return 'injected';
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
