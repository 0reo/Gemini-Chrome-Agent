console.log("Gemini Agent content script loaded!");

let isPageLoading = true;
setTimeout(() => {
    isPageLoading = false;
    console.log("History loaded. Agent is now ARMED.");
}, 3000);

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
            const outputText = message.data.output || message.data.message;
            const fullText = `System Result:\n${outputText}`;
            
            // 1. Focus the box so we can simulate user input
            promptBox.focus();
            
            // 2. Select any existing text in the box and clear it
            document.execCommand('selectAll', false, null);
            document.execCommand('delete', false, null);
            
            // 3. Simulate a "Paste" action. This safely formats newlines 
            // and prevents the React UI from treating \n as the Enter key.
            document.execCommand('insertText', false, fullText);
            
            // 4. Wait 500ms for the UI to enable the Send button, then click it
            setTimeout(() => {
                const sendButton = document.querySelector('button[aria-label="Send message"]');
                if (sendButton && !sendButton.disabled) {
                    console.log("Auto-clicking Send...");
                    sendButton.click();
                } else {
                    console.warn("Send button not found or is disabled.");
                }
            }, 500);
        }
    }
});