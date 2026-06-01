import { CONFIG } from '@/utils/config';
import { dbgAgent } from '@/utils/debug-agent-log';
import { info, warn, error } from '@/utils/logger';
import type { ExtensionMessage, HostResponse } from '@/utils/types';

export default defineBackground(() => {
  let port: Browser.runtime.Port | null = null;
  const pendingResponses = new Map<string, number>();

  function connectToHost(): void {
    info('Connecting to native host...');
    port = browser.runtime.connectNative(CONFIG.NATIVE_HOST_NAME);

    port.onMessage.addListener((response: HostResponse) => {
      info('Received from host', { id: response.id, status: response.status });
      clearPendingTimeout(response.id);

      browser.storage.session.get('lastActiveTabId').then(({ lastActiveTabId }) => {
        if (lastActiveTabId) {
          browser.tabs.sendMessage(lastActiveTabId as number, { type: 'HOST_RESPONSE', data: response })
            .catch((err: Error) => {
              warn('Failed to route to stored tab, broadcasting fallback', { error: err.message });
              broadcastToGeminiTabs(response);
            });
        } else {
          broadcastToGeminiTabs(response);
        }
      });
    });

    port.onDisconnect.addListener(() => {
      const lastError = browser.runtime.lastError;
      if (lastError) {
        error('Native host disconnected with error', { message: lastError.message });
        dbgAgent('D', 'background.ts:onDisconnect', 'native host error', {
          message: lastError.message,
        });
      } else {
        info('Native host disconnected (clean)');
      }
      port = null;
    });
  }

  function broadcastToGeminiTabs(response: HostResponse): void {
    browser.tabs.query({ url: '*://gemini.google.com/*' }).then((tabs) => {
      if (tabs.length > 0) {
        const target = tabs[tabs.length - 1];
        if (target.id) {
          browser.tabs.sendMessage(target.id, { type: 'HOST_RESPONSE', data: response })
            .catch((err: Error) => warn('Fallback broadcast failed', { error: err.message }));
        }
      } else {
        warn('No Gemini tab found for response broadcast');
      }
    });
  }

  function setPendingTimeout(id: string): void {
    const timer = self.setTimeout(() => {
      pendingResponses.delete(id);
      warn('Request timed out waiting for host response', { id });
    }, 60000);
    pendingResponses.set(id, timer);
  }

  function clearPendingTimeout(id: string): void {
    const timer = pendingResponses.get(id);
    if (timer) {
      self.clearTimeout(timer);
      pendingResponses.delete(id);
    }
  }

  // Initialize connection (guarded for build-time compatibility)
  if (typeof browser.runtime.connectNative === 'function') {
    connectToHost();
  }

  // Listen for messages from content scripts
  browser.runtime.onMessage.addListener((request: ExtensionMessage, sender) => {
    if (request.type === 'SEND_TO_HOST' && request.payload) {
      dbgAgent('D', 'background.ts:SEND_TO_HOST', 'forwarding', {
        id: request.payload.id,
        action: request.payload.action,
        hasPort: !!port,
      });
      info('Forwarding payload to host', { id: request.payload.id, action: request.payload.action });

      if (sender.tab?.id) {
        browser.storage.session.set({ lastActiveTabId: sender.tab.id })
          .catch((err: Error) => warn('Failed to persist tab ID', { error: err.message }));
      }

      if (!port && typeof browser.runtime.connectNative === 'function') {
        info('Native port missing; reconnecting...');
        connectToHost();
      }

      try {
        port?.postMessage(request.payload);
        setPendingTimeout(request.payload.id);
        info('Payload forwarded successfully');
      } catch (e) {
        error('Failed to post message to host', { error: (e as Error).message });
      }
    }
  });

  // Keep service worker alive while Native Messaging is active
  browser.runtime.onConnect.addListener((externalPort) => {
    externalPort.onDisconnect.addListener(() => {
      info('External port disconnected');
    });
  });
});
