"""DesktopPetSetup.exe: bundles DesktopPet.exe + install.cmd + uninstall.cmd and runs install.cmd.
Pass /S for a silent install (no dialogs).
"""
import ctypes, os, subprocess, sys

TITLE = 'Desktop Pet Setup'
quiet = '/S' in sys.argv
box = ctypes.windll.user32.MessageBoxW

if quiet or box(0, 'Install Desktop Pet?', TITLE, 0x24) == 6:  # MB_YESNO|MB_ICONQUESTION -> IDYES
    # Full cmd.exe path + private cwd: never run a cmd.exe/reg.exe planted next to the installer.
    cmd = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'cmd.exe')
    # Reset so the launched DesktopPet.exe doesn't reuse this installer's temp folder (deleted on exit).
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
    r = subprocess.run([cmd, '/c', os.path.join(sys._MEIPASS, 'install.cmd')], cwd=sys._MEIPASS, env=env,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    if not quiet:
        if r.returncode == 0:
            box(0, 'Desktop Pet is installed. Open it any time from the Start menu.', TITLE, 0x40)
        else:
            box(0, f'Install failed (code {r.returncode}).', TITLE, 0x10)
    sys.exit(r.returncode)
