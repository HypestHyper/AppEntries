"""Command-line tools in your home folder that have no menu entry: installed
with cargo, go, pipx, uv or npm, or put in ~/.local/bin by hand. Pure
Python, no GTK. Only reads files; the commands that update or remove a tool
are run by the user, in a terminal."""
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from . import APP_ID, install_info, pkgmanagers, uninstall

KINDS = {
    "cargo": "Rust · cargo", "go": "Go · go install", "pipx": "Python · pipx", "uv": "Python · uv",
    "npm": "Node · npm", "file": "A file in ~/.local/bin",
    # Packages you installed with the system's package manager.
    "pacman": "pacman", "apt": "apt", "dnf": "dnf", "zypper": "zypper", "rpm-ostree": "rpm-ostree",
    "xbps": "xbps", "apk": "apk", "portage": "Portage", "nix": "Nix",
}
SYSTEM_KINDS = ("pacman", "apt", "dnf", "zypper", "rpm-ostree", "xbps", "apk", "portage", "nix")
BIN_DIRS = ("/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/games", "/usr/local/bin")


@dataclass
class Tool:
    name: str
    kind: str                       # cargo, go, pipx, uv, npm or file
    version: str = ""
    commands: list[str] = field(default_factory=list)   # the command names it adds
    paths: list[str] = field(default_factory=list)      # those files
    folder: str = ""                # its own folder, if it has one
    size: int = 0
    project: str = ""               # where it came from (a web address), if known
    update: list = field(default_factory=list)          # commands that update it
    remove: list = field(default_factory=list)          # commands that remove it ([] = move `trash` to the Trash)
    trash: list[str] = field(default_factory=list)
    needs_password: bool = False    # removing it asks for your password (a system package)
    description: str = ""           # its one-line summary
    group: str = ""                 # for a package: the manager's label (pacman, apt…)

    @property
    def search_text(self) -> str:
        return " ".join([self.name, self.description, self.kind, self.project] + self.commands).casefold()

    @property
    def github(self) -> str:
        return install_info.github_of(self.project).removeprefix("GitHub: ")


def _size(paths) -> int:
    total = 0
    for p in paths:
        try:
            total += uninstall.folder_size(p) if os.path.isdir(p) else os.path.getsize(p)
        except OSError:
            pass
    return total


def _links_into(folder: str, bins: list[str]) -> list[str]:
    out = []
    for b in bins:
        try:
            for n in sorted(os.listdir(b)):
                p = os.path.join(b, n)
                if os.path.islink(p) and (os.path.realpath(p) + os.sep).startswith(os.path.realpath(folder) + os.sep):
                    out.append(p)
        except OSError:
            continue
    return out


def _python(home: str, bins: list[str]) -> list[Tool]:
    out = []
    for kind, base in (("pipx", ".local/share/pipx/venvs"), ("uv", ".local/share/uv/tools")):
        root = os.path.join(home, base)
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for n in names:
            venv = os.path.join(root, n)
            if not os.path.isfile(os.path.join(venv, "pyvenv.cfg")):
                continue
            links = _links_into(venv, bins)
            t = Tool(n, kind, commands=[os.path.basename(x) for x in links], paths=links, folder=venv,
                     size=_size([venv]))
            for name, version, url, _editable in install_info._dists(venv):
                if name.lower().replace("_", "-") == n.lower().replace("_", "-"):
                    t.version, t.project = version, install_info._https(url) if url.startswith(("http", "git")) else ""
                    t.description = _summary(venv, name)
            t.update = [["pipx", "upgrade", n]] if kind == "pipx" else [["uv", "tool", "upgrade", n]]
            t.remove = [["pipx", "uninstall", n]] if kind == "pipx" else [["uv", "tool", "uninstall", n]]
            out.append(t)
    return out


def _cargo(home: str) -> list[Tool]:
    data = install_info._json(os.path.join(home, ".cargo", ".crates2.json"))
    out = []
    for key, info in ((data or {}).get("installs") or {}).items():
        m = re.match(r"^(\S+) (\S+) \((.+)\)$", key)
        if not m:
            continue
        name, version, source = m.groups()
        bins = [os.path.join(home, ".cargo", "bin", b) for b in (info or {}).get("bins", [])]
        t = Tool(name, "cargo", version, commands=[os.path.basename(b) for b in bins],
                 paths=[b for b in bins if os.path.exists(b)],
                 description="Built from its code" if source.startswith("git+") else "From crates.io")
        t.size = _size(t.paths)
        if source.startswith("git+"):
            t.project = install_info._https(re.sub(r"[?#].*$", "", source[4:]))
            t.update = [["cargo", "install", "--git", t.project, name]]
        else:
            t.update = [["cargo", "install", name]]
        t.remove = [["cargo", "uninstall", name]]
        out.append(t)
    return out


