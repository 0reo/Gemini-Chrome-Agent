# Chrome Web Store Publishing Guide

## Pre-Submission Checklist

### Code
- [ ] All `console.log` removed or gated behind debug flag
- [ ] No hardcoded API keys, tokens, or secrets
- [ ] No test/development files in the zip
- [ ] All manifest file paths exist
- [ ] Tested in clean Chrome profile (not dev profile)
- [ ] Tested on Chrome Stable (not just Canary)
- [ ] Valid JSON manifest (`node -e "JSON.parse(require('fs').readFileSync('manifest.json','utf8'))"`)

### Manifest
- [ ] `manifest_version: 3`
- [ ] All 3 icon sizes: `icons/icon16.png`, `icons/icon48.png`, `icons/icon128.png`
- [ ] Permissions are minimal — only what's actually used
- [ ] No `unsafe-eval` in CSP
- [ ] `version` is higher than previous published version (for updates)

### Store listing assets
- [ ] Store icon: 128×128 PNG
- [ ] At least 1 screenshot: 1280×800 or 640×400 PNG/JPG
- [ ] Description is accurate and not keyword-stuffed

---

## Account Setup (One-Time)

1. Go to [Chrome Web Store Developer Dashboard](https://chrome.google.com/webstore/devconsole)
2. Sign in with Google account
3. Pay **$5 one-time registration fee**
4. Accept Developer Agreement

---

## Package the Extension

```bash
# From your extension root directory
zip -r ../my-extension-v1.0.0.zip . \
  --exclude "*.git*" --exclude "*.DS_Store" \
  --exclude "*node_modules*" --exclude "*.map"
```

**Critical**: `manifest.json` must be at the root of the zip — not inside a subfolder.

Max zip size: 128MB. Test your zip: unzip to temp folder and load as unpacked.

---

## Store Listing Fields

**Name** (max 45 chars): Accurate and descriptive. No keyword stuffing.
- ✅ "Dark Mode for GitHub"
- ❌ "Best Dark Mode GitHub Extension Free 2024"

**Summary** (max 132 chars): One clear sentence shown in search results.

**Description** (max 16,000 chars): Explain what it does, key features, how to use it. Briefly justify sensitive permissions.

**Privacy Policy URL**: Required if you collect any user data (including analytics).

---

## Privacy Disclosure (Mandatory)

During submission you'll answer questions about data collection. Common answers:

| You collect this | What to disclose |
|---|---|
| Nothing | "This extension does not collect any user data" |
| Analytics (e.g. GA) | Disclose: usage analytics, not linked to identity |
| User settings stored locally | `chrome.storage.local`, no transmission |
| Auth tokens | Disclose: authentication purposes, not shared |

Misrepresentation → removal from store.

---

## Review Timeline

- New extensions: 1–7 business days
- Updates: 1–3 business days
- Expedited (security fixes): email cws-developer-support@google.com

---

## Common Rejection Reasons & Fixes

| Rejection | Fix |
|---|---|
| Misleading name/description | Use accurate naming. No "Best" / "Free" keyword stuffing |
| Missing privacy policy | Add URL if you handle any user data |
| Overly broad permissions | Reduce scope, justify in description |
| Remotely hosted code | Bundle all JS locally |
| Single purpose violation | Remove unrelated features or split extension |
| `eval()` or `innerHTML` with untrusted input | Refactor to DOM APIs |
| External CDN `<script>` tags | Download and bundle locally |
| Missing icons | Add 16, 48, 128px PNG icons |

---

## Versioning

Format: `"1.2.3"` (up to 4 parts). New version must always be higher than previous.

- Patch: `1.0.0` → `1.0.1` (bug fixes)
- Minor: `1.0.0` → `1.1.0` (new features, backwards compatible)
- Major: `1.0.0` → `2.0.0` (breaking changes, major redesign)

---

## Useful Links

- [Developer Dashboard](https://chrome.google.com/webstore/devconsole)
- [Program Policies](https://developer.chrome.com/docs/webstore/program-policies/)
- [CRX Viewer](https://crxviewer.robwu.nl/) — inspect published extensions
- [Extension Samples](https://github.com/GoogleChrome/chrome-extensions-samples)
