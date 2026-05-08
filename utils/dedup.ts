import { CONFIG } from './config';
import { hashPayload } from './protocol';
import type { AgentPayload } from './types';
import { debug } from './logger';

const processedPayloads = new Map<string, number>();
let lastCleanup = 0;

export function isRecentlyProcessed(payload: AgentPayload): boolean {
  const now = Date.now();
  const hash = hashPayload(payload);

  if (now - lastCleanup > CONFIG.CLEANUP_INTERVAL_MS) {
    lastCleanup = now;
    for (const [key, time] of processedPayloads.entries()) {
      if (now - time > CONFIG.PAYLOAD_TTL_MS) {
        processedPayloads.delete(key);
      }
    }
  }

  if (processedPayloads.has(hash)) {
    debug('Deduplication: payload rejected', { hash, action: payload.action });
    return true;
  }

  processedPayloads.set(hash, now);
  return false;
}

export function markPayloadProcessed(payload: AgentPayload): void {
  const hash = hashPayload(payload);
  processedPayloads.set(hash, Date.now());
}

export function clearProcessedPayloads(): void {
  processedPayloads.clear();
  lastCleanup = 0;
}
