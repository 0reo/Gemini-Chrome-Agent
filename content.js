console.log("Gemini Agent content script loaded!");

// 1. Robust History Ignoring
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
        const text = block.innerText;
        
        // If we already processed THIS EXACT text, skip it.
        // This prevents the loop breaking when React recycles DOM elements (like on Regenerate).
        if (block.dataset.processedText === text) return;
        
        if (text.includes('"action":')) {
            try {
                let payload = JSON.parse(text);
                block.dataset.processedText = text; // Mark this specific payload text as processed
                
                if (isPageLoading) {
                    console.log("Ignored history block:", payload.action);
                    return; 
                }
                
                console.log("Live agent payload detected!", payload);
                chrome.runtime.sendMessage({type: "SEND_TO_HOST", payload: payload});
            } catch (e) {
                // Still streaming JSON
            }
        }
    });
});

observer.observe(document.body, { childList: true, subtree: true, characterData: true });

chrome.runtime.onMessage.addListener((message) => {
    if (message.type === "HOST_RESPONSE") {
        console.log("Received response from Ubuntu:", message.data);
        
        const promptBox = document.querySelector('rich-textarea div[contenteditable="true"], .ql-editor'); 
        
        if (promptBox) {
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
            
            // 3. Inject text safely
            document.execCommand('insertText', false, fullText);
            
            // 4. Wake up React so it knows the text changed and enables the Send button
            promptBox.dispatchEvent(new Event('input', { bubbles: true }));
            
            // 5. Poll for the Send button to become enabled
            let attempts = 0;
            const clickInterval = setInterval(() => {
                const sendButton = document.querySelector('button[aria-label*="Send"]');
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