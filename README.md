# desktop-pet

this thingy lets you drop a pet on ur desktop. u can move it around and stuff, throw it against the wall, downslam it, idk. do whatever

Right-click it for **Add pet / Remove this pet / Quit**.

## Install

1. Download `DesktopPetSetup.exe` from the [latest release](https://github.com/yuvancantcodeforshit/desktop-pet/releases/latest).
2. Double-click it, answer **Yes**. (Windows warning? **More info** > **Run anyway** — the exe isn't code-signed.)
3. Open it any time: Start menu > **Desktop Pet**.

Uninstall: Settings > Apps > Desktop Pet > Uninstall.

## Updates

Automatic. On start the pet checks the latest GitHub release, downloads a newer `DesktopPet.exe`,
verifies its SHA-256, and restarts into it within a minute. Offline or bad download: keeps the current version.

## Release a new version

```powershell
.\release.ps1 1.0.1
```

Selftest, version bump, build, commit + push, GitHub release — one command.
Needs Python with `pyinstaller` and the GitHub CLI signed in once (`gh auth login`).

## Files

| File | What it is |
|------|------------|
| `pet.py` | The pet itself + auto-updater. `python pet.py` runs it, `--selftest` checks it. |
| `installer.py` | Builds into `DesktopPetSetup.exe`; runs `install.cmd`. `/S` = silent. |
| `install.cmd` | Copies the app to `%LOCALAPPDATA%\Programs\DesktopPet`, adds Start menu + Apps entry. No admin. |
| `uninstall.cmd` | Removes all of the above. |
| `release.ps1` | The one-command release. |
| `dist/` | Build output (not committed). |
