"""Desktop pet: walks on the taskbar, climbs screen edges, falls, can be dragged and thrown.
Run: pythonw pet.py   (right-click a pet for Settings / Add / Remove / Quit; tray icon too)
"""
import ctypes, ctypes.wintypes, hashlib, io, json, math, os, queue, random, re, shutil, subprocess, sys, tempfile, threading, time
import tkinter as tk
import urllib.request, winreg

import packs

try:  # sharp text and images: draw at the real screen resolution instead of letting Windows stretch a blurry copy
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware; must happen before any window exists
except (AttributeError, OSError):
    ctypes.windll.user32.SetProcessDPIAware()
DPI_SCALE = ctypes.windll.user32.GetDpiForSystem() / 96
ctypes.windll.winmm.timeBeginPeriod(1)  # 1 ms timer: Windows' default 15.6 ms tick held Tk's timer to ~43 fps  # e.g. 1.25 on a 125% display; pets grow to match

VERSION = '1.0.3'        # bump before each release; release.ps1 reads it
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
    'Light':    ('#f3f3f3', '#ffffff', '#2f60d8', '#1a1a1a', '#666666'),
}
DEFAULTS = {'color': '#7ecf8f', 'speed': 1.0, 'size': 1.0, 'pets': 1, 'monitors': [], 'character': '',
            'style': 'Blob', 'theme': 'Midnight', 'accent': '', 'font': 'Segoe UI'}
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
    s = dict(DEFAULTS)
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
    }
    for k, ok in checks.items():
        if k in saved and ok(saved[k]):
            s[k] = saved[k]
    if saved.get('character') is True:  # v1.0.3 kept one custom image; it becomes a pack at startup
        s['character'] = '__migrate__'
    s['pets'] = int(s['pets'])
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
FLOOR_STATES = ('walk', 'run', 'idle', 'sit', 'lie', 'dance')
STAND_INS = {'run': ('walk',), 'chase': ('run', 'walk'), 'lie': ('sit',), 'ceiling': ('drag',)}  # pack lacks a state


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


