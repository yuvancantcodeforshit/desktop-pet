"""Desktop pet: walks on the taskbar, climbs screen edges, falls, can be dragged and thrown.
Run: pythonw pet.py   (right-click a pet for Settings / Add / Remove / Quit)
"""
import ctypes, ctypes.wintypes, hashlib, io, json, math, os, random, shutil, subprocess, sys, tempfile, threading
import tkinter as tk
import urllib.request, winreg
from tkinter import colorchooser, filedialog

VERSION = '1.0.2'        # bump before each release; release.ps1 reads it
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
CHARACTER_FILE = os.path.join(SETTINGS_DIR, 'character.png')
DEFAULTS = {'color': '#7ecf8f', 'speed': 1.0, 'size': 1.0, 'pets': 1, 'monitors': [], 'character': False}
MAX_IMAGE = 2048         # px; bigger character images would eat memory
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


# --- settings ---
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
        'color': lambda v: isinstance(v, str) and len(v) == 7 and v[0] == '#'
                           and all(c in '0123456789abcdefABCDEF' for c in v[1:]),
        'speed': num(0.5, 3), 'size': num(0.5, 2.5),
        'pets': lambda v: num(1, 10)(v) and v == int(v),
        'monitors': lambda v: isinstance(v, list) and all(isinstance(m, str) for m in v),
        'character': lambda v: isinstance(v, bool),
    }
    for k, ok in checks.items():
        if k in saved and ok(saved[k]):
            s[k] = saved[k]
    s['pets'] = int(s['pets'])
    return s


def save_settings(s, path=None):
    path = path or SETTINGS_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + '.tmp', 'w', encoding='utf-8') as f:
        json.dump(s, f, indent=2)
    os.replace(path + '.tmp', path)  # never leave a half-written settings file


def autostart(enable=None):
    """Read (enable=None) or set Windows' 'run at login' entry for the installed exe."""
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as k:
        if enable:
            winreg.SetValueEx(k, 'DesktopPet', 0, winreg.REG_SZ, f'"{sys.executable}"')
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


def all_monitors():
    """[(name, work area)] of every connected monitor, primary first."""
    found = []
    cb = MONITORENUMPROC(lambda h, dc, rc, data: found.append(_monitor_info(h)) or 1)
    user32.EnumDisplayMonitors(None, None, cb, None)
    primary = monitor_at()
    return sorted(found, key=lambda m: m != primary)


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


