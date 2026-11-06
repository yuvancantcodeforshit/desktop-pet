# desktop-pet

this thingy lets you drop a pet on ur desktop. u can move it around and stuff, throw it against the wall, downslam it, idk. do whatever

Right-click it for **Settings / Add pet / Remove this pet / Quit**, or use the tray icon by the clock.

**Settings window** (own dark title bar: minimize, eye = hide to tray, close):
- **Home:** live preview, current character, speed / size / number of pets, show or hide all pets.
- **Characters:** pick a character pack (drop a folder or `.zip` on the tab, or use the buttons);
  the default blob has styles (Blob, Cat, Ghost, Bunny) and colors.
- **Customize:** window theme, accent color, font.
- **Settings:** start with Windows, which screens pets use, updates, about, reset.

Everything is saved in `%APPDATA%\DesktopPet\` (packs in `characters\`).

## Character packs

A folder or `.zip` with one image per state. Only `idle` is required; missing states use `idle`.
Images face right (the pet mirrors them walking left); animated GIF or still PNG, up to 2048 px.

```
my-cat/
  pack.json   {"name": "My cat", "author": "you", "fps": 8}   (optional)
  idle.gif    walk.gif    fall.png    drag.png    sit.png    climb.gif
```

## Run from source

```powershell
python -m pip install --user customtkinter tkinterdnd2 pystray pillow
pythonw pet.py
```

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

Or use the developer panel: `pythonw dev.py` (buttons for release, selftest, run pet, git pull, GitHub).

Selftest, version bump, build, commit + push, GitHub release — one command.
Needs Python with `pyinstaller` and the GitHub CLI signed in once (`gh auth login`).

## Code signing

Unsigned exes get blocked by Windows **Smart App Control** and warned about by SmartScreen.
`release.ps1` signs both exes automatically once `signing\metadata.json` exists. One-time setup
(individuals must live in the US or Canada; Microsoft bills from the moment the account is created):

1. Azure account with a pay-as-you-go subscription, billing account type **Individual**,
   legal name + address exactly as on your government ID.
2. Azure portal > create an **Artifact Signing account** (Basic tier). Note its region endpoint
   (e.g. East US = `https://eus.codesigning.azure.net`).
3. On that account > Access control (IAM): give yourself **Artifact Signing Identity Verifier** and
   **Artifact Signing Certificate Profile Signer**.
4. Identity validation > New identity > Individual. Takes 1–20 business days.
5. Certificate profiles > create a **Public Trust** profile.
6. On this PC: `winget install -e --id Microsoft.Azure.ArtifactSigningClientTools`,
   `winget install -e --id Microsoft.AzureCLI`, then `az login`.
7. Copy `signing\metadata.example.json` to `signing\metadata.json` and fill in the endpoint,
   account and profile names. (It's git-ignored.)

Then `.\release.ps1 <version>` signs, tests and publishes as usual.

## Files

| File | What it is |
|------|------------|
| `pet.py` | The pet itself, tray icon, settings storage, auto-updater. `python pet.py` runs it, `--selftest` checks everything. |
| `panel.py` | The Settings window (CustomTkinter): title bar, 4 tabs. |
| `packs.py` | Character packs: import (folder/zip, with safety checks), list, delete, load animation frames. |
| `installer.py` | Builds into `DesktopPetSetup.exe`; runs `install.cmd`. `/S` = silent. |
| `install.cmd` | Copies the app to `%LOCALAPPDATA%\Programs\DesktopPet`, adds Start menu + Apps entry. No admin. |
| `uninstall.cmd` | Removes all of the above. |
| `release.ps1` | The one-command release. |
| `dev.py` | Developer panel (not shipped): release / selftest / run / git buttons. |
| `dist/` | Build output (not committed). |
