# Debug notes (branch debug/setup-python-telegram)

Problems found while testing the installer. "Fixed" items are on this branch; "Open" items are recorded only.

## Fixed

1. **Skipping Telegram/Discord left SYNOX unable to start.** `Start.bat` ended with
   "bot_token 還不是真的 Telegram token，也沒有開 Discord". Now:
   - the wizard lets you skip the bot step (and the Discord option is available);
   - with no chat channel, `synox run` runs web-only and opens the web UI with a one-time owner login link
     (`run_channels` returns `()` when `web.enabled`; it still errors if the web UI is off too);
   - the finish page always starts SYNOX; the skip config uses the reserved local owner id
     (`logic.local_owner_id()`), which is replaced when Telegram is added later by re-running Setup.
2. **AI step: no way to get Claude Code.** When `claude` is not found the page shows
   "打開下載網頁" and "裝好了，重新偵測".
3. **Icon.** Desktop shortcut, startup shortcut and the wizard window now use `src/synox/assets/synox.ico`
   (placeholder artwork generated once; replace the file to change it).

## Open (not done on this branch)

1. **Icon artwork** is a placeholder (blue square with an "S"); needs a real design.
2. **No small control app / tray icon.** There is nothing in the notification area or taskbar to show status or
   open/stop SYNOX. Today SYNOX runs in a minimized console window started by `Start.bat`.
3. **Installer does not offer "start SYNOX now / at login" as a clear choice.** Autostart is a checkbox
   (default off) and the app is always started at the end of the wizard; there is no explicit "open now" option.
4. **nssm / Windows service: not implemented** (no nssm, service or scheduled-task code in the repo).
   A service runs in session 0 and cannot show a window or open a browser, so a tray app is probably the better fit
   for non-technical users.
5. **Telegram / Discord cannot be set up from the web UI.** The settings page only covers the AI source,
   packs and backup. Users who skip the bot step must re-run `Setup.bat` to add a bot. A "channels" section in
   the web settings (token check, pairing, save to vault) is the natural follow-up.
6. In web-only mode the browser opens on every start (including autostart at login).
7. Discord pairing in the wizard was only unit-tested, never run against a real bot.
