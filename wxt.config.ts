import { defineConfig } from 'wxt';

// See https://wxt.dev/api/config.html
export default defineConfig({
  manifest: {
    name: 'Gemini Local Agent',
    description: 'Bridge between Google Gemini web UI and local Ubuntu via Native Messaging',
    version: '2.0.0',
    permissions: ['nativeMessaging', 'activeTab', 'scripting', 'storage'],
    host_permissions: ['*://gemini.google.com/*'],
  },
});
