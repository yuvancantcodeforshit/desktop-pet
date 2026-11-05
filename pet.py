"""Desktop pet: walks on the taskbar, climbs screen edges, falls, can be dragged and thrown.
Run: pythonw pet.py   (right-click a pet for Add / Remove / Quit)
"""
import ctypes, ctypes.wintypes, hashlib, json, os, random, subprocess, sys, threading, tkinter as tk
import urllib.request

VERSION = '1.0.0'        # bump before each release; release.ps1 reads it
REPO = 'yuvancantcodeforshit/desktop-pet'
UPDATE_URL = f'https://github.com/{REPO}/releases/latest/download/'
MAX_EXE = 100_000_000    # refuse absurd downloads

SIZE = 64
KEY = '#010203'          # colour made fully transparent
GRAVITY = 1.5
BODY, LINE, CHEEK = '#7ecf8f', '#2f6b3c', '#f4a6b8'


def work_area(root):
    """Screen rect minus the taskbar, so pets stand on top of it."""
    r = ctypes.wintypes.RECT()
    if ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0):  # SPI_GETWORKAREA
        return r.left, r.top, r.right, r.bottom
    return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def newer(a, b):
    """True if version string a is newer than b."""
    return tuple(map(int, a.split('.'))) > tuple(map(int, b.split('.')))


def download_update():
    """Background: fetch a newer DesktopPet.exe from GitHub Releases, keep it only if its SHA-256 matches."""
    try:
        with urllib.request.urlopen(UPDATE_URL + 'latest.json', timeout=10) as r:  # HTTPS, cert-checked
            info = json.loads(r.read(10_000))
        if not newer(info['version'], VERSION):
            return
        with urllib.request.urlopen(UPDATE_URL + 'DesktopPet.exe', timeout=120) as r:
            data = r.read(MAX_EXE + 1)
        if len(data) > MAX_EXE or hashlib.sha256(data).hexdigest() != info['sha256'].lower():
            return
        part = sys.executable + '.part'
        with open(part, 'wb') as f:
            f.write(data)
        os.replace(part, sys.executable + '.new')  # .new only ever holds a verified file
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
    # reset so the new exe unpacks fresh instead of reusing this process's temp folder
    subprocess.Popen([exe], cwd=os.path.dirname(exe), env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1'))
    return True


class Pet:
    def __init__(self, app):
        self.app, self.alive = app, True
        w = self.win = tk.Toplevel(app.root)
        w.overrideredirect(True)
        w.attributes('-topmost', True)
        w.attributes('-transparentcolor', KEY)
        self.cv = tk.Canvas(w, width=SIZE, height=SIZE, bg=KEY, highlightthickness=0, cursor='hand2')
        self.cv.pack()
        L, T, R, B = app.area
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
        self.set('fall')

    def menu(self, e):
        m = tk.Menu(self.win, tearoff=0)
        m.add_command(label='Add pet', command=self.app.add)
        m.add_command(label='Remove this pet', command=lambda: self.app.remove(self))
        m.add_separator()
        m.add_command(label='Quit', command=self.app.root.destroy)
        m.tk_popup(e.x_root, e.y_root)

    # --- behaviour ---
    def step(self):
        L, T, R, B = self.app.area
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
        self.area = work_area(self.root)
        self.pets = []
        self.add()
        if getattr(sys, 'frozen', False):  # only the installed exe self-updates, not `python pet.py`
            threading.Thread(target=download_update, daemon=True).start()
            self.root.after(60_000, self.poll_update)

    def poll_update(self):
        if apply_update():
            self.root.destroy()
        else:
            self.root.after(60_000, self.poll_update)

    def add(self):
        self.pets.append(Pet(self))

    def remove(self, pet):
        pet.alive = False
        pet.win.destroy()
        self.pets.remove(pet)
        if not self.pets:
            self.root.destroy()


def selftest():
    assert newer('1.0.10', '1.0.9') and not newer('1.0.0', '1.0.0') and not newer('0.9', '1.0')
    app = App()
    p = app.pets[0]
    floor = app.area[3] - SIZE
    for _ in range(200):
        p.step()
        assert app.area[0] <= p.x <= app.area[2] - SIZE, p.x
    assert p.y <= floor
    p.x, p.state, p.dir = app.area[2] - SIZE, 'walk', 1  # walk into right wall
    p.step()
    assert p.state == 'climb' or p.dir == -1
    app.root.destroy()
    print('selftest ok')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
    else:
        if getattr(sys, 'frozen', False):
            try:
                os.remove(sys.executable + '.old')  # leftover from the last update
            except OSError:
                pass
            if apply_update():  # update downloaded last run but never applied
                sys.exit()
        App().root.mainloop()
