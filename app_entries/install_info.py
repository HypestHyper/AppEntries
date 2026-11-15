"""Where an app came from: its package, version, when it was installed and
by whom (where that's recorded), its size and what it depends on.

Only reads. Each package manager is asked without root, or its own records
are read, and nothing is guessed: what a manager doesn't record is left
empty, and the page says so. Pure Python, no GTK.

`summary()` is the quick part (one question to the package manager);
`dependencies()` adds the lists, which take longer. Both are remembered
until a package database changes, so opening an app again is instant."""
import gzip
import os
import re
import shlex
import struct
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import appimages, pkgmanagers, uninstall

Run = Callable[[list[str]], Optional[tuple[int, str]]]


@dataclass
class Dep:
    name: str
    installed: bool = True
    why: str = ""                 # for optional ones: what it adds


@dataclass
class Details:
    kind: str = ""                # package, flatpak, snap, appimage, file, steam, distrobox or ""
    manager: str = ""             # pacman, apt, Flatpak, Snap, …
    package: str = ""
    version: str = ""
    repo: str = ""                # where the package came from, in words
    foreign: bool = False         # not from the distribution's own repositories
    date: float = 0               # a Unix time, 0 if unknown
    date_label: str = ""          # installed, updated (installed or last updated) or file
    reason: str = ""              # you or dependency, "" if not recorded
    by: str = ""                  # the user who installed it, "" if not recorded
    scope: str = ""               # system (all users) or user (just you)
    size: int = 0                 # bytes, 0 if unknown
    path: str = ""                # the program file, for apps that are just a file
    origin: str = ""              # the web address a download came from
    updates_from: str = ""        # e.g. "GitHub: owner/repo"
    runtime: str = ""             # a Flatpak's runtime
    publisher: str = ""
    note: str = ""                # one line for kinds there's nothing more to say about
    full: bool = False            # dependencies() has filled the lists below
    depends: list[Dep] = field(default_factory=list)
    required_by: list[str] = field(default_factory=list)
    optional: list[Dep] = field(default_factory=list)
    shared_with: int = 0          # other apps using the same Flatpak runtime
    raw: dict = field(default_factory=dict, repr=False)   # what the quick question returned, kept for later


class System:
    """How to reach the system: run commands, find programs, read files.
    Tests give their own."""

    def __init__(self, run: Run = pkgmanagers.run, which=None, root: str = "", home: str = ""):
        import shutil
        self.run = run
        self.which = which or shutil.which
        self.root = root
        self.home = home or os.path.expanduser("~")
        self._managers = None

    def p(self, path: str) -> str:
        return self.root + path if self.root and path.startswith("/") else path

    def managers(self):
        if self._managers is None:
            self._managers = pkgmanagers.detect(self.run, self.which)
        return self._managers

    def out(self, argv) -> str:
        r = self.run(argv)
        return r[1] if r is not None and r[0] == 0 else ""


# ---------------------------------------------------------------------------
# remembering answers


_cache: dict = {}
_DBS = ("/var/lib/pacman/local", "/var/lib/dpkg/status", "/var/lib/rpm", "/usr/lib/sysimage/rpm",
        "/var/lib/flatpak/app", "/var/lib/snapd/state.json", "/var/db/xbps", "/lib/apk/db/installed",
        "/nix/var/nix/profiles")


def _stamp(sysm: System, files=()) -> tuple:
    out = []
    for p in [sysm.p(d) for d in _DBS] + [os.path.join(sysm.home, ".local/share/flatpak/app")] + list(files):
        try:
            out.append(os.stat(p).st_mtime_ns)
        except OSError:
            out.append(0)
    return tuple(out)


def _key(app) -> tuple:
    return (app.id, app.base_path, app.source_path, app.exec)


def cached(app, sysm: Optional[System] = None) -> Optional[Details]:
    """The remembered details, if nothing has changed since, else None."""
    hit = _cache.get(_key(app))
    if hit is None:
        return None
    stamp, d = hit
    return d if stamp == _stamp(sysm or _default(), [d.path] if d.path else []) else None


_sys = None


def _default() -> System:
    global _sys
    if _sys is None:
        _sys = System()
    return _sys


# ---------------------------------------------------------------------------
# the quick part


def summary(app, sysm: Optional[System] = None) -> Details:
    sysm = sysm or _default()
    d = cached(app, sysm)
    if d is not None:
        return d
    d = _summary(app, sysm)
    _cache[_key(app)] = (_stamp(sysm, [d.path] if d.path else []), d)
    return d


