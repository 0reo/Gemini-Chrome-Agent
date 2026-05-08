// popup.js — Runs in the popup context (created when icon clicked, destroyed when closed)
// Do NOT store state in variables — use chrome.storage for persistence

"use strict";

// ─── DOM References ────────────────────────────────────────────────────────
const actionBtn  = document.getElementById("actionBtn");
const statusEl   = document.getElementById("status");
const outputEl   = document.getElementById("output");
const optionsLink = document.getElementById("optionsLink");

// ─── Init ─────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  // Load saved state from storage
  const { enabled = false } = await chrome.storage.local.get("enabled");
  updateUI(enabled);
});

// ─── Event Listeners ──────────────────────────────────────────────────────
actionBtn.addEventListener("click", async () => {
  setStatus("Working...");
  actionBtn.disabled = true;

  try {
    // Get the current active tab
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    // Option A: Send message to content script
    const response = await sendMessageToTab(tab.id, { action: "doSomething" });

    if (response?.success) {
      setStatus("Done!");
      showOutput(response.data);
    } else {
      setStatus("No response from page.");
    }

    // Option B: Send message to service worker
    // const response = await chrome.runtime.sendMessage({ action: "fetchData" });

  } catch (err) {
    setStatus(`Error: ${err.message}`);
    console.error(err);
  } finally {
    actionBtn.disabled = false;
  }
});

optionsLink.addEventListener("click", (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
});

// ─── Helpers ──────────────────────────────────────────────────────────────
function setStatus(text) {
  statusEl.textContent = text;
}

function showOutput(data) {
  outputEl.textContent = typeof data === "object" ? JSON.stringify(data, null, 2) : data;
  outputEl.classList.remove("hidden");
}

function updateUI(enabled) {
  actionBtn.textContent = enabled ? "Disable" : "Enable";
  statusEl.textContent = enabled ? "Active" : "Inactive";
}

/**
 * Send a message to a tab's content script, with error handling.
 * Returns null if no content script is listening on that tab.
 */
function sendMessageToTab(tabId, message) {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) {
        console.warn("Tab message error:", chrome.runtime.lastError.message);
        resolve(null);
      } else {
        resolve(response);
      }
    });
  });
}
