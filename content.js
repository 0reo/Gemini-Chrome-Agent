console.log("Gemini Agent content script loaded!");

let isPageLoading = true;
let isAgentPaused = false;
let historyTimeout;

const createControls = () => {
    if (document.getElementById('gemini-agent-controls')) return;
    const container = document.createElement('div');
    container.id = 'gemini-agent-controls';
    container.style.cssText = 'position:fixed;bottom:80px;right:20px;z-index:10000;background:#1e1e1e;color:white;padding:12px;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,0.4);display:flex;flex-direction:column;gap:10px;font-family:sans-serif;font-size:13px;border:1px solid #333;min-width:150px;';
    const header = document.createElement('div');
    header.innerHTML = '<b>Agent Control</b>';
    const toggleBtn = document.createElement('button');
    toggleBtn.innerText = 'Pause Agent';
    toggleBtn.style.cssText = 'background:#333;color:white;border:1px solid #444;padding:6px;cursor:pointer;border-radius:6px;';
    toggleBtn.onclick = () => {
        isAgentPaused = !isAgentPaused;
        toggleBtn.innerText = isAgentPaused ? 'Resume Agent' : 'Pause Agent';
        toggleBtn.style.borderColor = isAgentPaused ? '#d32f2f' : '#444';
    };
    container.appendChild(header); container.appendChild(toggleBtn);
    document.body.appendChild(container);
    window.addEventListener('keydown', (e) => {
        if (e.altKey && e.shiftKey && e.key === 'K') { isAgentPaused = !isAgentPaused; toggleBtn.click(); }
    });
};

const historyObserver = new MutationObserver(() => {
    clearTimeout(historyTimeout);
    historyTimeout = setTimeout(() => { if (isPageLoading) { isPageLoading = false; createControls(); historyObserver.disconnect(); } }, 1500);
});
historyObserver.observe(document.body, { childList: true, subtree: true });

const recentPayloads = new Set();
const observer = new MutationObserver(() => {
    if (isAgentPaused) return;
    document.querySelectorAll('pre code, code').forEach(block => {
        const text = block.innerText;
        if (text.includes('"action":')) {
            try {
                let payload = JSON.parse(text); let pStr = JSON.stringify(payload);
                if (block.dataset.processedPayload === pStr || recentPayloads.has(pStr)) return;
                block.dataset.processedPayload = pStr; recentPayloads.add(pStr);
                setTimeout(() => recentPayloads.delete(pStr), 10000);
                if (!isPageLoading) chrome.runtime.sendMessage({type: "SEND_TO_HOST", payload: payload});
            } catch (e) { }
        }
    });
});
observer.observe(document.body, { childList: true, subtree: true, characterData: true });

chrome.runtime.onMessage.addListener((message) => {
    if (message.type === "HOST_RESPONSE") {
        const promptBox = document.querySelector('rich-textarea [contenteditable="true"], [role="textbox"][contenteditable="true"], .ql-editor'); 
        if (promptBox) {
            const fullText = `System Result:\n${message.data?.output || message.data?.error || "No Output"}`;
            promptBox.focus();
            const dt = new DataTransfer(); dt.setData('text/plain', fullText);
            const ev = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
            document.execCommand('selectAll', false, null); document.execCommand('delete', false, null);
            promptBox.dispatchEvent(ev);
            if (promptBox.innerText.length < 5) document.execCommand('insertText', false, fullText);
            promptBox.dispatchEvent(new Event('input', { bubbles: true }));
            setTimeout(() => {
                const btn = document.querySelector('button[aria-label*="Send"], [data-testid="send-button"]');
                if (btn && !btn.disabled && !isAgentPaused) btn.click();
            }, 500);
        }
    }
});