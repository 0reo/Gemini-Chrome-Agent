import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { isRecentlyProcessed, markPayloadProcessed, clearProcessedPayloads } from './dedup';
import type { AgentPayload } from './types';

vi.mock('./logger', () => ({
  debug: vi.fn(),
}));

describe('isRecentlyProcessed', () => {
  beforeEach(() => {
    clearProcessedPayloads();
  });

  it('returns false on first call and true on second call with same payload', () => {
    const payload: AgentPayload = { id: '1', action: 'run_shell', command: 'echo hi' };
    expect(isRecentlyProcessed(payload)).toBe(false);
    expect(isRecentlyProcessed(payload)).toBe(true);
  });
});

describe('markPayloadProcessed', () => {
  beforeEach(() => {
    clearProcessedPayloads();
  });

  it('marks a payload as processed', () => {
    const payload: AgentPayload = { id: '1', action: 'run_shell', command: 'echo hi' };
    markPayloadProcessed(payload);
    expect(isRecentlyProcessed(payload)).toBe(true);
  });
});

describe('clearProcessedPayloads', () => {
  it('clears all processed payloads', () => {
    const payload: AgentPayload = { id: '1', action: 'run_shell', command: 'echo hi' };
    isRecentlyProcessed(payload);
    expect(isRecentlyProcessed(payload)).toBe(true);
    clearProcessedPayloads();
    expect(isRecentlyProcessed(payload)).toBe(false);
  });
});

describe('TTL expiration', () => {
  beforeEach(() => {
    clearProcessedPayloads();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('returns false for a payload processed 61 seconds ago', () => {
    const payload: AgentPayload = { id: '1', action: 'run_shell', command: 'echo hi' };
    isRecentlyProcessed(payload);
    vi.advanceTimersByTime(61000);
    expect(isRecentlyProcessed(payload)).toBe(false);
  });
});

describe('Cleanup', () => {
  beforeEach(() => {
    clearProcessedPayloads();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('prunes old entries during cleanup intervals', () => {
    const payload1: AgentPayload = { id: '1', action: 'run_shell', command: 'echo hi' };
    const payload2: AgentPayload = { id: '2', action: 'run_shell', command: 'echo hello' };

    isRecentlyProcessed(payload1);
    vi.advanceTimersByTime(1000);
    isRecentlyProcessed(payload2);

    // Both should be processed
    expect(isRecentlyProcessed(payload1)).toBe(true);
    expect(isRecentlyProcessed(payload2)).toBe(true);

    // Advance past cleanup interval and TTL
    vi.advanceTimersByTime(70000);

    // After cleanup, old entries should be gone
    expect(isRecentlyProcessed(payload1)).toBe(false);
    expect(isRecentlyProcessed(payload2)).toBe(false);
  });
});
