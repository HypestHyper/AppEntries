"""Hide and unhide applications with user-level .desktop overrides.

Original files outside the user's data dir are never touched. To hide an app,
App Entries puts a full copy of its entry in the user's folder with
NoDisplay=true: launchers then leave it out of their menus, but it keeps
working as the default app for links and files and in "Open With". (The
spec's Hidden=true would make the app count as uninstalled.)

Every change is recorded as a `Change` holding the file's text before and
after, which is also what Undo uses. Pure Python, no GTK.
"""
import hashlib
import os
import tempfile
from dataclasses import dataclass
from typing import List, Optional, Union

from .desktop_entries import (CHECKSUM_KEY, current_desktops, GROUP, HIDDEN_KEY, MANAGED_KEY, App, DesktopFile,
                              is_true, user_apps_dir)

# Keys a file made by App Entries 1.0 may hold and still count as "ours only".
MINIMAL_KEYS = {"Type", "Name", "Hidden", MANAGED_KEY}


class OverrideError(Exception):
    """A file couldn't be read or written. `path` is the file involved."""

    def __init__(self, path: str, reason: str):
        super().__init__("%s: %s" % (path, reason))
        self.path = path
        self.reason = reason


class NeedsConfirmation(Exception):
    """Unhiding would delete a user file this app didn't create (or one the
    user has since edited). Ask, then retry with allow_delete=True."""

    def __init__(self, path: str):
        super().__init__(path)
        self.path = path


class ConflictError(OverrideError):
    """The file changed on disk since this app last wrote it."""


@dataclass
class Change:
    app_id: str
    app_name: str
    path: str
    before: Optional[Union[str, bytes]]  # file text before, None if it didn't exist
    after: Optional[Union[str, bytes]]   # file text after, None if it was deleted (bytes for images)
    hidden: bool           # the app's state after the change

    def reversed(self) -> "Change":
        return Change(self.app_id, self.app_name, self.path, self.after, self.before, not self.hidden)


# ---------------------------------------------------------------------------
# File helpers


