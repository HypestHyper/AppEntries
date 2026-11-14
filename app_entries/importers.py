"""Make a launcher for something you downloaded: an AppImage, an app in a
folder (from a tar.gz or zip), a Windows program, a Java .jar, a .desktop
file that came with an app, or an app inside a Distrobox container. Pure
Python, no GTK.

Each reader looks at the thing and returns an Import: a launchers.Spec filled
in from what it found (name, icon, file types…), plus what saving it would
also do. Nothing is changed here. Reading an AppImage doesn't run it unless
the caller passes allow_run=True, which it does only after asking.
"""
import os
import re
import shlex
import shutil
import stat
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from . import desktop_entries as de
from . import icon_library, launchers
from .editing import escape, split_list
from .overrides import Change, read_text

# Where people keep apps like these; also where the scan looks.
APP_FOLDERS = ("Applications", "AppImages", ".local/bin/appimages", "Games", "Downloads")
MAX_ICON = 2 * 1024 * 1024
# Programs in an app folder that aren't the app itself.
_HELPERS = re.compile(r"(chrome[-_]sandbox|crashpad|crash[-_]?report|update|updater|uninstall|install|"
                      r"helper|launcher\.sh$|\.so(\.\d+)*$|^lib)", re.IGNORECASE)


class NeedsRun(Exception):
    """Reading this AppImage needs it to run its own extractor (asked first)."""


@dataclass
class Import:
    kind: str                        # appimage, folder, exe, jar, desktop, distrobox
    source: str                      # the file or folder it came from
    spec: launchers.Spec
    icon: Optional[tuple[bytes, str]] = None   # (image data, file name) to put in the icon library
    entry_text: str = ""             # kind desktop: the entry as it'll be installed
    entry_id: str = ""
    version: str = ""
    notes: list[str] = field(default_factory=list)   # things worth saying in the form
    how: str = ""                    # appimage: how it was read: squashfs, extract, name


def home(env=None) -> str:
    env = os.environ if env is None else env
    return env.get("HOME") or os.path.expanduser("~")


def applications_dir(env=None) -> str:
    return os.path.join(home(env), "Applications")


def _pretty(name: str) -> str:
    """A display name from a file name: "Obsidian-1.7.7-x86_64.AppImage" -> "Obsidian"."""
    base = os.path.basename(name.rstrip("/"))
    base = re.sub(r"\.(appimage|exe|jar|desktop|tar\.\w+|zip)$", "", base, flags=re.IGNORECASE)
    base = re.sub(r"[-_ .]?(v?\d+(\.\d+)+.*|x86[-_]64.*|amd64.*|aarch64.*|linux.*|portable.*)$", "", base,
                  flags=re.IGNORECASE)
    base = base.replace("_", " ").replace("-", " ").strip()
    return base[:1].upper() + base[1:] if base else os.path.basename(name)


def _version_in(name: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)+)", os.path.basename(name))
    return m.group(1) if m else ""


def _from_entry(spec: launchers.Spec, d: dict) -> None:
    """Fill a spec from a .desktop entry's main group."""
    spec.name = de.unescape(d.get("Name", "")) or spec.name
    spec.comment = de.unescape(d.get("Comment", "")) or de.unescape(d.get("GenericName", "")) or spec.comment
    cats = [c for c in split_list(d.get("Categories", "")) if c]
    if cats:
        spec.categories = cats
    spec.keywords = [k for k in split_list(d.get("Keywords", "")) if k]
    spec.mime_types = [m for m in split_list(d.get("MimeType", "")) if m]
    spec.wm_class = de.unescape(d.get("StartupWMClass", ""))
    spec.terminal = de.is_true(d.get("Terminal"))
    exec_line = d.get("Exec", "")
    spec.accepts_files = any(code in exec_line for code in ("%f", "%F", "%u", "%U"))


def _icon_ok(data: bytes) -> bool:
    if not data or len(data) > MAX_ICON:
        return False
    try:
        icon_library.check(data)
        return True
    except icon_library.IconError:
        return False


# ---------------------------------------------------------------------------
# AppImage


def is_appimage(path: str) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(11)
    except OSError:
        return False
    return (head[:4] == b"\x7fELF" and head[8:11] in (b"AI\x01", b"AI\x02")) or path.lower().endswith(".appimage")


