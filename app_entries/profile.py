"""Export your changes to one file, and import them on another machine or
after a reinstall. Pure Python, no GTK.

The file is JSON. It holds what App Entries did, not copies of system
entries: a hidden app is stored by its ID, so importing hides whatever
version is installed there. Edited entries and your own launchers are
stored in full, with the icons they use. Paths inside your home folder are
stored relative to it, so the file works for another user name too.

Importing only plans: it returns the changes and what was skipped, and the
caller shows them before anything is written. Every change can be undone.
"""
import base64
import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import APP_NAME, VERSION
from . import desktop_entries as de
from .overrides import (Change, NeedsConfirmation, OverrideError, is_pristine, override_path, plan_set_hidden,
                        read_bytes, read_text)

FORMAT = 1
DATA = "@DATA@"  # stands for ~/.local/share (XDG_DATA_HOME) in the file
_ICON_KEYS = ("Icon", "X-AppEntries-Icon-Path")


class ProfileError(Exception):
    pass


@dataclass
class Item:
    id: str
    name: str
    kind: str               # hidden, shown, entry (an edited system app) or launcher (your own)
    text: str = ""          # the file, for entry and launcher

    def describe(self) -> str:
        return {"hidden": "hide", "shown": "show", "entry": "edited entry",
                "launcher": "launcher"}.get(self.kind, self.kind)


@dataclass
class Plan:
    changes: List[Change] = field(default_factory=list)
    adds: List[str] = field(default_factory=list)       # one line per change, for showing before importing
    skipped: List[Tuple[str, str]] = field(default_factory=list)   # (name, why)
    unchanged: int = 0


# ---------------------------------------------------------------------------
# Export


def _portable(text: str, data_dir: str) -> str:
    """Icon paths inside the data folder written with the placeholder."""
    out = []
    for line in text.splitlines():
        key = line.split("=", 1)[0].strip()
        if (key in _ICON_KEYS or key.startswith("Icon[")) and data_dir in line:
            line = line.replace(data_dir, DATA)
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def _local(text: str, data_dir: str) -> str:
    return text.replace(DATA, data_dir)


def _icon_files(text: str, data_dir: str) -> List[str]:
    """Absolute icon files in the data folder that the entry uses."""
    found = []
    for k, v in de.DesktopFile(text).items():
        if k in _ICON_KEYS or k.startswith("Icon["):
            path = de.unescape(v)
            if os.path.isabs(path) and path.startswith(data_dir + os.sep) and os.path.isfile(path):
                found.append(path)
    return found


def collect(apps: List[de.App], include_others: bool = False, env=None) -> Tuple[List[Item], int]:
    """What to export, and how many files in your folder were left out
    because App Entries didn't make them (see include_others)."""
    items, others = [], 0
    for app in apps:
        if not app.override_path:
            continue
        text = read_text(app.override_path)
        if text is None:
            continue
        df = de.DesktopFile(text)
        d = df.group_dict()
        ours = de.is_true(d.get(de.MANAGED_KEY)) or app.created
        if app.created:
            items.append(Item(app.id, app.name, "launcher", text))
        elif app.system and (is_pristine(df) or de.is_bare_override(d)):
            if not ours and not include_others:
                others += 1
                continue
            items.append(Item(app.id, app.name, "hidden" if app.hidden else "shown"))
        elif app.system:
            if not ours and not include_others:
                others += 1
                continue
            items.append(Item(app.id, app.name, "entry", text))
        else:  # an app that only exists in your folder, not made here
            if not include_others:
                others += 1
                continue
            items.append(Item(app.id, app.name, "launcher", text))
    return items, others


def export_text(apps: List[de.App], include_others: bool = False, env=None) -> Tuple[str, List[Item], int]:
    """The export file's text, the items in it, and how many files were left out."""
    data_dir = de.user_data_dir(env)
    items, others = collect(apps, include_others, env)
    files: Dict[str, str] = {}
    out = []
    for it in items:
        entry = {"id": it.id, "name": it.name, "kind": it.kind}
        if it.text:
            for path in _icon_files(it.text, data_dir):
                data = read_bytes(path)
                if data is not None:
                    files[DATA + path[len(data_dir):]] = base64.b64encode(data).decode("ascii")
            entry["text"] = _portable(it.text, data_dir)
        out.append(entry)
    doc = {"app": APP_NAME, "version": VERSION, "format": FORMAT,
           "exported": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "items": out, "files": files}
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n", items, others


