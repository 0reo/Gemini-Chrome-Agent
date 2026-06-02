// Runs in the page's MAIN world so it can override HTMLInputElement.prototype.click
// (the isolated content script has a separate prototype). Bridges to the isolated
// content script via window.postMessage. Browser-injected, so not blocked by CSP.

interface FileDesc { name: string; type: string; base64: string; }
interface UploadResult { ok: boolean; count?: number; error?: string; }

export default defineContentScript({
  matches: ['*://gemini.google.com/*'],
  world: 'MAIN',
  main() {
    window.addEventListener('message', async (ev: MessageEvent) => {
      if (ev.source !== window) return;
      const d = ev.data;
      if (!d || typeof d.__gla !== 'string') return;
      if (d.__gla === 'quill-set' && typeof d.text === 'string') {
        setComposerText(d.text as string);
        return;
      }
      if (d.__gla === 'attach-request' && Array.isArray(d.files)) {
        const result = await performUpload(d.files as FileDesc[]);
        window.postMessage({ __gla: 'attach-result', nonce: d.nonce, ...result }, '*');
      }
    });

    // Set Gemini's composer text by writing Quill's MODEL directly. On the new-input-ui composer
    // the model (not the DOM) arms and submits the message; execCommand only mutates the DOM and no
    // longer updates the model (issue #16). Running in the MAIN world, we can reach the page's
    // Quill instance via its `__quill` property — the isolated content script cannot.
    function setComposerText(text: string): void {
      const ed = (document.querySelector('.ql-editor.textarea')
        || document.querySelector('.ql-editor')
        || document.querySelector('[role="textbox"][contenteditable="true"]')) as HTMLElement | null;
      if (ed) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        let q: any = null;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        let node: any = ed;
        for (let i = 0; i < 6 && node; i++) {
          if (node.__quill) { q = node.__quill; break; }
          node = node.parentElement;
        }
        ed.focus();
        if (q && typeof q.setText === 'function') {
          // 'user' source is REQUIRED: Quill emits text-change as user input, which arms Gemini's
          // Send button on new-input-ui. Default 'api' syncs the model but leaves Send disabled (#16).
          try {
            q.setText(text, 'user');
            try { q.setSelection(q.getLength(), 0); } catch { /* selection is best-effort */ }
            return;
          } catch (e) {
            // Surface the Quill error and stop — do NOT fall through to execCommand:
            // on new-input-ui execCommand desyncs Quill's model (text shows but Send
            // never arms), leaving stale text in the composer. An empty composer is
            // cleaner; triggerSend's armed-Send gate then declines to submit rather
            // than sending garbage. The isolated caller (injectText) already returned
            // true, but triggerSend won't auto-submit an empty box (#18/!4 review).
            // eslint-disable-next-line no-console
            console.warn('[Gemini Agent][uploader] q.setText threw:', (e as Error)?.message || e);
            return;
          }
        }
        // fallback (no Quill instance — old UI): execCommand
        document.execCommand('selectAll', false, undefined);
        document.execCommand('delete', false, undefined);
        document.execCommand('insertText', false, text);
        return;
      }
      const ta = document.querySelector('textarea') as HTMLTextAreaElement | null;
      if (ta) {
        ta.focus();
        ta.value = text;
        ta.dispatchEvent(new Event('input', { bubbles: true }));
      }
    }

    const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const findButton = (pred: (b: HTMLButtonElement) => boolean): HTMLButtonElement | null =>
      (Array.from(document.querySelectorAll('button')) as HTMLButtonElement[]).find(pred) || null;

    async function performUpload(descs: FileDesc[]): Promise<UploadResult> {
      let fileObjs: File[];
      try {
        fileObjs = descs.map((dsc) => {
          const bin = atob(dsc.base64);
          const bytes = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
          return new File([bytes], dsc.name, { type: dsc.type || 'application/octet-stream' });
        });
      } catch (e) {
        return { ok: false, error: 'file reconstruction failed: ' + ((e as Error)?.message || e) };
      }

      const origClick = HTMLInputElement.prototype.click;
      const origFSA = (window as any).showOpenFilePicker;
      let intercepted = false;

      HTMLInputElement.prototype.click = function (this: HTMLInputElement) {
        if (this.type === 'file') {
          intercepted = true;
          const dt = new DataTransfer();
          fileObjs.forEach((f) => dt.items.add(f));
          this.files = dt.files;
          this.dispatchEvent(new Event('input', { bubbles: true }));
          this.dispatchEvent(new Event('change', { bubbles: true }));
          return;
        }
        // eslint-disable-next-line prefer-rest-params
        return origClick.apply(this, arguments as any);
      };
      if (origFSA) {
        (window as any).showOpenFilePicker = async () => { const e = new Error('aborted'); (e as any).name = 'AbortError'; throw e; };
      }

      try {
        const toolsBtn = findButton((b) => (b.getAttribute('aria-label') || '') === 'Upload & tools');
        if (!toolsBtn) return { ok: false, error: 'Upload & tools button not found' };
        toolsBtn.click();

        let filesBtn: HTMLButtonElement | null = null;
        for (let i = 0; i < 20 && !filesBtn; i++) {
          await wait(100);
          filesBtn = findButton((b) => (b.innerText || '').trim().split('\n')[0] === 'Files');
        }
        if (!filesBtn) return { ok: false, error: 'Files menu item not found (Gemini UI may have changed)' };
        filesBtn.click();

        for (let i = 0; i < 20 && !intercepted; i++) await wait(100);
        if (!intercepted) return { ok: false, error: 'file input click not intercepted (Gemini UI may have changed)' };

        await wait(800); // let Gemini register the attachment chip
        return { ok: true, count: fileObjs.length };
      } finally {
        HTMLInputElement.prototype.click = origClick;
        if (origFSA) (window as any).showOpenFilePicker = origFSA;
      }
    }
  },
});
