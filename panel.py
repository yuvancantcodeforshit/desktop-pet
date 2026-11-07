"""Settings window: right-click a pet > Settings, or click the tray icon.
Qt (PySide6): its own dark title bar (minimize / hide to tray / close), four tabs along the bottom,
themes, accent colour and font. Every change applies to the pets at once and is saved.
"""
import ctypes, os, threading, webbrowser

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QCursor, QFont, QFontDatabase, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QCheckBox, QColorDialog, QComboBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton, QScrollArea, QSlider,
                               QStackedWidget, QVBoxLayout, QWidget, QWidgetAction)

import packs

ICONS = 'Segoe Fluent Icons'  # ships with Windows 11
TABS = (('home', '', 'Home'), ('characters', '', 'Characters'),
        ('customize', '', 'Customize'), ('settings', '', 'Settings'))
COLORS = (('Mint', '#7ecf8f'), ('Sky', '#7cc4f2'), ('Lavender', '#b9a3f0'), ('Peach', '#f7b98b'), ('Lemon', '#f2e27a'),
          ('Coral', '#f2847a'), ('Rose', '#f29fc4'), ('Teal', '#4fc1b3'), ('Grey', '#b0b0b0'), ('Midnight', '#4a5a8a'),
          ('Snow', '#f4f4f4'), ('Lime', '#b5e35a'))
ACCENTS = ('#57c8ff', '#2f60d8', '#4fc1b3', '#7ecf8f', '#f2e27a', '#ff9e7a', '#ff6b6b', '#f29fc4', '#b9a3f0', '#e8e8e8')
FONTS = ('Segoe UI Variable', 'Segoe UI', 'Bahnschrift', 'Cascadia Mono', 'Trebuchet MS', 'Comic Sans MS', 'Georgia')
BEHAVIOUR = {'walk': 'Walk', 'run': 'Run', 'sit': 'Sit', 'lie': 'Lie down', 'dance': 'Dance',
             'climb': 'Climb walls', 'chase': 'Chase the mouse', 'jump': 'Jump onto windows'}  # pet.ACTIONS
RESTYLE = {'theme', 'accent', 'font'}         # redraw the whole window
REFRESH = {'character', 'style', 'color'}     # rebuild the pages that show the character; sliders redraw nothing
W, H, MIN_H = 460, 660, 360  # width is fixed; only the height can be dragged
DANGER = '#ff6b6b'
CLOSE_RED = '#c42b1c'  # Windows' own close-button red


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


def dot_icon(color, ring=None, size=28):
    """Round colour dot (with an optional ring for the chosen one), crisp at any display scaling."""
    from PIL import Image, ImageDraw
    k = 4
    img = Image.new('RGBA', (size * k, size * k), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if ring:
        d.ellipse((2, 2, size * k - 3, size * k - 3), outline=ring, width=2 * k)
    m = size * k // 5 if ring else 0
    d.ellipse((m, m, size * k - 1 - m, size * k - 1 - m), fill=color)
    return img.resize((size * 2, size * 2), Image.LANCZOS)


class Switch(QAbstractButton):
    """iOS-style on/off switch; the knob glides (critically damped, no bounce)."""

    def __init__(self, checked, on, off):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(46, 26)
        self.on, self.off, self.pos_ = QColor(on), QColor(off), 1.0 if checked else 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(180 if animations_on() else 0)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._at)
        self.toggled.connect(self._go)

    def _go(self, checked):
        self.anim.stop()
        self.anim.setStartValue(self.pos_)
        self.anim.setEndValue(1.0 if checked else 0.0)
        self.anim.start()

    def _at(self, v):
        self.pos_ = v
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        t = self.pos_
        c = QColor.fromRgbF(*(a + (b - a) * t for a, b in zip(self.off.getRgbF()[:3], self.on.getRgbF()[:3])))
        p.setBrush(c)
        p.drawRoundedRect(QRectF(0, 0, 46, 26), 13, 13)
        p.setBrush(QColor('#ffffff'))
        p.drawEllipse(QRectF(3 + t * 20, 3, 20, 20))

    def sizeHint(self):
        return QSize(46, 26)


class Clickable(QFrame):
    """A frame that acts like a button (rows, theme tiles, tabs)."""

    def __init__(self, on_click, name=''):
        super().__init__()
        self.on_click = on_click
        self.setObjectName(name)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.on_click()


