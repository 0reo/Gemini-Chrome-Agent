import { CONFIG } from './config';
import type { LogEntry } from './types';

let logBuffer: LogEntry[] = [];

async function flushToServer(entry: LogEntry): Promise<void> {
  try {
    const payload = JSON.stringify(entry);
    await fetch(`${CONFIG.LOG_SERVER_URL}/log?m=${encodeURIComponent(payload)}`).catch(() => {});
  } catch {
    // Silent fail — don't let logging break the extension
  }
}

async function persistToStorage(entry: LogEntry): Promise<void> {
  try {
    const result = await browser.storage.local.get('agentLogs');
    const logs: LogEntry[] = (result.agentLogs as LogEntry[]) || [];
    logs.push(entry);
    while (logs.length > CONFIG.LOG_BUFFER_SIZE) logs.shift();
    await browser.storage.local.set({ agentLogs: logs });
  } catch {
    // Storage might be unavailable
  }
}

export function log(level: LogEntry['level'], message: string, data?: unknown): void {
  const entry: LogEntry = { level, message, data, ts: Date.now() };

  // Console first
  const consoleMethod = level === 'error' ? console.error : level === 'warn' ? console.warn : level === 'debug' ? console.debug : console.log;
  consoleMethod(`[Gemini Agent] ${message}`, data ?? '');

  // Buffer
  logBuffer.push(entry);

  // Async sinks
  flushToServer(entry);
  persistToStorage(entry);
}

export function debug(message: string, data?: unknown): void { log('debug', message, data); }
export function info(message: string, data?: unknown): void { log('info', message, data); }
export function warn(message: string, data?: unknown): void { log('warn', message, data); }
export function error(message: string, data?: unknown): void { log('error', message, data); }

export async function getLogs(): Promise<LogEntry[]> {
  try {
    const result = await browser.storage.local.get('agentLogs');
    return (result.agentLogs as LogEntry[]) || [];
  } catch {
    return [];
  }
}

export async function clearLogs(): Promise<void> {
  logBuffer = [];
  await browser.storage.local.remove('agentLogs');
}
