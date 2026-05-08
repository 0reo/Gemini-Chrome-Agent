# Gemini Chrome Agent — Protocol Specification for LLMs

> **Target audience:** The Gemini LLM (and any other LLM generating actions for this agent).  
> **Purpose:** Defines exactly how to output actions and what the system will do with them.

---

## How to Output an Action

When you want the agent to perform a local operation, output a **JSON code block** (fenced with triple backticks and the `json` language tag). The extension scans your response for code blocks containing an `"action"` key.

**Format:**

````markdown
```json
{"action": "run_shell", "command": "ls -la", "id": "auto-generated"}
```
````

**Rules:**
1. The JSON **must** be inside a code block (```json ... ```).
2. The JSON **must** contain `"action"` with one of the 7 supported action names.
3. The `"id"` field is optional in your output — if omitted, the extension will generate one before sending to the host. You may include it for traceability.
4. Only **one action per code block**. If you need multiple actions, output multiple code blocks sequentially.
5. Do not wrap the JSON in explanatory text inside the same code block. Keep the block pure JSON.

---

## Action Reference

### 1. `run_shell`

Execute an arbitrary shell command on the user's local machine.

| Attribute | Value |
|-----------|-------|
| **Description** | Runs the command via `subprocess.run(command, shell=True, timeout=30)`. Returns stdout, stderr, and exit code. |
| **Required fields** | `command` (string) |
| **Optional fields** | `id` (string) |

**Example:**
```json
{"action": "run_shell", "command": "git log --oneline -5"}
```

**Safety notes:**
- The command runs with the same privileges as the browser process.
- There is **no sandbox** and **no allow-list**.
- Output is truncated at **1MB** to protect the messaging protocol.
- Timeout is **30 seconds**.

---

### 2. `write_file`

Create or overwrite a file with the given content.

| Attribute | Value |
|-----------|-------|
| **Description** | Writes `content` to `filepath`. Creates parent directories automatically. Overwrites existing files without warning. |
| **Required fields** | `filepath` (string), `content` (string) |
| **Optional fields** | `id` (string) |

**Example:**
```json
{"action": "write_file", "filepath": "/tmp/notes.txt", "content": "Hello from Gemini"}
```

**Safety notes:**
- `~` is expanded to the user's home directory.
- Existing files are **silently overwritten**.
- Be careful with system paths (e.g., `~/.bashrc`, `/etc/hosts`).

---

### 3. `read_file`

Read the entire contents of a file.

| Attribute | Value |
|-----------|-------|
| **Description** | Reads a file as UTF-8 text. Returns an error if the file does not exist. |
| **Required fields** | `filepath` (string) |
| **Optional fields** | `id` (string) |

**Example:**
```json
{"action": "read_file", "filepath": "/tmp/notes.txt"}
```

**Safety notes:**
- `~` is expanded to the user's home directory.
- Binary files will be decoded as UTF-8; invalid bytes may be replaced or cause errors.
- Output is truncated at **1MB**.

---

### 4. `list_files`

List the entries in a directory.

| Attribute | Value |
|-----------|-------|
| **Description** | Returns a newline-separated list of filenames in the directory. If the path is a file, reports that. If it does not exist, reports that. |
| **Required fields** | `filepath` (string) |
| **Optional fields** | `id` (string) |

**Example:**
```json
{"action": "list_files", "filepath": "/tmp"}
```

**Safety notes:**
- Does not recurse into subdirectories.
- Hidden files (dotfiles) are included.

---

### 5. `git_status`

Run `git status` in a directory.

| Attribute | Value |
|-----------|-------|
| **Description** | Executes `git status` in the specified directory. Returns the stdout. Non-zero exit codes return an error response. |
| **Required fields** | `filepath` (string — the directory containing the `.git` repo) |
| **Optional fields** | `id` (string) |

**Example:**
```json
{"action": "git_status", "filepath": "~/projects/my-repo"}
```

**Safety notes:**
- The directory must be a valid Git repository (or a subdirectory of one).
- Timeout is **30 seconds**.

---

### 6. `git_diff`

Run `git diff` in a directory.

| Attribute | Value |
|-----------|-------|
| **Description** | Executes `git diff` in the specified directory. Returns the stdout. Non-zero exit codes return an error response. |
| **Required fields** | `filepath` (string — the directory containing the `.git` repo) |
| **Optional fields** | `id` (string) |

**Example:**
```json
{"action": "git_diff", "filepath": "~/projects/my-repo"}
```

**Safety notes:**
- Large diffs are truncated at **1MB**.
- Timeout is **30 seconds**.

---

### 7. `run_python`

Execute a Python script either from an existing file or from inline code.

| Attribute | Value |
|-----------|-------|
| **Description** | Runs a Python script using the same interpreter as `host.py`. Either `filepath` or `content` must be provided. If `content` is provided, it is written to a temporary file and executed. |
| **Required fields** | One of: `filepath` (string) **or** `content` (string) |
| **Optional fields** | `id` (string) |

**Example (inline):**
```json
{"action": "run_python", "content": "import os\nprint(os.getcwd())"}
```

**Example (from file):**
```json
{"action": "run_python", "filepath": "/tmp/script.py"}
```

**Safety notes:**
- Inline content is written to a temporary file and deleted after execution.
- The script runs with the same privileges as the browser user.
- Timeout is **30 seconds**.
- Output is truncated at **1MB**.

---

## Response Format You Will See

After the agent executes your action, it automatically injects the result back into the chat input and sends it. You will see a message like this from the user (the agent):

```
System Result:
<command output here>
```

If the command failed, the result looks like:

```
System Result:
--- Standard Error ---
<error output>
```

Or, for a hard error:

```
System Result:
Command timed out after 30 seconds.
```

You should treat this as the ground-truth output of the action and continue the conversation accordingly.

---

## Rate Limits and Cooldowns

The agent enforces automatic safety limits to prevent runaway loops:

| Limit | Value | Behavior |
|-------|-------|----------|
| **Cooldown** | 15 seconds | After executing one action, the agent ignores all payloads for 15 seconds. |
| **Rate limit** | 5 per minute | If more than 5 actions execute within 60 seconds, the agent **auto-pauses** and stops processing until manually resumed. |
| **Settling period** | 5 seconds | After page load or resume, the agent ignores existing/historical payloads for 5 seconds. |
| **Deduplication TTL** | 60 seconds | Identical payloads (same action + fields) are ignored for 60 seconds. |

### What this means for you

- **Do not** output a rapid sequence of actions expecting immediate sequential execution. Wait for the `System Result` of each action before outputting the next one.
- If you hit the rate limit, the user must manually resume the agent (via the popup or `Alt+Shift+K`).
- The cooldown is per-action, not per-conversation. Even different actions trigger the 15-second cooldown.

---

## Quick Reference: Action → Required Fields

| Action | Required JSON Fields |
|--------|---------------------|
| `run_shell` | `"command": "..."` |
| `write_file` | `"filepath": "..."`, `"content": "..."` |
| `read_file` | `"filepath": "..."` |
| `list_files` | `"filepath": "..."` |
| `git_status` | `"filepath": "..."` |
| `git_diff` | `"filepath": "..."` |
| `run_python` | `"filepath": "..."` **or** `"content": "..."` |

**All actions accept an optional `"id"` field.** If you omit it, the extension generates one automatically.
