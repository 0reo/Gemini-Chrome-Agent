// Version: 2.1 - Non-blocking debounced payload detection with initial scan
console.log("[Gemini Agent] content script loaded!");

let isAgentPaused = false;

// --- Agent Controls UI ---
const createControls = () => {
    if (document.getElementById('gemini-agent-controls')) return;
    const container = document.createElement('div');
    container.id = 'gemini-agent-controls';
    container.style.cssText = 'position:fixed;bottom:80px;right:20px;z-index:10000;background:#1e1e1e;color:white;padding:12px;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,0.4);display:flex;flex-direction:column;gap:10px;font-family:sans-serif;font-size:13px;border:1px solid #333;min-width:150px;';
    
    const header = document.createElement('div');
    header.innerHTML = '<b>Agent Control</b>';
    
    const statusText = document.createElement('div');
    statusText.id = 'gemini-agent-status';
    statusText.innerText = 'Status: Active';
    statusText.style.cssText = 'font-size:11px;color:#aaa;';
    
    const toggleBtn = document.createElement('button');
    toggleBtn.innerText = 'Pause Agent';
    toggleBtn.style.cssText = 'background:#333;color:white;border:1px solid #444;padding:6px;cursor:pointer;border-radius:6px;width:100%;';
    
    toggleBtn.onclick = () => {
        isAgentPaused = !isAgentPaused;
        toggleBtn.innerText = isAgentPaused ? 'Resume Agent' : 'Pause Agent';
        toggleBtn.style.borderColor = isAgentPaused ? '#d32f2f' : '#444';
        statusText.innerText = isAgentPaused ? 'Status: Paused' : 'Status: Active';
        statusText.style.color = isAgentPaused ? '#d32f2f' : '#aaa';
        console.log("[Gemini Agent] State changed. Paused:", isAgentPaused);
    };

    container.appendChild(header);
    container.appendChild(statusText);
    container.appendChild(toggleBtn);
    document.body.appendChild(container);

    window.addEventListener('keydown', (e) => {
        if (e.altKey && e.shiftKey && e.key === 'K') {
            toggleBtn.click();
        }
    });
};

createControls();

// --- Deduplication System ---
const processedPayloads = new Map(); // hash -> timestamp
const PAYLOAD_TTL_MS = 60000; // 60 seconds
const CLEANUP_INTERVAL_MS = 5000; // only clean stale entries every 5s
let lastCleanup = 0;
const VALID_ACTIONS = new Set(['run_shell', 'write_file', 'read_file']);

function getPayloadHash(payload) {
    try {
        const canonical = JSON.stringify(payload, Object.keys(payload).sort());
        let hash = 0;
        for (let i = 0; i < canonical.length; i++) {
            const char = canonical.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash;
        }
        return hash.toString(16);
    } catch {
        return String(Math.random());
    }
}

function isRecentlyProcessed(payload) {
    const now = Date.now();
    const hash = getPayloadHash(payload);
    
    // Periodic cleanup of old entries (throttled to avoid iterating every scan)
    if (now - lastCleanup > CLEANUP_INTERVAL_MS) {
        lastCleanup = now;
        for (const [key, time] of processedPayloads.entries()) {
            if (now - time > PAYLOAD_TTL_MS) {
                processedPayloads.delete(key);
            }
        }
    }
    
    if (processedPayloads.has(hash)) {
        return true;
    }
    
    processedPayloads.set(hash, now);
    return false;
}

function isValidAgentPayload(payload) {
    if (!payload || typeof payload !== 'object') return false;
    const action = payload.action;
    if (!action || !VALID_ACTIONS.has(action)) return false;
    
    if (action === 'run_shell' && typeof payload.command !== 'string') return false;
    if (action === 'write_file' && (typeof payload.filepath !== 'string' || typeof payload.content !== 'string')) return false;
    if (action === 'read_file' && typeof payload.filepath !== 'string') return false;
    
    return true;
}

// --- Mark existing blocks on load (prevents re-execution on refresh) ---
function markExistingBlocks() {
    const blocks = document.querySelectorAll('pre code, code');
    let marked = 0;
    for (const block of blocks) {
        const text = block.textContent;
        if (!text.includes('"action"')) continue;
        try {
            const payload = JSON.parse(text);
            if (isValidAgentPayload(payload)) {
                isRecentlyProcessed(payload);
                marked++;
            }
        } catch (e) {
            // Not valid JSON yet or not an agent payload
        }
    }
    if (marked > 0) {
        console.log(`[Gemini Agent] Marked ${marked} existing payload(s) as processed.`);
    }
}

// --- Debounced Payload Detection ---
// Scanning the DOM on every mutation causes severe jank while Gemini streams.
// We debounce so the scan only runs after mutations settle.
let scanTimeout = null;
const SCAN_DEBOUNCE_MS = 250;

const observer = new MutationObserver(() => {
    if (isAgentPaused) return;
    if (scanTimeout) clearTimeout(scanTimeout);
    scanTimeout = setTimeout(scanForPayloads, SCAN_DEBOUNCE_MS);
});

