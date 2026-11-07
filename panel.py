"""Settings window: right-click a pet > Settings, or click the tray icon.
CustomTkinter, its own dark title bar (minimize / hide to tray / close), and four tabs along the bottom.
"""
import ctypes, os, threading, tkinter as tk, webbrowser
from tkinter import colorchooser, filedialog, font as tkfont, messagebox

import customtkinter as ctk

import packs

ICONS = 'Segoe Fluent Icons'  # ships with Windows 11
TABS = (('home', '', 'Home'), ('characters', '', 'Characters'),
        ('customize', '', 'Customize'), ('settings', '', 'Settings'))
COLORS = (('Mint', '#7ecf8f'), ('Sky', '#7cc4f2'), ('Lavender', '#b9a3f0'), ('Peach', '#f7b98b'), ('Lemon', '#f2e27a'),
          ('Coral', '#f2847a'), ('Rose', '#f29fc4'), ('Teal', '#4fc1b3'), ('Grey', '#b0b0b0'), ('Midnight', '#4a5a8a'),
          ('Snow', '#f4f4f4'), ('Lime', '#b5e35a'))
ACCENTS = ('#57c8ff', '#2f60d8', '#4fc1b3', '#7ecf8f', '#f2e27a', '#ff9e7a', '#ff6b6b', '#f29fc4', '#b9a3f0', '#e8e8e8')
FONTS = ('Segoe UI Variable', 'Segoe UI', 'Bahnschrift', 'Cascadia Mono', 'Trebuchet MS', 'Comic Sans MS', 'Georgia')
RESTYLE = {'theme', 'accent', 'font'}         # redraw the whole window
REFRESH = {'character', 'style', 'color'}     # redraw the pages that show the character; sliders redraw nothing
W, H, MIN_H = 460, 660, 360  # width is fixed; only the height can be dragged
DANGER = '#ff6b6b'
CLOSE_RED = '#c42b1c'  # Windows' own close-button red
TIP_KEY = '#010204'    # colour made see-through around tooltip pills


def animations_on():
    """Windows' 'Animation effects' setting (Settings > Accessibility > Visual effects)."""
    v = ctypes.c_int(1)
    ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(v), 0)  # SPI_GETCLIENTAREAANIMATION
    return bool(v.value)


def shade(hex_color, k):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return '#%02x%02x%02x' % tuple(max(0, min(255, int(v * k))) for v in (r, g, b))


