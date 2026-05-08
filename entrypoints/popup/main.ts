import './style.css';

const app = document.querySelector<HTMLDivElement>('#app')!;

function render(status: 'active' | 'paused') {
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
    </div>
  `;

  const btn = document.getElementById('toggle-btn');
  btn?.addEventListener('click', async () => {
    const { isAgentPaused } = await browser.storage.local.get('isAgentPaused');
    const current = isAgentPaused !== false;
    await browser.storage.local.set({ isAgentPaused: !current });
    render(!current ? 'paused' : 'active');
  });
}

async function init() {
  const { isAgentPaused } = await browser.storage.local.get('isAgentPaused');
  render(isAgentPaused !== false ? 'paused' : 'active');
}

init();
