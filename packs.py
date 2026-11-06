"""Character packs: a folder or .zip holding one image per pet state, plus an optional pack.json.

    my-cat/
      pack.json    {"name": "My cat", "author": "me", "fps": 8}   (all optional)
      idle.gif     required; animated GIF or still PNG
      walk.gif  fall.png  drag.png  sit.png  climb.gif            optional, missing ones use idle

Images face right; the pet mirrors them when walking left.
"""
import io, json, os, re, shutil, zipfile

from PIL import Image, ImageOps, ImageSequence, ImageTk

STATES = ('idle', 'walk', 'fall', 'drag', 'sit', 'climb')
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


def import_pack(src, packs_dir):
    """Copy a pack folder or .zip into packs_dir. Returns the new folder name.
    Raises ValueError with a reason the user can read."""
    files = {}
    if os.path.isfile(src) and zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            for info in z.infolist():
                base = _wanted(info.filename)  # basename only: zip paths like ../../x are never used
                if base and not info.is_dir() and info.file_size <= MAX_FILE:
                    files[base] = z.read(info)
        default = os.path.splitext(os.path.basename(src))[0]
    elif os.path.isdir(src):
        for name in os.listdir(src):
            base, path = _wanted(name), os.path.join(src, name)
            if base and os.path.isfile(path) and os.path.getsize(path) <= MAX_FILE:
                with open(path, 'rb') as f:
                    files[base] = f.read()
        default = os.path.basename(os.path.normpath(src))
    else:
        raise ValueError('drop a pack folder or a .zip')
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
    name = re.sub(r'[^\w\- ]', '', str(meta.get('name') if isinstance(meta, dict) and meta.get('name') else default))
    name = name.strip()[:40] or 'pack'
    dest, n = os.path.join(packs_dir, name), 2
    while os.path.exists(dest):
        dest, n = os.path.join(packs_dir, f'{name} {n}'), n + 1
    os.makedirs(dest)
    for fname, data in files.items():
        with open(os.path.join(dest, fname), 'wb') as f:
            f.write(data)
    return os.path.basename(dest)


def list_packs(packs_dir):
    """[(folder name, meta)] of installed packs, sorted by name."""
    if not os.path.isdir(packs_dir):
        return []
    out = []
    for name in sorted(os.listdir(packs_dir), key=str.lower):
        path = os.path.join(packs_dir, name)
        if os.path.isdir(path) and any(os.path.exists(os.path.join(path, 'idle' + e)) for e in EXTS):
            out.append((name, read_meta(path)))
    return out


def delete_pack(packs_dir, name):
    path = os.path.realpath(os.path.join(packs_dir, name))
    if os.path.dirname(path) != os.path.realpath(packs_dir):  # only ever a direct child of packs_dir
        raise ValueError('not a pack folder')
    shutil.rmtree(path)


def load_frames(folder, px, smooth=False):
    """({state: (frames facing right, frames facing left)}, fps). Frames are PhotoImages fitted in a px square.
    smooth keeps soft edges (for the Settings window); the pets need hard edges (see below)."""
    meta = read_meta(folder)
    fps = meta.get('fps', 8)
    fps = min(30, max(1, fps)) if isinstance(fps, (int, float)) and not isinstance(fps, bool) else 8
    out = {}
    for name in os.listdir(folder):
        stem, ext = os.path.splitext(name.lower())
        if stem not in STATES or ext not in EXTS:
            continue
        right, left = [], []
        with Image.open(os.path.join(folder, name)) as im:
            for fr in ImageSequence.Iterator(im):
                fr = fr.convert('RGBA')
                k = px / max(fr.size)
                fr = fr.resize((max(1, round(fr.width * k)), max(1, round(fr.height * k))),
                               Image.NEAREST if k > 1 else Image.LANCZOS)  # NEAREST keeps pixel art crisp
                if not smooth:  # the pet window can only show fully clear or fully solid pixels
                    fr.putalpha(fr.getchannel('A').point(lambda v: 255 if v >= 128 else 0))
                right.append(ImageTk.PhotoImage(fr))
                left.append(ImageTk.PhotoImage(ImageOps.mirror(fr)))
        out[stem] = (right, left)
    return out, fps
