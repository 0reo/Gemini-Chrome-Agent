console.log("Gemini Agent content script loaded!");

// 1. Observe the DOM for code blocks
const observer = new MutationObserver(() => {
    const codeBlocks = document.querySelectorAll('pre code, code');
    
    codeBlocks.forEach(block => {
        // If we already processed this block, skip it
        if (block.dataset.processed) return;
        
        const text = block.innerText;
        
        // Check if it looks like our agent command
        if (text.includes('"action":')) {
            try {
                // This will fail while Gemini is still streaming word-by-word.
                // It will only succeed once the entire JSON block is completely finished.
                let payload = JSON.parse(text);
                
                // Success! Mark it as processed so we don't run it twice
                block.dataset.processed = "true";
                console.log("Agent payload detected and parsed!", payload);
                
                // Send it to the background script
                chrome.runtime.sendMessage({type: "SEND_TO_HOST", payload: payload});
            } catch (e) {
                // Still streaming or invalid JSON. Do nothing and wait for the next mutation.
            }
        }
    });
});

observer.observe(document.body, { childList: true, subtree: true, characterData: true });

// 2. Listen for output from the local machine and inject it into the prompt box
chrome.runtime.onMessage.addListener((message) => {
    if (message.type === "HOST_RESPONSE") {
        console.log("Received response from Ubuntu:", message.data);
        
        // Find Gemini's prompt input box. 
        // This selector targets the rich-text editor Gemini currently uses.
        const promptBox = document.querySelector('rich-textarea div[contenteditable="true"], .ql-editor'); 
        
        if (promptBox) {
            // Inject the result
            const outputText = message.data.output || message.data.message;
            promptBox.innerHTML = `<p><strong>Local Execution Result:</strong><br>${outputText}</p>`;
            
            // Note: We are manually injecting text, but we won't auto-click "Send" yet 
            // so you can review what happened before the AI gets it.
        } else {
            console.warn("Could not find the Gemini prompt input box to inject the response.");
        }
    }
});