"""Desktop pet: walks on the taskbar, climbs screen edges, falls, can be dragged and thrown.
Run: pythonw pet.py   (right-click a pet for Add / Remove / Quit)
"""
import ctypes, ctypes.wintypes, hashlib, io, json, os, random, subprocess, sys, tempfile, threading, tkinter as tk
import urllib.request

VERSION = '1.0.1'        # bump before each release; release.ps1 reads it
REPO = 'yuvancantcodeforshit/desktop-pet'
UPDATE_URL = f'https://github.com/{REPO}/releases/latest/download/'
MAX_EXE = 100_000_000    # refuse absurd downloads

FROZEN = getattr(sys, 'frozen', False)  # True when running as the built DesktopPet.exe

SIZE = 64
KEY = '#010203'          # colour made fully transparent
GRAVITY = 1.5
BODY, LINE, CHEEK = '#7ecf8f', '#2f6b3c', '#f4a6b8'


class MONITORINFO(ctypes.Structure):
    _fields_ = [('cbSize', ctypes.wintypes.DWORD), ('rcMonitor', ctypes.wintypes.RECT),
                ('rcWork', ctypes.wintypes.RECT), ('dwFlags', ctypes.wintypes.DWORD)]


user32 = ctypes.windll.user32
user32.MonitorFromPoint.restype = ctypes.c_void_p  # HMONITOR is pointer-sized; default int would truncate it
user32.MonitorFromPoint.argtypes = [ctypes.wintypes.POINT, ctypes.wintypes.DWORD]
user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]


def work_area(x=0, y=0):
    """Screen rect minus the taskbar of the monitor at (x, y), so pets stand on top of it.
    (0, 0) is always the primary monitor; off-screen points use the nearest monitor."""
    mon = user32.MonitorFromPoint(ctypes.wintypes.POINT(int(x), int(y)), 2)  # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    r = mi.rcWork
    return r.left, r.top, r.right, r.bottom


def newer(a, b):
    """True if version string a is newer than b."""
    return tuple(map(int, a.split('.'))) > tuple(map(int, b.split('.')))


def download_update(exe=None):
    """Background: fetch a newer DesktopPet.exe from GitHub Releases, keep it only if its SHA-256 matches."""
    exe = exe or sys.executable
    try:
        with urllib.request.urlopen(UPDATE_URL + 'latest.json', timeout=10) as r:  # HTTPS, cert-checked
            info = json.loads(r.read(10_000))
        if not newer(info['version'], VERSION):
            return
        with urllib.request.urlopen(UPDATE_URL + 'DesktopPet.exe', timeout=120) as r:
            data = r.read(MAX_EXE + 1)
        if len(data) > MAX_EXE or hashlib.sha256(data).hexdigest() != info['sha256'].lower():
            return
        part = exe + '.part'
        with open(part, 'wb') as f:
            f.write(data)
        os.replace(part, exe + '.new')  # .new only ever holds a verified file
    except Exception:
        pass  # offline, no release yet, bad manifest: keep running this version


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
        self.cv = tk.Canvas(w, width=SIZE, height=SIZE, bg=KEY, highlightthickness=0, cursor='hand2')
        self.cv.pack()
        self.area = L, T, R, B = work_area()  # new pets start on the primary monitor
        self.x, self.y = random.randint(L, R - SIZE), T
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
        self.area = work_area(self.x + SIZE // 2, self.y + SIZE // 2)

    def menu(self, e):
        m = tk.Menu(self.win, tearoff=0)
        m.add_command(label='Add pet', command=self.app.add)
        m.add_command(label='Remove this pet', command=lambda: self.app.remove(self))
        m.add_separator()
        m.add_command(label='Quit', command=self.app.root.destroy)
        m.tk_popup(e.x_root, e.y_root)

    # --- behaviour ---
    def step(self):
        L, T, R, B = self.area
        floor, s = B - SIZE, self.state
        self.frame += 1
        self.timer -= 1
        if s == 'fall':
            self.vy += GRAVITY
            self.x += self.vx
            self.y += self.vy
            if not L <= self.x <= R - SIZE:
                self.x = max(L, min(R - SIZE, self.x))
                self.vx = -self.vx * 0.5
            if self.y >= floor:
                self.y, self.vx, self.vy = floor, 0, 0
                self.set('idle')
        elif s == 'walk':
            self.x += 2 * self.dir
            if not L <= self.x <= R - SIZE:
                self.x = max(L, min(R - SIZE, self.x))
                if random.random() < 0.5:
                    self.set('climb')
                else:
                    self.dir = -self.dir
        elif s == 'climb':
            self.y -= 2
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
        top = 26 if s == 'sit' else 14 + (2 if step else 0)
        # feet (dangle while dragged)
        fy = 52 if s != 'drag' else 56
        c.create_oval(16, fy - step, 28, fy + 8 - step, fill=LINE, outline='')
        c.create_oval(36, fy - 3 + step, 48, fy + 5 + step, fill=LINE, outline='')
        # body
        c.create_oval(8, top, 56, 58, fill=BODY, outline=LINE, width=2)
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


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.pets = []
        self.minutes = 0
        self.add()
        if FROZEN:
            threading.Thread(target=download_update, daemon=True).start()
        self.root.after(60_000, self.every_minute)

    def every_minute(self):
        for p in self.pets:  # resolution, taskbar or monitor layout may have changed
            p.update_area()
        self.minutes += 1
        if FROZEN:  # only the installed exe self-updates, not `python pet.py`
            if apply_update():
                self.root.destroy()
                return
            if self.minutes % 360 == 0:  # pets left running for days still get updates (every 6 h)
                threading.Thread(target=download_update, daemon=True).start()
        self.root.after(60_000, self.every_minute)

    def add(self):
        self.pets.append(Pet(self))

    def remove(self, pet):
        pet.alive = False
        pet.win.destroy()
        self.pets.remove(pet)
        if not self.pets:
            self.root.destroy()


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


def selftest():
    assert newer('1.0.10', '1.0.9') and not newer('1.0.0', '1.0.0') and not newer('0.9', '1.0')
    check_updater()
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
