"""Desktop pet: walks on the taskbar, climbs screen edges, falls, can be dragged and thrown.
Run: pythonw pet.py   (right-click a pet for Settings / Add / Remove / Quit; tray icon too)
"""
import ctypes, ctypes.wintypes, hashlib, io, json, math, os, random, re, shutil, subprocess, sys, tempfile, threading, time
import urllib.request, winreg

import packs
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QCursor, QIcon, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget

try:  # sharp text and images: draw at the real screen resolution instead of letting Windows stretch a blurry copy
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware; must happen before any window exists
except (AttributeError, OSError):
    ctypes.windll.user32.SetProcessDPIAware()
DPI_SCALE = ctypes.windll.user32.GetDpiForSystem() / 96
ctypes.windll.winmm.timeBeginPeriod(1)  # 1 ms timer: Windows' default 15.6 ms tick held Tk's timer to ~43 fps  # e.g. 1.25 on a 125% display; pets grow to match

VERSION = '1.0.4'        # bump before each release; release.ps1 reads it
REPO = 'yuvancantcodeforshit/desktop-pet'
UPDATE_URL = f'https://github.com/{REPO}/releases/latest/download/'
MAX_EXE = 100_000_000    # refuse absurd downloads

FROZEN = getattr(sys, 'frozen', False)  # True when running as the built DesktopPet.exe

SIZE = 64                # base pet size in px; the size setting scales it
KEY = '#010203'          # colour made fully transparent
GRAVITY = 1.5
LINE, CHEEK = '#2f6b3c', '#f4a6b8'

SETTINGS_DIR = os.path.join(os.environ.get('APPDATA') or os.path.expanduser('~'), 'DesktopPet')
SETTINGS_FILE = os.path.join(SETTINGS_DIR, 'settings.json')
PACKS_DIR = os.path.join(SETTINGS_DIR, 'characters')
CHARACTER_FILE = os.path.join(SETTINGS_DIR, 'character.png')  # single image from v1.0.3, moved into a pack on start
BLOB_STYLES = ('Blob', 'Cat', 'Ghost', 'Bunny')
# window themes: background, card, accent, text, muted text
THEMES = {
    'Midnight': ('#1c1c1c', '#2b2b2b', '#57c8ff', '#ffffff', '#9a9a9a'),
    'Ocean':    ('#0f1b2d', '#172a45', '#4fc3f7', '#ffffff', '#8fa3bf'),
    'Forest':   ('#13201a', '#1d3328', '#7ecf8f', '#ffffff', '#8fae9a'),
    'Sunset':   ('#2a1a1f', '#3d2630', '#ff9e7a', '#ffffff', '#b8949e'),
    'Grape':    ('#1d1730', '#2b2245', '#b9a3f0', '#ffffff', '#9d93b8'),
    'Rose':     ('#241519', '#341f26', '#f29fc4', '#ffffff', '#b99aa6'),
    'Mocha':    ('#1e1815', '#2d2420', '#e0a96d', '#ffffff', '#a8998c'),
    'Slate':    ('#1a1d23', '#262b34', '#7aa2f7', '#ffffff', '#8e96a8'),
    'Mint':     ('#101f1c', '#17302b', '#4fc1b3', '#ffffff', '#86aaa4'),
    'Nord':     ('#2e3440', '#3b4252', '#88c0d0', '#eceff4', '#9aa5b8'),
    'Crimson':  ('#1f1012', '#321a1d', '#ff6b6b', '#ffffff', '#b58f93'),
    'Amoled':   ('#000000', '#121212', '#57c8ff', '#ffffff', '#8a8a8a'),
    'Light':    ('#f3f3f3', '#ffffff', '#2f60d8', '#1a1a1a', '#666666'),
    'Cream':    ('#f6f1e7', '#fffaf0', '#c0763a', '#2a2118', '#7a6c5c'),
    'Sky':      ('#eaf2fb', '#ffffff', '#2f7fd8', '#14202e', '#5f7287'),
    'Blossom':  ('#fbeef2', '#ffffff', '#d8587f', '#2b1a20', '#7d6068'),
}
DEFAULTS = {'color': '#7ecf8f', 'speed': 1.0, 'size': 1.0, 'pets': 1, 'monitors': [], 'character': '',
            'style': 'Blob', 'theme': 'Midnight', 'accent': '', 'font': 'Segoe UI Variable', 'off': [], 'chars': {},
            'gravity': 1.0, 'throw': 1.0, 'damping': 1.0, 'spin': 1.0, 'advanced': False, 'schedule': {'on': False, 'from': 22, 'to': 7}, 'roster': {'': 1}}
# things a pet may do on its own; Settings > Home > Behaviour turns them off (saved in 'off')
ACTIONS = ('walk', 'run', 'sit', 'lie', 'dance', 'climb', 'chase', 'jump')
# per-character options (Settings > Characters > Tweaks): saved as settings['chars'][name][key]


def char_default(name, key):
    return {'fall': 'free' if name in FREE_FALL else 'steady', 'crash': 600}[key]


def char_opt(s, name, key):
    """A character's option: what you saved, else its built-in default."""
    v = s['chars'].get(name, {}).get(key)
    return char_default(name, key) if v is None else v


def clean_chars(v):
    """Keep only valid per-character options; anything mistyped or out of range is dropped one by one."""
    ok = {'fall': lambda x: x in ('steady', 'free'),
          'crash': lambda x: isinstance(x, (int, float)) and not isinstance(x, bool) and 100 <= x <= 2000}
    out = {}
    for name, d in (v.items() if isinstance(v, dict) else ()):
        if isinstance(name, str) and re.fullmatch(r'[\w\- ]{1,40}', name) and isinstance(d, dict):
            d = {k: x for k, x in d.items() if k in ok and ok[k](x)}
            if d:
                out[name] = d
    return out

# day and night (Settings > Home): calmer and sitting more at night, livelier by day
BASE_WEIGHTS = {'walk': 3, 'idle': 2, 'sit': 2, 'run': 1, 'lie': 1, 'dance': 1, 'jump': 1}
MOOD_WEIGHTS = {'night': {'walk': 1, 'idle': 3, 'sit': 5, 'run': 0, 'lie': 4, 'dance': 0, 'jump': 0},
                'day': {'walk': 4, 'idle': 1, 'sit': 1, 'run': 3, 'lie': 0, 'dance': 2, 'jump': 2}}


def clean_schedule(v):
    """{'on', 'from', 'to'}: each field that is mistyped or out of range falls back to its default."""
    v = v if isinstance(v, dict) else {}
    hour = lambda x, d: x if isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 23 else d
    return {'on': v.get('on') if isinstance(v.get('on'), bool) else False,
            'from': hour(v.get('from'), 22), 'to': hour(v.get('to'), 7)}


def clock_hour():
    return time.localtime().tm_hour


def mood(s, hour=None):
    """None (schedule off), 'night' or 'day'. Night runs from `from` to `to`, past midnight if from > to."""
    sch = s['schedule']
    if not sch['on']:
        return None
    h = clock_hour() if hour is None else hour
    a, b = sch['from'], sch['to']
    night = h >= a or h < b if a > b else a <= h < b
    return 'night' if night else 'day'

# who is on the desk: settings['roster'] = {character: how many}; '' is the default blob
def clean_roster(v, character, pets):
    """Valid entries only, 10 pets at most. Settings from before multi-character derive it from character + pets."""
    name_ok = lambda k: isinstance(k, str) and (k == '' or re.fullmatch(r'[\w\- ]{1,40}', k))
    if not isinstance(v, dict):
        return {character: pets} if pets else {}
    out, room = {}, 10
    for k, n in v.items():
        if name_ok(k) and isinstance(n, int) and not isinstance(n, bool) and n > 0 and room > 0:
            out[k] = min(n, room)
            room -= out[k]
    return out


def set_total(s, total):
    """Home's Pets stepper: the main character gains pets first and loses them first, then the others."""
    r, main = dict(s['roster']), s['character']
    total = max(0, min(10, total))
    cur = sum(r.values())
    if total > cur:
        r[main] = r.get(main, 0) + total - cur
    else:
        for ch in [main] + [k for k in reversed(list(r)) if k != main]:
            take = min(r.get(ch, 0), cur - total)
            r[ch] = r.get(ch, 0) - take
            cur -= take
    s['roster'] = {k: v for k, v in r.items() if v > 0}
    s['pets'] = sum(s['roster'].values())

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
# app icon; bundled next to the code (PyInstaller unpacks data files into sys._MEIPASS)
LOGO = os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))), 'logo.ico')


def logo_image(size=256, color=DEFAULTS['color']):
    """The default blob as a square RGBA picture: app icon, tray icon, title bar logo.
    logo.ico is made from it: python -c "import pet; pet.save_logo()" """
    from PIL import Image, ImageDraw
    k = size * 4 / 64  # draw 4x bigger on a 64-unit grid, then shrink for smooth edges
    img = Image.new('RGBA', (size * 4, size * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    at = lambda *xy: [v * k for v in xy]
    line = max(1, round(2.5 * k))
    d.ellipse(at(15, 49, 28, 60), fill=LINE)  # feet
    d.ellipse(at(36, 47, 49, 58), fill=LINE)
    d.ellipse(at(5, 8, 59, 57), fill=color, outline=LINE, width=line)
    for x in (24, 40):
        d.ellipse(at(x - 3.5, 26, x + 3.5, 34), fill=LINE)  # eyes
    d.arc(at(26, 30, 38, 42), 25, 155, fill=LINE, width=line)  # smile
    for x in (15, 49):
        d.ellipse(at(x - 4.5, 36, x + 4.5, 42), fill=CHEEK)
    return img.resize((size, size), Image.LANCZOS)


def save_logo(path=None):
    logo_image(256).save(path or LOGO, sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])


# --- settings ---
def is_hex(v):
    return isinstance(v, str) and len(v) == 7 and v[0] == '#' and all(c in '0123456789abcdefABCDEF' for c in v[1:])


def load_settings(path=None):
    """Saved settings over defaults. Anything missing, mistyped or out of range falls back to its default."""
    s = dict(DEFAULTS, chars={}, schedule=clean_schedule(None), roster=dict(DEFAULTS['roster']))
    try:
        with open(path or SETTINGS_FILE, encoding='utf-8') as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return s
    if not isinstance(saved, dict):
        return s
    num = lambda lo, hi: lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi
    checks = {
        'color': is_hex,
        'speed': num(0.5, 3), 'size': num(0.5, 2.5),
        'pets': lambda v: num(0, 10)(v) and v == int(v),
        'monitors': lambda v: isinstance(v, list) and all(isinstance(m, str) for m in v),
        'character': lambda v: isinstance(v, str) and re.fullmatch(r'[\w\- ]{0,40}', v),  # a pack folder name, never a path
        'style': lambda v: v in BLOB_STYLES,
        'theme': lambda v: v in THEMES,
        'accent': lambda v: v == '' or is_hex(v),
        'font': lambda v: isinstance(v, str) and 0 < len(v) <= 60,
        'off': lambda v: isinstance(v, list) and all(a in ACTIONS for a in v),
        'gravity': num(0.5, 2), 'throw': num(0.3, 2), 'damping': num(0.4, 3), 'spin': num(0, 2),  # Settings > Physics
        'advanced': lambda v: isinstance(v, bool),
    }
    for k, ok in checks.items():
        if k in saved and ok(saved[k]):
            s[k] = saved[k]
    s['chars'] = clean_chars(saved.get('chars'))
    s['schedule'] = clean_schedule(saved.get('schedule'))
    if saved.get('character') is True:  # v1.0.3 kept one custom image; it becomes a pack at startup
        s['character'] = '__migrate__'
    s['roster'] = clean_roster(saved.get('roster'), s['character'], int(s['pets']))
    s['pets'] = sum(s['roster'].values())
    return s


def save_settings(s, path=None):
    path = path or SETTINGS_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(s, f, indent=2)
    os.replace(path + '.tmp', path)  # never leave a half-written settings file


def autostart(enable=None):
    """Read (enable=None) or set Windows' 'run at login' entry: the exe, or pythonw + this file when run from source."""
    cmd = (f'"{sys.executable}"' if FROZEN else
           f'"{os.path.join(os.path.dirname(sys.executable), "pythonw.exe")}" "{os.path.abspath(__file__)}"') + ' --startup'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
        if enable:
            winreg.SetValueEx(k, 'DesktopPet', 0, winreg.REG_SZ, cmd)
        elif enable is False:
            try:
                winreg.DeleteValue(k, 'DesktopPet')
            except FileNotFoundError:
                pass
        try:
            winreg.QueryValueEx(k, 'DesktopPet')
            return True
        except FileNotFoundError:
            return False


# --- monitors ---
class MONITORINFOEX(ctypes.Structure):
    _fields_ = [('cbSize', ctypes.wintypes.DWORD), ('rcMonitor', ctypes.wintypes.RECT),
                ('rcWork', ctypes.wintypes.RECT), ('dwFlags', ctypes.wintypes.DWORD),
                ('szDevice', ctypes.c_wchar * 32)]


MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
user32 = ctypes.windll.user32
user32.MonitorFromPoint.restype = ctypes.c_void_p  # HMONITOR is pointer-sized; default int would truncate it
user32.MonitorFromPoint.argtypes = [ctypes.wintypes.POINT, ctypes.wintypes.DWORD]
user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFOEX)]
user32.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.c_void_p, MONITORENUMPROC, ctypes.c_void_p]


def _monitor_info(h):
    mi = MONITORINFOEX(cbSize=ctypes.sizeof(MONITORINFOEX))
    user32.GetMonitorInfoW(h, ctypes.byref(mi))
    r = mi.rcWork
    return mi.szDevice, (r.left, r.top, r.right, r.bottom)


