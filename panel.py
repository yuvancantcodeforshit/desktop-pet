"""Settings window: right-click a pet > Settings, or click the tray icon.
CustomTkinter, its own dark title bar (minimize / hide to tray / close), and four tabs along the bottom.
"""
import ctypes, os, threading, tkinter as tk, webbrowser
from tkinter import colorchooser, filedialog, font as tkfont, messagebox

import customtkinter as ctk

import packs

# The pets already run at Windows' display scaling; CustomTkinter scaling on top made the window
# 1.25 x too big and off-centre on a 125% screen.
ctk.deactivate_automatic_dpi_awareness()

ICONS = 'Segoe Fluent Icons'  # ships with Windows 11
TABS = (('home', '', 'Home'), ('characters', '', 'Characters'),
        ('customize', '', 'Customize'), ('settings', '', 'Settings'))
COLORS = (('Mint', '#7ecf8f'), ('Sky', '#7cc4f2'), ('Lavender', '#b9a3f0'), ('Peach', '#f7b98b'), ('Lemon', '#f2e27a'),
          ('Coral', '#f2847a'), ('Rose', '#f29fc4'), ('Teal', '#4fc1b3'), ('Grey', '#b0b0b0'), ('Midnight', '#4a5a8a'),
          ('Snow', '#f4f4f4'), ('Lime', '#b5e35a'))
FONTS = ('Segoe UI', 'Segoe UI Variable Display', 'Bahnschrift', 'Cascadia Mono', 'Trebuchet MS', 'Comic Sans MS', 'Georgia')
REBUILD = {'theme', 'accent', 'font', 'character', 'style', 'color'}  # changes that redraw the window; sliders don't
W, H = 400, 660
DANGER = '#ff6b6b'


def shade(hex_color, k):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return '#%02x%02x%02x' % tuple(max(0, min(255, int(v * k))) for v in (r, g, b))