function scanForPayloads() {
    scanTimeout = null;
    // textContent is orders of magnitude faster than innerText because it
    // does not force a layout recalculation.
    const blocks = document.querySelectorAll('pre code, code');
    for (const block of blocks) {
        const text = block.textContent;
        if (!text.includes('"action"')) continue;
        
        try {
            let payload = JSON.parse(text);
            if (!isValidAgentPayload(payload)) continue;
            if (isRecentlyProcessed(payload)) continue;

            console.log("[Gemini Agent] Executing action:", payload.action, payload);
            chrome.runtime.sendMessage({type: "SEND_TO_HOST", payload: payload});
        } catch (e) { 
            // JSON.parse fails while streaming — expected, ignore
        }
    }
}

// Mark existing blocks BEFORE observing, then watch for new ones
markExistingBlocks();
observer.observe(document.body, { childList: true, subtree: true, characterData: true });

// --- Response Injection ---
chrome.runtime.onMessage.addListener((message) => {
    if (message.type === "HOST_RESPONSE") {
        if (isAgentPaused) {
            console.log("[Gemini Agent] Response received but agent is paused; ignoring.");
            return;
        }
        injectResponse(message.data);
    }
});

function injectResponse(data) {
    const outputText = data?.output || data?.error || data?.message || "Command completed.";
    const fullText = `System Result:\n${outputText}`;
    
    const inputStrategies = [
        () => {
            const el = document.querySelector('rich-textarea [contenteditable="true"]');
            if (el) return injectIntoContentEditable(el, fullText);
            return false;
        },
        () => {
            const el = document.querySelector('[role="textbox"][contenteditable="true"]');
            if (el) return injectIntoContentEditable(el, fullText);
            return false;
        },
        () => {
            const el = document.querySelector('.ql-editor');
            if (el) return injectIntoContentEditable(el, fullText);
            return false;
        },
        () => {
            const el = document.querySelector('textarea');
            if (el) {
                el.focus();
                el.value = fullText;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }
            return false;
        }
    ];
    
    let injected = false;
    for (const strategy of inputStrategies) {
        try {
            if (strategy()) {
                injected = true;
                break;
            }
        } catch (e) {
            console.warn("[Gemini Agent] Injection strategy failed:", e);
        }
    }
    
    if (!injected) {
        console.error("[Gemini Agent] Could not find any injectable input element.");
        return;
    }
    
    triggerSend();
}

function injectIntoContentEditable(element, text) {
    element.focus();
    
    // Clear existing content
    document.execCommand('selectAll', false, null);
    document.execCommand('delete', false, null);
    
    // Strategy A: Clipboard paste event (often triggers React state updates)
    const dt = new DataTransfer();
    dt.setData('text/plain', text);
    const pasteEvent = new ClipboardEvent('paste', { 
        clipboardData: dt, 
        bubbles: true, 
        cancelable: true 
    });
    element.dispatchEvent(pasteEvent);
    
    // Strategy B: execCommand fallback
    if (element.innerText.length < 5) {
        document.execCommand('insertText', false, text);
    }
    
    // Strategy C: Direct property manipulation for stubborn frameworks
    if (element.innerText.length < 5) {
        element.innerText = text;
    }
    
    // Dispatch framework lifecycle events
    ['input', 'change', 'compositionend', 'keyup', 'keydown'].forEach(type => {
        element.dispatchEvent(new Event(type, { bubbles: true }));
    });
    
    return true;
}

function triggerSend() {
    const buttonSelectors = [
        'button[aria-label="Send message"]',
        'button[aria-label*="Send"]',
        'button[mattooltip*="Send"]',
        'button[data-testid="send-button"]',
        'button.send-button',
        'button[aria-label*="send"]',
    ];
    
    let attempts = 0;
    const maxAttempts = 50; // 10 seconds total
    
    const interval = setInterval(() => {
        if (isAgentPaused) {
            clearInterval(interval);
            return;
        }
        
        let sendButton = null;
        
        // Selector-based search
        for (const selector of buttonSelectors) {
            try {
                const btn = document.querySelector(selector);
                if (btn && btn.disabled === false) {
                    sendButton = btn;
                    break;
                }
            } catch (e) { /* invalid selector */ }
        }
        
        // Text-content fallback
        if (!sendButton) {
            sendButton = Array.from(document.querySelectorAll('button')).find(btn => {
                const text = (btn.innerText || btn.textContent || '').toLowerCase();
                const aria = (btn.getAttribute('aria-label') || '').toLowerCase();
                return (text.includes('send') || aria.includes('send')) && !btn.disabled;
            });
        }
        
        if (sendButton) {
            clearInterval(interval);
            sendButton.click();
            console.log("[Gemini Agent] Auto-submitted response.");
            return;
        }
        
        // Keep triggering input events to enable the button
        triggerInputEvents();
        
        if (++attempts >= maxAttempts) {
            clearInterval(interval);
            console.warn("[Gemini Agent] Failed to find enabled send button after maximum attempts.");
        }
    }, 200);
}

function triggerInputEvents() {
    const inputs = document.querySelectorAll(
        'rich-textarea [contenteditable="true"], ' +
        '[role="textbox"][contenteditable="true"], ' +
        '.ql-editor, ' +
        'textarea'
    );
    inputs.forEach(el => {
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }));
        el.dispatchEvent(new KeyboardEvent('keyup', { key: 'a', bubbles: true }));
    });
}
