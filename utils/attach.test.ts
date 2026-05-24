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
