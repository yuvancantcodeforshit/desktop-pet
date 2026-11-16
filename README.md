# desktop-pet

this thingy lets you drop a pet on ur desktop. u can move it around and stuff, throw it against the wall, downslam it, idk. do whatever

Right-click a pet for **Settings / Add pet / Change character / Sit here / Call pets here / Pause pets / Hide pets /
Remove this pet / Quit**. The tray icon by the clock has **Settings / Add pet / Call pets / Pause pets / Show pets /
Hide for 1 hour / Quit**.

## What pets do

- Walk, run, sit, lie down, climb walls, swing along the top of the screen.
- Stand on any window's top edge and jump up onto it.
- Walk across to the monitor next door.
- Click one: a little hop. Drag one: pick it up, swing it, throw it.
- Two pets that meet stop and face each other. Sometimes they sit down together.
- **Ctrl+Alt+P** hides or shows them all.

## Easy on the PC

- Frames follow the screen refresh (60, 120, 144 Hz).
- Nothing is redrawn when nothing changed. Resting pets tick a few times a second.
- Pets hide and stop in fullscreen apps, on the lock screen and with the display off.
- Half the frame rate on battery.

**Settings window** (own dark title bar: minimize, eye = hide to tray, close):
- **Home:** live preview, current character, speed / size / number of pets, show or hide all pets.
- **Characters:** pick a character pack (drop a folder or `.zip` on the tab, or use the buttons);
  the default blob has styles (Blob, Cat, Ghost, Bunny) and colors.
- **Customize:** window theme, accent color, font.
- **Settings:** start with Windows, bring pets back on launch, smoother animations, ground shadow, idle breathing,
  hide in fullscreen, battery saver, hotkey, physics, which screens pets use, about, reset.

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
python -m pip install --user pyside6-essentials pillow
python pet.py
```

`python pet.py --startup` brings the saved pets back without opening Settings. `python pet.py --selftest` checks it.
The Settings window is PySide6. Errors go to `%APPDATA%\DesktopPet\log.txt`.
