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

function setElementText(el: HTMLElement, text: string): void {
  if (el instanceof HTMLTextAreaElement) {
    el.value = text;
  } else {
    el.innerText = text;
  }
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

  el.focus();
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(el);
  selection?.removeAllRanges();
  selection?.addRange(range);

  // Delete current content
  range.deleteContents();

  // Insert new text node
  const textNode = document.createTextNode(text);
  range.insertNode(textNode);

  // Move cursor to end
  range.selectNodeContents(textNode);
  range.collapse(false);
  selection?.removeAllRanges();
  selection?.addRange(range);

  // Minimal event dispatch to trigger React state updates
  el.dispatchEvent(new InputEvent('input', { bubbles: true, data: text }));

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
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return 'injected';
}

export function triggerSend(isPaused: () => boolean, shouldAutoSubmit: boolean): void {
  if (!shouldAutoSubmit) {
    info('Auto-submit disabled; response left in input for user review');
    return;
  }

  const buttonSelectors = [
    'button[aria-label="Send message"]',
    'button[aria-label*="Send"]',
    'button[mattooltip*="Send"]',
    'button[data-testid="send-button"]',
    'button.send-button',
    'button[aria-label*="send"]',
  ];

  let attempts = 0;

  const interval = window.setInterval(() => {
    if (isPaused()) {
      clearInterval(interval);
      return;
    }

    let sendButton: HTMLButtonElement | null = null;
    for (const selector of buttonSelectors) {
      const btn = document.querySelector<HTMLButtonElement>(selector);
      if (btn && !btn.disabled) {
        sendButton = btn;
        break;
      }
    }

    if (!sendButton) {
      sendButton = Array.from(document.querySelectorAll('button')).find((btn) => {
        const text = (btn.innerText || btn.textContent || '').toLowerCase();
        const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
        return (text.includes('send') || aria.includes('send')) && !btn.disabled;
      }) || null;
    }

    if (sendButton) {
      clearInterval(interval);
      sendButton.click();
      info('Auto-submitted response');
      return;
    }

    // Only trigger input events for the first few attempts, then wait quietly
    if (attempts < 5) {
      triggerInputEvents();
    }

    if (++attempts >= CONFIG.MAX_SEND_ATTEMPTS) {
      clearInterval(interval);
      warn('Failed to find enabled send button after maximum attempts');
    }
  }, CONFIG.SEND_POLL_INTERVAL_MS);
}

function triggerInputEvents(): void {
  const inputs = document.querySelectorAll<HTMLElement>(
    'rich-textarea [contenteditable="true"], [role="textbox"][contenteditable="true"], .ql-editor, textarea'
  );
  inputs.forEach((el) => {
    el.dispatchEvent(new InputEvent('input', { bubbles: true }));
  });
}