def go_module(path: str) -> tuple[str, str]:
    """(module, version) a Go program was built from, read from the build
    information Go puts in every program, or ("", "")."""
    try:
        with open(path, "rb") as f:
            data = f.read(64 * 1024 * 1024)
    except OSError:
        return "", ""
    m = re.search(rb"(?:^|\n)mod\t([^\t\n]+)\t([^\t\n]+)", data)
    if m:
        return m.group(1).decode("utf-8", "replace"), m.group(2).decode("utf-8", "replace")
    m = re.search(rb"\npath\t([^\t\n]+)\n", data)
    return (m.group(1).decode("utf-8", "replace"), "") if m else ("", "")


def _go(home: str, env) -> list[Tool]:
    gobin = env.get("GOBIN") or os.path.join(env.get("GOPATH") or os.path.join(home, "go"), "bin")
    out = []
    try:
        names = sorted(os.listdir(gobin))
    except OSError:
        return out
    for n in names:
        p = os.path.join(gobin, n)
        if not os.path.isfile(p):
            continue
        module, version = go_module(p)
        t = Tool(n, "go", version, commands=[n], paths=[p], size=_size([p]),
                 description=f"Built from {module}" if module else "A Go program")
        if module:
            if module.startswith("github.com/"):
                t.project = "https://" + "/".join(module.split("/")[:3])
            t.update = [["go", "install", module + "@latest"]]
        t.trash = [p]
        out.append(t)
    return out


def _npm(home: str) -> list[Tool]:
    prefixes = [os.path.join(home, ".npm-global"), os.path.join(home, ".local")]
    try:
        with open(os.path.join(home, ".npmrc"), encoding="utf-8") as f:
            m = re.search(r"^\s*prefix\s*=\s*(\S+)", f.read(), flags=re.MULTILINE)
        if m:
            prefixes.insert(0, os.path.expanduser(m.group(1)))
    except OSError:
        pass
    out, seen = [], set()
    for prefix in prefixes:
        root = os.path.join(prefix, "lib", "node_modules")
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for n in names:
            dirs = [os.path.join(root, n, x) for x in os.listdir(os.path.join(root, n))] if n.startswith("@") \
                else [os.path.join(root, n)]
            for d in dirs:
                pkg = install_info._json(os.path.join(d, "package.json"))
                if not isinstance(pkg, dict) or pkg.get("name") in seen or pkg.get("name") == "npm":
                    continue
                seen.add(pkg.get("name"))
                bins = pkg.get("bin") or {}
                bins = list(bins) if isinstance(bins, dict) else [pkg.get("name", "").split("/")[-1]]
                repo = pkg.get("repository") or ""
                repo = repo.get("url", "") if isinstance(repo, dict) else repo
                t = Tool(pkg.get("name", n), "npm", pkg.get("version", ""), commands=bins, folder=d,
                         description=str(pkg.get("description") or ""),
                         paths=[os.path.join(prefix, "bin", b) for b in bins], size=_size([d]),
                         project=install_info._https(repo) if repo else "")
                t.update = [["npm", "install", "-g", t.name + "@latest"]]
                t.remove = [["npm", "uninstall", "-g", t.name]]
                out.append(t)
    return out


def _loose(home: str, bins: list[str], taken: set[str]) -> list[Tool]:
    out = []
    for b in bins:
        try:
            names = sorted(os.listdir(b))
        except OSError:
            continue
        for n in names:
            p = os.path.join(b, n)
            if p in taken or n.startswith(".") or n in (APP_ID, "app-entries") or not os.path.isfile(p):
                continue
            real = os.path.realpath(p)
            if real in taken:
                continue
            if any((real + os.sep).startswith(os.path.realpath(t) + os.sep) for t in taken if os.path.isdir(t)):
                continue
            t = Tool(n, "file", commands=[n], paths=[p], size=_size([real]))
            what, comment, _preview = describe_file(real)
            t.description = comment or what
            t.project = install_info.download_origin(real)
            _checkout, remote = install_info.git_remote(real, home)
            if remote:
                t.project = remote
                t.update = [["git", "-C", _checkout, "pull"]]
            t.trash = [p]
            out.append(t)
    return out