def export(path: str, apps: List[de.App], include_others: bool = False, env=None) -> Tuple[List[Item], int]:
    text, items, others = export_text(apps, include_others, env)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except OSError as e:
        raise ProfileError("%s: %s" % (path, e.strerror or e)) from e
    return items, others


# ---------------------------------------------------------------------------
# Import


def read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except OSError as e:
        raise ProfileError("%s: %s" % (path, e.strerror or e)) from e
    except ValueError as e:
        raise ProfileError("This isn't an App Entries export: %s" % e) from e
    return parse(doc)


def parse(doc) -> dict:
    if not isinstance(doc, dict) or not isinstance(doc.get("items"), list):
        raise ProfileError("This isn't an App Entries export.")
    if int(doc.get("format", 0)) > FORMAT:
        raise ProfileError("This file was made by a newer App Entries. Update it to import the file.")
    for it in doc["items"]:
        if not isinstance(it, dict) or not isinstance(it.get("id"), str) or it.get("kind") not in (
                "hidden", "shown", "entry", "launcher"):
            raise ProfileError("The file is damaged: an item can't be read.")
        if not it["id"].endswith(".desktop") or "/" in it["id"] or it["id"].startswith("."):
            raise ProfileError("The file is damaged: %r isn't an app ID." % it["id"])
    return doc


def _safe_file(rel: str, data_dir: str) -> Optional[str]:
    """Where an icon from the file goes, or None if it would land outside the
    icon folders."""
    if not rel.startswith(DATA + "/"):
        return None
    path = os.path.normpath(os.path.join(data_dir, rel[len(DATA) + 1:]))
    allowed = (os.path.join(data_dir, "icons") + os.sep, os.path.join(data_dir, "app-entries") + os.sep)
    return path if path.startswith(allowed) else None


def plan_import(doc: dict, apps: List[de.App], env=None) -> Plan:
    """The changes that bring this machine in line with the file. Nothing is
    written here."""
    plan = Plan()
    data_dir = de.user_data_dir(env)
    by_id = {a.id: a for a in apps}
    files = doc.get("files") or {}
    wanted_files = set()
    for raw in doc["items"]:
        it = Item(raw["id"], raw.get("name") or raw["id"], raw["kind"], raw.get("text") or "")
        app = by_id.get(it.id)
        if it.kind in ("hidden", "shown"):
            if app is None or not app.system:
                plan.skipped.append((it.name, "not installed here"))
                continue
            try:
                change = plan_set_hidden(app, it.kind == "hidden", env)
            except NeedsConfirmation:
                plan.skipped.append((it.name, "another program's file hides it; show it from the app to remove that"))
                continue
            except OverrideError as e:
                plan.skipped.append((it.name, e.reason))
                continue
            if change is None:
                plan.unchanged += 1
            else:
                plan.changes.append(change)
                plan.adds.append("%s %s" % ("Hide" if it.kind == "hidden" else "Show", it.name))
            continue

        text = _local(it.text, data_dir)
        if not de.DesktopFile(text).has_group():
            plan.skipped.append((it.name, "the entry in the file is damaged"))
            continue
        if it.kind == "entry" and (app is None or not app.system):
            plan.skipped.append((it.name, "not installed here, so there's nothing to edit"))
            continue
        path = override_path(app, env) if app else os.path.join(de.user_apps_dir(env), it.id)
        before = read_text(path)
        if before == text:
            plan.unchanged += 1
        else:
            plan.changes.append(Change(it.id, it.name, path, before, text, _hides(text)))
            verb = ("Replace your launcher" if it.kind == "launcher" else "Replace your edit of") if before \
                else ("Add launcher" if it.kind == "launcher" else "Edit")
            plan.adds.append("%s %s" % (verb, it.name))
        for k, v in de.DesktopFile(it.text).items():
            if (k in _ICON_KEYS or k.startswith("Icon[")) and de.unescape(v).startswith(DATA + "/"):
                wanted_files.add(de.unescape(v))

    for rel in sorted(wanted_files):
        data = files.get(rel)
        path = _safe_file(rel, data_dir)
        if data is None or path is None:
            continue
        try:
            content = base64.b64decode(data, validate=True)
        except ValueError:
            continue
        before = read_bytes(path)
        if before != content:
            plan.changes.insert(0, Change("", os.path.basename(path), path, before, content, False))
    return plan


def _hides(text: str) -> bool:
    d = de.DesktopFile(text).group_dict()
    return de.is_true(d.get("NoDisplay")) or de.is_true(d.get("Hidden"))
