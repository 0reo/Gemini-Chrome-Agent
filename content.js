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
            // Ensure we capture literally anything returned so it's never blank
            let outputText = message.data.output || message.data.error || message.data.message;
            
            // If it's completely empty, fallback to the raw JSON string
            if (!outputText || outputText.trim() === "") {
                outputText = JSON.stringify(message.data);
            }
            
            const fullText = `System Result:\n${outputText}`;
            
            // 1. Focus the box
            promptBox.focus();
            
            // 2. Clear the box safely
            document.execCommand('selectAll', false, null);
            document.execCommand('delete', false, null);
            
            // 3. Inject text using a true React-compatible Paste Event
            const dataTransfer = new DataTransfer();
            dataTransfer.setData('text/plain', fullText);
            const pasteEvent = new ClipboardEvent('paste', {
                clipboardData: dataTransfer,
                bubbles: true,
                cancelable: true
            });
            promptBox.dispatchEvent(pasteEvent);
            
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