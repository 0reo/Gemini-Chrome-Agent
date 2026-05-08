#!/usr/bin/env bash
# scaffold.sh — Generate a Chrome Extension folder structure
# Usage: bash scaffold.sh <extension-name> [type]
# Types: popup | content | background | full (default: full)

set -euo pipefail

# ─── Args ────────────────────────────────────────────────────────────────────
EXT_NAME="${1:-my-extension}"
EXT_TYPE="${2:-full}"
EXT_DIR="./${EXT_NAME}"

# Convert name to title case for display
EXT_TITLE=$(echo "$EXT_NAME" | sed 's/-/ /g' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) substr($i,2); print}')

echo "🔧 Scaffolding Chrome Extension: ${EXT_TITLE} (type: ${EXT_TYPE})"
echo "📁 Output directory: ${EXT_DIR}"
echo ""

# ─── Create Directories ──────────────────────────────────────────────────────
mkdir -p "${EXT_DIR}/icons"

if [[ "$EXT_TYPE" == "popup" || "$EXT_TYPE" == "full" ]]; then
  mkdir -p "${EXT_DIR}/popup"
fi
if [[ "$EXT_TYPE" == "content" || "$EXT_TYPE" == "full" ]]; then
  mkdir -p "${EXT_DIR}/content"
fi
if [[ "$EXT_TYPE" == "background" || "$EXT_TYPE" == "full" ]]; then
  mkdir -p "${EXT_DIR}/background"
fi
if [[ "$EXT_TYPE" == "full" ]]; then
  mkdir -p "${EXT_DIR}/options"
  mkdir -p "${EXT_DIR}/assets"
fi

# ─── manifest.json ────────────────────────────────────────────────────────────
cat > "${EXT_DIR}/manifest.json" << MANIFEST
{
  "manifest_version": 3,
  "name": "${EXT_TITLE}",
  "version": "1.0.0",
  "description": "A Chrome extension",

  "icons": {
    "16": "icons/icon16.png",
    "48": "icons/icon48.png",
    "128": "icons/icon128.png"
  },

  "action": {
    "default_popup": "popup/popup.html",
    "default_icon": { "48": "icons/icon48.png" },
    "default_title": "${EXT_TITLE}"
  },

  "background": {
    "service_worker": "background/service-worker.js"
  },

  "content_scripts": [
    {
      "matches": ["<all_urls>"],
      "js": ["content/content.js"],
      "run_at": "document_end"
    }
  ],

  "permissions": [
    "activeTab",
    "storage"
  ],

  "options_page": "options/options.html"
}
MANIFEST

echo "✅ Created manifest.json"

# ─── popup/popup.html ────────────────────────────────────────────────────────
if [[ -d "${EXT_DIR}/popup" ]]; then
cat > "${EXT_DIR}/popup/popup.html" << 'HTML'
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <link rel="stylesheet" href="popup.css" />
</head>
<body>
  <div class="container">
    <h1 class="title">Extension</h1>
    <button id="actionBtn">Do Something</button>
    <div id="output"></div>
  </div>
  <script src="popup.js"></script>
</body>
</html>
HTML

cat > "${EXT_DIR}/popup/popup.css" << 'CSS'
* { box-sizing: border-box; }
body { width: 320px; min-height: 200px; margin: 0; padding: 16px; font-family: -apple-system, sans-serif; }
.title { font-size: 1.25rem; font-weight: 700; margin-bottom: 16px; }
button { padding: 8px 16px; background: #2563EB; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 0.875rem; }
button:hover { background: #1d4ed8; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
#output { margin-top: 16px; font-size: 0.875rem; color: #374151; }
CSS

cat > "${EXT_DIR}/popup/popup.js" << 'JS'
"use strict";

document.addEventListener("DOMContentLoaded", async () => {
  const actionBtn = document.getElementById("actionBtn");
  const output = document.getElementById("output");

  actionBtn.addEventListener("click", async () => {
    actionBtn.disabled = true;
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      chrome.tabs.sendMessage(tab.id, { action: "ping" }, (response) => {
        if (chrome.runtime.lastError) {
          output.textContent = "No content script on this page.";
        } else {
          output.textContent = JSON.stringify(response, null, 2);
        }
        actionBtn.disabled = false;
      });
    } catch (err) {
      output.textContent = "Error: " + err.message;
      actionBtn.disabled = false;
    }
  });
});
JS
echo "✅ Created popup/"
fi

# ─── content/content.js ──────────────────────────────────────────────────────
if [[ -d "${EXT_DIR}/content" ]]; then
cat > "${EXT_DIR}/content/content.js" << 'JS'
"use strict";

if (window.__extInjected) throw new Error("Already injected");
window.__extInjected = true;

console.log("[Extension] Content script loaded:", location.href);

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === "ping") {
    sendResponse({ pong: true, url: location.href, title: document.title });
  }
});
JS
echo "✅ Created content/content.js"
fi

