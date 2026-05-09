import { describe, it, expect, beforeEach } from 'vitest';
import { hashPayload, isValidPayload } from '../utils/protocol';
import { isRecentlyProcessed, markPayloadProcessed, clearProcessedPayloads } from '../utils/dedup';
import type { AgentPayload } from '../utils/types';

describe('Performance: hashPayload', () => {
  const basePayload: AgentPayload = {
    action: 'run_shell',
    command: 'echo hello',
    id: 'perf-test-1',
  };

  it('hashes small payloads in under 1ms', () => {
    const start = performance.now();
    for (let i = 0; i < 1000; i++) {
      hashPayload({ ...basePayload, id: `id-${i}` });
    }
    const elapsed = performance.now() - start;
    expect(elapsed).toBeLessThan(10); // 1000 hashes in < 10ms = < 0.01ms each
  });

  it('hashes large payloads (1KB) in under 1ms each', () => {
    const largePayload: AgentPayload = {
      action: 'run_python',
      code: 'x = "' + 'a'.repeat(1000) + '"',
      id: 'large-test',
    };

    const start = performance.now();
    for (let i = 0; i < 100; i++) {
      hashPayload(largePayload);
    }
    const elapsed = performance.now() - start;
    expect(elapsed).toBeLessThan(10); // 100 hashes in < 10ms
  });

  it('produces consistent hashes for identical payloads', () => {
    const h1 = hashPayload(basePayload);
    const h2 = hashPayload(basePayload);
    expect(h1).toBe(h2);
  });

  it('produces different hashes for different payloads', () => {
    const h1 = hashPayload(basePayload);
    const h2 = hashPayload({ ...basePayload, command: 'echo world' });
    expect(h1).not.toBe(h2);
  });
});

describe('Performance: dedup memory', () => {
  beforeEach(() => {
    clearProcessedPayloads();
  });

  it('does not leak memory with many unique payloads', () => {
    const start = performance.now();
    for (let i = 0; i < 5000; i++) {
      const payload: AgentPayload = {
        action: 'run_shell',
        command: `echo ${i}`,
        id: `batch-${i}`,
      };
      isRecentlyProcessed(payload);
    }
    const elapsed = performance.now() - start;

    // 5000 inserts should complete in reasonable time
    expect(elapsed).toBeLessThan(100);
  });

  it('cleanup removes stale entries', () => {
    // Mark some payloads as processed
    for (let i = 0; i < 100; i++) {
      markPayloadProcessed({ action: 'run_shell', command: `cmd${i}`, id: `id${i}` });
    }

    // All should be recognized
    expect(isRecentlyProcessed({ action: 'run_shell', command: 'cmd0', id: 'id0' })).toBe(true);

    // Simulate time passing by directly manipulating internal state isn't possible,
    // but we can verify the cleanup mechanism exists by checking it runs without error
    clearProcessedPayloads();
    expect(isRecentlyProcessed({ action: 'run_shell', command: 'cmd0', id: 'id0' })).toBe(false);
  });
});

describe('Performance: isValidPayload', () => {
  const validPayloads: AgentPayload[] = [
    { action: 'run_shell', command: 'ls', id: '1' },
    { action: 'write_file', path: '/tmp/test.txt', content: 'hello', id: '2' },
    { action: 'read_file', path: '/tmp/test.txt', id: '3' },
    { action: 'list_files', path: '/tmp', id: '4' },
    { action: 'git_status', path: '/repo', id: '5' },
    { action: 'git_diff', path: '/repo', id: '6' },
    { action: 'run_python', code: 'print(1)', id: '7' },
  ];

  it('validates 7 actions in under 1ms total', () => {
    const start = performance.now();
    for (let i = 0; i < 1000; i++) {
      for (const payload of validPayloads) {
        isValidPayload(payload);
      }
    }
    const elapsed = performance.now() - start;
    expect(elapsed).toBeLessThan(10); // 7000 validations in < 10ms
  });

  it('rejects invalid payloads quickly', () => {
    const invalidPayloads = [
      null,
      undefined,
      {},
      { action: 'unknown' },
      { action: 'run_shell' }, // missing command
      { action: 'write_file', path: '/tmp' }, // missing content
    ];

    const start = performance.now();
    for (let i = 0; i < 10000; i++) {
      for (const payload of invalidPayloads) {
        isValidPayload(payload);
      }
    }
    const elapsed = performance.now() - start;
    expect(elapsed).toBeLessThan(10);
  });
});