def monitor_at(x=0, y=0):
    """(name, work area) of the monitor at (x, y). Work area = screen minus taskbar, so pets stand on top of it.
    (0, 0) is always the primary monitor; off-screen points use the nearest monitor."""
    return _monitor_info(user32.MonitorFromPoint(ctypes.wintypes.POINT(int(x), int(y)), 2))  # MONITOR_DEFAULTTONEAREST


def cursor_monitor():
    """(name, work area) of the monitor the mouse pointer is on."""
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return monitor_at(pt.x, pt.y)


def all_monitors():
    """[(name, work area)] of every connected monitor, primary first."""
    found = []
    cb = MONITORENUMPROC(lambda h, dc, rc, data: found.append(_monitor_info(h)) or 1)
    user32.EnumDisplayMonitors(None, None, cb, None)
    primary = monitor_at()
    return sorted(found, key=lambda m: m != primary)


# --- smooth pet windows ---
# A pet window shows a 32-bit picture with real per-pixel transparency (UpdateLayeredWindow).
# The old way (-transparentcolor) could only make pixels fully clear or fully solid: jagged edges.
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [('biSize', ctypes.wintypes.DWORD), ('biWidth', ctypes.wintypes.LONG), ('biHeight', ctypes.wintypes.LONG),
                ('biPlanes', ctypes.wintypes.WORD), ('biBitCount', ctypes.wintypes.WORD),
                ('biCompression', ctypes.wintypes.DWORD), ('biSizeImage', ctypes.wintypes.DWORD),
                ('biXPelsPerMeter', ctypes.wintypes.LONG), ('biYPelsPerMeter', ctypes.wintypes.LONG),
                ('biClrUsed', ctypes.wintypes.DWORD), ('biClrImportant', ctypes.wintypes.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [('BlendOp', ctypes.c_ubyte), ('BlendFlags', ctypes.c_ubyte),
                ('SourceConstantAlpha', ctypes.c_ubyte), ('AlphaFormat', ctypes.c_ubyte)]


gdi32 = ctypes.windll.gdi32
_vp = ctypes.c_void_p  # handles are pointer-sized; ctypes' default int would cut them in half on 64-bit
user32.GetParent.restype = user32.GetDC.restype = _vp
user32.GetParent.argtypes = user32.GetDC.argtypes = [_vp]
user32.ReleaseDC.argtypes = [_vp, _vp]
user32.GetWindowLongW.argtypes = [_vp, ctypes.c_int]
user32.SetWindowLongW.argtypes = [_vp, ctypes.c_int, ctypes.c_long]
user32.UpdateLayeredWindow.argtypes = [_vp, _vp, _vp, _vp, _vp, _vp, ctypes.wintypes.DWORD, _vp, ctypes.wintypes.DWORD]
gdi32.CreateCompatibleDC.restype = gdi32.CreateDIBSection.restype = gdi32.SelectObject.restype = _vp
gdi32.CreateCompatibleDC.argtypes = [_vp]
gdi32.CreateDIBSection.argtypes = [_vp, _vp, ctypes.c_uint, ctypes.POINTER(_vp), _vp, ctypes.wintypes.DWORD]
gdi32.SelectObject.argtypes = [_vp, _vp]
gdi32.DeleteObject.argtypes = gdi32.DeleteDC.argtypes = [_vp]


def show_layered(hwnd, data, w, h, x=None, y=None):
    """Put w x h premultiplied BGRA bytes on a layered window, moving it to (x, y) in the same call
    (moving and redrawing separately made the pet stutter)."""
    screen = user32.GetDC(None)
    mem = gdi32.CreateCompatibleDC(screen)
    bits = _vp()
    bmp = gdi32.CreateDIBSection(screen, ctypes.byref(BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32)),
                                 0, ctypes.byref(bits), None, 0)
    if bmp and bits:
        ctypes.memmove(bits, data, len(data))
        old = gdi32.SelectObject(mem, bmp)
        dst = None if x is None else ctypes.byref(ctypes.wintypes.POINT(int(x), int(y)))
        user32.UpdateLayeredWindow(hwnd, screen, dst, ctypes.byref(ctypes.wintypes.SIZE(w, h)), mem,
                                   ctypes.byref(ctypes.wintypes.POINT(0, 0)), 0,
                                   ctypes.byref(BLENDFUNCTION(0, 0, 255, 1)), 2)  # AC_SRC_ALPHA, ULW_ALPHA
        gdi32.SelectObject(mem, old)
        gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(None, screen)


# --- updates ---
def newer(a, b):
    """True if version string a is newer than b."""
    return tuple(map(int, a.split('.'))) > tuple(map(int, b.split('.')))


def download_update(exe=None):
    """Fetch a newer DesktopPet.exe from GitHub Releases, keep it only if its SHA-256 matches.
    Returns 'latest', 'downloaded' or 'failed'."""
    exe = exe or sys.executable
    try:
        with urllib.request.urlopen(UPDATE_URL + 'latest.json', timeout=10) as r:  # HTTPS, cert-checked
            info = json.loads(r.read(10_000))
        if not newer(info['version'], VERSION):
            return 'latest'
        with urllib.request.urlopen(UPDATE_URL + 'DesktopPet.exe', timeout=120) as r:
            data = r.read(MAX_EXE + 1)
        if len(data) > MAX_EXE or hashlib.sha256(data).hexdigest() != info['sha256'].lower():
            return 'failed'
        part = exe + '.part'
        with open(part, 'wb') as f:
            f.write(data)
        os.replace(part, exe + '.new')  # .new only ever holds a verified file
        return 'downloaded'
    except Exception:
        return 'failed'  # offline, no release yet, bad manifest: keep running this version


def apply_update(exe=None):
    """Swap in a verified DesktopPet.exe.new and start it. True if swapped (caller should exit).
    If Windows refuses to start the new exe (e.g. Smart App Control blocks unsigned files), the old one is put back."""
    exe = exe or sys.executable
    if not os.path.exists(exe + '.new'):
        return False
    try:
        if os.path.exists(exe + '.old'):
            os.remove(exe + '.old')
        os.replace(exe, exe + '.old')  # Windows allows renaming a running exe, not overwriting it
        os.replace(exe + '.new', exe)
    except OSError:
        return False
    try:
        # PYINSTALLER_RESET_ENVIRONMENT: new exe unpacks fresh instead of reusing this process's temp folder.
        # DESKTOPPET_RESTART: new exe waits for this one to exit instead of quitting as a second copy.
        subprocess.Popen([exe], cwd=os.path.dirname(exe),
                         env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1', DESKTOPPET_RESTART='1'))
    except OSError:  # blocked or broken: roll back so the pet keeps working
        os.remove(exe)
        os.replace(exe + '.old', exe)
        return False
    return True


k32 = ctypes.WinDLL('kernel32', use_last_error=True)
k32.CreateMutexW.restype = k32.CreateEventW.restype = k32.OpenEventW.restype = ctypes.c_void_p
SHOW_EVENT = 'DesktopPetShowSettings'  # a second launch sets this; the running app opens its Settings


def single_instance():
    """Hold a named lock for this process's lifetime. False if another copy already runs
    (that copy is told to open its Settings window, so clicking the app again just brings it up)."""
    h = k32.CreateMutexW(None, True, 'DesktopPetSingleInstance')
    if ctypes.get_last_error() != 183:  # not ERROR_ALREADY_EXISTS: we own it
        return True
    wait = 10_000 if os.environ.get('DESKTOPPET_RESTART') else 0
    # 0 = got it, 0x80 = previous owner exited without releasing (also ours now)
    if k32.WaitForSingleObject(ctypes.c_void_p(h), wait) in (0, 0x80):
        return True
    ev = k32.OpenEventW(0x0002, False, SHOW_EVENT)  # EVENT_MODIFY_STATE
    if ev:
        k32.SetEvent(ctypes.c_void_p(ev))
    return False


STEP = 1 / 30  # seconds per movement step
ONCE = ('land', 'fall')  # pack animations that play through once and hold their last picture
FLOOR_STATES = ('walk', 'run', 'idle', 'sit', 'lie', 'dance')
STAND_INS = {'run': ('walk',), 'chase': ('run', 'walk'), 'lie': ('sit',), 'ceiling': ('drag',)}  # pack lacks a state
FREE_FALL = ('TDL', 'Green', 'TCO', 'Orange')  # characters whose plain drops keep full gravity (not the steady fall)


def cursor_pos():
    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.IsIconic.argtypes = user32.IsZoomed.argtypes = [ctypes.c_void_p]
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.DWORD)]
user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.wintypes.RECT)]
ctypes.windll.dwmapi.DwmGetWindowAttribute.argtypes = [ctypes.c_void_p, ctypes.wintypes.DWORD, ctypes.c_void_p,
                                                       ctypes.wintypes.DWORD]
SHELL_CLASSES = {'Progman', 'WorkerW', 'Shell_TrayWnd', 'Shell_SecondaryTrayWnd'}


def active_window():
    """(hwnd, left, top, right) of the window in front, if pets can stand on it (not ours, not minimized,
    maximized or the desktop/taskbar); else None."""
    h = user32.GetForegroundWindow()
    if not h or user32.IsIconic(h) or user32.IsZoomed(h):
        return None
    pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    cls = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(h, cls, 64)
    if pid.value == os.getpid() or cls.value in SHELL_CLASSES:
        return None
    r = ctypes.wintypes.RECT()
    # the visible frame (GetWindowRect includes Windows 10/11's invisible resize borders)
    if ctypes.windll.dwmapi.DwmGetWindowAttribute(h, 9, ctypes.byref(r), ctypes.sizeof(r)):
        user32.GetWindowRect(h, ctypes.byref(r))
    return (h, r.left, r.top, r.right) if r.right - r.left >= 150 else None


class PetWidget(QWidget):
    """The pet's window. Qt never paints it: Pet.draw() hands Windows a finished 32-bit picture
    (per-pixel transparency, moved and redrawn in one call). Qt only delivers the mouse."""

    def __init__(self, pet):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.pet = pet
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setCursor(Qt.PointingHandCursor)
        self.hwnd = int(self.winId())
        ex = user32.GetWindowLongW(self.hwnd, -20)
        user32.SetWindowLongW(self.hwnd, -20, ex | 0x80000 | 0x80)  # WS_EX_LAYERED (invisible until drawn), TOOLWINDOW

    def paintEvent(self, e):
        pass  # the layered window shows Pet.draw()'s picture

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.pet.grab()
        elif e.button() == Qt.RightButton:
            self.pet.menu()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton and self.pet.state in ('drag', 'hang'):
            self.pet.drag()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.pet.state in ('drag', 'hang'):
            self.pet.drop()


