"""Updates from the project's GitHub releases. Pure Python, no GTK.

Checking only reads the release list (nothing about you is sent). Updating
downloads the release's source, checks it, and runs its install.sh into the
same place the running copy was installed, so no password is needed for a
home-folder install. The old copy is kept until the new one is in place,
and put back if installing fails. Your settings, icons and launchers live
elsewhere and aren't touched.
"""
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import List, Optional, Tuple

from . import APP_ID, VERSION

REPO = "HypestHyper/AppEntries"
API = "https://api.github.com/repos/" + REPO
PAGE = "https://github.com/%s/releases" % REPO
MAX_DOWNLOAD = 50 * 1024 * 1024
CHECK_EVERY = 6 * 3600  # seconds between automatic checks

HERE = os.path.dirname(os.path.abspath(__file__))


class UpdateError(Exception):
    pass


@dataclass
class Release:
    version: str        # without the leading v
    name: str
    notes: str
    tarball: str
    url: str
    prerelease: bool


def parse_version(text: str) -> Tuple[int, ...]:
    """(major, minor, patch, final): 1.2.3-beta sorts before 1.2.3."""
    m = re.match(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(.*)$", (text or "").strip())
    if not m:
        return (0, 0, 0, 0)
    return (int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0), 0 if m.group(4).strip("-+. ") else 1)


def is_newer(candidate: str, current: str = VERSION) -> bool:
    return parse_version(candidate) > parse_version(current)


def _get(url: str, timeout: float = 15):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "%s/%s" % (APP_ID, VERSION),
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read(4 * 1024 * 1024).decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise UpdateError("GitHub is limiting requests right now. Try again in an hour.") from e
        raise UpdateError("GitHub answered %d %s." % (e.code, e.reason)) from e
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise UpdateError("Couldn't reach GitHub: %s" % reason) from e
    except ValueError as e:
        raise UpdateError("GitHub sent something unexpected.") from e


def releases_from(data) -> List[Release]:
    out = []
    for r in data if isinstance(data, list) else []:
        if not isinstance(r, dict) or r.get("draft") or not r.get("tag_name"):
            continue
        tag = str(r["tag_name"])
        out.append(Release(tag.lstrip("vV"), str(r.get("name") or tag), str(r.get("body") or ""),
                           str(r.get("tarball_url") or ""), str(r.get("html_url") or PAGE),
                           bool(r.get("prerelease"))))
    return out


def tags_from(data) -> List[Release]:
    out = []
    for t in data if isinstance(data, list) else []:
        name = str(t.get("name") or "") if isinstance(t, dict) else ""
        if re.match(r"v?\d+\.\d+", name):
            out.append(Release(name.lstrip("vV"), name, "", str(t.get("tarball_url") or ""),
                               "https://github.com/%s/tree/%s" % (REPO, name), parse_version(name)[3] == 0))
    return out


def pick(found: List[Release], include_test: bool) -> Optional[Release]:
    usable = [r for r in found if r.tarball and (include_test or not r.prerelease)]
    return max(usable, key=lambda r: parse_version(r.version), default=None)


def latest(include_test: bool = False) -> Optional[Release]:
    """The newest release (or tag, when the project has no releases yet)."""
    found = releases_from(_get(API + "/releases?per_page=30"))
    if not found:
        found = tags_from(_get(API + "/tags?per_page=30"))
    return pick(found, include_test)


# ---------------------------------------------------------------------------
# Where this copy is installed


@dataclass
class Install:
    kind: str        # home, system, source (a git checkout) or unknown
    prefix: str = ""
    launcher: str = ""

    @property
    def can_update(self) -> bool:
        return self.kind == "home"


def location(here: str = HERE) -> Install:
    root = os.path.dirname(here)
    if os.path.isdir(os.path.join(root, ".git")):
        return Install("source")
    # install.sh puts the package in <prefix>/share/<APP_ID>/app_entries.
    share = os.path.dirname(root)
    if os.path.basename(root) != APP_ID or os.path.basename(share) != "share":
        return Install("unknown")
    prefix = os.path.dirname(share)
    launcher = os.path.join(prefix, "bin", APP_ID)
    if os.access(root, os.W_OK) and os.access(os.path.dirname(launcher), os.W_OK):
        return Install("home", prefix, launcher)
    return Install("system", prefix, launcher)


# ---------------------------------------------------------------------------
# Installing


def _download(url: str, dest: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "%s/%s" % (APP_ID, VERSION)})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
            total = 0
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOAD:
                    raise UpdateError("The download is larger than expected, so it was stopped.")
                f.write(chunk)
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError("The download failed: %s" % getattr(e, "reason", e)) from e


def _extract(archive: str, dest: str) -> str:
    """Unpack safely (no absolute paths, links or ..) and return the one
    top folder."""
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members = tar.getmembers()
            for m in members:
                name = os.path.normpath(m.name)
                if name.startswith(("/", "..")) or "/../" in "/%s/" % name or not (m.isfile() or m.isdir()):
                    raise UpdateError("The download contains an unsafe path (%s), so it wasn't used." % m.name)
            if hasattr(tarfile, "data_filter"):  # Python 3.12+, and security updates of older ones
                tar.extractall(dest, members=members, filter="data")
            else:
                tar.extractall(dest, members=members)
    except (tarfile.TarError, OSError) as e:
        raise UpdateError("The download couldn't be unpacked: %s" % e) from e
    tops = os.listdir(dest)
    if len(tops) != 1:
        raise UpdateError("The download doesn't look like an App Entries release.")
    top = os.path.join(dest, tops[0])
    if not (os.path.isfile(os.path.join(top, "install.sh"))
            and os.path.isfile(os.path.join(top, "app_entries", "__init__.py"))):
        raise UpdateError("The download doesn't look like an App Entries release.")
    return top


def install(release: Release, where: Optional[Install] = None) -> str:
    """Download and install the release over this copy. Returns the
    installer's output. Raises UpdateError, leaving the old copy working."""
    where = where or location()
    if not where.can_update:
        raise UpdateError("This copy can't update itself.")
    appdir = os.path.join(where.prefix, "share", APP_ID)
    with tempfile.TemporaryDirectory(prefix="app-entries-update-") as tmp:
        archive = os.path.join(tmp, "release.tar.gz")
        _download(release.tarball, archive)
        src = _extract(archive, os.path.join(tmp, "src"))
        backup = os.path.join(tmp, "previous")
        shutil.copytree(os.path.join(appdir, "app_entries"), backup)
        env = dict(os.environ, LC_ALL="C")
        try:
            r = subprocess.run(["sh", os.path.join(src, "install.sh"), "--prefix", where.prefix],
                               cwd=src, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, timeout=600, env=env)
            ok, log = r.returncode == 0, r.stdout
        except (OSError, subprocess.TimeoutExpired) as e:
            ok, log = False, str(e)
        if not ok:
            target = os.path.join(appdir, "app_entries")
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(backup, target)
            raise UpdateError("Installing the update failed, so the current version was kept.\n\n" + log[-2000:])
        return log
