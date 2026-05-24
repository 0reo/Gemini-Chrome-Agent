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
