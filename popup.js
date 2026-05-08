const statusCard = document.getElementById('status-card');
const statusText = document.getElementById('status-text');
const toggleBtn = document.getElementById('toggle-btn');

async function updateUI() {
  const { isAgentPaused } = await chrome.storage.local.get('isAgentPaused');

  statusCard.classList.remove('active', 'paused');

  if (isAgentPaused) {
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
  const newState = !isAgentPaused;
  await chrome.storage.local.set({ isAgentPaused: newState });
  updateUI();
});

updateUI();
