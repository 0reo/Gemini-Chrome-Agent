# Gemini Chrome Agent

A native messaging bridge that connects the [Google Gemini web interface](https://gemini.google.com) directly to your local Ubuntu environment. It enables Gemini to act as an autonomous agent capable of executing shell commands, reading files, and writing files — all from the chat interface.

---

## Features

- **Shell Execution** — Run bash commands on your local machine and stream results back to Gemini.
- **File I/O** — Read local files into the chat and write generated code directly to disk.
- **Auto-Submit Loop** — Execution results are automatically injected back into the Gemini prompt box.
- **Anti-Looping** — Deduplicates payloads to prevent recursive execution.
- **Agent Controls** — Pause/resume the agent via an on-screen control panel or `Alt+Shift+K`.

---

## Quick Start

### 1. Load the Extension

1. Open Brave and go to `brave://extensions/`.
2. Enable **Developer mode**.
3. Click **Load unpacked** and select this directory.
4. Copy the generated **Extension ID**.

### 2. Run the Setup Script

```bash
./setup.sh
```

Paste your Extension ID when prompted.

### 3. Start Using the Agent

1. Refresh your Gemini tab.
2. Ask Gemini to generate a JSON command block, e.g.:

```json
{
  "action": "run_shell",
  "command": "git status"
}
```

The extension will detect the payload, execute it, and return the result.

### Gemini gem instructions

Copy the system prompt from [`docs/GEM_PROMPT.md`](docs/GEM_PROMPT.md) into your Gemini gem's **Instructions** field so the model knows how to emit action JSON blocks.

---

## Project Structure

| File | Purpose |
|------|---------|
| `manifest.json` | Extension manifest (Manifest V3) |
| `background.js` | Service worker handling Native Messaging |
| `content.js` | Content script for Gemini page scraping & injection |
| `host.py` | Python native messaging host |
| `main.py` | Standalone CLI for testing actions without the browser |
| `setup.sh` | Automated setup & symlink script |
| `com.local.gemini_agent.json` | Native Messaging host manifest |

---

## CLI Testing

Test agent actions directly from the terminal:

```bash
# Shell command
python3 main.py run_shell "echo 'Hello World'"

# Write a file
python3 main.py write_file /tmp/test.txt "Hello from CLI"

# Read a file
python3 main.py read_file /tmp/test.txt

# Interactive mode
python3 main.py interactive
```

---

## Documentation

For full setup instructions, troubleshooting, and architecture details, see [`project-documentation.md`](project-documentation.md).

---

## Security Notes

- This tool executes commands with the same permissions as your user account.
- The Native Messaging manifest is locked to your specific Extension ID.
- Always review commands before allowing them to run unsupervised.

---

## Requirements

- Brave or Chrome browser
- Ubuntu (or another Linux distribution)
- Python 3

---

## License

Provided as-is for educational and personal use. Use at your own risk.
