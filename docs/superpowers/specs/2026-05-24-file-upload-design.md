# File Upload Support — Design

**Date:** 2026-05-24
**Status:** Approved decisions; pending spec review
**Branch:** wxt-migration

## Overview

Let the agent attach **local files** to the Gemini chat as real uploads, instead of
pasting their contents inline as chat text. Primary use case: hand Gemini a large
script (or several) to work on. Files are identified by **local path** and read by
the native host — this is the extension's value-add over Gemini's built-in uploader,
which can only take browser-picked files.

Two ways to trigger an attach:
1. **Gemini-driven** — Gemini emits a JSON action block (fits the existing agentic loop).
2. **User-driven** — the popup, where the user enters local path(s) and clicks "Attach".

## Goals

- Attach **1 or many** files in a single operation.
- Support **any file type**, text or binary (scripts, images, PDFs, archives).
- Reuse the existing **auto-submit** behavior for the Gemini-driven path.
- Handle **large files** robustly (chunked transfer) with a hard size ceiling.

## Non-goals

- A browser file-picker in the popup (redundant with Gemini's own uploader; the
  value here is path-based upload via the native host).
- Drag-and-drop or paste injection (verified non-functional — see below).
- Uploading to anywhere other than the active Gemini conversation.

## Verified mechanism (live recon, 2026-05-24)

Tested against live Gemini (`gemini.google.com`) via chrome-devtools-mcp:

- Synthetic **paste** (`ClipboardEvent` + `DataTransfer`) → **ignored** by Gemini.
- Synthetic **drag-and-drop** (`DragEvent` on `.xap-uploader-dropzone`, even with a
  shared `DataTransfer` whose `types` includes `'Files'`) → **ignored** by Gemini.
- **Working path:** Gemini's upload is triggered by a real `<input type="file">.click()`.
  Overriding `HTMLInputElement.prototype.click` so that, for file inputs, it sets
  `input.files` from a `DataTransfer` we build and dispatches `input`+`change`, then
  programmatically opening **Upload & tools → Files**, makes Gemini ingest our files
  through its own handler.
  - Confirmed: `input.files` is settable; the input is `multiple`; `accept` is unset
    (any type); verified with both 1 file and 2 files appearing as attachment chips.

The override must run in the page's **MAIN world** (the content script's isolated
world has a separate `HTMLInputElement.prototype`). A WXT `world: 'MAIN'` content
script is browser-injected, so it is not blocked by Gemini's CSP (unlike an injected
`<script>` tag — the reason the `localhost:9999` logger is CSP-blocked). The hook is
installed only for the managed upload and restored immediately after.

## Architecture & data flow

```
PATH(s)
  │  (Gemini action block  OR  popup path input)
  ▼
content.ts (isolated)  ──{type:SEND_TO_HOST, attach_files payload}──▶ background.ts
                                                                          │
                                                          connectNative   ▼
                                                                       host.py
                                          reads each path, base64, splits into chunks
                                                                          │
        ◀── chunk messages (per file: index/total) + completion ─────────┘
content.ts (isolated): reassemble base64 per file → raw bytes (ArrayBuffer)
        │  window.postMessage({files: [{name, type, bytes}], nonce})
        ▼
uploader.main.ts (MAIN world):
   reconstruct File[] from the bytes  →  hook HTMLInputElement.prototype.click
   →  click "Upload & tools" → click "Files"  (Gemini's input.click is intercepted,
      our files injected)  →  restore hook  →  postMessage result back
        │
        ▼
content.ts (isolated): if a prompt was supplied, inject it via the existing
   execCommand path; then triggerSend() iff auto-submit is enabled.
```

## Components (new / changed)

### `host.py` — new `attach_files` handler
- Input: `filepaths: string[]` (expand `~`).
- For each path: stat the file; if missing/unreadable → per-file error; if size >
  **ceiling (25 MB)** → per-file error ("file too large to attach"). Otherwise read
  bytes, base64-encode, split into chunks of **512 KB** (base64 chars) — comfortably
  under Chrome's host→extension single-message cap (documented 1 MB).
