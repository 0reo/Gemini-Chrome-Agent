// Version: 2.3 - Cooldown & execution gate to prevent runaway loops
console.log("[Gemini Agent] content script loaded!");

let isAgentPaused = false;
let isCooldown = false;
let cooldownTimer = null;
let executionsThisMinute = 0;
let minuteTimer = null;

const COOLDOWN_MS = 15000;           // 15s after each execution
const MAX_PER_MINUTE = 5;            // auto-pause if exceeded
const SETTLING_PERIOD_MS = 5000;
const PAGE_LOAD_TIME = Date.now();

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
        if (!isAgentPaused) clearCooldown();
        updateUI();
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

function updateUI() {
    const btn = document.querySelector('#gemini-agent-controls button');
    const status = document.getElementById('gemini-agent-status');
    if (!btn || !status) return;
    
    if (isAgentPaused) {
        btn.innerText = 'Resume Agent';
        btn.style.borderColor = '#d32f2f';
        status.innerText = 'Status: Paused';
        status.style.color = '#d32f2f';
    } else if (isCooldown) {
        btn.innerText = 'On Cooldown';
        btn.style.borderColor = '#f9a825';
        status.innerText = 'Status: Cooldown';
        status.style.color = '#f9a825';
    } else {
        btn.innerText = 'Pause Agent';
        btn.style.borderColor = '#444';
        status.innerText = 'Status: Active';
        status.style.color = '#aaa';
    }
}

function setCooldown() {
    isCooldown = true;
    updateUI();
    if (cooldownTimer) clearTimeout(cooldownTimer);
    cooldownTimer = setTimeout(() => {
        isCooldown = false;
        updateUI();
        console.log("[Gemini Agent] Cooldown ended.");
    }, COOLDOWN_MS);
}

function clearCooldown() {
    isCooldown = false;
    if (cooldownTimer) clearTimeout(cooldownTimer);
    updateUI();
}

function trackExecution() {
    executionsThisMinute++;
    if (!minuteTimer) {
        minuteTimer = setTimeout(() => {
            executionsThisMinute = 0;
            minuteTimer = null;
        }, 60000);
    }
    if (executionsThisMinute >= MAX_PER_MINUTE) {
        console.warn(`[Gemini Agent] Rate limit hit (${MAX_PER_MINUTE}/min). Auto-pausing.`);
        isAgentPaused = true;
        updateUI();
    }
}

createControls();

// --- Deduplication System ---
const processedPayloads = new Map();
const PAYLOAD_TTL_MS = 60000;
const CLEANUP_INTERVAL_MS = 5000;
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

function isSettling() {
    return (Date.now() - PAGE_LOAD_TIME) < SETTLING_PERIOD_MS;
}

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
        } catch (e) {}
    }
    if (marked > 0) {
        console.log(`[Gemini Agent] Marked ${marked} existing payload(s) as processed.`);
    }
}

// --- Debounced Payload Detection ---
let scanTimeout = null;
const SCAN_DEBOUNCE_MS = 250;

const observer = new MutationObserver(() => {
    if (isAgentPaused || isCooldown) return;
    if (scanTimeout) clearTimeout(scanTimeout);
    scanTimeout = setTimeout(scanForPayloads, SCAN_DEBOUNCE_MS);
});

function scanForPayloads() {
    scanTimeout = null;
    const settling = isSettling();
    const blocks = document.querySelectorAll('pre code, code');
    for (const block of blocks) {
        const text = block.textContent;
        if (!text.includes('"action"')) continue;
        try {
            let payload = JSON.parse(text);
            if (!isValidAgentPayload(payload)) continue;
            if (isRecentlyProcessed(payload)) continue;

            if (settling) {
                console.log("[Gemini Agent] Settling: ignored historical payload:", payload.action);
                continue;
            }

            console.log("[Gemini Agent] Executing action:", payload.action, payload);
            chrome.runtime.sendMessage({type: "SEND_TO_HOST", payload: payload});
            setCooldown();
            trackExecution();
        } catch (e) {}
    }
}

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
    document.execCommand('selectAll', false, null);
    document.execCommand('delete', false, null);
    
    const dt = new DataTransfer();
    dt.setData('text/plain', text);
    const pasteEvent = new ClipboardEvent('paste', { 
        clipboardData: dt, 
        bubbles: true, 
        cancelable: true 
    });
    element.dispatchEvent(pasteEvent);
    
    if (element.innerText.length < 5) {
        document.execCommand('insertText', false, text);
    }
    if (element.innerText.length < 5) {
        element.innerText = text;
    }
    
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
    const maxAttempts = 50;
    
    const interval = setInterval(() => {
        if (isAgentPaused) {
            clearInterval(interval);
            return;
        }
        
        let sendButton = null;
        for (const selector of buttonSelectors) {
            try {
                const btn = document.querySelector(selector);
                if (btn && btn.disabled === false) {
                    sendButton = btn;
                    break;
                }
            } catch (e) {}
        }
        
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
