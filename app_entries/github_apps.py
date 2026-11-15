"""Apps that come from GitHub: which project an app is from, whether a newer
release is out, and downloading it. Pure Python, no GTK.

The project is found without asking anything online: an AppImage's own
update information, the web address a browser saved a download from, or a
project the user linked by hand. GitHub is only contacted when the user
asks to check, and then only the project's public release list is read
(nothing about the user is sent). A download goes to a temporary file next
to the old one, is checked, and only then made ready; replacing the old
file is left to the caller, which keeps it in the Trash for Undo."""
import fnmatch
import json
import os
import platform
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import VERSION

API = "https://api.github.com/repos/"
AGENT = f"App-Entries/{VERSION}"
MAX_DOWNLOAD = 4 * 1024 * 1024 * 1024       # 4 GB: bigger than any AppImage worth updating this way

ARCHES = {
    "x86_64": ("x86_64", "x86-64", "amd64", "x64"),
    "aarch64": ("aarch64", "arm64"),
    "armv7l": ("armv7l", "armhf", "armv7"),
    "i686": ("i686", "i386", "x86"),
}


class GitHubError(Exception):
    pass


@dataclass
class Source:
    owner: str
    repo: str
    tag: str = "latest"          # latest, latest-pre, latest-all or a tag
    pattern: str = ""            # which release file, from the AppImage's update information
    how: str = ""                # appimage, download or linked

    @property
    def name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def page(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"


@dataclass
class Asset:
    name: str
    url: str
    size: int = 0


@dataclass
class Release:
    tag: str
    name: str = ""
    notes: str = ""
    url: str = ""
    published: str = ""
    prerelease: bool = False
    assets: list[Asset] = field(default_factory=list)


@dataclass
class Check:
    """What a check found for one app."""
    release: Release
    asset: Optional[Asset]       # the file to download, None if the release has no fitting AppImage
    current: str                 # the version in use, "" if it can't be told
    newer: bool


# ---------------------------------------------------------------------------
# finding the project


def _links_path(env=None) -> str:
    env = env if env is not None else os.environ
    home = env.get("HOME") or os.path.expanduser("~")
    state = env.get("XDG_STATE_HOME", "")
    base = state if os.path.isabs(state) else os.path.join(home, ".local", "state")
    return os.path.join(base, "app-entries", "github.json")


def _load(env=None) -> dict:
    try:
        with open(_links_path(env), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: dict, env=None) -> None:
    p = _links_path(env)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)
    os.replace(tmp, p)


def parse_project(text: str) -> Optional[tuple[str, str]]:
    """"owner/repo", or any github.com address of it, as (owner, repo)."""
    text = (text or "").strip()
    m = re.match(r"^(?:https?://)?(?:www\.)?github\.com/([\w.-]+)/([\w.-]+)", text) or \
        re.match(r"^([\w.-]+)/([\w.-]+)$", text)
    if not m:
        return None
    repo = m.group(2).removesuffix(".git")
    return m.group(1), repo


def link(app_id: str, project: str, env=None) -> Source:
    """Remember that an app comes from this GitHub project."""
    found = parse_project(project)
    if found is None:
        raise GitHubError("That isn't a GitHub project. Use owner/name, or the project's address.")
    data = _load(env)
    data.setdefault(app_id, {})["project"] = "/".join(found)
    _save(data, env)
    return Source(*found, how="linked")


def unlink(app_id: str, env=None) -> None:
    data = _load(env)
    if data.pop(app_id, None) is not None:
        _save(data, env)


def remember_installed(app_id: str, tag: str, file_name: str, project: str = "", env=None) -> None:
    """After an update: which release is in use now, so the next check is
    exact, and which project it came from."""
    data = _load(env)
    entry = data.setdefault(app_id, {})
    entry["tag"], entry["file"] = tag, file_name
    if project:
        entry["updated_from"] = project
    _save(data, env)


