"""Settings window: right-click a pet > Settings, or click the tray icon.
Qt (PySide6): its own dark title bar (minimize / hide to tray / close), four tabs in a side bar,
themes, accent colour and font. Every change applies to the pets at once and is saved.
"""
import colorsys, ctypes, os, sys, threading, webbrowser

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QCursor, QFont, QFontDatabase, QGuiApplication, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QAbstractButton, QCheckBox, QColorDialog, QComboBox, QFrame, QGridLayout,
                               QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSlider,
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
             'climb': 'Climb walls', 'jump': 'Jump onto windows'}  # pet.ACTIONS ('chase' is kept there for old settings)
# (title, where it is, search words, tab, sub-tab, section, advanced): what the search box can jump to
SEARCH = (
    ('Speed', 'Home', 'speed fast slow walk', 'home', None, None, False),
    ('Size', 'Home', 'size scale big small', 'home', None, None, False),
    ('Pets', 'Home · how many', 'pets count number add remove spawn', 'home', None, None, False),
    ('Show pets', 'Home', 'show hide visible tray', 'home', None, None, False),
    ('Behaviour', 'Home', 'behaviour behavior walk run sit lie dance climb jump actions', 'home', None, None, False),
    ('Day and night', 'Home · schedule', 'schedule night day calm active sleep time hours', 'home', None, None, False),
    ('Characters', 'Pick, add or delete', 'character pack zip import folder shimeji delete', 'characters', 'Characters', None, False),
    ('Fall style', 'Characters > Tweaks', 'tweak fall steady free gravity character', 'characters', 'Tweaks', None, False),
    ('Laptop', 'Characters > Tweaks', 'tweak laptop sit code yellow', 'characters', 'Tweaks', None, False),
    ('Staff sparkles', 'Characters > Tweaks', 'tweak sparkles staff yellow fall', 'characters', 'Tweaks', None, False),
    ('Crash height', 'Characters > Tweaks', 'tweak crash landing height', 'characters', 'Tweaks', None, True),
    ('Lines he types', 'Characters > Tweaks', 'tweak code typed lines yellow laptop', 'characters', 'Tweaks', None, True),
    ('Blob look', 'Style and colour of the default pet', 'blob style color colour default', 'characters', 'Blob look', None, False),
    ('Themes', 'Customize', 'theme dark light midnight ocean forest sunset grape', 'customize', 'Themes', None, False),
    ('Accent color', 'Customize', 'accent color colour auto character', 'customize', 'Colors', None, False),
    ('Font', 'Customize', 'font text typeface', 'customize', 'Font', None, False),
    ('Start with Windows', 'Settings > General', 'startup autostart login boot windows', 'settings', None, 'General', False),
    ('Advanced options', 'Settings > General', 'advanced simple deep options', 'settings', None, 'General', False),
    ('Screens', 'Which monitors pets walk on', 'screen monitor display', 'settings', None, 'Screens', False),
    ('Physics', 'Gravity, throw, swing, spin', 'physics gravity throw swing damping spin', 'settings', None, 'Physics', True),
    ('Updates', 'Settings', 'update version check', 'settings', None, 'Updates', False),
    ('About', 'Settings', 'about version', 'settings', None, 'About', False),
    ('Danger zone', 'Settings', 'danger reset delete uninstall quit', 'settings', None, 'Danger zone', False),
)
RESTYLE = {'theme', 'accent', 'font', 'character'}  # redraw the whole window (the accent follows the character)
REFRESH = {'style', 'color', 'advanced'}                  # rebuild the pages that show the blob; sliders redraw nothing
SIDE = 76  # side bar width
W, H, MIN_H = 460 + SIDE, 660, 360  # width is fixed; only the height can be dragged
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


def rgba(hex_color, a):
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f'rgba({r},{g},{b},{int(a * 255)})'


_ACCENTS = {}  # character -> its main colour (or None); packs rarely change, so cached for the run