class SettingsWindow(QWidget):
    def __init__(self, app, core, tab='home'):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Window)  # our own title bar, still on the taskbar
        self.app, self.core, self.tab = app, core, tab
        self.subtab = {}        # page -> chosen sub-tab
        self.open_sections = {'General'}
        self.status = ''        # message on the Characters tab (import result)
        self.thumbs = {}        # (pack name, px) -> loaded frames, kept for the window's life
        self.frame = 0
        self.drag_from = None
        self.setWindowTitle('Desktop Pet')
        self.setAcceptDrops(True)
        self.setFixedWidth(W)
        self.resize(W, H)
        self.setWindowOpacity(0)
        self.restyle()
        self.anim = self.every(100, self.animate)
        self.place()
        self.show()
        self.round_corners()
        self.fade(1)

    # --- window chrome ---
    def every(self, ms, fn):
        t = QTimer(self)
        t.timeout.connect(fn)
        t.start(ms)
        return t

    def place(self):
        """Centre on the screen the mouse is on, never taller than it (the pages scroll)."""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        r = screen.availableGeometry()
        self.resize(W, min(H, r.height() - 40))
        self.move(r.x() + (r.width() - W) // 2, r.y() + (r.height() - self.height()) // 2)

    def round_corners(self):
        try:  # DWMWA_WINDOW_CORNER_PREFERENCE = 33, DWMWCP_ROUND = 2 (Windows 11; ignored elsewhere)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(int(self.winId())), 33,
                                                       ctypes.byref(ctypes.c_int(2)), 4)
        except (OSError, AttributeError):
            pass

    def fade(self, to, then=None):
        """Ease the window's opacity to `to` (~130 ms, ease-out); instant if Windows animations are off."""
        a = self.fader = QPropertyAnimation(self, b'windowOpacity', self)
        a.setDuration(130 if animations_on() else 0)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.setEndValue(to)
        if then:
            a.finished.connect(then)
        a.start()

    def show_tab(self, tab):
        """Open on a tab (tray / right-click / second launch): bring the window back the way it left."""
        self.pick(tab)
        if not self.isVisible() or self.isMinimized() or self.windowOpacity() < 1:
            self.setWindowOpacity(0)
            self.showNormal()
            self.fade(1)
        self.raise_()
        self.activateWindow()

    def hide_to_tray(self):
        """Eye button: fade the window away; the tray icon or right-click > Settings brings it back."""
        self.fade(0, self.hide)

    def close(self):
        self.app.panel = None
        self.fade(0, lambda: (self.deleteLater(), self.app.quit_if_idle()))

    def closeEvent(self, e):  # Alt+F4 and friends
        e.ignore()
        self.close()

    # title bar dragging and the height grip
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            y = e.position().y()
            self.drag_from = ('move' if y < 42 else 'grip' if y > self.height() - 8 else None,
                              e.globalPosition().toPoint(), self.pos(), self.height())

    def mouseMoveEvent(self, e):
        if not self.drag_from or not self.drag_from[0]:
            self.setCursor(Qt.SizeVerCursor if e.position().y() > self.height() - 8 else Qt.ArrowCursor)
            return
        kind, start, pos, h = self.drag_from
        d = e.globalPosition().toPoint() - start
        if kind == 'move':
            self.move(pos + d)
        else:  # bottom edge: height only, the content keeps its size and scrolls
            limit = (self.screen().availableGeometry().bottom() - self.y())
            self.resize(W, max(MIN_H, min(limit, h + d.y())))

    def mouseReleaseEvent(self, _):
        self.drag_from = None

    # drag and drop of character packs (Characters tab)
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and self.tab == 'characters':
            e.acceptProposedAction()

    def dropEvent(self, e):
        for url in e.mimeData().urls():
            if url.isLocalFile():
                self.import_pack(url.toLocalFile())
        e.acceptProposedAction()

    # --- theme ---
    def restyle(self):
        """Theme, accent or font changed (or first open): rebuild everything in the new look."""
        s = self.app.settings
        bg, card, acc, text, muted = self.core.THEMES[s['theme']]
        acc = s['accent'] or acc
        light = s['theme'] == 'Light'
        self.c = c = dict(bg=bg, card=card, acc=acc, text=text, muted=muted, on_acc=ink(acc),
                          hover=shade(card, 0.93) if light else shade(card, 1.25),  # light theme: hover goes darker
                          border=shade(card, 0.88) if light else shade(card, 1.32),  # 1px edge: dark cards need it
                          btn_hover=shade(bg, 0.88) if light else shade(bg, 2.1),
                          tip='#3a3a3a' if light else shade(card, 1.45))
        have = set(QFontDatabase.families())
        fam = s['font'] if s['font'] in have or s['font'] + ' Text' in have else 'Segoe UI'
        # Segoe UI Variable is Windows' system font with optical sizes: Display cut for headings, Text for body
        body, head = (fam + ' Text', fam + ' Display') if fam + ' Text' in have else (fam, fam)
        self.family = body
        self.setStyleSheet(f'''
            QWidget {{ color: {c['text']}; font-family: "{body}"; font-size: 13px; }}
            SettingsWindow, QScrollArea, QStackedWidget, #page {{ background: {c['bg']}; border: none; }}
            #card {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 12px; }}
            #row {{ background: transparent; border-radius: 10px; }}
            #row:hover {{ background: {c['hover']}; }}
            #rowOn {{ background: {c['hover']}; border-radius: 10px; }}
            #title {{ font-family: "{head}"; font-size: 20px; font-weight: 600; }}
            #section {{ font-family: "{head}"; font-size: 15px; font-weight: 600; }}
            #bold {{ font-weight: 600; }}
            #muted {{ color: {c['muted']}; font-size: 12px; }}
            #accent {{ color: {c['acc']}; font-size: 12px; }}
            #badge {{ color: {c['muted']}; background: {c['card']}; border-radius: 6px; padding: 1px 6px; font-size: 11px; }}
            #circle {{ background: {c['card']}; border-radius: 24px; }}
            #icon {{ font-family: "{ICONS}"; font-size: 20px; background: transparent; }}
            QPushButton {{ background: {c['hover']}; border: none; border-radius: 8px; padding: 6px 14px; }}
            QPushButton:hover {{ background: {shade(c['hover'], 0.9 if light else 1.15)}; }}
            QPushButton:pressed {{ background: {shade(c['hover'], 0.82 if light else 1.3)}; }}
            #primary {{ background: {c['acc']}; color: {c['on_acc']}; font-weight: 600; }}
            #primary:hover {{ background: {shade(c['acc'], 0.9)}; }}
            #danger {{ background: {DANGER}; color: #ffffff; font-weight: 600; }}
            #glyph {{ font-family: "{ICONS}"; font-size: 12px; padding: 0; min-width: 32px; min-height: 28px; }}
            #chrome {{ font-family: "{ICONS}"; font-size: 10px; background: transparent; border-radius: 15px;
                       min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; padding: 0; }}
            #chrome:hover {{ background: {c['btn_hover']}; }}
            #close:hover {{ background: {CLOSE_RED}; color: #ffffff; }}
            #tabbar {{ background: {c['card']}; border-top: 1px solid {c['border']}; }}
            #tab QLabel {{ background: transparent; }}
            #grip {{ background: {c['card']}; }}
            QSlider::groove:horizontal {{ height: 4px; background: {c['border']}; border-radius: 2px; }}
            QSlider::sub-page:horizontal {{ background: {c['acc']}; border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: {c['acc']}; width: 18px; height: 18px; margin: -7px 0;
                                          border-radius: 9px; border: 2px solid {c['bg']}; }}
            QComboBox {{ background: {c['hover']}; border: none; border-radius: 8px; padding: 6px 10px; min-width: 140px; }}
            QComboBox QAbstractItemView {{ background: {c['card']}; selection-background-color: {c['acc']};
                                           selection-color: {c['on_acc']}; border: 1px solid {c['border']}; }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 2px solid {c['muted']}; }}
            QCheckBox::indicator:checked {{ background: {c['acc']}; border-color: {c['acc']}; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
            QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 3px; min-height: 30px; }}
            QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
            QToolTip {{ background: {c['tip']}; color: #f2f2f2; border: none; padding: 4px 8px; }}
            QMenu {{ background: {c['card']}; border: 1px solid {c['border']}; padding: 4px; }}
            QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
            QMenu::item:selected {{ background: {c['hover']}; }}
        ''')
        old = self.layout()
        if old:  # throw the previous look away (a layout can't be replaced while it is set)
            QWidget().setLayout(old)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.titlebar())
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        root.addWidget(self.tabbar())
        grip = QFrame(objectName='grip')
        grip.setFixedHeight(6)
        grip.setCursor(Qt.SizeVerCursor)
        grip.setAttribute(Qt.WA_TransparentForMouseEvents)  # the window itself handles the drag
        root.addWidget(grip)
        self.build_pages()

    def build_pages(self):
        """(Re)build all four pages off-screen, then show the current one: no flash."""
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        self.preview = self.count = None
        self.pages = {}
        for key, *_ in TABS:
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            page = QWidget(objectName='page')
            self.body = QVBoxLayout(page)
            self.body.setContentsMargins(14, 10, 14, 14)
            self.body.setSpacing(10)
            getattr(self, 'page_' + key)()
            self.body.addStretch(1)
            area.setWidget(page)
            self.stack.addWidget(area)
            self.pages[key] = area
        self.pick(self.tab)

    def pick(self, tab):
        self.tab = tab
        self.stack.setCurrentWidget(self.pages[tab])
        c = self.c
        for key, (icon, name, bar) in self.tab_parts.items():
            on = key == tab
            icon.setStyleSheet(f'color: {c["acc"] if on else c["muted"]}; font-family: "{ICONS}"; font-size: 18px;')
            name.setStyleSheet(f'color: {c["text"] if on else c["muted"]}; font-size: 11px;'
                               f'font-weight: {600 if on else 400};')
            bar.setStyleSheet(f'background: {c["acc"] if on else "transparent"}; border-radius: 1px;')

    # --- building blocks ---
    def titlebar(self):
        bar = QWidget()
        bar.setFixedHeight(42)
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 0, 8, 0)
        row.setSpacing(4)
        logo = QLabel()
        logo.setPixmap(self.pixmap(self.core.logo_image(80), 20))
        row.addWidget(logo)
        title = QLabel('Desktop Pet', objectName='bold')
        row.addWidget(title)
        row.addWidget(QLabel(f'v{self.core.VERSION}', objectName='badge'), 0, Qt.AlignVCenter)
        row.addStretch(1)
        for icon, fn, tip, name in (('', self.showMinimized, 'Minimize', 'chrome'),
                                    ('', self.hide_to_tray, 'Hide to tray', 'chrome'),
                                    ('', self.close, 'Close', 'close')):
            b = QPushButton(icon)
            b.setObjectName(name)
            if name == 'close':  # same shape as the others, red on hover
                b.setStyleSheet(self.styleSheet().split('#chrome {')[1].split('}')[0].join(('QPushButton {', '}')))
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            row.addWidget(b)
        return bar

    def tabbar(self):
        bar = QFrame(objectName='tabbar')
        row = QHBoxLayout(bar)
        row.setContentsMargins(6, 6, 6, 4)
        self.tab_parts = {}
        for key, icon, name in TABS:
            t = Clickable(lambda k=key: self.pick(k), 'tab')
            col = QVBoxLayout(t)
            col.setSpacing(2)
            col.setContentsMargins(0, 2, 0, 2)
            parts = (QLabel(icon), QLabel(name), QFrame())
            parts[2].setFixedSize(24, 3)
            for p in parts:
                col.addWidget(p, 0, Qt.AlignHCenter)
            row.addWidget(t, 1)
            self.tab_parts[key] = parts
        return bar

    def pixmap(self, img, size):
        """PIL picture -> QPixmap of `size` logical px, sharp on scaled displays."""
        dpr = self.devicePixelRatioF()
        pm = self.core.to_pixmap(img)
        pm = pm.scaled(int(size * dpr), int(size * dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        return pm

    def card(self, layout=None):
        f = QFrame(objectName='card')
        lay = (layout or QVBoxLayout)(f)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        self.body.addWidget(f)
        return lay

    def header(self, icon, title, sub, image=None):
        row = QHBoxLayout()
        circle = QLabel(objectName='circle')
        circle.setFixedSize(48, 48)
        circle.setAlignment(Qt.AlignCenter)
        if image:
            circle.setPixmap(self.pixmap(image, 32))
        else:
            circle.setText(icon)
            circle.setStyleSheet(f'font-family: "{ICONS}"; font-size: 20px; background: {self.c["card"]};'
                                 'border-radius: 24px;')
        row.addWidget(circle)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(QLabel(title, objectName='title'))
        col.addWidget(QLabel(sub, objectName='muted'))
        row.addLayout(col, 1)
        self.body.addLayout(row)

    def button(self, text, fn, kind=''):
        b = QPushButton(text, objectName=kind)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(fn)
        return b

    def glyph(self, icon, fn, color=None, tip=''):
        b = self.button(icon, fn, 'glyph')
        if color:
            b.setStyleSheet(f'color: {color};')
        b.setToolTip(tip)
        return b

    def slider(self, lay, key, text, lo, hi):
        row = QHBoxLayout()
        name = QLabel(text)
        name.setFixedWidth(70)
        value = QLabel(f'{self.app.settings[key]:.1f}x')
        value.setFixedWidth(40)
        sl = QSlider(Qt.Horizontal)
        sl.setRange(int(lo * 10), int(hi * 10))
        sl.setValue(round(self.app.settings[key] * 10))
        sl.setCursor(Qt.PointingHandCursor)

        def moved(v):
            value.setText(f'{v / 10:.1f}x')
            if v / 10 != self.app.settings[key]:
                self.change(key, v / 10)
        sl.valueChanged.connect(moved)  # connected after setValue: opening the window changes nothing
        for w in (name, sl, value):
            row.addWidget(w, 1 if w is sl else 0)
        lay.addLayout(row)

    def switch_row(self, lay, title, desc, value, fn):
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(QLabel(title, objectName='bold'))
        d = QLabel(desc, objectName='muted')
        d.setWordWrap(True)
        col.addWidget(d)
        row.addLayout(col, 1)
        sw = Switch(value, self.c['acc'], self.c['border'])
        sw.toggled.connect(fn)
        row.addWidget(sw, 0, Qt.AlignVCenter)
        lay.addLayout(row)

    def change(self, key, value):
        self.app.settings[key] = value
        self.app.apply()
        if key in RESTYLE:
            self.restyle()
        elif key in REFRESH:
            self.build_pages()
        elif key == 'pets':
            self.update_count()

    # --- pictures ---
    def blob_pixmap(self, size, f=150):
        s = self.app.settings
        dpr = self.devicePixelRatioF()
        img = self.core.blob_image(int(size * dpr), s['color'], s['style'], f)
        pm = self.core.to_pixmap(img)
        pm.setDevicePixelRatio(dpr)
        return pm

    def pack_frames(self, name, size):
        """A pack's pictures at `size` logical px (soft edges), cached."""
        dpr = self.devicePixelRatioF()
        key = (name, int(size * dpr))
        if key not in self.thumbs:
            try:
                self.thumbs[key] = packs.load_frames(os.path.join(self.core.PACKS_DIR, name), key[1])
            except Exception:
                self.thumbs[key] = None
        frames = self.thumbs[key]
        return frames if frames and 'idle' in frames[0] else None

    def thumb(self, name, size=40):
        lab = QLabel()
        lab.setFixedSize(size, size)
        lab.setAlignment(Qt.AlignCenter)
        lab.setStyleSheet('background: transparent;')
        if not name:
            lab.setPixmap(self.blob_pixmap(size - 2))
        else:
            frames = self.pack_frames(name, size - 2)
            if frames:
                pm = self.core.to_pixmap(frames[0]['idle'][0][0])
                pm.setDevicePixelRatio(self.devicePixelRatioF())
                lab.setPixmap(pm)
        return lab

    def animate(self):
        """Home preview plays the current character."""
        if not self.preview or not self.isVisible():
            return
        self.frame += 3
        if self.app.pack:
            frames = self.pack_frames(self.app.settings['character'], 110)
            if frames:
                seq = frames[0]['idle'][0]
                pm = self.core.to_pixmap(seq[int(self.frame * frames[1] / 30) % len(seq)])
                pm.setDevicePixelRatio(self.devicePixelRatioF())
                self.preview.setPixmap(pm)
        else:
            self.preview.setPixmap(self.blob_pixmap(118, 0 if self.frame % 150 < 6 else 150))  # blink now and then

    # --- Home ---
    def page_home(self):
        self.header('', 'Desktop Pet', 'Your little desk buddy', self.core.logo_image(96))
        lay = self.card()
        self.preview = Clickable(self.spawn)
        self.preview = QLabel()
        self.preview.setFixedHeight(130)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setCursor(Qt.PointingHandCursor)
        self.preview.mousePressEvent = lambda e: self.spawn()
        self.preview.setToolTip('Click to send a pet out')
        lay.addWidget(self.preview)
        self.count = QLabel(objectName='muted')
        self.count.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.count)
        lay = self.card(QHBoxLayout)
        name = self.app.settings['character'] if self.app.pack else ''
        lay.addWidget(self.thumb(name))
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(QLabel(name or f"{self.app.settings['style']} (default)", objectName='bold'))
        col.addWidget(QLabel('Character', objectName='muted'))
        lay.addLayout(col, 1)
        lay.addWidget(self.button('Change', lambda: self.pick('characters')))
        lay = self.card()
        self.slider(lay, 'speed', 'Speed', 0.5, 3)
        self.slider(lay, 'size', 'Size', 0.5, 2.5)
        row = QHBoxLayout()
        name = QLabel('Pets')
        name.setFixedWidth(70)
        row.addWidget(name)
        row.addWidget(self.glyph('', lambda: self.step_pets(-1), tip='Fewer'))
        self.pets_value = QLabel(objectName='bold')
        self.pets_value.setFixedWidth(30)
        self.pets_value.setAlignment(Qt.AlignCenter)
        row.addWidget(self.pets_value)
        row.addWidget(self.glyph('', lambda: self.step_pets(1), tip='More'))
        row.addWidget(QLabel('max 10', objectName='muted'))
        row.addStretch(1)
        lay.addLayout(row)
        self.switch_row(self.card(), 'Show pets', 'Hide every pet without quitting. The tray icon can bring them back.',
                        self.app.visible, self.app.set_visible)
        self.behaviour(self.card(QHBoxLayout))
        self.update_count()

    def behaviour(self, lay):
        """Home: a dropdown of check boxes for what pets may do on their own."""
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(QLabel('Behaviour', objectName='bold'))
        col.addWidget(QLabel('What your pets may do on their own.', objectName='muted'))
        lay.addLayout(col, 1)
        off = self.app.settings['off']
        b = self.button(f'{len(BEHAVIOUR) - len(off)} of {len(BEHAVIOUR)} on  ▾', lambda: None)
        menu = QMenu(b)
        for key, name in BEHAVIOUR.items():
            box = QCheckBox(name)  # check boxes in the menu: it stays open while you tick several
            box.setChecked(key not in off)
            box.setCursor(Qt.PointingHandCursor)
            box.setStyleSheet('padding: 5px 10px;')

            def toggled(on, k=key):
                now = [a for a in self.app.settings['off'] if a != k] + ([] if on else [k])
                self.app.settings['off'] = now
                self.app.apply()
                b.setText(f'{len(BEHAVIOUR) - len(now)} of {len(BEHAVIOUR)} on  ▾')
            box.toggled.connect(toggled)
            act = QWidgetAction(menu)
            act.setDefaultWidget(box)
            menu.addAction(act)
        b.clicked.disconnect()
        b.clicked.connect(lambda: menu.exec(b.mapToGlobal(b.rect().bottomLeft())))
        lay.addWidget(b, 0, Qt.AlignVCenter)

    def step_pets(self, d):
        v = max(0, min(10, self.app.settings['pets'] + d))
        if v != self.app.settings['pets']:
            self.change('pets', v)

    def update_count(self):
        if not self.count:
            return
        n = len(self.app.pets)
        hint = 'Click to send one out' if n < 10 else 'That is all 10 of them!'
        self.count.setText(f'{hint}  ·  {n} on your desk')
        self.pets_value.setText(str(n))

    def spawn(self):
        """Home: clicking the character sends a new pet onto the desktop."""
        self.app.add()
        if not self.app.visible:
            self.app.set_visible(True)
        self.update_count()

    # --- sub-tabs (Characters, Customize) ---
    def subtabs(self, page, tabs):
        current = self.subtab.setdefault(page, tabs[0][0])
        row = QHBoxLayout()
        row.setSpacing(4)
        for name, icon, _ in tabs:
            on = name == current
            b = QPushButton(f'{name}')
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f'background: {self.c["card"] if on else "transparent"}; border-radius: 9px;'
                            f'padding: 7px 14px; font-weight: {600 if on else 400};'
                            f'color: {self.c["text"] if on else self.c["muted"]};')
            b.clicked.connect(lambda _=0, n=name: self.pick_subtab(page, n))
            row.addWidget(b)
        row.addStretch(1)
        self.body.addLayout(row)
        dict((n, f) for n, _, f in tabs)[current](self.card())

    def pick_subtab(self, page, name):
        if self.subtab.get(page) != name:
            self.subtab[page] = name
            self.build_pages()

    # --- Characters ---
    def page_characters(self):
        self.header('', 'Characters', 'Pick who lives on your desk')
        self.subtabs('characters', (('Characters', '', self.sub_packs), ('Blob look', '', self.sub_blob)))

    def sub_packs(self, lay):
        row = QHBoxLayout()
        row.addWidget(self.button('+ Add .zip', self.add_zip, 'primary'))
        row.addWidget(self.button('Add folder', self.add_folder))
        row.addWidget(self.button('Open folder', self.open_packs))
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(QLabel(self.status or 'Drop a pack folder or .zip anywhere on this tab.',
                             objectName='accent' if self.status else 'muted'))
        current = self.app.settings['character'] if self.app.pack else ''
        entries = [('', 'Default blob', 'Built in · change its look in Blob look')]
        entries += [(n, m.get('name') if isinstance(m.get('name'), str) else n,
                     f"by {m['author']}" if isinstance(m.get('author'), str) else 'Character pack')
                    for n, m in packs.list_packs(self.core.PACKS_DIR)]
        for name, title, sub in entries:
            active = name == current
            r = Clickable(lambda n=name: self.change('character', n), 'rowOn' if active else 'row')
            h = QHBoxLayout(r)
            h.setContentsMargins(8, 6, 8, 6)
            h.addWidget(self.thumb(name))
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(QLabel(title, objectName='bold'))
            col.addWidget(QLabel(sub, objectName='muted'))
            h.addLayout(col, 1)
            if active:
                ok = QLabel('')
                ok.setStyleSheet(f'font-family: "{ICONS}"; font-size: 14px; color: {self.c["acc"]}; background: transparent;')
                h.addWidget(ok)
            if name:
                path = os.path.join(self.core.PACKS_DIR, name)
                h.addWidget(self.glyph('', lambda p=path: os.startfile(p), tip='Open its folder'))
                h.addWidget(self.glyph('', lambda n=name: self.delete(n), DANGER, 'Delete'))
            lay.addWidget(r)

    def sub_blob(self, lay):
        st = self.app.settings
        row = QHBoxLayout()
        row.addWidget(QLabel('Style'))
        combo = QComboBox()
        combo.addItems(list(self.core.BLOB_STYLES))
        combo.setCurrentText(st['style'])
        combo.currentTextChanged.connect(lambda v: self.change('style', v))
        row.addWidget(combo)
        row.addStretch(1)
        prev = QLabel()
        prev.setPixmap(self.blob_pixmap(60))
        row.addWidget(prev)
        lay.addLayout(row)
        lay.addWidget(QLabel('Color', objectName='section'))
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, (n, col) in enumerate(COLORS):
            b = self.button(n, lambda _=0, v=col: self.change('color', v))
            b.setIcon(QIcon(self.core.to_pixmap(dot_icon(col))))
            b.setIconSize(QSize(14, 14))
            b.setStyleSheet('text-align: left; padding: 7px 10px;' +
                            (f'border: 2px solid {self.c["acc"]};' if col == st['color'] else ''))
            grid.addWidget(b, i // 3, i % 3)
        lay.addLayout(grid)
        lay.addWidget(self.button('Custom color...', self.pick_color), 0, Qt.AlignLeft)

    def import_pack(self, path):
        try:
            names = packs.import_pack(path, self.core.PACKS_DIR)
            self.status = f'Added {", ".join(names)}.' if len(names) < 4 else f'Added {len(names)} characters.'
            self.change('character', names[0])
        except ValueError as err:
            self.status = f"Couldn't add {os.path.basename(os.path.normpath(path))}: {err}"
            self.build_pages()

    def add_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose a character pack', '', 'Character pack (*.zip)')
        if path:
            self.import_pack(path)

    def add_folder(self):
        path = QFileDialog.getExistingDirectory(self, 'Choose a character pack folder')
        if path:
            self.import_pack(path)

    def open_packs(self):
        os.makedirs(self.core.PACKS_DIR, exist_ok=True)
        os.startfile(self.core.PACKS_DIR)

    def confirm(self, title, text):
        return QMessageBox.question(self, title, text) == QMessageBox.Yes

    def delete(self, name):
        if not self.confirm('Delete character', f'Delete "{name}"? Its files are removed.'):
            return
        packs.delete_pack(self.core.PACKS_DIR, name)
        self.thumbs = {k: v for k, v in self.thumbs.items() if k[0] != name}
        self.status = f'Deleted {name}.'
        self.change('character', '' if self.app.settings['character'] == name else self.app.settings['character'])

    def pick_color(self):
        c = QColorDialog.getColor(QColor(self.app.settings['color']), self, 'Pet color')
        if c.isValid():
            self.change('color', c.name())

    # --- Customize ---
    def page_customize(self):
        self.header('', 'Customize', 'Make this window yours')
        self.subtabs('customize', (('Themes', '', self.sub_themes), ('Colors', '', self.sub_accent),
                                   ('Font', '', self.sub_font)))

    def sub_themes(self, lay):
        lay.addWidget(QLabel('A theme sets the whole look. Change its accent in Colors.', objectName='muted'))
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (name, (tbg, tcard, tacc, ttext, _)) in enumerate(self.core.THEMES.items()):
            on = name == self.app.settings['theme']
            tile = Clickable(lambda n=name: self.set_theme(n))
            tile.setFixedHeight(70)
            tile.setStyleSheet(f'background: {tbg}; border-radius: 10px;'
                               f'border: 2px solid {self.c["acc"] if on else tcard};')
            v = QVBoxLayout(tile)
            v.setContentsMargins(10, 10, 10, 8)
            top = QHBoxLayout()
            strip = QFrame()
            strip.setFixedHeight(12)
            strip.setStyleSheet(f'background: {tcard}; border: none; border-radius: 5px;')
            top.addWidget(strip, 1)
            more = QPushButton('')
            more.setFixedSize(24, 24)
            more.setCursor(Qt.PointingHandCursor)
            more.setStyleSheet(f'font-family: "{ICONS}"; font-size: 10px; padding: 0; border: none; color: {ttext};'
                               f'background: {shade(tbg, 0.8 if name == "Light" else 1.9)}; border-radius: 12px;')
            more.clicked.connect(lambda _=0, n=name, b=more: self.theme_menu(n, b))
            top.addWidget(more)
            v.addLayout(top)
            low = QHBoxLayout()
            lab = QLabel(name)
            lab.setStyleSheet(f'color: {ttext}; font-weight: 600; border: none; background: transparent;')
            low.addWidget(lab)
            low.addStretch(1)
            dot = QFrame()
            dot.setFixedSize(12, 12)
            dot.setStyleSheet(f'background: {tacc}; border: none; border-radius: 6px;')
            low.addWidget(dot)
            v.addLayout(low)
            grid.addWidget(tile, i // 2, i % 2)
        lay.addLayout(grid)

    def theme_menu(self, name, button):
        m = QMenu(self)
        m.addAction(f'Use {name}', lambda: self.set_theme(name))
        m.addAction(f'Use {name}, keep my accent', lambda: self.change('theme', name))
        m.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def set_theme(self, name):
        self.app.settings['accent'] = ''  # a theme brings its own accent
        self.change('theme', name)

    def sub_accent(self, lay):
        lay.addWidget(QLabel('Accent color', objectName='section'))
        lay.addWidget(QLabel('Buttons, sliders, switches and the active tab.', objectName='muted'))
        row = QHBoxLayout()
        row.setSpacing(4)
        for col in ACCENTS:
            sw = Clickable(lambda v=col: self.change('accent', v))
            sw.setFixedSize(32, 32)
            h = QHBoxLayout(sw)
            h.setContentsMargins(0, 0, 0, 0)
            pic = QLabel()
            pic.setPixmap(self.pixmap(dot_icon(col, self.c['text'] if col.lower() == self.c['acc'].lower() else None), 30))
            h.addWidget(pic)
            row.addWidget(sw)
        row.addStretch(1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(self.button('Pick color...', self.pick_accent))
        row.addWidget(self.button('Theme default', lambda: self.change('accent', '')))
        row.addStretch(1)
        lay.addLayout(row)

    def pick_accent(self):
        c = QColorDialog.getColor(QColor(self.c['acc']), self, 'Accent color')
        if c.isValid():
            self.change('accent', c.name())

    def sub_font(self, lay):
        lay.addWidget(QLabel('Font', objectName='section'))
        have = set(QFontDatabase.families())
        combo = QComboBox()
        combo.addItems([f for f in FONTS if f in have or f + ' Text' in have])
        combo.setCurrentText(self.app.settings['font'])
        combo.currentTextChanged.connect(lambda v: self.change('font', v))
        lay.addWidget(combo, 0, Qt.AlignLeft)
        lay.addWidget(QLabel('The quick brown pet jumps over the taskbar.'))

    # --- Settings ---
    def page_settings(self):
        self.header('', 'Settings', 'How the app behaves')
        for name, fill, color in (('General', self.sec_general, None), ('Screens', self.sec_screens, None),
                                  ('Updates', self.sec_updates, None), ('About', self.sec_about, None),
                                  ('Danger zone', self.sec_danger, DANGER)):
            lay = self.card()
            head = Clickable(lambda: None)
            h = QHBoxLayout(head)
            h.setContentsMargins(0, 0, 0, 0)
            t = QLabel(name, objectName='section')
            chev = QLabel()
            for w in (t, chev):
                w.setStyleSheet((f'color: {color};' if color else '') + 'background: transparent;')
            chev.setStyleSheet(chev.styleSheet() + f'font-family: "{ICONS}"; font-size: 11px;')
            h.addWidget(t, 1)
            h.addWidget(chev)
            lay.addWidget(head)
            content = QWidget()
            content.setStyleSheet('background: transparent;')
            inner = QVBoxLayout(content)
            inner.setContentsMargins(0, 4, 0, 0)
            fill(inner)
            lay.addWidget(content)

            def toggle(n=name, c=content, ch=chev):
                self.open_sections ^= {n}
                c.setVisible(n in self.open_sections)
                ch.setText('' if n in self.open_sections else '')
            head.on_click = toggle
            content.setVisible(name in self.open_sections)
            chev.setText('' if name in self.open_sections else '')
        self.body.addWidget(QLabel(f'Desktop Pet v{self.core.VERSION}', objectName='muted'), 0, Qt.AlignHCenter)

    def sec_general(self, lay):
        self.switch_row(lay, 'Start with Windows', 'Open Desktop Pet automatically when you log in.',
                        self.core.autostart(), self.core.autostart)

    def sec_screens(self, lay):
        lay.addWidget(QLabel('Pets only walk on the screens you tick.', objectName='muted'))
        self.mon_boxes = []
        for i, (name, (L, T, R, B)) in enumerate(self.core.all_monitors()):
            box = QCheckBox(f'Screen {i + 1}' + ('  ·  main' if i == 0 else '') + f'   {R - L} x {B - T}')
            box.setChecked(not self.app.settings['monitors'] or name in self.app.settings['monitors'])
            box.setCursor(Qt.PointingHandCursor)
            box.toggled.connect(self.change_monitors)
            lay.addWidget(box)
            self.mon_boxes.append((name, box))

    def change_monitors(self):
        on = [name for name, box in self.mon_boxes if box.isChecked()]
        self.change('monitors', [] if len(on) in (0, len(self.mon_boxes)) else on)  # [] = all monitors

    def sec_updates(self, lay):
        if not self.core.FROZEN:
            lay.addWidget(QLabel('Running from source: updates arrive with git pull.', objectName='muted'))
            return
        row = QHBoxLayout()
        self.upd_btn = self.button('Check for updates', self.check_updates, 'primary')
        self.upd_status = QLabel(objectName='muted')
        row.addWidget(self.upd_btn)
        row.addWidget(self.upd_status, 1)
        lay.addLayout(row)

    def check_updates(self):
        self.upd_btn.setEnabled(False)
        self.upd_status.setText('checking...')
        result = []
        threading.Thread(target=lambda: result.append(self.core.download_update()), daemon=True).start()

        def wait():  # the thread only fills `result`; the window reads it here, on its own thread
            if not result:
                QTimer.singleShot(300, wait)
            elif result[0] == 'downloaded' and self.core.apply_update():
                self.app.quit()  # the new version starts on its own
            else:
                self.upd_status.setText({'latest': 'up to date', 'failed': "couldn't check"}.get(result[0], ''))
                self.upd_btn.setEnabled(True)
        wait()

    def sec_about(self, lay):
        lay.addWidget(QLabel(f'Desktop Pet v{self.core.VERSION}\nMade by yuvancantcodeforshit', objectName='muted'))
        row = QHBoxLayout()
        row.addWidget(self.button('GitHub page', lambda: webbrowser.open(f'https://github.com/{self.core.REPO}')))
        row.addWidget(self.button('Settings folder', lambda: (os.makedirs(self.core.SETTINGS_DIR, exist_ok=True),
                                                              os.startfile(self.core.SETTINGS_DIR))))
        row.addStretch(1)
        lay.addLayout(row)

    def sec_danger(self, lay):
        d = QLabel('Put every setting back to default. Your character packs stay.', objectName='muted')
        d.setWordWrap(True)
        lay.addWidget(d)
        lay.addWidget(self.button('Reset all settings', self.reset, 'danger'), 0, Qt.AlignLeft)

    def reset(self):
        if self.confirm('Reset settings', 'Reset every setting to its default?'):
            self.app.settings.clear()
            self.app.settings.update({k: list(v) if isinstance(v, list) else v for k, v in self.core.DEFAULTS.items()})
            self.change('theme', self.core.DEFAULTS['theme'])