def read_text(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise OverrideError(path, e.strerror or str(e)) from e


def read_bytes(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise OverrideError(path, e.strerror or str(e)) from e


def atomic_write(path: str, text: Union[str, bytes]) -> None:
    """Write via a temp file in the same directory, then os.replace()."""
    folder = os.path.dirname(path)
    try:
        os.makedirs(folder, exist_ok=True)
        try:
            mode = os.stat(path).st_mode & 0o777
        except FileNotFoundError:
            mode = 0o644
        fd, tmp = tempfile.mkstemp(dir=folder, prefix=".app-entries-", suffix=".tmp")
    except OSError as e:
        raise OverrideError(path, e.strerror or str(e)) from e
    try:
        with (os.fdopen(fd, "wb") if isinstance(text, bytes) else os.fdopen(fd, "w", encoding="utf-8")) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except OSError as e:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise OverrideError(path, e.strerror or str(e)) from e


def delete(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as e:
        raise OverrideError(path, e.strerror or str(e)) from e


def apply(change: Change) -> None:
    """Make the file match change.after, if it still matches change.before."""
    binary = isinstance(change.after, bytes) or isinstance(change.before, bytes)
    current = read_bytes(change.path) if binary else read_text(change.path)
    if current != change.before:
        raise ConflictError(change.path, "the file changed on disk")
    if change.after is None:
        delete(change.path)
    else:
        atomic_write(change.path, change.after)


def undo(change: Change) -> Change:
    rev = change.reversed()
    apply(rev)
    return rev


# ---------------------------------------------------------------------------
# Copies made by App Entries


def override_path(app: App, env=None) -> str:
    """Where the user-level file for this app lives (or would live)."""
    return app.override_path or os.path.join(user_apps_dir(env), app.id)


def _digest(df: DesktopFile) -> str:
    probe = DesktopFile(df.text())
    probe.remove(CHECKSUM_KEY)
    return hashlib.sha256(probe.text().encode("utf-8")).hexdigest()[:16]


def is_minimal_managed(df: DesktopFile) -> bool:
    """A bare Hidden=true file made by App Entries 1.0."""
    d = df.group_dict()
    return (is_true(d.get(MANAGED_KEY)) and df.groups() == [GROUP]
            and set(d) <= MINIMAL_KEYS)


def is_pristine(df: DesktopFile) -> bool:
    """Made by App Entries and not edited since, so it can be replaced or
    deleted without losing anything."""
    d = df.group_dict()
    if not is_true(d.get(MANAGED_KEY)):
        return False
    return is_minimal_managed(df) or d.get(CHECKSUM_KEY) == _digest(df)


def show_here(df: DesktopFile, env=None) -> None:
    """Let the current desktop list it: add it to OnlyShowIn (if that's set)
    and take it out of NotShowIn."""
    desktops = current_desktops(env)
    if not desktops:
        return
    d = df.group_dict()
    current = {x.casefold() for x in desktops}
    only = [x for x in d.get("OnlyShowIn", "").split(";") if x.strip()]
    if only and not any(x.casefold() in current for x in only):
        df.set("OnlyShowIn", ";".join(only + [desktops[0]]) + ";")
    never = [x for x in d.get("NotShowIn", "").split(";") if x.strip()]
    if any(x.casefold() in current for x in never):
        kept = [x for x in never if x.casefold() not in current]
        if kept:
            df.set("NotShowIn", ";".join(kept) + ";")
        else:
            df.remove("NotShowIn")


def managed_copy(app: App, hidden: bool, env=None) -> str:
    """A full copy of the app's system entry, shown or hidden."""
    source = read_text(app.base_path)
    if source is None:
        raise OverrideError(app.base_path, "the app's original entry is missing")
    df = DesktopFile(source)
    verb = "hide" if hidden else "show"
    df.lines[:0] = [
        "# Copy made by App Entries to %s %s in app launchers." % (verb, app.id),
        "# Change it back in App Entries, or delete this file, to undo.",
    ]
    df.remove("Hidden")
    df.set("NoDisplay", "true" if hidden else "false")
    if not hidden:
        show_here(df, env)
    df.set(MANAGED_KEY, "true")
    df.set(CHECKSUM_KEY, _digest(df))
    return df.text()


# ---------------------------------------------------------------------------
# Planning


def plan_set_hidden(app: App, hidden: bool, env=None, allow_delete: bool = False) -> Optional[Change]:
    """The change that makes launchers show (hidden=False) or hide the app,
    or None if it's already that way."""
    if app.hidden == hidden:
        return None
    path = override_path(app, env)
    before = read_text(path)
    df = DesktopFile(before) if before is not None else None

    # No user file, or one App Entries made and nobody edited: it can be
    # rebuilt from the system entry, or dropped if the system entry already
    # does the right thing.
    if app.base_path and (df is None or is_pristine(df)):
        if hidden == app.base_hidden:
            after = None
        else:
            after = managed_copy(app, hidden, env)
        if after is None and before is None:
            return None
        return Change(app.id, app.name, path, before, after, hidden)

    if df is None:
        return None
    d = df.group_dict()

    if hidden:
        df.set("NoDisplay", "true")
        df.set(HIDDEN_KEY, "true")
        return Change(app.id, app.name, path, before, df.text(), True)

    if not d.get("Exec", "").strip():
        # A bare override someone else made, or one that's been edited. With
        # no Exec of its own it hides the real app by existing, so the only
        # way back is deleting it, and that needs the user's OK.
        if not allow_delete:
            raise NeedsConfirmation(path)
        return Change(app.id, app.name, path, before, None, False)

    # The user's own complete entry: take out only what hides it.
    df.remove("Hidden")
    if is_true(d.get("NoDisplay")):
        df.remove("NoDisplay")
    df.remove(HIDDEN_KEY)
    show_here(df, env)
    return Change(app.id, app.name, path, before, df.text(), False)


def set_hidden(app: App, hidden: bool, env=None, allow_delete: bool = False) -> Optional[Change]:
    """Plan and apply. Returns the change made, or None if nothing to do."""
    change = plan_set_hidden(app, hidden, env, allow_delete)
    if change is not None:
        apply(change)
    return change


def plan_update_legacy(app: App) -> Change:
    """Rewrite a bare Hidden=true file from an earlier version as a NoDisplay
    copy, so the app keeps opening links and files. It stays hidden."""
    before = read_text(app.override_path)
    if before is None or not is_minimal_managed(DesktopFile(before)):
        raise OverrideError(app.override_path, "this isn't a file from the earlier version")
    return Change(app.id, app.name, app.override_path, before, managed_copy(app, True), True)


def plan_delete(app_id: str, name: str, path: str, hidden_after: bool) -> Change:
    """Delete one file in the user's folder (Undo puts it back)."""
    before = read_text(path)
    if before is None:
        raise OverrideError(path, "the file is already gone")
    return Change(app_id, name, path, before, None, hidden_after)


def plan_restore_original(app: App) -> Change:
    """Delete the user's file for an app, so its system entry is used again."""
    if not (app.override_path and app.base_path):
        raise OverrideError(app.override_path or app.id, "there's no original entry to go back to")
    return plan_delete(app.id, app.name, app.override_path, app.base_hidden)


def plan_unhide_all(apps: List[App], env=None):
    """Changes that show every app the user (or App Entries) hid. Apps hidden by
    their own package, and files that would need deleting without asking,
    are left out. Returns (changes, skipped apps)."""
    changes, skipped = [], []
    for app in apps:
        if not app.hidden or not app.has_override:
            continue
        try:
            change = plan_set_hidden(app, False, env)
        except NeedsConfirmation:
            skipped.append(app)
            continue
        if change is not None:
            changes.append(change)
    return changes, skipped


def apply_all(changes: List[Change]) -> List[Change]:
    """Apply in order. If one fails, the ones already made are undone and the
    error is raised, so it's all or nothing."""
    done = []
    try:
        for c in changes:
            apply(c)
            done.append(c)
    except OverrideError:
        for c in reversed(done):
            try:
                undo(c)
            except OverrideError:
                pass
        raise
    return done


def undo_all(changes: List[Change]) -> List[Change]:
    return apply_all([c.reversed() for c in reversed(changes)])
