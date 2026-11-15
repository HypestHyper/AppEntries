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
    approx: bool = False         # the size is rounded (read from github.com's page, not the API)


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


def source_of(app_id: str, update_info: str = "", origin: str = "", env=None, project: str = "",
              how: str = "") -> Optional[Source]:
    """The project an app comes from, or None. `update_info` is an
    AppImage's update information, `origin` the download's web address,
    `project` an address found another way (`how`: pip, git or homepage)."""
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
    found = parse_project(project) if "github.com/" in (project or "") else None
    if found:
        return Source(*found, how=how or "homepage")
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


# ---------------------------------------------------------------------------
# reading releases from github.com's own pages
#
# GitHub's API allows 60 questions an hour without an account, which a list
# of apps uses up fast. github.com's pages answer the same questions without
# that limit: /releases/latest redirects to the newest version's page, the
# release's file list is a small page of its own, and releases.atom lists
# recent versions with their notes. The API is only asked if they fail.

WEB = "https://github.com/"
_remembered: dict = {}          # (project, tag) -> (when, Release): asked within the hour
REMEMBER = 3600


def _fetch(url: str, follow: bool = True, timeout: float = 15) -> tuple[int, dict, bytes]:
    """(status, headers, body) of a github.com page."""
    import urllib.error
    import urllib.request

    class Stay(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(Stay)
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "text/html,application/atom+xml"})
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read(4 * 1024 * 1024)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), b""
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise GitHubError(f"Couldn't reach GitHub: {getattr(e, 'reason', e)}") from e


def web_latest_tag(src: Source, fetch: Callable = _fetch) -> str:
    """The newest (non-test) release's tag, from where /releases/latest leads."""
    status, headers, _body = fetch(WEB + src.name + "/releases/latest", False)
    where = headers.get("Location") or headers.get("location") or ""
    m = re.search(r"/releases/tag/([^/?#]+)", where)
    if status in (301, 302, 303, 307, 308) and m:
        from urllib.parse import unquote
        return unquote(m.group(1))
    if status == 404 or (status in (301, 302) and not m):
        raise GitHubError("GitHub has no releases for this project (or it's private).")
    raise GitHubError(f"GitHub answered {status}.")