def squashfs_offset(path: str) -> int:
    """Where a type 2 AppImage's squashfs starts: right after the ELF
    runtime, worked out from the ELF header (its section headers are last)."""
    with open(path, "rb") as f:
        ident = f.read(64)
    if ident[:4] != b"\x7fELF":
        raise ValueError("not an ELF file")
    bits64 = ident[4] == 2
    end = "<" if ident[5] == 1 else ">"
    if bits64:
        shoff, = struct.unpack(end + "Q", ident[0x28:0x30])
        shentsize, shnum = struct.unpack(end + "HH", ident[0x3A:0x3E])
    else:
        shoff, = struct.unpack(end + "I", ident[0x20:0x24])
        shentsize, shnum = struct.unpack(end + "HH", ident[0x2E:0x32])
    offset = shoff + shentsize * shnum
    with open(path, "rb") as f:
        f.seek(offset)
        if f.read(4) != b"hsqs":
            raise ValueError("no squashfs where the runtime ends")
    return offset


def _unsquash(path: str, offset: int, dest: str, wanted: list[str]) -> bool:
    tool = shutil.which("unsquashfs")
    if not tool:
        return False
    try:
        r = subprocess.run([tool, "-o", str(offset), "-d", dest, "-f", "-no-progress", path, *wanted],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return r.returncode == 0 and os.path.isdir(dest)


def _extract_run(path: str, dest_parent: str, wanted: list[str]) -> bool:
    """The AppImage's own extractor: this runs the file (only after asking)."""
    if not os.access(path, os.X_OK):
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
    ok = False
    for pattern in wanted:
        try:
            r = subprocess.run([os.path.abspath(path), "--appimage-extract", pattern], cwd=dest_parent,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
                               env=dict(os.environ, APPIMAGE_EXTRACT_AND_RUN="0"))
            ok = ok or r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    return ok and os.path.isdir(os.path.join(dest_parent, "squashfs-root"))


def _resolve_in(root: str, rel: str) -> Optional[str]:
    """A path inside the extracted tree, following links but never out of it."""
    p = os.path.join(root, rel)
    for _ in range(8):
        if not os.path.islink(p):
            break
        target = os.readlink(p)
        p = os.path.normpath(os.path.join(os.path.dirname(p), target) if not os.path.isabs(target)
                             else os.path.join(root, target.lstrip("/")))
    real_root = os.path.realpath(root)
    if not os.path.realpath(p).startswith(real_root + os.sep) or not os.path.isfile(p):
        return None
    return p


def read_appimage(path: str, allow_run: bool = False) -> Import:
    path = os.path.abspath(path)
    spec = launchers.Spec(name=_pretty(path), kind="program", program=path, categories=["Utility"])
    imp = Import("appimage", path, spec, version=_version_in(path))
    with tempfile.TemporaryDirectory(prefix="app-entries-appimage-") as tmp:
        root = None
        wanted = ["*.desktop", ".DirIcon", "*.png", "*.svg"]
        try:
            offset = squashfs_offset(path)
        except (OSError, ValueError):
            offset = None
        if offset is not None and _unsquash(path, offset, os.path.join(tmp, "r"), wanted):
            root, imp.how = os.path.join(tmp, "r"), "squashfs"
        elif allow_run and _extract_run(path, tmp, wanted):
            root, imp.how = os.path.join(tmp, "squashfs-root"), "extract"
        elif not allow_run and offset is not None:
            raise NeedsRun(path)
        if root is None:
            imp.how = "name"
            imp.notes.append("Its name and icon couldn't be read from the file, so check them below.")
            return imp
        entries = sorted(n for n in os.listdir(root) if n.endswith(".desktop"))
        d = {}
        if entries:
            p = _resolve_in(root, entries[0])
            if p:
                d = de.DesktopFile.load(p).group_dict()
                _from_entry(spec, d)
                imp.version = de.unescape(d.get("X-AppImage-Version", "")) or imp.version
        icon_name = de.unescape(d.get("Icon", ""))
        # The icon at the top named as the entry says, or .DirIcon; links
        # to icons deeper in are followed, after extracting those too.
        candidates = [icon_name + ext for ext in (".svg", ".png")] if icon_name else []
        candidates.append(".DirIcon")
        for rel in candidates:
            p = _resolve_in(root, rel)
            if p is None and os.path.islink(os.path.join(root, rel)) and offset is not None and imp.how == "squashfs":
                target = os.path.normpath(os.path.join("/", os.readlink(os.path.join(root, rel)))).lstrip("/")
                _unsquash(path, offset, root, [target])
                p = _resolve_in(root, rel)
            if p is None:
                continue
            with open(p, "rb") as f:
                data = f.read(MAX_ICON + 1)
            if _icon_ok(data):
                kind = icon_library.check(data)
                imp.icon = (data, (icon_name or spec.name or "appimage") + "." + kind)
                break
    return imp


# ---------------------------------------------------------------------------
# An app in a folder


def _executables(folder: str, depth: int = 2) -> list[str]:
    out = []
    base = folder.rstrip("/").count(os.sep)
    for dirpath, dirnames, filenames in os.walk(folder):
        if dirpath.count(os.sep) - base >= depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for n in filenames:
            p = os.path.join(dirpath, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode) and st.st_mode & stat.S_IXUSR and not _HELPERS.search(n):
                out.append(p)
    return out


def _score(path: str, folder: str) -> tuple:
    """Better guesses first: named like the folder, at the top, a real program."""
    name = os.path.basename(path).lower()
    want = re.sub(r"[^a-z0-9]", "", _pretty(folder).lower())
    flat = re.sub(r"[^a-z0-9]", "", name)
    try:
        with open(path, "rb") as f:
            elf = f.read(4) == b"\x7fELF"
    except OSError:
        elf = False
    depth = os.path.relpath(path, folder).count(os.sep)
    return (not (want and (flat.startswith(want) or want.startswith(flat))), depth, not elf, len(name))


def _find_icon(folder: str, name: str) -> Optional[tuple[bytes, str]]:
    want = re.sub(r"[^a-z0-9]", "", name.lower())
    found = []
    for dirpath, dirnames, filenames in os.walk(folder):
        if dirpath[len(folder):].count(os.sep) > 4:
            dirnames[:] = []
        for n in filenames:
            low = n.lower()
            if not low.endswith((".png", ".svg")):
                continue
            flat = re.sub(r"[^a-z0-9]", "", os.path.splitext(low)[0])
            good = flat in (want, "icon", "logo", "appicon") or (want and want in flat)
            if good:
                p = os.path.join(dirpath, n)
                try:
                    size = os.path.getsize(p)
                except OSError:
                    continue
                found.append((low.endswith(".svg"), size, p))
    for _svg, _size, p in sorted(found, reverse=True):
        with open(p, "rb") as f:
            data = f.read(MAX_ICON + 1)
        if _icon_ok(data):
            return data, os.path.basename(p)
    return None


def read_folder(folder: str) -> Import:
    folder = os.path.abspath(folder)
    spec = launchers.Spec(name=_pretty(folder), kind="program", categories=["Utility"], workdir=folder)
    imp = Import("folder", folder, spec, version=_version_in(folder))
    # An entry that came with it says the most.
    for dirpath, dirnames, filenames in os.walk(folder):
        if dirpath[len(folder):].count(os.sep) > 3:
            dirnames[:] = []
        for n in sorted(filenames):
            if n.endswith(".desktop"):
                d = de.DesktopFile.load(os.path.join(dirpath, n)).group_dict()
                if d.get("Type", "Application") == "Application" and d.get("Name"):
                    _from_entry(spec, d)
                    prog = launchers.parse_exec(de.unescape(d.get("Exec", "")))[:1]
                    if prog:
                        p = prog[0] if os.path.isabs(prog[0]) else os.path.join(dirpath, prog[0])
                        if os.path.isfile(p):
                            spec.program = p
                    icon = de.unescape(d.get("Icon", ""))
                    if icon and os.path.isfile(os.path.join(dirpath, icon)):
                        with open(os.path.join(dirpath, icon), "rb") as f:
                            data = f.read(MAX_ICON + 1)
                        if _icon_ok(data):
                            imp.icon = (data, os.path.basename(icon))
                    break
        else:
            continue
        break
    if not spec.program:
        progs = sorted(_executables(folder), key=lambda p: _score(p, folder))
        if progs:
            spec.program = progs[0]
            if len(progs) > 1:
                imp.notes.append("It has more than one program; this one looks like the app. Choose another "
                                 "if it isn't.")
        else:
            imp.notes.append("No program was found in it. Choose the file that starts the app.")
    if imp.icon is None:
        imp.icon = _find_icon(folder, spec.name)
    return imp


# ---------------------------------------------------------------------------
# Windows programs and Java


RUNNERS = (
    ("wine", "Wine", "wine"),
    ("umu", "Proton (umu)", "umu-run"),
)


def runners(which=shutil.which) -> list[tuple[str, str]]:
    """(key, name) for the Windows runners that are installed."""
    return [(k, n) for k, n, prog in RUNNERS if which(prog)]


def exe_icon(path: str) -> Optional[tuple[bytes, str]]:
    """The program's own icon, with wrestool and icotool (icoutils) if installed."""
    wres, ico = shutil.which("wrestool"), shutil.which("icotool")
    if not (wres and ico):
        return None
    with tempfile.TemporaryDirectory(prefix="app-entries-exe-") as tmp:
        icon_file = os.path.join(tmp, "icon.ico")
        try:
            with open(icon_file, "wb") as f:
                subprocess.run([wres, "-x", "-t", "14", path], stdout=f, stderr=subprocess.DEVNULL, timeout=30)
            if os.path.getsize(icon_file) == 0:
                return None
            subprocess.run([ico, "-x", "-o", tmp, icon_file], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        pngs = [os.path.join(tmp, n) for n in os.listdir(tmp) if n.endswith(".png")]
        if not pngs:
            return None
        best = max(pngs, key=os.path.getsize)
        with open(best, "rb") as f:
            data = f.read(MAX_ICON + 1)
        return (data, "icon.png") if _icon_ok(data) else None


def read_exe(path: str, runner: str = "wine") -> Import:
    path = os.path.abspath(path)
    prog = {k: p for k, _n, p in RUNNERS}.get(runner, "wine")
    spec = launchers.Spec(name=_pretty(path), kind="program", categories=["Game"] if "game" in path.lower()
                          else ["Utility"], workdir=os.path.dirname(path),
                          program=prog + " " + shlex.quote(path))
    imp = Import("exe", path, spec, version=_version_in(path))
    imp.icon = exe_icon(path)
    if not shutil.which(prog):
        name = {k: n for k, n, _p in RUNNERS}.get(runner, prog)
        imp.notes.append(f"{name} isn't installed, so this won't start until it is.")
    return imp


def read_jar(path: str) -> Import:
    path = os.path.abspath(path)
    spec = launchers.Spec(name=_pretty(path), kind="program", categories=["Utility"],
                          workdir=os.path.dirname(path), program="java -jar " + shlex.quote(path))
    imp = Import("jar", path, spec, version=_version_in(path))
    if not shutil.which("java"):
        imp.notes.append("Java isn't installed, so this won't start until it is.")
    return imp


# ---------------------------------------------------------------------------
# A .desktop file that came with an app


def read_desktop_file(path: str, env=None) -> Import:
    """The entry as it'll be installed: paths relative to where it came from
    are made absolute, so it keeps working from your applications folder."""
    path = os.path.abspath(path)
    text = read_text(path) or ""
    df = de.DesktopFile(text)
    d = df.group_dict()
    here = os.path.dirname(path)
    spec = launchers.Spec()
    _from_entry(spec, d)
    imp = Import("desktop", path, spec)
    for key in ("Exec", "TryExec"):
        value = de.unescape(d.get(key, ""))
        words = launchers.parse_exec(value) if key == "Exec" else [value]
        if words and words[0] and not os.path.isabs(words[0]) and os.path.exists(os.path.join(here, words[0])):
            fixed = os.path.join(here, words[0])
            df.set(key, escape(value.replace(words[0], shlex.quote(fixed), 1)))
            imp.notes.append(f"{key} pointed next to the file; it now points to {fixed}.")
    icon = de.unescape(d.get("Icon", ""))
    if icon and not os.path.isabs(icon) and os.path.isfile(os.path.join(here, icon)):
        df.set("Icon", escape(os.path.join(here, icon)))
        imp.notes.append("Its icon is next to the file, so the entry points to it there.")
    imp.entry_text = df.text()
    imp.entry_id = os.path.basename(path)
    return imp


# ---------------------------------------------------------------------------
# Distrobox


def _run(argv, timeout=30) -> str:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return r.stdout if r.returncode == 0 else ""


def containers() -> list[str]:
    """Distrobox containers, by name."""
    if not shutil.which("distrobox"):
        return []
    out = []
    for line in _run(["distrobox", "list", "--no-color"]).splitlines()[1:]:
        cols = [c.strip() for c in line.split("|")]
        if len(cols) >= 2 and cols[1]:
            out.append(cols[1])
    return out


def container_apps(name: str) -> list[tuple[str, str]]:
    """(desktop ID, name) of the apps installed in a container."""
    script = ("for f in /usr/share/applications/*.desktop; do "
              "n=$(grep -m1 '^Name=' \"$f\" | cut -d= -f2-); nd=$(grep -m1 '^NoDisplay=true' \"$f\"); "
              "[ -z \"$nd\" ] && printf '%s\\t%s\\n' \"${f##*/}\" \"$n\"; done")
    apps = []
    for line in _run(["distrobox", "enter", name, "--", "sh", "-c", script], timeout=120).splitlines():
        did, _tab, title = line.partition("\t")
        if did.endswith(".desktop"):
            apps.append((did, title or did))
    return apps


def export_argv(container: str, app: str) -> list[str]:
    """distrobox-export run in the container adds the app to your menus."""
    return ["distrobox", "enter", container, "--", "distrobox-export", "--app", app.removesuffix(".desktop")]


# ---------------------------------------------------------------------------
# Saving


def detect(path: str) -> str:
    """Which reader fits: appimage, folder, exe, jar, desktop, or ""."""
    if os.path.isdir(path):
        return "folder"
    low = path.lower()
    if low.endswith(".desktop"):
        return "desktop"
    if low.endswith((".exe", ".msi", ".bat")):
        return "exe"
    if low.endswith(".jar"):
        return "jar"
    if is_appimage(path):
        return "appimage"
    return ""


def moved_path(source: str, env=None) -> str:
    """Where Move to Applications puts it, without overwriting anything."""
    target = os.path.join(applications_dir(env), os.path.basename(source.rstrip("/")))
    base, n = target, 2
    while os.path.exists(target) and os.path.realpath(target) != os.path.realpath(source):
        stem, ext = os.path.splitext(base)
        target, n = f"{stem}-{n}{ext}", n + 1
    return target


def in_applications(source: str, env=None) -> bool:
    return os.path.realpath(os.path.dirname(source.rstrip("/"))) == os.path.realpath(applications_dir(env))


def move(source: str, env=None) -> str:
    """Move the file or folder into ~/Applications; returns where it went."""
    target = moved_path(source, env)
    if os.path.realpath(target) == os.path.realpath(source):
        return source
    os.makedirs(applications_dir(env), exist_ok=True)
    shutil.move(source, target)
    return target


def repoint(imp: Import, old: str, new: str) -> None:
    """After moving: the launcher points to the new place."""
    s = imp.spec
    s.program = s.program.replace(old, new) if old in s.program else s.program
    if s.workdir == old or s.workdir.startswith(old + os.sep):
        s.workdir = new + s.workdir[len(old):]
    imp.source = new


def plan_icon(imp: Import, env=None) -> tuple[Optional[str], list[Change]]:
    """Where the icon goes in your library, and the change that puts it there."""
    if imp.icon is None:
        return None, []
    data, name = imp.icon
    for existing in icon_library.list_icons(env):
        try:
            if os.path.getsize(existing) == len(data):
                with open(existing, "rb") as f:
                    if f.read() == data:
                        return existing, []
        except OSError:
            continue
    target = icon_library._unique(name, env)
    return target, [Change("", imp.spec.name, target, None, data, False)]


def make_executable(path: str) -> bool:
    """Whether it had to be made executable."""
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return False
    if mode & stat.S_IXUSR:
        return False
    os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return True


def has_entry(source: str, apps) -> bool:
    """Whether an installed entry already starts this file or something in this folder."""
    real = os.path.realpath(source)
    for a in apps:
        line = a.exec or ""
        if source in line or real in line:
            return True
    return False


def find_without_launcher(apps, env=None) -> list[tuple[str, str]]:
    """(path, kind) of AppImages, Windows programs and app folders in the
    usual places that no launcher starts yet. Only looks; changes nothing."""
    out = []
    for rel in APP_FOLDERS:
        d = os.path.join(home(env), rel)
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            if n.startswith("."):
                continue
            p = os.path.join(d, n)
            kind = detect(p)
            file_app = kind in ("appimage", "exe") and os.path.isfile(p)
            folder_app = kind == "folder" and rel != "Downloads" and bool(_executables(p, 1))
            if not (file_app or folder_app):
                continue
            if not has_entry(p, apps):
                out.append((p, kind))
    return out
