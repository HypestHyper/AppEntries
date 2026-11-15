"""Command-line tools in your home folder that have no menu entry: installed
with cargo, go, pipx, uv or npm, or put in ~/.local/bin by hand. Pure
Python, no GTK. Only reads files; the commands that update or remove a tool
are run by the user, in a terminal."""
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from . import APP_ID, install_info, uninstall

KINDS = {
    "cargo": "Rust · cargo", "go": "Go · go install", "pipx": "Python · pipx", "uv": "Python · uv",
    "npm": "Node · npm", "file": "A file in ~/.local/bin",
}


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
                 paths=[b for b in bins if os.path.exists(b)])
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
        t = Tool(n, "go", version, commands=[n], paths=[p], size=_size([p]))
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
            t.project = install_info.download_origin(real)
            _checkout, remote = install_info.git_remote(real, home)
            if remote:
                t.project = remote
                t.update = [["git", "-C", _checkout, "pull"]]
            t.trash = [p]
            out.append(t)
    return out


def scan(env=None, apps=()) -> list[Tool]:
    """`apps` are the apps with menu entries: the programs they start aren't
    listed here, as they already have a page."""
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
    return tools


def by_kind(tools: list[Tool]) -> list[tuple[str, list[Tool]]]:
    order = list(KINDS)
    groups: dict[str, list[Tool]] = {}
    for t in tools:
        groups.setdefault(t.kind, []).append(t)
    return [(k, sorted(groups[k], key=lambda t: t.name.lower())) for k in order if k in groups]


def find(tools: list[Tool], name: str) -> Optional[Tool]:
    return next((t for t in tools if t.name == name), None)