def _program(app) -> str:
    """The first word of its command that's a file, made absolute."""
    try:
        words = shlex.split(app.exec)
    except ValueError:
        words = app.exec.split()
    import shutil
    for w in words:
        if "=" in w and not w.startswith("/"):
            continue        # env VAR=value
        if os.path.basename(w) in ("env", "sh", "bash", "flatpak", "snap"):
            continue
        p = w if os.path.isabs(w) else (shutil.which(w) or "")
        if p and os.path.isfile(p):
            return p
        if not w.startswith("-"):
            break
    return ""


def _summary(app, sysm: System) -> Details:
    kind = uninstall.kind_of(app)
    if kind == "flatpak":
        return _flatpak(uninstall._flatpak_id(app), sysm)
    if kind == "snap":
        return _snap(uninstall._snap_name(app), sysm)
    if kind == "steam":
        return Details(kind="steam", manager="Steam", note="steam")
    if kind == "distrobox":
        box, _rest = uninstall._distrobox(app.exec)
        return Details(kind="distrobox", manager="Distrobox", package=box, note="distrobox")
    image = appimages.appimage_of(app.exec)
    if image:
        return _file(image, sysm, kind="appimage")
    # A package: the one that installed its entry, or else its program.
    for path in (app.base_path if app.system else "", _program(app)):
        if not path:
            continue
        m, pkg = pkgmanagers.owner_of(path, sysm.managers())
        if m is not None:
            return _package(m, pkg, sysm)
    prog = _program(app)
    if prog:
        return _file(prog, sysm, kind="file")
    return Details()


# -- packages -----------------------------------------------------------------


def _package(m, pkg: str, sysm: System) -> Details:
    if m.name == "pacman":
        return _pacman(pkg, sysm)
    if m.name == "apt":
        return _apt(pkg, sysm)
    if m.name in ("dnf", "zypper", "rpm-ostree", "rpm"):
        return _rpm(m, pkg, sysm)
    info = m.info(pkg)
    return Details(kind="package", manager=m.label, package=pkg, version=info.version, size=info.size,
                   foreign=info.foreign, scope="system")


def _fields(text: str, indented: bool = False) -> dict:
    """`Key : value` lines, with indented lines continuing the value. With
    `indented`, keys may be indented too (flatpak lines them up on the colon)."""
    fields, key = {}, None
    for line in text.splitlines():
        m = re.match(r"^\s*(\w[\w ]*?):\s?(.*)$" if indented else r"^(\S[^:]*?)\s*:\s?(.*)$", line)
        if m:
            key = m.group(1).strip()
            fields[key] = m.group(2).strip()
        elif key and line.startswith(" "):
            fields[key] += "\n" + line.strip()
    return fields


def _pacman(pkg, sysm):
    f = _fields(sysm.out(["pacman", "-Qi", pkg]))
    d = Details(kind="package", manager="pacman", package=pkg, version=f.get("Version", ""), scope="system")
    d.size = pkgmanagers._human_size(f.get("Installed Size", ""))
    d.foreign = sysm.out(["pacman", "-Qqm", pkg]).strip() == pkg
    d.repo = "foreign" if d.foreign else "distribution"
    reason = f.get("Install Reason", "")
    d.reason = "dependency" if "dependency" in reason.lower() else ("you" if reason else "")
    # The exact time is in pacman's own record; the printed date is a fallback.
    desc = sysm.p(f"/var/lib/pacman/local/{pkg}-{d.version}/desc")
    try:
        with open(desc, encoding="utf-8", errors="replace") as fh:
            m = re.search(r"%INSTALLDATE%\n(\d+)", fh.read())
        d.date = float(m.group(1)) if m else 0
    except OSError:
        d.date = _parse_date(f.get("Install Date", ""))
    d.date_label = "installed" if d.date else ""
    d.raw = f
    return d


