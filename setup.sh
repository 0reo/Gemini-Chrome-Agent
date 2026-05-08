#!/bin/bash

# Get the absolute path of the directory where this script is located
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
HOST_SCRIPT="$PROJECT_DIR/host.py"
MANIFEST_FILE="$PROJECT_DIR/com.local.gemini_agent.json"
BRAVE_NM_DIR="$HOME/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts"
SYMLINK_PATH="$BRAVE_NM_DIR/com.local.gemini_agent.json"
WXT_OUTPUT_DIR="$PROJECT_DIR/.output/chrome-mv3"

echo "=== Gemini Agent Native Messaging Setup for Brave ==="

# 1. Check that Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "✖ Error: Python 3 is required but not found in PATH."
    echo "Please install Python 3 and try again."
    exit 1
fi
echo "✔ Python 3 found: $(python3 --version)"

# 2. Check that the WXT build output exists
if [ ! -f "$WXT_OUTPUT_DIR/manifest.json" ]; then
    echo "✖ Error: Extension build output not found at $WXT_OUTPUT_DIR/manifest.json"
    echo "Please run 'npm run build' first to generate the extension files."
    exit 1
fi
echo "✔ Extension build output found at $WXT_OUTPUT_DIR"

# 3. Make the Python host script executable and verify it exists
if [ -f "$HOST_SCRIPT" ]; then
    chmod +x "$HOST_SCRIPT"
    if [ ! -x "$HOST_SCRIPT" ]; then
        echo "✖ Error: host.py exists but could not be made executable."
        echo "Check permissions on $PROJECT_DIR."
        exit 1
    fi
    echo "✔ Made host.py executable."
else
    echo "✖ Error: host.py not found in $PROJECT_DIR."
    echo "Please make sure host.py is in the same directory as this setup script."
    exit 1
fi

# 4. Ask for the Extension ID
echo ""
echo "Please go to brave://extensions/"
echo "Enable Developer mode, then click 'Load unpacked' and select:"
echo "  $WXT_OUTPUT_DIR"
echo "Copy the generated Extension ID."
read -p "Paste your Extension ID here: " EXTENSION_ID

if [ -z "$EXTENSION_ID" ]; then
    echo "✖ Error: Extension ID cannot be empty. Setup aborted."
    exit 1
fi

# Validate Extension ID format: exactly 32 lowercase alphanumeric characters
if ! [[ "$EXTENSION_ID" =~ ^[a-z0-9]{32}$ ]]; then
    echo "✖ Error: Invalid Extension ID format."
    echo "Extension IDs must be exactly 32 lowercase alphanumeric characters."
    echo "Example: abcdefghijklmnopqrstuvwxyz123456"
    exit 1
fi
echo "✔ Extension ID format is valid."

# 5. Generate the Native Messaging Manifest with absolute paths and the provided ID
echo "Generating Native Messaging Manifest..."
cat > "$MANIFEST_FILE" << EOF
{
  "name": "com.local.gemini_agent",
  "description": "Local agent for Gemini Web App",
  "path": "$HOST_SCRIPT",
  "type": "stdio",
  "allowed_origins": [
    "chrome-extension://$EXTENSION_ID/"
  ]
}
EOF
echo "✔ Generated com.local.gemini_agent.json with absolute path: $HOST_SCRIPT"

# 6. Create the Brave Native Messaging directory if it doesn't exist and verify write access
if [ ! -d "$BRAVE_NM_DIR" ]; then
    mkdir -p "$BRAVE_NM_DIR"
fi

if [ ! -w "$BRAVE_NM_DIR" ]; then
    echo "✖ Error: Cannot write to Brave Native Messaging directory:"
    echo "  $BRAVE_NM_DIR"
    echo "Check permissions and try again."
    exit 1
fi
echo "✔ Brave Native Messaging directory is writable."

# 7. Create the symlink
ln -sf "$MANIFEST_FILE" "$SYMLINK_PATH"
if [ ! -L "$SYMLINK_PATH" ]; then
    echo "✖ Error: Failed to create symlink at $SYMLINK_PATH"
    exit 1
fi
echo "✔ Created symlink at $SYMLINK_PATH"

echo ""
echo "=== Setup Complete! ==="
echo "If your extension is already loaded in Brave, click the 'Refresh' icon on the extension page to apply changes."
echo "You can now test the connection!"
