import { describe, it, expect } from 'vitest';
import {
  generateId,
  isValidPayload,
  hashPayload,
  createRequestPayload,
  createSuccessResponse,
  createErrorResponse,
} from './protocol';
import type { AgentPayload } from './types';

describe('generateId', () => {
  it('returns a string in the format timestamp-random', () => {
    const id = generateId();
    expect(typeof id).toBe('string');
    expect(id).toMatch(/^[a-z0-9]+-[a-z0-9]+$/);
  });

  it('produces unique ids across 100 calls', () => {
    const ids = new Set<string>();
    for (let i = 0; i < 100; i++) {
      ids.add(generateId());
    }
    expect(ids.size).toBe(100);
  });
});

describe('isValidPayload', () => {
  it('accepts run_shell with command', () => {
    expect(isValidPayload({ action: 'run_shell', command: 'echo hi' })).toBe(true);
  });

  it('rejects run_shell without command', () => {
    expect(isValidPayload({ action: 'run_shell' })).toBe(false);
  });

  it('accepts write_file with filepath and content', () => {
    expect(isValidPayload({ action: 'write_file', filepath: '/tmp/a', content: 'b' })).toBe(true);
  });

  it('rejects write_file missing filepath', () => {
    expect(isValidPayload({ action: 'write_file', content: 'b' })).toBe(false);
  });

  it('rejects write_file missing content', () => {
    expect(isValidPayload({ action: 'write_file', filepath: '/tmp/a' })).toBe(false);
  });

  it('accepts read_file with filepath', () => {
    expect(isValidPayload({ action: 'read_file', filepath: '/tmp/a' })).toBe(true);
  });

  it('rejects read_file without filepath', () => {
    expect(isValidPayload({ action: 'read_file' })).toBe(false);
  });

  it('accepts list_files with filepath', () => {
    expect(isValidPayload({ action: 'list_files', filepath: '/tmp' })).toBe(true);
  });

  it('rejects list_files without filepath', () => {
    expect(isValidPayload({ action: 'list_files' })).toBe(false);
  });

  it('accepts git_status with filepath', () => {
    expect(isValidPayload({ action: 'git_status', filepath: '.' })).toBe(true);
  });

  it('rejects git_status without filepath', () => {
    expect(isValidPayload({ action: 'git_status' })).toBe(false);
  });

  it('accepts git_diff with filepath', () => {
    expect(isValidPayload({ action: 'git_diff', filepath: '.' })).toBe(true);
  });

  it('rejects git_diff without filepath', () => {
    expect(isValidPayload({ action: 'git_diff' })).toBe(false);
  });

  it('accepts run_python with filepath only', () => {
    expect(isValidPayload({ action: 'run_python', filepath: '/tmp/a.py' })).toBe(true);
  });

  it('accepts run_python with content only', () => {
    expect(isValidPayload({ action: 'run_python', content: 'print(1)' })).toBe(true);
  });

  it('accepts run_python with both filepath and content', () => {
    expect(isValidPayload({ action: 'run_python', filepath: '/tmp/a.py', content: 'print(1)' })).toBe(true);
  });

  it('rejects run_python with neither filepath nor content', () => {
    expect(isValidPayload({ action: 'run_python' })).toBe(false);
  });

  it('rejects missing action', () => {
    expect(isValidPayload({ command: 'echo hi' })).toBe(false);
  });

  it('rejects invalid action', () => {
    expect(isValidPayload({ action: 'invalid_action' })).toBe(false);
  });

  it('rejects non-object input', () => {
    expect(isValidPayload(null)).toBe(false);
    expect(isValidPayload('string')).toBe(false);
    expect(isValidPayload(123)).toBe(false);
  });
});

describe('hashPayload', () => {
  it('returns the same hash for identical payloads', () => {
    const p: AgentPayload = { id: '1', action: 'run_shell', command: 'echo hi' };
    expect(hashPayload(p)).toBe(hashPayload(p));
  });

  it('returns different hashes for different payloads', () => {
    const p1: AgentPayload = { id: '1', action: 'run_shell', command: 'echo hi' };
    const p2: AgentPayload = { id: '2', action: 'run_shell', command: 'echo hi' };
    expect(hashPayload(p1)).not.toBe(hashPayload(p2));
  });
});

describe('createRequestPayload', () => {
  it('generates an id and preserves fields', () => {
    const payload = createRequestPayload('run_shell', { command: 'echo hi' });
    expect(payload.id).toBeDefined();
    expect(payload.action).toBe('run_shell');
    expect(payload.command).toBe('echo hi');
  });

  it('generates unique ids for multiple calls', () => {
    const p1 = createRequestPayload('run_shell', { command: 'echo hi' });
    const p2 = createRequestPayload('run_shell', { command: 'echo hi' });
    expect(p1.id).not.toBe(p2.id);
  });
});

describe('createSuccessResponse', () => {
  it('returns a success response with the correct shape', () => {
    const resp = createSuccessResponse('req-1', 'output text', { extra: true });
    expect(resp).toEqual({
      id: 'req-1',
      status: 'success',
      output: 'output text',
      meta: { extra: true },
    });
  });
});

describe('createErrorResponse', () => {
  it('returns an error response with the correct shape', () => {
    const resp = createErrorResponse('req-1', 'something went wrong', { extra: true });
    expect(resp).toEqual({
      id: 'req-1',
      status: 'error',
      error: 'something went wrong',
      meta: { extra: true },
    });
  });
});

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
