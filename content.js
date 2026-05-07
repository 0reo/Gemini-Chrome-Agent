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
                
                if (isPageLoading) return; 
                
                console.log("Live agent payload detected!", payload);
                chrome.runtime.sendMessage({type: "SEND_TO_HOST", payload: payload});
            } catch (e) { }
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
                outputText = JSON.stringify(message.data) || "NO DATA RETURNED";
            }
            
            const fullText = `System Result:\n${outputText}`;
            
            promptBox.focus();
            
            // --- DATA TRANSFER VIA CLIPBOARD SIMULATION ---
            // This is the most reliable way to wake up a React/Quill editor
            const dataTransfer = new DataTransfer();
            dataTransfer.setData('text/plain', fullText);
            
            const pasteEvent = new ClipboardEvent('paste', {
                clipboardData: dataTransfer,
                bubbles: true,
                cancelable: true
            });

            // Clear existing content first
            document.execCommand('selectAll', false, null);
            document.execCommand('delete', false, null);

            // Dispatch the paste
            promptBox.dispatchEvent(pasteEvent);
            
            // Fallback if paste event is ignored
            if (promptBox.innerText.length < 5) {
                document.execCommand('insertText', false, fullText);
            }

            // Trigger input event to enable Send button
            promptBox.dispatchEvent(new Event('input', { bubbles: true }));

            let attempts = 0;
            const clickInterval = setInterval(() => {
                const sendButton = document.querySelector('button[aria-label*="Send"], button[mattooltip*="Send"], [data-testid="send-button"]');
                if (sendButton && !sendButton.disabled) {
                    clearInterval(clickInterval);
                    sendButton.click();
                } else if (attempts >= 20) {
                    clearInterval(clickInterval);
                }
                attempts++;
            }, 250);
        }
    }
});