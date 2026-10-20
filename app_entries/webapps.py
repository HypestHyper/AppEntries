"""Web apps: a site in its own window, with no address bar or tabs, using a
Chromium-based browser's app mode (--app=URL). Pure Python, no GTK.

Firefox has no such mode (its --kiosk is full screen with no way out), so
it isn't offered.
"""
import html.parser
import os
import shlex
import shutil
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional, Tuple

from . import APP_ID, VERSION
from . import desktop_entries as de

# id, name, commands, Flatpak IDs
BROWSERS = [
    ("chromium", "Chromium", ["chromium", "chromium-browser", "ungoogled-chromium"],
     ["org.chromium.Chromium", "io.github.ungoogled_software.ungoogled_chromium"]),
    ("chrome", "Google Chrome", ["google-chrome-stable", "google-chrome"], ["com.google.Chrome"]),
    ("brave", "Brave", ["brave", "brave-browser", "brave-browser-stable"], ["com.brave.Browser"]),
    ("vivaldi", "Vivaldi", ["vivaldi-stable", "vivaldi"], ["com.vivaldi.Vivaldi"]),
    ("edge", "Microsoft Edge", ["microsoft-edge-stable", "microsoft-edge"], ["com.microsoft.Edge"]),
    ("thorium", "Thorium", ["thorium-browser"], []),
    ("helium", "Helium", ["helium-browser", "helium"], []),
]
MAX_ICON = 2 * 1024 * 1024


def _flatpak_bins(env) -> List[str]:
    home = env.get("HOME") or os.path.expanduser("~")
    return [os.path.join(home, ".local", "share", "flatpak", "exports", "bin"), "/var/lib/flatpak/exports/bin"]


def installed(env=None) -> List[Tuple[str, str, str]]:
    """(id, name, program) for each Chromium-based browser found."""
    env = os.environ if env is None else env
    from .health import search_dirs
    path = ":".join(search_dirs(env))
    out = []
    for bid, name, commands, flatpaks in BROWSERS:
        program = next((p for p in (shutil.which(c, path=path) for c in commands) if p), None)
        if program is None:
            for folder in _flatpak_bins(env):
                program = next((os.path.join(folder, f) for f in flatpaks
                                if os.access(os.path.join(folder, f), os.X_OK)), None)
                if program:
                    name += " (Flatpak)"
                    break
        if program:
            out.append((bid, name, program))
    return out


def has_firefox(env=None) -> bool:
    env = os.environ if env is None else env
    from .health import search_dirs
    return bool(shutil.which("firefox", path=":".join(search_dirs(env))))


def normalize(url: str) -> str:
    """https:// added when there's no scheme. Raises ValueError for anything
    that isn't a web address."""
    u = url.strip()
    if not u:
        raise ValueError("Enter the site's address.")
    if "://" not in u:
        u = "https://" + u
    p = urllib.parse.urlsplit(u)
    if p.scheme not in ("http", "https") or not p.hostname or " " in u:
        raise ValueError("That isn't a web address. It should look like example.com or https://example.com/app.")
    return u


def name_for(url: str) -> str:
    """A starting name from the address: mail.example.com -> Mail Example."""
    host = urllib.parse.urlsplit(normalize(url)).hostname or ""
    parts = [p for p in host.split(".") if p not in ("www", "app", "web")][:-1] or host.split(".")[:1]
    return " ".join(p.capitalize() for p in parts)


def profile_dir(did: str, env=None) -> str:
    return os.path.join(de.user_data_dir(env), "app-entries", "web-apps", did[:-len(".desktop")])


# Dark mode choices and the Chromium options for them.
DARK = {
    "system": [],
    "dark": ["--force-dark-mode"],                    # sites that have a dark theme use it
    "force": ["--force-dark-mode", "--enable-features=WebContentsForceDark"],  # every page made dark
}

# What each browser's app windows are called (X11 class / Wayland app_id):
# <prefix>-<host>__<path>-<profile folder>, like chrome-web.whatsapp.com__-Default.
CLASS_PREFIX = {"chromium": "chromium", "chrome": "chrome", "brave": "brave", "vivaldi": "vivaldi",
                "edge": "msedge", "thorium": "thorium", "helium": "helium"}


def args_for(url: str, profile: str = "", dark: str = "system") -> str:
    argv = ["--app=" + url]
    if profile:
        argv.append("--user-data-dir=" + profile)
    argv += DARK.get(dark, [])
    return shlex.join(argv)


