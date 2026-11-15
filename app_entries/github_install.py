"""Installing an app straight from its GitHub project. Pure Python, no GTK.

Given a project link, App Entries reads the project and its releases
(three questions to GitHub at most), and ranks each release's files for
this computer: an AppImage, an app archive, a package for this system or a
Flatpak bundle. Projects that only publish source code get the usual
command for their language (pipx, cargo, go install, npm) or a git clone.
A download is checked against the release's checksum file when it has one,
and archives are unpacked without letting any file land outside their
folder. Installing itself goes through the same steps as adding a
downloaded app, or runs in the user's terminal."""
import hashlib
import os
import platform
import re
import shutil
import tarfile
import zipfile
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import github_apps

KIND_ORDER = {"appimage": 0, "archive": 1, "package": 2, "flatpak": 3}
OTHER_SYSTEMS = ("windows", "win32", "win64", "-win-", "_win_", "macos", "darwin", "osx", "-mac-", "_mac_",
                 "-mac.", "android", "freebsd", "openbsd", "ios")
SKIP = (".sha256", ".sha512", ".sha1", ".md5", ".sig", ".asc", ".minisig", ".pem", ".zsync", ".blockmap",
        ".sbom", ".spdx", ".json", ".txt", ".yml", ".yaml", ".exe", ".msi", ".dmg", ".pkg", ".apk", ".msix",
        ".nupkg", ".sh256", ".intoto.jsonl")
ARCHIVES = (".tar.gz", ".tgz", ".tar.xz", ".txz", ".tar.bz2", ".tar.zst", ".zip")
PACKAGE_EXT = {"apt": ".deb", "dnf": ".rpm", "zypper": ".rpm", "rpm-ostree": ".rpm", "pacman": ".pkg.tar.zst"}


@dataclass
class Project:
    owner: str
    repo: str
    description: str = ""
    homepage: str = ""
    stars: int = 0
    archived: bool = False
    language: str = ""

    @property
    def name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"


@dataclass
class Choice:
    """One way to install a release."""
    kind: str                      # appimage, archive, package, flatpak or source
    title: str                     # what it is, in words
    why: str = ""                  # why it's suggested (or not first)
    asset: Optional[github_apps.Asset] = None
    commands: list = field(default_factory=list)   # for source: what runs in the terminal
    fits: bool = True              # made for this computer


TEST_WORDS = re.compile(r"(?<![a-z])(alpha|beta|rc\d*|pre|preview|nightly|dev|canary|snapshot|insider)(?![a-z])",
                        re.IGNORECASE)


def fetch(text: str, web: Callable = github_apps._fetch) -> Project:
    """The project, read from its page on github.com (not the API, which
    allows few questions an hour)."""
    from html import unescape
    found = github_apps.parse_project(text)
    if found is None:
        raise github_apps.GitHubError("That isn't a GitHub project. Paste its address, or owner/name.")
    status, _h, body = web(github_apps.WEB + "/".join(found))
    if status == 404:
        raise github_apps.GitHubError("GitHub has no project at that address (or it's private).")
    if status != 200:
        raise github_apps.GitHubError(f"GitHub answered {status}.")
    html = body.decode("utf-8", "replace")
    m = re.search(r'<meta property="og:description" content="([^"]*)"', html)
    desc = unescape(m.group(1)) if m else ""
    desc = re.sub(r"\s*(- )?Contribute to [\w.-]+/[\w.-]+ development by creating an account on GitHub\.?$",
                  "", desc).strip()
    if desc.startswith("Contribute to "):
        desc = ""
    return Project(found[0], found[1], desc, archived="This repository has been archived" in html)


def is_test(rel: github_apps.Release) -> bool:
    """A test version (the releases feed doesn't say, so its name does)."""
    return rel.prerelease or bool(TEST_WORDS.search(rel.tag + " " + rel.name))


def releases(p: Project, web: Callable = github_apps._fetch, include_test: bool = False,
             get: Callable = github_apps._get) -> list[github_apps.Release]:
    """Recent releases, newest first, without their files (files() reads
    those for the one chosen). From github.com's releases feed; the API only
    if that fails."""
    src = github_apps.Source(p.owner, p.repo)
    try:
        out = github_apps.web_releases(src, web)
    except github_apps.GitHubError:
        try:
            data = get(github_apps.API + p.name + "/releases?per_page=30")
            out = [github_apps._release(r) for r in data if not r.get("draft")]
        except github_apps.GitHubError:
            return []
    return [r for r in out if include_test or not is_test(r)]


