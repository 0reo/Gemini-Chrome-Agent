# File Upload Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the agent attach local files (by path) to the Gemini chat as real uploads — via a Gemini-driven `attach_files` action and a user-driven popup — instead of pasting contents inline.

**Architecture:** `host.py` reads file(s) by path, base64-encodes, and streams them to the extension in size-bounded chunks (native-messaging has a ~1 MB host→extension message cap). The isolated content script reassembles the chunks and hands the bytes to a MAIN-world content script, which reconstructs `File` objects, overrides `HTMLInputElement.prototype.click` to feed them into Gemini's own uploader, and triggers *Upload & tools → Files*. Synthetic paste/drop were verified non-functional; this input-hook path was verified working live (1 and multiple files).

**Tech Stack:** TypeScript (WXT, content scripts incl. `world: 'MAIN'`), Python 3 (native host), vitest, Python unittest.

**Spec:** `docs/superpowers/specs/2026-05-24-file-upload-design.md`

---

## File Structure

| File | Responsibility | New/Modified |
|------|----------------|--------------|
| `utils/types.ts` | `attach_files` action, `filepaths`/`prompt` fields, `AttachChunk`, `HostResponse.attach`/`status:'attach'` | Modify |
| `utils/protocol.ts` | Validate `attach_files` payloads | Modify |
| `utils/config.ts` | `ATTACH_MAX_BYTES`, `ATTACH_CHUNK_SIZE`; `VALID_ACTIONS` += `attach_files` | Modify |
| `utils/attach.ts` | `AttachAssembler` — reassemble chunk stream into file descriptors | **Create** |
| `utils/injection.ts` | Extract `injectText(text)` (raw insert) used by `injectResponse` and the attach prompt | Modify |
| `host.py` | `read_file_b64`, `chunk_b64`, `handle_attach_files`; dispatch `attach_files` | Modify |
| `entrypoints/uploader.content.ts` | MAIN-world uploader: reconstruct `File[]`, hook input click, trigger Files menu | **Create** |
| `entrypoints/content.ts` | Route `attach` chunks → assembler → MAIN-world upload → prompt+send; handle popup `ATTACH_REQUEST` | Modify |
| `entrypoints/popup/main.ts` | Path textarea + "Attach to Gemini" button + status | Modify |
| `utils/attach.test.ts` | Unit tests for `AttachAssembler` | **Create** |
| `test/test_attach.py` | Unit tests for host attach helpers | **Create** |

---

## Task 1: Protocol layer — types, validation, config

**Files:**
- Modify: `utils/types.ts`
- Modify: `utils/protocol.ts`
- Modify: `utils/config.ts`
- Test: `utils/protocol.test.ts` (append), `utils/config.test.ts` (append)

- [ ] **Step 1: Write the failing tests**

Append to `utils/protocol.test.ts` (this file already imports `vitest` helpers and `isValidPayload`; do **not** re-add those imports — only add the `describe` block below; if either import is somehow missing, add it):
```ts
describe('isValidPayload: attach_files', () => {
  it('accepts a non-empty filepaths array', () => {
    expect(isValidPayload({ action: 'attach_files', filepaths: ['/a.py'], id: '1' })).toBe(true);
    expect(isValidPayload({ action: 'attach_files', filepaths: ['/a.py', '/b.png'], prompt: 'go', id: '2' })).toBe(true);
  });
  it('rejects missing/empty/invalid filepaths', () => {
    expect(isValidPayload({ action: 'attach_files', id: '3' })).toBe(false);
    expect(isValidPayload({ action: 'attach_files', filepaths: [], id: '4' })).toBe(false);
    expect(isValidPayload({ action: 'attach_files', filepaths: [1, 2], id: '5' })).toBe(false);
    expect(isValidPayload({ action: 'attach_files', filepaths: [''], id: '6' })).toBe(false);
  });
});
```