def dark_of(args: str) -> str:
    try:
        words = shlex.split(args)
    except ValueError:
        return "system"
    if any("WebContentsForceDark" in w for w in words):
        return "force"
    return "dark" if "--force-dark-mode" in words else "system"


def window_class(url: str, browser: str) -> str:
    """The class Chromium-based browsers usually give this site's app window,
    so docks can match it to the launcher and window rules can use it."""
    p = urllib.parse.urlsplit(normalize(url))
    path = (p.path or "/").replace("/", "_")
    if p.query:
        path += "_" + p.query.replace("/", "_")
    return "%s-%s_%s-Default" % (CLASS_PREFIX.get(browser, "chrome"), p.hostname or "", path)


def profile_of(args: str) -> str:
    """The --user-data-dir in a web app's arguments, or ""."""
    try:
        for a in shlex.split(args):
            if a.startswith("--user-data-dir="):
                return a.split("=", 1)[1]
    except ValueError:
        pass
    return ""


def own_data(args: str, env=None) -> str:
    """The web app's own sign-ins folder, if it has one App Entries made.
    A browser's own profile (no --user-data-dir, or one pointing anywhere
    else) is never returned, so it can't be offered for deletion."""
    folder = os.path.realpath(profile_of(args)) if profile_of(args) else ""
    root = os.path.realpath(os.path.join(de.user_data_dir(env), "app-entries", "web-apps"))
    if folder and folder.startswith(root + os.sep) and os.path.isdir(folder):
        return folder
    return ""


# ---------------------------------------------------------------------------
# The site's icon


class _Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.icons = []  # (score, href)

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        rel = a.get("rel", "").lower().split()
        href = a.get("href", "")
        if not href or not ({"icon", "apple-touch-icon", "apple-touch-icon-precomposed"} & set(rel)):
            return
        size = 0
        for s in a.get("sizes", "").lower().split():
            if "x" in s and s.split("x")[0].isdigit():
                size = max(size, int(s.split("x")[0]))
        if href.lower().split("?")[0].endswith(".svg") or a.get("type", "") == "image/svg+xml":
            size = 1000  # scales to any size
        elif "apple-touch-icon" in " ".join(rel):
            size = max(size, 180)
        self.icons.append((size, href))


def icon_candidates(page_url: str, html_text: str) -> List[str]:
    """Icon addresses from a page, best first, then the usual fallbacks."""
    parser = _Links()
    try:
        parser.feed(html_text)
    except Exception:  # noqa: BLE001 - a broken page just has no links
        pass
    found = [urllib.parse.urljoin(page_url, h) for _s, h in sorted(parser.icons, key=lambda x: -x[0])]
    root = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(page_url))
    for fallback in ("/apple-touch-icon.png", "/favicon.ico"):
        if root + fallback not in found:
            found.append(root + fallback)
    return [u for u in found if urllib.parse.urlsplit(u).scheme in ("http", "https")]


def _get(url: str, limit: int) -> Tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (%s %s)" % (APP_ID, VERSION)})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = r.read(limit + 1)
        if len(data) > limit:
            raise ValueError("too large")
        return data, r.headers.get("Content-Type", "")


def fetch_icon(url: str) -> Tuple[bytes, str]:
    """The site's best icon: (data, kind), kind being svg, png or other
    (ico, jpeg, webp: for the caller to convert). Raises ValueError."""
    url = normalize(url)
    page = ""
    try:
        data, ctype = _get(url, 2 * 1024 * 1024)
        if "html" in ctype:
            page = data.decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        pass
    for candidate in icon_candidates(url, page):
        try:
            data, ctype = _get(candidate, MAX_ICON)
        except (urllib.error.URLError, OSError, ValueError):
            continue
        kind = sniff(data)
        if kind:
            return data, kind
    raise ValueError("The site doesn't offer an icon App Entries can use. Pick a styled icon instead.")


def sniff(data: bytes) -> Optional[str]:
    head = data[:512].lstrip()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in data[:2048]):
        return "svg"
    if data[:4] in (b"\x00\x00\x01\x00",) or data[:3] == b"\xff\xd8\xff" or data[8:12] == b"WEBP" \
            or data[:6] in (b"GIF87a", b"GIF89a"):
        return "other"
    return None
