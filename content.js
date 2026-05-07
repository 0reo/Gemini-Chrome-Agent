console.log("Gemini Agent content script loaded!");

let isPageLoading = true;
let isAgentPaused = false;
let historyTimeout;

// 1. Create Control Panel UI
const createControls = () => {
    if (document.getElementById('gemini-agent-controls')) return;

    const container = document.createElement('div');
    container.id = 'gemini-agent-controls';
    container.style.cssText = `
        position: fixed;
        bottom: 80px;
        right: 20px;
        z-index: 10000;
        background: #1e1e1e;
        color: white;
        padding: 12px;
        border-radius: 12px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.4);
        display: flex;
        flex-direction: column;
        gap: 10px;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        font-size: 13px;
        border: 1px solid #333;
        min-width: 150px;
    `;

    const header = document.createElement('div');
    header.style.cssText = 'display: flex; align-items: center; justify-content: space-between; font-weight: bold; border-bottom: 1px solid #333; padding-bottom: 5px;';
    
    const statusDot = document.createElement('span');
    statusDot.id = 'agent-status-dot';
    statusDot.style.cssText = 'width: 8px; height: 8px; border-radius: 50%; background: #4caf50; display: inline-block; margin-right: 8px;';
    
    header.innerHTML = '<span>Agent Control</span>';
    header.prepend(statusDot);

    const toggleBtn = document.createElement('button');
    toggleBtn.innerText = 'Pause Agent';
    toggleBtn.style.cssText = 'background: #333; color: white; border: 1px solid #444; padding: 6px; cursor: pointer; border-radius: 6px; font-weight: 500; transition: all 0.2s;';
    
    const updateUIState = () => {
        toggleBtn.innerText = isAgentPaused ? 'Resume Agent' : 'Pause Agent';
        toggleBtn.style.borderColor = isAgentPaused ? '#d32f2f' : '#444';
        statusDot.style.background = isAgentPaused ? '#f44336' : '#4caf50';
    };

    toggleBtn.onclick = () => {
        isAgentPaused = !isAgentPaused;
        updateUIState();
        console.log("Agent Paused State:", isAgentPaused);
    };

    const clearCacheBtn = document.createElement('button');
    clearCacheBtn.innerText = 'Reset Session Cache';
    clearCacheBtn.style.cssText = 'background: transparent; color: #888; border: none; padding: 4px; cursor: pointer; font-size: 11px; text-decoration: underline;';
    clearCacheBtn.onclick = () => {
        recentPayloads.clear();
        console.log("Payload cache cleared.");
    };

    const shortcutHint = document.createElement('div');
    shortcutHint.innerText = 'Alt+Shift+K to Stop';
    shortcutHint.style.cssText = 'font-size: 10px; color: #555; text-align: center; margin-top: 4px;';

    container.appendChild(header);
    container.appendChild(toggleBtn);
    container.appendChild(clearCacheBtn);
    container.appendChild(shortcutHint);
    document.body.appendChild(container);

    // Keyboard Listener
    window.addEventListener('keydown', (e) => {
        if (e.altKey && e.shiftKey && e.key === 'K') {
            isAgentPaused = !isAgentPaused;
            updateUIState();
            console.warn("Agent Toggled via Hotkey. Paused:", isAgentPaused);
        }
    });
};

// 2. History Stabilization
const historyObserver = new MutationObserver(() => {
    clearTimeout(historyTimeout);
    historyTimeout = setTimeout(() => {
        if (isPageLoading) {
            isPageLoading = false;
            console.log("History stabilized. Agent ARMED.");
            createControls();
            historyObserver.disconnect();
        }
    }, 1500);
});
historyObserver.observe(document.body, { childList: true, subtree: true });

setTimeout(() => { 
    if (isPageLoading) { 
        isPageLoading = false; 
        console.log("Agent ARMED via fallback."); 
        createControls();
        historyObserver.disconnect(); 
    } 
}, 4000);

const recentPayloads = new Set();

// 3. Command Scraper
const observer = new MutationObserver(() => {
    if (isAgentPaused) return;

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
                setTimeout(() => recentPayloads.delete(payloadStr), 10000);
                
                if (isPageLoading) return; 
                
                console.log("Agent payload detected!", payload);
                chrome.runtime.sendMessage({type: "SEND_TO_HOST", payload: payload});
            } catch (e) { }
        }
    });
});

observer.observe(document.body, { childList: true, subtree: true, characterData: true });

// 4. Result Injection
chrome.runtime.onMessage.addListener((message) => {
    if (message.type === "HOST_RESPONSE") {
        console.log("Received from host:", message.data);
        
        const promptBox = document.querySelector('rich-textarea [contenteditable="true"], [role="textbox"][contenteditable="true"], .ql-editor'); 
        
        if (promptBox) {
            let outputText = message.data?.output || message.data?.error || message.data?.message;
            if (!outputText || outputText.trim() === "") {
                outputText = JSON.stringify(message.data) || "NO DATA RETURNED";
            }
            
            const fullText = `System Result:\n${outputText}`;
            promptBox.focus();
            
            const dataTransfer = new DataTransfer();
            dataTransfer.setData('text/plain', fullText);
            const pasteEvent = new ClipboardEvent('paste', {
                clipboardData: dataTransfer,
                bubbles: true,
                cancelable: true
            });

            document.execCommand('selectAll', false, null);
            document.execCommand('delete', false, null);
            promptBox.dispatchEvent(pasteEvent);
            
            if (promptBox.innerText.length < 5) {
                document.execCommand('insertText', false, fullText);
            }

            promptBox.dispatchEvent(new Event('input', { bubbles: true }));

            let attempts = 0;
            const clickInterval = setInterval(() => {
                const sendButton = document.querySelector('button[aria-label*="Send"], button[mattooltip*="Send"], [data-testid="send-button"]');
                if (sendButton && !sendButton.disabled && !isAgentPaused) {
                    clearInterval(clickInterval);
                    sendButton.click();
                } else if (attempts >= 20 || isAgentPaused) {
                    clearInterval(clickInterval);
                }
                attempts++;
            }, 250);
        }
    }
});