_SIZE = {"B": 1, "KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}


def web_assets(src: Source, tag: str, fetch: Callable = _fetch) -> list[Asset]:
    """A release's files, from its file list page (the source code archives
    GitHub adds to every release are left out)."""
    from html import unescape
    from urllib.parse import quote, unquote
    status, _h, body = fetch(WEB + src.name + "/releases/expanded_assets/" + quote(tag, safe=""))
    if status != 200:
        raise GitHubError(f"GitHub answered {status}.")
    html = body.decode("utf-8", "replace")
    out, seen = [], set()
    for m in re.finditer(r'href="(/[^"]+/releases/download/[^"]+)"', html):
        path = unescape(m.group(1))
        name = unquote(path.rsplit("/", 1)[1])
        if name in seen:
            continue
        seen.add(name)
        size = 0
        # The size follows the link, before the next file's link.
        nxt = html.find("/releases/download/", m.end())
        after = html[m.end():nxt if nxt > 0 else m.end() + 6000]
        sm = re.search(r">\s*([\d.]+)\s*(B|KB|MB|GB)\s*<", after)
        if sm:
            size = int(float(sm.group(1)) * _SIZE[sm.group(2)])
        out.append(Asset(name, "https://github.com" + path, size, approx=True))
    return out


def web_releases(src: Source, fetch: Callable = _fetch) -> list[Release]:
    """Recent releases with their notes, newest first, from releases.atom
    (it doesn't say which are test versions)."""
    from html import unescape
    status, _h, body = fetch(WEB + src.name + "/releases.atom")
    if status != 200:
        raise GitHubError(f"GitHub answered {status}.")
    text = body.decode("utf-8", "replace")
    out = []
    for entry in re.findall(r"<entry>(.*?)</entry>", text, flags=re.DOTALL):
        link = re.search(r'<link[^>]+href="([^"]+)"', entry)
        tag = re.search(r"/releases/tag/([^\"/?#]+)", link.group(1)).group(1) if link and "/releases/tag/" in \
            link.group(1) else ""
        if not tag:
            continue
        from urllib.parse import unquote
        title = re.search(r"<title>(.*?)</title>", entry, flags=re.DOTALL)
        content = re.search(r"<content[^>]*>(.*?)</content>", entry, flags=re.DOTALL)
        updated = re.search(r"<updated>(.*?)</updated>", entry)
        notes = unescape(content.group(1)) if content else ""
        notes = unescape(re.sub(r"<[^>]+>", "", notes.replace("<li>", "- ").replace("</p>", "\n").replace(
            "<br>", "\n")))
        out.append(Release(unquote(tag), unescape(title.group(1)).strip() if title else "", notes.strip(),
                           WEB + src.name + "/releases/tag/" + tag, updated.group(1) if updated else ""))
    return out


def latest_web(src: Source, fetch: Callable = _fetch, notes: bool = False) -> Release:
    if src.tag in ("latest", ""):
        tag = web_latest_tag(src, fetch)
    elif src.tag in ("latest-pre", "latest-all"):
        found = web_releases(src, fetch)
        if not found:
            raise GitHubError("GitHub has no releases for this project.")
        tag = found[0].tag
    else:
        tag = src.tag
    rel = Release(tag, url=WEB + src.name + "/releases/tag/" + tag)
    rel.assets = web_assets(src, tag, fetch)
    if notes:
        try:
            match = next((r for r in web_releases(src, fetch) if r.tag == tag), None)
            if match is not None:
                rel.name, rel.notes, rel.published = match.name, match.notes, match.published
        except GitHubError:
            pass
    return rel


def latest(src: Source, get: Callable = _get, fetch: Callable = _fetch, notes: bool = True) -> Release:
    """The release to compare with: from github.com's pages, remembered for
    an hour; the API only if the pages fail (or when tests pass their own `get`)."""
    import time as _time
    key = (src.name, src.tag)
    hit = _remembered.get(key)
    if hit is not None and _time.time() - hit[0] < REMEMBER and get is _get:
        return hit[1]
    if get is _get:
        try:
            rel = latest_web(src, fetch, notes)
            _remembered[key] = (_time.time(), rel)
            return rel
        except GitHubError as e:
            if "no releases" in str(e):
                raise
    rel = latest_api(src, get)
    if get is _get:
        _remembered[key] = (_time.time(), rel)
    return rel


def latest_api(src: Source, get: Callable = _get) -> Release:
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
               machine: str = "", ext: str = ".appimage") -> Optional[Asset]:
    """The release file to use: the one the AppImage's update information
    names, else a file of this type (.appimage, .deb, .rpm) for this
    computer's processor, closest in name to the file in use."""
    images = [a for a in assets if a.name.lower().endswith(ext)]
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
            same_size = asset.size and not asset.approx and os.path.getsize(path) == asset.size
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


PACKAGE_FILES = {"apt": ".deb", "dnf": ".rpm", "zypper": ".rpm"}


def check_version(src: Source, installed: str, kind: str = "", get: Callable = _get, machine: str = "") -> Check:
    """For apps whose version is known (a package, a Python app): whether
    the latest release is newer, and for a package the release's .deb or
    .rpm for this computer."""
    rel = latest(src, get)
    ext = PACKAGE_FILES.get(kind, "")
    asset = pick_asset(rel.assets, "", installed, machine, ext) if ext else None
    current = version_in(installed) or installed
    latest_v = version_in(rel.tag) or version_in(rel.name)
    newer = bool(current and latest_v and _key(latest_v) > _key(current))
    if not (current and latest_v):
        newer = bool(latest_v or rel.tag) and rel.tag not in (installed or "")
    return Check(rel, asset, current, newer)


# ---------------------------------------------------------------------------
# downloading


MAGIC = {".appimage": (b"\x7fELF", "an AppImage"), ".deb": (b"!<arch>", "a .deb package"),
         ".rpm": (b"\xed\xab\xee\xdb", "an .rpm package")}


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
            sent = int((r.headers.get("Content-Length") if hasattr(r, "headers") else 0) or 0)
            total = sent or asset.size
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
        expected = asset.size if asset.size and not asset.approx else sent
        if expected and done != expected:
            raise GitHubError("The download was cut short. Nothing was changed.")
        ext = next((e for e in MAGIC if name.lower().endswith(e)), ".appimage")
        magic, what = MAGIC[ext]
        with open(part, "rb") as f:
            if f.read(len(magic)) != magic:
                raise GitHubError(f"The downloaded file isn't {what}. Nothing was changed.")
        os.chmod(part, 0o755 if ext == ".appimage" else 0o644)
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
