console.log("Gemini Agent content script loaded!");

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

const recentPayloads = new Set();

const observer = new MutationObserver(() => {
    const codeBlocks = document.querySelectorAll('pre code, code');
    
    codeBlocks.forEach(block => {
        const text = block.innerText;
        
        if (text.includes('"action":')) {
            try {
                let payload = JSON.parse(text);
                let payloadStr = JSON.stringify(payload);
                
                if (block.dataset.processedPayload === payloadStr) return;
                block.dataset.processedPayload = payloadStr;
                
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
        
        const promptBox = document.querySelector('rich-textarea [contenteditable="true"], [role="textbox"][contenteditable="true"], .ql-editor'); 
        
        if (promptBox) {
            let outputText = message.data?.output || message.data?.error || message.data?.message;
            
            if (!outputText || outputText.trim() === "") {
                outputText = JSON.stringify(message.data) || "NO DATA RETURNED FROM PYTHON";
            }
            
            const fullText = `System Result:\n${outputText}`;
            
            // 1. Focus the box aggressively
            promptBox.scrollIntoView();
            promptBox.focus();
            
            // 2. Use keystroke simulation (execCommand) so the React editor respects the input
            document.execCommand('selectAll', false, null);
            document.execCommand('delete', false, null);
            document.execCommand('insertText', false, fullText);
            
            // 3. Wake up the Send button
            promptBox.dispatchEvent(new Event('input', { bubbles: true }));
            
            let attempts = 0;
            const clickInterval = setInterval(() => {
                const sendButton = document.querySelector('button[aria-label*="Send"], button[mattooltip*="Send"]');
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
        } else {
            console.error("Could not find the Gemini text box to inject the result!");
        }
    }
});