let port = chrome.runtime.connectNative('com.local.gemini_agent');

port.onMessage.addListener((response) => {
    // When the Python script finishes writing a file or running a shell command,
    // it sends the output back here. We route it back to the Gemini web tab.
    chrome.tabs.query({active: true, currentWindow: true}, function(tabs) {
        chrome.tabs.sendMessage(tabs[0].id, {type: "HOST_RESPONSE", data: response});
    });
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.type === "SEND_TO_HOST") {
        port.postMessage(request.payload);
    }
});