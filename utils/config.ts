export const CONFIG = {
  COOLDOWN_MS: 15000,
  MAX_PER_MINUTE: 5,
  SETTLING_PERIOD_MS: 5000,
  PAYLOAD_TTL_MS: 60000,
  CLEANUP_INTERVAL_MS: 5000,
  SCAN_DEBOUNCE_MS: 250,
  SEND_POLL_INTERVAL_MS: 100,
  SEND_READY_TIMEOUT_MS: 2000,
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
]);
