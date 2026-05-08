const statusCard = document.getElementById('status-card');
const statusText = document.getElementById('status-text');
const toggleBtn = document.getElementById('toggle-btn');

async function updateUI() {
  const { isAgentPaused } = await chrome.storage.local.get('isAgentPaused');
  // Default to paused when no state has been stored yet
  const paused = isAgentPaused !== false;

  statusCard.classList.remove('active', 'paused');

  if (paused) {
    statusCard.classList.add('paused');
    statusText.textContent = 'Paused';
    toggleBtn.textContent = 'Resume Agent';
  } else {
    statusCard.classList.add('active');
    statusText.textContent = 'Active';
    toggleBtn.textContent = 'Pause Agent';
  }
}

toggleBtn.addEventListener('click', async () => {
  const { isAgentPaused } = await chrome.storage.local.get('isAgentPaused');
  const current = isAgentPaused !== false; // default to true (paused)
  const newState = !current;
  await chrome.storage.local.set({ isAgentPaused: newState });
  updateUI();
});

updateUI();
