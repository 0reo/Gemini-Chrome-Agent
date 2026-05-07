let port = null;
let lastActiveTabId = null; // We will store the exact tab that sent the request

function connectToHost() {
    console.log("Connecting to Ubuntu host...");
    port = chrome.runtime.connectNative('com.local.gemini_agent');
    
    port.onMessage.addListener((response) => {
        console.log("Received from Ubuntu:", response);
        
        // Send the response back to the EXACT tab that requested it
        if (lastActiveTabId) {
            chrome.tabs.sendMessage(lastActiveTabId, {type: "HOST_RESPONSE", data: response})
                .catch(err => console.warn("Could not send to the active Gemini tab", err));
        } else {
            console.warn("No active tab ID saved to route the response to.");
        }
    });

    port.onDisconnect.addListener(() => {
        console.error("Native host disconnected!", chrome.runtime.lastError);
        port = null;
    });
}

connectToHost();

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === "SEND_TO_HOST") {
        console.log("Received payload from Gemini tab:", request.payload);
        
        // Save the exact Tab ID of the tab making the request
        if (sender.tab && sender.tab.id) {
            lastActiveTabId = sender.tab.id;
        }
        
        if (!port) {
            connectToHost();
        }
        
        try {
            port.postMessage(request.payload);
            console.log("Successfully forwarded to Ubuntu!");
        } catch (e) {
            console.error("Failed to send message to host:", e);
        }
    }
});