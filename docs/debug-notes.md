# Debug notes (branch debug/setup-python-telegram)

Problems found while testing the installer. "Fixed" items are on this branch; "Open" items are recorded only.

## Fixed

1. **Skipping Telegram/Discord left SYNOX unable to start.** `Start.bat` ended with
   "bot_token 還不是真的 Telegram token，也沒有開 Discord". Now:
   - the wizard lets you skip the bot step, and offers Discord as a second channel;
   - with no chat channel, `synox run` runs web-only (`run_channels` returns `()` when `web.enabled`; it still errors
     if the web UI is off too) and opens the web UI with a one-time owner login link;
   - the skip config uses the reserved local owner id (`logic.local_owner_id()`).
2. **Owner could not get into the local web UI after skipping** ("請先登入 … 在 Telegram 打 /web").
   - Root cause 1: on Windows `HTTPServer` (SO_REUSEADDR) let a second SYNOX bind a port another SYNOX already
     listened on, so its login link went to the other instance, which did not know the token. The web server now binds
     exclusively on Windows (SO_EXCLUSIVEADDRUSE); a taken port is a normal bind failure with a message, and web-only
     mode stops with exit code 2 instead of running with no reachable UI.
   - Root cause 2: the only owner link was the one opened at startup. New `python -m synox web-login` and
     `Open-SYNOX.bat` start SYNOX if needed and open a fresh one-time owner link; the desktop shortcut targets it.
     The "請先登入" page now explains this before mentioning Telegram `/web`. The two-step login (confirm page, POST with
     form token + cookie + Origin check) is unchanged.
3. **Browser popped up on every start, including autostart at login.** The Startup entry runs
   `Start.bat --no-browser` (sets `SYNOX_NO_BROWSER=1`); `run --no-browser` / `SYNOX_NO_BROWSER` are honoured.
4. **Finish page** has a "完成後立刻開啟 SYNOX" checkbox (default on). Unchecked: config, shortcuts and autostart are
   still written, nothing is launched.
5. **AI step: no way to get Claude Code.** When `claude` is not found the page shows "打開下載網頁" and
   "裝好了，重新偵測".
6. **Icon wiring.** Desktop shortcut, startup shortcut and the wizard window use `src/synox/assets/synox.ico`
   (placeholder artwork).
7. **Telegram / Discord from the web UI.** Settings page has an owner-only "聊天通道" card: paste a token, it is
   checked (`getMe`) and saved like the wizard does (Discord token goes into the vault; a multi-bot `channels.discord.bots`
   config is refused). Restart is needed for a channel change to take effect. Owner pairing is NOT in the web UI (see Open 5).
8. `logic.save_discord_token` no longer writes the vault before refusing a multi-bot config.

9. **Uninstall / reset for testing.** `Uninstall.bat` (menu, or `Uninstall.bat check|shortcuts|env|all [-Yes]`) runs
   `setup/uninstall.ps1`: `check` only lists what is installed; `shortcuts` stops SYNOX and removes the desktop shortcut,
   startup entry and .synoxpack association; `env` also deletes `.venv` and `runtime\` (config and data kept, Setup.bat
   restores it); `all` also deletes `config.json` and `data\` (asks you to type DELETE unless `-Yes`). It never deletes the
   SYNOX folder. Reinstall = Uninstall + Setup.bat. Repair = re-run Setup.bat (idempotent, reuses `.venv`, prefills the
   wizard from config.json) and `python -m synox doctor`; no separate Repair tool for now.

10. **Local owner opens the web UI without a link.** In personal mode, typing `http://127.0.0.1:<port>/` in the browser
   (address bar, bookmark, desktop shortcut) logs the owner in automatically. Accepted only for a real browser navigation:
   `Host` must be 127.0.0.1/localhost with our port (blocks DNS rebinding), `Sec-Fetch-Site: none`, `Sec-Fetch-Mode: navigate`,
   `Sec-Fetch-Dest: document`, no `Origin`. Why not no check at all: the web UI can install packs, i.e. run code on this PC, so
   any web page open in the same browser must not be able to reach it. Off for server mode, when `web.public_url` is set, or
   with `"web": {"local_auto_login": false}`. Other OS user accounts on the same PC can still reach the port; the link flow
   (`Open-SYNOX.bat`) stays for them and for non-browser clients.

## Open

1. **Icon artwork** is a placeholder (blue square with an "S"); needs a real design.
2. **No small control app / tray icon.** Nothing in the notification area or taskbar shows status or opens/stops
   SYNOX; it runs in a minimized console window started by `Start.bat`.
3. **nssm / Windows service: not implemented** (no nssm, service or scheduled-task code in the repo).
   Recommendation: build a tray app (e.g. a small `pystray` process started at login by the existing Startup entry)
   with "Open SYNOX" (= `web-login`), status, "Stop", and "Start at login". Do not use a Windows service: it runs in
   session 0, cannot show a window or open the user's browser, needs admin rights and a bundled nssm binary, and a
   non-technical user does not benefit from service semantics on a personal PC. A service only makes sense for a
   shared always-on server install, which can stay a documented, advanced option.
4. **Real-bot testing.** Discord pairing in the wizard and the new web channel card were only tested with fakes (no
   real Telegram/Discord bot, no real browser for the new JavaScript).
5. **Owner id change (needs a product decision).** A web-only install uses the placeholder owner id
   (`local_owner_id()`, 10**15). Pairing Telegram (re-running Setup, or a future web pairing flow) replaces it with
   the real Telegram id, so data stored under the placeholder (notes, web chats, any Discord link in identities.json)
   is no longer the owner's. Decide: migrate/alias the old id, or keep the placeholder as the owner and link Telegram to
   it (as Discord does today). This also blocks Telegram pairing from the web UI.
6. Decisions pending from the user: should the desktop shortcut (`Open-SYNOX.bat`) also open the web UI for users who
   have Telegram; port conflict behaviour (stop with a message vs pick a free port); finish button text when the
   checkbox is off ("完成並開始" vs "完成"); Telegram bot token stays in plain text in config.json (as the wizard does).
7. Older SYNOX copies still bind with SO_REUSEADDR and can bind over a new one; browser cookies are not separated by
   port, so two local instances share the session cookie name.