def _parse_date(text: str) -> float:
    text = " ".join(text.split())
    for fmt in ("%a %b %d %H:%M:%S %Y", "%a %d %b %Y %H:%M:%S %Z", "%a %d %b %Y %I:%M:%S %p %Z",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return time.mktime(time.strptime(text, fmt))
        except ValueError:
            continue
    return 0


def _apt(pkg, sysm):
    out = sysm.out(["dpkg-query", "-W", "-f", "${Version}\t${Installed-Size}\t${Architecture}\t${Maintainer}\n",
                    pkg])
    parts = (out.splitlines()[0].split("\t") if out.strip() else []) + [""] * 4
    d = Details(kind="package", manager="apt", package=pkg, version=parts[0], scope="system")
    d.size = int(parts[1]) * 1024 if parts[1].isdigit() else 0
    arch = parts[2]
    # Installed for something else? apt keeps that in extended_states.
    try:
        with open(sysm.p("/var/lib/apt/extended_states"), encoding="utf-8", errors="replace") as fh:
            for block in fh.read().split("\n\n"):
                b = _fields(block)
                if b.get("Package") == pkg and b.get("Auto-Installed") == "1":
                    d.reason = "dependency"
                    break
            else:
                d.reason = "you"
    except OSError:
        pass
    when, by = _apt_history(pkg, sysm)
    if when:
        d.date, d.date_label, d.by = when, "installed", by
    else:
        # The logs are gone: the date its file list was last written.
        for name in (f"{pkg}:{arch}.list", f"{pkg}.list"):
            try:
                d.date = os.stat(sysm.p("/var/lib/dpkg/info/" + name)).st_mtime
                d.date_label = "updated"
                break
            except OSError:
                continue
    return d


def _apt_history(pkg, sysm) -> tuple[float, str]:
    """(when, by whom) apt first installed it, from its history logs."""
    folder = sysm.p("/var/log/apt")
    try:
        names = [n for n in os.listdir(folder) if n.startswith("history.log")]
    except OSError:
        return 0, ""
    # Oldest first: history.log.9.gz … history.log.1.gz, history.log.
    def order(n):
        m = re.search(r"\.(\d+)", n)
        return -int(m.group(1)) if m else 0
    found = (0.0, "")
    pat = re.compile(r"(^|[ ,])" + re.escape(pkg) + r"(:[\w-]+)? \(")
    for n in sorted(names, key=order):
        path = os.path.join(folder, n)
        try:
            opener = gzip.open if n.endswith(".gz") else open
            with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        for block in text.split("\n\n"):
            b = _fields(block)
            if pat.search(b.get("Install", "")):
                when = _parse_date(b.get("Start-Date", ""))
                by = re.sub(r"\s*\(\d+\)$", "", b.get("Requested-By", ""))
                if when and not found[0]:
                    found = (when, by)
        if found[0]:
            break
    return found


def _rpm(m, pkg, sysm):
    out = sysm.out(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}\\t%{INSTALLTIME}\\t%{SIZE}\\t%{VENDOR}\\n", pkg])
    parts = (out.splitlines()[0].split("\t") if out.strip() else []) + [""] * 4
    d = Details(kind="package", manager=m.label, package=pkg, version=parts[0], scope="system")
    d.date = float(parts[1]) if parts[1].isdigit() else 0
    d.date_label = "installed" if d.date else ""
    d.size = int(parts[2]) if parts[2].isdigit() else 0
    d.repo = "" if parts[3] in ("", "(none)") else parts[3]
    return d


# -- Flatpak and Snap ---------------------------------------------------------


def _flatpak(fid, sysm):
    f = _fields(sysm.out(["flatpak", "info", fid]), indented=True)
    d = Details(kind="flatpak", manager="Flatpak", package=fid, version=f.get("Version", ""))
    d.repo = f.get("Origin", "")
    d.scope = "user" if f.get("Installation", "") == "user" else "system"
    d.size = pkgmanagers._human_size(f.get("Installed", "").replace("\xa0", " "))
    d.runtime = f.get("Runtime", "")
    base = os.path.join(sysm.home, ".local/share/flatpak") if d.scope == "user" else sysm.p("/var/lib/flatpak")
    ref = f.get("Ref", "")
    parts = ref.split("/")
    if len(parts) == 4:
        try:
            d.date = os.stat(os.path.join(base, "app", fid, parts[2], parts[3], "active", "deploy")).st_mtime
            d.date_label = "updated"
        except OSError:
            pass
    d.raw = f
    return d


def _snap(name, sysm):
    out = sysm.out(["snap", "list", name])
    rows = [l.split() for l in out.splitlines()[1:] if l.strip()]
    d = Details(kind="snap", manager="Snap", package=name, scope="system")
    if rows:
        row = rows[0] + [""] * 6
        d.version, rev, tracking, d.publisher = row[1], row[2], row[3], row[4].rstrip("*✓")
        d.repo = tracking
        try:
            d.size = os.stat(sysm.p(f"/var/lib/snapd/snaps/{name}_{rev}.snap")).st_size
        except OSError:
            pass
        try:
            d.date = os.stat(sysm.p(f"/snap/{name}/{rev}")).st_mtime
            d.date_label = "updated"
        except OSError:
            pass
    try:
        with open(sysm.p(f"/snap/{name}/current/meta/snap.yaml"), encoding="utf-8", errors="replace") as fh:
            m = re.search(r"^base:\s*(\S+)", fh.read(), flags=re.MULTILINE)
        if m:
            d.raw["base"] = m.group(1)
    except OSError:
        pass
    return d


# -- programs that are just a file --------------------------------------------


def _file(path, sysm, kind="file"):
    d = Details(kind=kind, path=path, scope="user" if path.startswith(sysm.home + os.sep) else "system")
    try:
        st = os.stat(path)
        d.size, d.date, d.date_label = st.st_size, st.st_mtime, "file"
    except OSError:
        pass
    d.origin = download_origin(path)
    d.raw["update_info"] = update_info(path) if kind == "appimage" else ""
    d.updates_from = appimage_updates(path) if kind == "appimage" else ""
    if not d.updates_from:
        d.updates_from = github_of(d.origin)
    return d


def download_origin(path: str) -> str:
    """The web address a browser saved the file from, if it noted one."""
    for attr in ("user.xdg.origin.url", "user.xdg.referrer.url"):
        try:
            return os.getxattr(path, attr).decode("utf-8", "replace").strip("\0 ")
        except (OSError, AttributeError):
            continue
    return ""


def github_of(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+)", url or "")
    return f"GitHub: {m.group(1)}/{m.group(2)}" if m else ""


def update_info(path: str) -> str:
    """An AppImage's update information (its .upd_info section), as written."""
    return elf_section(path, ".upd_info").split(b"\0", 1)[0].decode("utf-8", "replace").strip()


def appimage_updates(path: str) -> str:
    """Where an AppImage says its updates come from, e.g. "GitHub: owner/repo", or ""."""
    info = update_info(path)
    if not info:
        return ""
    parts = info.split("|")
    if parts[0] in ("gh-releases-zsync", "gh-releases-direct") and len(parts) >= 3:
        return f"GitHub: {parts[1]}/{parts[2]}"
    if parts[0] == "zsync" and len(parts) >= 2:
        m = re.match(r"https?://([^/]+)", parts[1])
        return m.group(1) if m else ""
    return ""


def elf_section(path: str, name: str, limit: int = 1 << 16) -> bytes:
    """The bytes of one section of a 64- or 32-bit ELF file, or b""."""
    try:
        with open(path, "rb") as f:
            head = f.read(64)
            if head[:4] != b"\x7fELF":
                return b""
            is64, little = head[4] == 2, head[5] == 1
            e = "<" if little else ">"
            if is64:
                shoff, = struct.unpack_from(e + "Q", head, 0x28)
                shentsize, shnum, shstrndx = struct.unpack_from(e + "HHH", head, 0x3A)
            else:
                shoff, = struct.unpack_from(e + "I", head, 0x20)
                shentsize, shnum, shstrndx = struct.unpack_from(e + "HHH", head, 0x2E)
            if not shoff or shnum > 4096:
                return b""

            def header(i):
                f.seek(shoff + i * shentsize)
                raw = f.read(shentsize)
                if is64:
                    nm, _t, _fl, _a, off, size = struct.unpack_from(e + "IIQQQQ", raw)
                else:
                    nm, _t, _fl, _a, off, size = struct.unpack_from(e + "IIIIII", raw)
                return nm, off, size

            _n, str_off, str_size = header(shstrndx)
            f.seek(str_off)
            names = f.read(min(str_size, limit))
            for i in range(shnum):
                nm, off, size = header(i)
                if names[nm:names.find(b"\0", nm)] == name.encode():
                    f.seek(off)
                    return f.read(min(size, limit))
    except (OSError, struct.error, ValueError):
        pass
    return b""


# ---------------------------------------------------------------------------
# the slower part: what it needs and what needs it


def dependencies(app, sysm: Optional[System] = None) -> Details:
    sysm = sysm or _default()
    d = summary(app, sysm)
    if d.full:
        return d
    try:
        if d.kind == "package" and d.manager == "pacman":
            _pacman_deps(d, sysm)
        elif d.kind == "package" and d.manager == "apt":
            _apt_deps(d, sysm)
        elif d.kind == "package" and d.manager in ("dnf", "zypper", "rpm-ostree", "rpm"):
            _rpm_deps(d, sysm)
        elif d.kind == "flatpak":
            _flatpak_deps(d, sysm)
        elif d.kind == "snap" and d.raw.get("base"):
            d.depends = [Dep(d.raw["base"])]
    finally:
        d.full = True
    return d


def _names(text: str) -> list[str]:
    if not text or text.strip() == "None":
        return []
    return [re.split(r"[<>=]", w, maxsplit=1)[0] for w in text.split()]


def _pacman_deps(d, sysm):
    f = d.raw
    d.depends = [Dep(n) for n in _names(f.get("Depends On", ""))]
    d.required_by = _names(f.get("Required By", ""))
    for line in f.get("Optional Deps", "").split("\n"):
        line = line.strip()
        if not line or line == "None":
            continue
        installed = line.endswith("[installed]")
        line = line.removesuffix("[installed]").strip()
        if not re.match(r"^[\w@.+-]+(?:[<>=]+\S+)?:", line) and d.optional:
            # A long description carried on to the next line.
            d.optional[-1].why += " " + line
            d.optional[-1].installed = d.optional[-1].installed or installed
            continue
        name, _sep, why = line.partition(":")
        d.optional.append(Dep(re.split(r"[<>=]", name.strip(), maxsplit=1)[0], installed, why.strip()))


def _apt_list(text: str) -> list[str]:
    """`a (>= 1), b | c` -> ["a", "b or c"]."""
    out = []
    for item in text.split(","):
        alts = [re.sub(r"\s*\(.*?\)|:\w+$", "", a).strip() for a in item.split("|")]
        alts = [a for a in alts if a]
        if alts:
            out.append(" or ".join(alts))
    return out


def _dpkg_status(sysm) -> dict:
    """Every installed package's fields, read from dpkg's own record (far
    quicker than asking apt-cache)."""
    try:
        with open(sysm.p("/var/lib/dpkg/status"), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return {}
    out = {}
    for block in text.split("\n\n"):
        f = _fields(block)
        if f.get("Package") and f.get("Status", "").endswith(" installed"):
            out[f["Package"]] = f
    return out


def _apt_deps(d, sysm):
    status = _dpkg_status(sysm)
    me = status.get(d.package, {})
    needs = _apt_list(me.get("Pre-Depends", "")) + _apt_list(me.get("Depends", ""))
    extra = _apt_list(me.get("Recommends", "")) + _apt_list(me.get("Suggests", ""))
    d.depends = [Dep(x, any(n in status for n in x.split(" or "))) for x in needs]
    d.optional = [Dep(x, any(n in status for n in x.split(" or "))) for x in extra]
    d.required_by = sorted(name for name, f in status.items() if name != d.package and any(
        d.package in x.split(" or ") for x in _apt_list(f.get("Pre-Depends", "")) + _apt_list(f.get("Depends", ""))))


def origin(app, sysm: Optional[System] = None) -> Details:
    """Fills in where an apt package came from (apt-cache takes about a
    second, so it's asked after the summary is shown)."""
    sysm = sysm or _default()
    d = summary(app, sysm)
    if d.kind != "package" or d.manager != "apt" or d.repo:
        return d
    lines = sysm.out(["apt-cache", "policy", d.package]).splitlines()
    sources, mine = [], False
    for line in lines:
        if line.startswith(" ***"):
            mine = True
        elif mine and re.match(r"^\s+\d+ ", line):
            sources.append(line.split(None, 1)[1].strip())
        elif mine:
            break
    repos = [x for x in sources if not x.startswith("/")]
    if repos:
        words = repos[0].split()
        url = re.sub(r"^\w+://", "", words[0]).rstrip("/")
        d.repo = f"{url} ({words[1]})" if len(words) > 1 else url
    elif sources:
        d.repo = "local"
    else:
        d.repo = "unknown"
    return d


def _rpm_deps(d, sysm):
    caps = [c.strip() for c in sysm.out(["rpm", "-q", "--requires", d.package]).splitlines()
            if c.strip() and not c.startswith("rpmlib(")]
    caps = [re.split(r"\s+[<>=]", c, maxsplit=1)[0] for c in caps]
    if caps:
        prov = sysm.out(["rpm", "-q", "--whatprovides", "--qf", "%{NAME}\\n"] + caps)
        names = [l.strip() for l in prov.splitlines() if l.strip() and " " not in l.strip()]
        d.depends = [Dep(n) for n in dict.fromkeys(names) if n != d.package]
    need = sysm.out(["rpm", "-q", "--whatrequires", "--qf", "%{NAME}\\n", d.package])
    d.required_by = list(dict.fromkeys(l.strip() for l in need.splitlines()
                                       if l.strip() and " " not in l.strip()))


def _flatpak_deps(d, sysm):
    if d.runtime:
        d.depends = [Dep(d.runtime)]
        rows = sysm.out(["flatpak", "list", "--app", "--columns=application,runtime"]).splitlines()
        d.shared_with = sum(1 for r in rows if r.split("\t")[-1].strip() == d.runtime
                            and r.split("\t")[0].strip() != d.package)
