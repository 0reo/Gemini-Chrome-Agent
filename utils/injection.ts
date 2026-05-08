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

  el.focus();
  document.execCommand('selectAll', false, null);
  document.execCommand('delete', false, null);

  // Primary: DataTransfer paste simulation (React-compatible)
  const dt = new DataTransfer();
  dt.setData('text/plain', text);
  const pasteEvent = new ClipboardEvent('paste', {
    clipboardData: dt,
    bubbles: true,
    cancelable: true,
  });
  el.dispatchEvent(pasteEvent);

  // Fallback 1: execCommand insertText
  if (el.innerText.length < 5) {
    document.execCommand('insertText', false, text);
  }

  // Fallback 2: direct innerText assignment
  if (el.innerText.length < 5) {
    el.innerText = text;
  }

  // Trigger React state updates
  ['input', 'change', 'compositionend', 'keyup', 'keydown'].forEach((type) => {
    el.dispatchEvent(new Event(type, { bubbles: true }));
  });

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

    triggerInputEvents();

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
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }));
    el.dispatchEvent(new KeyboardEvent('keyup', { key: 'a', bubbles: true }));
  });
}
