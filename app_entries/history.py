"""A log of every change App Entries makes, kept on disk so each can be
undone later, even after a restart. Pure Python, no GTK.

An entry holds the changed files' text before and after (overrides.Change)
and anything moved to the Trash. Undoing applies them in reverse, which
only works while the files still look as App Entries left them: if a
later change touched the same file, that one has to be undone first.
"""
import base64
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import List, Optional

from . import trash
from .overrides import Change, ConflictError, OverrideError, undo_all

KEEP = 200                      # entries kept
MAX_ENTRY = 8 * 1024 * 1024     # bigger changes are listed but can't be undone from here


@dataclass
class Entry:
    id: int
    when: float
    message: str
    changes: List[Change] = field(default_factory=list)
    trashed: List[trash.Trashed] = field(default_factory=list)
    undone: float = 0.0          # when it was undone, 0 if it wasn't
    too_big: bool = False        # its files weren't kept, so it can't be undone
    # Commands that install again what was uninstalled (run in a terminal),
    # and whether they open Steam instead.
    reinstall: List[List[str]] = field(default_factory=list)
    reinstall_steam: bool = False

    @property
    def can_undo(self) -> bool:
        return not self.undone and not self.too_big and bool(self.changes or self.trashed)

    @property
    def paths(self) -> List[str]:
        return [c.path for c in self.changes] + [t.original for t in self.trashed]


def path(env=None) -> str:
    env = os.environ if env is None else env
    home = env.get("HOME") or os.path.expanduser("~")
    state = env.get("XDG_STATE_HOME") or ""
    base = state if os.path.isabs(state) else os.path.join(home, ".local", "state")
    return os.path.join(base, "app-entries", "history.json")


def _enc(v):
    if v is None:
        return None
    if isinstance(v, bytes):
        return {"b64": base64.b64encode(v).decode("ascii")}
    return v


def _dec(v):
    if isinstance(v, dict):
        return base64.b64decode(v.get("b64", ""))
    return v


def _to_json(e: Entry) -> dict:
    return {
        "id": e.id, "when": e.when, "message": e.message, "undone": e.undone, "too_big": e.too_big,
        "changes": [{"app_id": c.app_id, "app_name": c.app_name, "path": c.path, "before": _enc(c.before),
                     "after": _enc(c.after), "hidden": c.hidden} for c in e.changes],
        "trashed": [{"original": t.original, "file": t.file, "info": t.info} for t in e.trashed],
        "reinstall": e.reinstall, "reinstall_steam": e.reinstall_steam,
    }


def _from_json(d: dict) -> Entry:
    return Entry(
        id=int(d["id"]), when=float(d["when"]), message=str(d["message"]),
        undone=float(d.get("undone") or 0), too_big=bool(d.get("too_big")),
        changes=[Change(c["app_id"], c["app_name"], c["path"], _dec(c["before"]), _dec(c["after"]),
                        bool(c["hidden"])) for c in d.get("changes", [])],
        trashed=[trash.Trashed(t["original"], t["file"], t["info"]) for t in d.get("trashed", [])],
        reinstall=[[str(w) for w in c] for c in d.get("reinstall") or [] if isinstance(c, list)],
        reinstall_steam=bool(d.get("reinstall_steam")),
    )


def load(env=None) -> List[Entry]:
    """Newest first."""
    try:
        with open(path(env), encoding="utf-8") as f:
            data = json.load(f)
        entries = [_from_json(d) for d in data.get("entries", [])]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    return sorted(entries, key=lambda e: e.id, reverse=True)


def _save(entries: List[Entry], env=None) -> None:
    p = path(env)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), prefix=".history-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "entries": [_to_json(e) for e in entries[:KEEP]]}, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, p)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record(message: str, changes: List[Change], trashed: Optional[List[trash.Trashed]] = None,
           env=None, reinstall: Optional[List[List[str]]] = None, reinstall_steam: bool = False) -> Optional[Entry]:
    """Add an entry. Returns it, or None if there was nothing to record or
    the log couldn't be written (the change itself is already made)."""
    trashed = list(trashed or [])
    if not changes and not trashed and not reinstall:
        return None
    entries = load(env)
    e = Entry(id=(entries[0].id + 1) if entries else 1, when=time.time(), message=message,
              changes=list(changes), trashed=trashed, reinstall=list(reinstall or []),
              reinstall_steam=reinstall_steam)
    size = sum(len(c.before or "") + len(c.after or "") for c in e.changes)
    if size > MAX_ENTRY:
        e.too_big = True
        e.changes = [Change(c.app_id, c.app_name, c.path, None, None, c.hidden) for c in e.changes]
    try:
        _save([e] + entries, env)
    except OSError:
        return None
    return e


def add_trashed(entry_id: int, trashed: List[trash.Trashed], env=None) -> None:
    """Things moved to the Trash after the files were changed."""
    if not trashed:
        return
    entries = load(env)
    for e in entries:
        if e.id == entry_id:
            e.trashed += trashed
            try:
                _save(entries, env)
            except OSError:
                pass
            return


class UndoError(Exception):
    def __init__(self, message: str, path: str = ""):
        super().__init__(message)
        self.path = path


def undo(entry_id: int, env=None) -> Entry:
    """Put back what an entry changed. Raises UndoError and changes nothing
    when that isn't possible."""
    entries = load(env)
    e = next((x for x in entries if x.id == entry_id), None)
    if e is None:
        raise UndoError("That change isn't in the history any more.")
    if e.undone:
        raise UndoError("That change was already undone.")
    if e.too_big:
        raise UndoError("That change was too large to keep a copy of, so it can't be undone here.")
    if not e.changes and not e.trashed:
        raise UndoError("App Entries didn't change any files for this, so there's nothing to undo. Use "
                        "Reinstall to get the app back.")
    for t in e.trashed:
        if not os.path.lexists(t.file):
            raise UndoError("%s isn't in the Trash any more, so this can't be undone." % t.original, t.original)
        if os.path.lexists(t.original):
            raise UndoError("Something is already at %s, so this can't be undone." % t.original, t.original)
    try:
        undo_all(e.changes)
    except ConflictError as err:
        raise UndoError("A file was changed after this, by a later change or by hand. Undo the later "
                        "changes first.", err.path) from err
    except OverrideError as err:
        raise UndoError("The file couldn't be changed: %s." % err.reason, err.path) from err
    for t in e.trashed:
        trash.restore(t)
    e.undone = time.time()
    try:
        _save(entries, env)
    except OSError:
        pass
    return e


def clear(env=None) -> None:
    try:
        os.unlink(path(env))
    except FileNotFoundError:
        pass