def apply_update():
    """Swap in a verified DesktopPet.exe.new and start it. True if swapped (caller should exit)."""
    exe = sys.executable
    if not os.path.exists(exe + '.new'):
        return False
    try:
        if os.path.exists(exe + '.old'):
            os.remove(exe + '.old')
        os.replace(exe, exe + '.old')  # Windows allows renaming a running exe, not overwriting it
        os.replace(exe + '.new', exe)
    except OSError:
        return False
    # PYINSTALLER_RESET_ENVIRONMENT: new exe unpacks fresh instead of reusing this process's temp folder.
    # DESKTOPPET_RESTART: new exe waits for this one to exit instead of quitting as a second copy.
    subprocess.Popen([exe], cwd=os.path.dirname(exe),
                     env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1', DESKTOPPET_RESTART='1'))
    return True


def single_instance():
    """Hold a named lock for this process's lifetime. False if another copy already runs."""
    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    h = k32.CreateMutexW(None, True, 'DesktopPetSingleInstance')
    if ctypes.get_last_error() != 183:  # not ERROR_ALREADY_EXISTS: we own it
        return True
    wait = 10_000 if os.environ.get('DESKTOPPET_RESTART') else 0
    # 0 = got it, 0x80 = previous owner exited without releasing (also ours now)
    return k32.WaitForSingleObject(ctypes.c_void_p(h), wait) in (0, 0x80)


class Pet:
    def __init__(self, app):
        self.app, self.alive = app, True
        w = self.win = tk.Toplevel(app.root)
        w.overrideredirect(True)
        w.attributes('-topmost', True)
        w.attributes('-transparentcolor', KEY)
        self.cv = tk.Canvas(w, bg=KEY, highlightthickness=0, cursor='hand2')
        self.cv.pack()
        self.resize()
        self.area = L, T, R, B = random.choice(app.allowed_areas())  # start on a monitor allowed in Settings
        self.x, self.y = random.randint(L, max(L, R - self.px)), T
        self.vx = self.vy = 0
        self.dir = random.choice((-1, 1))
        self.frame = 0
        self.set('fall')
        self.cv.bind('<ButtonPress-1>', self.grab)
        self.cv.bind('<B1-Motion>', self.drag)
        self.cv.bind('<ButtonRelease-1>', self.drop)
        self.cv.bind('<Button-3>', self.menu)
        self.tick()

    def set(self, state):
        self.state, self.timer = state, random.randint(40, 200)

    def resize(self):
        self.px = int(SIZE * self.app.settings['size'])
        self.cv.config(width=self.px, height=self.px)

    # --- mouse ---
    def grab(self, e):
        self.set('drag')
        self.ox, self.oy, self.vx, self.vy = e.x, e.y, 0, 0

    def drag(self, e):
        nx, ny = e.x_root - self.ox, e.y_root - self.oy
        self.vx, self.vy = nx - self.x, ny - self.y
        self.x, self.y = nx, ny
        self.win.geometry(f'+{nx}+{ny}')

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
        m.add_command(label='Quit', command=self.app.root.destroy)
        m.tk_popup(e.x_root, e.y_root)

    # --- behaviour ---
    def step(self):
        L, T, R, B = self.area
        px, speed = self.px, self.app.settings['speed']
        floor, s = B - px, self.state
        self.frame += 1
        self.timer -= 1
        if s == 'fall':
            self.vy += GRAVITY
            self.x += self.vx
            self.y += self.vy
            if not L <= self.x <= R - px:
                self.x = max(L, min(R - px, self.x))
                self.vx = -self.vx * 0.5
            if self.y >= floor:
                self.y, self.vx, self.vy = floor, 0, 0
                self.set('idle')
        elif s == 'walk':
            self.x += 2 * speed * self.dir
            if not L <= self.x <= R - px:
                self.x = max(L, min(R - px, self.x))
                if random.random() < 0.5:
                    self.set('climb')
                else:
                    self.dir = -self.dir
        elif s == 'climb':
            self.y -= 2 * speed
            if self.y <= T or self.timer <= 0:  # let go, hop away from the wall
                self.y = max(T, self.y)
                self.vx, self.vy = -self.dir * 3, -4
                self.set('fall')
        if s in ('walk', 'idle', 'sit') and self.timer <= 0:
            self.set(random.choice(('walk', 'walk', 'idle', 'sit')))
            if self.state == 'walk':
                self.dir = random.choice((-1, 1))

    def tick(self):
        if not self.alive:
            return
        if self.state != 'drag':
            self.step()
            self.win.geometry(f'+{int(self.x)}+{int(self.y)}')
        self.draw()
        self.win.after(33, self.tick)

    def draw(self):
        c, d, f, s = self.cv, self.dir, self.frame, self.state
        c.delete('all')
        moving = s in ('walk', 'climb')
        step = 3 if moving and f // 5 % 2 else 0
        if self.app.char_img:  # custom character from Settings: it hops while moving
            c.create_image(self.px // 2, self.px - step, anchor='s', image=self.app.char_img)
            return
        top = 26 if s == 'sit' else 14 + (2 if step else 0)
        # feet (dangle while dragged)
        fy = 52 if s != 'drag' else 56
        c.create_oval(16, fy - step, 28, fy + 8 - step, fill=LINE, outline='')
        c.create_oval(36, fy - 3 + step, 48, fy + 5 + step, fill=LINE, outline='')
        # body
        c.create_oval(8, top, 56, 58, fill=self.app.settings['color'], outline=LINE, width=2)
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
        if self.px != SIZE:  # drawn at 64 px, then scaled to the size setting
            c.scale('all', 0, 0, self.px / SIZE, self.px / SIZE)


class SettingsWindow:
    """Right-click > Settings. Every change applies to the pets at once and is saved."""

    def __init__(self, app):
        self.app, s = app, app.settings
        w = self.win = tk.Toplevel(app.root)
        w.title('Desktop Pet settings')
        w.resizable(False, False)
        w.attributes('-topmost', True)
        w.protocol('WM_DELETE_WINDOW', self.close)
        f = tk.Frame(w, padx=14, pady=10)
        f.pack()
        rows = iter(range(100))

        def row(label, widget):
            r = next(rows)
            tk.Label(f, text=label).grid(row=r, column=0, sticky='nw', pady=4, padx=(0, 12))
            widget.grid(row=r, column=1, sticky='w', pady=4)

        self.color_btn = tk.Button(f, width=10, bg=s['color'], activebackground=s['color'], command=self.pick_color)
        row('Color', self.color_btn)
        for key, label, lo, hi, res in (('speed', 'Speed', 0.5, 3, 0.1), ('size', 'Size', 0.5, 2.5, 0.1),
                                        ('pets', 'Number of pets', 1, 10, 1)):
            sc = tk.Scale(f, from_=lo, to=hi, resolution=res, orient='horizontal', length=200)
            sc.set(s[key])  # set before the callback is attached, so opening the window changes nothing
            sc.config(command=lambda v, k=key: self.change(k, int(float(v)) if k == 'pets' else float(v)))
            row(label, sc)

        cf = tk.Frame(f)
        tk.Button(cf, text='Choose image...', command=self.pick_character).pack(side='left')
        tk.Button(cf, text='Default blob', command=lambda: self.change('character', False)).pack(side='left', padx=6)
        self.char_status = tk.Label(cf, fg='gray', text='custom image' if s['character'] else 'default')
        self.char_status.pack(side='left')
        row('Character', cf)

        mf = tk.Frame(f)
        self.mon_vars = []
        for name, (L, T, R, B) in all_monitors():
            v = tk.BooleanVar(value=not s['monitors'] or name in s['monitors'])
            tk.Checkbutton(mf, text=f'{name.replace(chr(92), "").replace(".", "")}  ({R - L}x{B - T})',
                           variable=v, command=self.change_monitors).pack(anchor='w')
            self.mon_vars.append((name, v))
        row('Show on monitors', mf)

        self.auto = tk.BooleanVar(value=FROZEN and autostart())
        row('Start with Windows', tk.Checkbutton(f, text='' if FROZEN else '(installed app only)', variable=self.auto,
                                                 state='normal' if FROZEN else 'disabled',
                                                 command=lambda: autostart(self.auto.get())))

        uf = tk.Frame(f)
        tk.Label(uf, text=f'v{VERSION}').pack(side='left')
        self.upd_btn = tk.Button(uf, text='Check now', command=self.check_updates,
                                 state='normal' if FROZEN else 'disabled')
        self.upd_btn.pack(side='left', padx=6)
        self.upd_status = tk.Label(uf, fg='gray', text='' if FROZEN else '(installed app only)')
        self.upd_status.pack(side='left')
        row('Updates', uf)
        tk.Button(f, text='Close', width=10, command=self.close).grid(row=next(rows), column=1, sticky='e', pady=(8, 0))

    def change(self, key, value):
        self.app.settings[key] = value
        if key == 'character':
            self.char_status.config(text='custom image' if value else 'default')
        self.app.apply()

    def pick_color(self):
        c = colorchooser.askcolor(self.app.settings['color'], parent=self.win)[1]
        if c:
            self.color_btn.config(bg=c, activebackground=c)
            self.change('color', c)

    def pick_character(self):
        path = filedialog.askopenfilename(parent=self.win, title='Choose a character image',
                                          filetypes=[('PNG or GIF image', '*.png *.gif')])
        if not path:
            return
        try:  # only copy files Tk can actually show, at a sane size
            img = tk.PhotoImage(file=path)
        except tk.TclError:
            self.char_status.config(text='not a PNG/GIF image')
            return
        if max(img.width(), img.height()) > MAX_IMAGE:
            self.char_status.config(text=f'too big (max {MAX_IMAGE} px)')
            return
        os.makedirs(SETTINGS_DIR, exist_ok=True)
        shutil.copyfile(path, CHARACTER_FILE)
        self.app.settings['character'] = False  # force a reload even if a custom image was already set
        self.change('character', True)

    def change_monitors(self):
        on = [name for name, v in self.mon_vars if v.get()]
        self.change('monitors', [] if len(on) in (0, len(self.mon_vars)) else on)  # [] = all monitors

    def check_updates(self):
        self.upd_btn.config(state='disabled')
        self.upd_status.config(text='checking...')
        result = []
        threading.Thread(target=lambda: result.append(download_update()), daemon=True).start()

        def wait():  # tkinter is not thread-safe: the thread only fills `result`, the UI reads it here
            if not result:
                self.app.root.after(300, wait)
            elif result[0] == 'downloaded' and apply_update():
                self.app.root.destroy()  # the new version starts on its own
            elif self.win.winfo_exists():
                self.upd_status.config(text={'latest': 'up to date', 'failed': "couldn't check"}.get(result[0], ''))
                self.upd_btn.config(state='normal')
        wait()

    def close(self):
        self.win.destroy()
        self.app.panel = None


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.settings = load_settings()
        self.load_character()
        self.pets = []
        self.panel = None
        self.minutes = 0
        for _ in range(self.settings['pets']):
            self.add(save=False)
        if FROZEN:
            threading.Thread(target=download_update, daemon=True).start()
        self.root.after(60_000, self.every_minute)

    def every_minute(self):
        for p in self.pets:  # resolution, taskbar or monitor layout may have changed
            if p.state != 'drag':
                p.update_area()
        self.minutes += 1
        if FROZEN:  # only the installed exe self-updates, not `python pet.py`
            if apply_update():
                self.root.destroy()
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

    def load_character(self):
        """Custom character image, scaled to roughly the pet size. None means draw the blob."""
        self.char_img = None
        if not self.settings['character']:
            return
        try:
            img = tk.PhotoImage(file=CHARACTER_FILE)
        except tk.TclError:
            return  # file missing or broken: fall back to the blob
        px, big = int(SIZE * self.settings['size']), max(img.width(), img.height())
        if big > px:
            img = img.subsample(math.ceil(big / px))
        elif big * 2 <= px:
            img = img.zoom(px // big)
        self.char_img = img

    def apply(self):
        """Save settings and push them to every pet. The Settings window calls this on each change."""
        save_settings(self.settings)
        self.load_character()
        for p in self.pets:
            p.resize()
            p.update_area()
        while len(self.pets) < self.settings['pets']:
            self.add(save=False)
        while len(self.pets) > self.settings['pets']:
            self.remove(self.pets[-1])

    def open_settings(self):
        if self.panel:
            self.panel.win.lift()
        else:
            self.panel = SettingsWindow(self)

    def add(self, save=True):
        self.pets.append(Pet(self))
        if save:
            self.settings['pets'] = min(10, len(self.pets))
            save_settings(self.settings)

    def remove(self, pet):
        pet.alive = False
        pet.win.destroy()
        self.pets.remove(pet)
        if not self.pets:
            self.root.destroy()
            return
        self.settings['pets'] = min(10, len(self.pets))
        save_settings(self.settings)


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


def check_settings(d):
    """Bad or hostile settings files fall back to defaults; good ones round-trip."""
    path = os.path.join(d, 's.json')
    assert load_settings(path) == DEFAULTS  # missing file
    for junk in ('not json', '[1, 2]', '{"color": "red; rm", "size": 99, "pets": 2.5, "speed": true}'):
        with open(path, 'w') as f:
            f.write(junk)
        assert load_settings(path) == DEFAULTS, junk
    good = dict(DEFAULTS, color='#ff0000', size=2.0, pets=3, monitors=['\\\\.\\DISPLAY2'], character=True)
    save_settings(good, path)
    assert load_settings(path) == good


def selftest():
    global SETTINGS_FILE, CHARACTER_FILE
    assert newer('1.0.10', '1.0.9') and not newer('1.0.0', '1.0.0') and not newer('0.9', '1.0')
    check_updater()
    assert all_monitors() and all_monitors()[0] == monitor_at()
    with tempfile.TemporaryDirectory() as d:
        check_settings(d)
        SETTINGS_FILE, CHARACTER_FILE = os.path.join(d, 'settings.json'), os.path.join(d, 'c.png')  # never touch real ones
        app = App()
        p = app.pets[0]
        L, T, R, B = p.area
        for _ in range(200):
            p.step()
            assert L <= p.x <= R - SIZE, p.x
        assert p.y <= B - SIZE
        p.x, p.state, p.dir = R - SIZE, 'walk', 1  # walk into right wall
        p.step()
        assert p.state == 'climb' or p.dir == -1
        app.open_settings()
        app.panel.change('size', 2.0)
        app.panel.change('pets', 3)
        assert p.px == 2 * SIZE and len(app.pets) == 3 and load_settings()['pets'] == 3
        tk.PhotoImage(width=200, height=100).write(CHARACTER_FILE, format='png')
        app.panel.change('character', True)
        assert app.char_img and max(app.char_img.width(), app.char_img.height()) <= 2 * SIZE
        app.panel.close()
        app.root.destroy()
    print('selftest ok')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        try:
            selftest()
        except Exception as e:  # exit code, not a crash dialog: release.ps1 runs this on the built exe
            print('selftest FAILED:', repr(e))
            sys.exit(1)
    else:
        if FROZEN:
            if not single_instance():
                sys.exit()  # already running
            try:
                os.remove(sys.executable + '.old')  # leftover from the last update
            except OSError:
                pass
            if apply_update():  # update downloaded last run but never applied
                sys.exit()
        App().root.mainloop()
