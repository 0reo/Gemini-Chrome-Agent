# Driving the live extension yourself

"Test it in the browser" = **you** launch, attach, inject a real payload, and read the evidence. You do
not open the browser and hand it back. This file has the exact commands and CDP/MCP probes.

## 1. Launch the debug Brave

```bash
./scripts/launch-debug-brave.sh                 # builds if needed, loads ext, CDP on :9222
GLA_DEBUG_PORT=9333 ./scripts/launch-debug-brave.sh    # if 9222 is taken
```

Why this exact launch (don't substitute a plain `npx chrome-devtools-mcp` launch-mode, and don't use
Playwright's bundled Chromium):
- **Attach, never launch-fresh.** A fresh Chrome has no Google login, no loaded extension, and the wrong
  extension ID → it cannot reach a logged-in Gemini and native messaging is dead. You must attach to the
  real Brave profile that has the extension + login.
- `--remote-allow-origins=*` is **required** on Chrome/Brave 144+, or the `/json` CDP discovery endpoints
  404 and `--browserUrl` can't find the socket.
- Loads from the absolute `.output/chrome-mv3` (no trailing slash) so the ID stays
  `pggfgfolmomlhlnabkfboiiojdkhapoh` (native-messaging lock — see pipeline-stages stage 4).
- No `--headless` / `--enable-automation`: Google blocks login ("browser may not be secure") otherwise.
  The persistent profile (`gla-debug-profile`) remembers the login after the first manual sign-in.

## 2. Attach

`.mcp.json` defines a `brave-debug` MCP server (`chrome-devtools-mcp --browserUrl http://127.0.0.1:9222`).
Your client loads `.mcp.json` at session start — **restart the session** after first creating/launching it.
Then: `list_pages` → `navigate_page` (to the Gemini tab) → `evaluate_script` / `take_snapshot` /
`list_console_messages`.

> Reminder: `list_console_messages` shows the **MAIN** world. `content.ts` logs in the **ISOLATED** world
> and won't appear there. Read storage/DOM/dispatched-events instead (all cross both worlds).

## 3. Read live state first (Rule 1) — paste-ready `evaluate_script`

**Is it actually paused, and what are the settings?** `chrome.*` APIs exist **only in extension
contexts** — run this against the **service-worker** target (`brave://extensions/` → service worker, or
the SW target over CDP), NOT the Gemini page. On a page's MAIN world `chrome.storage` is `undefined` and
the read throws `chrome is undefined` — which is exactly the misleading failure you'll hit when the SW is
asleep. If `list_pages`/targets show no service worker, the SW is asleep or the extension isn't loaded:
wake it (click the SW link) before trusting any storage read. (The content script's ISOLATED world and
the popup can also read storage, but the SW target is the reliable one to drive over CDP.)
```js
// in the SERVICE-WORKER context:
() => new Promise((resolve) =>
  chrome.storage.local.get(
    ['isAgentPaused','autoSubmit','cooldownSeconds','maxPerMinute','settlingSeconds'],
    resolve));
```

**Did it already succeed? (stage 5 — check this BEFORE anything upstream):**
```js
() => {
  const ed = document.querySelector('.ql-editor') || document.querySelector('[contenteditable="true"]');
  const send = document.querySelector('button[aria-label="Send message"]');
  return {
    threadHasSystemResult: document.body.innerText.includes('System Result'),
    composerText: ed ? (ed.innerText || ed.textContent || '').slice(0, 200) : null,
    composerBlank: ed ? ed.classList.contains('ql-blank') : null,   // true = empty = likely already sent
    sendPointerEvents: send ? getComputedStyle(send).pointerEvents : 'no-send-button', // 'none' = not armed
    qlEditors: document.querySelectorAll('.ql-editor').length,
    url: location.href,
  };
}
```
`threadHasSystemResult: true` (or composer blank + a new turn) ⇒ **the pipeline worked**; stop blaming it.

## 4. Reproduce the user scenario end-to-end

Inject a **real** action block into the page the way Gemini would, then watch all three surfaces.

```js
// stage-1 input: create a <pre><code> block the content script will scan
() => {
  const pre = document.createElement('pre');
  const code = document.createElement('code');
  code.className = 'language-json';
  code.textContent = '{"action":"run_shell","command":"echo gla_live_probe"}';
  pre.appendChild(code);
  document.body.appendChild(pre);
  return { injected: true };
}
```
Then, within a few seconds:
- `tail -n 20 /tmp/gemini_host.log` → expect `message received {action:"run_shell"}` (stage 4 proof).
- re-run the stage-5 probe → expect `gla_live_probe` output in a `System Result:` turn.
- `list_console_messages` (SW context) for `[Background]` (stage 3); the page's own DevTools for
  `[Gemini Agent] scan complete {withAction, executed}` (stages 1–2).

> **False-green warning (this is how the motivating incident went wrong).** A `<pre><code>` you inject
> *after* the page loaded is a brand-new element, past the settling window and not in the
> `blocksPresentAtLoad` set — so it runs fine and "proves" the extension works while the user's is still
> broken. It tests the happy path, **not the user's condition.** Two things it does NOT reproduce:
> 1. **The load-time guards.** If the user's symptom is "JSON was on screen, nothing ran," the block was
>    present *before* the script loaded (history / refresh / extension reload). Reproduce that: put the
>    block in the DOM, then **reload the tab** (or `chrome.runtime.reload()` the extension) and watch —
>    expect a `historical block skip`. A post-load injection skips this entirely.
> 2. **Gemini's renderer.** Your hand-built node may be a clean `<pre><code>` when Gemini's streamed
>    output is split across nodes or inline. Inspect the *real* node from the failing chat:
>    `[...document.querySelectorAll('pre code, code')].map(n => n.textContent.slice(0,80))`.
>
> Prefer driving Gemini to emit the block itself, or testing directly on the user's actual failing tab,
> over a synthetic injection. When you must inject, inject-then-reload to exercise the load path.

**Mind the guards while reproducing:** if you just reloaded, wait out the 5 s settling window; if you
just ran a payload, wait out the 15 s cooldown; an identical payload within 60 s is deduped. To force a
clean run, resume + reload, or vary the command string.

## 5. Toggle pause from CDP (the keyboard shortcut crosses worlds via the window EventTarget)

```js
() => { window.dispatchEvent(new KeyboardEvent('keydown',
  {altKey:true, shiftKey:true, key:'K', code:'KeyK', bubbles:true, cancelable:true}));
  return {toggled:true}; }
```
Or set storage directly **from the service-worker context** (not the page):
`chrome.storage.local.set({ isAgentPaused: false })`.

## 6. One-shot alternative (no MCP wired)

`scripts/diagnose.py` does steps 3–4 in one CLI pass and prints a per-stage verdict. Run from repo root
(it reuses `test/e2e_browser.py`'s CDP client):
```bash
python3 .agents/skills/debugging-gemini-agent/scripts/diagnose.py [port]
```

## Operational gotchas (learned the hard way)

- **Port contention looks like "the extension is blocking CDP."** Two Brave instances both binding `:9222`
  (one on `127.0.0.1`, one on `[::1]`) make CDP attach flaky/split-brain. The extension and MCP are
  innocent. Check holders: `ss -tlnp | grep 9222` / `lsof -i :9222`, then `kill <pid>` the stray one.
- **Don't `pkill -f gla-debug-profile`** — your own shell's command line contains that string, so pkill
  SIGTERMs the shell mid-command. Kill specific PIDs from `lsof`/`ss` output instead.