- Emit, per file, a sequence of chunk messages then a per-file completion marker; emit
  a final batch-completion message. Partial success is allowed: valid files attach even
  if a sibling errored; errors are reported per file.
- This path must **not** apply the existing 1 MB stdout truncation.

### `entrypoints/uploader.main.ts` — NEW, `world: 'MAIN'`
- Listens for a `window.postMessage` (validated by a per-request `nonce`) carrying
  reconstructed file descriptors `{name, type, bytes}`.
- Builds `File[]`, installs the `HTMLInputElement.prototype.click` override (guarding
  against `window.showOpenFilePicker` too), clicks **Upload & tools** then **Files**,
  waits for the attachment to register, restores the override, and posts a
  success/failure result back. Times out with an error if "Files" / the input is not
  found (e.g., Gemini DOM changed).

### `entrypoints/content.ts` — changed
- On an `attach_files` response: buffer chunks keyed by `(requestId, fileIndex)`;
  on batch completion, decode and hand `{files, nonce}` to the MAIN-world script.
- After MAIN reports success: if `prompt` was supplied, inject it via the existing
  `injectResponse`/execCommand path; then `triggerSend()` iff the `autoSubmit` toggle
  is on (Gemini-driven). Popup-driven attaches are **stage-only** (never auto-submit).
- Surface per-file errors to the logger (and, for the loop, as the text sent back).

### `entrypoints/popup` — changed
- A textarea (one local path per line) + an **"Attach to Gemini"** button.
- Sends the paths to the active Gemini tab's content script; shows per-file status
  (attached / error). Stage-only: the user then types their prompt and sends.

### `utils/types.ts`, `utils/protocol.ts`, `utils/config.ts` — changed
- `AgentAction` gains `'attach_files'`; `AgentPayload` gains `filepaths?: string[]`
  and `prompt?: string`.
- `isValidPayload`: `attach_files` requires `filepaths` to be a non-empty string array.
- `VALID_ACTIONS` gains `'attach_files'`.
- `CONFIG` gains `ATTACH_MAX_BYTES` (25 MB) and `ATTACH_CHUNK_SIZE` (512 KB).

## Protocol

**Gemini-driven request** (in a chat code block):
```json
{ "action": "attach_files", "filepaths": ["~/proj/big_script.py", "/tmp/diagram.png"], "prompt": "Refactor big_script.py; the diagram shows the target architecture." }
```
`prompt` is optional. If omitted and auto-submit is on, a default summary
("Attached N file(s): …") is sent as the message text.

**Chunk transfer** (host → extension, all sharing the request `id`): each message
carries `meta` with `{ filename, mimeType, fileIndex, fileCount, chunkIndex,
chunkCount }` and the base64 chunk; a terminal message marks batch completion. Exact
field names finalized in the implementation plan.

## Auto-submit behavior

Reuse the existing toggle. Gemini-driven attach: attach → inject optional prompt →
auto-send iff toggle on. Popup attach: stage only, never auto-send.

## Error handling

- Missing/unreadable file, or size > ceiling → per-file error; other files still attach.
- "Files" button / file input not found within a timeout → batch error, logged and
  surfaced (no silent failure).
- Chunk reassembly incomplete within a timeout → batch error.
- All errors reported per file where possible; the Gemini-driven path reports failures
  back into the chat so the model knows what did/didn't attach.

## Testing

- **Python unit** (`test/`): `attach_files` read + base64 + chunking + size guard +
  missing-file handling.
- **TS unit** (`vitest`): `isValidPayload` for `attach_files` (valid arrays; rejects
  empty/missing `filepaths`).
- **Live E2E** (chrome-devtools-mcp, the un-unit-testable layer): attach 1 file and
  multiple files to real Gemini, confirm chips appear, confirm prompt injection +
  auto-submit send the files. Mirrors the recon already done.

## Risks

- Gemini DOM/flow changes (the "Files" menu path, the dropzone, the input). Mitigated
  by a timeout + surfaced error, and by the live E2E test catching regressions.
- Very large batches/files: bounded by the 25 MB per-file ceiling and chunking.
