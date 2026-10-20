"""Ask the desktop to reload its app list. Most launchers notice changes in
~/.local/share/applications on their own; this is for the ones that don't.
Only runs when you ask. Pure Python, no GTK."""
import os
import shutil
import subprocess
from typing import List

from . import desktop_entries as de


def steps(env=None) -> List[str]:
    """What refresh() would do here, in plain words."""
    env = env if env is not None else os.environ
    out = ["Mark your applications folder as changed, so launchers that watch it reload"]
    if _has_mime_cache(env):
        out.append("Update the list of which apps open which files in that folder (update-desktop-database)")
    if _kde(env) and _kbuild():
        out.append("Rebuild the KDE menu cache (%s)" % _kbuild())
    return out


def _kde(env) -> bool:
    return "KDE" in [d.upper() for d in de.current_desktops(dict(env))]


def _has_mime_cache(env) -> bool:
    """Only update a cache that's already there: making a new one would leave
    a file that goes stale when nothing else keeps it up to date."""
    return bool(shutil.which("update-desktop-database")) and os.path.isfile(
        os.path.join(de.user_apps_dir(dict(env)), "mimeinfo.cache"))


def _kbuild() -> str:
    return shutil.which("kbuildsycoca6") or shutil.which("kbuildsycoca5") or ""


def _run(cmd: List[str]) -> str:
    try:
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60, text=True)
    except (OSError, subprocess.TimeoutExpired) as e:
        return "%s failed: %s" % (os.path.basename(cmd[0]), e)
    if r.returncode != 0:
        msg = (r.stderr or "").strip().splitlines()
        return "%s failed: %s" % (os.path.basename(cmd[0]), msg[-1] if msg else "exit %d" % r.returncode)
    return "Ran %s" % os.path.basename(cmd[0])


def refresh(env=None) -> List[str]:
    """Do it. Returns one line per step, saying what happened."""
    env = env if env is not None else os.environ
    folder = de.user_apps_dir(dict(env))
    done = []
    try:
        os.makedirs(folder, exist_ok=True)
        os.utime(folder)
        done.append("Marked %s as changed" % folder)
    except OSError as e:
        done.append("Couldn't touch %s: %s" % (folder, e.strerror or e))
    if _has_mime_cache(env):
        done.append(_run(["update-desktop-database", folder]))
    if _kde(env) and _kbuild():
        done.append(_run([_kbuild()]))
    return done