def char_accent(core, name):
    """Main colour of a character's idle picture: the average of its most common saturated hue."""
    if name not in _ACCENTS:
        out = None
        try:
            im = packs.load_frames(os.path.join(core.PACKS_DIR, name), 48)[0]['idle'][0][0].convert('RGBA')
            hues = {}
            for r, g, b, a in im.getdata():
                h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
                if a > 200 and s > 0.4 and v > 0.35:
                    hues.setdefault(int(h * 12) % 12, []).append((r, g, b))
            if hues:
                px = max(hues.values(), key=len)
                out = '#%02x%02x%02x' % tuple(sum(p[i] for p in px) // len(px) for i in range(3))
        except Exception:  # no idle picture, broken pack: the theme's own accent is used instead
            pass
        _ACCENTS[name] = out
    return _ACCENTS[name]


def accent_of(core, s):
    """Your picked accent, else the character's colour, else the theme's."""
    return s['accent'] or (s['character'] and char_accent(core, s['character'])) or core.THEMES[s['theme']][2]


def menu_qss(core, s):
    """Right-click and tray menus in the Settings theme (they are not part of the Settings window)."""
    bg, card, _, text, _ = core.THEMES[s['theme']]
    acc, light = accent_of(core, s), s['theme'] == 'Light'
    edge = shade(card, 0.88) if light else shade(card, 1.32)
    return (f'QMenu {{ background: {card}; color: {text}; border: 1px solid {edge}; padding: 4px; }}'
            f'QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}'
            f'QMenu::item:selected {{ background: {acc}; color: {ink(acc)}; }}'
            f'QMenu::separator {{ height: 1px; background: {edge}; margin: 4px 8px; }}')


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

    def press(self, down):
        """Pressed look the instant the button goes down (dimmed), gone when it comes up or the mouse leaves."""
        if down and not self.graphicsEffect():
            e = QGraphicsOpacityEffect(self)
            e.setOpacity(0.6)
            self.setGraphicsEffect(e)
        elif not down and self.graphicsEffect():
            self.setGraphicsEffect(None)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.press(True)

    def mouseMoveEvent(self, e):  # drag off cancels, drag back on re-arms
        self.press(bool(e.buttons() & Qt.LeftButton) and self.rect().contains(e.position().toPoint()))

    def mouseReleaseEvent(self, e):
        self.press(False)
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.on_click()


class SettingsWindow(QWidget):
    def __init__(self, app, core, tab='home'):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Window)  # our own title bar, still on the taskbar
        self.app, self.core, self.tab = app, core, tab
        self.subtab = {}        # page -> chosen sub-tab
        self.edit_char = ''     # character shown on Characters > Tweaks
        self.open_sections = {'General'}
        self.status = ''        # message on the Characters tab (import result)
        self.thumbs = {}        # (pack name, px) -> loaded frames, kept for the window's life
        self.frame = 0
        self.drag_from = None
        self.fades = {}         # running child fades: slot -> (animation, clean-up)
        self.setWindowTitle('Desktop Pet')
        self.setAcceptDrops(True)
        self.setFixedWidth(W)
        self.resize(W, H)
        self.setWindowOpacity(0)
        self.setAttribute(Qt.WA_TranslucentBackground)  # Mica shows through (Windows 11)
        self.setAttribute(Qt.WA_StyledBackground)
        self.mica = sys.getwindowsversion().build >= 22621
        self.restyle()
        QShortcut(QKeySequence('Ctrl+F'), self, lambda: self.search.setFocus())
        self.anim = self.every(100, self.animate)
        self.place()
        self.show()
        self.round_corners()
        self.fade(1)

    def paintEvent(self, _):
        # the window paints its own background: unpainted (alpha 0) pixels of a translucent window let clicks
        # fall through to the window behind, which then covers this one
        QPainter(self).fillRect(self.rect(), self.fill)

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
        self.set_backdrop()

    def set_backdrop(self):
        """Windows 11 Mica behind the window, dark or light with the theme. Fails: plain opaque background."""
        try:
            h, dwm = ctypes.c_void_p(int(self.winId())), ctypes.windll.dwmapi
            dwm.DwmSetWindowAttribute(h, 20, ctypes.byref(ctypes.c_int(self.app.settings['theme'] != 'Light')), 4)
            ok = (dwm.DwmExtendFrameIntoClientArea(h, ctypes.byref((ctypes.c_int * 4)(-1, -1, -1, -1))) == 0
                  and dwm.DwmSetWindowAttribute(h, 38, ctypes.byref(ctypes.c_int(2)), 4) == 0)  # 38 = backdrop, 2 = Mica
        except (OSError, AttributeError):
            ok = False
        if self.mica and not ok:
            self.mica = False
            self.restyle()

    def fade(self, to, then=None):
        """Ease the window's opacity to `to` (~130 ms, ease-out); instant if Windows animations are off."""
        if getattr(self, 'fader', None):
            self.fader.stop()  # interrupted: the new fade starts from the current opacity; the old `then` never runs
        a = self.fader = QPropertyAnimation(self, b'windowOpacity', self)
        a.setDuration(130 if animations_on() else 0)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.setEndValue(to)
        if then:
            a.finished.connect(then)
        a.start()

    def fade_child(self, slot, w, to, ms, done):
        """Ease a child widget's opacity from 1-`to` to `to` (ease-out), then run `done`.
        A newer fade in the same slot finishes the old one at once, so nothing is left half-faded."""
        old = self.fades.pop(slot, None)
        if old:
            old[0].stop()
            old[1]()
        e = QGraphicsOpacityEffect(w)
        e.setOpacity(1 - to)
        w.setGraphicsEffect(e)
        a = QPropertyAnimation(e, b'opacity', self)
        a.setDuration(ms)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.setEndValue(float(to))

        def finish():
            self.fades.pop(slot, None)
            try:
                done()
            except RuntimeError:  # the widget was rebuilt away meanwhile
                pass
        a.finished.connect(finish)
        self.fades[slot] = (a, finish)
        a.start()

    def fade_in(self, page):
        """Tab switch: the new page fades in (~120 ms); the effect is dropped after so scrolling stays cheap."""
        self.fade_child('page', page, 1, 120, lambda: page.setGraphicsEffect(None))

    def crossfade(self, change):
        """Theme / accent / font: snapshot the old look, apply `change`, then fade the snapshot away (~180 ms).
        Mouse goes straight through the snapshot, so the new look is usable at once."""
        if not (self.isVisible() and animations_on()):
            return change()
        shot = QLabel(self)
        shot.setPixmap(self.grab())  # includes any snapshot still fading: starts from what is on screen
        shot.setAttribute(Qt.WA_TransparentForMouseEvents)
        shot.setGeometry(self.rect())
        change()
        shot.show()
        shot.raise_()
        self.fade_child('look', shot, 0, 180, shot.deleteLater)

    def show_tab(self, tab):
        """Open on a tab (tray / right-click / second launch): bring the window back the way it left."""
        self.pick(tab)
        if not self.isVisible() or self.isMinimized():
            self.setWindowOpacity(0)
            self.showNormal()
            self.fade(1)
        elif self.windowOpacity() < 1:  # caught mid-fade: turn around from where it is
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
        acc = accent_of(self.core, s)
        light = s['theme'] == 'Light'
        a = self.mica  # translucent layers over Mica; plain colours when there is none
        self.fill = QColor(bg)
        self.fill.setAlphaF(0.7 if a else 1.0)
        self.c = c = dict(light=light, bg=bg, card=card, acc=acc, text=text, muted=muted, on_acc=ink(acc),
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
            QDialog {{ background: {bg}; }}
            QScrollArea, QScrollArea > QWidget, QStackedWidget, #page {{ background: transparent; border: none; }}
            #card {{ background: {rgba(card, 0.8) if a else card}; border: 1px solid {c['border']}; border-radius: 14px; }}
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
            #primary:pressed {{ background: {shade(c['acc'], 0.8)}; }}
            #danger {{ background: {DANGER}; color: #ffffff; font-weight: 600; }}
            #danger:hover {{ background: {shade(DANGER, 0.9)}; }}
            #danger:pressed {{ background: {shade(DANGER, 0.8)}; }}
            #glyph {{ font-family: "{ICONS}"; font-size: 12px; padding: 0; min-width: 32px; min-height: 28px; }}
            #chrome {{ font-family: "{ICONS}"; font-size: 10px; background: transparent; border-radius: 15px;
                       min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; padding: 0; }}
            #chrome:hover {{ background: {c['btn_hover']}; }}
            #chrome:pressed {{ background: {shade(c['btn_hover'], 0.85 if light else 1.2)}; }}
            #close:hover {{ background: {CLOSE_RED}; color: #ffffff; }}
            #close:pressed {{ background: {shade(CLOSE_RED, 0.85)}; color: #ffffff; }}
            #side {{ background: {rgba(card, 0.45) if a else card}; border-right: 1px solid {c['border']}; }}
            #tab {{ border-radius: 10px; }}
            #tab:hover {{ background: {c['hover']}; }}
            #tab QLabel {{ background: transparent; }}
            #grip {{ background: transparent; }}
            QSlider::groove:horizontal {{ height: 4px; background: {c['border']}; border-radius: 2px; }}
            QSlider::sub-page:horizontal {{ background: {c['acc']}; border-radius: 2px; }}
            QSlider::handle:horizontal {{ background: {c['acc']}; width: 18px; height: 18px; margin: -7px 0;
                                          border-radius: 9px; border: 2px solid {c['bg']}; }}
            QLineEdit {{ background: {c['hover']}; border: 1px solid transparent; border-radius: 14px; padding: 4px 12px; }}
            QLineEdit:focus {{ border: 1px solid {c['acc']}; }}
            #results {{ background: {c['card']}; border: 1px solid {c['border']}; border-radius: 12px; margin: 6px 14px 0 14px; }}
            QPlainTextEdit {{ background: {c['hover']}; border: none; border-radius: 8px; padding: 6px;
                              font-family: "Cascadia Mono", Consolas; font-size: 12px; }}
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
        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self.sidebar())
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(self.results)
        col.addWidget(self.stack, 1)
        body.addLayout(col, 1)
        root.addLayout(body, 1)
        grip = QFrame(objectName='grip')
        grip.setFixedHeight(6)
        grip.setCursor(Qt.SizeVerCursor)
        grip.setAttribute(Qt.WA_TransparentForMouseEvents)  # the window itself handles the drag
        root.addWidget(grip)
        self.build_pages()
        if self.isVisible():
            self.set_backdrop()  # dark or light Mica follows the theme

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
        for lab in self.stack.findChildren(QLabel):  # QSS has no letter-spacing: tighten big headings here
            if lab.objectName() in ('title', 'section'):
                lab.ensurePolished()
                f = lab.font()
                f.setLetterSpacing(QFont.AbsoluteSpacing, -0.4 if lab.objectName() == 'title' else -0.15)
                lab.setFont(f)
        self.pick(self.tab, fade=False)

    def pick(self, tab, fade=True):
        self.tab = tab
        page = self.pages[tab]
        if fade and page is not self.stack.currentWidget() and self.isVisible() and animations_on():
            self.fade_in(page)
        self.stack.setCurrentWidget(page)
        c = self.c
        for key, (icon, name, bar) in self.tab_parts.items():
            on = key == tab
            icon.setStyleSheet(f'color: {c["acc"] if on else c["muted"]}; font-family: "{ICONS}"; font-size: 18px;')
            name.setStyleSheet(f'color: {c["text"] if on else c["muted"]}; font-size: 11px;'
                               f'font-weight: {600 if on else 400};')
            bar.setStyleSheet(f'background: {c["acc"] if on else "transparent"}; border-radius: 1px;')
            self.tab_boxes[key].setStyleSheet(f'#tab {{ background: {c["hover"]}; border-radius: 10px; }}' if on else '')

    # --- search (title bar) ---
    def make_search(self, row):
        # results sit in the layout, above the page (a floating child or window got clipped on Mica)
        self.results = QFrame(objectName='results')
        self.results.hide()
        QVBoxLayout(self.results).setContentsMargins(6, 6, 6, 6)
        self.hits = []
        box = self.search = QLineEdit(objectName='search')
        box.setPlaceholderText('Search settings  (Ctrl+F)')
        box.setClearButtonEnabled(True)
        box.setFixedWidth(200)
        box.textChanged.connect(self.show_results)
        box.returnPressed.connect(lambda: self.hits and self.go(self.hits[0]))
        esc = QShortcut(QKeySequence('Esc'), box)
        esc.setContext(Qt.WidgetShortcut)
        esc.activated.connect(box.clear)
        row.addSpacing(10)
        row.addWidget(box)

    def show_results(self, text):
        words = text.lower().split()
        self.hits = [e for e in SEARCH if all(w in f'{e[0]} {e[1]} {e[2]}'.lower() for w in words)] if words else []
        lay = self.results.layout()
        while lay.count():
            w = lay.takeAt(0).widget()
            w.setParent(None)  # gone at once, so old rows never show under the new ones
            w.deleteLater()
        if not words:
            self.results.hide()
            return
        for e in self.hits[:6]:
            r = Clickable(lambda e=e: self.go(e), 'row')
            col = QVBoxLayout(r)
            col.setContentsMargins(8, 4, 8, 4)
            col.setSpacing(0)
            col.addWidget(QLabel(e[0], objectName='bold'))
            hint = e[1] + (' · Advanced' if e[6] and not self.app.settings['advanced'] else '')
            col.addWidget(QLabel(hint, objectName='muted'))
            lay.addWidget(r)
        if not self.hits:
            lay.addWidget(QLabel('Nothing matches', objectName='muted'))
        self.results.show()

    def go(self, hit):
        """Jump to a setting: its tab, sub-tab and section (Advanced ones switch Advanced on)."""
        _, _, _, tab, sub, section, adv = hit
        self.search.clear()
        if adv and not self.app.settings['advanced']:
            self.app.settings['advanced'] = True
            self.app.apply()
        if sub:
            self.subtab[tab] = sub
        if section:
            self.open_sections.add(section)
        self.tab = tab
        self.build_pages()
        if section:
            QTimer.singleShot(60, lambda: self.pages['settings'].ensureWidgetVisible(self.section_frames[section]))

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
        self.make_search(row)
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

    def sidebar(self):
        bar = QFrame(objectName='side')
        bar.setFixedWidth(SIDE)
        col = QVBoxLayout(bar)
        col.setContentsMargins(8, 10, 8, 10)
        col.setSpacing(4)
        self.tab_parts, self.tab_boxes = {}, {}
        for key, icon, name in TABS:
            t = Clickable(lambda k=key: self.pick(k), 'tab')
            t.setFixedHeight(58)
            row = QHBoxLayout(t)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(0)
            mark = QFrame()  # accent bar on the active tab
            mark.setFixedSize(3, 22)
            lab = QVBoxLayout()
            lab.setSpacing(2)
            parts = (QLabel(icon), QLabel(name), mark)
            for p in parts[:2]:
                lab.addWidget(p, 0, Qt.AlignHCenter)
            row.addWidget(mark, 0, Qt.AlignVCenter)
            row.addLayout(lab, 1)
            row.addSpacing(3)
            col.addWidget(t)
            self.tab_parts[key], self.tab_boxes[key] = parts, t
        col.addStretch(1)
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
        sh = QGraphicsDropShadowEffect(f)  # soft shadow lifts the card off the window
        sh.setBlurRadius(24)
        sh.setOffset(0, 3)
        sh.setColor(QColor(0, 0, 0, 40 if self.c['light'] else 110))
        f.setGraphicsEffect(sh)
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

    def slider(self, lay, key, text, lo, hi, w=70):
        row = QHBoxLayout()
        name = QLabel(text)
        name.setFixedWidth(w)
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
            self.crossfade(self.restyle)
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

    def preview_px(self):
        """Preview size follows the Size slider (in steps of 10, so dragging does not reload pictures each tick)."""
        return max(40, min(125, round(80 * self.app.settings['size'] / 10) * 10))

    def animate(self):
        """Home preview plays the current character: as big as Size, walking at Speed."""
        if not self.preview or not self.isVisible():
            return
        s = self.app.settings
        self.frame += 3
        px = self.preview_px()
        if self.app.pack:
            frames = self.pack_frames(s['character'], px)
            if frames:
                seq = frames[0]['walk' if 'walk' in frames[0] else 'idle'][0]
                pm = self.core.to_pixmap(seq[int(self.frame * frames[1] / 30 * s['speed']) % len(seq)])
                pm.setDevicePixelRatio(self.devicePixelRatioF())
                self.preview.setPixmap(pm)
        else:
            self.preview.setPixmap(self.blob_pixmap(px, 0 if self.frame % 150 < 6 else 150))  # blink now and then

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
        self.schedule(self.card())
        self.update_count()

    def schedule(self, lay):
        """Home: calmer at night, livelier by day."""
        s = self.app.settings['schedule']
        self.switch_row(lay, 'Day and night', 'Calmer and sitting more at night, livelier by day.', s['on'],
                        lambda on: self.set_schedule('on', on))
        if not s['on']:
            return
        row = QHBoxLayout()
        for label, key in (('Night from', 'from'), ('until', 'to')):
            row.addWidget(QLabel(label))
            box = QComboBox()
            box.addItems([f'{h:02d}:00' for h in range(24)])
            box.setCurrentIndex(s[key])
            box.setStyleSheet('min-width: 70px;')
            box.currentIndexChanged.connect(lambda i, k=key: self.set_schedule(k, i))
            row.addWidget(box)
        row.addStretch(1)
        lay.addLayout(row)
        now = self.core.mood(self.app.settings)
        lay.addWidget(QLabel('Right now: ' + ('night, calm' if now == 'night' else 'day, lively'), objectName='muted'))

    def set_schedule(self, key, value):
        st = self.app.settings
        st['schedule'] = self.core.clean_schedule({**st['schedule'], key: value})
        self.app.apply()
        if key == 'on':
            self.build_pages()  # the hour pickers appear or go

    def behaviour(self, lay):
        """Home: a dropdown of check boxes for what pets may do on their own."""
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(QLabel('Behaviour', objectName='bold'))
        col.addWidget(QLabel('What your pets may do on their own.', objectName='muted'))
        lay.addLayout(col, 1)
        off = self.app.settings['off']
        b = self.button(f'{sum(k not in off for k in BEHAVIOUR)} of {len(BEHAVIOUR)} on  ▾', lambda: None)
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
                b.setText(f'{sum(k not in now for k in BEHAVIOUR)} of {len(BEHAVIOUR)} on  ▾')
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
        self.subtabs('characters', (('Characters', '', self.sub_packs), ('Tweaks', '', self.sub_tweaks),
                                       ('Blob look', '', self.sub_blob)))

    def sub_packs(self, lay):
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
                h.addWidget(self.glyph('\ue713', lambda n=name: self.tweak(n), tip='Tweaks'))
                h.addWidget(self.glyph('', lambda n=name: self.delete(n), DANGER, 'Delete'))
            lay.addWidget(r)

    def tweak(self, name):
        """Gear on a character row: open its Tweaks."""
        self.edit_char = name
        self.pick_subtab('characters', 'Tweaks')

    def set_opt(self, name, key, value):
        """Save one option of one character (None = back to its default) and push it to the pets."""
        st = self.app.settings
        mine = dict(st['chars'].get(name, {}))
        if value is None:
            mine.pop(key, None)
        else:
            mine[key] = value
        st['chars'] = self.core.clean_chars({**st['chars'], name: mine})
        self.app.apply()

    def sub_tweaks(self, lay):
        """Options of one character; the ones only some characters have show only for them."""
        st = self.app.settings
        names = [n for n, _ in packs.list_packs(self.core.PACKS_DIR)]
        name = self.edit_char if self.edit_char in names else (st['character'] if st['character'] in names
                                                              else (names[0] if names else ''))
        if not name:
            lay.addWidget(QLabel('Add a character first. The default blob has no tweaks.', objectName='muted'))
            return
        self.edit_char = name
        opt = lambda k: self.core.char_opt(st, name, k)
        row = QHBoxLayout()
        row.addWidget(QLabel('Tweaks for', objectName='bold'))
        pick = QComboBox()
        pick.addItems(names)
        pick.setCurrentText(name)
        pick.currentTextChanged.connect(lambda v: self.tweak(v))
        row.addWidget(pick)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(QLabel('Only this character. Pets pick changes up right away.', objectName='muted'))
        lay.addWidget(QLabel('Falling', objectName='section'))
        row = QHBoxLayout()
        row.addWidget(QLabel('Fall style'))
        fall = QComboBox()
        fall.addItems(['Steady (capped speed)', 'Free fall (full gravity)'])
        fall.setCurrentIndex(0 if opt('fall') == 'steady' else 1)
        fall.currentIndexChanged.connect(lambda i: self.set_opt(name, 'fall', 'steady' if i == 0 else 'free'))
        row.addWidget(fall)
        row.addStretch(1)
        lay.addLayout(row)
        if st['advanced']:
            row = QHBoxLayout()
            row.addWidget(QLabel('Crash height'))
            val = QLabel(f"{opt('crash')} px")
            val.setFixedWidth(60)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(4, 30)  # steps of 50 px: 200..1500
            sl.setValue(max(4, min(30, round(opt('crash') / 50))))
            sl.setCursor(Qt.PointingHandCursor)

            def moved(v):
                val.setText(f'{v * 50} px')
                self.set_opt(name, 'crash', v * 50)
            sl.valueChanged.connect(moved)
            row.addWidget(sl, 1)
            row.addWidget(val)
            lay.addLayout(row)
            lay.addWidget(QLabel('Drops from higher than this end in a crash landing.', objectName='muted'))
        extras = self.core.CHAR_EXTRAS.get(name, ())
        if not st['advanced']:
            lay.addWidget(QLabel('More (crash height' + (', typed lines' if 'code' in extras else '') +
                                 ') is under Settings > General > Advanced options.', objectName='muted', wordWrap=True))
        if extras:
            lay.addWidget(QLabel('Only for ' + name, objectName='section'))
        if 'laptop' in extras:
            self.switch_row(lay, 'Laptop', 'Sits down and codes on his laptop. Off: he just sits.',
                            opt('laptop'), lambda on: self.set_opt(name, 'laptop', on))
        if 'sparkles' in extras:
            self.switch_row(lay, 'Staff sparkles', 'Sparkles fly off his staff when he falls.',
                            opt('sparkles'), lambda on: self.set_opt(name, 'sparkles', on))
        if 'code' in extras and st['advanced']:
            lay.addWidget(QLabel('Lines he types', objectName='bold'))
            lay.addWidget(QLabel('One per line, 40 characters at most. Add " => text" to show what it prints.',
                                 objectName='muted'))
            default = [c + (f' => {o}' if o else '') for c, o in self.core.Pet.CODE]
            box = QPlainTextEdit('\n'.join(opt('code') or default))
            box.setFixedHeight(130)
            lay.addWidget(box)

            def save():
                lines = [''.join(ch for ch in l if ch.isprintable())[:40].rstrip() for l in box.toPlainText().splitlines()]
                lines = [l for l in lines if l.strip()][:20]
                self.set_opt(name, 'code', None if not lines or lines == default else lines)
                self.build_pages()
            row = QHBoxLayout()
            row.addWidget(self.button('Save lines', save, 'primary'))
            row.addWidget(self.button('Reset lines', lambda: (self.set_opt(name, 'code', None), self.build_pages())))
            row.addStretch(1)
            lay.addLayout(row)
        lay.addWidget(self.button('Reset all tweaks for ' + name,
                                  lambda: (self.app.settings['chars'].pop(name, None), self.app.apply(), self.build_pages())),
                      0, Qt.AlignLeft)

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
        lay.addWidget(QLabel('Buttons, sliders, switches and the active tab. Auto follows your character.', objectName='muted'))
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
        row.addWidget(self.button('Auto', lambda: self.change('accent', '')))
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
        self.section_frames = {}
        self.header('', 'Settings', 'How the app behaves')
        adv = (('Physics', self.sec_physics, None),) if self.app.settings['advanced'] else ()
        for name, fill, color in (('General', self.sec_general, None), ('Screens', self.sec_screens, None), *adv,
                                  ('Updates', self.sec_updates, None), ('About', self.sec_about, None),
                                  ('Danger zone', self.sec_danger, DANGER)):
            lay = self.card()
            self.section_frames[name] = lay.parentWidget()
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
        self.switch_row(lay, 'Advanced options', 'Show the deep options: physics, crash height, typed lines.',
                        self.app.settings['advanced'], self.set_advanced)

    def set_advanced(self, on):
        if on:
            self.open_sections.add('Physics')
        self.change('advanced', on)

    def sec_physics(self, lay):
        lay.addWidget(QLabel('Gravity: how fast pets fall. Throw power: how far a flick sends them. '
                             'Swing damping: how fast a held pet stops swinging. Spin speed: how fast they tumble.',
                             objectName='muted', wordWrap=True))
        for key, text, lo, hi in (('gravity', 'Gravity', 0.5, 2), ('throw', 'Throw power', 0.3, 2),
                                  ('damping', 'Swing damping', 0.4, 3), ('spin', 'Spin speed', 0, 2)):
            self.slider(lay, key, text, lo, hi, 100)
        lay.addWidget(self.button('Reset physics', self.reset_physics), 0, Qt.AlignLeft)

    def reset_physics(self):
        for k in ('gravity', 'throw', 'damping', 'spin'):
            self.app.settings[k] = self.core.DEFAULTS[k]
        self.app.apply()
        self.build_pages()

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