Append the two new keys to the `numericKeys` array in `utils/config.test.ts`:
```ts
      'SEND_READY_TIMEOUT_MS',
      'ATTACH_MAX_BYTES',
      'ATTACH_CHUNK_SIZE',
      'LOG_BUFFER_SIZE',
```
(Insert `ATTACH_MAX_BYTES` and `ATTACH_CHUNK_SIZE` immediately before `'LOG_BUFFER_SIZE'`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm run test -- protocol config`
Expected: FAIL — `attach_files` not yet valid; `ATTACH_MAX_BYTES`/`ATTACH_CHUNK_SIZE` undefined.

- [ ] **Step 3: Update `utils/types.ts`**

Replace the `AgentAction`, `AgentPayload`, and `HostResponse` definitions with:
```ts
export type AgentAction = 'run_shell' | 'write_file' | 'read_file' | 'list_files' | 'git_status' | 'git_diff' | 'run_python' | 'attach_files';

export interface AgentPayload {
  id: string;
  action: AgentAction;
  command?: string;
  filepath?: string;
  filepaths?: string[];
  content?: string;
  prompt?: string;
  meta?: Record<string, unknown>;
}

export interface AttachChunk {
  kind: 'chunk' | 'error' | 'complete';
  fileCount: number;
  fileIndex?: number;
  filename?: string;
  mimeType?: string;
  chunkIndex?: number;
  chunkCount?: number;
  data?: string;   // base64 substring (kind: 'chunk')
  error?: string;  // (kind: 'error')
}

export interface HostResponse {
  id: string;
  status: 'success' | 'error' | 'fatal_error' | 'attach';
  output?: string;
  message?: string;
  error?: string;
  code?: number;
  attach?: AttachChunk;
  meta?: Record<string, unknown>;
}
```
Leave `ExtensionMessage`, `AgentState`, `LogEntry` unchanged.

- [ ] **Step 4: Update `utils/protocol.ts`**

In `isValidPayload`, add `'attach_files'` to the `validActions` array, and add this check before `return true;`:
```ts
  if (p.action === 'attach_files') {
    if (!Array.isArray(p.filepaths) || p.filepaths.length === 0) return false;
    if (!p.filepaths.every((f) => typeof f === 'string' && f.length > 0)) return false;
  }
```

- [ ] **Step 5: Update `utils/config.ts`**

Add to the `CONFIG` object (after `SEND_READY_TIMEOUT_MS`):
```ts
  ATTACH_MAX_BYTES: 25 * 1024 * 1024,
  ATTACH_CHUNK_SIZE: 512 * 1024,
```
Add `'attach_files'` to the `VALID_ACTIONS` set.

- [ ] **Step 6: Run tests to verify they pass**

Run: `npm run test -- protocol config`
Expected: PASS (all).

- [ ] **Step 7: Commit**

```bash
git add utils/types.ts utils/protocol.ts utils/config.ts utils/protocol.test.ts utils/config.test.ts
git commit -m "feat(protocol): add attach_files action, attach chunk types, config"
```

---

## Task 2: Chunk reassembly util (`AttachAssembler`)

**Files:**
- Create: `utils/attach.ts`
- Test: `utils/attach.test.ts`

- [ ] **Step 1: Write the failing test**

Create `utils/attach.test.ts`:
```ts
import { describe, it, expect } from 'vitest';
import { AttachAssembler } from './attach';
import type { AttachChunk } from './types';

const chunk = (o: Partial<AttachChunk>): AttachChunk => ({ kind: 'chunk', fileCount: 1, ...o }) as AttachChunk;

describe('AttachAssembler', () => {
  it('reassembles a single multi-chunk file on complete', () => {
    const a = new AttachAssembler();
    expect(a.add(chunk({ fileIndex: 0, filename: 'a.txt', mimeType: 'text/plain', chunkIndex: 0, chunkCount: 2, data: 'aGVs' }))).toBeNull();
    expect(a.add(chunk({ fileIndex: 0, filename: 'a.txt', mimeType: 'text/plain', chunkIndex: 1, chunkCount: 2, data: 'bG8=' }))).toBeNull();
    const res = a.add({ kind: 'complete', fileCount: 1 });
    expect(res).not.toBeNull();
    expect(res!.files).toEqual([{ filename: 'a.txt', mimeType: 'text/plain', base64: 'aGVsbG8=' }]);
    expect(res!.errors).toEqual([]);
  });

  it('reassembles two files and preserves per-file errors', () => {
    const a = new AttachAssembler();
    a.add(chunk({ fileCount: 2, fileIndex: 0, filename: 'a.txt', mimeType: 'text/plain', chunkIndex: 0, chunkCount: 1, data: 'QQ==' }));
    a.add({ kind: 'error', fileCount: 2, fileIndex: 1, filename: 'big.bin', error: 'too large' });
    const res = a.add({ kind: 'complete', fileCount: 2 });
    expect(res!.files).toEqual([{ filename: 'a.txt', mimeType: 'text/plain', base64: 'QQ==' }]);
    expect(res!.errors).toEqual([{ filename: 'big.bin', error: 'too large' }]);
  });

  it('flags an incomplete file as an error on complete', () => {
    const a = new AttachAssembler();
    a.add(chunk({ fileIndex: 0, filename: 'a.txt', chunkIndex: 0, chunkCount: 2, data: 'aGVs' }));
    const res = a.add({ kind: 'complete', fileCount: 1 });
    expect(res!.files).toEqual([]);
    expect(res!.errors[0].filename).toBe('a.txt');
    expect(res!.errors[0].error).toMatch(/incomplete/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- attach`
Expected: FAIL — `Cannot find module './attach'`.

- [ ] **Step 3: Create `utils/attach.ts`**

```ts
import type { AttachChunk } from './types';

export interface ReassembledFile { filename: string; mimeType: string; base64: string; }
export interface AttachError { filename: string; error: string; }
export interface AttachResult { files: ReassembledFile[]; errors: AttachError[]; }

interface FileAcc { filename: string; mimeType: string; parts: string[]; received: number; chunkCount: number; }

export class AttachAssembler {
  private files = new Map<number, FileAcc>();
  private errors: AttachError[] = [];

  /** Returns the assembled result on the 'complete' message, otherwise null. */
  add(chunk: AttachChunk): AttachResult | null {
    if (chunk.kind === 'chunk') {
      const idx = chunk.fileIndex ?? 0;
      let acc = this.files.get(idx);
      if (!acc) {
        acc = {
          filename: chunk.filename || `file-${idx}`,
          mimeType: chunk.mimeType || 'application/octet-stream',
          parts: new Array(chunk.chunkCount ?? 1).fill(''),
          received: 0,
          chunkCount: chunk.chunkCount ?? 1,
        };
        this.files.set(idx, acc);
      }
      const ci = chunk.chunkIndex ?? 0;
      if (acc.parts[ci] === '') {
        acc.parts[ci] = chunk.data || '';
        acc.received++;
      }
      return null;
    }
    if (chunk.kind === 'error') {
      this.errors.push({ filename: chunk.filename || `file-${chunk.fileIndex}`, error: chunk.error || 'unknown error' });
      return null;
    }
    // kind === 'complete'
    const files: ReassembledFile[] = [];
    for (const acc of this.files.values()) {
      if (acc.received === acc.chunkCount) {
        files.push({ filename: acc.filename, mimeType: acc.mimeType, base64: acc.parts.join('') });
      } else {
        this.errors.push({ filename: acc.filename, error: `incomplete: ${acc.received}/${acc.chunkCount} chunks received` });
      }
    }
    return { files, errors: this.errors };
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- attach`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add utils/attach.ts utils/attach.test.ts
git commit -m "feat(attach): add AttachAssembler chunk reassembler"
```

---

## Task 3: Native host `attach_files` handler

**Files:**
- Modify: `host.py`
- Test: `test/test_attach.py`

- [ ] **Step 1: Write the failing test**

Create `test/test_attach.py`:
```python
import os
import base64
import tempfile
import unittest

from host import read_file_b64, chunk_b64


class TestReadFileB64(unittest.TestCase):
    def test_reads_and_base64_encodes(self):
        with tempfile.NamedTemporaryFile('wb', suffix='.txt', delete=False) as f:
            f.write(b'hello')
            path = f.name
        try:
            mime, b64 = read_file_b64(path, max_bytes=1024)
            self.assertEqual(base64.b64decode(b64), b'hello')
            self.assertTrue(mime)  # some mime guessed or octet-stream
        finally:
            os.unlink(path)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            read_file_b64('/no/such/file.xyz', max_bytes=1024)

    def test_too_large_raises_valueerror(self):
        with tempfile.NamedTemporaryFile('wb', suffix='.bin', delete=False) as f:
            f.write(b'x' * 100)
            path = f.name
        try:
            with self.assertRaises(ValueError):
                read_file_b64(path, max_bytes=10)
        finally:
            os.unlink(path)


class TestChunkB64(unittest.TestCase):
    def test_splits_and_rejoins_exactly(self):
        b64 = 'A' * 1000
        chunks = chunk_b64(b64, 256)
        self.assertEqual(len(chunks), 4)  # 256,256,256,232
        self.assertEqual(''.join(chunks), b64)

    def test_single_chunk_when_small(self):
        self.assertEqual(chunk_b64('abc', 256), ['abc'])

    def test_empty_string(self):
        self.assertEqual(chunk_b64('', 256), [])


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest test.test_attach -v`
Expected: FAIL — `ImportError: cannot import name 'read_file_b64'`.

- [ ] **Step 3: Add helpers + handler to `host.py`**

Add `import base64` and `import mimetypes` to the imports at the top. After the `truncate_output` function, add:
```python
ATTACH_MAX_BYTES = 25 * 1024 * 1024
ATTACH_CHUNK_SIZE = 512 * 1024  # base64 characters per chunk


def read_file_b64(path, max_bytes=ATTACH_MAX_BYTES):
    """Read a file and return (mime_type, base64_str). Raises FileNotFoundError
    or ValueError (too large)."""
    expanded = os.path.expanduser(path)
    if not os.path.isfile(expanded):
        raise FileNotFoundError(f'File not found: {path}')
    size = os.path.getsize(expanded)
    if size > max_bytes:
        raise ValueError(f'File too large to attach ({size} bytes > {max_bytes} limit): {path}')
    with open(expanded, 'rb') as f:
        raw = f.read()
    mime = mimetypes.guess_type(expanded)[0] or 'application/octet-stream'
    return mime, base64.b64encode(raw).decode('ascii')


def chunk_b64(b64, chunk_size=ATTACH_CHUNK_SIZE):
    """Split a base64 string into chunk_size-character pieces (rejoinable by concat)."""
    return [b64[i:i + chunk_size] for i in range(0, len(b64), chunk_size)]


def handle_attach_files(msg):
    req_id = msg.get('id', 'unknown')
    filepaths = msg.get('filepaths') or []
    start = time.perf_counter()
    file_count = len(filepaths)
    logging.info(f"[{req_id}] Attaching {file_count} file(s)")

    for idx, path in enumerate(filepaths):
        try:
            mime, b64 = read_file_b64(path)
            filename = os.path.basename(os.path.expanduser(path)) or f'file-{idx}'
            chunks = chunk_b64(b64)
            chunk_count = max(1, len(chunks))
            if not chunks:
                chunks = ['']  # zero-byte file -> one empty chunk
            for ci, part in enumerate(chunks):
                send_message({
                    'id': req_id,
                    'status': 'attach',
                    'attach': {
                        'kind': 'chunk',
                        'fileCount': file_count,
                        'fileIndex': idx,
                        'filename': filename,
                        'mimeType': mime,
                        'chunkIndex': ci,
                        'chunkCount': chunk_count,
                        'data': part,
                    },
                    'meta': {},
                })
        except Exception as e:
            logging.error(f"[{req_id}] attach error for {path}: {e}")
            send_message({
                'id': req_id,
                'status': 'attach',
                'attach': {
                    'kind': 'error',
                    'fileCount': file_count,
                    'fileIndex': idx,
                    'filename': os.path.basename(str(path)) or str(path),
                    'error': str(e),
                },
                'meta': {},
            })

    duration_ms = round((time.perf_counter() - start) * 1000)
    send_message({
        'id': req_id,
        'status': 'attach',
        'attach': {'kind': 'complete', 'fileCount': file_count},
        'meta': {'duration_ms': duration_ms},
    })
```

- [ ] **Step 4: Wire dispatch in `host.py`**

In the `__main__` dispatch chain, add before the `else:` branch:
```python
            elif action == 'attach_files':
                handle_attach_files(msg)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m unittest test.test_attach -v`
Expected: PASS (all 6).

- [ ] **Step 6: Run the full Python suite for regressions**

Run: `python3 -m unittest discover -s test -v`
Expected: PASS (existing protocol tests unaffected).

- [ ] **Step 7: Commit**

```bash
git add host.py test/test_attach.py
git commit -m "feat(host): add attach_files handler with chunked base64 transfer + size guard"
```

---

## Task 4: Extract `injectText` in `injection.ts`

**Files:**
- Modify: `utils/injection.ts`

(No new unit test — `injection.ts` is DOM-coupled and covered by the live E2E in Task 8. This is a pure refactor that keeps `injectResponse` behavior identical and exposes raw-text injection for attach prompts.)

- [ ] **Step 1: Refactor `injectResponse` to delegate to `injectText`**

Replace the `injectResponse` function with:
```ts
/** Inject raw text into Gemini's composer (Quill). Returns true on success. */
export function injectText(fullText: string): boolean {
  const strategies = [
    () => injectIntoContentEditable(document.querySelector('rich-textarea [contenteditable="true"]'), fullText),
    () => injectIntoContentEditable(document.querySelector('[role="textbox"][contenteditable="true"]'), fullText),
    () => injectIntoContentEditable(document.querySelector('.ql-editor'), fullText),
    () => injectIntoTextarea(document.querySelector('textarea'), fullText),
  ];

  for (const strategy of strategies) {
    try {
      const result = strategy();
      if (result === 'injected') {
        info('Text injected successfully');
        return true;
      }
      if (result === 'skipped_user_typing') {
        warn('Injection skipped: user is actively typing in the input');
        return false;
      }
    } catch (e) {
      warn('Injection strategy failed', { error: (e as Error).message });
    }
  }
  error('Could not find any injectable input element');
  return false;
}

export function injectResponse(data: { output?: string; error?: string; message?: string }): boolean {
  const outputText = data?.output || data?.error || data?.message || 'Command completed.';
  return injectText(`System Result:\n${outputText}`);
}
```

- [ ] **Step 2: Verify build + existing tests + typecheck**

Run: `npm run compile && npm run test`
Expected: typecheck exit 0; all tests pass (no behavior change).

- [ ] **Step 3: Commit**

```bash
git add utils/injection.ts
git commit -m "refactor(injection): extract injectText for raw composer insertion"
```

---

## Task 5: MAIN-world uploader content script

**Files:**
- Create: `entrypoints/uploader.content.ts`

(Verified via Task 8 live E2E — this is the exact mechanism confirmed during design recon.)

- [ ] **Step 1: Create `entrypoints/uploader.content.ts`**

```ts
// Runs in the page's MAIN world so it can override HTMLInputElement.prototype.click
// (the isolated content script has a separate prototype). Bridges to the isolated
// content script via window.postMessage. Browser-injected, so not blocked by CSP.

interface FileDesc { name: string; type: string; base64: string; }
interface UploadResult { ok: boolean; count?: number; error?: string; }

export default defineContentScript({
  matches: ['*://gemini.google.com/*'],
  world: 'MAIN',
  main() {
    window.addEventListener('message', async (ev: MessageEvent) => {
      if (ev.source !== window) return;
      const d = ev.data;
      if (!d || d.__gla !== 'attach-request' || !Array.isArray(d.files)) return;
      const result = await performUpload(d.files as FileDesc[]);
      window.postMessage({ __gla: 'attach-result', nonce: d.nonce, ...result }, '*');
    });

    const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
    const findButton = (pred: (b: HTMLButtonElement) => boolean): HTMLButtonElement | null =>
      (Array.from(document.querySelectorAll('button')) as HTMLButtonElement[]).find(pred) || null;

    async function performUpload(descs: FileDesc[]): Promise<UploadResult> {
      let fileObjs: File[];
      try {
        fileObjs = descs.map((dsc) => {
          const bin = atob(dsc.base64);
          const bytes = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
          return new File([bytes], dsc.name, { type: dsc.type || 'application/octet-stream' });
        });
      } catch (e) {
        return { ok: false, error: 'file reconstruction failed: ' + ((e as Error)?.message || e) };
      }

      const origClick = HTMLInputElement.prototype.click;
      const origFSA = (window as any).showOpenFilePicker;
      let intercepted = false;

      HTMLInputElement.prototype.click = function (this: HTMLInputElement) {
        if (this.type === 'file') {
          intercepted = true;
          const dt = new DataTransfer();
          fileObjs.forEach((f) => dt.items.add(f));
          this.files = dt.files;
          this.dispatchEvent(new Event('input', { bubbles: true }));
          this.dispatchEvent(new Event('change', { bubbles: true }));
          return;
        }
        // eslint-disable-next-line prefer-rest-params
        return origClick.apply(this, arguments as any);
      };
      if (origFSA) {
        (window as any).showOpenFilePicker = async () => { const e = new Error('aborted'); (e as any).name = 'AbortError'; throw e; };
      }

      try {
        const toolsBtn = findButton((b) => (b.getAttribute('aria-label') || '') === 'Upload & tools');
        if (!toolsBtn) return { ok: false, error: 'Upload & tools button not found' };
        toolsBtn.click();

        let filesBtn: HTMLButtonElement | null = null;
        for (let i = 0; i < 20 && !filesBtn; i++) {
          await wait(100);
          filesBtn = findButton((b) => (b.innerText || '').trim().split('\n')[0] === 'Files');
        }
        if (!filesBtn) return { ok: false, error: 'Files menu item not found (Gemini UI may have changed)' };
        filesBtn.click();

        for (let i = 0; i < 20 && !intercepted; i++) await wait(100);
        if (!intercepted) return { ok: false, error: 'file input click not intercepted (Gemini UI may have changed)' };

        await wait(800); // let Gemini register the attachment chip
        return { ok: true, count: fileObjs.length };
      } finally {
        HTMLInputElement.prototype.click = origClick;
        if (origFSA) (window as any).showOpenFilePicker = origFSA;
      }
    }
  },
});
```

- [ ] **Step 2: Verify it builds + registers as a second content script**

Run: `npm run build`
Expected: build succeeds; output lists a second content script (e.g. `content-scripts/uploader.js`). Confirm with: `grep -o '"world": *"MAIN"' .output/chrome-mv3/manifest.json` → prints a match.

- [ ] **Step 3: Commit**

```bash
git add entrypoints/uploader.content.ts
git commit -m "feat(uploader): add MAIN-world script that injects files into Gemini's uploader"
```

---

## Task 6: Wire attach handling in `content.ts`

**Files:**
- Modify: `entrypoints/content.ts`

(Verified via Task 8 live E2E.)

- [ ] **Step 1: Add imports + attach state**

At the top of `content.ts`, update the injection import and add the assembler import:
```ts
import { injectResponse, injectText, triggerSend } from '@/utils/injection';
import { AttachAssembler, type AttachResult } from '@/utils/attach';
```

Inside `main()`, near the other `let` declarations, add:
```ts
    const attachAssemblers = new Map<string, AttachAssembler>();
    const attachRequests = new Map<string, { source: 'gemini' | 'popup'; prompt?: string }>();
```

- [ ] **Step 2: Record attach context when dispatching a Gemini-driven attach**

In `scanForPayloads`, immediately after the existing `browser.runtime.sendMessage({ type: 'SEND_TO_HOST', payload } ...)` line, add:
```ts
          if (payload.action === 'attach_files') {
            attachRequests.set(payload.id, { source: 'gemini', prompt: payload.prompt });
          }
```

- [ ] **Step 3: Add the popup-driven `ATTACH_REQUEST` listener + attach completion logic**

Add this block inside `main()` (e.g., just before `info('Content script loaded');`):
```ts
    // Popup-driven attach: receive paths, dispatch an attach_files request to the host.
    browser.runtime.onMessage.addListener((message: any) => {
      if (message?.type === 'ATTACH_REQUEST' && Array.isArray(message.filepaths)) {
        const id = generateId();
        attachRequests.set(id, { source: 'popup' });
        browser.runtime.sendMessage({
          type: 'SEND_TO_HOST',
          payload: { id, action: 'attach_files', filepaths: message.filepaths },
        } as ExtensionMessage);
      }
    });

    function performAttachUpload(files: AttachResult['files']): Promise<{ ok: boolean; error?: string }> {
      return new Promise((resolve) => {
        const nonce = generateId();
        const timer = window.setTimeout(() => {
          window.removeEventListener('message', onResult);
          resolve({ ok: false, error: 'uploader timed out' });
        }, 15000);
        function onResult(ev: MessageEvent) {
          const d = ev.data;
          if (ev.source !== window || !d || d.__gla !== 'attach-result' || d.nonce !== nonce) return;
          window.clearTimeout(timer);
          window.removeEventListener('message', onResult);
          resolve({ ok: !!d.ok, error: d.error });
        }
        window.addEventListener('message', onResult);
        window.postMessage({
          __gla: 'attach-request',
          nonce,
          files: files.map((f) => ({ name: f.filename, type: f.mimeType, base64: f.base64 })),
        }, '*');
      });
    }

    async function handleAttachComplete(id: string, result: AttachResult): Promise<void> {
      const ctx = attachRequests.get(id) || { source: 'gemini' as const };
      attachRequests.delete(id);
      for (const err of result.errors) warn('Attach error', { filename: err.filename, error: err.error });
      if (result.files.length === 0) {
        warn('Attach produced no files', { errors: result.errors.length });
        return;
      }
      const upload = await performAttachUpload(result.files);
      if (!upload.ok) { error('File upload into Gemini failed', { error: upload.error }); return; }
      info('Files attached', { count: result.files.length, source: ctx.source });

      if (ctx.source === 'popup') return; // stage only

      // Gemini-driven: inject prompt (or a default summary) then honor auto-submit.
      const names = result.files.map((f) => f.filename).join(', ');
      const promptText = (ctx.prompt && ctx.prompt.trim()) || `Attached ${result.files.length} file(s): ${names}`;
      injectText(promptText);
      const { autoSubmit } = await browser.storage.local.get('autoSubmit').catch(() => ({ autoSubmit: true }));
      if (autoSubmit !== false) triggerSend();
    }
```

- [ ] **Step 4: Route `attach` responses in the HOST_RESPONSE handler**

In the existing `browser.runtime.onMessage` HOST_RESPONSE handler, at the very start of the `if (message.type === 'HOST_RESPONSE')` block (before the `isPaused()` check), add:
```ts
        if (message.data?.status === 'attach' && message.data.attach) {
          const id = message.data.id;
          let asm = attachAssemblers.get(id);
          if (!asm) { asm = new AttachAssembler(); attachAssemblers.set(id, asm); }
          const result = asm.add(message.data.attach);
          if (result) { attachAssemblers.delete(id); void handleAttachComplete(id, result); }
          return;
        }
```

- [ ] **Step 5: Verify build + typecheck + tests**

Run: `npm run compile && npm run test && npm run build`
Expected: typecheck exit 0; tests pass; build succeeds.

- [ ] **Step 6: Commit**

```bash
git add entrypoints/content.ts
git commit -m "feat(content): route attach chunks, drive MAIN-world upload, inject prompt + send"
```

---

## Task 7: Popup — path input + "Attach to Gemini"

**Files:**
- Modify: `entrypoints/popup/main.ts`

- [ ] **Step 1: Add the attach UI to the popup markup**

In `render(...)`, inside `.settings-section` (after the auto-submit row's closing `</label>`), add:
```html
        <div class="attach-row">
          <textarea id="attach-paths" class="attach-input" rows="2" placeholder="Local file path(s) to attach, one per line"></textarea>
          <button id="attach-btn" class="secondary-btn">Attach to Gemini</button>
          <div id="attach-status" class="status-msg"></div>
        </div>
```

- [ ] **Step 2: Wire the attach button**

In `render(...)`, after the auto-submit listener block, add:
```ts
  const attachBtn = document.getElementById('attach-btn');
  attachBtn?.addEventListener('click', async () => {
    const ta = document.getElementById('attach-paths') as HTMLTextAreaElement | null;
    const statusEl = document.getElementById('attach-status')!;
    const filepaths = (ta?.value || '').split('\n').map((s) => s.trim()).filter(Boolean);
    if (filepaths.length === 0) {
      statusEl.textContent = 'Enter at least one file path';
      statusEl.className = 'status-msg warn';
      return;
    }
    const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !/:\/\/gemini\.google\.com\//.test(tab.url || '')) {
      statusEl.textContent = 'Open a Gemini tab first';
      statusEl.className = 'status-msg warn';
      return;
    }
    await browser.tabs.sendMessage(tab.id, { type: 'ATTACH_REQUEST', filepaths });
    statusEl.textContent = `Attaching ${filepaths.length} file(s)… (staged in the composer)`;
    statusEl.className = 'status-msg success';
  });
```

- [ ] **Step 3: Add popup styles**

Append to `entrypoints/popup/style.css`:
```css
.attach-row { margin-top: 10px; display: flex; flex-direction: column; gap: 6px; }
.attach-input {
  width: 100%; box-sizing: border-box; resize: vertical; font-family: monospace;
  font-size: 12px; padding: 6px; border-radius: 6px; border: 1px solid #444; background: #1e1e1e; color: #eee;
}
```

- [ ] **Step 4: Verify build + typecheck**

Run: `npm run compile && npm run build`
Expected: typecheck exit 0; build succeeds.

- [ ] **Step 5: Commit**

```bash
git add entrypoints/popup/main.ts entrypoints/popup/style.css
git commit -m "feat(popup): add local-path attach UI"
```

---

## Task 8: Live end-to-end verification (chrome-devtools-mcp)

**Files:** none (verification only). Prereq: `./scripts/launch-debug-brave.sh` running, logged into Gemini, `brave-debug` MCP attached (see `gla-live-debug-workflow` memory).

- [ ] **Step 1: Reload the rebuilt extension**

Run `npm run build`, then in the debug Brave: navigate to `brave://extensions`, reload the extension (or via CDP, click the dev-reload button), and navigate back to `https://gemini.google.com/app`.

- [ ] **Step 2: Verify Gemini-driven attach (single file)**

Create a test file: `printf 'print("gla attach e2e")\n' > /tmp/gla-e2e.py`.
Resume the agent (Alt+Shift+K) and inject an action block whose text is:
```json
{"action":"attach_files","filepaths":["/tmp/gla-e2e.py"],"prompt":"What does this script do?"}
```
Expected: `gla-e2e.py` appears as an attachment chip; the prompt text is injected; with auto-submit on, the message + file are sent (new turn appears). Confirm via `take_snapshot` / `evaluate_script` checking the chip filename is present and the composer cleared.

- [ ] **Step 3: Verify Gemini-driven attach (multiple files)**

Create `/tmp/gla-e2e-2.txt`. Inject:
```json
{"action":"attach_files","filepaths":["/tmp/gla-e2e.py","/tmp/gla-e2e-2.txt"]}
```
Expected: both chips appear; with no `prompt`, the default summary `Attached 2 file(s): …` is the sent text (auto-submit on).

- [ ] **Step 4: Verify popup-driven attach (stage-only)**

Open the popup, enter `/tmp/gla-e2e.py` in the path box, click "Attach to Gemini". Expected: the chip appears in the composer and **nothing is sent** (stage-only); you can type a prompt and send manually.

- [ ] **Step 5: Verify size guard + missing file**

Inject `{"action":"attach_files","filepaths":["/no/such/file"]}` → expect no attachment and an `[Gemini Agent] Attach error` log (check via `getLogs()` in the page/SW console). Optionally test a >25 MB file → per-file "too large" error, no attachment.

- [ ] **Step 6: Clean up test artifacts**

`rm -f /tmp/gla-e2e.py /tmp/gla-e2e-2.txt`. Optionally delete the test Gemini threads.

- [ ] **Step 7: Commit (if any docs/notes updated)**

No code change expected; if verification revealed fixes, commit them with `fix(...)` messages referencing the cause.

---

## Notes for the implementer

- **DRY/YAGNI:** no browser file-picker in the popup (Gemini already has one); the value is path-based upload. No drag/paste fallbacks — both verified non-functional.
- **Security:** the isolated↔MAIN bridge validates `ev.source === window`, the `__gla` tag, and a per-request `nonce`. This is local-only (the user's own Gemini); a malicious page could in principle post a spoofed `attach-request`, but it would only attach files the host already chose to read for this session.
- **Worlds:** `injectText`/`triggerSend` run in the isolated world (they already worked there); only the `input.click` override needs MAIN world.
