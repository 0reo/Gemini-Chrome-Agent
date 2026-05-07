console.log("Gemini Agent content script loaded!");

// 1. Robust History Ignoring: Wait for the DOM to stabilize
let isPageLoading = true;
let historyTimeout;
const historyObserver = new MutationObserver(() => {
    clearTimeout(historyTimeout);
    historyTimeout = setTimeout(() => {
        if (isPageLoading) {
            isPageLoading = false;
            console.log("History stabilized. Agent is now ARMED.");
            historyObserver.disconnect();
        }
    }, 1500);
});
historyObserver.observe(document.body, { childList: true, subtree: true });

// Fallback if no history exists
setTimeout(() => { 
    if (isPageLoading) { 
        isPageLoading = false; 
        console.log("Agent ARMED via fallback."); 
        historyObserver.disconnect(); 
    } 
}, 4000);

const observer = new MutationObserver(() => {
    const codeBlocks = document.querySelectorAll('pre code, code');
    
    codeBlocks.forEach(block => {
        if (block.dataset.processed) return;
        
        const text = block.innerText;
        
        if (text.includes('"action":')) {
            try {
                let payload = JSON.parse(text);
                block.dataset.processed = "true"; 
                
                if (isPageLoading) {
                    console.log("Ignored history block:", payload.action);
                    return; 
                }
                
                console.log("Live agent payload detected!", payload);
                chrome.runtime.sendMessage({type: "SEND_TO_HOST", payload: payload});
            } catch (e) {}
        }
    });
});

observer.observe(document.body, { childList: true, subtree: true, characterData: true });

chrome.runtime.onMessage.addListener((message) => {
    if (message.type === "HOST_RESPONSE") {
        console.log("Received response from Ubuntu:", message.data);
        
        const promptBox = document.querySelector('rich-textarea div[contenteditable="true"], .ql-editor'); 
        
        if (promptBox) {
            // Grab output, OR error, OR message, OR just dump the raw JSON so we never get a blank string
            const outputText = message.data.output || message.data.error || message.data.message || JSON.stringify(message.data);
            const fullText = `System Result:\n${outputText}`;
            
            // 1. Focus the box so we can simulate user input
            promptBox.focus();
            
            // 2. Select any existing text in the box and clear it
            document.execCommand('selectAll', false, null);
            document.execCommand('delete', false, null);
            
            // 3. Simulate a "Paste" action. This safely formats newlines 
        // and prevents the React UI from treating \n as the Enter key.
        document.execCommand('insertText', false, fullText);
        
        // 4. Robust auto-clicker: Poll for the button to be ready (max 3 seconds)
        let attempts = 0;
        const clickInterval = setInterval(() => {
            const sendButton = document.querySelector('button[aria-label="Send message"]');
            if (sendButton && !sendButton.disabled) {
                clearInterval(clickInterval);
                console.log("Auto-clicking Send...");
                sendButton.click();
            } else if (attempts >= 15) {
                clearInterval(clickInterval);
                console.warn("Send button never became enabled.");
            }
            attempts++;
        }, 200);
    }
}
});