class Pet:
    def __init__(self, app, char=''):
        self.app, self.alive, self.char = app, True, char  # char: its character pack's name, '' = blob
        self.win = PetWidget(self)
        self.shown = {}  # picture -> its prepared bytes
        self.resize()
        self.area = L, T, R, B = random.choice(app.allowed_areas())  # start on a monitor allowed in Settings
        self.x, self.y = random.randint(L, max(L, R - self.px)), T
        self.vx = self.vy = 0
        self.spin = self.spin_v = 0  # degrees, degrees per step: tumble in the air after a throw
        self.th = self.om = 0.0  # radians, radians/s: swing about the held hand or foot (0: hanging straight down)
        self.lean, self.pose = 0.0, None  # held by the hand: the shown picture's own body angle; (picture, when)
        self.sparks = []  # Yellow's staff fall: sparkles off the gem, [x, y, vx, vy, life]
        self.ledge = None  # the window this pet stands on, as (hwnd, left, top, right)
        self.dir = random.choice((-1, 1))
        self.frame = 0       # physics steps (30 a second): drives sprite animation and timers
        self.t = 0.0         # seconds alive, continuous: drives the blob's smooth motion
        self.prev = (self.x, self.y)
        self.acc, self.last = 0.0, time.perf_counter()
        self.set('fall')
        if app.visible:
            self.win.show()

    def set(self, state, timer=None, leap=False):
        """leap: a throw or a jump (the pack's leap poses in the air); any other fall is a plain drop."""
        self.state, self.timer, self.leap = state, timer or random.randint(40, 200), leap
        if state == 'sit':  # sitting down at the laptop: a fresh terminal, from the first line
            self.__dict__.pop('term', None)
        self.since = getattr(self, 'frame', 0)  # pack animations start from their first picture

    def land(self, hard=False, full=False, slow=1):
        """Touched down. Packs: a soft landing plays the second half of the landing animation (crouch, stand); a
        hard one crashes face down (its first picture) with a tiny hop, lies a moment, then plays all of it (crawl
        up, stand). full: all of it now. slow: played that many times slower. Blob: quick squash."""
        frames = self.pack[0] if self.pack else None
        self.land_slow = slow
        if frames is None:
            self.set('land', 6)
        elif hard and 'land' in frames and self.char == 'Orange':  # by name: his landing pictures, all evenly timed
            return self.land(full=True)
        elif hard and 'land' in frames:
            self.set('crash', 22)
            self.vy = -3.5  # the body thumps the floor and lifts a few px
        elif 'land' in frames:
            ticks = round(len(frames['land'][0]) * 30 / self.pack[1] * slow)
            skip = 0 if full else ticks // 2
            self.set('land', max(1, ticks - skip + (3 if slow > 1 else 0)))  # a slow landing holds its end a moment
            self.since = self.frame - skip  # start partway through
        else:
            self.set('idle')

    def resize(self):
        self.pack, self.pack_scale = self.app.get_pack(self.char)
        self.px = int(pet_px(self.app.settings) * (self.pack_scale if self.pack else 1))
        if self.char == 'Orange' and self.pack:  # load his get-up pictures now, not mid-landing (no hitch)
            self.getup_frames()
        self.shown.clear()

    # --- mouse (screen pixels from Windows, the same units as the pet's position) ---
    def body(self):
        """Where the visible pet sits on its square: (left, top, right, bottom), from the picture's solid pixels."""
        img = self.picture()
        l, t, r, b = img.getbbox() or (0, 0, img.width, img.height)
        dx, dy = (self.px - img.width) // 2, 0 if self.state == 'ceiling' else self.px - img.height
        return l + dx, t + dy, r + dx, b + dy

    def grab(self):
        """Picked up by the feet: hangs upside down by them. Anywhere else: reaches up and holds the pointer
        with its hand (the top of the 'held' picture). Either way that spot sits right on the pointer."""
        mx, my = cursor_pos()
        self.trail = [(time.perf_counter(), mx, my)]  # recent pointer positions, for the throw
        l, t, r, b = self.body()
        leg = self.state != 'ceiling' and my - self.y > t + 0.72 * (b - t)
        self.vx = self.vy = self.spin = self.spin_v = self.om = 0
        self.th = self.lean = self.calm = 0.0
        self.pose = None  # (picture, when picked) while held by the hand
        self.set('hang' if leg else 'drag')
        px = self.px
        if not self.pack:  # the blob's held foot and raised hand are drawn at known spots (64 px grid)
            self.hx, self.hy = px / 2, px * (5 if leg else 4) / 64
        elif not leg:
            self.held_pose()
        else:  # held upside down by the tip of a foot
            self.leg_pose()
        self.pv, self.pm = (0.0, 0.0), (mx, my)  # smoothed pointer velocity, last pointer position
        self.follow()

    def grip(self, img):
        """Where a held picture's raised hand tip is on the px square, and its arm's lean from straight down
        under that hand (radians, + = body to the right). Measured once per picture."""
        cache = self.app.__dict__.setdefault('grips', {})
        key = (id(img), self.px)
        if key not in cache:
            raw, w = img.getchannel('A').tobytes(), img.width
            solid = [(i % w, i // w) for i in range(len(raw)) if raw[i] > 128] or [(0, 0)]
            cx, cy = sum(p[0] for p in solid) / len(solid), sum(p[1] for p in solid) / len(solid)
            # the raised hand's tip: the solid point in the top half furthest from the body's middle (the head
            # can be the highest point, but it sits close to the middle)
            upper = [p for p in solid if p[1] < cy] or solid
            far = max(upper, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
            tip = [p for p in upper if abs(p[0] - far[0]) <= 3 and abs(p[1] - far[1]) <= 3]
            hx, hy = sum(p[0] for p in tip) / len(tip), sum(p[1] for p in tip) / len(tip)
            dx, dy = (self.px - img.width) // 2, self.px - img.height
            # does the arm reach up to that hand? the solid pixels a short way from the tip, as a direction
            k = img.width / 128
            arm = [p for p in solid if 10 * k <= math.dist(p, (hx, hy)) <= 22 * k] or [(hx, hy + 1)]
            ax, ay = sum(p[0] for p in arm) / len(arm) - hx, sum(p[1] for p in arm) / len(arm) - hy
            lean = math.atan2(ax, ay)  # the arm is the rope: it is what lines up with the swing
            up = abs(math.degrees(lean)) < 50  # the arm runs down from the hand, not sideways
            cache[key] = hx + dx, hy + dy, lean, up
        return cache[key]

    def foot(self, img):
        """Where a picture's lowest foot tip ends up on the px square once the picture is turned upside down."""
        cache = self.app.__dict__.setdefault('feet', {})
        key = (id(img), self.px)
        if cache.get(key, (None,))[0] is not img:  # keyed by the picture itself (ids get reused)
            a = img.getchannel('A')
            l, t, r, b = a.getbbox() or (0, 0, img.width, img.height)
            xs = [x for y in range(b - 4, b) for x in range(l, r) if a.getpixel((x, y)) > 128] or [(l + r) / 2]
            low = [x for x in xs if abs(x - xs[len(xs) // 2]) <= 6]
            dx, dy = (self.px - img.width) // 2, self.px - img.height
            # the picture is turned 180 degrees in its px square, so the foot's spot is mirrored both ways
            cache[key] = img, (self.px - 1 - (dx + sum(low) / len(low)), self.px - 1 - (dy + b - 3))
        return cache[key][1]

    def getup_frames(self):
        """(right, left) get-up pictures for Orange: Yellow's landing pictures after the first (push up, kneel,
        stand), recoloured in Orange's own colour and sized like his pictures. None if Yellow's pack is missing."""
        from collections import Counter
        from PIL import Image, ImageChops, ImageDraw, ImageFilter
        cache = self.app.__dict__.setdefault('getups', {})
        mine = self.pack[0]['idle'][0][0]
        key = (id(mine), self.px)
        if cache.get(key, (None,))[0] is not mine:  # keyed by the picture itself (ids get reused)
            yellow = self.app.get_pack('Yellow')[0]
            out = None
            if yellow and 'land' in yellow[0]:
                raw = mine.tobytes()
                col = Counter(raw[i:i + 3] for i in range(0, len(raw), 4) if raw[i + 3] > 200).most_common(1)
                col = tuple(col[0][0]) if col else (255, 140, 30)
                pairs = []
                for side in (0, 1):
                    seq = []
                    for p_ in yellow[0]['land'][side]:
                        if not any(p_ is q for q in seq):
                            seq.append(p_)
                    pics = []
                    w_ = max(3, round(6.5 * p_.width / 128)) if seq else 3  # line width
                    # Orange's own head (a ring), cut from his standing picture
                    ma = mine.getchannel('A')
                    ml, mt, mr, mb = ma.getbbox() or (0, 0, mine.width, mine.height)
                    rows = [(y, [x for x in range(ml, mr) if ma.getpixel((x, y)) > 128]) for y in range(mt, mt + (mb - mt) // 3)]
                    widest = max(rows, key=lambda r: (r[1][-1] - r[1][0]) if r[1] else 0)
                    R = (widest[1][-1] - widest[1][0] + 1) / 2 if widest[1] else 10
                    hx0 = (widest[1][-1] + widest[1][0]) / 2 if widest[1] else mine.width / 2
                    # cut a little wide (so the bottom of the ring isn't sliced flat), then trimmed to a circle
                    m_ = 3
                    his_head = mine.crop((round(hx0 - R - m_), mt - m_, round(hx0 + R + m_), round(mt + 2 * R + m_)))
                    ring = Image.new('L', his_head.size, 0)
                    ImageDraw.Draw(ring).ellipse((m_ - 1.5, m_ - 1.5, his_head.width - m_ + 1.5, his_head.height - m_ + 1.5), fill=255)
                    his_head.putalpha(ImageChops.multiply(his_head.getchannel('A'), ring))
                    for p_ in seq[1:]:
                        a = p_.getchannel('A')
                        # Yellow's head is a smaller solid disc: find it (the only part thicker than a line), clear
                        # it, and put Orange's own ring head in its place
                        inner = a.point(lambda v: 255 if v > 128 else 0).filter(ImageFilter.MinFilter(2 * w_ + 1))
                        ib = inner.getbbox()
                        pic = Image.new('RGBA', p_.size, col + (255,))
                        if ib:
                            icx, icy = (ib[0] + ib[2]) / 2, (ib[1] + ib[3]) / 2
                            rr = (ib[2] - ib[0]) / 2 + w_ + 5  # Yellow's head radius, its soft edge included
                            a = a.copy()
                            ImageDraw.Draw(a).ellipse((icx - rr, icy - rr, icx + rr, icy + rr), fill=0)
                            pic.putalpha(a)
                            pic.alpha_composite(his_head, (round(icx - his_head.width / 2), round(icy - his_head.height / 2)))
                        else:
                            pic.putalpha(a)
                        if pic.size != mine.size:  # his pictures may be fitted to a different size
                            k = mine.height / pic.height
                            pic = pic.resize((round(pic.width * k), mine.height), Image.LANCZOS)
                        pics.append(pic)
                    pairs.append(pics)
                out = tuple(pairs) if pairs[0] else None
            cache[key] = mine, out
        return cache[key][1]

    def leg_pose(self):
        """Held by the leg: the pack's monkey-bar frames that hang from a raised arm, turned upside down, so an
        arm hangs and the free leg angles off the held one. The swing picks among them (choppy on purpose): one
        end of the row swinging one way, the other end the other way, the middle hanging still."""
        frames = self.pack[0]
        side = 1 if self.dir < 0 else 0
        pics = [p for p in {id(p): p for p in frames.get('ceiling', ([], []))[side]}.values() if self.grip(p)[3]]
        pics = pics or [frames['drag'][side][0]]
        n = len(pics)
        i = n // 2 if abs(self.om) < 0.4 else max(0, min(n - 1, int((self.om + 3) / 6 * n)))
        now = time.perf_counter()
        best = pics[i]
        if getattr(self, 'lpose', None) is None or (best is not self.lpose[0] and now - self.lpose[1] > 0.12):
            self.lpose = best, now
        img = self.lpose[0]
        if self.char == 'TCO':  # shortcut, by name: the fire from his held picture's hand
            img = with_hand_fire(img, frames['drag'][side][0], self)
        self.hx, self.hy = self.foot(img)
        self.lean = 0.0
        return img

    def held_pose(self):
        """Held by the hand: the pack's monkey-bar frames (swing) show its body at many angles under one raised
        hand, so show the one nearest the real swing angle (turning only the rest), facing the way it swings.
        Hanging still: the plain held picture (pinch). Sets the picture's hand tip as the grip."""
        frames = self.pack[0]
        if abs(self.om) > 1.5:  # swinging hard one way: faces that way
            self.dir = 1 if self.om > 0 else -1
        side = 1 if self.dir < 0 else 0
        still = abs(self.om) < 0.4 and abs(self.th) < 0.15
        pics = frames['drag'][side] if still or 'ceiling' not in frames else frames['ceiling'][side]
        uniq = lambda ps: [p for p in {id(p): p for p in ps}.values() if self.grip(p)[3]]  # hanging from a raised arm
        # (a pack whose held picture has no raised arm, like TDL's, hangs still in its monkey-bar frames instead)
        pics = uniq(pics) or uniq(frames.get('ceiling', ([], []))[side]) or list({id(p): p for p in pics}.values())
        want = self.th + 0.15 * self.om  # a touch ahead of the swing, like a body leading with its legs
        best = min(pics, key=lambda p: abs(self.grip(p)[2] - want))
        now = time.perf_counter()
        if self.pose is None or (best is not self.pose[0] and now - self.pose[1] > 0.1):  # no flicker
            self.pose = best, now
        self.hx, self.hy, self.lean, _ = self.grip(self.pose[0])
        return self.pose[0]

    def follow(self, dt=0.0):
        """Held: the hand or foot sits on the pointer and the body swings below it like a pendulum, pushed by
        the pointer's acceleration (move fast and it lags and wobbles; stop and it swings back and settles)."""
        mx, my = cursor_pos()
        now = time.perf_counter()
        self.trail = [p for p in self.trail if now - p[0] < 0.1] + [(now, mx, my)]
        if dt > 0:
            a = 1 - math.exp(-dt / 0.04)  # smooth the pointer: mouse moves arrive in uneven jumps
            vx = self.pv[0] + ((mx - self.pm[0]) / dt - self.pv[0]) * a
            vy = self.pv[1] + ((my - self.pm[1]) / dt - self.pv[1]) * a
            g, length = self.g / STEP ** 2, self.px * 0.6  # px/s^2; pivot to the body's swing centre
            # a flick swings it hard (whirl the pointer to swing it right round); a jump of the pointer can't
            ax, ay = (max(-6 * g, min(6 * g, (v - p) / dt)) for v, p in zip((vx, vy), self.pv))
            self.pv, self.pm = (vx, vy), (mx, my)
            n = max(1, int(dt / 0.004))  # small sub-steps keep the swing stable
            for _ in range(n):
                al = (-(g - ay) * math.sin(self.th) - ax * math.cos(self.th)) / length - 2.5 * self.app.settings['damping'] * self.om
                self.om += al * dt / n
                self.th = (self.th + self.om * dt / n + math.pi) % (2 * math.pi) - math.pi  # can go right round
            # held still a while: kicks to get free now and then (the swing then plays out on its own)
            self.calm = self.calm + dt if abs(self.om) < 0.3 and math.hypot(vx, vy) < 60 else 0.0
            if self.calm > 1.5 and random.random() < dt * 0.7:
                self.om += random.choice((-1, 1)) * random.uniform(1.5, 2.5)
                self.calm = 0.0
        if self.state == 'drag' and self.pack:
            self.held_pose()
        elif self.state == 'hang' and self.pack:
            self.leg_pose()
        self.x, self.y = self.prev = mx - self.hx, my - self.hy

    def drag(self):
        self.follow()
        self.draw()  # follow the pointer at once, not on the next frame

    def drop(self):
        # throw with the pointer's real speed over its last 0.1 s (one jittery event no longer decides it)
        t0, x0, y0 = self.trail[0]
        t1, x1, y1 = self.trail[-1]
        dt = max(t1 - t0, 1 / 60)
        if time.perf_counter() - t1 > 0.08:  # held still before letting go: just drop
            x1, y1 = x0, y0
        k = self.app.settings['throw']  # Throw power slider
        lim = 25 * max(1, k)
        self.vx = max(-lim, min(lim, (x1 - x0) / dt * STEP * k))  # px per movement step
        self.vy = max(-lim, min(lim, (y1 - y0) / dt * STEP * k))
        # let go: keeps its swing as spin, and a throw rolls it the way it was thrown (right: clockwise)
        self.spin = math.degrees(self.th) + (180 if self.state == 'hang' else 0)
        self.spin_v = max(-25, min(25, math.degrees(self.om) * STEP - self.vx * (0.6 if self.state == 'hang' else 0.3)))
        self.spin_v *= self.app.settings['spin']  # Spin speed slider
        thrown = math.hypot(self.vx, self.vy) / k > 4
        if not thrown:  # let go without a throw: a plain, upright drop
            self.spin = self.spin_v = 0
        self.update_area()  # dropped on another monitor: live there
        self.set('fall', leap=thrown)

    def update_area(self):
        """Live on the monitor under the pet; if Settings turned that monitor off, hop to an allowed one."""
        name, area = monitor_at(self.x + self.px // 2, self.y + self.px // 2)
        if self.app.allowed(name):
            self.area = area
            return
        self.area = L, T, R, B = random.choice(self.app.allowed_areas())
        self.x, self.y = random.randint(L, max(L, R - self.px)), T
        self.set('fall')

    @property
    def g(self):
        """Gravity per step: the built-in value times the Gravity slider."""
        return GRAVITY * self.app.settings['gravity']

    def opt(self, key):
        return char_opt(self.app.settings, self.char, key)

    def laptop(self):
        """Yellow sits and codes at his laptop."""
        return bool(self.pack) and self.char == 'Yellow'

    def menu(self):
        m = QMenu()
        m.setStyleSheet(self.app.menu_qss())
        m.addAction('Settings...', self.app.open_settings)
        m.addAction('Add pet', self.app.add)
        m.addAction('Remove this pet', lambda: self.app.remove(self))
        m.addSeparator()
        m.addAction('Quit', self.app.quit)
        m.exec(QCursor.pos())

    # --- behaviour ---
    def step(self):
        if self.state == 'sit' and self.laptop():
            self.term_step()
        L, T, R, B = self.area
        px, speed = self.px, self.app.settings['speed']
        floor, s = B - px, self.state
        self.timer -= 1
        cx = self.x + px / 2
        w = self.app.win  # active window: (hwnd, left, top, right) or None
        if self.ledge:  # standing on a window: it is the floor, its width is the walkway; ride along if it moves
            if not w or w[0] != self.ledge[0] or w[2] - px < T:
                self.ledge = None
                if s not in ('fall', 'drag'):
                    self.set('fall')
            else:
                self.x += w[1] - self.ledge[1]
                self.y += w[2] - self.ledge[2]
                self.ledge = w
                L, R, floor = w[1], w[3], w[2] - px
        if s == 'fall':
            bottom = self.y + px
            # shortcut: Yellow's fall pictures ride a staff, by name: sparkles fly off it, and he always lands softly
            staff = self.pack and not self.leap and self.char == 'Yellow'
            # a plain drop falls at a steady 10 px a step; throws keep gravity, and so do these characters
            # (by name), always
            if not self.leap and self.vy >= 0 and self.opt('fall') == 'steady':
                self.vy = min(self.vy + self.g, 10)
            else:
                self.vy += self.g
            if staff:  # sparkles fly off the gem, left behind as he comes down
                self.sparks = [[x + vx, y + vy, vx, vy, life - 1] for x, y, vx, vy, life in self.sparks if life > 1]
                if random.random() < 0.7:  # x is away from the rider (the side is set when drawn), y is up
                    self.sparks.append([0.0, 0.0, random.uniform(0.2, 1.6), -random.uniform(1.0, 2.6), 16])
            self.x += self.vx
            self.y += self.vy
            if not L <= self.x <= R - px:  # hit a screen edge: bounce off it, the knock flips the spin
                self.x = max(L, min(R - px, self.x))
                self.spin_v = max(-15, min(15, -self.spin_v * 0.6 + self.vx * 0.5))
                self.vx = -self.vx * 0.5
            cx = self.x + px / 2
            if (w and not self.ledge and self.vy > 0 and w[1] <= cx <= w[3] and bottom <= w[2] <= self.y + px
                    and w[2] - px > T):  # dropping past a window's top edge: land on it
                self.ledge, floor = w, w[2] - px
            if self.spin or self.spin_v:  # tumbling the way it was thrown: full turns, only air drag slows it
                self.spin = (self.spin + self.spin_v + 180) % 360 - 180
                self.spin_v *= 0.985
            if self.y >= floor:
                self.y = floor
                # how it meets the floor: sideways or upside down, or from high up (the crash height, 600 px by
                # default: the speed a free fall reaches over that drop) = a crash; never off the staff
                tdl = self.pack and not self.leap and self.char == 'TDL'  # by name
                hard = not (staff or tdl) and (self.vy > (2 * self.g * self.opt('crash')) ** 0.5 or abs(self.spin) > 50)
                self.sparks = []
                self.vx, self.vy, self.spin, self.spin_v = 0, 0, 0, 0
                if tdl:  # TDL's landing: the whole thing, slow, so it lands with weight
                    self.land(full=True, slow=1.2)
                else:
                    self.land(hard)
        elif s == 'land':
            if self.timer <= 0:
                # Orange (by name): his landing ends lying in the water, so he gets up: Yellow's get-up pictures
                # (push up, kneel, stand), recoloured orange (his own pack has none; his lie picture is on a bed)
                getup = self.char == 'Orange' and self.getup_frames()
                self.set('getup', 15) if getup else self.set('idle')
        elif s == 'getup' and self.timer <= 0:
            self.set('idle')
        elif s == 'crash':  # face down after a hard landing: a little hop off the floor, then lies still
            if self.vy:
                self.y += self.vy
                self.vy += self.g
                if self.y >= floor:
                    self.y, self.vy = floor, 0
            if self.timer <= 0:
                self.land(full=True)
        elif s in ('walk', 'run'):
            self.x += (2 if s == 'walk' else 4) * speed * self.dir
            if s == 'run' and random.random() < 0.004 and 'lie' not in self.app.settings['off']:  # tripped over its own feet
                self.set('lie', 45)
            if not L <= self.x <= R - px:
                self.x = max(L, min(R - px, self.x))
                if self.ledge:  # end of the window: sit on the edge, or hop off
                    if random.random() < 0.5:
                        self.set('sit')
                    else:
                        self.ledge, self.vx, self.vy = None, self.dir * 3, -6
                        self.set('fall')
                elif random.random() < 0.5 and 'climb' not in self.app.settings['off']:
                    self.set('climb')
                else:
                    self.dir = -self.dir
        elif s == 'climb':
            self.y -= 2 * speed
            if self.y <= T:  # reached the top: grab the top edge and swing along it, away from the wall
                self.y, self.dir = T, -self.dir
                self.set('ceiling')
            elif self.timer <= 0 and random.random() < 0.004:  # now and then a tired climber lets go
                self.vx, self.vy = -self.dir * 3, -4
                self.set('fall')
        elif s == 'ceiling':  # monkey bars across the top of the screen
            self.y = T
            self.x += 2.5 * speed * self.dir
            if not L <= self.x <= R - px:  # reached the far side: drop down
                self.x = max(L, min(R - px, self.x))
                self.set('fall')
            elif self.timer <= 0 and random.random() < 0.006:
                self.set('fall')
        if s in FLOOR_STATES and self.timer <= 0:
            self.next_move(w, cx)

    def next_move(self, w, cx):
        """Pick what to do next while standing around."""
        L, T, R, B = self.area
        off = self.app.settings['off']
        weights = MOOD_WEIGHTS.get(mood(self.app.settings), BASE_WEIGHTS)
        pick = lambda wt: [m for m, n in wt.items() if m != 'jump' for _ in range(n) if m not in off]
        choices = pick(weights) or pick(BASE_WEIGHTS)  # everything the mood likes is switched off: plain weights
        if (w and not self.ledge and 'jump' not in off and w[2] < self.y and w[3] - w[1] > self.px * 2
                and w[1] < R - self.px and w[3] > L + self.px):  # only windows on this pet's screen
            choices += ['jump'] * weights['jump']
        move = random.choice(choices)
        if move == 'jump':  # leap up onto the active window's top edge
            h = self.y + self.px - w[2]
            if 0 < h < 700:
                self.vy = -((2 * self.g * (h + 30)) ** 0.5)
                t = (-self.vy + max(0, self.vy ** 2 - 2 * self.g * h) ** 0.5) / self.g
                target = min(max(cx, w[1] + self.px, L + self.px), w[3] - self.px, R - self.px)
                self.vx = max(-25, min(25, (target - cx) / max(t, 1)))
                self.set('fall', leap=True)
                return
            move = 'idle'
        # Yellow (by name) codes on his laptop for 30-50 s (until picked up)
        self.set(move, random.randint(900, 1500) if move == 'sit' and self.laptop() else None)
        if move in ('walk', 'run'):
            self.dir = random.choice((-1, 1))

    def tick(self):
        """About 60 frames a second. Movement is worked out in fixed 1/30 s steps (so speeds stay the same and
        Tk's uneven timer can't speed it up or slow it down); in between, the drawn position glides from the last
        step to the next one."""
        if not self.alive:
            return
        now = time.perf_counter()
        dt, self.last = min(0.1, now - self.last), now
        self.t += dt
        x, y = self.x, self.y
        if self.state in ('drag', 'hang'):
            self.acc = 0.0
            self.follow(dt)
            x, y = self.x, self.y
        else:
            self.acc += dt
            while self.acc >= STEP:
                self.prev = (self.x, self.y)
                self.frame += 1
                self.step()
                self.acc -= STEP
            a = self.acc / STEP
            x = self.prev[0] + (self.x - self.prev[0]) * a
            y = self.prev[1] + (self.y - self.prev[1]) * a
        self.draw(x, y)

    def picture(self):
        """This tick's PIL picture of the pet."""
        d, f, s = self.dir, self.frame, self.state
        if s == 'hang' and self.pack:  # held by the leg: a pack's struggle animation, turned upside down when drawn
            s = 'drag'
        if s == 'dance':  # turn to and fro to the beat
            d = 1 if f // 12 % 2 else -1
        if self.pack:  # character pack: that state's animation (or a stand-in), mirrored when facing left
            frames, fps = self.pack
            if self.state == 'drag':
                return self.pose[0] if getattr(self, 'pose', None) else self.held_pose()
            if self.state == 'hang':
                return self.leg_pose()
            if (s == 'fall' and not self.leap and self.char == 'TDL'
                    and 'fall' in frames):  # by name: his fall picture is drawn stretched tall; shown at 75% height
                img = frames['fall'][1 if d < 0 else 0][0]
                return unstretched(img, self.app)
            if s == 'fall' and self.leap and 'ceiling' in frames:  # thrown or jumping: the leap poses (swing)
                s = 'ceiling'
            if s == 'crash' and 'land' in frames:  # crashed: face down, the landing animation's first picture
                return frames['land'][1 if d < 0 else 0][0]
            if s == 'getup':  # getting up from the floor: three pictures, a sixth of a second each
                pics = self.getup_frames()[1 if d < 0 else 0]
                return pics[min(len(pics) - 1, (f - self.since) // 5)]
            pair = next((frames[k] for k in (s,) + STAND_INS.get(s, ()) if k in frames), frames['idle'])
            seq = pair[1] if d < 0 else pair[0]
            i = int((f - self.since) * fps / 30 / (getattr(self, 'land_slow', 1) if s == 'land' else 1))
            img = seq[min(i, len(seq) - 1) if s in ONCE else i % len(seq)]
            return img
        step = 0
        if s in ('walk', 'climb', 'ceiling', 'run', 'chase', 'dance', 'hang'):
            period = 0.2 if s in ('run', 'chase') else 0.3 if s == 'hang' else 0.34  # seconds per stride / flail
            phase = int(self.t % period / period * 12)  # 12 poses per stride, drawn once each and reused
            step = round(3 * math.sin(2 * math.pi * phase / 12), 1)
        blink = f % 100 < 4 or s == 'sit' and f % 200 < 100 or s == 'lie'
        st = self.app.settings
        return self.app.blob_frame(s, 1 if d > 0 else -1, step, blink, st['style'], st['color'], self.px)

    def draw(self, x=None, y=None):
        if not self.win.isVisible():
            return
        img = self.picture()
        if self.state == 'sit' and self.laptop():
            return self.draw_desk(x, y)
        if self.state == 'fall' and self.pack and not self.leap and self.char == 'Yellow':
            return self.draw_staff(img, x, y)
        top = self.state == 'ceiling'  # hanging: picture hugs the top edge, not the floor
        hang = self.state == 'hang'
        held = self.state in ('drag', 'hang')
        # turn: swing about the held hand or foot, or tumble in the air about the middle
        turn = (round(math.degrees(self.th - self.lean) / 2) * 2 if held else
                round(self.spin / 4) * 4 % 360 if self.state == 'fall' else 0)
        key = (id(img), top, hang, turn, (round(self.hx), round(self.hy)) if held else None)
        shown = self.shown.get(key)
        if shown is None:
            from PIL import Image
            px = self.px
            cw = max(px, img.width)  # a picture wider than the square (Yellow's laptop) stays centred on it
            canvas = Image.new('RGBA', (cw, px), (0, 0, 0, 0))
            canvas.alpha_composite(img, ((cw - img.width) // 2, 0 if top else px - img.height))
            if hang:
                canvas = canvas.transpose(Image.Transpose.ROTATE_180)
            dx, dy = -(cw - px) // 2, 0  # where the picture's corner sits, from the pet's position
            if turn:  # room to turn all the way round the pivot, then trimmed to what's drawn
                big = Image.new('RGBA', (3 * px, 3 * px), (0, 0, 0, 0))
                big.paste(canvas, (px, px))
                big = turned(big, turn, center=(self.hx + px, self.hy + px) if held else None)
                l, t, r, b = big.getbbox() or (px, px, px + 1, px + 1)
                canvas, dx, dy = big.crop((l, t, r, b)), l - px, t - px
            # premultiplied, as Windows wants
            shown = canvas.convert('RGBa').tobytes('raw', 'BGRa'), canvas.width, canvas.height, dx, dy
            if len(self.shown) > 600:
                self.shown.clear()
            self.shown[key] = shown
        data, w, h, dx, dy = shown
        show_layered(self.win.hwnd, data, w, h, round(self.x if x is None else x) + dx,
                     round(self.y if y is None else y) + dy)

    # --- Yellow at his laptop (by name): facing you, cross-legged, coding in a little terminal by his head ---
    CODE = (('print("Hello World")', 'Hello World'), ('x = 5', None), ('y = x * 2', None), ('print(y)', '10'),
            ('name = "Yellow"', None), ('print("Hi " + name)', 'Hi Yellow'), ('for i in range(3):', None),
            ('    print(i)', '0 1 2'), ('import random', None), ('print(random.randint(1, 6))', '4'))
    KEYS = 'qwertyuiopasdfghjklzxcvbnm'

    def term_step(self):
        """One 1/30 s step of his typing: a character at an uneven pace (slower after spaces and symbols),
        now and then a wrong key he notices and backspaces, Enter at the end of a line (with its output), short
        breaks between lines, and every few seconds a glance up at what he has typed."""
        t = self.__dict__.setdefault('term', {'lines': [], 'cur': '', 'todo': [], 'wait': 20, 'n': 0,
                                               'glance': 0, 'next_glance': random.randint(90, 180), 'tap': 0,
                                               'idle': 0})
        t['tap'] = max(0, t['tap'] - 1)
        t['idle'] += 1
        t['look'] = max(0, min(3, t.get('look', 0) + (1 if t['glance'] else -1)))  # head eases up / back down
        if t['glance']:
            t['glance'] -= 1
            return
        t['next_glance'] -= 1
        if t['next_glance'] <= 0:  # looks up at the code for a moment, then back down at the laptop
            t['glance'], t['next_glance'] = random.randint(18, 30), random.randint(110, 200)
            return
        if t['wait'] > 0:
            t['wait'] -= 1
            return
        if not t['todo']:  # next line: plan the keystrokes, with the odd typo fixed straight away
            code, out = self.CODE[t['n'] % len(self.CODE)]
            t['n'] += 1
            for ch in code:
                if ch.isalpha() and random.random() < 0.05:
                    t['todo'] += [('key', random.choice(self.KEYS)), ('wait', random.randint(5, 10)), ('back', None)]
                t['todo'].append(('key', ch))
            t['todo'].append(('enter', out))
        act, val = t['todo'].pop(0)
        if act == 'wait':
            t['wait'] = val
            return
        if act == 'key':
            t['cur'] += val
            t['wait'] = random.randint(2, 5) + (random.randint(2, 6) if val in ' ("=:.+' else 0)
        elif act == 'back':
            t['cur'] = t['cur'][:-1]
            t['wait'] = random.randint(3, 6)
        else:  # Enter: the line moves up, its output under it
            t['lines'] += ['> ' + t['cur']] + ([val] if val else [])
            t['lines'] = t['lines'][-3:]
            t['cur'] = ''
            t['wait'] = random.randint(25, 50)
        t['tap'], t['idle'] = 2, 0

    def desk_parts(self):
        """His standing picture (facing you) cut into head, body and arms, sat down on crossed legs (drawn in his
        own yellow and line width), turned to the laptop at his right-front (towards the code), hands on its keys.
        Built at 4x the pet's size so the cuts and turns stay clean, with round joints over the neck and shoulders.
        Returns (base, head, arms, lid, shoulder points, head pivot, head centre, scale k, R), all at 4x."""
        from PIL import Image, ImageDraw
        cache = self.app.__dict__.setdefault('desks', {})
        src_img = self.pack[0]['idle'][0][0]
        key = (id(src_img), self.px)
        if cache.get(key, (None,))[0] is not src_img:  # keyed by the picture itself (ids get reused)
            R = 4
            img = src_img.resize((src_img.width * R, src_img.height * R), Image.BICUBIC)
            k, W, H = img.width / 128, img.width, img.height  # k: 1/128 of the (4x) picture
            l, t, r, b = img.getbbox() or (0, 0, W, H)
            h, cx = b - t, (l + r) / 2
            neck, hip = t + 0.21 * h, t + 0.53 * h
            seat = b - 9 * k
            dy = round(seat - hip)  # sat down: everything above the hips drops by this
            al = img.getchannel('A')
            masks = {n: Image.new('L', img.size, 0) for n in ('head', 'body', 'arm0', 'arm1')}
            mp = {n: m.load() for n, m in masks.items()}
            ap = al.load()
            for yy in range(int(t), int(hip) + 1):
                for xx in range(W):
                    if not ap[xx, yy]:
                        continue
                    n = 'head' if yy < neck else 'body' if abs(xx - cx) <= 3.5 * k else 'arm0' if xx < cx else 'arm1'
                    mp[n][xx, yy] = 255
            part = {}
            for n, m in masks.items():
                pic = Image.new('RGBA', img.size, (0, 0, 0, 0))
                pic.paste(img, (0, 0), m)
                out = Image.new('RGBA', img.size, (0, 0, 0, 0))
                out.alpha_composite(pic.crop((0, 0, W, H - dy)), (0, dy))
                part[n] = out
            hb0 = part['head'].getbbox() or (0, 0, W, H)
            cx = (hb0[0] + hb0[2]) / 2  # from here on, his middle is under his head (the arms widen the picture)
            # hunched over the laptop: head a little forward and down, back curving out behind him
            hunch = Image.new('RGBA', img.size, (0, 0, 0, 0))
            hunch.alpha_composite(part['head'], (round(4 * k), round(1.5 * k)))
            # his head as a clean round circle, the same size and place (the enlarged picture's edge is rough
            # and flat where it was cut from the neck)
            solid_ = hunch.getchannel('A').point(lambda v: 255 if v > 128 else 0)  # the head itself, not its soft edge
            hb_ = solid_.getbbox() or (0, 0, 2, 2)
            r_, hcx = (hb_[2] - hb_[0]) / 2, (hb_[0] + hb_[2]) / 2
            yel = next((c for c in hunch.getdata() if c[3] == 255), (255, 197, 0, 255))
            part['head'] = Image.new('RGBA', img.size, (0, 0, 0, 0))
            ImageDraw.Draw(part['head']).ellipse((hcx - r_, hb_[1], hcx + r_, hb_[1] + 2 * r_), fill=yel)
            col = (255, 197, 0, 255)
            for yy in range(int(neck), int(hip)):  # his own yellow, from the middle of his body
                c = img.getpixel((round(cx), yy))
                if c[3] == 255:
                    col = c
                    break
            lw = 6 * k  # his line width
            big = Image.new('RGBA', img.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(big)

            def stroke(p_, q, w=lw):
                d.line([p_, q], fill=col, width=round(w))
                for x0, y0 in (p_, q):
                    d.ellipse((x0 - w / 2, y0 - w / 2, x0 + w / 2, y0 + w / 2), fill=col)
            k1, k2 = (cx - 21 * k, b - 8 * k), (cx + 21 * k, b - 8 * k)  # knees out to the sides, a little up
            stroke((cx - 2 * k, seat), k1)
            stroke((cx + 2 * k, seat), k2)
            stroke(k2, (cx - 7 * k, b - 3 * k))  # shins crossing in front, feet tucked under the other knee
            stroke(k1, (cx + 7 * k, b - 3 * k))
            hb = part['head'].getbbox() or (0, 0, 1, 1)
            pivot = ((hb[0] + hb[2]) / 2, hb[3])  # where the head sits on the neck
            top_ = (pivot[0], pivot[1] - 4 * k)  # neck and body: one smooth curve, arched back, down to his seat
            spine = [((1 - u) ** 2 * cx + 2 * u * (1 - u) * (cx - 5 * k) + u ** 2 * top_[0],
                      (1 - u) ** 2 * seat + 2 * u * (1 - u) * ((seat + top_[1]) / 2) + u ** 2 * top_[1])
                     for u in (i / 16 for i in range(17))]
            for p0, p1 in zip(spine, spine[1:]):
                stroke(p0, p1, lw)
            shoulders = []
            for n in ('arm0', 'arm1'):  # the shoulder: where the arm meets the top of his body
                alp = part[n].getchannel('A').tobytes()
                pts = [(q % W, q // W) for q in range(0, len(alp), 2) if alp[q] > 128] or [(cx, neck + dy)]
                sh = min(pts, key=lambda q: math.dist(q, (cx, neck + dy + lw)))
                sh = (sh[0] + (lw / 3 if sh[0] < cx else -lw / 3), sh[1] + lw / 3)  # a little inside the arm's end
                shoulders.append(sh)
            caps = Image.new('RGBA', img.size, (0, 0, 0, 0))  # drawn over the arms: rounds off their cut tops
            dc = ImageDraw.Draw(caps)
            for sh in shoulders:
                r_ = lw * 0.62
                dc.ellipse((sh[0] - r_, sh[1] - r_, sh[0] + r_, sh[1] + r_), fill=col)
            base = Image.new('RGBA', img.size)
            base.alpha_composite(big)
            lid = Image.new('RGBA', img.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(lid)
            silver, edge = (200, 203, 208, 255), (128, 131, 138, 255)
            # the laptop up on his lap, turned to his right-front (towards the code): the keyboard deck in front of him,
            # the lid rising from its far edge and leaning back, its silver back and scribbled apple towards you
            dx_ = 10 * k  # out towards his knee, almost hanging off it, so his typing hands show
            deck = [(cx - 2 * k + dx_, b - 8 * k), (cx + 18 * k + dx_, b - 8 * k), (cx + 24 * k + dx_, b - 13 * k),
                    (cx + 4 * k + dx_, b - 13 * k)]
            d.polygon(deck, fill=(150, 153, 160, 255), outline=(110, 113, 120, 255), width=round(1.2 * k))
            lidq = [(cx + 4 * k + dx_, b - 13 * k), (cx + 24 * k + dx_, b - 13 * k), (cx + 30 * k + dx_, b - 36 * k),
                    (cx + 10 * k + dx_, b - 36 * k)]
            d.polygon(lidq, fill=silver, outline=edge, width=round(1.6 * k))
            d.line([lidq[0], lidq[3]], fill=(160, 200, 240, 255), width=round(1.3 * k))  # screen light, his side
            ax, ay, white = sum(q[0] for q in lidq) / 4, sum(q[1] for q in lidq) / 4, (255, 255, 255, 255)
            d.ellipse((ax - 3.2 * k, ay - 2.8 * k, ax + 3.2 * k, ay + 3.4 * k), fill=white)  # the apple
            d.ellipse((ax - 5 * k, ay - 1.4 * k, ax - 1.8 * k, ay + 1.8 * k), fill=silver)  # its bite, facing him
            d.polygon([(ax + .2 * k, ay - 3 * k), (ax + 1.8 * k, ay - 5.8 * k), (ax + 2.6 * k, ay - 5 * k),
                       (ax + .8 * k, ay - 2.8 * k)], fill=white)  # its leaf
            arms = []
            for n, sh in zip(('arm0', 'arm1'), shoulders):  # each arm swung from its shoulder so the hand lands on the keys
                a_ = part[n]
                alp = a_.getchannel('A').tobytes()
                pts = [(q % W, q // W) for q in range(0, len(alp), 3) if alp[q] > 128] or [sh]
                hand = max(pts, key=lambda q: math.dist(q, sh))
                key_ = (cx + (5 if n == 'arm0' else 13) * k, b - 10 * k)  # on the keyboard, behind the lid
                turn = math.degrees(math.atan2(key_[1] - sh[1], key_[0] - sh[0]) - math.atan2(hand[1] - sh[1], hand[0] - sh[0]))
                arms.append(turned(a_, -turn, sh))
            hc = ((hb[0] + hb[2]) / 2, (hb[1] + hb[3]) / 2)
            # his arms as clean lines in his own yellow and width: from his body line
            # down to the keys (hidden behind the lid), so nothing sticks out where an arm turns
            sh_ = spine[13]  # shoulders: high on his curved back
            # far arm, then near arm: shoulder -> elbow (by his side, a little forward) -> hand on the keys
            reach = [(sh_, (sh_[0] + 1 * k, sh_[1] + 17 * k), (cx + 15 * k, b - 12 * k)),
                     (sh_, (sh_[0] + 4 * k, sh_[1] + 16 * k), (cx + 22 * k, b - 12 * k))]
            cache[key] = src_img, base, part['head'], reach, lid, (col, lw), pivot, hc, k, R, caps
        return cache[key][1:]

    def desk_frame(self, dips, look):
        """One picture of him at the laptop (pet size): arms dipped by dips (degrees) as he taps, head tipped up
        by look (0-3) towards the code. Built at 4x and shrunk, cached per pose."""
        from PIL import Image, ImageDraw
        cache = self.app.__dict__.setdefault('desk_frames', {})
        parts = self.desk_parts()
        key = (id(parts[0]), dips, look)
        if key not in cache:
            base, head, reach, lid, (col, lw), pivot, hc, k, R, caps = parts
            im = base.copy()
            d = ImageDraw.Draw(im)
            for (sh, el, key_), dip in zip(reach, dips):  # a keypress: that hand dips a touch, the elbow stays
                end = (key_[0], key_[1] + dip * k)
                d.line([sh, el, end], fill=col, width=round(lw), joint='curve')
                for x0, y0 in (sh, el, end):
                    d.ellipse((x0 - lw / 2, y0 - lw / 2, x0 + lw / 2, y0 + lw / 2), fill=col)
            im.alpha_composite(lid)  # the laptop in front of his arms: his hands are on its keys, behind the lid
            im.alpha_composite(turned(head, -5 + 7 * look / 3, pivot))  # tipped down at the screen; looks up a little
            if len(cache) > 200:
                cache.clear()
            cache[key] = im.resize((im.width // R, im.height // R), Image.LANCZOS)
        return cache[key]

    def draw_desk(self, x, y):
        """Yellow at his laptop: hands tap as he types, head eases up to glance at his code, which appears in a
        little terminal by his head (a blinking underscore when he stops)."""
        from PIL import Image, ImageDraw, ImageFont
        t = self.__dict__.get('term') or {'lines': [], 'cur': '', 'tap': 0, 'glance': 0, 'idle': 0, 'look': 0}
        parts = self.desk_parts()
        hc, k, R = parts[6], parts[7], parts[8]
        hx, hy, k = hc[0] / R, hc[1] / R, k / R
        dips = tuple(1.5 * t['tap'] if (len(t['cur']) + i) % 2 else 0 for i in range(2))  # one hand, then the other
        pic = self.desk_frame(dips, t.get('look', 0))
        px = self.px
        pad, top = px * 2, px // 2  # room to the right for the code, and above for its lines
        im = Image.new('RGBA', (px + 2 * pad, px + top), (0, 0, 0, 0))
        o = pad + (px - pic.width) // 2, top + px - pic.height
        im.alpha_composite(pic, o)
        # the terminal: lines above, the one being typed with its underscore, beside and above his head
        font = self.app.__dict__.get('term_font')
        if font is None:
            try:
                font = ImageFont.truetype('consola.ttf', max(9, round(10.2 * k)))
            except OSError:
                font = ImageFont.load_default()
            self.app.term_font = font
        d = ImageDraw.Draw(im)
        lh = round(13.2 * k)
        tx, ty = o[0] + hx + 15 * k, o[1] + hy - 24 * k
        blink = t['idle'] < 12 or (self.frame // 15) % 2 == 0
        for n, line in enumerate(t['lines']):
            d.text((tx, ty - (len(t['lines']) - n) * lh), line, font=font,
                   fill=(235, 235, 235, 255) if line.startswith('> ') else (150, 220, 150, 255))
        cur = '> ' + t['cur']
        d.text((tx, ty), cur, font=font, fill=(235, 235, 235, 255))
        if blink:
            d.text((tx + d.textlength(cur, font=font), ty), '_', font=font, fill=(255, 255, 255, 255))
        show_layered(self.win.hwnd, im.convert('RGBa').tobytes('raw', 'BGRa'), im.width, im.height,
                     round(self.x if x is None else x) - pad, round(self.y if y is None else y) - top)

    def draw_staff(self, img, x, y):
        """Yellow riding his staff down: his fall picture as drawn, with sparkles streaming off the gem."""
        from PIL import Image, ImageDraw
        px = self.px
        pad = px // 2  # room for sparkles above and beside him
        cache = self.app.__dict__.setdefault('staffs', {})
        key = (id(img), px)
        if cache.get(key, (None,))[0] is not img:  # keyed by the picture itself (ids get reused)
            gem, tip = staff_ends(img)
            ox, oy = pad + (px - img.width) // 2, pad + px - img.height
            base = Image.new('RGBA', (px + 2 * pad,) * 2, (0, 0, 0, 0))
            base.alpha_composite(without_sparkles(img, gem), (ox, oy))  # only the moving sparkles
            cache[key] = img, base, (gem[0] + ox, gem[1] + oy), (1 if gem[0] > tip[0] else -1)
        _, base, (gx, gy), side = cache[key]
        im = base.copy()
        d = ImageDraw.Draw(im)
        k = px / 128
        for sx, sy, _, _, life in self.sparks:  # little four-point stars, shrinking and fading
            cx, cy, r = gx + side * sx * k, gy + sy * k, (1 + life / 6) * k
            col = (255, 255, 255, int(255 * min(1, life / 10)))
            d.line((cx - r, cy, cx + r, cy), fill=col, width=max(1, round(k)))
            d.line((cx, cy - r, cx, cy + r), fill=col, width=max(1, round(k)))
        show_layered(self.win.hwnd, im.convert('RGBa').tobytes('raw', 'BGRa'), im.width, im.height,
                     round(self.x if x is None else x) - pad, round(self.y if y is None else y) - pad)


def staff_ends(img):
    """(gem centre, pole tip) of a staff picture. The staff is the solid pixels that are neither the yellow
    body nor grey/white sparkles; of its two far ends the bulky one is the gem (the command block)."""
    raw, w = img.tobytes(), img.width
    pts = []
    for i in range(0, len(raw), 4):
        r, g, b, al = raw[i], raw[i + 1], raw[i + 2], raw[i + 3]
        if al > 200 and not (r > 200 and g > 140 and b < 90) and max(r, g, b) - min(r, g, b) > 40:
            pts.append((i // 4 % w, i // 4 // w))
    if len(pts) < 10:  # no staff found
        return (w / 2, img.height / 2), (w / 2, img.height)
    k = w / 128  # sizes below are for a 128 px wide picture
    ends = [min(pts), max(pts)]  # leftmost and rightmost staff pixels
    bulk = [sum(1 for p in pts if math.dist(p, e) < 12 * k) for e in ends]
    gem, tip = (ends[0], ends[1]) if bulk[0] > bulk[1] else (ends[1], ends[0])
    near = [p for p in pts if math.dist(p, gem) < 22 * k]
    return (sum(p[0] for p in near) / len(near), sum(p[1] for p in near) / len(near)), tip


def pet_px(settings):
    """On-screen pet size in pixels: base size x size setting x display scaling."""
    return int(SIZE * settings['size'] * DPI_SCALE)


def turned(img, deg, center=None):
    """img turned deg counter-clockwise about center, without dark seams: turning a picture with see-through
    edges mixes in the black of its empty pixels unless it is premultiplied first."""
    from PIL import Image
    if not deg:
        return img
    return img.convert('RGBa').rotate(deg, Image.BICUBIC, center=center).convert('RGBA')


def unstretched(img, app):
    """TDL's fall picture, drawn stretched tall (152 px for a 128 px character): back to his width, 75% height."""
    from PIL import Image
    cache = app.__dict__.setdefault('unstretched', {})
    if cache.get(id(img), (None,))[0] is not img:  # keyed by the picture itself (ids get reused)
        r = max(1.0, img.height / img.width)  # it was fitted by its height, so it came out narrow
        r *= 1.12  # a touch bigger: squashed back to his width alone, he looked smaller than his normal self
        cache[id(img)] = img, img.resize((round(img.width * r), round(img.height * r * 0.75)), Image.LANCZOS)
    return cache[id(img)][1]


def with_hand_fire(img, held, pet_):
    """TCO: img with the fire from his held picture's raised hand put on img's raised hand. The fire is the
    coloured (not black) pixels of the held picture; it keeps its place relative to the hand tip."""
    from PIL import Image
    cache = pet_.app.__dict__.setdefault('fires', {})
    key = (id(img), id(held))
    if cache.get(key, (None, None))[:2] != (img, held):  # keyed by the pictures themselves
        raw = bytearray(held.tobytes())
        body = bytearray(raw)
        for i in range(0, len(raw), 4):
            if max(raw[i:i + 3]) > 90:  # fire: lit pixels
                body[i + 3] = 0
            else:  # body: dark pixels
                raw[i + 3] = 0
        fire = Image.frombytes('RGBA', held.size, bytes(raw))
        body = Image.frombytes('RGBA', held.size, bytes(body))
        px = pet_.px
        hx0, hy0 = pet_.grip(body)[:2]  # his hand tip without the fire (on the px square)
        hx1, hy1 = pet_.grip(img)[:2]
        dx = round((hx1 - (px - img.width) // 2) - (hx0 - (px - held.width) // 2))  # held picture -> img
        dy = round((hy1 - (px - img.height)) - (hy0 - (px - held.height)))
        layer = Image.new('RGBA', img.size, (0, 0, 0, 0))
        layer.paste(fire, (dx, dy), fire)
        out = img.copy()
        out.alpha_composite(layer)
        cache[key] = img, held, body, out
    return cache[key][3]


def without_sparkles(img, gem):
    """The staff picture with its drawn (still) sparkles cleared: grey/white pixels away from the gem
    (whose own screen is light grey)."""
    from PIL import Image
    raw, w, k = bytearray(img.tobytes()), img.width, img.width / 128
    for i in range(0, len(raw), 4):
        r, g, b = raw[i], raw[i + 1], raw[i + 2]
        if raw[i + 3] and min(r, g, b) > 120 and max(r, g, b) - min(r, g, b) < 40                 and math.dist((i // 4 % w, i // 4 // w), gem) > 18 * k:
            raw[i + 3] = 0
    return Image.frombytes('RGBA', img.size, bytes(raw))


class PilCanvas:
    """The bit of a canvas drawing API that draw_blob uses, painted onto a PIL image 4x larger and shrunk,
    so edges come out smooth."""

    def __init__(self, size):
        from PIL import Image, ImageDraw
        self.size, self.k = size, size * 4 / SIZE
        self.img = Image.new('RGBA', (size * 4, size * 4), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def _at(self, pts):
        return [v * self.k for v in pts]

    def _w(self, width):
        return max(1, round(width * self.k))

    def create_oval(self, *xy, fill='', outline='', width=1):
        self.d.ellipse(self._at(xy), fill=fill or None, outline=outline or None, width=self._w(width) if outline else 0)

    def create_rectangle(self, *xy, fill='', outline='', width=1):
        self.d.rectangle(self._at(xy), fill=fill or None, outline=outline or None, width=self._w(width) if outline else 0)

    def create_polygon(self, *pts, fill='', outline='', width=1):
        self.d.polygon(self._at(pts), fill=fill or None, outline=outline or None, width=self._w(width) if outline else 0)

    def create_line(self, *pts, fill='', width=1):
        self.d.line(self._at(pts), fill=fill, width=self._w(width))

    def create_arc(self, *xy, start=0, extent=90, style='arc', outline='', width=1):
        # tk: degrees counter-clockwise from 3 o'clock; PIL: clockwise
        self.d.arc(self._at(xy), -(start + extent), -start, fill=outline, width=self._w(width))

    def image(self):
        from PIL import Image
        return self.img.resize((self.size, self.size), Image.LANCZOS)


def blob_image(size, color, style='Blob', f=50):
    """Smooth size x size picture of the default pet (f=50: eyes open, 0: blinking)."""
    pc = PilCanvas(size)
    draw_blob(pc, color, 'idle', 1, f, 0, style)
    return pc.image()


def draw_blob(c, color, s='idle', d=1, f=0, step=0, style='Blob'):
    """The default pet at 64 px on canvas c: state s, facing d (-1/1), animation frame f, foot step offset,
    style one of BLOB_STYLES (ears, ghost tail)."""
    top = (26 if s in ('sit', 'land') else 34 if s == 'lie' else 20 if s == 'ceiling' else 8 if s == 'hang'
           else 14 + abs(step) * 0.7)
    if s == 'ceiling':  # hanging from the top edge: arms up, one hand forward per step
        c.create_line(24, top + 8, 22 + step, 0, fill=LINE, width=3)
        c.create_line(40, top + 8, 42 - step, 0, fill=LINE, width=3)
    if s == 'drag':  # picked up: one arm reaches up, its hand (top middle) holds the pointer
        c.create_line(42, top + 22, 32, 6, fill=LINE, width=3)
        c.create_oval(28, 0, 36, 8, fill=LINE, outline='')
    if s == 'hang':  # held up by one ankle. Drawn feet-down here; Pet.draw turns it over, so these arms dangle and flail
        for x, hx in ((16, 13 + 2 * step), (48, 51 - 2 * step)):
            c.create_line(x, top + 24, hx, 8, fill=LINE, width=3)
            c.create_oval(hx - 4, 4, hx + 4, 12, fill=LINE, outline='')
    if style == 'Cat':  # ears behind the body
        for x0, x1, x2 in ((12, 18, 28), (36, 46, 52)):
            c.create_polygon(x0, top + 10, x1, top - 8, x2, top + 2, fill=color, outline=LINE, width=2)
    elif style == 'Bunny':
        for x in (20, 44):
            c.create_oval(x - 5, top - 14, x + 5, top + 12, fill=color, outline=LINE, width=2)
            c.create_oval(x - 2, top - 9, x + 2, top + 6, fill=CHEEK, outline='')
    if style == 'Ghost':  # no feet: rounded top, wavy hem
        c.create_oval(8, top, 56, top + 40, fill=color, outline=LINE, width=2)
        c.create_rectangle(9, top + 20, 55, 52, fill=color, outline='')
        c.create_line(8, top + 20, 8, 54, fill=LINE, width=2)
        c.create_line(56, top + 20, 56, 54, fill=LINE, width=2)
        for x in (8, 24, 40):
            c.create_oval(x, 46 - step, x + 16, 60 - step, fill=color, outline='')
    elif s == 'hang':  # held leg straight out the middle, the free foot flopping at the side
        c.create_line(32, top + 36, 32, 58, fill=LINE, width=5)
        c.create_oval(26, 55, 38, 63, fill=LINE, outline='')
        c.create_oval(44, 42 - step, 56, 50 - step, fill=LINE, outline='')
        c.create_oval(8, top, 56, 50, fill=color, outline=LINE, width=2)
    else:
        # feet (dangle while dragged)
        fy = 56 if s in ('drag', 'ceiling') else 52
        c.create_oval(16, fy - step, 28, fy + 8 - step, fill=LINE, outline='')
        c.create_oval(36, fy - 3 + step, 48, fy + 5 + step, fill=LINE, outline='')
        # body
        c.create_oval(8, top, 56, 58, fill=color, outline=LINE, width=2)
    # face, looks where it's going
    ex, ey = 32 + d * 5, top + 16
    if s in ('fall', 'drag', 'hang'):
        for dx in (-8, 8):
            c.create_oval(ex + dx - 4, ey - 4, ex + dx + 4, ey + 4, fill='white', outline=LINE)
            c.create_oval(ex + dx - 1, ey - 1, ex + dx + 1, ey + 1, fill=LINE, outline='')
        c.create_oval(ex - 3, ey + 7, ex + 3, ey + 13, fill=LINE, outline='')  # "o" mouth
    else:
        blink = f % 100 < 4 or s == 'sit' and f % 200 < 100
        for dx in (-8, 8):
            if blink:
                c.create_line(ex + dx - 3, ey, ex + dx + 3, ey, fill=LINE, width=2)
            else:
                c.create_oval(ex + dx - 3, ey - 3, ex + dx + 3, ey + 3, fill=LINE, outline='')
        c.create_arc(ex - 4, ey + 3, ex + 4, ey + 11, start=200, extent=140, style='arc', outline=LINE, width=2)
    for dx in (-14, 14):
        c.create_oval(ex + dx - 3, ey + 4, ex + dx + 3, ey + 8, fill=CHEEK, outline='')
    if style == 'Cat':  # whiskers
        for dy in (6, 9):
            c.create_line(ex - 22, ey + dy, ex - 15, ey + dy, fill=LINE)
            c.create_line(ex + 15, ey + dy, ex + 22, ey + dy, fill=LINE)


def to_pixmap(img):
    """PIL RGBA picture -> QPixmap."""
    data = img.convert('RGBA').tobytes('raw', 'RGBA')
    return QPixmap.fromImage(QImage(data, img.width, img.height, img.width * 4, QImage.Format_RGBA8888).copy())


class App:
    def __init__(self, tray=True, startup=False, window=True):
        """startup: launched at Windows login, so bring back the saved pets quietly.
        Otherwise (Start menu / taskbar) open Settings and wait for the user to send a pet out from Home."""
        self.qt = QApplication.instance() or QApplication(sys.argv)
        self.qt.setQuitOnLastWindowClosed(False)  # the tray and the pets keep it alive
        if os.path.exists(LOGO):
            self.qt.setWindowIcon(QIcon(LOGO))
        self.settings = load_settings()
        self.blob_cache = {}
        self.pack_cache = {}
        self.migrate_character()
        self.load_character()
        self.pets = []
        self.panel = None
        self.visible = True
        self.minutes = 0
        self.win = None  # active window pets can stand on; refreshed by watch_window()
        self.tray = self.start_tray() if tray else None
        self.show_event = k32.CreateEventW(None, False, False, SHOW_EVENT)
        if tray and autostart():
            autostart(True)  # refresh an older login entry so it carries --startup
        if startup:
            for ch, n in list(self.settings['roster'].items()):
                for _ in range(n):
                    self.add(ch, save=False)
        else:
            self.settings['pets'] = 0  # in memory only until a pet is sent out; the saved count is for login
            self.settings['roster'] = {}
        if FROZEN:
            threading.Thread(target=download_update, daemon=True).start()
        self.timers = [self.every(15, self.frame, precise=True), self.every(60_000, self.every_minute),
                       self.every(100, self.watch_window), self.every(200, self.poll)]
        if window and not startup:
            QTimer.singleShot(50, self.open_settings)
        self.watch_window()

    def every(self, ms, fn, precise=False):
        t = QTimer()
        if precise:
            t.setTimerType(Qt.PreciseTimer)
        t.timeout.connect(fn)
        t.start(ms)
        return t

    def run(self):
        self.qt.exec()

    def frame(self):
        for p in list(self.pets):
            p.tick()

    def watch_window(self):
        self.win = active_window()

    def poll(self):
        if self.show_event and k32.WaitForSingleObject(ctypes.c_void_p(self.show_event), 0) == 0:
            self.open_settings()  # the app was launched again

    def every_minute(self):
        for p in self.pets:  # resolution, taskbar or monitor layout may have changed
            if p.state != 'drag':
                p.update_area()
        self.minutes += 1
        if FROZEN:  # only the installed exe self-updates, not `python pet.py`
            if apply_update():
                self.quit()
                return
            if self.minutes % 360 == 0:  # pets left running for days still get updates (every 6 h)
                threading.Thread(target=download_update, daemon=True).start()

    def allowed(self, name):
        """Monitor allowed by Settings? No choice saved, or none of the chosen ones connected: all allowed."""
        chosen = self.settings['monitors']
        return not chosen or name in chosen or not any(n in chosen for n, _ in all_monitors())

    def allowed_areas(self):
        return [area for name, area in all_monitors() if self.allowed(name)]

    def migrate_character(self):
        """v1.0.3's single custom image becomes a pack named 'My image'."""
        if self.settings['character'] != '__migrate__':
            return
        self.settings['character'] = ''
        if os.path.exists(CHARACTER_FILE):
            dest = os.path.join(PACKS_DIR, 'My image')
            os.makedirs(dest, exist_ok=True)
            shutil.copyfile(CHARACTER_FILE, os.path.join(dest, 'idle.png'))
            self.settings['character'] = 'My image'
        r = self.settings['roster']
        if '__migrate__' in r:
            r[self.settings['character']] = r.get(self.settings['character'], 0) + r.pop('__migrate__')
        save_settings(self.settings)

    def get_pack(self, name):
        """((frames, fps) or None for the blob, the pack's scale) for one character at the current size."""
        path = os.path.join(PACKS_DIR, name)
        scale = packs.scale_of(packs.read_meta(path)) if name and os.path.isdir(path) else 1
        key = (name, pet_px(self.settings), scale)
        if key not in self.pack_cache:  # sliders call apply() many times a second: never reload images needlessly
            if len(self.pack_cache) > 12:  # the Size slider makes a key per step
                self.pack_cache.clear()
            pack = None
            if name and os.path.isdir(path):
                try:
                    pack = packs.load_frames(path, int(pet_px(self.settings) * scale))
                except Exception:
                    pack = None  # broken pack: fall back to the blob rather than crash the pets
                if pack and 'idle' not in pack[0]:
                    pack = None
            self.pack_cache[key] = pack
        return self.pack_cache[key], scale

    def load_character(self):
        """The main character (Home preview, accent, Add pet): its pack in self.pack; None means the blob."""
        self.pack, self.pack_scale = self.get_pack(self.settings['character'])

    def menu_qss(self):
        from panel import menu_qss  # the menus follow the Settings theme
        return menu_qss(sys.modules[__name__], self.settings)

    def apply(self):
        """Save settings and push them to every pet. The Settings window calls this on each change."""
        self.load_character()
        r = self.settings['roster']
        for ch in [c for c in r if c and not os.path.isdir(os.path.join(PACKS_DIR, c))]:
            r[''] = r.get('', 0) + r.pop(ch)  # a deleted pack: its pets turn into blobs
        self.settings['pets'] = sum(r.values())
        save_settings(self.settings)
        for p in self.pets:
            p.resize()
            p.update_area()
        have = lambda ch: sum(p.char == ch for p in self.pets)
        for p in reversed(list(self.pets)):  # too many of a character: the newest go
            if have(p.char) > r.get(p.char, 0):
                self.remove(p, count=False)
        for ch, n in r.items():
            while have(ch) < n:
                self.add(ch, save=False)
        self.quit_if_idle()
        if self.tray:
            self.tray.setIcon(QIcon(to_pixmap(logo_image(64, self.settings['color']))))
            self.tray_menu.setStyleSheet(self.menu_qss())

    def blob_frame(self, s, d, step, blink, style, color, px):
        """Smooth picture of the default pet for one pose, drawn once and reused."""
        key = (s, d, step, blink, style, color, px)
        img = self.blob_cache.get(key)
        if img is None:
            pc = PilCanvas(px)
            draw_blob(pc, color, s, d, 0 if blink else 150, step, style)  # f=0 blinks, f=150 eyes open
            if len(self.blob_cache) > 300:
                self.blob_cache.clear()
            img = self.blob_cache[key] = pc.image()
        return img

    def set_visible(self, on):
        self.visible = on
        for p in self.pets:
            p.win.setVisible(on)
        if self.tray:
            self.show_action.setChecked(on)

    def open_settings(self, tab='home'):
        if self.panel:
            self.panel.show_tab(tab)
        else:
            from panel import SettingsWindow
            self.panel = SettingsWindow(self, sys.modules[__name__], tab)

    def start_tray(self):
        """Tray icon next to the clock: click = Settings; menu = Settings, Show pets, Quit."""
        tray = QSystemTrayIcon(QIcon(to_pixmap(logo_image(64, self.settings['color']))))
        tray.setToolTip('Desktop Pet')
        menu = self.tray_menu = QMenu()
        menu.setStyleSheet(self.menu_qss())
        menu.addAction('Settings', self.open_settings)
        self.show_action = QAction('Show pets', menu, checkable=True, checked=True)
        self.show_action.toggled.connect(lambda on: on != self.visible and self.set_visible(on))
        menu.addAction(self.show_action)
        menu.addSeparator()
        menu.addAction('Quit', self.quit)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda why: why == QSystemTrayIcon.Trigger and self.open_settings())
        tray.show()
        return tray

    def quit(self):
        if self.tray:
            self.tray.hide()
        for p in self.pets:
            p.alive = False
            p.win.close()
        self.qt.quit()

    def add(self, char=None, save=True):
        if len(self.pets) >= 10:
            return
        char = self.settings['character'] if char is None else char
        self.pets.append(Pet(self, char))
        if save:
            r = self.settings['roster']
            r[char] = r.get(char, 0) + 1
            self.settings['pets'] = sum(r.values())
            save_settings(self.settings)

    def remove(self, pet, count=True):
        pet.alive = False
        pet.win.close()
        pet.win.deleteLater()
        self.pets.remove(pet)
        if count:  # apply() fixes the roster itself
            r = self.settings['roster']
            r[pet.char] = r.get(pet.char, 0) - 1
            if r[pet.char] <= 0:
                del r[pet.char]
            self.settings['pets'] = sum(r.values())
            save_settings(self.settings)
            self.quit_if_idle()

    def quit_if_idle(self):
        """No pets, no Settings window, no tray icon to come back from: nothing left to show, so exit."""
        if not self.pets and not self.tray and not self.panel:
            self.quit()


def check_updater():
    """Wrong SHA-256 must leave no .new file; right one must produce it."""
    payload = b'pretend exe'
    real = urllib.request.urlopen
    with tempfile.TemporaryDirectory() as d:
        exe = os.path.join(d, 'DesktopPet.exe')
        try:
            for sha, want in (('0' * 64, False), (hashlib.sha256(payload).hexdigest(), True)):
                manifest = json.dumps({'version': '999.0.0', 'sha256': sha}).encode()
                urllib.request.urlopen = lambda url, timeout: io.BytesIO(manifest if url.endswith('.json') else payload)
                download_update(exe)
                assert os.path.exists(exe + '.new') == want, f'sha {sha[:8]}: .new exists={not want}'
        finally:
            urllib.request.urlopen = real
        # an update Windows refuses to run must be rolled back, not left in place
        with open(exe, 'wb') as f:
            f.write(b'current')  # .new from above is not a real exe, so starting it fails
        assert not apply_update(exe), 'unstartable update reported as applied'
        with open(exe, 'rb') as f:
            assert f.read() == b'current', 'old exe not restored after failed update'


def check_settings(d):
    """Bad or hostile settings files fall back to defaults; good ones round-trip."""
    path = os.path.join(d, 's.json')
    assert load_settings(path) == DEFAULTS  # missing file
    for junk in ('not json', '[1, 2]', '{"color": "red; rm", "size": 99, "pets": 2.5, "speed": true}',
                 '{"character": "..\\\\..\\\\Windows", "theme": "Nope", "style": 3, "accent": "blue"}'):
        with open(path, 'w') as f:
            f.write(junk)
        assert load_settings(path) == DEFAULTS, junk
    good = dict(DEFAULTS, color='#ff0000', size=2.0, pets=3, roster={'My cat': 3}, monitors=['\\\\.\\DISPLAY2'], character='My cat',
                style='Ghost', theme='Ocean', accent='#123456', font='Bahnschrift')
    save_settings(good, path)
    assert load_settings(path) == good


def check_packs(d):
    """Import from a folder and a .zip, refuse junk and zip paths that escape, load and delete."""
    import zipfile
    from PIL import Image
    src, dest = os.path.join(d, 'src'), os.path.join(d, 'packs')
    os.makedirs(src)
    os.makedirs(dest)
    frames = [Image.new('RGBA', (40, 30), c) for c in ('red', 'blue')]
    frames[0].save(os.path.join(src, 'idle.gif'), save_all=True, append_images=frames[1:], duration=100, loop=0)
    Image.new('RGBA', (30, 40), 'green').save(os.path.join(src, 'walk.png'))
    with open(os.path.join(src, 'pack.json'), 'w') as f:
        json.dump({'name': 'Test pet', 'author': 'me', 'fps': 12}, f)
    assert packs.import_pack(src, dest) == ['Test pet']
    z = os.path.join(d, 'zipped.zip')
    with zipfile.ZipFile(z, 'w') as zf:
        zf.write(os.path.join(src, 'idle.gif'), 'inner/idle.gif')
        zf.writestr('../../evil.png', b'x')  # must never be written outside the pack
        zf.writestr('notes.txt', b'ignored')
    assert packs.import_pack(z, dest) == ['zipped']
    assert sorted(os.listdir(os.path.join(dest, 'zipped'))) == ['idle.gif'] and not os.path.exists(os.path.join(d, 'evil.png'))
    for bad in (os.path.join(d, 'nothing.zip'), d):  # no idle image
        if bad.endswith('.zip'):
            with zipfile.ZipFile(bad, 'w') as zf:
                zf.writestr('walk.txt', b'x')
        try:
            packs.import_pack(bad, dest)
            raise AssertionError(f'{bad} should be refused')
        except ValueError:
            pass
    loaded, fps = packs.load_frames(os.path.join(dest, 'Test pet'), 64)
    assert fps == 12 and len(loaded['idle'][0]) == 2 and max(loaded['idle'][0][0].size) == 64
    # a Shimeji-ee download: img/<name>/conf/actions.xml naming its pictures (facing left, 128 px)
    shim = os.path.join(d, 'shimeji.zip')
    pose = lambda img, t: f'<Pose Image="/{img}" ImageAnchor="64,128" Velocity="0,0" Duration="{t}" />'
    actions = ('<Mascot xmlns="http://www.group-finity.com/Mascot"><ActionList>'
               f'<Action Name="Stand" Type="Stay"><Animation>{pose("stand01.png", 250)}</Animation></Action>'
               f'<Action Name="Walk" Type="Move"><Animation>{pose("walk01.png", 2)}{pose("walk02.png", 2)}</Animation></Action>'
               '<Action Name="Pinched" Type="Embedded"><Animation Condition="#{x}">' + pose('pinch01.png', 5) +
               '</Animation><Animation>' + pose('pinch02.png', 5) + '</Animation></Action>'
               '</ActionList></Mascot>')
    with zipfile.ZipFile(shim, 'w') as zf:
        zf.writestr('app/img/Blue/conf/actions.xml', actions)
        zf.writestr('app/conf/actions.xml', actions)  # app-wide defaults with no pictures: skipped
        for i, img in enumerate(('stand01.png', 'walk01.png', 'walk02.png', 'pinch01.png', 'pinch02.png')):
            buf = io.BytesIO()
            Image.new('RGBA', (128, 128), (i * 40, 80, 200, 255)).save(buf, 'PNG')
            zf.writestr('app/img/Blue/' + img, buf.getvalue())
    assert packs.import_pack(shim, dest) == ['Blue']
    meta = packs.read_meta(os.path.join(dest, 'Blue'))
    assert meta['faces'] == 'left' and meta['frames']['drag'] == [['pinch02.png', 5]]  # the plain (unconditioned) pose
    sframes, sfps = packs.load_frames(os.path.join(dest, 'Blue'), 64)
    assert sfps == 25 and len(sframes['walk'][0]) == 4 and len(sframes['idle'][0]) == 250 and 'climb' not in sframes
    assert [n for n, _ in packs.list_packs(dest)] == ['Blue', 'Test pet', 'zipped']
    packs.delete_pack(dest, 'Blue')
    packs.delete_pack(dest, 'zipped')
    try:
        packs.delete_pack(dest, '..')
        raise AssertionError('deleting outside the packs folder must be refused')
    except ValueError:
        pass
    assert [n for n, _ in packs.list_packs(dest)] == ['Test pet']


def selftest():
    global SETTINGS_FILE, PACKS_DIR, CHARACTER_FILE, active_window
    active_window = lambda: None  # the user's real windows must not take part in the test
    assert newer('1.0.10', '1.0.9') and not newer('1.0.0', '1.0.0') and not newer('0.9', '1.0')
    check_updater()
    assert os.path.exists(LOGO), f'missing {LOGO}'
    assert logo_image(32).size == (32, 32) and logo_image(32).getpixel((16, 16))[3] == 255  # solid in the middle
    assert all_monitors() and all_monitors()[0] == monitor_at()
    with tempfile.TemporaryDirectory() as d:
        check_settings(d)
        # never touch the real settings or packs
        SETTINGS_FILE, PACKS_DIR = os.path.join(d, 'settings.json'), os.path.join(d, 'packs')
        CHARACTER_FILE = os.path.join(d, 'c.png')
        app = App(tray=False, startup=True, window=False)
        check_packs(d)
        p = app.pets[0]
        L, T, R, B = p.area
        for _ in range(200):
            p.step()
            assert L <= p.x <= R - p.px, p.x
        assert p.y <= B - p.px
        p.x, p.state, p.dir = R - p.px, 'walk', 1  # walk into right wall
        p.step()
        assert p.state == 'climb' or p.dir == -1
        p.x, p.y, p.state, p.dir = R - p.px, T + 6, 'climb', 1  # climbing the right wall, nearly at the top
        for _ in range(5):
            p.step()
        assert p.state == 'ceiling' and p.dir == -1 and p.y == T, (p.state, p.dir, p.y)
        p.draw()  # hanging picture hugs the top
        p.timer, p.x = 10 ** 6, L + 1  # monkey-barred all the way across
        p.step()
        assert p.state == 'fall'
        # a window under a falling pet becomes its floor; it rides along when the window moves; walks off its end
        win = (12345, L + 100, T + 400, L + 700)
        app.win = win
        p.x, p.y, p.vx, p.vy, p.ledge = L + 300, T + 400 - p.px - 30, 0, 5, None
        p.set('fall')
        for _ in range(10):
            p.step()
        assert p.ledge and p.state in ('land', 'idle') and p.y == T + 400 - p.px, (p.state, p.y)
        app.win = (12345, L + 150, T + 380, L + 750)
        p.step()
        assert p.y == T + 380 - p.px and p.ledge[1] == L + 150, 'rides the moved window'
        p.set('walk', 10 ** 6)
        p.dir, p.x = 1, L + 750 - p.px
        p.step()
        assert p.state in ('sit', 'fall'), p.state
        p.ledge, app.win = (12345, L + 150, T + 380, L + 750), None
        p.set('idle')
        p.step()
        assert not p.ledge and p.state == 'fall', 'window gone: falls'
        # leap from the floor onto a window above
        p.ledge, p.state, p.y, p.x = None, 'idle', B - p.px, L + 300
        random.seed(1)
        app.win = (12345, L + 200, B - 300, L + 900)
        for _ in range(200):
            p.next_move(app.win, p.x + p.px / 2)
            if p.state == 'fall' and p.vy < 0:
                break
        for _ in range(200):
            p.step()
            if p.state != 'fall':
                break
        assert p.ledge and p.y == B - 300 - p.px, ('jump onto window', p.state, p.y)
        app.win = None
        for st in ('run', 'chase', 'lie', 'dance'):  # new poses draw for the blob
            p.state = st
            p.draw()
        for style in BLOB_STYLES:
            app.settings['style'] = style
            p.draw()
            img = blob_image(40, '#7ecf8f', style)
            assert img.size == (40, 40) and img.getpixel((24, 24))[3] == 255, style  # smooth picture, solid body
        global cursor_pos
        real_cursor = cursor_pos
        p.x, p.y, p.state = 100, 100, 'idle'
        l, t, r, b = p.body()
        cursor_pos = lambda: (100 + (l + r) // 2, 100 + b - 2)  # grab by the feet: hangs upside down
        p.grab()
        assert p.state == 'hang' and p.hy < p.px / 3
        mx0, my0 = cursor_pos()
        assert abs(p.x + p.hx - mx0) < 0.01 and abs(p.y + p.hy - my0) < 0.01  # the foot is on the pointer at once
        for i in range(40):  # pointer sweeps right, then stops
            cursor_pos = lambda i=i: (mx0 + 8 * min(i, 20), my0)
            p.follow(1 / 60)
            p.draw()
            if i == 12:
                assert p.th < -0.05, p.th  # the body lags behind, swung to the left
        roll, random.random = random.random, lambda: 1.0  # no struggle kicks while checking it settles
        for _ in range(400):
            p.follow(1 / 60)
        random.random = roll
        assert abs(p.th) < 0.02 and abs(p.om) < 0.05, (p.th, p.om)  # swung back and settled
        for _ in range(600):  # held still: kicks now and then
            p.follow(1 / 60)
            if abs(p.om) > 1:
                break
        assert abs(p.om) > 1, 'struggles when held still'
        p.th = p.om = 0.0
        p.trail = [(time.perf_counter() - 0.05, 0, 100), (time.perf_counter(), 60, 100)]
        p.drop()
        assert p.state == 'fall' and p.spin_v < 0  # thrown right: rolls clockwise
        for _ in range(200):
            p.draw()
            p.step()
            p.tick()
        assert p.spin == 0 and p.state != 'fall'  # tumbled, righted itself, landed
        p.x, p.y, p.state = 100, 100, 'idle'
        cursor_pos = lambda: (100 + (l + r) // 2, 100 + t + 2)  # grab by the head: holds on with its hand
        p.grab()
        assert p.state == 'drag'
        cursor_pos = real_cursor
        app.settings['off'] = [a for a in ACTIONS if a != 'sit']
        for _ in range(20):
            p.set('idle', 1)
            p.next_move(None, 0)
            assert p.state in ('idle', 'sit'), p.state
        app.settings['off'] = []
        app.open_settings()
        panel = app.panel
        for tab in ('home', 'characters', 'customize', 'settings'):
            panel.show_tab(tab)
        panel.change('size', 2.0)
        panel.change('pets', 3)
        assert p.px == int(2 * SIZE * DPI_SCALE) and len(app.pets) == 3 and load_settings()['pets'] == 3
        panel.pick_subtab('customize', 'Font')
        assert char_opt(app.settings, 'Yellow', 'crash') == 600 and char_opt(app.settings, 'TDL', 'fall') == 'free'
        assert char_opt(app.settings, 'Blue', 'fall') == 'steady'
        assert clean_chars({'Yellow': {'crash': 5, 'laptop': False}, '../x': {'crash': 900},
                            'Blue': {'fall': 'free'}}) == {'Blue': {'fall': 'free'}}
        panel.set_opt('Yellow', 'crash', 900)
        assert load_settings()['chars']['Yellow']['crash'] == 900
        panel.edit_char = 'Test pet'
        panel.pick_subtab('characters', 'Tweaks')
        panel.set_opt('Yellow', 'crash', None)
        assert 'Yellow' not in load_settings()['chars']
        panel.pick_subtab('characters', 'Characters')
        panel.change('gravity', 2.0)
        assert p.g == 2 * GRAVITY
        panel.change('gravity', 1.0)
        save_settings(dict(app.settings, throw=99, damping='x', advanced=1))
        assert load_settings()['throw'] == 1.0 and load_settings()['damping'] == 1.0 and not load_settings()['advanced']
        app.apply()
        panel.search.setText('gravity')
        phys = [h for h in panel.hits if h[0] == 'Physics']
        assert phys and panel.results.isVisible()
        panel.go(phys[0])  # jumps to Settings > Physics and switches Advanced on
        assert panel.tab == 'settings' and app.settings['advanced'] and not panel.search.text()
        panel.change('advanced', False)
        panel.search.setText('zzzz')
        assert not panel.hits and panel.results.isVisible()
        panel.search.clear()
        panel.show_tab('home')
        panel.change('size', 2.0)
        panel.animate()
        panel.change('size', 1.0)
        assert clean_schedule({'on': 'x', 'from': 25, 'to': 7}) == {'on': False, 'from': 22, 'to': 7}
        night = {'schedule': {'on': True, 'from': 22, 'to': 7}}
        assert [mood(night, h) for h in (23, 3, 12)] == ['night', 'night', 'day']
        assert mood({'schedule': {'on': True, 'from': 9, 'to': 17}}, 12) == 'night' and mood({'schedule': {'on': False}}, 3) is None
        panel.set_schedule('on', True)
        assert load_settings()['schedule']['on'] is True
        globals()['clock_hour'] = lambda: 23
        for _ in range(60):  # night: never runs or dances
            p.set('idle', 1)
            p.next_move(None, 0)
            assert p.state in ('idle', 'sit', 'lie', 'walk'), p.state
        globals()['clock_hour'] = lambda: time.localtime().tm_hour
        panel.set_schedule('on', False)
        panel.show_tab('home')
        panel.spawn()  # clicking the character on Home
        assert len(app.pets) == 4 and load_settings()['pets'] == 4
        panel.change('pets', 0)  # no pets left must not quit while the window is open
        assert not app.pets and app.qt is not None
        panel.change('pets', 1)
        p = app.pets[0]
        panel.pick_character('Test pet')  # one pet on the desk: it swaps
        p = app.pets[0]
        assert app.pack and p.pack and p.char == 'Test pet' and len(app.pack[0]['idle'][0]) == 2
        panel.set_count('', 2)  # two blobs join it
        assert sorted(q.char for q in app.pets) == ['', '', 'Test pet'] and load_settings()['roster'] == {'Test pet': 1, '': 2}
        assert clean_roster({'a': 20, 'b': 3, '': -1, '../x': 1}, '', 1) == {'a': 10} and clean_roster(None, 'Yellow', 2) == {'Yellow': 2}
        panel.set_count('Test pet', 99)  # capped: ten pets at most
        assert len(app.pets) == 10
        panel.set_count('', 0)
        panel.set_count('Test pet', 1)
        assert [q.char for q in app.pets] == ['Test pet']
        p = app.pets[0]
        for s in ('walk', 'climb', 'sit'):  # walk has its own image, climb/sit fall back to idle
            p.state = s
            p.draw()
        for n in THEMES:  # every theme builds
            panel.change('theme', n)
        panel.change('theme', 'Light')
        panel.change('font', 'Bahnschrift')
        app.set_visible(False)
        assert not any(q.win.isVisible() for q in app.pets)
        app.set_visible(True)
        assert panel.grab().toImage().pixelColor(panel.width() // 2, panel.height() - 3).alpha() > 0  # no click-through gaps
        panel.close()
        app.quit()
    print('selftest ok')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        try:
            selftest()
        except Exception as e:  # exit code, not a crash dialog: release.ps1 runs this on the built exe
            print('selftest FAILED:', repr(e))
            sys.exit(1)
    else:
        if not single_instance():
            sys.exit()  # already running: it opens its Settings window instead
        if FROZEN:
            try:
                os.remove(sys.executable + '.old')  # leftover from the last update
            except OSError:
                pass
            if apply_update():  # update downloaded last run but never applied
                sys.exit()
        App(startup='--startup' in sys.argv).run()
