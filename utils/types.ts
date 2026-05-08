export type AgentAction = 'run_shell' | 'write_file' | 'read_file' | 'list_files';

export interface AgentPayload {
  id: string;
  action: AgentAction;
  command?: string;
  filepath?: string;
  content?: string;
  meta?: Record<string, unknown>;
}

export interface HostResponse {
  id: string;
  status: 'success' | 'error' | 'fatal_error';
  output?: string;
  message?: string;
  error?: string;
  code?: number;
  meta?: Record<string, unknown>;
}

export interface ExtensionMessage {
  type: 'SEND_TO_HOST' | 'HOST_RESPONSE';
  payload?: AgentPayload;
  data?: HostResponse;
}

export type AgentState = 'settling' | 'armed' | 'cooldown' | 'paused' | 'error';

export interface LogEntry {
  level: 'debug' | 'info' | 'warn' | 'error';
  message: string;
  data?: unknown;
  ts: number;
}
