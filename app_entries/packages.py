"""Which package installed a file, and the command that removes it.

Only looks things up; the command is shown to the user to copy, never run.
"""
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


@dataclass
class Owner:
    package: str   # package name
    manager: str   # pacman, apt, dnf, zypper, rpm, flatpak or snap
    command: str   # the command that removes it


def _run(argv: List[str]) -> Optional[str]:
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=10,
                             env=dict(os.environ, LC_ALL="C"))
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout if out.returncode == 0 else None


def _rpm_frontend(which) -> str:
    if which("zypper"):
        return "zypper"
    if which("dnf"):
        return "dnf"
    return "rpm"


REMOVE = {
    "pacman": "sudo pacman -Rns {pkg}",
    "apt": "sudo apt remove {pkg}",
    "dnf": "sudo dnf remove {pkg}",
    "zypper": "sudo zypper remove {pkg}",
    "rpm": "sudo rpm -e {pkg}",
    "flatpak": "flatpak uninstall {pkg}",
    "snap": "sudo snap remove {pkg}",
}


def owner_of(path: str, source: str = "system", run: Callable = _run, which: Callable = shutil.which) -> Optional[Owner]:
    """The package that owns `path`, or None if it can't be told."""
    name = os.path.basename(path)
    if source == "flatpak":
        app_id = name[:-len(".desktop")] if name.endswith(".desktop") else name
        return Owner(app_id, "flatpak", REMOVE["flatpak"].format(pkg=app_id))
    if source == "snap":
        snap = name.split("_", 1)[0]
        return Owner(snap, "snap", REMOVE["snap"].format(pkg=snap))

    if which("pacman"):
        out = run(["pacman", "-Qoq", path])
        if out and out.strip():
            pkg = out.split()[0]
            return Owner(pkg, "pacman", REMOVE["pacman"].format(pkg=pkg))
    if which("dpkg-query"):
        out = run(["dpkg-query", "-S", path])
        if out and ": " in out:
            pkg = out.split(": ", 1)[0].split(",")[0].strip().split(":")[0]
            return Owner(pkg, "apt", REMOVE["apt"].format(pkg=pkg))
    if which("rpm"):
        out = run(["rpm", "-qf", "--qf", "%{NAME}\\n", path])
        if out and out.strip() and "not owned" not in out:
            pkg = out.split()[0]
            mgr = _rpm_frontend(which)
            return Owner(pkg, mgr, REMOVE[mgr].format(pkg=pkg))
    return None


def owners(apps, run: Callable = _run, which: Callable = shutil.which) -> Dict[str, Owner]:
    """Owners of the system entries of these apps, by app ID."""
    out = {}
    cache: Dict[str, Optional[Owner]] = {}
    for a in apps:
        path = a.base_path
        if not path or a.source not in ("system", "flatpak", "snap"):
            continue
        if path not in cache:
            cache[path] = owner_of(path, a.source, run, which)
        if cache[path] is not None:
            out[a.id] = cache[path]
    return out


_manager = None


def system_manager(which: Callable = shutil.which) -> str:
    """The package manager this system uses: pacman, apt, dnf, zypper, rpm, or ""."""
    global _manager
    if _manager is None or which is not shutil.which:
        found = ""
        for tool, name in (("pacman", "pacman"), ("dpkg-query", "apt"), ("zypper", "zypper"),
                           ("dnf", "dnf"), ("rpm", "rpm")):
            if which(tool):
                found = name
                break
        if which is not shutil.which:
            return found
        _manager = found
    return _manager
