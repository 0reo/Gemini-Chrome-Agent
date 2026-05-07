#!/bin/bash

# Get the absolute path of the directory where this script is located
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
HOST_SCRIPT="$PROJECT_DIR/host.py"
MANIFEST_FILE="$PROJECT_DIR/com.local.gemini_agent.json"
BRAVE_NM_DIR="$HOME/.config/BraveSoftware/Brave-Browser/NativeMessagingHosts"
SYMLINK_PATH="$BRAVE_NM_DIR/com.local.gemini_agent.json"

echo "=== Gemini Agent Native Messaging Setup for Brave ==="

# 1. Make the Python host script executable
if [ -f "$HOST_SCRIPT" ]; then
    chmod +x "$HOST_SCRIPT"
    echo "✔ Made host.py executable."
else
    echo "✖ Error: host.py not found in $PROJECT_DIR."
    echo "Please make sure host.py is in the same directory as this setup script."
    exit 1
fi

# 2. Ask for the Extension ID
echo ""
echo "Please go to brave://extensions/"
echo "Load your unpacked extension from $PROJECT_DIR"
echo "Copy the generated Extension ID."
read -p "Paste your Extension ID here: " EXTENSION_ID

if [ -z "$EXTENSION_ID" ]; then
    echo "✖ Error: Extension ID cannot be empty. Setup aborted."
    exit 1
fi

# 3. Generate the Native Messaging Manifest with absolute paths and the provided ID
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

# 4. Create the Brave Native Messaging directory if it doesn't exist
mkdir -p "$BRAVE_NM_DIR"
echo "✔ Ensured Brave Native Messaging directory exists."

# 5. Create the symlink
ln -sf "$MANIFEST_FILE" "$SYMLINK_PATH"
echo "✔ Created symlink at $SYMLINK_PATH"

echo ""
echo "=== Setup Complete! ==="
echo "If your extension is already loaded in Brave, click the 'Refresh' icon on the extension page to apply changes."
echo "You can now test the connection!"