def _packages(managers, apps) -> list[Tool]:
    """Packages you installed yourself that add a command (a program in
    /usr/bin and the like) and have no menu entry: terminal programs, which
    the app list doesn't show. Ones the system, your desktop or App Entries
    needs are left out, as Uninstall would refuse them anyway."""
    out = []
    with_entry = {a.base_path for a in apps if a.base_path} | {a.source_path for a in apps if a.source_path}
    for m in managers:
        try:
            mine = m.user_installed()
        except (OSError, ValueError, KeyError):
            mine = []       # one manager failing shouldn't hide the others
        keep = set(m.protected())
        mine = [p for p in dict.fromkeys(mine) if p and p not in keep and not pkgmanagers.needed_by_system(p)]
        files = m.files_many(mine)
        # Cheap first: only packages that add a command and have no menu entry.
        found = {}
        for pkg in mine:
            own = files.get(pkg, [])
            if any(f.endswith(".desktop") and "/applications/" in f for f in own) or any(f in with_entry for f in own):
                continue        # it has a menu entry: it's in the app list
            bins = sorted({f for f in own if os.path.dirname(f) in BIN_DIRS}, key=os.path.basename)
            if bins:            # else a library, data or a service, not something you run
                found[pkg] = bins
        found = {p: b for p, b in found.items() if not m.base_system(p) and not m.blocked(p)}
        infos = m.info_many(list(found))
        defaults = [o.key for o in m.options if o.default]
        for pkg, bins in found.items():
            info = infos.get(pkg) or pkgmanagers.Info(pkg)
            t = Tool(pkg, m.name, info.version, commands=[os.path.basename(b) for b in bins], paths=bins,
                     size=info.size, needs_password=m.needs_root, description=info.description, group=m.label)
            t.remove = m.commands([pkg], defaults)
            out.append(t)
    return out


def _nix(home: str) -> list[Tool]:
    """Programs in your own Nix profile, grouped by the package they come from."""
    bin_dir = os.path.join(home, ".nix-profile", "bin")
    try:
        names = sorted(os.listdir(bin_dir))
    except OSError:
        return []
    by_pkg: dict[str, list[str]] = {}
    for n in names:
        store = pkgmanagers._store_name(os.path.realpath(os.path.join(bin_dir, n)))
        if store:
            pkg = re.sub(r"-\d[\w.+-]*$", "", store) or store
            by_pkg.setdefault(pkg, []).append(n)
    out = []
    for pkg, bins in sorted(by_pkg.items()):
        version = re.search(r"-(\d[\w.+-]*)$", pkgmanagers._store_name(os.path.realpath(
            os.path.join(bin_dir, bins[0])))) if bins else None
        t = Tool(pkg, "nix", version.group(1) if version else "", commands=bins)
        t.remove = [["nix", "profile", "remove", pkg]] if os.path.isfile(
            os.path.join(home, ".nix-profile", "manifest.json")) else [["nix-env", "--uninstall", pkg]]
        out.append(t)
    return out


def scan(env=None, apps=(), system: bool = False, managers=None) -> list[Tool]:
    """`apps` are the apps with menu entries: the programs they start aren't
    listed here, as they already have a page. With `system`, terminal
    programs installed with the system's package manager are listed too."""
    env = os.environ if env is None else env
    home = env.get("HOME") or os.path.expanduser("~")
    bins = [os.path.join(home, ".local", "bin"), os.path.join(home, "bin")]
    tools = _python(home, bins) + _cargo(home) + _go(home, env) + _npm(home)
    launched = set()
    for a in apps:
        prog = install_info._program(a)
        if prog:
            launched.add(prog)
            launched.add(os.path.realpath(prog))
    tools = [t for t in tools if not any(p in launched or os.path.realpath(p) in launched for p in t.paths)]
    taken = {p for t in tools for p in t.paths} | {t.folder for t in tools if t.folder} | launched
    tools += _loose(home, bins, taken)
    if system:
        if managers is None:
            managers = [m for m in pkgmanagers.detect() if m.name != "nix"]
        tools += _packages(managers, apps) + _nix(home)
    return tools


def by_kind(tools: list[Tool]) -> list[tuple[str, list[Tool]]]:
    order = list(KINDS)
    groups: dict[str, list[Tool]] = {}
    for t in tools:
        groups.setdefault(t.kind, []).append(t)
    return [(k, sorted(groups[k], key=lambda t: t.name.lower())) for k in order if k in groups]


