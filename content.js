// 1. Observe the Gemini DOM for completed responses
const observer = new MutationObserver((mutations) => {
    // You will need to inspect Gemini's DOM to find the exact class that indicates 
    // a message has finished generating. Look for the appearance of the "Copy" or "Thumbs up" buttons.
    const latestMessage = document.querySelector('.latest-gemini-response-class'); // Replace with actual class
    
    if (latestMessage && !latestMessage.dataset.processed) {
        latestMessage.dataset.processed = "true";
        
        // Example parsing logic: if Gemini outputs a specific JSON block, execute it
        const codeBlocks = latestMessage.querySelectorAll('pre code');
        codeBlocks.forEach(block => {
            if (block.innerText.includes('"action": "write_file"')) {
                let payload = JSON.parse(block.innerText);
                chrome.runtime.sendMessage({type: "SEND_TO_HOST", payload: payload});
            }
        });
    }
});

observer.observe(document.body, { childList: true, subtree: true });

// 2. Listen for output from the local machine and inject it into the prompt box
chrome.runtime.onMessage.addListener((message) => {
    if (message.type === "HOST_RESPONSE") {
        // Find Gemini's prompt input box
        const promptBox = document.querySelector('rich-textarea div[contenteditable="true"]'); // Replace with actual selector
        if (promptBox) {
            promptBox.innerText = `Local Execution Result:\n${message.data.output || message.data.message}`;
            
            // Optionally, find the send button and click it to automate the loop
            // document.querySelector('button[aria-label="Send message"]').click();
        }
    }
});