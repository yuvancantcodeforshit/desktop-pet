# HANDOFF: desktop-pet

Personal Windows desktop pet (Shimeji-like), PySide6 + Pillow. Repo `yuvancantcodeforshit/desktop-pet`.
Working copy: `C:\Users\Yuvan\OneDrive\Documents\desktop-pet` (the old `C:\Users\Yuvan\Documents\desktop-pet` is gone).
Owner: terse replies (ultracave, max 5 list items, one next action). Windows, PowerShell.

## 1. State
- `main` = `origin/main` at `2dde049`, clean, no open PRs. `python pet.py --selftest` prints `selftest ok` (~17 s).
- Works: physics at 30 Hz (`STEP`), Settings window (`panel.py`, PySide6, tabs Home/Characters/Customize/Settings), packs (Alan Becker Yellow/Blue/Green/Orange/Purple/Red/TCO/TDL/victim), Smoother animations toggle (setting `smooth`, Settings > General), single-instance lock.
- Removed on purpose: back landing (PR #68), Yellow-only tweaks (PR #69). Yellow still sits at his laptop (`Pet.laptop()`, `desk_parts`).
- Not working: "run at login" (`autostart()`, `pet.py:221`) builds `pythonw.exe` beside `sys.executable`. That file no longer exists in `C:\Users\Yuvan\AppData\Local\Python\pythoncore-3.14-64\`. Login entry is off now.
- Stale: `README.md` says the Settings window is CustomTkinter. It is PySide6.
- Many merged feature branches remain on origin (`back-*`, `desk-*`, ...). Harmless.

## 2. Open tasks
1. Fix `autostart()`: use `Desktop Pet.exe` (renamed `pythonw.exe`, same folder) when `pythonw.exe` is missing. Test: toggle Settings > General > Start with Windows, then read `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` value `DesktopPet`.
2. Click the Start menu shortcut once to confirm it launches (only the same exe and args were tested by hand). Shortcut: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Desktop Pet.lnk`.
3. Optional: update README (PySide6 panel; drop release/signing/updater text, see rule 5).
4. Optional: `~/.claude/projects/C--Users-Yuvan-OneDrive-Documents-desktop-pet/memory/` is empty. Rules live in the old `...-Documents-desktop-pet/memory/`. Copy them over.

## 3. Files
- `pet.py` (~1900 lines): `Pet` (state machine, physics, drawing), `App` (tray, windows, settings), `show_layered` (per-pixel-alpha window), `selftest()`, settings load/save, updater.
- `panel.py` (~1230 lines): Settings window, search index, themes.
- `packs.py`: import (folder/zip/shimeji), list, delete, `load_frames(folder, px)`.
- `dev.py`: developer panel (not shipped). `release.ps1`, `installer.py`, `install.cmd`, `uninstall.cmd`, `signing/`, `dist/`: release tooling, unused.
- `graphify-out/` and `dist/` are git-ignored.
- Data: `%APPDATA%\DesktopPet\settings.json` and `characters\` (user packs). Do not delete.

## 4. Run, test, screenshot
- Run from source (PowerShell, repo folder): `python pet.py` (opens Settings; send a pet out from there). `--startup` skips the window.
- Real launch mimic: `& "C:\Users\Yuvan\AppData\Local\Python\pythoncore-3.14-64\Desktop Pet.exe" pet.py --startup`.
- Restart: kill only the PID whose command line has `pet.py`. Then relaunch.
- Test: `python pet.py --selftest` (exits 1 and prints `selftest FAILED` on error).
- Visual change: launch the app, screenshot, zoom, then commit. Test screen: "Built-in Display" 1920x1020 at 125%. Tools: `mcp__computer-use__*`.
- Workflow: branch, PR, merge to `main`, restart the pet. Merge freely. No releases unless asked.

## 5. Rules and gotchas
- Never kill by image name (`pythonw.exe`, `Desktop Pet.exe`): it also kills other Python apps. Screenshots can hide the user's windows.
- Personal use only: no signing, sharing, or releases. Do not touch updater/release code.
- Animate with each pack's own pictures; never draw characters in code (a code-drawn ragdoll was rejected). Human-like motion, no bouncy-ball squash.
- TCO, TDL, Orange have ring heads (others solid discs). When borrowing or recolouring frames, use that character's own head cut from its own standing picture, trimmed to a circle. Zoom to check.
- Head size: measure solid pixels, not the soft anti-aliased edge.
- Pictures are cached keyed by the source image object (`id()` is reused). Key caches on the picture, as `desk_parts` does.
- `pet.py` uses LF endings. Old patch scripts wrote CRLF: don't.
- Bind any local server to `127.0.0.1`. No `CLAUDE.md` in the repo; global one in `~/.claude/CLAUDE.md`.