def ink(hex_color):
    """Readable text colour on top of hex_color."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return '#111111' if 0.299 * r + 0.587 * g + 0.114 * b > 150 else '#ffffff'


class Tip:
    """Small tooltip under a widget after a short hover."""

    def __init__(self, widget, text, panel):
        self.w, self.text, self.panel, self.tip, self.job = widget, text, panel, None, None
        widget.bind('<Enter>', self.enter, add='+')
        widget.bind('<Leave>', self.leave, add='+')
        widget.bind('<ButtonPress-1>', self.leave, add='+')

    def enter(self, _):
        self.job = self.w.after(1, self.show)  # straight away; after() so a quick pass-over can cancel it

    def leave(self, _=None):
        if self.job:
            self.w.after_cancel(self.job)
            self.job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None

    def show(self):
        c = self.panel.c
        t = self.tip = tk.Toplevel(self.w, bg=TIP_KEY)
        t.overrideredirect(True)
        t.attributes('-topmost', True)
        t.attributes('-transparentcolor', TIP_KEY)  # see-through corners around the rounded pill
        ctk.CTkLabel(t, text=self.text, fg_color=c['tip'], bg_color=TIP_KEY, text_color='#f2f2f2', corner_radius=8,
                     font=self.panel.font(11), height=24, padx=10).pack()
        t.update_idletasks()
        x = self.w.winfo_rootx() + (self.w.winfo_width() - t.winfo_width()) // 2
        t.geometry(f'+{x}+{self.w.winfo_rooty() + self.w.winfo_height() + 4}')


class SettingsWindow:
    def __init__(self, app, core, tab='home'):
        self.app, self.core, self.tab = app, core, tab
        self.open_sections = {'General'}
        self.subtab = {}        # page -> chosen sub-tab (Characters / Customize)
        self.status = ''        # message on the Characters tab (import result)
        self.thumbs = {}        # (pack name, px) -> small loaded frames, kept for the window's life
        self.pages = {}         # tab -> its built page; switching tabs just shows another one, no rebuild
        self.frame = 0
        self.preview = None
        w = self.win = ctk.CTkToplevel(app.root)
        w.overrideredirect(True)  # our own title bar instead of the white Windows one
        w.attributes('-alpha', 0)  # fades in once placed (fit_on_screen)
        self.ready = False
        w.attributes('-topmost', True)
        if os.path.exists(core.LOGO):
            w.iconbitmap(core.LOGO)  # also stops CustomTkinter swapping in its own icon
        self.logo = ctk.CTkImage(core.logo_image(64), size=(20, 20))
        self.k = ctk.ScalingTracker.get_widget_scaling(w)  # display scaling for the plain tk canvases
        w.geometry(f'{W}x{H}')  # CustomTkinter scales this size for the display
        self.restyle()
        w.after(400, self.fit_on_screen)  # after CustomTkinter has applied display scaling

    def fit_on_screen(self):
        """Shrink to the screen height if needed (the body scrolls) and centre on the main screen."""
        w = self.win
        L, T, R, B = self.core.cursor_monitor()[1]  # open where the user is looking
        w.update_idletasks()
        if w.winfo_height() > B - T - 20:
            w.geometry(f'{W}x{int((B - T - 40) / ctk.ScalingTracker.get_window_scaling(w))}')
            w.update_idletasks()
        # straight to Tk: CustomTkinter's geometry() would scale the position as well
        tk.Wm.wm_geometry(w, f'+{L + (R - L - w.winfo_width()) // 2}+{T + (B - T - w.winfo_height()) // 2}')
        w.after(50, self.taskbar_button)
        self.ready = True
        self.fade(1)
        self.animate()

    # --- window chrome ---
    def taskbar_button(self):
        """Borderless windows get no taskbar button or rounded corners by default; ask Windows for both."""
        try:
            hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, (style & ~0x80) | 0x40000)  # WS_EX_APPWINDOW
            # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2 (Windows 11; ignored elsewhere)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(ctypes.c_int(2)), 4)
            self.win.withdraw()
            self.win.after(10, self.win.deiconify)
        except (tk.TclError, OSError, AttributeError):
            pass  # window closed already, or no DWM

    def grip_press(self, e):
        self.grip0 = (e.y_root, self.win.winfo_height())

    def grip_drag(self, e):
        """Bottom edge: change the height only; the content keeps its size and scrolls."""
        L, T, R, B = self.core.monitor_at()[1]
        h = max(int(MIN_H * self.k), min(B - self.win.winfo_y(), self.grip0[1] + e.y_root - self.grip0[0]))
        self.win.geometry(f'{W}x{int(h / self.k)}')

    def grab(self, e):
        self.off = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def move(self, e):
        tk.Wm.wm_geometry(self.win, f'+{e.x_root - self.off[0]}+{e.y_root - self.off[1]}')  # unscaled, see __init__

    def minimize(self):
        self.win.overrideredirect(False)  # Windows can only minimize a window with a frame
        self.win.iconify()

        def restored(_):
            if self.win.state() == 'normal':
                self.win.overrideredirect(True)
                self.win.unbind('<Map>')
        self.win.bind('<Map>', restored)

    def fade(self, to, then=None, steps=8):
        """Ease the window's opacity to `to` over ~130 ms (ease-out); instant if Windows animations are off."""
        if not animations_on():
            steps = 1
        start = float(self.win.attributes('-alpha'))

        def tick(i=1):
            try:
                k = 1 - (1 - i / steps) ** 3
                self.win.attributes('-alpha', start + (to - start) * k)
                if i < steps:
                    self.win.after(16, tick, i + 1)
                elif then:
                    then()
            except tk.TclError:
                pass  # window closed mid-fade
        tick()

    def hide(self):
        """Eye button: fade the window away; the tray icon or right-click > Settings brings it back."""
        self.fade(0, self.win.withdraw)

    def close(self):
        w, self.app.panel = self.win, None
        self.fade(0, lambda: (w.destroy(), self.app.quit_if_idle()))

    def show(self, tab):
        """Switch tabs. Every page stays placed in the same spot; the chosen one is raised to the top.
        Nothing is hidden or re-shown, so nothing has to repaint (hiding made CustomTkinter redraw = flash)."""
        self.tab = tab
        if tab not in self.pages:
            self.pages[tab] = self.make_page(tab)
        self.raise_page(tab)
        self.color_tabs()
        hidden = self.win.state() != 'normal' or float(self.win.attributes('-alpha')) < 1
        if hidden and self.ready:
            self.win.attributes('-alpha', 0)
        self.win.deiconify()
        if hidden and self.ready:
            self.fade(1)  # comes back the way it left
        self.win.lift()
        self.win.focus_force()  # take the foreground, so the first click lands on our buttons

    def raise_page(self, tab):
        page = self.pages[tab]
        getattr(page, '_parent_frame', page).lift()  # a scrollable frame lives inside its own outer frame

    def make_page(self, tab):
        self.body = ctk.CTkScrollableFrame(self.stack, fg_color=self.c['bg'], corner_radius=0,
                                           scrollbar_button_color=self.c['card'],
                                           scrollbar_button_hover_color=self.c['hover'])
        getattr(self, 'page_' + tab)()
        self.body.place(relx=0, rely=0, relwidth=1, relheight=1)
        return self.body

    def prebuild(self):
        """Build the tabs not opened yet, one per idle moment, under the current one: first visits are instant too."""
        for key, *_ in TABS:
            if key not in self.pages:
                self.pages[key] = self.make_page(key)
                self.raise_page(self.tab)
                self.win.after(30, self.prebuild)
                return

    def refresh(self):
        """Settings that pages show changed: rebuild the visible page and put it on top (old one still covers
        the spot until then, so no flash); the other pages are rebuilt quietly underneath."""
        old = self.pages
        self.pages = {self.tab: self.make_page(self.tab)}
        self.raise_page(self.tab)
        for page in old.values():
            page.destroy()
        self.win.after(30, self.prebuild)

    # --- building blocks ---
    def restyle(self):
        """Theme, accent or font changed (or first open): redraw the whole window."""
        s = self.app.settings
        bg, card, acc, text, muted = self.core.THEMES[s['theme']]
        acc = s['accent'] or acc
        light = s['theme'] == 'Light'
        self.c = dict(bg=bg, card=card, acc=acc, text=text, muted=muted, on_acc=ink(acc),
                      hover=shade(card, 0.93) if light else shade(card, 1.25),  # light theme: hover goes darker
                      border=shade(card, 0.88) if light else shade(card, 1.32),  # 1px edge: dark cards need it
                      btn_hover=shade(bg, 0.88) if light else shade(bg, 2.1),
                      tip='#3a3a3a' if light else shade(card, 1.45))
        have = set(tkfont.families(self.app.root))
        self.family = s['font'] if s['font'] in have or s['font'] + ' Text' in have else 'Segoe UI'
        # Segoe UI Variable is Windows' system font with optical sizes: Display cut for headings, Text for body
        optical = lambda size: (self.family + (' Display' if size >= 16 else ' Text')
                                if self.family + ' Text' in have else self.family)
        self.font = lambda size=13, bold=False: ctk.CTkFont(family=optical(size), size=size,
                                                            weight='bold' if bold else 'normal')
        ctk.set_appearance_mode('light' if light else 'dark')
        for child in self.win.winfo_children():
            child.destroy()
        self.pages, self.preview = {}, None
        self.win.configure(fg_color=bg)
        self.titlebar()
        grip = ctk.CTkFrame(self.win, fg_color=card, corner_radius=0, height=8, cursor='sb_v_double_arrow')  # ~Windows' own edge
        grip.pack(fill='x', side='bottom')
        grip.bind('<ButtonPress-1>', self.grip_press)
        grip.bind('<B1-Motion>', self.grip_drag)
        self.tabbar()
        self.stack = ctk.CTkFrame(self.win, fg_color=bg, corner_radius=0)  # all pages sit here, on top of each other
        self.stack.pack(fill='both', expand=True)
        self.show(self.tab)
        self.win.after(300, self.prebuild)

    def titlebar(self):
        c = self.c
        bar = ctk.CTkFrame(self.win, fg_color=c['bg'], corner_radius=0, height=38)
        bar.pack(fill='x', side='top')
        title = ctk.CTkLabel(bar, text=' Desktop Pet', image=self.logo, compound='left', font=self.font(13, True),
                             text_color=c['text'])
        title.pack(side='left', padx=(12, 6))
        ver = ctk.CTkLabel(bar, text=f'v{self.core.VERSION}', font=self.font(10), text_color=c['muted'],
                           fg_color=c['card'], corner_radius=6, height=20, padx=6)  # small rounded badge
        ver.pack(side='left')
        self.title_buttons = []  # (button, tooltip): close, hide, minimize
        for icon, cmd, tip in (('', self.close, 'Close'), ('', self.hide, 'Hide to tray'),
                               ('', self.minimize, 'Minimize')):
            red = cmd == self.close
            b = ctk.CTkButton(bar, text=icon, width=30, height=30, corner_radius=15, font=ctk.CTkFont(family=ICONS, size=11),
                              fg_color='transparent', hover_color=c['btn_hover'], hover=not red,
                              text_color=c['text'], command=cmd)
            b.pack(side='right', padx=2, pady=4)
            if red:  # red circle + white glyph drawn by hand: changing the glyph colour would wipe CTk's own hover
                b.bind('<Enter>', lambda e, b=b: b.configure(fg_color=CLOSE_RED, text_color='#ffffff'), add='+')
                b.bind('<Leave>', lambda e, b=b: b.configure(fg_color='transparent', text_color=c['text']), add='+')
            self.title_buttons.append((b, Tip(b, tip, self)))
        for w in (bar, title, ver):
            w.bind('<ButtonPress-1>', self.grab)
            w.bind('<B1-Motion>', self.move)

    def tabbar(self):
        c = self.c
        bar = ctk.CTkFrame(self.win, fg_color=c['card'], corner_radius=0)
        bar.pack(fill='x', side='bottom')
        self.tab_parts = {}
        for key, icon, name in TABS:
            f = ctk.CTkFrame(bar, fg_color='transparent')
            f.pack(side='left', expand=True, pady=(8, 6))
            parts = [ctk.CTkLabel(f, text=icon, font=ctk.CTkFont(family=ICONS, size=18), height=24),
                     ctk.CTkLabel(f, text=name, height=16),
                     ctk.CTkFrame(f, width=24, height=3, corner_radius=2)]
            for p in parts:
                p.pack(pady=(0, 2))
            for w in [f] + parts:
                w.bind('<Button-1>', lambda e, k=key: self.show(k))
                w.configure(cursor='hand2')
            self.tab_parts[key] = parts

    def color_tabs(self):
        c = self.c
        for key, (icon, name, bar) in self.tab_parts.items():
            on = key == self.tab
            icon.configure(text_color=c['acc'] if on else c['muted'])
            name.configure(text_color=c['text'] if on else c['muted'], font=self.font(11, on))
            bar.configure(fg_color=c['acc'] if on else c['card'])

    def header(self, icon, title, sub, image=None):
        h = ctk.CTkFrame(self.body, fg_color='transparent')
        h.pack(fill='x', padx=14, pady=(10, 8))
        circle = ctk.CTkFrame(h, width=48, height=48, corner_radius=24, fg_color=self.c['card'])
        circle.pack(side='left')
        circle.pack_propagate(False)  # stay a circle; a label this round would pad itself wider
        ctk.CTkLabel(circle, text='' if image else icon, image=image, font=ctk.CTkFont(family=ICONS, size=20),
                     text_color=self.c['text'], fg_color='transparent', width=30, height=30).place(relx=0.5, rely=0.5,
                                                                                               anchor='center')
        t = ctk.CTkFrame(h, fg_color='transparent')
        t.pack(side='left', padx=12)
        self.label(t, title, 18, True).pack(anchor='w')
        self.label(t, sub, 12, muted=True).pack(anchor='w')

    def card(self, parent=None):
        f = ctk.CTkFrame(parent or self.body, fg_color=self.c['card'], corner_radius=12, border_width=1,
                         border_color=self.c['border'])
        f.pack(fill='x', padx=14, pady=5)
        return f

    def label(self, parent, text, size=13, bold=False, muted=False, **kw):
        color = kw.pop('color', self.c['text'])
        kw.setdefault('font', self.font(size, bold))
        return ctk.CTkLabel(parent, text=text, justify='left', text_color=self.c['muted'] if muted else color, **kw)

    def button(self, parent, text, command, primary=False, color=None, **kw):
        fill = color or (self.c['acc'] if primary else self.c['hover'])
        return ctk.CTkButton(parent, text=text, command=command, font=self.font(12, primary), height=30, corner_radius=8,
                             fg_color=fill, hover_color=shade(fill, 0.85), text_color=ink(fill), **kw)

    def slider(self, parent, key, text, lo, hi, steps):
        row = ctk.CTkFrame(parent, fg_color='transparent')
        row.pack(fill='x', padx=12, pady=4)
        self.label(row, text, width=70, anchor='w').pack(side='left')
        value = self.label(row, '', width=44)
        show = lambda v: value.configure(text=f'{v:g}' if key == 'pets' else f'{v:.1f}x')
        sl = ctk.CTkSlider(row, from_=lo, to=hi, number_of_steps=steps, width=250, progress_color=self.c['acc'],
                           button_color=self.c['acc'], button_hover_color=shade(self.c['acc'], 0.85))
        sl.set(self.app.settings[key])
        show(self.app.settings[key])

        def moved(v):
            v = int(round(v)) if key == 'pets' else round(v, 1)
            show(v)
            if v != self.app.settings[key]:
                self.change(key, v)
        sl.configure(command=moved)  # attached after set(), so opening the window changes nothing
        sl.pack(side='left', padx=6)
        value.pack(side='left')
        self.sliders[key] = (sl, show)

    def stepper(self, parent, key, text, lo, hi):
        """Whole number with down/up arrow buttons, kept between lo and hi."""
        row = ctk.CTkFrame(parent, fg_color='transparent')
        row.pack(fill='x', padx=12, pady=4)
        self.label(row, text, width=70, anchor='w').pack(side='left')
        value = self.label(row, '', 15, True, width=40)
        show = lambda v: value.configure(text=str(v))

        def step(d):
            v = max(lo, min(hi, self.app.settings[key] + d))
            if v != self.app.settings[key]:
                self.change(key, v)
            show(self.app.settings[key])
        arrow = lambda icon, d: ctk.CTkButton(row, text=icon, width=34, height=30, corner_radius=8,
                                              font=ctk.CTkFont(family=ICONS, size=11), fg_color=self.c['hover'],
                                              hover_color=shade(self.c['hover'], 1.25), text_color=self.c['text'],
                                              command=lambda: step(d))
        arrow('', -1).pack(side='left', padx=(6, 0))  # chevron down
        value.pack(side='left', padx=4)
        arrow('', 1).pack(side='left')  # chevron up
        self.label(row, f'max {hi}', 11, muted=True).pack(side='left', padx=10)
        show(self.app.settings[key])
        self.sliders[key] = (None, show)

    def switch(self, parent, title, desc, value, command, enabled=True):
        row = ctk.CTkFrame(parent, fg_color='transparent')
        row.pack(fill='x', padx=12, pady=8)
        t = ctk.CTkFrame(row, fg_color='transparent')
        t.pack(side='left', fill='x', expand=True)
        self.label(t, title, 13, True).pack(anchor='w')
        self.label(t, desc, 11, muted=True, wraplength=260).pack(anchor='w')
        var = tk.BooleanVar(value=value)
        ctk.CTkSwitch(row, text='', variable=var, width=46, progress_color=self.c['acc'],
                      state='normal' if enabled else 'disabled', command=lambda: command(var.get())).pack(side='right')

    def change(self, key, value):
        self.app.settings[key] = value
        self.app.apply()
        if key in RESTYLE:
            self.restyle()
        elif key in REFRESH:
            self.refresh()
        elif key == 'pets':
            self.update_count()

    def animate(self):
        """Preview on the Home tab plays the current character."""
        try:
            if not self.win.winfo_exists():
                return
            c, k = self.preview, self.k
            if c is not None and c.winfo_exists():
                c.delete('all')
                s = self.app.settings
                if self.app.pack:
                    pack = self.smooth_pack(s['character'], int(110 * k))
                    if pack:
                        self.core.draw_pack(c, pack, 'idle', 1, self.frame, int(124 * k), x=int(90 * k))
                else:
                    blink = self.frame % 150 < 6  # blink for a moment every few seconds
                    img = self.blob_photo(int(118 * k), s['color'], s['style'], 0 if blink else 50)
                    c.create_image(int(90 * k), int(128 * k), anchor='s', image=img)
            self.frame += 3
            self.win.after(100, self.animate)
        except tk.TclError:
            pass  # window went away mid-frame

    def blob_photo(self, px, color, style, f=50):
        """Smooth (anti-aliased) blob picture, cached; tk canvas shapes have jagged edges."""
        from PIL import ImageTk
        key = ('blob', px, color, style, f)
        if key not in self.thumbs:
            self.thumbs[key] = ImageTk.PhotoImage(self.core.blob_image(px, color, style, f))
        return self.thumbs[key]

    def smooth_pack(self, name, px):
        """A pack's frames with soft edges for this window (the pets use hard-edged ones), cached."""
        key = (name, px)
        if key not in self.thumbs:
            try:
                self.thumbs[key] = packs.load_frames(os.path.join(self.core.PACKS_DIR, name), px, smooth=True)
            except Exception:
                self.thumbs[key] = None
        pack = self.thumbs[key]
        return pack if pack and 'idle' in pack[0] else None

    def canvas(self, parent, w, h, bg):
        """Plain tk canvas sized for the display scaling (CustomTkinter scales its own widgets, not these)."""
        return tk.Canvas(parent, width=int(w * self.k), height=int(h * self.k), bg=bg, highlightthickness=0)

    def thumb(self, parent, name, bg=None):
        """40 px picture of a pack (or the blob for name ''), on the colour of whatever it sits on."""
        k = self.k
        c = self.canvas(parent, 40, 40, bg or self.c['card'])
        if not name:
            s = self.app.settings
            c.create_image(int(20 * k), int(39 * k), anchor='s', image=self.blob_photo(int(38 * k), s['color'], s['style']))
            return c
        pack = self.smooth_pack(name, int(36 * k))
        if pack:
            self.core.draw_pack(c, pack, 'idle', 1, 0, int(38 * k), x=int(20 * k))
        return c

    # --- Home ---
    def page_home(self):
        self.header('', 'Desktop Pet', 'Your little desk buddy',
                    ctk.CTkImage(self.core.logo_image(96), size=(32, 32)))
        self.sliders = {}
        c = self.card()
        self.preview = self.canvas(c, 180, 130, self.c['card'])
        self.preview.configure(cursor='hand2')
        self.preview.pack(pady=(8, 0))
        self.preview.bind('<Button-1>', lambda e: self.spawn())
        self.count = self.label(c, '', 11, muted=True)
        self.count.pack(pady=(0, 8))
        row = ctk.CTkFrame(self.card(), fg_color='transparent')
        row.pack(fill='x', padx=12, pady=10)
        name = self.app.settings['character']
        self.thumb(row, name if self.app.pack else '').pack(side='left')
        t = ctk.CTkFrame(row, fg_color='transparent')
        t.pack(side='left', padx=10)
        self.label(t, name if self.app.pack else f"{self.app.settings['style']} (default)", 13, True).pack(anchor='w')
        self.label(t, 'Character', 11, muted=True).pack(anchor='w')
        self.button(row, 'Change', lambda: self.show('characters'), width=80).pack(side='right')
        c = self.card()
        ctk.CTkFrame(c, width=1, height=4, fg_color='transparent').pack()  # 1 px wide: must not cover the card's border
        self.slider(c, 'speed', 'Speed', 0.5, 3, 25)
        self.slider(c, 'size', 'Size', 0.5, 2.5, 20)
        self.stepper(c, 'pets', 'Pets', 0, 10)
        ctk.CTkFrame(c, width=1, height=4, fg_color='transparent').pack()  # 1 px wide: must not cover the card's border
        self.switch(self.card(), 'Show pets', 'Hide every pet without quitting. The tray icon can bring them back.',
                    self.app.visible, self.app.set_visible)
        self.update_count()

    def update_count(self):
        """Home tab's pet count line and Pets slider, updated in place."""
        try:
            n = len(self.app.pets)
            hint = 'Click to send one out' if n < 10 else 'That is all 10 of them!'
            self.count.configure(text=f'{hint}  ·  {n} on your desk')
            sl, show = self.sliders['pets']
            if sl:
                sl.set(n)
            show(n)
        except (AttributeError, KeyError, tk.TclError):
            pass  # Home page not built yet

    def spawn(self):
        """Home tab: clicking the character sends a new pet onto the desktop."""
        self.app.add()
        if not self.app.visible:
            self.app.set_visible(True)
        self.update_count()

    # --- Characters ---
    def page_characters(self):
        self.header('\uE716', 'Characters', 'Pick who lives on your desk')
        self.subtabs('characters', (('Characters', '\uE716', self.sub_packs), ('Blob look', '\uE790', self.sub_blob)))
        if self.app.dnd:
            self.drop_targets(self.body)

    def subtabs(self, page, tabs):
        """Folder-style tabs: the chosen one has the panel's colour and joins onto it."""
        current = self.subtab.setdefault(page, tabs[0][0])
        bar = ctk.CTkFrame(self.body, fg_color='transparent')
        bar.pack(fill='x', padx=14, pady=(0, 0))
        for name, icon, _ in tabs:
            on = name == current
            col = self.c['card'] if on else 'transparent'
            t = ctk.CTkFrame(bar, fg_color=col, corner_radius=10, height=38)
            t.pack(side='left', padx=(0, 4))
            parts = [ctk.CTkLabel(t, text=icon, font=ctk.CTkFont(family=ICONS, size=13), width=20,
                                  text_color=self.c['text'] if on else self.c['muted']),
                     self.label(t, name, 12, on, muted=not on)]
            parts[0].pack(side='left', padx=(12, 4), pady=8)
            parts[1].pack(side='left', padx=(0, 14))
            if on:  # square off the bottom corners so the tab runs straight into the panel
                ctk.CTkFrame(t, fg_color=col, corner_radius=0, height=10).place(relx=0, rely=1, relwidth=1, anchor='sw')
            for w in [t] + parts:
                w.bind('<Button-1>', lambda e, n=name: self.pick_subtab(page, n))
                w.configure(cursor='hand2')
        panel = ctk.CTkFrame(self.body, fg_color=self.c['card'], corner_radius=12, border_width=1,
                             border_color=self.c['border'])
        panel.pack(fill='x', padx=14, pady=(0, 6))
        dict((n, f) for n, _, f in tabs)[current](panel)

    def pick_subtab(self, page, name):
        if self.subtab.get(page) != name:
            self.subtab[page] = name
            self.refresh()

    def hoverable(self, frame, widgets, hot):
        """Light up a row while the pointer is anywhere over it (moving onto a child must not flicker it off)."""
        canvases = [w for w in widgets if isinstance(w, tk.Canvas)]  # thumbnails follow the row colour

        def paint(fg, bg):
            frame.configure(fg_color=fg)
            for c in canvases:
                c.configure(bg=bg)

        def leave(_):
            x, y = frame.winfo_pointerxy()
            w = frame.winfo_containing(x, y)
            while w is not None and w is not frame:
                w = w.master
            if w is None:
                paint('transparent', self.c['card'])
        for w in widgets:
            w.bind('<Enter>', lambda e: paint(hot, hot), add='+')
            w.bind('<Leave>', leave, add='+')

    def square_button(self, parent, icon, command, color=None):
        """Small icon button on its own dark square, like the row buttons in Mechvibes."""
        base = shade(self.c['card'], 0.78) if self.app.settings['theme'] != 'Light' else shade(self.c['card'], 0.92)
        return ctk.CTkButton(parent, text=icon, width=32, height=28, corner_radius=8,
                             font=ctk.CTkFont(family=ICONS, size=12), fg_color=base, hover_color=shade(base, 1.6),
                             text_color=color or self.c['text'], command=command)

    def sub_packs(self, c):
        row = ctk.CTkFrame(c, fg_color='transparent')
        row.pack(fill='x', padx=10, pady=(12, 4))
        self.button(row, '+ Add .zip', self.add_zip, primary=True, width=96).pack(side='left')
        self.button(row, 'Add folder', self.add_folder, width=90).pack(side='left', padx=6)
        self.button(row, 'Open folder', self.open_packs, width=96).pack(side='left')
        hint = 'Drop a pack folder or .zip anywhere on this tab.' if self.app.dnd else 'Drag and drop needs tkinterdnd2.'
        self.label(c, self.status or hint, 11, muted=not self.status, color=self.c['acc']).pack(anchor='w', padx=12, pady=(0, 6))
        current = self.app.settings['character'] if self.app.pack else ''
        entries = [('', 'Default blob', 'Built in \u00b7 change its look in Blob look')]
        entries += [(n, m.get('name') if isinstance(m.get('name'), str) else n,
                     f"by {m['author']}" if isinstance(m.get('author'), str) else 'Character pack')
                    for n, m in packs.list_packs(self.core.PACKS_DIR)]
        hot = shade(self.c['card'], 1.15)
        for name, title, sub in entries:
            active = name == current
            r = ctk.CTkFrame(c, fg_color=self.c['hover'] if active else 'transparent', corner_radius=10)
            r.pack(fill='x', padx=6, pady=2)
            parts = [self.thumb(r, name, self.c['hover'] if active else self.c['card'])]
            parts[0].pack(side='left', padx=8, pady=6)
            t = ctk.CTkFrame(r, fg_color='transparent')
            t.pack(side='left')
            parts += [t, self.label(t, title, 13, True), self.label(t, sub, 11, muted=True)]
            parts[2].pack(anchor='w')
            parts[3].pack(anchor='w')
            if name:
                path = os.path.join(self.core.PACKS_DIR, name)
                self.square_button(r, '\uE74D', lambda n=name: self.delete(n), DANGER).pack(side='right', padx=(4, 8))
                self.square_button(r, '\uE838', lambda p=path: os.startfile(p)).pack(side='right')
            if active:
                self.label(r, '\uE73E', color=self.c['acc'], font=ctk.CTkFont(family=ICONS, size=15)).pack(side='right', padx=8)
            else:
                self.hoverable(r, [r] + parts, hot)
            for w in [r] + parts:
                w.bind('<Button-1>', lambda e, n=name: self.change('character', n))
        ctk.CTkFrame(c, width=1, height=6, fg_color='transparent').pack()  # 1 px wide: must not cover the card's border

    def sub_blob(self, c):
        row = ctk.CTkFrame(c, fg_color='transparent')
        row.pack(fill='x', padx=12, pady=(12, 0))
        st, k = self.app.settings, self.k
        preview = self.canvas(row, 64, 64, self.c['card'])  # live look at the blob being styled
        preview.create_image(int(32 * k), int(63 * k), anchor='s',
                             image=self.blob_photo(int(60 * k), st['color'], st['style']))
        preview.pack(side='right')
        self.label(row, 'Style', width=60, anchor='w').pack(side='left')
        ctk.CTkOptionMenu(row, values=list(self.core.BLOB_STYLES), command=lambda v: self.change('style', v),
                          fg_color=self.c['hover'], button_color=self.c['hover'], button_hover_color=self.c['acc'],
                          text_color=self.c['text'], font=self.font(12), dropdown_font=self.font(12),
                          variable=tk.StringVar(value=self.app.settings['style'])).pack(side='left')
        self.label(c, 'Color', 13, True).pack(anchor='w', padx=12, pady=(12, 0))
        grid = ctk.CTkFrame(c, fg_color='transparent')
        grid.pack(padx=8, pady=8)
        for i, (n, col) in enumerate(COLORS):
            on = col == self.app.settings['color']
            b = ctk.CTkButton(grid, text=n, width=124, height=30, corner_radius=8, font=self.font(12), anchor='w',
                              fg_color=self.c['hover'], hover_color=shade(self.c['hover'], 1.2), text_color=self.c['text'],
                              border_width=2 if on else 0, border_color=self.c['acc'],
                              image=self.dot(col), compound='left', command=lambda v=col: self.change('color', v))
            b.grid(row=i // 3, column=i % 3, padx=3, pady=3)
        self.button(c, 'Custom color...', self.pick_color).pack(anchor='w', padx=12, pady=(0, 12))

    def dot(self, color):
        from PIL import Image, ImageDraw
        img = Image.new('RGBA', (28, 28), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse((2, 2, 26, 26), fill=color)
        return ctk.CTkImage(img, size=(14, 14))

    def drop_targets(self, w):
        from tkinterdnd2 import DND_FILES, TkinterDnD
        TkinterDnD.DnDWrapper.drop_target_register(w, DND_FILES)
        TkinterDnD.DnDWrapper.dnd_bind(w, '<<Drop>>', self.dropped)
        for child in w.winfo_children():
            self.drop_targets(child)

    def dropped(self, e):
        for path in self.win.tk.splitlist(e.data):
            self.import_pack(path)
        return e.action

    def import_pack(self, path):
        try:
            names = packs.import_pack(path, self.core.PACKS_DIR)
            self.status = f'Added {", ".join(names)}.' if len(names) < 4 else f'Added {len(names)} characters.'
            self.change('character', names[0])
        except ValueError as err:
            self.status = f"Couldn't add {os.path.basename(os.path.normpath(path))}: {err}"
            self.refresh()

    def add_zip(self):
        path = filedialog.askopenfilename(parent=self.win, title='Choose a character pack',
                                          filetypes=[('Character pack', '*.zip')])
        if path:
            self.import_pack(path)

    def add_folder(self):
        path = filedialog.askdirectory(parent=self.win, title='Choose a character pack folder')
        if path:
            self.import_pack(path)

    def open_packs(self):
        os.makedirs(self.core.PACKS_DIR, exist_ok=True)
        os.startfile(self.core.PACKS_DIR)

    def delete(self, name):
        if not messagebox.askyesno('Delete character', f'Delete "{name}"? Its files are removed.', parent=self.win):
            return
        packs.delete_pack(self.core.PACKS_DIR, name)
        self.thumbs.pop(name, None)
        self.status = f'Deleted {name}.'
        self.change('character', '' if self.app.settings['character'] == name else self.app.settings['character'])

    def pick_color(self):
        c = colorchooser.askcolor(self.app.settings['color'], parent=self.win)[1]
        if c:
            self.change('color', c)

    # --- Customize ---
    def page_customize(self):
        self.header('\uE790', 'Customize', 'Make this window yours')
        self.subtabs('customize', (('Themes', '\uE771', self.sub_themes), ('Colors', '\uE790', self.sub_accent),
                                   ('Font', '\uE8D2', self.sub_font)))

    def sub_themes(self, c):
        self.label(c, 'A theme sets the whole look. Change its accent in Colors.', 11, muted=True).pack(anchor='w', padx=12, pady=(12, 4))
        grid = ctk.CTkFrame(c, fg_color='transparent')
        grid.pack(padx=8, pady=(0, 10))
        for i, (name, (tbg, tcard, tacc, ttext, _)) in enumerate(self.core.THEMES.items()):
            on = name == self.app.settings['theme']
            tile = ctk.CTkFrame(grid, fg_color=tbg, corner_radius=10, width=190, height=70,
                                border_width=2, border_color=self.c['acc'] if on else tcard)
            tile.grid(row=i // 2, column=i % 2, padx=4, pady=4)
            tile.pack_propagate(False)
            bar = ctk.CTkFrame(tile, fg_color=tcard, corner_radius=6, height=14)
            bar.pack(fill='x', padx=(10, 40), pady=(12, 6))
            low = ctk.CTkFrame(tile, fg_color='transparent')
            low.pack(fill='x', padx=10)
            parts = [bar, low, ctk.CTkLabel(low, text=name, font=self.font(12, True), text_color=ttext, height=18),
                     ctk.CTkFrame(low, fg_color=tacc, width=12, height=12, corner_radius=6)]
            parts[2].pack(side='left')
            parts[3].pack(side='right')
            for w in [tile] + parts:
                w.bind('<Button-1>', lambda e, n=name: self.set_theme(n))
                w.configure(cursor='hand2')
            light = name == 'Light'
            normal, hot = self.dots_image(shade(tbg, 0.8 if light else 1.9), ttext), \
                self.dots_image(shade(tbg, 0.68 if light else 2.6), ttext)
            more = ctk.CTkLabel(tile, text='', image=normal, fg_color='transparent', width=24, height=24, cursor='hand2')
            more.place(relx=1, x=-8, y=8, anchor='ne')
            more.bind('<Enter>', lambda e, m=more, i=hot: m.configure(image=i))
            more.bind('<Leave>', lambda e, m=more, i=normal: m.configure(image=i))
            more.bind('<Button-1>', lambda e, n=name, m=more: self.theme_menu(n, m))

    def swatch_image(self, color, selected):
        """Round colour swatch; the chosen one gets a ring."""
        from PIL import Image, ImageDraw
        img = Image.new('RGBA', (120, 120), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if selected:
            d.ellipse((2, 2, 117, 117), outline=self.c['text'], width=7)
        d.ellipse((20, 20, 99, 99), fill=color)
        return ctk.CTkImage(img, size=(30, 30))

    def dots_image(self, fill, dot):
        """Round '...' button picture (a real circle; a CTk button this small pads itself into a pill)."""
        from PIL import Image, ImageDraw
        img = Image.new('RGBA', (96, 96), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((0, 0, 95, 95), fill=fill)
        for x in (28, 48, 68):
            d.ellipse((x - 6, 42, x + 6, 54), fill=dot)
        return ctk.CTkImage(img, size=(24, 24))

    def theme_menu(self, name, button):
        """The round ... button on a theme card."""
        m = tk.Menu(self.win, tearoff=0)
        m.add_command(label=f'Use {name}', command=lambda: self.set_theme(name))
        m.add_command(label=f'Use {name}, keep my accent', command=lambda: self.change('theme', name))
        m.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())

    def sub_accent(self, c):
        self.label(c, 'Accent color', 13, True).pack(anchor='w', padx=12, pady=(12, 2))
        self.label(c, 'Buttons, sliders, switches and the active tab.', 11, muted=True).pack(anchor='w', padx=12)
        row = ctk.CTkFrame(c, fg_color='transparent')
        row.pack(anchor='w', padx=8, pady=(10, 0))
        for col in ACCENTS:
            on = col.lower() == self.c['acc'].lower()
            sw = ctk.CTkLabel(row, text='', image=self.swatch_image(col, on), width=34, height=34, cursor='hand2')
            sw.pack(side='left', padx=2)
            sw.bind('<Button-1>', lambda e, v=col: self.change('accent', v))
        row = ctk.CTkFrame(c, fg_color='transparent')
        row.pack(fill='x', padx=12, pady=12)
        ctk.CTkFrame(row, fg_color=self.c['acc'], width=44, height=28, corner_radius=8).pack(side='left')
        self.button(row, 'Pick color...', self.pick_accent).pack(side='left', padx=8)
        self.button(row, 'Theme default', lambda: self.change('accent', '')).pack(side='left')

    def sub_font(self, c):
        self.label(c, 'Font', 13, True).pack(anchor='w', padx=12, pady=(12, 4))
        have = set(tkfont.families(self.app.root))
        ctk.CTkOptionMenu(c, values=[f for f in FONTS if f in have or f + ' Text' in have],
                          command=lambda v: self.change('font', v),
                          variable=tk.StringVar(value=self.app.settings['font']), width=240, font=self.font(12),
                          dropdown_font=self.font(12), fg_color=self.c['hover'], button_color=self.c['hover'],
                          button_hover_color=self.c['acc'], text_color=self.c['text']).pack(anchor='w', padx=12)
        self.label(c, 'The quick brown pet jumps over the taskbar.', 13).pack(anchor='w', padx=12, pady=(10, 14))

    def set_theme(self, name):
        self.app.settings['accent'] = ''  # a theme brings its own accent
        self.change('theme', name)

    def pick_accent(self):
        c = colorchooser.askcolor(self.c['acc'], parent=self.win)[1]
        if c:
            self.change('accent', c)

    # --- Settings ---
    def page_settings(self):
        self.header('', 'Settings', 'How the app behaves')
        self.section('General', self.sec_general)
        self.section('Screens', self.sec_screens)
        self.section('Updates', self.sec_updates)
        self.section('About', self.sec_about)
        self.section('Danger zone', self.sec_danger, DANGER)
        self.label(self.body, f'Desktop Pet v{self.core.VERSION}', 11, muted=True).pack(pady=10)

    def section(self, name, fill, color=None):
        c = self.card()
        is_open = name in self.open_sections
        head = ctk.CTkFrame(c, fg_color='transparent')
        head.pack(fill='x', padx=12, pady=10)
        parts = [self.label(head, name, 14, True, color=color or self.c['text']),
                 self.label(head, '' if is_open else '', color=color or self.c['text'],
                            font=ctk.CTkFont(family=ICONS, size=11))]
        parts[0].pack(side='left')
        parts[1].pack(side='right')
        for w in [head] + parts:
            w.bind('<Button-1>', lambda e: self.toggle_section(name))
            w.configure(cursor='hand2')
        if is_open:
            fill(c)

    def toggle_section(self, name):
        self.open_sections ^= {name}
        self.refresh()

    def sec_general(self, c):
        self.switch(c, 'Start with Windows', 'Open Desktop Pet automatically when you log in.',
                    self.core.autostart(), self.core.autostart)

    def sec_screens(self, c):
        self.label(c, 'Pets only walk on the screens you tick.', 11, muted=True).pack(anchor='w', padx=12)
        self.mon_vars = []
        for i, (name, (L, T, R, B)) in enumerate(self.core.all_monitors()):
            var = tk.BooleanVar(value=not self.app.settings['monitors'] or name in self.app.settings['monitors'])
            label = f'Screen {i + 1}' + ('  \u00b7  main' if i == 0 else '') + f'   {R - L} x {B - T}'
            ctk.CTkCheckBox(c, text=label, variable=var,
                            command=self.change_monitors, font=self.font(12), text_color=self.c['text'],
                            fg_color=self.c['acc'], hover_color=shade(self.c['acc'], 0.85)).pack(anchor='w', padx=12, pady=4)
            self.mon_vars.append((name, var))
        ctk.CTkFrame(c, width=1, height=6, fg_color='transparent').pack()  # 1 px wide: must not cover the card's border

    def change_monitors(self):
        on = [name for name, v in self.mon_vars if v.get()]
        self.change('monitors', [] if len(on) in (0, len(self.mon_vars)) else on)  # [] = all monitors

    def sec_updates(self, c):
        row = ctk.CTkFrame(c, fg_color='transparent')
        row.pack(fill='x', padx=12, pady=(0, 12))
        if not self.core.FROZEN:
            self.label(row, 'Running from source: updates arrive with git pull.', 11, muted=True).pack(anchor='w')
            return
        self.upd_btn = self.button(row, 'Check for updates', self.check_updates, primary=True)
        self.upd_btn.pack(side='left')
        self.upd_status = self.label(row, '', 11, muted=True)
        self.upd_status.pack(side='left', padx=8)

    def check_updates(self):
        self.upd_btn.configure(state='disabled')
        self.upd_status.configure(text='checking...')
        result = []
        threading.Thread(target=lambda: result.append(self.core.download_update()), daemon=True).start()

        def wait():  # tkinter is not thread-safe: the thread only fills `result`, the UI reads it here
            if not result:
                self.app.root.after(300, wait)
            elif result[0] == 'downloaded' and self.core.apply_update():
                self.app.quit()  # the new version starts on its own
            elif self.win.winfo_exists() and self.upd_status.winfo_exists():
                self.upd_status.configure(text={'latest': 'up to date', 'failed': "couldn't check"}.get(result[0], ''))
                self.upd_btn.configure(state='normal')
        wait()

    def sec_about(self, c):
        self.label(c, f'Desktop Pet v{self.core.VERSION}\nMade by yuvancantcodeforshit', 12, muted=True).pack(anchor='w', padx=12)
        row = ctk.CTkFrame(c, fg_color='transparent')
        row.pack(fill='x', padx=12, pady=10)
        self.button(row, 'GitHub page', lambda: webbrowser.open(f'https://github.com/{self.core.REPO}')).pack(side='left')
        self.button(row, 'Settings folder', lambda: (os.makedirs(self.core.SETTINGS_DIR, exist_ok=True),
                                                     os.startfile(self.core.SETTINGS_DIR))).pack(side='left', padx=8)

    def sec_danger(self, c):
        self.label(c, 'Put every setting back to default. Your character packs stay.', 11, muted=True,
                   wraplength=330).pack(anchor='w', padx=12)
        self.button(c, 'Reset all settings', self.reset, color=DANGER).pack(anchor='w', padx=12, pady=10)

    def reset(self):
        if messagebox.askyesno('Reset settings', 'Reset every setting to its default?', parent=self.win):
            self.app.settings.clear()
            self.app.settings.update({k: list(v) if isinstance(v, list) else v for k, v in self.core.DEFAULTS.items()})
            self.change('theme', self.core.DEFAULTS['theme'])
