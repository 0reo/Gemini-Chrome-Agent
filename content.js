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

// NEW: Prevent duplicate executions from whitespace streaming and React DOM teardowns
const recentPayloads = new Set();

const observer = new MutationObserver(() => {
    const codeBlocks = document.querySelectorAll('pre code, code');
    
    codeBlocks.forEach(block => {
        const text = block.innerText;
        
        if (text.includes('"action":')) {
            try {
                let payload = JSON.parse(text);
                
                // Normalize the payload to a string (ignores all whitespace/formatting changes)
                let payloadStr = JSON.stringify(payload);
                
                // If we ALREADY sent this exact JSON block in the last 4 seconds, skip it!
                if (recentPayloads.has(payloadStr)) return;
                
                if (isPageLoading) {
                    // Add history payloads to the set so they don't misfire later
                    recentPayloads.add(payloadStr);
                    return; 
                }
                
                // Lock this payload from being sent again
                recentPayloads.add(payloadStr);
                // Unlock it after 4 seconds so you can intentionally run the same command again later
                setTimeout(() => recentPayloads.delete(payloadStr), 4000);
                
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