def files(p: Project, rel: github_apps.Release, web: Callable = github_apps._fetch) -> list[github_apps.Asset]:
    if rel.assets:
        return rel.assets
    rel.assets = github_apps.web_assets(github_apps.Source(p.owner, p.repo), rel.tag, web)
    return rel.assets


# ---------------------------------------------------------------------------
# choosing a file


def _ext(name: str) -> str:
    low = name.lower()
    for e in ARCHIVES + (".pkg.tar.zst", ".appimage", ".deb", ".rpm", ".flatpak", ".flatpakref"):
        if low.endswith(e):
            return e
    return os.path.splitext(low)[1]


def _other_arch(name: str, machine: str) -> bool:
    mine, others = github_apps._arch_words(machine)
    low = name.lower()
    for w in sorted(mine, key=len, reverse=True):
        low = re.sub(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", " ", low)
    return any(github_apps._has_word(low, w) for w in others)


def _named_arch(name: str, machine: str) -> bool:
    mine, _others = github_apps._arch_words(machine)
    return any(github_apps._has_word(name, w) for w in mine)


def choices(rel: github_apps.Release, manager: str = "", machine: str = "") -> list[Choice]:
    """Every file in the release that could install the app, best first.
    Ones for other processors or systems are left out."""
    machine = machine or platform.machine()
    out = []
    for a in rel.assets:
        low, ext = a.name.lower(), _ext(a.name)
        if any(low.endswith(s) for s in SKIP) or any(o in low for o in OTHER_SYSTEMS) or _other_arch(a.name, machine):
            continue
        if ext == ".appimage":
            out.append(Choice("appimage", "AppImage", "A single file that runs on any distribution. Kept in "
                              "~/Applications, with a menu entry and updates from GitHub.", a))
        elif ext in ARCHIVES:
            if "src" in low or "source" in low:
                continue
            out.append(Choice("archive", "App archive", "Unpacked into its own folder in ~/Applications, with a "
                              "menu entry.", a))
        elif ext in (".deb", ".rpm", ".pkg.tar.zst"):
            fits = PACKAGE_EXT.get(manager) == ext
            out.append(Choice("package", f"{ext.lstrip('.').split('.')[0]} package",
                              f"Installed with {manager} in your terminal." if fits else
                              f"A package for another kind of system than this one ({manager or 'unknown'}).",
                              a, fits=fits))
        elif ext in (".flatpak", ".flatpakref"):
            out.append(Choice("flatpak", "Flatpak bundle", "Installed for you with Flatpak in your terminal.", a,
                              fits=bool(shutil.which("flatpak"))))

    def rank(c):
        return (not c.fits, KIND_ORDER.get(c.kind, 9), not _named_arch(c.asset.name, machine), len(c.asset.name))
    return sorted(out, key=rank)


def checksum_asset(rel: github_apps.Release, name: str) -> Optional[github_apps.Asset]:
    """The release's checksum file covering `name`, if it has one."""
    for a in rel.assets:
        low = a.name.lower()
        if low in (name.lower() + ".sha256", name.lower() + ".sha256sum"):
            return a
    for a in rel.assets:
        low = a.name.lower()
        if re.search(r"(sha256|checksum|sums)", low) and not low.endswith((".sig", ".asc", ".pem")):
            return a
    return None


def verify(path: str, name: str, text: str) -> Optional[bool]:
    """True if the file's SHA-256 matches the checksum list, False if it
    doesn't, None if the list doesn't mention it."""
    want = ""
    for line in text.splitlines():
        parts = line.strip().replace("*", " ").split()
        if len(parts) == 1 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            want = parts[0]          # a .sha256 file with just the sum
        elif len(parts) >= 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]) and \
                os.path.basename(parts[-1]) == name:
            want = parts[0]
            break
    if not want:
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower() == want.lower()


def fetch_text(asset: github_apps.Asset, opener: Optional[Callable] = None, limit: int = 1024 * 1024) -> str:
    import urllib.request
    req = urllib.request.Request(asset.url, headers={"User-Agent": github_apps.AGENT})
    with (opener or urllib.request.urlopen)(req, timeout=30) as r:
        return r.read(limit).decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# projects with no files to download: install from source


RAW = "https://raw.githubusercontent.com/"
SOURCE_FILES = ("pyproject.toml", "setup.py", "Cargo.toml", "go.mod", "package.json")


def _file(p: Project, path: str, web: Callable) -> str:
    """A file from the project's main branch, or "" (raw.githubusercontent.com
    isn't limited like the API)."""
    try:
        status, _h, body = web(RAW + p.name + "/HEAD/" + path)
    except github_apps.GitHubError:
        return ""
    return body.decode("utf-8", "replace") if status == 200 else ""


