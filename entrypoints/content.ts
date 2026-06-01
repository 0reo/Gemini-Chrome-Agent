import { CONFIG } from '@/utils/config';
import { info, warn, error } from '@/utils/logger';
import { isValidPayload, generateId } from '@/utils/protocol';
import { isRecentlyProcessed, markPayloadProcessed } from '@/utils/dedup';
import { injectResponse, injectText, triggerSend } from '@/utils/injection';
import { AttachAssembler, type AttachResult } from '@/utils/attach';
import type { AgentPayload, AgentState, ExtensionMessage } from '@/utils/types';

export default defineContentScript({
  matches: ['*://gemini.google.com/*'],
  main() {
    let state: AgentState = 'settling';
    let cooldownTimer: number | null = null;
    let executionsThisMinute = 0;
    let minuteTimer: number | null = null;
    let scanTimeout: number | null = null;
    const pageLoadTime = Date.now();
    const attachAssemblers = new Map<string, AttachAssembler>();
    const attachRequests = new Map<string, { source: 'gemini' | 'popup'; prompt?: string }>();
    /** Action JSON blocks already in the DOM when this script loaded — never auto-run. */
    const blocksPresentAtLoad = new WeakSet<Element>();
    /** Action JSON blocks already dispatched this session — never re-run same DOM node. */
    const executedBlocks = new WeakSet<Element>();

    /** Selectors for Gemini JSON action blocks (keep in sync with closed-loop DOM audit). */
    const ACTION_BLOCK_SELECTOR = 'pre code, code, pre code.language-json, pre code.hljs';

    // Dynamic settings (overridable via storage)
    let cooldownMs: number = CONFIG.COOLDOWN_MS;
    let maxPerMinute: number = CONFIG.MAX_PER_MINUTE;
    let settlingPeriodMs: number = CONFIG.SETTLING_PERIOD_MS;
    async function loadSettings(): Promise<void> {
      try {
        const result = await browser.storage.local.get([
          'cooldownSeconds', 'maxPerMinute', 'settlingSeconds'
        ]);
        if (typeof result.cooldownSeconds === 'number') {
          cooldownMs = result.cooldownSeconds * 1000;
        }
        if (typeof result.maxPerMinute === 'number') {
          maxPerMinute = result.maxPerMinute;
        }
        if (typeof result.settlingSeconds === 'number') {
          settlingPeriodMs = result.settlingSeconds * 1000;
        }
      } catch {
        // Fallback to CONFIG defaults already set
      }
    }

    // --- State Machine ---
    function setState(newState: AgentState): void {
      info(`State transition: ${state} → ${newState}`);
      state = newState;
    }

    function isSettling(): boolean {
      return state === 'settling' && Date.now() - pageLoadTime < settlingPeriodMs;
    }

    function isArmed(): boolean {
      return state === 'armed' || state === 'cooldown';
    }

    function isPaused(): boolean {
      return state === 'paused';
    }

    function scheduleScan(): void {
      if (isPaused() || state === 'cooldown') {
        return;
      }
      if (scanTimeout) clearTimeout(scanTimeout);
      scanTimeout = window.setTimeout(scanForPayloads, CONFIG.SCAN_DEBOUNCE_MS);
    }

    function setCooldown(): void {
      setState('cooldown');
      if (cooldownTimer) clearTimeout(cooldownTimer);
      cooldownTimer = window.setTimeout(() => {
        setState('armed');
        info('Cooldown ended');
      }, cooldownMs);
    }

    function trackExecution(): void {
      executionsThisMinute++;
      if (!minuteTimer) {
        minuteTimer = window.setTimeout(() => {
          executionsThisMinute = 0;
          minuteTimer = null;
        }, 60000);
      }
      if (executionsThisMinute >= maxPerMinute) {
        warn(`Rate limit hit (${maxPerMinute}/min). Auto-pausing.`);
        setState('paused');
        browser.storage.local.set({ isAgentPaused: true }).catch(() => {});
      }
    }

    // --- Init settings & pause state ---
    loadSettings().then(() => {
      browser.storage.local.get('isAgentPaused').then(({ isAgentPaused }) => {
        const paused = isAgentPaused === true;
        if (paused) {
          setState('paused');
        } else {
          setState('settling');
          window.setTimeout(() => {
            setState('armed');
            scheduleScan();
          }, settlingPeriodMs);
        }
        info('Initial pause state synced', { paused });
      });
    });

    browser.storage.onChanged.addListener((changes, area) => {
      if (area !== 'local') return;

      if (changes.isAgentPaused) {
        const paused = changes.isAgentPaused.newValue === true;
        if (paused) {
          setState('paused');
        } else {
          setState('armed');
          if (cooldownTimer) {
            clearTimeout(cooldownTimer);
            cooldownTimer = null;
          }
          scheduleScan();
        }
        info('Pause state synced via storage', { paused });
      }

      if (changes.cooldownSeconds) {
        const val = changes.cooldownSeconds.newValue;
        if (typeof val === 'number') {
          cooldownMs = val * 1000;
          info('Cooldown setting updated', { seconds: val });
        }
      }

      if (changes.maxPerMinute) {
        const val = changes.maxPerMinute.newValue;
        if (typeof val === 'number') {
          maxPerMinute = val;
          info('Rate limit setting updated', { maxPerMinute: val });
        }
      }

      if (changes.settlingSeconds) {
        const val = changes.settlingSeconds.newValue;
        if (typeof val === 'number') {
          settlingPeriodMs = val * 1000;
          info('Settling period setting updated', { seconds: val });
        }
      }


    });

    // Keyboard shortcut
    window.addEventListener('keydown', (e) => {
      if (e.altKey && e.shiftKey && e.key === 'K') {
        const newPaused = !isPaused();
        browser.storage.local.set({ isAgentPaused: newPaused }).catch(() => {});
        info('State toggled via keyboard shortcut', { paused: newPaused });
      }
    });

    function parsePayloadFromBlock(block: Element): AgentPayload | null {
      const text = (block.textContent || '').trim();
      if (!text.includes('"action"')) return null;
      try {
        const payload = JSON.parse(text) as AgentPayload;
        return isValidPayload(payload) ? payload : null;
      } catch {
        return null;
      }
    }

    /** Last valid action JSON block in document order (for user-initiated rerun). */
    function findLastActionBlock(): Element | null {
      const blocks = document.querySelectorAll(ACTION_BLOCK_SELECTOR);
      let last: Element | null = null;
      for (const block of blocks) {
        if (parsePayloadFromBlock(block)) last = block;
      }
      return last;
    }

    function dispatchFromBlock(block: Element, source: 'scan' | 'rerun'): void {
      const payload = parsePayloadFromBlock(block);
      if (!payload) {
        warn('Cannot dispatch: invalid action block', { source });
        return;
      }
      if (!payload.id) {
        payload.id = generateId();
      }
      markPayloadProcessed(payload);
      executedBlocks.add(block);
      const context = extractChatContext(block);
      info('Executing action', { action: payload.action, id: payload.id, context, source });
      browser.runtime.sendMessage({ type: 'SEND_TO_HOST', payload } as ExtensionMessage);
      if (payload.action === 'attach_files') {
        attachRequests.set(payload.id, { source: 'gemini', prompt: payload.prompt });
      }
      setCooldown();
      trackExecution();
    }

    /** User-initiated: run the latest action block once (bypasses historical / executed guards). */
    function rerunLatestAction(): void {
      if (isPaused()) {
        warn('Rerun latest: agent is paused');
        return;
      }
      const block = findLastActionBlock();
      if (!block) {
        warn('Rerun latest: no action JSON block found in thread');
        return;
      }
      info('Rerun latest action (user requested)');
      dispatchFromBlock(block, 'rerun');
    }

    // --- Record action blocks already on the page (chat history) — do not auto-run ---
    function recordBlocksPresentAtLoad(): void {
      const blocks = document.querySelectorAll(ACTION_BLOCK_SELECTOR);
      let recorded = 0;
      for (const block of blocks) {
        const text = block.textContent || '';
        if (!text.includes('"action"')) continue;
        try {
          const payload = JSON.parse(text) as AgentPayload;
          if (isValidPayload(payload)) {
            blocksPresentAtLoad.add(block);
            recorded++;
          }
        } catch {
          // Not valid JSON
        }
      }
      if (recorded > 0) {
        info(`Recorded ${recorded} historical action block(s) (will not auto-run)`);
      }
    }

    // --- Debounced Payload Detection ---
    const observer = new MutationObserver(() => {
      scheduleScan();
    });

    function scanForPayloads(): void {
      scanTimeout = null;
      const settling = isSettling();
      const blocks = document.querySelectorAll(ACTION_BLOCK_SELECTOR);
      let executed = 0;

      for (const block of blocks) {
        const payload = parsePayloadFromBlock(block);
        if (!payload) continue;

        if (settling) {
          info('Settling: ignored historical payload', { action: payload.action });
          continue;
        }

        if (blocksPresentAtLoad.has(block)) {
          continue;
        }

        if (executedBlocks.has(block)) {
          continue;
        }

        if (isRecentlyProcessed(payload)) {
          continue;
        }

        dispatchFromBlock(block, 'scan');
        executed++;
      }
      if (executed > 0) {
        info('Scan dispatched payloads', { count: executed, state, settling });
      }
    }

    // Extract surrounding chat context for a given code block element
    function extractChatContext(block: Element): string {
      try {
        // Try to find the parent message container
        let el: Element | null = block;
        for (let i = 0; i < 6 && el; i++) {
          el = el.parentElement;
          if (el && (el.getAttribute('data-test-id') || el.className?.includes('message'))) {
            const text = (el.textContent || '').substring(0, 200).replace(/\s+/g, ' ');
            return text;
          }
        }
        // Fallback: get text from siblings/parents
        const parent = block.parentElement;
        if (parent) {
          return (parent.textContent || '').substring(0, 200).replace(/\s+/g, ' ');
        }
      } catch {
        // Ignore extraction errors
      }
      return '';
    }

    recordBlocksPresentAtLoad();
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });

    // --- Response Injection ---
    browser.runtime.onMessage.addListener((message: ExtensionMessage) => {
      if (message.type === 'HOST_RESPONSE') {
        // Attach chunks are reassembled and completed regardless of pause state:
        // once files have been sent to the host, finish the round trip.
        if (message.data?.status === 'attach' && message.data.attach) {
          const id = message.data.id;
          let asm = attachAssemblers.get(id);
          if (!asm) { asm = new AttachAssembler(); attachAssemblers.set(id, asm); }
          const result = asm.add(message.data.attach);
          if (result) { attachAssemblers.delete(id); void handleAttachComplete(id, result); }
          return;
        }
        if (isPaused()) {
          info('Response received but agent is paused; ignoring');
          return;
        }
        if (message.data) {
          const injected = injectResponse(message.data);
          if (injected) {
            // Read auto-submit fresh from storage to avoid a stale in-memory value.
            // Default ON (the agent loop's whole point) — and keep that default on a
            // storage-read failure too, so the two paths can't disagree.
            browser.storage.local.get('autoSubmit')
              .then(({ autoSubmit }) => autoSubmit !== false)
              .catch(() => true)
              .then((shouldSubmit) => {
                if (shouldSubmit) {
                  triggerSend();
                } else {
                  info('Auto-submit disabled; response left in input for manual submit');
                }
              });
          }
        }
      }
    });

    // Popup / harness messages (attach, rerun latest).
    browser.runtime.onMessage.addListener((message: { type?: string; filepaths?: string[] }) => {
      if (message?.type === 'ATTACH_REQUEST' && Array.isArray(message.filepaths)) {
        const id = generateId();
        attachRequests.set(id, { source: 'popup' });
        browser.runtime.sendMessage({
          type: 'SEND_TO_HOST',
          payload: { id, action: 'attach_files', filepaths: message.filepaths },
        } as ExtensionMessage);
        return;
      }
      if (message?.type === 'RERUN_LATEST') {
        rerunLatestAction();
      }
    });

    // Closed-loop harness: window.postMessage({ __gla: 'rerun-latest' }, '*')
    window.addEventListener('message', (ev: MessageEvent) => {
      if (ev.source !== window || !ev.data || ev.data.__gla !== 'rerun-latest') return;
      rerunLatestAction();
    });

    function performAttachUpload(files: AttachResult['files']): Promise<{ ok: boolean; error?: string }> {
      return new Promise((resolve) => {
        const nonce = generateId();
        const timer = window.setTimeout(() => {
          window.removeEventListener('message', onResult);
          resolve({ ok: false, error: 'uploader timed out' });
        }, 15000);
        function onResult(ev: MessageEvent) {
          const d = ev.data;
          if (ev.source !== window || !d || d.__gla !== 'attach-result' || d.nonce !== nonce) return;
          window.clearTimeout(timer);
          window.removeEventListener('message', onResult);
          resolve({ ok: !!d.ok, error: d.error });
        }
        window.addEventListener('message', onResult);
        window.postMessage({
          __gla: 'attach-request',
          nonce,
          files: files.map((f) => ({ name: f.filename, type: f.mimeType, base64: f.base64 })),
        }, '*');
      });
    }

    async function handleAttachComplete(id: string, result: AttachResult): Promise<void> {
      const ctx = attachRequests.get(id) || { source: 'gemini' as const };
      attachRequests.delete(id);
      for (const err of result.errors) warn('Attach error', { filename: err.filename, error: err.error });
      if (result.files.length === 0) {
        warn('Attach produced no files', { errors: result.errors.length });
        return;
      }
      const upload = await performAttachUpload(result.files);
      if (!upload.ok) { error('File upload into Gemini failed', { error: upload.error }); return; }
      info('Files attached', { count: result.files.length, source: ctx.source });

      if (ctx.source === 'popup') return; // stage only

      // Gemini-driven: inject prompt (or a default summary) then honor auto-submit.
      // injectText returns false when the user is actively typing (input-hijack guard);
      // in that case we must NOT auto-submit, or we'd send the user's own text.
      const names = result.files.map((f) => f.filename).join(', ');
      const promptText = (ctx.prompt && ctx.prompt.trim()) || `Attached ${result.files.length} file(s): ${names}`;
      const injected = injectText(promptText);
      const { autoSubmit } = await browser.storage.local.get('autoSubmit').catch(() => ({ autoSubmit: true }));
      if (injected && autoSubmit !== false) triggerSend();
    }

    document.documentElement.dataset.glaAgentReady = String(Date.now());
    info('Content script loaded');
  },
});
