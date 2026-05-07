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

// Global lock to prevent rapid-fire duplicates across different elements
const recentPayloads = new Set();

const observer = new MutationObserver(() => {
    const codeBlocks = document.querySelectorAll('pre code, code');
    
    codeBlocks.forEach(block => {
        const text = block.innerText;
        
        if (text.includes('"action":')) {
            try {
                let payload = JSON.parse(text);
                let payloadStr = JSON.stringify(payload); // Normalize formatting
                
                // If THIS specific code block already processed this exact payload, skip it.
                if (block.dataset.processedPayload === payloadStr) return;
                block.dataset.processedPayload = payloadStr;
                
                // If ANY block recently fired this exact payload, skip it (4-second lock)
                if (recentPayloads.has(payloadStr)) return;
                
                recentPayloads.add(payloadStr);
                setTimeout(() => recentPayloads.delete(payloadStr), 4000);
                
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
            
            if (!outputText || outputText.trim() === "") {
                outputText = JSON.stringify(message.data);
            }
            
            const fullText = `System Result:\n${outputText}`;
            
            promptBox.focus();
            document.execCommand('selectAll', false, null);
            document.execCommand('delete', false, null);
            document.execCommand('insertText', false, fullText);
            promptBox.dispatchEvent(new Event('input', { bubbles: true }));
            
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