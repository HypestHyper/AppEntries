"""Move files and folders to the Trash, the way file managers do
(freedesktop.org Trash spec), so they can be restored from there.
Pure Python, no GTK."""
import os
import shutil
import time
import urllib.parse
from dataclasses import dataclass

from . import desktop_entries as de


class TrashError(Exception):
    pass


@dataclass
class Trashed:
    original: str
    file: str   # where it is in the Trash
    info: str   # its .trashinfo


def folder(env=None) -> str:
    return os.path.join(de.user_data_dir(env), "Trash")


def move(path: str, env=None) -> Trashed:
    path = os.path.abspath(path)
    if not os.path.lexists(path):
        raise TrashError(f"{path} is already gone")
    files, info = os.path.join(folder(env), "files"), os.path.join(folder(env), "info")
    try:
        os.makedirs(files, exist_ok=True)
        os.makedirs(info, exist_ok=True)
    except OSError as e:
        raise TrashError("Couldn't open the Trash: %s" % (e.strerror or e)) from e
    base = os.path.basename(path.rstrip("/")) or "file"
    name, n = base, 2
    while True:
        info_path = os.path.join(info, name + ".trashinfo")
        try:  # reserve the name, as the spec asks
            fd = os.open(info_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            stem, ext = os.path.splitext(base)
            name, n = f"{stem}.{n}{ext}", n + 1
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        when = time.strftime("%Y-%m-%dT%H:%M:%S")
        f.write(f"[Trash Info]\nPath={urllib.parse.quote(path)}\nDeletionDate={when}\n")
    target = os.path.join(files, name)
    try:
        shutil.move(path, target)
    except OSError as e:
        os.unlink(info_path)
        raise TrashError(f"Couldn't move {path} to the Trash: {e.strerror or e}") from e
    return Trashed(path, target, info_path)


def restore(t: Trashed) -> None:
    if os.path.lexists(t.original):
        raise TrashError(f"Something is already at {t.original}, so it was left in the Trash")
    try:
        os.makedirs(os.path.dirname(t.original), exist_ok=True)
        shutil.move(t.file, t.original)
    except OSError as e:
        raise TrashError(f"Couldn't restore {t.original}: {e.strerror or e}") from e
    try:
        os.unlink(t.info)
    except OSError:
        pass
