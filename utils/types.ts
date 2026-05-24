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
