# Desktop Pet: improvement list

Measured 2026-11-15, Yellow at 112 px, 60 Hz screen, smooth on. Effort: S < 1 h, M = a few hours, L = a day or more.
`*` = recommended.

## Measured
- Frame timer is 15 ms, screen refresh is 16.67 ms: 7 frames a second land twice in one refresh (uneven glide).
- A new rotation angle costs 5 to 15 ms the first time (dropped frame in throws and swings).
- Yellow at his laptop: 1.8 ms a frame (about 12% of one core), 187 ms hitch on first sit.
- An idle pet re-sends the same picture 66 times a second (0.165 ms each; a move alone is 0.011 ms).
- Memory 111 MB. `timeBeginPeriod(1)` stays on all the time.
- Walk has 6 pictures, run 11, climb 5. Idle, sit and lie are 1 still picture.

## A. Smoother animation
- A1* Screen-synced frames: pace on the display refresh (DwmFlush), also follows 120/144 Hz. M
- A2* No hitch in throws and swings: rotate with Qt per frame, fractional degrees. M
- A3* Feet match the ground: walk and run frames advance with distance, so Speed no longer slides the feet. S
- A4* Ease in and out: walk, run and climb ramp up and down over about 0.2 s. S
- A5 Turn-around: pass through the standing picture for 3 frames, not an instant mirror flip. S
- A6 Real in-betweens: replace the 50% cross-fade (ghost limbs) with shape-morph frames from the pack's own pictures. L, needs a visual check per character, may be rejected.
- A7 Soft state changes: 80 ms blend when walk turns into idle, sit, lie. S
- A8 Idle breathing: slow 1 to 2% chest rise on idle, sit, lie (not a bounce). S, taste risk.
- A9 Sub-pixel glide: draw slow moves at quarter-pixel offsets. M, small gain.
- A10 Settings preview at 30 fps (now 10 fps), pictures cached. S

## P. Less strain on the device
- P1* Draw only on change: skip identical frames, move-only when the picture is the same. S
- P2* Cache the laptop scene and the staff fall: 1.8 ms to about 0.2 ms, built at load. S
- P3* Sleep when still: tick drops to a few Hz when every pet sits or idles. S
- P4* Drop the always-on 1 ms system timer (needs A1, or only while moving). S
- P5* Pause in fullscreen apps, on the lock screen, with the display off. Toggle in Settings. M
- P6 Battery mode: 30 fps and calmer on battery. S
- P7 Event-driven background checks: no 100 ms and 200 ms polls. S
- P8 Lower memory: skip states that are switched off (dance is 98 pictures x 2), mirror on demand. About 15 to 25 MB. M

## F. Functionality
- F1 Stand on any visible window, not only the active one. L
- F2 Walk across monitors. M
- F3 Call pets: they run to the pointer (menu, tray). S
- F4 Click reactions: a click without a drag gets a small reaction. S
- F5 Pets notice each other: stop, face, sit together. M
- F6* Instant display changes: resolution, taskbar, monitor changes apply at once (now up to 60 s). S
- F7* Error log in %APPDATA%\DesktopPet\log.txt (pythonw hides crashes). S
- F8 Global hotkey to hide and show pets. S

## E. Ease of use
- E1* Richer right-click menu: change this pet's character, sit here, hide all, pause. S
- E2 Tray quick actions: add by character, pause, hide for 1 hour. S
- E3* Bring pets back on a normal launch (now it opens Settings with zero pets). Toggle. S
- E4 Fix the stale README. S

## S. Look
- S1* Fade in and out on spawn, remove, hide (150 ms). S
- S2 Soft ground shadow under a standing pet. S, taste risk.
- S3* Readable terminal: thin dark outline on Yellow's code (white text vanishes on light windows). S
