#!/usr/bin/env bash
# package.sh — Package a Chrome Extension for Chrome Web Store upload
# Usage: bash package.sh [extension-dir]
# If no dir given, packages the current directory.

set -euo pipefail

EXT_DIR="${1:-.}"
EXT_DIR="${EXT_DIR%/}"  # Remove trailing slash

# Validate manifest exists
if [[ ! -f "${EXT_DIR}/manifest.json" ]]; then
  echo "❌ Error: manifest.json not found in '${EXT_DIR}'"
  echo "   Run from your extension folder or pass the path as an argument."
  exit 1
fi

# Extract name and version from manifest
EXT_NAME=$(node -e "const m=require('./${EXT_DIR}/manifest.json'); console.log(m.name.toLowerCase().replace(/[^a-z0-9]+/g,'-'))" 2>/dev/null \
  || grep '"name"' "${EXT_DIR}/manifest.json" | head -1 | sed 's/.*: *"\(.*\)".*/\1/' | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
EXT_VERSION=$(node -e "const m=require('./${EXT_DIR}/manifest.json'); console.log(m.version)" 2>/dev/null \
  || grep '"version"' "${EXT_DIR}/manifest.json" | head -1 | sed 's/.*: *"\(.*\)".*/\1/')

ZIP_NAME="${EXT_NAME}-v${EXT_VERSION}.zip"

echo "📦 Packaging: ${EXT_NAME} v${EXT_VERSION}"
echo "📁 Source: ${EXT_DIR}"
echo "📄 Output: ${ZIP_NAME}"
echo ""

# Check for common issues before packaging
echo "🔍 Pre-package checks..."

# Check for node_modules
if [[ -d "${EXT_DIR}/node_modules" ]]; then
  echo "⚠️  Warning: node_modules found — will be excluded"
fi

# Check for .map files (source maps — optional to exclude)
MAP_COUNT=$(find "${EXT_DIR}" -name "*.map" 2>/dev/null | wc -l)
if [[ $MAP_COUNT -gt 0 ]]; then
  echo "ℹ️  Found ${MAP_COUNT} .map files — will be excluded"
fi

# Check all icon sizes exist
for size in 16 48 128; do
  if [[ ! -f "${EXT_DIR}/icons/icon${size}.png" ]]; then
    echo "⚠️  Warning: icons/icon${size}.png is missing"
  fi
done

echo ""

# Create the zip (from inside the extension directory so manifest is at root)
cd "${EXT_DIR}"
zip -r "../${ZIP_NAME}" . \
  --exclude "*.git*" \
  --exclude "*.DS_Store" \
  --exclude "*Thumbs.db" \
  --exclude "*node_modules*" \
  --exclude "*.map" \
  --exclude "*.sh" \
  --exclude "*.md" \
  --exclude "__MACOSX*" \
  --exclude "*.zip" \
  --exclude "evals*" \
  --exclude "test*" \
  --exclude "*.test.js" \
  --exclude "*.spec.js"
cd -

echo "✅ Package created: ${ZIP_NAME}"
echo ""
echo "Next steps:"
echo "  1. Test the zip: unzip ${ZIP_NAME} -d /tmp/test-ext && open chrome://extensions"
echo "  2. Load /tmp/test-ext as unpacked to verify"
echo "  3. Upload to: https://chrome.google.com/webstore/devconsole"
