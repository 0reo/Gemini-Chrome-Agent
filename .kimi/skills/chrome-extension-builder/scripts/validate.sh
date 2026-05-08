#!/usr/bin/env bash
# validate.sh — Validate a Chrome Extension manifest and check for common issues
# Usage: bash validate.sh [extension-dir]

set -euo pipefail

EXT_DIR="${1:-.}"
ERRORS=0
WARNINGS=0

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

error()   { echo -e "${RED}❌ ERROR:${NC} $1"; ERRORS=$((ERRORS+1)); }
warn()    { echo -e "${YELLOW}⚠️  WARN:${NC} $1"; WARNINGS=$((WARNINGS+1)); }
success() { echo -e "${GREEN}✅${NC} $1"; }

echo "🔍 Validating Chrome Extension: ${EXT_DIR}"
echo "══════════════════════════════════════════"

# ─── manifest.json exists ────────────────────────────────────────────────────
if [[ ! -f "${EXT_DIR}/manifest.json" ]]; then
  error "manifest.json not found"
  exit 1
fi
success "manifest.json found"

# ─── Valid JSON ───────────────────────────────────────────────────────────────
if node -e "JSON.parse(require('fs').readFileSync('${EXT_DIR}/manifest.json','utf8'))" 2>/dev/null; then
  success "manifest.json is valid JSON"
elif python3 -c "import json; json.load(open('${EXT_DIR}/manifest.json'))" 2>/dev/null; then
  success "manifest.json is valid JSON"
else
  error "manifest.json contains invalid JSON — fix syntax errors"
  exit 1
fi

# ─── Parse manifest fields ───────────────────────────────────────────────────
MV=$(python3 -c "import json,sys; m=json.load(open('${EXT_DIR}/manifest.json')); print(m.get('manifest_version',''))" 2>/dev/null || echo "")
NAME=$(python3 -c "import json; m=json.load(open('${EXT_DIR}/manifest.json')); print(m.get('name',''))" 2>/dev/null || echo "")
VERSION=$(python3 -c "import json; m=json.load(open('${EXT_DIR}/manifest.json')); print(m.get('version',''))" 2>/dev/null || echo "")
PERMS=$(python3 -c "import json; m=json.load(open('${EXT_DIR}/manifest.json')); print(' '.join(m.get('permissions',[])))" 2>/dev/null || echo "")

# ─── Manifest version ─────────────────────────────────────────────────────────
if [[ "$MV" == "3" ]]; then
  success "manifest_version: 3 ✓"
elif [[ "$MV" == "2" ]]; then
  error "manifest_version is 2 — Chrome Web Store no longer accepts MV2. Migrate to MV3."
else
  error "manifest_version is missing or invalid (got: '$MV')"
fi

# ─── Required fields ─────────────────────────────────────────────────────────
[[ -n "$NAME" ]] && success "name: '${NAME}'" || error "name is missing"
[[ -n "$VERSION" ]] && success "version: '${VERSION}'" || error "version is missing"

# ─── Icons ───────────────────────────────────────────────────────────────────
for size in 16 48 128; do
  ICON_PATH="${EXT_DIR}/icons/icon${size}.png"
  if [[ -f "$ICON_PATH" ]]; then
    success "icons/icon${size}.png found"
  else
    warn "icons/icon${size}.png not found — required for Chrome Web Store"
  fi
done

# ─── Referenced files exist ───────────────────────────────────────────────────
POPUP_HTML=$(python3 -c "import json; m=json.load(open('${EXT_DIR}/manifest.json')); print(m.get('action',{}).get('default_popup',''))" 2>/dev/null || echo "")
if [[ -n "$POPUP_HTML" ]]; then
  if [[ -f "${EXT_DIR}/${POPUP_HTML}" ]]; then
    success "Popup found: ${POPUP_HTML}"
  else
    error "Popup file not found: ${POPUP_HTML}"
  fi
fi

SW=$(python3 -c "import json; m=json.load(open('${EXT_DIR}/manifest.json')); print(m.get('background',{}).get('service_worker',''))" 2>/dev/null || echo "")
if [[ -n "$SW" ]]; then
  if [[ -f "${EXT_DIR}/${SW}" ]]; then
    success "Service worker found: ${SW}"
  else
    error "Service worker file not found: ${SW}"
  fi
fi

# ─── Dangerous permissions ────────────────────────────────────────────────────
DANGEROUS_PERMS=("history" "bookmarks" "cookies" "clipboardRead" "nativeMessaging" "debugger" "management")
for perm in "${DANGEROUS_PERMS[@]}"; do
  if echo "$PERMS" | grep -q "$perm"; then
    warn "Sensitive permission '$perm' — requires justification in Chrome Web Store listing"
  fi
done

# ─── Check for eval usage ────────────────────────────────────────────────────
if grep -r --include="*.js" "eval(" "${EXT_DIR}" --exclude-dir=node_modules 2>/dev/null | grep -v "//.*eval" | head -3; then
  warn "eval() usage detected — not allowed in extension pages (CSP violation)"
fi

# ─── Check for inline scripts in HTML ────────────────────────────────────────
HTML_INLINE=$(grep -r --include="*.html" "<script>" "${EXT_DIR}" 2>/dev/null | grep -v "src=" || true)
if [[ -n "$HTML_INLINE" ]]; then
  warn "Inline <script> tags found in HTML — use external .js files instead"
fi

# ─── Check for external scripts ──────────────────────────────────────────────
EXT_SCRIPTS=$(grep -r --include="*.html" 'src="http' "${EXT_DIR}" 2>/dev/null || true)
if [[ -n "$EXT_SCRIPTS" ]]; then
  error "External script URLs found in HTML — bundle all dependencies locally"
fi

# ─── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════"
if [[ $ERRORS -eq 0 && $WARNINGS -eq 0 ]]; then
  echo -e "${GREEN}🎉 All checks passed!${NC}"
elif [[ $ERRORS -eq 0 ]]; then
  echo -e "${YELLOW}⚠️  Passed with ${WARNINGS} warning(s). Review before submitting.${NC}"
else
  echo -e "${RED}❌ ${ERRORS} error(s) and ${WARNINGS} warning(s). Fix errors before publishing.${NC}"
  exit 1
fi
