export const CONFIG = {
  COOLDOWN_MS: 15000,
  MAX_PER_MINUTE: 5,
  SETTLING_PERIOD_MS: 5000,
  PAYLOAD_TTL_MS: 60000,
  CLEANUP_INTERVAL_MS: 5000,
  SCAN_DEBOUNCE_MS: 250,
  SEND_POLL_INTERVAL_MS: 100,
  // triggerSend() only counts SEND_READY_TIMEOUT_MS against the give-up clock
  // AFTER Gemini stops generating (the Send button replaces the Stop button).
  // The System Result is often injected mid-generation, so the wait is keyed off
  // generation state, with SEND_ABSOLUTE_CAP_MS as a hard backstop (issue #18).
  SEND_READY_TIMEOUT_MS: 2000,
  SEND_ABSOLUTE_CAP_MS: 30000,
  ATTACH_MAX_BYTES: 25 * 1024 * 1024,
  ATTACH_CHUNK_SIZE: 512 * 1024,
  LOG_SERVER_URL: 'http://localhost:9999',
  LOG_BUFFER_SIZE: 1000,
  NATIVE_HOST_NAME: 'com.local.gemini_agent',
} as const;

export const VALID_ACTIONS: Set<string> = new Set([
  'run_shell',
  'write_file',
  'read_file',
  'list_files',
  'git_status',
  'git_diff',
  'run_python',
  'attach_files',
]);
