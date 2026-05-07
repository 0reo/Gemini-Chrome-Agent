let port = null;

function connectToHost() {
    console.log("Connecting to Ubuntu host...");
    port = chrome.runtime.connectNative('com.local.gemini_agent');
    
    port.onMessage.addListener((response) => {
        console.log("Received from Ubuntu:", response);
        chrome.tabs.query({url: "*://gemini.google.com/*"}, function(tabs) {
            if (tabs && tabs.length > 0) {
                chrome.tabs.sendMessage(tabs[0].id, {type: "HOST_RESPONSE", data: response})
                    .catch(err => console.warn("Could not send to Gemini tab", err));
            }
        });
    });

    port.onDisconnect.addListener(() => {
        console.error("Native host disconnected!", chrome.runtime.lastError);
        port = null;
    });
}

// Connect immediately when the service worker starts
connectToHost();

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === "SEND_TO_HOST") {
        console.log("Received payload from Gemini tab:", request.payload);
        
        // If the Service Worker went to sleep and lost the connection, reconnect!
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