def from_source(p: Project, web: Callable = github_apps._fetch, which: Callable = shutil.which,
                home: str = "") -> list[Choice]:
    """The usual way to install the project from its code, by what its files
    say it is written in, plus a git clone."""
    home = home or os.path.expanduser("~")
    texts = {n: _file(p, n, web) for n in SOURCE_FILES}
    names = {n for n, t in texts.items() if t}
    url = p.url
    out = []
    if names & {"pyproject.toml", "setup.py"}:
        if which("pipx"):
            out.append(Choice("source", "Python app, with pipx", "pipx gives it its own environment and puts "
                              "its commands in ~/.local/bin.", commands=[["pipx", "install", "git+" + url]]))
        if which("uv"):
            out.append(Choice("source", "Python app, with uv", "uv gives it its own environment and puts its "
                              "commands in ~/.local/bin.", commands=[["uv", "tool", "install", "git+" + url]]))
    if "Cargo.toml" in names:
        out.append(Choice("source", "Rust, with cargo", "cargo builds it and puts it in ~/.cargo/bin.",
                          commands=[["cargo", "install", "--git", url]], fits=bool(which("cargo"))))
    if "go.mod" in names:
        m = re.search(r"^module\s+(\S+)", texts["go.mod"], flags=re.MULTILINE)
        module = m.group(1) if m else f"github.com/{p.name}"
        out.append(Choice("source", "Go, with go install", "go builds it and puts it in ~/go/bin.",
                          commands=[["go", "install", module + "@latest"]], fits=bool(which("go"))))
    if "package.json" in names:
        out.append(Choice("source", "Node, with npm", "npm installs it for you, with its commands.",
                          commands=[["npm", "install", "-g", "github:" + p.name]], fits=bool(which("npm"))))
    target = os.path.join(home, "Apps", p.repo)
    out.append(Choice("source", "A copy of the code, with git", f"Cloned to ~/Apps/{p.repo}; its README says "
                      "how to build or run it.", commands=[["git", "clone", url, target]], fits=bool(which("git"))))
    return out


# ---------------------------------------------------------------------------
# unpacking an app archive


class UnsafeArchive(Exception):
    pass


def _inside(base: str, name: str) -> bool:
    target = os.path.realpath(os.path.join(base, name))
    return target == os.path.realpath(base) or target.startswith(os.path.realpath(base) + os.sep)


def unpack(archive: str, apps_dir: str, name: str) -> str:
    """Unpack into a new folder in `apps_dir` (named after the app, never
    overwriting) and return it. A single top folder inside the archive
    becomes the app's folder. Refuses archives with paths that lead out."""
    stem = re.sub(r"[^\w.+-]+", "-", name).strip("-") or "app"
    target, n = os.path.join(apps_dir, stem), 2
    while os.path.exists(target):
        target, n = os.path.join(apps_dir, f"{stem}-{n}"), n + 1
    work = target + ".unpacking"
    os.makedirs(work)
    try:
        if archive.lower().endswith(".zip"):
            with zipfile.ZipFile(archive) as z:
                for info in z.infolist():
                    if not _inside(work, info.filename):
                        raise UnsafeArchive(f"{info.filename} would land outside the app's folder")
                z.extractall(work)
                for info in z.infolist():
                    mode = info.external_attr >> 16
                    if mode & 0o111 and not info.is_dir():
                        os.chmod(os.path.join(work, info.filename), 0o755)
        else:
            with tarfile.open(archive) as t:
                for m in t.getmembers():
                    # A symbolic link points from its own folder; a hard link from the archive's top.
                    link = (os.path.join(os.path.dirname(m.name), m.linkname) if m.issym() else
                            m.linkname if m.islnk() else "")
                    if not _inside(work, m.name) or m.isdev() or (link and not _inside(work, link)):
                        raise UnsafeArchive(f"{m.name} would land outside the app's folder")
                if hasattr(tarfile, "data_filter"):
                    t.extractall(work, filter="data")
                else:
                    t.extractall(work)
        inner = os.listdir(work)
        if len(inner) == 1 and os.path.isdir(os.path.join(work, inner[0])):
            os.rename(os.path.join(work, inner[0]), target)
            os.rmdir(work)
        else:
            os.rename(work, target)
        return target
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise


def mark_origin(folder: str, url: str) -> None:
    """Note where an unpacked app came from on its programs, as browsers do
    for downloads, so it's still known as a GitHub app later."""
    for root in (folder, os.path.join(folder, "bin")):
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for n in names:
            p = os.path.join(root, n)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                try:
                    os.setxattr(p, "user.xdg.origin.url", url.encode())
                except (OSError, AttributeError):
                    pass
