import { describe, it, expect } from 'vitest';
import { CONFIG, VALID_ACTIONS } from './config';

describe('CONFIG', () => {
  it('has all positive numeric constants', () => {
    const numericKeys = [
      'COOLDOWN_MS',
      'MAX_PER_MINUTE',
      'SETTLING_PERIOD_MS',
      'PAYLOAD_TTL_MS',
      'CLEANUP_INTERVAL_MS',
      'SCAN_DEBOUNCE_MS',
      'SEND_POLL_INTERVAL_MS',
      'SEND_READY_TIMEOUT_MS',
      'LOG_BUFFER_SIZE',
    ] as const;

    for (const key of numericKeys) {
      const value = CONFIG[key];
      expect(typeof value).toBe('number');
      expect(value).toBeGreaterThan(0);
    }
  });
});

describe('VALID_ACTIONS', () => {
  it('contains all 7 actions', () => {
    const expected = [
      'run_shell',
      'write_file',
      'read_file',
      'list_files',
      'git_status',
      'git_diff',
      'run_python',
    ];
    for (const action of expected) {
      expect(VALID_ACTIONS.has(action)).toBe(true);
    }
    expect(VALID_ACTIONS.size).toBe(7);
  });
});
