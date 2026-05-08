import { CONFIG } from '@/utils/config';
import { info, warn, error } from '@/utils/logger';
import { isValidPayload, generateId } from '@/utils/protocol';
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

    // Dynamic settings (overridable via storage)
    let cooldownMs: number = CONFIG.COOLDOWN_MS;
    let maxPerMinute: number = CONFIG.MAX_PER_MINUTE;
    let settlingPeriodMs: number = CONFIG.SETTLING_PERIOD_MS;

    async function loadSettings(): Promise<void> {
      try {
        const result = await browser.storage.local.get(['cooldownSeconds', 'maxPerMinute', 'settlingSeconds']);
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
        const paused = isAgentPaused !== false; // default to paused
        if (paused) {
          setState('paused');
        } else {
          setState('settling');
          window.setTimeout(() => setState('armed'), settlingPeriodMs);
        }
        info('Initial pause state synced', { paused });
      });
    });

    browser.storage.onChanged.addListener((changes, area) => {
      if (area !== 'local') return;

      if (changes.isAgentPaused) {
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

          if (!payload.id) {
            payload.id = generateId();
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
