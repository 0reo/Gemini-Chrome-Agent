import { CONFIG } from '@/utils/config';
import { info, warn, error } from '@/utils/logger';
import { isValidPayload } from '@/utils/protocol';
import { isRecentlyProcessed, markPayloadProcessed } from '@/utils/dedup';
import { injectResponse, triggerSend } from '@/utils/injection';
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

    // --- State Machine ---
    function setState(newState: AgentState): void {
      info(`State transition: ${state} → ${newState}`);
      state = newState;
    }

    function isSettling(): boolean {
      return state === 'settling' && Date.now() - pageLoadTime < CONFIG.SETTLING_PERIOD_MS;
    }

    function isArmed(): boolean {
      return state === 'armed' || state === 'cooldown';
    }

    function isPaused(): boolean {
      return state === 'paused';
    }

    function setCooldown(): void {
      setState('cooldown');
      if (cooldownTimer) clearTimeout(cooldownTimer);
      cooldownTimer = window.setTimeout(() => {
        setState('armed');
        info('Cooldown ended');
      }, CONFIG.COOLDOWN_MS);
    }

    function trackExecution(): void {
      executionsThisMinute++;
      if (!minuteTimer) {
        minuteTimer = window.setTimeout(() => {
          executionsThisMinute = 0;
          minuteTimer = null;
        }, 60000);
      }
      if (executionsThisMinute >= CONFIG.MAX_PER_MINUTE) {
        warn(`Rate limit hit (${CONFIG.MAX_PER_MINUTE}/min). Auto-pausing.`);
        setState('paused');
        browser.storage.local.set({ isAgentPaused: true }).catch(() => {});
      }
    }

    // --- Sync pause state from storage ---
    browser.storage.local.get('isAgentPaused').then(({ isAgentPaused }) => {
      const paused = isAgentPaused !== false; // default to paused
      if (paused) {
        setState('paused');
      } else {
        setState('settling');
        window.setTimeout(() => setState('armed'), CONFIG.SETTLING_PERIOD_MS);
      }
      info('Initial pause state synced', { paused });
    });

    browser.storage.onChanged.addListener((changes, area) => {
      if (area === 'local' && changes.isAgentPaused) {
        const paused = changes.isAgentPaused.newValue !== false;
        if (paused) {
          setState('paused');
        } else {
          setState('armed');
          if (cooldownTimer) {
            clearTimeout(cooldownTimer);
            cooldownTimer = null;
          }
        }
        info('Pause state synced via storage', { paused });
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

    // --- Mark existing blocks on load ---
    function markExistingBlocks(): void {
      const blocks = document.querySelectorAll('pre code, code');
      let marked = 0;
      for (const block of blocks) {
        const text = block.textContent || '';
        if (!text.includes('"action"')) continue;
        try {
          const payload = JSON.parse(text) as AgentPayload;
          if (isValidPayload(payload)) {
            markPayloadProcessed(payload);
            marked++;
          }
        } catch {
          // Not valid JSON
        }
      }
      if (marked > 0) {
        info(`Marked ${marked} existing payload(s) as processed`);
      }
    }

    // --- Debounced Payload Detection ---
    const observer = new MutationObserver(() => {
      if (isPaused() || state === 'cooldown') return;
      if (scanTimeout) clearTimeout(scanTimeout);
      scanTimeout = window.setTimeout(scanForPayloads, CONFIG.SCAN_DEBOUNCE_MS);
    });

    function scanForPayloads(): void {
      scanTimeout = null;
      const settling = isSettling();
      const blocks = document.querySelectorAll('pre code, code');

      for (const block of blocks) {
        const text = block.textContent || '';
        if (!text.includes('"action"')) continue;

        try {
          const payload = JSON.parse(text) as AgentPayload;
          if (!isValidPayload(payload)) continue;
          if (isRecentlyProcessed(payload)) continue;

          if (settling) {
            info('Settling: ignored historical payload', { action: payload.action });
            continue;
          }

          info('Executing action', { action: payload.action, id: payload.id });
          browser.runtime.sendMessage({ type: 'SEND_TO_HOST', payload } as ExtensionMessage);
          setCooldown();
          trackExecution();
        } catch {
          // JSON parse failed — block is still streaming
        }
      }
    }

    markExistingBlocks();
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });

    // --- Response Injection ---
    browser.runtime.onMessage.addListener((message: ExtensionMessage) => {
      if (message.type === 'HOST_RESPONSE') {
        if (isPaused()) {
          info('Response received but agent is paused; ignoring');
          return;
        }
        if (message.data) {
          injectResponse(message.data);
          triggerSend(() => isPaused());
        }
      }
    });

    info('Content script loaded');
  },
});