def source_of(app_id: str, update_info: str = "", origin: str = "", env=None) -> Optional[Source]:
    """The project an app comes from, or None. `update_info` is an
    AppImage's update information, `origin` the download's web address."""
    linked = _load(env).get(app_id, {}).get("project", "")
    if linked and parse_project(linked):
        return Source(*parse_project(linked), how="linked")
    parts = (update_info or "").split("|")
    if parts[0] in ("gh-releases-zsync", "gh-releases-direct") and len(parts) >= 4:
        pattern = parts[4] if len(parts) > 4 else ""
        return Source(parts[1], parts[2], parts[3] or "latest", pattern.removesuffix(".zsync"), "appimage")
    found = parse_project(origin) if "github.com/" in (origin or "") else None
    if found:
        return Source(*found, how="download")
    known = _load(env).get(app_id, {}).get("updated_from", "")
    if known and parse_project(known):
        return Source(*parse_project(known), how="updated")
    return None


# ---------------------------------------------------------------------------
# reading releases


def _get(url: str, timeout: float = 15):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read(8 * 1024 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise GitHubError("GitHub has no releases for this project (or it's private).") from e
        if e.code in (403, 429):
            reset = e.headers.get("X-RateLimit-Reset", "") if e.headers else ""
            when = time.strftime("%H:%M", time.localtime(int(reset))) if reset.isdigit() else ""
            raise GitHubError("GitHub allows a limited number of checks an hour without an account. "
                              + (f"Try again after {when}." if when else "Try again later.")) from e
        raise GitHubError(f"GitHub answered {e.code} {e.reason}.") from e
    except (urllib.error.URLError, OSError) as e:
        raise GitHubError(f"Couldn't reach GitHub: {getattr(e, 'reason', e)}") from e
    except ValueError as e:
        raise GitHubError("GitHub sent something unexpected.") from e


def _release(data) -> Release:
    return Release(
        tag=data.get("tag_name", ""), name=data.get("name") or "", notes=data.get("body") or "",
        url=data.get("html_url", ""), published=data.get("published_at") or "",
        prerelease=bool(data.get("prerelease")),
        assets=[Asset(a.get("name", ""), a.get("browser_download_url", ""), a.get("size", 0))
                for a in data.get("assets") or [] if a.get("browser_download_url")])


def latest(src: Source, get: Callable = _get) -> Release:
    base = API + src.name
    if src.tag in ("latest", ""):
        return _release(get(base + "/releases/latest"))
    if src.tag in ("latest-pre", "latest-all"):
        found = [r for r in get(base + "/releases?per_page=10") if not r.get("draft")]
        if src.tag == "latest-pre":
            found = [r for r in found if r.get("prerelease")] or found
        if not found:
            raise GitHubError("GitHub has no releases for this project.")
        return _release(found[0])
    return _release(get(base + "/releases/tags/" + src.tag))


# ---------------------------------------------------------------------------
# choosing the file and telling versions apart


def _arch_words(machine: str) -> tuple[tuple[str, ...], set[str]]:
    mine = ARCHES.get(machine, (machine,))
    others = {w for k, ws in ARCHES.items() if k != machine for w in ws} - set(mine)
    return mine, others


def _has_word(name: str, word: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", name.lower()) is not None


def pick_asset(assets: list[Asset], pattern: str = "", current: str = "",
               machine: str = "") -> Optional[Asset]:
    """The release file to use: the one the AppImage's update information
    names, else an AppImage for this computer's processor, closest in name
    to the file in use."""
    images = [a for a in assets if a.name.lower().endswith(".appimage")]
    if pattern:
        named = [a for a in images if fnmatch.fnmatchcase(a.name, pattern)]
        if named:
            images = named
    mine, others = _arch_words(machine or platform.machine())

    def other_arch(name):
        # This computer's words come out first, so "x86" doesn't match in "x86_64".
        low = name.lower()
        for w in sorted(mine, key=len, reverse=True):
            low = re.sub(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", " ", low)
        return any(_has_word(low, w) for w in others)
    fits = [a for a in images if not other_arch(a.name)]
    if not fits:
        return None
    exact = [a for a in fits if any(_has_word(a.name, w) for w in mine)]
    pool = exact or fits

    def closeness(a):
        stem = re.sub(r"\d+(\.\d+)+", "", a.name.lower())
        cur = re.sub(r"\d+(\.\d+)+", "", (current or "").lower())
        common = len(os.path.commonprefix([stem, cur]))
        return (-common, len(a.name))
    return min(pool, key=closeness)


def version_in(text: str) -> str:
    """A version number in a tag or file name: "v1.8.0" or "Tool-1.8.0-x86_64" give "1.8.0"."""
    m = re.search(r"(?<![\d.])v?(\d+(?:\.\d+)+)", text or "")
    if m:
        return m.group(1)
    m = re.search(r"(?<![\w.])v?(\d+)(?![\w.])", text or "")
    return m.group(1) if m else ""


def _key(v: str) -> tuple:
    return tuple(int(x) for x in v.split(".") if x.isdigit())


def compare(app_id: str, path: str, release: Release, asset: Optional[Asset], env=None) -> Check:
    """Whether the release is newer than the file in use."""
    name = os.path.basename(path)
    known = _load(env).get(app_id, {})
    if known.get("tag") and known.get("file") == name:
        # App Entries put this release in place itself, so it knows.
        current = version_in(known["tag"]) or known["tag"]
        return Check(release, asset, current, known["tag"] != release.tag)
    current = version_in(name)
    latest_v = version_in(release.tag) or version_in(release.name)
    if current and latest_v:
        newer = _key(latest_v) > _key(current)
    elif asset is not None:
        # No version in the name: the same file name and size mean the same file.
        try:
            same_size = asset.size and os.path.getsize(path) == asset.size
        except OSError:
            same_size = False
        newer = not (asset.name == name or same_size)
    else:
        newer = False
    return Check(release, asset, current, newer)


def check(app_id: str, path: str, src: Source, get: Callable = _get, env=None, machine: str = "") -> Check:
    rel = latest(src, get)
    asset = pick_asset(rel.assets, src.pattern, os.path.basename(path), machine)
    return compare(app_id, path, rel, asset, env)


# ---------------------------------------------------------------------------
# downloading


def download(asset: Asset, folder: str, progress: Callable[[int, int], None] = lambda done, total: None,
             opener: Optional[Callable] = None, cancelled: Callable[[], bool] = lambda: False) -> str:
    """Download next to the old file and return its path. It's written to a
    hidden .part file first, checked (size, and that it's a program), and
    only then given its name; nothing is left behind if anything fails."""
    import urllib.error
    import urllib.request
    name = os.path.basename(asset.name)
    if not name or name.startswith("."):
        raise GitHubError("The release file has no usable name.")
    final = os.path.join(folder, name)
    if os.path.exists(final):
        stem, ext = os.path.splitext(name)
        n = 2
        while os.path.exists(os.path.join(folder, f"{stem}-{n}{ext}")):
            n += 1
        final = os.path.join(folder, f"{stem}-{n}{ext}")
    part = os.path.join(folder, "." + os.path.basename(final) + ".part")
    if not asset.url.startswith("https://"):
        raise GitHubError("The release file's address isn't a secure web address, so it wasn't downloaded.")
    req = urllib.request.Request(asset.url, headers={"User-Agent": AGENT})
    opener = opener or urllib.request.urlopen
    try:
        with opener(req, timeout=60) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or asset.size or 0) if hasattr(r, "headers") else asset.size
            done = 0
            while True:
                if cancelled():
                    raise GitHubError("Stopped.")
                chunk = r.read(512 * 1024)
                if not chunk:
                    break
                done += len(chunk)
                if done > MAX_DOWNLOAD:
                    raise GitHubError("The download is far larger than an app should be, so it was stopped.")
                f.write(chunk)
                progress(done, total)
        if asset.size and done != asset.size:
            raise GitHubError("The download was cut short. Nothing was changed.")
        with open(part, "rb") as f:
            if f.read(4) != b"\x7fELF":
                raise GitHubError("The downloaded file isn't an AppImage. Nothing was changed.")
        os.chmod(part, 0o755)
        try:
            # As browsers do, so it's still known where it came from.
            os.setxattr(part, "user.xdg.origin.url", asset.url.encode())
        except (OSError, AttributeError):
            pass
        os.replace(part, final)
        return final
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise GitHubError(f"The download failed: {getattr(e, 'reason', e)}") from e
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except OSError:
                pass
