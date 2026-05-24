import type { AgentPayload, HostResponse } from './types';

export function generateId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export function isValidPayload(payload: unknown): payload is AgentPayload {
  if (!payload || typeof payload !== 'object') return false;
  const p = payload as Record<string, unknown>;
  if (!p.action || typeof p.action !== 'string') return false;
  const validActions = ['run_shell', 'write_file', 'read_file', 'list_files', 'git_status', 'git_diff', 'run_python', 'attach_files'];
  if (!validActions.includes(p.action)) return false;

  if (p.action === 'run_shell' && typeof p.command !== 'string') return false;
  if (p.action === 'write_file' && (typeof p.filepath !== 'string' || typeof p.content !== 'string')) return false;
  if (p.action === 'read_file' && typeof p.filepath !== 'string') return false;
  if (p.action === 'list_files' && typeof p.filepath !== 'string') return false;
  if (p.action === 'git_status' && typeof p.filepath !== 'string') return false;
  if (p.action === 'git_diff' && typeof p.filepath !== 'string') return false;
  if (p.action === 'run_python' && (typeof p.filepath !== 'string' && typeof p.content !== 'string')) return false;

  if (p.action === 'attach_files') {
    if (!Array.isArray(p.filepaths) || p.filepaths.length === 0) return false;
    if (!(p.filepaths as unknown[]).every((f) => typeof f === 'string' && f.length > 0)) return false;
  }

  return true;
}

export function hashPayload(payload: AgentPayload): string {
  try {
    const canonical = JSON.stringify(payload, Object.keys(payload).sort());
    let hash = 0;
    for (let i = 0; i < canonical.length; i++) {
      const char = canonical.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash;
    }
    return hash.toString(16);
  } catch {
    return Math.random().toString(36).slice(2);
  }
}

export function createRequestPayload(action: AgentPayload['action'], fields: Omit<AgentPayload, 'id' | 'action'>): AgentPayload {
  return {
    id: generateId(),
    action,
    ...fields,
  };
}

export function createSuccessResponse(id: string, output: string, meta?: Record<string, unknown>): HostResponse {
  return { id, status: 'success', output, meta };
}

export function createErrorResponse(id: string, error: string, meta?: Record<string, unknown>): HostResponse {
  return { id, status: 'error', error, meta };
}