def find(tools: list[Tool], name: str) -> Optional[Tool]:
    return next((t for t in tools if t.name == name), None)


def _summary(venv: str, dist: str) -> str:
    import glob
    for meta in glob.glob(os.path.join(venv, "lib", "python*", "site-packages", "*.dist-info", "METADATA")):
        try:
            with open(meta, encoding="utf-8", errors="replace") as f:
                head = f.read(8192)
        except OSError:
            continue
        name = re.search(r"^Name:\s*(.+)$", head, flags=re.MULTILINE)
        if name and name.group(1).strip().lower().replace("_", "-") == dist.lower().replace("_", "-"):
            m = re.search(r"^Summary:\s*(.+)$", head, flags=re.MULTILINE)
            return m.group(1).strip() if m else ""
    return ""


SCRIPTS = {"sh": "A shell script", "bash": "A Bash script", "zsh": "A Zsh script", "fish": "A fish script",
           "python": "A Python script", "perl": "A Perl script", "ruby": "A Ruby script",
           "node": "A JavaScript (Node) script", "lua": "A Lua script"}
CODE_START = ("set -", "import ", "from ", "use ", "require")


def describe_file(path: str) -> tuple[str, str, list[str]]:
    """(what kind of file, its first comment line, its first lines if it's a
    script). Only reads it; nothing runs."""
    try:
        with open(path, "rb") as f:
            head = f.read(65536)
    except OSError:
        return "A file", "", []
    if head.startswith(b"\x7fELF"):
        return "A program (compiled, not a script)", "", []
    if not head.startswith(b"#!"):
        return "A file", "", []
    lines = head.decode("utf-8", "replace").splitlines()
    words = lines[0][2:].split()
    interp = os.path.basename(words[0]) if words else ""
    if interp == "env" and len(words) > 1:
        interp = os.path.basename(words[1])
    base = re.sub(r"[\d.]+$", "", interp)
    what = SCRIPTS.get(base) or f"A script run by {interp}"
    comment = ""
    for line in lines[1:40]:
        st = line.strip()
        if not st:
            continue
        if st.startswith(("#", "//", "--")):
            if st.startswith(("#!", "# -*-", "# vim:")):
                continue
            comment = st.lstrip("#/- ").strip()
            if comment:
                break
        elif st.startswith(CODE_START):
            continue
        else:
            break
    return what, comment, lines[:40]


NEEDS_ROOT = (r"must be (run as )?root|as root|superuser|permission denied|operation not permitted|"
              r"requires root|need(s)? to be root|run with sudo")


def has_manual(cmd: str, run=None) -> bool:
    """Whether `man` has a page for it (finding it runs nothing of the command's)."""
    import shutil
    import subprocess
    if not shutil.which("man"):
        return False
    try:
        r = (run or subprocess.run)(["man", "-w", cmd], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    # It names the page's file. (Minimised systems' stand-in man says yes to everything.)
    first = (r.stdout or "").strip().splitlines()[0] if r.returncode == 0 and (r.stdout or "").strip() else ""
    return bool(first) and os.path.isfile(first)


def help_script(cmd: str) -> str:
    """A shell script that shows a command's manual, or, if it has none,
    offers to run its --help, and only once you press Enter: a program that
    doesn't understand --help (a script of your own, say) would simply run.
    If it then says it needs administrator rights, that's explained, and
    the sudo command shown for you to run yourself; nothing runs as root."""
    import shlex
    c = shlex.quote(cmd)
    return (
        f'page=$(man -w {c} 2>/dev/null | head -n 1); if [ -n "$page" ] && [ -f "$page" ]; then exec man {c}; fi\n'
        f'printf "%s has no manual page.\\n\\nMost programs answer \\"%s --help\\" with a short summary, but a few '
        f'(scripts of your own, say) don\'t understand it and just run.\\n\\nPress Enter to run %s --help, or close '
        f'this window. " {c} {c} {c}\n'
        'read -r _ || exit 0\n'
        f'out=$({c} --help 2>&1 </dev/null)\n'
        f'if printf "%s" "$out" | grep -qiE {shlex.quote(NEEDS_ROOT)}; then\n'
        f'  printf "\\n%s\\n\\n%s needs administrator rights even to show its help. If you trust it, run:\\n'
        f'  sudo %s --help\\n" "$out" {c} {c}\n'
        'else\n'
        '  printf "%s\\n" "$out" | ${PAGER:-less}\n'
        'fi\n'
    )
