import './style.css';
import { getLogs, clearLogs } from '@/utils/logger';

const app = document.querySelector<HTMLDivElement>('#app')!;

const DEFAULTS = {
  cooldownSeconds: 15,
  maxPerMinute: 5,
  settlingSeconds: 5,
  autoSubmit: true,
};

function render(
  status: 'active' | 'paused',
  cooldownSeconds: number,
  maxPerMinute: number,
  settlingSeconds: number,
  logsCount: number,
  advancedOpen: boolean,
  autoSubmit: boolean
) {
  const isPaused = status === 'paused';
  app.innerHTML = `
    <div class="container">
      <div class="header">
        <div class="icon">🤖</div>
        <h1>Gemini Local Agent</h1>
      </div>
      <div class="status-card ${isPaused ? 'paused' : 'active'}">
        <div class="status-dot"></div>
        <div class="status-text">${isPaused ? 'Paused' : 'Active'}</div>
      </div>
      <button id="toggle-btn" class="toggle-btn">${isPaused ? 'Resume Agent' : 'Pause Agent'}</button>
      <div class="shortcut-hint">Alt+Shift+K to toggle</div>

      <div class="settings-section">
        <label class="setting-row toggle-row">
          <span class="setting-label">Auto-submit responses</span>
          <input id="auto-submit-input" type="checkbox" ${autoSubmit ? 'checked' : ''} />
        </label>
        <label class="setting-row">
          <span class="setting-label">Cooldown</span>
          <input id="cooldown-input" type="range" min="5" max="60" value="${cooldownSeconds}" />
          <span class="setting-value" id="cooldown-value">${cooldownSeconds}s</span>
        </label>
      </div>

      <button id="export-btn" class="secondary-btn">Export Logs</button>
      <div id="export-status" class="status-msg"></div>

      <button id="advanced-toggle" class="advanced-toggle ${advancedOpen ? 'open' : ''}">
        Advanced
        <span class="chevron">▼</span>
      </button>
      <div id="advanced-panel" class="advanced-panel ${advancedOpen ? 'open' : ''}">
        <label class="setting-row">
          <span class="setting-label">Rate limit</span>
          <input id="rate-limit-input" type="range" min="1" max="10" value="${maxPerMinute}" />
          <span class="setting-value" id="rate-limit-value">${maxPerMinute}/min</span>
        </label>
        <label class="setting-row">
          <span class="setting-label">Settling</span>
          <input id="settling-input" type="range" min="0" max="10" value="${settlingSeconds}" />
          <span class="setting-value" id="settling-value">${settlingSeconds}s</span>
        </label>
        <button id="clear-logs-btn" class="danger-btn">Clear Logs</button>
      </div>
    </div>
  `;

  const btn = document.getElementById('toggle-btn');
  btn?.addEventListener('click', async () => {
    const { isAgentPaused } = await browser.storage.local.get('isAgentPaused');
    const current = isAgentPaused !== false;
    await browser.storage.local.set({ isAgentPaused: !current });
    render(!current ? 'paused' : 'active', cooldownSeconds, maxPerMinute, settlingSeconds, logsCount, advancedOpen, autoSubmit);
  });

  const autoSubmitInput = document.getElementById('auto-submit-input') as HTMLInputElement | null;
  autoSubmitInput?.addEventListener('change', async () => {
    const val = autoSubmitInput.checked;
    await browser.storage.local.set({ autoSubmit: val });
  });

  let cooldownDebounce: number | null = null;
  const cooldownInput = document.getElementById('cooldown-input') as HTMLInputElement | null;
  cooldownInput?.addEventListener('input', async (e) => {
    const val = parseInt((e.target as HTMLInputElement).value, 10);
    document.getElementById('cooldown-value')!.textContent = `${val}s`;
    if (cooldownDebounce) clearTimeout(cooldownDebounce);
    cooldownDebounce = window.setTimeout(() => {
      browser.storage.local.set({ cooldownSeconds: val });
    }, 300);
  });

  const exportBtn = document.getElementById('export-btn');
  exportBtn?.addEventListener('click', async () => {
    const logs = await getLogs();
    const statusEl = document.getElementById('export-status')!;
    if (!logs.length) {
      statusEl.textContent = 'No logs available';
      statusEl.className = 'status-msg warn';
      return;
    }
    const blob = new Blob([JSON.stringify(logs, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `gemini-agent-logs-${new Date().toISOString()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    statusEl.textContent = `${logs.length} log(s) exported`;
    statusEl.className = 'status-msg success';
  });

  const advancedToggle = document.getElementById('advanced-toggle');
  const advancedPanel = document.getElementById('advanced-panel');
  advancedToggle?.addEventListener('click', () => {
    const next = !advancedOpen;
    advancedToggle.classList.toggle('open', next);
    advancedPanel?.classList.toggle('open', next);
    browser.storage.local.set({ popupAdvancedOpen: next });
  });

  let rateLimitDebounce: number | null = null;
  const rateLimitInput = document.getElementById('rate-limit-input') as HTMLInputElement | null;
  rateLimitInput?.addEventListener('input', async (e) => {
    const val = parseInt((e.target as HTMLInputElement).value, 10);
    document.getElementById('rate-limit-value')!.textContent = `${val}/min`;
    if (rateLimitDebounce) clearTimeout(rateLimitDebounce);
    rateLimitDebounce = window.setTimeout(() => {
      browser.storage.local.set({ maxPerMinute: val });
    }, 300);
  });

  let settlingDebounce: number | null = null;
  const settlingInput = document.getElementById('settling-input') as HTMLInputElement | null;
  settlingInput?.addEventListener('input', async (e) => {
    const val = parseInt((e.target as HTMLInputElement).value, 10);
    document.getElementById('settling-value')!.textContent = `${val}s`;
    if (settlingDebounce) clearTimeout(settlingDebounce);
    settlingDebounce = window.setTimeout(() => {
      browser.storage.local.set({ settlingSeconds: val });
    }, 300);
  });

  const clearLogsBtn = document.getElementById('clear-logs-btn');
  clearLogsBtn?.addEventListener('click', async () => {
    await clearLogs();
    const statusEl = document.getElementById('export-status')!;
    statusEl.textContent = 'Logs cleared';
    statusEl.className = 'status-msg success';
  });
}

async function init() {
  const { isAgentPaused, cooldownSeconds, maxPerMinute, settlingSeconds, popupAdvancedOpen, autoSubmit } =
    await browser.storage.local.get([
      'isAgentPaused',
      'cooldownSeconds',
      'maxPerMinute',
      'settlingSeconds',
      'popupAdvancedOpen',
      'autoSubmit',
    ]);

  const logs = await getLogs();
  render(
    isAgentPaused !== false ? 'paused' : 'active',
    typeof cooldownSeconds === 'number' ? cooldownSeconds : DEFAULTS.cooldownSeconds,
    typeof maxPerMinute === 'number' ? maxPerMinute : DEFAULTS.maxPerMinute,
    typeof settlingSeconds === 'number' ? settlingSeconds : DEFAULTS.settlingSeconds,
    logs.length,
    popupAdvancedOpen === true,
    typeof autoSubmit === 'boolean' ? autoSubmit : DEFAULTS.autoSubmit
  );
}

init();
