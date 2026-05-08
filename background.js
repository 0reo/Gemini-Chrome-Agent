let port = null;

function connectToHost() {
    console.log("[Background] Connecting to Ubuntu host...");
    port = chrome.runtime.connectNative('com.local.gemini_agent');
    
    port.onMessage.addListener((response) => {
        console.log("[Background] Received from Ubuntu:", response);
        
        // Try to route to the exact tab that sent the request.
        // Service workers go inactive and lose in-memory state, so we
        // persist the tab ID in session storage.
        chrome.storage.session.get('lastActiveTabId').then(({ lastActiveTabId }) => {
            if (lastActiveTabId) {
                chrome.tabs.sendMessage(lastActiveTabId, {type: "HOST_RESPONSE", data: response})
                    .catch(err => {
                        console.warn("[Background] Could not send to the active Gemini tab:", err.message);
                        // Fallback: broadcast to any Gemini tab
                        broadcastToGeminiTabs(response);
                    });
            } else {
                broadcastToGeminiTabs(response);
            }
        });
    });

    port.onDisconnect.addListener(() => {
        const error = chrome.runtime.lastError;
        if (error) {
            console.error("[Background] Native host disconnected!", error.message);
        } else {
            console.log("[Background] Native host disconnected (clean).");
        }
        port = null;
    });
}

function broadcastToGeminiTabs(response) {
    chrome.tabs.query({url: "*://gemini.google.com/*"}, function(tabs) {
        if (tabs && tabs.length > 0) {
            // Send to the most recently active Gemini tab
            const targetTab = tabs[tabs.length - 1];
            chrome.tabs.sendMessage(targetTab.id, {type: "HOST_RESPONSE", data: response})
                .catch(err => console.warn("[Background] Could not send to fallback Gemini tab:", err.message));
        } else {
            console.warn("[Background] No Gemini tab found to route the response to.");
        }
    });
}

// Connect immediately when the service worker starts
connectToHost();

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === "SEND_TO_HOST") {
        console.log("[Background] Received payload from Gemini tab:", request.payload);
        
        // Persist the sender tab ID so we can route responses back after
        // the service worker wakes up from sleep.
        if (sender.tab && sender.tab.id) {
            chrome.storage.session.set({ lastActiveTabId: sender.tab.id })
                .catch(err => console.warn("[Background] Failed to save tab ID:", err));
        }
        
        if (!port) {
            console.log("[Background] Native port missing; reconnecting...");
            connectToHost();
        }
        
        try {
            port.postMessage(request.payload);
            console.log("[Background] Successfully forwarded to Ubuntu!");
        } catch (e) {
            console.error("[Background] Failed to send message to host:", e);
        }
    }
});

// Keep the service worker alive while Native Messaging is active.
// Manifest V3 service workers can sleep after ~30s of inactivity,
// which kills the native messaging port.
chrome.runtime.onConnect.addListener((externalPort) => {
    externalPort.onDisconnect.addListener(() => {
        console.log("[Background] External port disconnected.");
    });
});