# ─── background/service-worker.js ────────────────────────────────────────────
if [[ -d "${EXT_DIR}/background" ]]; then
cat > "${EXT_DIR}/background/service-worker.js" << 'JS'
"use strict";

chrome.runtime.onInstalled.addListener(async ({ reason }) => {
  if (reason === "install") {
    console.log("[SW] Extension installed");
    await chrome.storage.local.set({ enabled: true });
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  console.log("[SW] Message:", message.action);
  sendResponse({ received: true });
});
JS
echo "✅ Created background/service-worker.js"
fi

# ─── options/options.html ────────────────────────────────────────────────────
if [[ -d "${EXT_DIR}/options" ]]; then
cat > "${EXT_DIR}/options/options.html" << 'HTML'
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
</head>
<body>
  <h1>Settings</h1>
  <label><input type="checkbox" id="enabled" /> Enable Extension</label>
  <br><br>
  <button id="save">Save</button>
  <span id="status"></span>
  <script src="options.js"></script>
</body>
</html>
HTML

cat > "${EXT_DIR}/options/options.js" << 'JS'
"use strict";
const enabledCb = document.getElementById("enabled");
const saveBtn = document.getElementById("save");
const statusEl = document.getElementById("status");

(async () => {
  const { enabled = true } = await chrome.storage.local.get("enabled");
  enabledCb.checked = enabled;
})();

saveBtn.addEventListener("click", async () => {
  await chrome.storage.local.set({ enabled: enabledCb.checked });
  statusEl.textContent = " Saved!";
  setTimeout(() => { statusEl.textContent = ""; }, 2000);
});
JS
echo "✅ Created options/"
fi

# ─── README.md ────────────────────────────────────────────────────────────────
cat > "${EXT_DIR}/README.md" << README
# ${EXT_TITLE}

A Chrome browser extension built with Manifest V3.

## Development

1. Open \`chrome://extensions\`
2. Enable **Developer Mode** (top-right toggle)
3. Click **Load unpacked** → select this folder
4. Make changes, then click the reload ↺ button on the extension card

## Structure

\`\`\`
${EXT_NAME}/
├── manifest.json          # Extension configuration
├── popup/                 # Popup UI (shown when clicking the icon)
├── content/               # Content scripts (run on web pages)
├── background/            # Service worker (background logic)
├── options/               # Settings page
└── icons/                 # Extension icons
\`\`\`

## Publishing

Run \`bash ../scripts/package.sh\` to create a zip for Chrome Web Store upload.
README

echo "✅ Created README.md"

# ─── Create placeholder icon ─────────────────────────────────────────────────
# Create a simple SVG placeholder (convert to PNG for production)
cat > "${EXT_DIR}/icons/icon.svg" << 'SVG'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">
  <rect width="128" height="128" rx="24" fill="#2563EB"/>
  <text x="64" y="80" font-size="64" text-anchor="middle" fill="white" font-family="sans-serif">E</text>
</svg>
SVG

echo "✅ Created icons/icon.svg (replace icon*.png files with real PNG icons before publishing)"

echo ""
echo "🎉 Done! Extension scaffolded at: ${EXT_DIR}"
echo ""
echo "Next steps:"
echo "  1. cd ${EXT_DIR}"
echo "  2. Add real PNG icons (16x16, 48x48, 128x128) to icons/"
echo "  3. Open chrome://extensions → Load unpacked → select ${EXT_DIR}"
echo "  4. Start building your features!"
