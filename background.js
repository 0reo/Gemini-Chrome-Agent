let port = chrome.runtime.connectNative('com.local.gemini_agent');

port.onMessage.addListener((response) => {
    // When the Python script finishes, explicitly look for the Gemini tab
    // instead of relying on the current active window.
    chrome.tabs.query({url: "*://gemini.google.com/*"}, function(tabs) {
        if (tabs && tabs.length > 0) {
            chrome.tabs.sendMessage(tabs[0].id, {type: "HOST_RESPONSE", data: response});
        } else {
            console.warn("Host responded, but no Gemini tab was found to receive it:", response);
        }
    });
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === "SEND_TO_HOST") {
        port.postMessage(request.payload);
    }
});