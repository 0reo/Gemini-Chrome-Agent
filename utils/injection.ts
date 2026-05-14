import { CONFIG } from './config';
import { info, warn, error } from './logger';

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
      if (strategy()) {
        info('Response injected successfully');
        return true;
      }
    } catch (e) {
      warn('Injection strategy failed', { error: (e as Error).message });
    }
  }

  error('Could not find any injectable input element');
  return false;
}

function injectIntoContentEditable(element: Element | null, text: string): boolean {
  if (!element) return false;
  const el = element as HTMLElement;

  // Safer approach: use Selection API instead of deprecated execCommand
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

  return true;
}

function injectIntoTextarea(element: Element | null, text: string): boolean {
  if (!element) return false;
  const el = element as HTMLTextAreaElement;
  el.focus();
  el.value = text;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
}

export function triggerSend(isPaused: () => boolean): void {
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
