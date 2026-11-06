"""Character packs: a folder or .zip holding one image per pet state, plus an optional pack.json.

    my-cat/
      pack.json    {"name": "My cat", "author": "me", "fps": 8}   (all optional)
      idle.gif     required; animated GIF or still PNG
      walk.gif  fall.png  drag.png  sit.png  climb.gif            optional, missing ones use idle

Images face right; the pet mirrors them when walking left.
"""
import io, json, os, re, shutil, zipfile

from PIL import Image, ImageOps, ImageSequence, ImageTk

STATES = ('idle', 'walk', 'fall', 'drag', 'sit', 'climb', 'ceiling')
EXTS = ('.gif', '.png')
MAX_FILE = 20_000_000    # bytes per image
MAX_SIDE = 2048          # px
MAX_FRAMES = 120         # per animation


def _wanted(name):
    """Pack file name we keep (lowercase), or None. Only known state images and pack.json, nothing else."""
    base = os.path.basename(name).lower()
    stem, ext = os.path.splitext(base)
    return base if base == 'pack.json' or (stem in STATES and ext in EXTS) else None


def _check_image(data):
    """Raise ValueError unless data is a GIF/PNG within the size and frame limits."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ('GIF', 'PNG'):
                raise ValueError(f'{im.format} is not GIF/PNG')
            if max(im.size) > MAX_SIDE or getattr(im, 'n_frames', 1) > MAX_FRAMES:
                raise ValueError(f'image too big (max {MAX_SIDE} px, {MAX_FRAMES} frames)')
            im.load()
    except ValueError:
        raise
    except Exception:
        raise ValueError('a file is not a readable GIF/PNG')


def read_meta(folder):
    try:
        with open(os.path.join(folder, 'pack.json'), encoding='utf-8') as f:
            meta = json.load(f)
        return meta if isinstance(meta, dict) else {}
    except (OSError, ValueError):
        return {}


class _Source:
    """Files of a dropped .zip or folder by relative path (forward slashes), read only on request."""

    def __init__(self, src):
        self.zip = None
        if os.path.isfile(src) and zipfile.is_zipfile(src):
            self.zip = zipfile.ZipFile(src)
            self.sizes = {i.filename: i.file_size for i in self.zip.infolist() if not i.is_dir()}
            self.default = os.path.splitext(os.path.basename(src))[0]
        elif os.path.isdir(src):
            self.root, self.sizes = src, {}
            for dirpath, dirs, names in os.walk(src):
                if dirpath[len(src):].count(os.sep) >= 4:
                    dirs.clear()  # Shimeji keeps its files at most a few folders down
                for n in names:
                    p = os.path.join(dirpath, n)
                    self.sizes[os.path.relpath(p, src).replace(os.sep, '/')] = os.path.getsize(p)
                if len(self.sizes) > 20_000:
                    raise ValueError('that folder is too big to be a pack')
            self.default = os.path.basename(os.path.normpath(src))
        else:
            raise ValueError('drop a pack folder or a .zip')
        self.lower = {n.lower(): n for n in self.sizes}

    def read(self, name):
        name = self.lower.get(name.lower())
        if name is None or self.sizes[name] > MAX_FILE:
            return None
        if self.zip:
            return self.zip.read(name)
        with open(os.path.join(self.root, name), 'rb') as f:
            return f.read()


def _write_pack(packs_dir, name, files):
    """New folder in packs_dir holding files ({basename: bytes}); returns the folder name."""
    name = re.sub(r'[^\w\- ]', '', str(name)).strip()[:40] or 'pack'
    dest, n = os.path.join(packs_dir, name), 2
    while os.path.exists(dest):
        dest, n = os.path.join(packs_dir, f'{name} {n}'), n + 1
    os.makedirs(dest)
    for fname, data in files.items():
        with open(os.path.join(dest, os.path.basename(fname)), 'wb') as f:  # basename: never a path from the pack
            f.write(data)
    return os.path.basename(dest)


def import_pack(src, packs_dir):
    """Copy a pack folder or .zip into packs_dir; also understands Shimeji / Shimeji-ee downloads.
    Returns the new folder names (one Shimeji download can hold several characters).
    Raises ValueError with a reason the user can read."""
    source = _Source(src)
    shimeji = [n for n in source.sizes if n.lower().endswith('conf/actions.xml')]
    if shimeji:
        names, errors = [], []
        for actions in sorted(shimeji)[:MAX_CHARACTERS]:
            try:
                names.append(_import_shimeji(source, actions, packs_dir))
            except ValueError as err:
                errors.append(str(err))
        if not names:
            raise ValueError(errors[0] if errors else 'no Shimeji characters found')
        return names
    files = {}
    for path in source.sizes:
        base = _wanted(path)
        # a folder: its own files only; a zip: also one folder down (people zip the folder itself)
        if base and path.count('/') <= (1 if source.zip else 0):
            data = source.read(path)
            if data is not None:
                files[base] = data
    if not any(n.startswith('idle.') for n in files):
        raise ValueError('a pack needs idle.gif or idle.png')
    for name, data in files.items():
        if name != 'pack.json':
            _check_image(data)
    meta = {}
    if 'pack.json' in files:
        try:
            meta = json.loads(files['pack.json'])
        except ValueError:
            files.pop('pack.json')  # broken metadata: keep the images, drop the file
    return [_write_pack(packs_dir, meta.get('name') if isinstance(meta, dict) and meta.get('name') else source.default,
                        files)]


# Shimeji action names that feed each pet state (first one found wins)
SHIMEJI_ACTIONS = {'idle': ('Stand',), 'walk': ('Walk',), 'fall': ('Falling', 'Fall'), 'drag': ('Pinched', 'Resisting'),
                   'sit': ('Sit',), 'climb': ('ClimbWall', 'GrabWall'), 'ceiling': ('ClimbCeiling', 'GrabCeiling')}
MAX_CHARACTERS = 20
MAX_TICKS = 250  # longest pose we keep, in Shimeji ticks (25 per second)


def parse_shimeji_actions(data):
    """{state: [(image file name, ticks)]} from a Shimeji conf/actions.xml."""
    import xml.etree.ElementTree as ET  # expat in current Python caps entity expansion ("billion laughs")
    if len(data) > 2_000_000:
        raise ValueError('actions.xml is too big')
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise ValueError('actions.xml is not valid XML')
    tag = lambda el: el.tag.rsplit('}', 1)[-1]  # some packs use an XML namespace
    actions = {}
    for el in root.iter():
        if tag(el) == 'Action' and el.get('Name'):
            actions.setdefault(el.get('Name'), el)
    out = {}
    for state, names in SHIMEJI_ACTIONS.items():
        for name in names:
            anims = [a for a in actions.get(name, []) if tag(a) == 'Animation']
            if not anims:
                continue
            # an animation without a Condition is the plain one; Pinched has only swing variants, take the middle
            anim = next((a for a in anims if not a.get('Condition')), anims[len(anims) // 2])
            poses = []
            for p in anim.iter():
                image = (p.get('Image') or '').replace('\\', '/').rsplit('/', 1)[-1]
                if tag(p) != 'Pose' or not image:
                    continue
                try:
                    ticks = int(p.get('Duration', '1'))
                except ValueError:
                    ticks = 1  # script expressions: one tick
                poses.append((image, max(1, min(MAX_TICKS, ticks))))
            if poses:
                out[state] = poses
                break
    return out


def _import_shimeji(source, actions_path, packs_dir):
    """One Shimeji character (its conf/actions.xml plus the images it names) becomes one pack."""
    prefix = actions_path[:-len('conf/actions.xml')]  # e.g. 'pack/img/Blue/' (Shimeji-ee) or 'pack/' (classic)
    states = parse_shimeji_actions(source.read(actions_path) or b'')
    if 'idle' not in states:
        raise ValueError('no Stand animation in actions.xml')
    files = {}
    for folder in (prefix, prefix + 'img/'):  # Shimeji-ee keeps images next to conf/, classic Shimeji in img/
        for poses in states.values():
            for image, _ in poses:
                if image.lower() not in files:
                    data = source.read(folder + image)
                    if data is not None:
                        files[image.lower()] = data
        if files:
            break
    states = {s: [[i.lower(), t] for i, t in poses if i.lower() in files] for s, poses in states.items()}
    states = {s: poses for s, poses in states.items() if poses}
    if 'idle' not in states:
        raise ValueError('the Stand images are missing')
    for data in files.values():
        _check_image(data)
    name = prefix.rstrip('/').rsplit('/', 1)[-1] if prefix.strip('/') else source.default
    if name.lower() == 'img' or not name:
        name = source.default
    meta = {'name': name, 'author': 'Shimeji', 'fps': 25, 'faces': 'left', 'scale': 2, 'frames': states}
    files['pack.json'] = json.dumps(meta, indent=1).encode()
    return _write_pack(packs_dir, name, files)


def list_packs(packs_dir):
    """[(folder name, meta)] of installed packs, sorted by name."""
    if not os.path.isdir(packs_dir):
        return []
    out = []
    for name in sorted(os.listdir(packs_dir), key=str.lower):
        path = os.path.join(packs_dir, name)
        if not os.path.isdir(path):
            continue
        meta = read_meta(path)
        frames = meta.get('frames') if isinstance(meta.get('frames'), dict) else {}
        if frames.get('idle') or any(os.path.exists(os.path.join(path, 'idle' + e)) for e in EXTS):
            out.append((name, meta))
    return out


def delete_pack(packs_dir, name):
    path = os.path.realpath(os.path.join(packs_dir, name))
    if os.path.dirname(path) != os.path.realpath(packs_dir):  # only ever a direct child of packs_dir
        raise ValueError('not a pack folder')
    shutil.rmtree(path)


def scale_of(meta):
    """How much bigger than the normal pet this pack draws (pack.json "scale"; Shimeji imports use 2)."""
    k = meta.get('scale', 1)
    return min(4, max(0.5, k)) if isinstance(k, (int, float)) and not isinstance(k, bool) else 1


def load_frames(folder, px, smooth=False, pil=False):
    """({state: (frames facing right, frames facing left)}, fps). Frames are PhotoImages fitted in a px square.
    smooth keeps soft edges (for the Settings window); pil gives smooth PIL pictures instead (the pets).
    Animations come from pack.json "frames" ({state: [[image, ticks], ...]}, Shimeji style) or one file per state."""
    meta = read_meta(folder)
    fps = meta.get('fps', 8)
    fps = min(30, max(1, fps)) if isinstance(fps, (int, float)) and not isinstance(fps, bool) else 8
    cache = {}

    def frames_of(name):
        """Every frame of one image file (an animated GIF has several), both directions."""
        if name not in cache:
            right, left = [], []
            with Image.open(os.path.join(folder, name)) as im:
                for fr in ImageSequence.Iterator(im):
                    fr = fr.convert('RGBA')
                    k = px / max(fr.size)
                    # smooth scaling; only big integer-ish blow-ups of tiny pixel art stay blocky on purpose
                    fr = fr.resize((max(1, round(fr.width * k)), max(1, round(fr.height * k))),
                                   Image.NEAREST if k >= 2 else Image.LANCZOS)
                    if pil:
                        right.append(fr)
                        left.append(ImageOps.mirror(fr))
                        continue
                    if not smooth:  # hard edges for anything shown with a single see-through colour
                        fr.putalpha(fr.getchannel('A').point(lambda v: 255 if v >= 128 else 0))
                    right.append(ImageTk.PhotoImage(fr))
                    left.append(ImageTk.PhotoImage(ImageOps.mirror(fr)))
            cache[name] = (right, left)
        return cache[name]

    out = {}
    spec = meta.get('frames') if isinstance(meta.get('frames'), dict) else None
    if spec:
        for state in STATES:
            right, left = [], []
            for entry in spec.get(state) or []:
                if not (isinstance(entry, list) and len(entry) == 2 and isinstance(entry[0], str)
                        and isinstance(entry[1], int)):
                    continue
                name = os.path.basename(entry[0])  # never a path out of the pack folder
                if not os.path.isfile(os.path.join(folder, name)):
                    continue
                r, l = frames_of(name)
                ticks = min(MAX_TICKS, max(1, entry[1]))
                right += r * ticks  # a pose shown for n ticks = the same picture n times (no copies, same objects)
                left += l * ticks
            if right:
                out[state] = (right, left)
    else:
        for name in os.listdir(folder):
            stem, ext = os.path.splitext(name.lower())
            if stem in STATES and ext in EXTS:
                out[stem] = frames_of(name)
    if meta.get('faces') == 'left':  # drawn facing left (Shimeji): swap so 'right' really faces right
        out = {s: (l, r) for s, (r, l) in out.items()}
    return out, fps