class Pet:
    def __init__(self, app):
        self.app, self.alive = app, True
        w = self.win = tk.Toplevel(app.root, cursor='hand2')
        w.overrideredirect(True)
        w.attributes('-topmost', True)
        self.hwnd, self.shown = None, {}  # layered window handle; picture -> its prepared bytes
        self.resize()
        self.area = L, T, R, B = random.choice(app.allowed_areas())  # start on a monitor allowed in Settings
        self.x, self.y = random.randint(L, max(L, R - self.px)), T
        self.vx = self.vy = 0
        self.ledge = None  # the window this pet stands on, as (hwnd, left, top, right)
        self.dir = random.choice((-1, 1))
        self.frame = 0       # physics steps (30 a second): drives sprite animation and timers
        self.t = 0.0         # seconds alive, continuous: drives the blob's smooth motion
        self.prev = (self.x, self.y)
        self.acc, self.last = 0.0, time.perf_counter()
        self.set('fall')
        w.bind('<ButtonPress-1>', self.grab)
        w.bind('<B1-Motion>', self.drag)
        w.bind('<ButtonRelease-1>', self.drop)
        w.bind('<Button-3>', self.menu)
        if not app.visible:
            w.withdraw()
        self.tick()

    def set(self, state, timer=None):
        self.state, self.timer = state, timer or random.randint(40, 200)

    def resize(self):
        self.px = int(pet_px(self.app.settings) * (self.app.pack_scale if self.app.pack else 1))
        self.win.geometry(f'{self.px}x{self.px}')
        self.shown.clear()

    # --- mouse ---
    def grab(self, e):
        self.set('drag')
        self.ox, self.oy, self.vx, self.vy = e.x, e.y, 0, 0

    def drag(self, e):
        nx, ny = e.x_root - self.ox, e.y_root - self.oy
        self.vx, self.vy = nx - self.x, ny - self.y
        self.x, self.y = self.prev = nx, ny
        self.draw(nx, ny)  # follow the pointer at once, not on the next frame

    def drop(self, _):
        self.vx, self.vy = max(-25, min(25, self.vx)), max(-25, min(25, self.vy))  # throw
        self.update_area()  # dropped on another monitor: live there
        self.set('fall')

    def update_area(self):
        """Live on the monitor under the pet; if Settings turned that monitor off, hop to an allowed one."""
        name, area = monitor_at(self.x + self.px // 2, self.y + self.px // 2)
        if self.app.allowed(name):
            self.area = area
            return
        self.area = L, T, R, B = random.choice(self.app.allowed_areas())
        self.x, self.y = random.randint(L, max(L, R - self.px)), T
        self.set('fall')

    def menu(self, e):
        m = tk.Menu(self.win, tearoff=0)
        m.add_command(label='Settings...', command=self.app.open_settings)
        m.add_command(label='Add pet', command=self.app.add)
        m.add_command(label='Remove this pet', command=lambda: self.app.remove(self))
        m.add_separator()
        m.add_command(label='Quit', command=self.app.quit)
        m.tk_popup(e.x_root, e.y_root)

    # --- behaviour ---
    def step(self):
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
            self.vy += GRAVITY
            self.x += self.vx
            self.y += self.vy
            if not L <= self.x <= R - px:
                self.x = max(L, min(R - px, self.x))
                self.vx = -self.vx * 0.5
            cx = self.x + px / 2
            if (w and not self.ledge and self.vy > 0 and w[1] <= cx <= w[3] and bottom <= w[2] <= self.y + px
                    and w[2] - px > T):  # dropping past a window's top edge: land on it
                self.ledge, floor = w, w[2] - px
            if self.y >= floor:
                self.y, self.vx, self.vy = floor, 0, 0
                self.set('idle')
        elif s in ('walk', 'run', 'chase'):
            if s == 'chase':  # after the mouse pointer, as long as it stays on this screen
                mx = cursor_pos()[0]
                if abs(mx - cx) < px / 3 or not L <= mx <= R:
                    self.set('idle')
                    return
                self.dir = 1 if mx > cx else -1
            self.x += (2 if s == 'walk' else 4) * speed * self.dir
            if s == 'run' and random.random() < 0.004:  # tripped over its own feet
                self.set('lie', 45)
            if not L <= self.x <= R - px:
                self.x = max(L, min(R - px, self.x))
                if self.ledge:  # end of the window: sit on the edge, or hop off
                    if random.random() < 0.5:
                        self.set('sit')
                    else:
                        self.ledge, self.vx, self.vy = None, self.dir * 3, -6
                        self.set('fall')
                elif random.random() < 0.5:
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
            self.x += 1.5 * speed * self.dir
            if not L <= self.x <= R - px:  # reached the far side: drop down
                self.x = max(L, min(R - px, self.x))
                self.set('fall')
            elif self.timer <= 0 and random.random() < 0.006:
                self.set('fall')
        if s in ('idle', 'sit') and self.timer % 10 == 0:  # keep an eye on the mouse pointer
            self.dir = 1 if cursor_pos()[0] > cx else -1
        if s in FLOOR_STATES and self.timer <= 0:
            self.next_move(w, cx)

    def next_move(self, w, cx):
        """Pick what to do next while standing around."""
        mx, my = cursor_pos()
        L, T, R, B = self.area
        choices = ['walk'] * 3 + ['idle'] * 2 + ['sit'] * 2 + ['run', 'lie', 'dance']
        if L <= mx <= R and T <= my <= B:
            choices.append('chase')
        if (w and not self.ledge and w[2] < self.y and w[3] - w[1] > self.px * 2
                and w[1] < R - self.px and w[3] > L + self.px):  # only windows on this pet's screen
            choices.append('jump')
        move = random.choice(choices)
        if move == 'jump':  # leap up onto the active window's top edge
            h = self.y + self.px - w[2]
            if 0 < h < 700:
                self.vy = -((2 * GRAVITY * (h + 30)) ** 0.5)
                t = (-self.vy + max(0, self.vy ** 2 - 2 * GRAVITY * h) ** 0.5) / GRAVITY
                target = min(max(cx, w[1] + self.px, L + self.px), w[3] - self.px, R - self.px)
                self.vx = max(-25, min(25, (target - cx) / max(t, 1)))
                self.set('fall')
                return
            move = 'idle'
        self.set(move)
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
        if self.state == 'drag':
            self.acc = 0.0
            if self.t % 1 > 0.6:  # held still for a moment: wriggle to get free
                x += 2 if self.t % 0.12 < 0.06 else -2
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
        self.win.after(15, self.tick)

    def picture(self):
        """This tick's PIL picture of the pet."""
        d, f, s = self.dir, self.frame, self.state
        if s == 'dance':  # turn to and fro to the beat
            d = 1 if f // 12 % 2 else -1
        if self.app.pack:  # character pack: that state's animation (or a stand-in), mirrored when facing left
            frames, fps = self.app.pack
            pair = next((frames[k] for k in (s,) + STAND_INS.get(s, ()) if k in frames), frames['idle'])
            seq = pair[1] if d < 0 else pair[0]
            return seq[int(f * fps / 30) % len(seq)]
        step = 0
        if s in ('walk', 'climb', 'ceiling', 'run', 'chase', 'dance'):
            period = 0.2 if s in ('run', 'chase') else 0.34  # seconds per stride
            phase = int(self.t % period / period * 12)  # 12 poses per stride, drawn once each and reused
            step = round(3 * math.sin(2 * math.pi * phase / 12), 1)
        blink = f % 100 < 4 or s == 'sit' and f % 200 < 100 or s == 'lie'
        st = self.app.settings
        return self.app.blob_frame(s, 1 if d > 0 else -1, step, blink, st['style'], st['color'], self.px)

    def draw(self, x=None, y=None):
        if self.hwnd is None:
            self.win.update_idletasks()
            self.hwnd = user32.GetParent(self.win.winfo_id())  # the real window around Tk's frame
            ex = user32.GetWindowLongW(self.hwnd, -20)
            user32.SetWindowLongW(self.hwnd, -20, ex | 0x80000 | 0x80)  # WS_EX_LAYERED, WS_EX_TOOLWINDOW
        img = self.picture()
        top = self.state == 'ceiling'  # hanging: picture hugs the top edge, not the floor
        key = (id(img), top)
        data = self.shown.get(key)
        if data is None:
            from PIL import Image
            canvas = Image.new('RGBA', (self.px, self.px), (0, 0, 0, 0))
            canvas.alpha_composite(img, ((self.px - img.width) // 2, 0 if top else self.px - img.height))
            data = canvas.convert('RGBa').tobytes('raw', 'BGRa')  # premultiplied, as Windows wants
            if len(self.shown) > 600:
                self.shown.clear()
            self.shown[key] = data
        show_layered(self.hwnd, data, self.px, self.px, self.x if x is None else x, self.y if y is None else y)


def pet_px(settings):
    """On-screen pet size in pixels: base size x size setting x display scaling."""
    return int(SIZE * settings['size'] * DPI_SCALE)


def draw_pack(c, pack, s, d, f, px, x=None):
    """One frame of a loaded pack ((frames, fps) from packs.load_frames) on canvas c, feet at the bottom."""
    frames, fps = pack
    right, left = frames.get(s) or frames['idle']
    seq = left if d < 0 else right
    c.create_image(px // 2 if x is None else x, px, anchor='s', image=seq[int(f * fps / 30) % len(seq)])


class PilCanvas:
    """The bit of the tk.Canvas drawing API that draw_blob uses, painted onto a PIL image 4x larger and shrunk,
    so edges come out smooth (tk's canvas has no anti-aliasing)."""

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
    top = 26 if s == 'sit' else 34 if s == 'lie' else 20 if s == 'ceiling' else 14 + abs(step) * 0.7
    if s == 'ceiling':  # hanging from the top edge: arms up, one hand forward per step
        c.create_line(24, top + 8, 22 + step, 0, fill=LINE, width=3)
        c.create_line(40, top + 8, 42 - step, 0, fill=LINE, width=3)
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
    else:
        # feet (dangle while dragged)
        fy = 56 if s in ('drag', 'ceiling') else 52
        c.create_oval(16, fy - step, 28, fy + 8 - step, fill=LINE, outline='')
        c.create_oval(36, fy - 3 + step, 48, fy + 5 + step, fill=LINE, outline='')
        # body
        c.create_oval(8, top, 56, 58, fill=color, outline=LINE, width=2)
    # face, looks where it's going
    ex, ey = 32 + d * 5, top + 16
    if s == 'fall' or s == 'drag':
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


class App:
    def __init__(self, tray=True, startup=False, window=True):
        """startup: launched at Windows login, so bring back the saved pets quietly.
        Otherwise (Start menu / taskbar) open Settings and wait for the user to send a pet out from Home."""
        self.root = tk.Tk()
        self.root.withdraw()
        if os.path.exists(LOGO):
            self.root.iconbitmap(default=LOGO)  # every window's taskbar / title icon
        try:  # drag-and-drop for the Characters tab; the app works without it
            from tkinterdnd2 import TkinterDnD
            TkinterDnD._require(self.root)
            self.dnd = True
        except Exception:
            self.dnd = False
        self.settings = load_settings()
        self.blob_cache = {}
        self.migrate_character()
        self.load_character()
        self.pets = []
        self.panel = None
        self.visible = True
        self.minutes = 0
        self.win = None  # active window pets can stand on; refreshed by watch_window()
        self.events = queue.Queue()  # tray icon runs in its own thread; it posts here, tk reads in poll()
        self.tray = start_tray(self) if tray else None
        self.show_event = k32.CreateEventW(None, False, False, SHOW_EVENT)
        if tray and autostart():
            autostart(True)  # refresh an older login entry so it carries --startup
        if startup:
            for _ in range(self.settings['pets']):
                self.add(save=False)
        else:
            self.settings['pets'] = 0  # in memory only until a pet is sent out; the saved count is for login
        if FROZEN:
            threading.Thread(target=download_update, daemon=True).start()
        self.root.after(60_000, self.every_minute)
        if window and not startup:
            self.root.after(50, self.open_settings)
        self.poll()
        self.watch_window()

    def watch_window(self):
        self.win = active_window()
        if self.root.winfo_exists():
            self.root.after(100, self.watch_window)

    def poll(self):
        try:
            while True:
                {'open': self.open_settings, 'toggle': lambda: self.set_visible(not self.visible),
                 'quit': self.quit}[self.events.get_nowait()]()
        except queue.Empty:
            pass
        if self.show_event and k32.WaitForSingleObject(ctypes.c_void_p(self.show_event), 0) == 0:
            self.open_settings()  # the app was launched again
        if self.root.winfo_exists():
            self.root.after(200, self.poll)

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
        self.root.after(60_000, self.every_minute)

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
        save_settings(self.settings)

    def load_character(self):
        """Load the chosen pack at the current size into self.pack; None means draw the blob."""
        name = self.settings['character']
        path = os.path.join(PACKS_DIR, name)
        self.pack_scale = packs.scale_of(packs.read_meta(path)) if name and os.path.isdir(path) else 1
        key = (name, pet_px(self.settings), self.pack_scale)
        if key == getattr(self, 'pack_key', None):
            return  # unchanged: sliders call apply() many times per second, don't reload images each time
        self.pack_key, self.pack = key, None
        if name and os.path.isdir(path):
            try:
                self.pack = packs.load_frames(path, int(pet_px(self.settings) * self.pack_scale), pil=True)
            except Exception:
                self.pack = None  # broken pack: fall back to the blob rather than crash the pets
            if self.pack and 'idle' not in self.pack[0]:
                self.pack = None

    def apply(self):
        """Save settings and push them to every pet. The Settings window calls this on each change."""
        save_settings(self.settings)
        self.load_character()
        for p in self.pets:
            p.resize()
            p.update_area()
        target = self.settings['pets']  # remove() rewrites the setting, so hold on to the goal
        while len(self.pets) < target:
            self.add(save=False)
        while len(self.pets) > target:
            self.remove(self.pets[-1])

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
            p.win.deiconify() if on else p.win.withdraw()
        if self.tray:
            self.tray.update_menu()

    def open_settings(self, tab='home'):
        if self.panel and self.panel.win.winfo_exists():
            self.panel.show(tab)
        else:
            from panel import SettingsWindow  # imported here: customtkinter is only needed once the window opens
            self.panel = SettingsWindow(self, sys.modules[__name__], tab)

    def quit(self):
        if self.tray:
            self.tray.stop()
        if self.root.winfo_exists():
            self.root.destroy()

    def add(self, save=True):
        if len(self.pets) >= 10:
            return
        self.pets.append(Pet(self))
        if save:
            self.settings['pets'] = len(self.pets)
            save_settings(self.settings)

    def remove(self, pet):
        pet.alive = False
        pet.win.destroy()
        self.pets.remove(pet)
        self.settings['pets'] = len(self.pets)
        save_settings(self.settings)
        self.quit_if_idle()

    def quit_if_idle(self):
        """No pets, no Settings window, no tray icon to come back from: nothing left to show, so exit."""
        if not self.pets and not self.tray and not (self.panel and self.panel.win.winfo_exists()):
            self.quit()


def start_tray(app):
    """Tray icon next to the clock: click = Settings; menu = Settings, Show pets, Quit. None if pystray is missing."""
    try:
        import pystray
    except ImportError:
        return None
    post = lambda ev: (lambda icon, item: app.events.put(ev))
    icon = pystray.Icon('DesktopPet', logo_image(64, app.settings['color']), 'Desktop Pet', pystray.Menu(
        pystray.MenuItem('Settings', post('open'), default=True),
        pystray.MenuItem('Show pets', post('toggle'), checked=lambda item: app.visible),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Quit', post('quit'))))
    icon.run_detached()
    return icon


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
    good = dict(DEFAULTS, color='#ff0000', size=2.0, pets=3, monitors=['\\\\.\\DISPLAY2'], character='My cat',
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
    assert fps == 12 and len(loaded['idle'][0]) == 2 and max(loaded['idle'][0][0].width(), loaded['idle'][0][0].height()) == 64
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
        assert p.ledge and p.state == 'idle' and p.y == T + 400 - p.px, (p.state, p.y)
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
        app.open_settings()
        panel = app.panel
        for tab in ('home', 'characters', 'customize', 'settings'):
            panel.show(tab)
        panel.change('size', 2.0)
        panel.change('pets', 3)
        assert p.px == int(2 * SIZE * DPI_SCALE) and len(app.pets) == 3 and load_settings()['pets'] == 3
        panel.show('home')
        panel.spawn()  # clicking the character on Home
        assert len(app.pets) == 4 and load_settings()['pets'] == 4
        panel.change('pets', 0)  # no pets left must not quit while the window is open
        assert not app.pets and app.root.winfo_exists()
        panel.change('pets', 1)
        p = app.pets[0]
        panel.change('character', 'Test pet')
        assert app.pack and len(app.pack[0]['idle'][0]) == 2
        for s in ('walk', 'climb', 'sit'):  # walk has its own image, climb/sit fall back to idle
            p.state = s
            p.draw()
        panel.change('theme', 'Light')
        panel.change('font', 'Bahnschrift')
        app.set_visible(False)
        assert all(q.win.state() == 'withdrawn' for q in app.pets)
        app.set_visible(True)
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
        App(startup='--startup' in sys.argv).root.mainloop()
