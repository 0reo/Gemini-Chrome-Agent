/** Session debug logging — remove after DEBUG-866d96 is resolved. */
export function dbgAgent(
  hypothesisId: string,
  location: string,
  message: string,
  data: Record<string, unknown> = {},
  runId = 'pre-fix',
): void {
  // #region agent log
  fetch('http://127.0.0.1:7471/ingest/b1058211-a8a6-4f68-9155-60dcd01a7c87', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': '866d96' },
    body: JSON.stringify({
      sessionId: '866d96',
      runId,
      hypothesisId,
      location,
      message,
      data,
      timestamp: Date.now(),
    }),
  }).catch(() => {});
  // #endregion
}