def ink(hex_color):
    """Readable text colour on top of hex_color."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return '#111111' if 0.299 * r + 0.587 * g + 0.114 * b > 150 else '#ffffff'


class SettingsWindow:
    def __init__(self, app, core, tab='home'):
        self.app, self.core, self.tab = app, core, tab
        self.open_sections = {'General'}
        self.status = ''        # message on the Characters tab (import result)
        self.thumbs = {}        # pack name -> small loaded frames, kept for the window's life
        self.frame = 0
        w = self.win = ctk.CTkToplevel(app.root)
        w.overrideredirect(True)  # our own title bar instead of the white Windows one
        w.attributes('-topmost', True)
        if os.path.exists(core.LOGO):
            w.iconbitmap(core.LOGO)  # also stops CustomTkinter swapping in its own icon
        self.logo = ctk.CTkImage(core.logo_image(64), size=(20, 20))
        w.geometry(f'{W}x{H}')  # CustomTkinter scales this size for the display
        self.build()
        w.after(400, self.fit_on_screen)  # after CustomTkinter has applied display scaling

    def fit_on_screen(self):
        """Shrink to the screen height if needed (the body scrolls) and centre on the main screen."""
        w = self.win
        L, T, R, B = self.core.monitor_at()[1]
        w.update_idletasks()
        if w.winfo_height() > B - T - 20:
            w.geometry(f'{W}x{int((B - T - 40) / ctk.ScalingTracker.get_window_scaling(w))}')
            w.update_idletasks()
        # straight to Tk: CustomTkinter's geometry() would scale the position as well
        tk.Wm.wm_geometry(w, f'+{L + (R - L - w.winfo_width()) // 2}+{T + (B - T - w.winfo_height()) // 2}')
        w.after(50, self.taskbar_button)
        self.animate()

    # --- window chrome ---
    def taskbar_button(self):
        """Borderless windows get no taskbar button by default; ask Windows for one (WS_EX_APPWINDOW)."""
        try:
            hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, (style & ~0x80) | 0x40000)
            self.win.withdraw()
            self.win.after(10, self.win.deiconify)
        except tk.TclError:
            pass  # window closed already

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

    def hide(self):
        """Eye button: tuck the window away; the tray icon or right-click > Settings brings it back."""
        self.win.withdraw()

    def close(self):
        self.win.destroy()
        self.app.panel = None
        self.app.quit_if_idle()

    def show(self, tab):
        self.tab = tab
        self.build()
        self.win.deiconify()
        self.win.lift()

    # --- building blocks ---
    def build(self):
        s = self.app.settings
        bg, card, acc, text, muted = self.core.THEMES[s['theme']]
        acc = s['accent'] or acc
        self.c = dict(bg=bg, card=card, acc=acc, text=text, muted=muted, hover=shade(card, 1.25), on_acc=ink(acc))
        family = s['font'] if s['font'] in tkfont.families(self.app.root) else 'Segoe UI'
        self.font = lambda size=13, bold=False: ctk.CTkFont(family=family, size=size, weight='bold' if bold else 'normal')
        ctk.set_appearance_mode('light' if s['theme'] == 'Light' else 'dark')
        for child in self.win.winfo_children():
            child.destroy()
        self.preview = None
        self.win.configure(fg_color=bg)
        self.titlebar()
        self.tabbar()
        self.body = ctk.CTkScrollableFrame(self.win, fg_color=bg, corner_radius=0, scrollbar_button_color=card,
                                           scrollbar_button_hover_color=self.c['hover'])
        self.body.pack(fill='both', expand=True)
        getattr(self, 'page_' + self.tab)()

    def titlebar(self):
        c = self.c
        bar = ctk.CTkFrame(self.win, fg_color=c['bg'], corner_radius=0, height=38)
        bar.pack(fill='x', side='top')
        title = ctk.CTkLabel(bar, text=' Desktop Pet', image=self.logo, compound='left', font=self.font(13, True),
                             text_color=c['text'])
        title.pack(side='left', padx=(12, 6))
        ver = ctk.CTkLabel(bar, text=f'v{self.core.VERSION}', font=self.font(11), text_color=c['muted'])
        ver.pack(side='left')
        for icon, cmd in (('', self.close), ('', self.hide), ('', self.minimize)):  # close, eye, minimize
            ctk.CTkButton(bar, text=icon, width=36, height=28, corner_radius=6, font=ctk.CTkFont(family=ICONS, size=11),
                          fg_color='transparent', hover_color=c['card'], text_color=c['text'], command=cmd).pack(side='right', padx=1)
        for w in (bar, title, ver):
            w.bind('<ButtonPress-1>', self.grab)
            w.bind('<B1-Motion>', self.move)

    def tabbar(self):
        c = self.c
        bar = ctk.CTkFrame(self.win, fg_color=c['card'], corner_radius=0)
        bar.pack(fill='x', side='bottom')
        for key, icon, name in TABS:
            on = key == self.tab
            col = c['acc'] if on else c['muted']
            f = ctk.CTkFrame(bar, fg_color='transparent')
            f.pack(side='left', expand=True, pady=(8, 6))
            parts = [ctk.CTkLabel(f, text=icon, font=ctk.CTkFont(family=ICONS, size=18), text_color=col, height=24),
                     ctk.CTkLabel(f, text=name, font=self.font(11, on), text_color=c['text'] if on else c['muted'], height=16),
                     ctk.CTkFrame(f, fg_color=c['acc'] if on else 'transparent', width=24, height=3, corner_radius=2)]
            for p in parts:
                p.pack(pady=(0, 2))
            for w in [f] + parts:
                w.bind('<Button-1>', lambda e, k=key: self.show(k))
                w.configure(cursor='hand2')

    def header(self, icon, title, sub, image=None):
        h = ctk.CTkFrame(self.body, fg_color='transparent')
        h.pack(fill='x', padx=14, pady=(10, 8))
        ctk.CTkLabel(h, text='' if image else icon, image=image, font=ctk.CTkFont(family=ICONS, size=22),
                     text_color=self.c['text'], width=46, height=46, fg_color=self.c['card'],
                     corner_radius=12).pack(side='left')
        t = ctk.CTkFrame(h, fg_color='transparent')
        t.pack(side='left', padx=12)
        self.label(t, title, 18, True).pack(anchor='w')
        self.label(t, sub, 12, muted=True).pack(anchor='w')

    def card(self, parent=None):
        f = ctk.CTkFrame(parent or self.body, fg_color=self.c['card'], corner_radius=12)
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
        sl = ctk.CTkSlider(row, from_=lo, to=hi, number_of_steps=steps, width=190, progress_color=self.c['acc'],
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
        if key in REBUILD:
            self.build()

    def animate(self):
        """Preview on the Home tab plays the current character."""
        try:
            if not self.win.winfo_exists():
                return
            c = self.preview
            if c is not None and c.winfo_exists():
                c.delete('all')
                if self.app.pack:
                    self.core.draw_pack(c, self.app.pack, 'idle', 1, self.frame, 124, x=90)
                else:
                    s = self.app.settings
                    self.core.draw_blob(c, s['color'], 'idle', 1, self.frame + 50, 0, s['style'])
                    c.scale('all', 0, 0, 1.9, 1.9)
                    c.move('all', 29, 2)
            self.frame += 3
            self.win.after(100, self.animate)
        except tk.TclError:
            pass  # window went away mid-frame

    def thumb(self, parent, name):
        """40 px picture of a pack (or the blob for name '')."""
        c = tk.Canvas(parent, width=40, height=40, bg=self.c['hover'], highlightthickness=0)
        if not name:
            s = self.app.settings
            self.core.draw_blob(c, s['color'], f=50, style=s['style'])
            c.scale('all', 0, 0, 0.6, 0.6)
            c.move('all', 1, 1)
            return c
        if name not in self.thumbs:
            try:
                self.thumbs[name] = packs.load_frames(os.path.join(self.core.PACKS_DIR, name), 36)
            except Exception:
                self.thumbs[name] = None
        if self.thumbs[name] and 'idle' in self.thumbs[name][0]:
            self.core.draw_pack(c, self.thumbs[name], 'idle', 1, 0, 38, x=20)
        return c

    # --- Home ---
    def page_home(self):
        self.header('', 'Desktop Pet', 'Your little desk buddy',
                    ctk.CTkImage(self.core.logo_image(96), size=(32, 32)))
        c = self.card()
        self.preview = tk.Canvas(c, width=180, height=130, bg=self.c['card'], highlightthickness=0, cursor='hand2')
        self.preview.pack(pady=(8, 0))
        self.preview.bind('<Button-1>', lambda e: self.spawn())
        hint = 'Click to send one out' if len(self.app.pets) < 10 else 'That is all 10 of them!'
        self.label(c, f'{hint}  ·  {len(self.app.pets)} on your desk', 11, muted=True).pack(pady=(0, 8))
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
        ctk.CTkFrame(c, height=4, fg_color='transparent').pack()
        self.slider(c, 'speed', 'Speed', 0.5, 3, 25)
        self.slider(c, 'size', 'Size', 0.5, 2.5, 20)
        self.slider(c, 'pets', 'Pets', 0, 10, 10)
        ctk.CTkFrame(c, height=4, fg_color='transparent').pack()
        self.switch(self.card(), 'Show pets', 'Hide every pet without quitting. The tray icon can bring them back.',
                    self.app.visible, self.app.set_visible)

    def spawn(self):
        """Home tab: clicking the character sends a new pet onto the desktop."""
        self.app.add()
        if not self.app.visible:
            self.app.set_visible(True)
        self.build()  # pet count and slider follow

    # --- Characters ---
    def page_characters(self):
        self.header('', 'Characters', 'Pick who lives on your desk')
        row = ctk.CTkFrame(self.body, fg_color='transparent')
        row.pack(fill='x', padx=14, pady=(0, 4))
        self.button(row, '+ Add .zip', self.add_zip, primary=True, width=96).pack(side='left')
        self.button(row, 'Add folder', self.add_folder, width=90).pack(side='left', padx=6)
        self.button(row, 'Open folder', self.open_packs, width=96).pack(side='left')
        hint = 'Drop a pack folder or .zip anywhere on this tab.' if self.app.dnd else 'Drag and drop needs tkinterdnd2.'
        self.label(self.body, self.status or hint, 11, muted=not self.status, color=self.c['acc']).pack(anchor='w', padx=16)

        c = self.card()
        current = self.app.settings['character'] if self.app.pack else ''
        entries = [('', 'Default blob', 'Built in · style and color below')]
        entries += [(n, m.get('name') if isinstance(m.get('name'), str) else n,
                     f"by {m['author']}" if isinstance(m.get('author'), str) else 'Character pack')
                    for n, m in packs.list_packs(self.core.PACKS_DIR)]
        for name, title, sub in entries:
            active = name == current
            r = ctk.CTkFrame(c, fg_color=self.c['hover'] if active else 'transparent', corner_radius=10)
            r.pack(fill='x', padx=6, pady=3)
            parts = [self.thumb(r, name)]
            parts[0].pack(side='left', padx=8, pady=6)
            t = ctk.CTkFrame(r, fg_color='transparent')
            t.pack(side='left')
            parts += [t, self.label(t, title, 13, True), self.label(t, sub, 11, muted=True)]
            parts[2].pack(anchor='w')
            parts[3].pack(anchor='w')
            if name:
                ctk.CTkButton(r, text='', width=32, height=28, font=ctk.CTkFont(family=ICONS, size=13),
                              fg_color='transparent', hover_color=self.c['card'], text_color=DANGER,
                              command=lambda n=name: self.delete(n)).pack(side='right', padx=6)
            if active:
                self.label(r, '', color=self.c['acc'], font=ctk.CTkFont(family=ICONS, size=15)).pack(side='right', padx=6)
            for w in [r] + parts:
                w.bind('<Button-1>', lambda e, n=name: self.change('character', n))

        c = self.card()
        self.label(c, 'Default blob look', 13, True).pack(anchor='w', padx=12, pady=(10, 4))
        row = ctk.CTkFrame(c, fg_color='transparent')
        row.pack(fill='x', padx=12)
        self.label(row, 'Style', width=60, anchor='w').pack(side='left')
        ctk.CTkOptionMenu(row, values=list(self.core.BLOB_STYLES), command=lambda v: self.change('style', v),
                          fg_color=self.c['hover'], button_color=self.c['hover'], button_hover_color=self.c['acc'],
                          text_color=self.c['text'], font=self.font(12), dropdown_font=self.font(12),
                          variable=tk.StringVar(value=self.app.settings['style'])).pack(side='left')
        grid = ctk.CTkFrame(c, fg_color='transparent')
        grid.pack(padx=8, pady=8)
        for i, (n, col) in enumerate(COLORS):
            on = col == self.app.settings['color']
            b = ctk.CTkButton(grid, text=n, width=104, height=30, corner_radius=8, font=self.font(12), anchor='w',
                              fg_color=self.c['hover'], hover_color=shade(self.c['hover'], 1.2), text_color=self.c['text'],
                              border_width=2 if on else 0, border_color=self.c['acc'],
                              image=self.dot(col), compound='left', command=lambda v=col: self.change('color', v))
            b.grid(row=i // 3, column=i % 3, padx=3, pady=3)
        self.button(c, 'Custom color...', self.pick_color).pack(anchor='w', padx=12, pady=(0, 12))
        if self.app.dnd:
            self.drop_targets(self.body)

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
            name = packs.import_pack(path, self.core.PACKS_DIR)
            self.status = f'Added {name}.'
            self.change('character', name)
        except ValueError as err:
            self.status = f"Couldn't add {os.path.basename(os.path.normpath(path))}: {err}"
            self.build()

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
        self.header('', 'Customize', 'Make this window yours')
        c = self.card()
        self.label(c, 'Themes', 13, True).pack(anchor='w', padx=12, pady=(10, 4))
        grid = ctk.CTkFrame(c, fg_color='transparent')
        grid.pack(padx=8, pady=(0, 10))
        for i, (name, (tbg, tcard, tacc, ttext, _)) in enumerate(self.core.THEMES.items()):
            on = name == self.app.settings['theme']
            tile = ctk.CTkFrame(grid, fg_color=tbg, corner_radius=10, width=165, height=64,
                                border_width=2, border_color=self.c['acc'] if on else tcard)
            tile.grid(row=i // 2, column=i % 2, padx=4, pady=4)
            tile.pack_propagate(False)
            bar = ctk.CTkFrame(tile, fg_color=tcard, corner_radius=6, height=14)
            bar.pack(fill='x', padx=10, pady=(10, 6))
            low = ctk.CTkFrame(tile, fg_color='transparent')
            low.pack(fill='x', padx=10)
            parts = [bar, low, ctk.CTkLabel(low, text=name, font=self.font(12, True), text_color=ttext, height=18),
                     ctk.CTkFrame(low, fg_color=tacc, width=12, height=12, corner_radius=6)]
            parts[2].pack(side='left')
            parts[3].pack(side='right')
            for w in [tile] + parts:
                w.bind('<Button-1>', lambda e, n=name: self.set_theme(n))
                w.configure(cursor='hand2')

        c = self.card()
        self.label(c, 'Accent color', 13, True).pack(anchor='w', padx=12, pady=(10, 2))
        self.label(c, 'Buttons, sliders, switches and the active tab.', 11, muted=True).pack(anchor='w', padx=12)
        row = ctk.CTkFrame(c, fg_color='transparent')
        row.pack(fill='x', padx=12, pady=10)
        ctk.CTkFrame(row, fg_color=self.c['acc'], width=44, height=28, corner_radius=8).pack(side='left')
        self.button(row, 'Pick color...', self.pick_accent).pack(side='left', padx=8)
        self.button(row, 'Theme default', lambda: self.change('accent', '')).pack(side='left')

        c = self.card()
        self.label(c, 'Font', 13, True).pack(anchor='w', padx=12, pady=(10, 4))
        have = set(tkfont.families(self.app.root))
        ctk.CTkOptionMenu(c, values=[f for f in FONTS if f in have], command=lambda v: self.change('font', v),
                          variable=tk.StringVar(value=self.app.settings['font']), width=220, font=self.font(12),
                          dropdown_font=self.font(12), fg_color=self.c['hover'], button_color=self.c['hover'],
                          button_hover_color=self.c['acc'], text_color=self.c['text']).pack(anchor='w', padx=12)
        self.label(c, 'The quick brown pet jumps over the taskbar.', 13).pack(anchor='w', padx=12, pady=(8, 12))

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
        self.build()

    def sec_general(self, c):
        self.switch(c, 'Start with Windows', 'Open Desktop Pet automatically when you log in.',
                    self.core.autostart(), self.core.autostart)

    def sec_screens(self, c):
        self.label(c, 'Pets only walk on the screens you tick.', 11, muted=True).pack(anchor='w', padx=12)
        self.mon_vars = []
        for name, (L, T, R, B) in self.core.all_monitors():
            var = tk.BooleanVar(value=not self.app.settings['monitors'] or name in self.app.settings['monitors'])
            ctk.CTkCheckBox(c, text=f'{name.replace(chr(92), "").replace(".", "")}  ({R - L}x{B - T})', variable=var,
                            command=self.change_monitors, font=self.font(12), text_color=self.c['text'],
                            fg_color=self.c['acc'], hover_color=shade(self.c['acc'], 0.85)).pack(anchor='w', padx=12, pady=4)
            self.mon_vars.append((name, var))
        ctk.CTkFrame(c, height=6, fg_color='transparent').pack()

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
