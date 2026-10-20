"""Edit an app's launcher entry: name, icon, command, where it appears.

Edits go into the user's copy of the entry (made from the system entry if
there isn't one yet), touching only the keys that changed. Pure Python, no GTK.
"""
import os
import re
from dataclasses import dataclass, field, replace
from typing import List, Optional, Tuple

from . import desktop_entries as de
from .desktop_entries import CHECKSUM_KEY, HIDDEN_KEY, MANAGED_KEY, DesktopFile, is_true
from .overrides import Change, OverrideError, override_path, read_text

# Main menu categories from the Desktop Menu Specification, with plain names.
MAIN_CATEGORIES = [
    ("AudioVideo", "Sound and video"),
    ("Development", "Programming"),
    ("Education", "Education"),
    ("Game", "Games"),
    ("Graphics", "Graphics"),
    ("Network", "Internet"),
    ("Office", "Office"),
    ("Science", "Science"),
    ("Settings", "Settings"),
    ("System", "System"),
    ("Utility", "Accessories"),
]

# Desktops as they appear in XDG_CURRENT_DESKTOP and OnlyShowIn/NotShowIn.
DESKTOPS = [
    ("GNOME", "GNOME"), ("KDE", "KDE Plasma"), ("XFCE", "Xfce"), ("X-Cinnamon", "Cinnamon"),
    ("MATE", "MATE"), ("LXQt", "LXQt"), ("Budgie", "Budgie"), ("Pantheon", "Pantheon"),
    ("COSMIC", "COSMIC"), ("Hyprland", "Hyprland"), ("sway", "Sway"), ("niri", "niri"),
    ("Unity", "Unity"),
]

_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_ENV_PREFIX = re.compile(r'^env\s+((?:(?:[A-Za-z_][A-Za-z0-9_]*=[^\s"]*|"[A-Za-z_][A-Za-z0-9_]*=[^"]*")\s+)+)(.*)$',
                         re.S)


@dataclass
class Action:
    id: str
    name: str
    enabled: bool


@dataclass
class Fields:
    name: str = ""
    generic_name: str = ""
    comment: str = ""
    keywords: List[str] = field(default_factory=list)
    icon: str = ""
    command: str = ""
    env: List[str] = field(default_factory=list)   # NAME=value
    terminal: bool = False
    prefers_gpu: bool = False
    wm_class: str = ""
    categories: List[str] = field(default_factory=list)  # main categories only
    show_in: str = "all"                                 # all, only or except
    desktops: List[str] = field(default_factory=list)
    actions: List[Action] = field(default_factory=list)
    hidden: bool = False                                 # kept out of launcher menus


def current_desktops(env=None) -> List[str]:
    env = os.environ if env is None else env
    return [d for d in (env.get("XDG_CURRENT_DESKTOP") or "").split(":") if d]


# ---------------------------------------------------------------------------
# Values


def escape(value: str) -> str:
    """The reverse of desktop_entries.unescape for string values."""
    return (value.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")
            .replace("\r", "\\r"))


def split_list(value: str) -> List[str]:
    """Split a ;-list, keeping escaped semicolons (\\;) inside items."""
    items = re.split(r"(?<!\\);", value)
    return [de.unescape(v.replace("\\;", ";")) for v in items if v.strip()]


def join_list(items: List[str]) -> str:
    items = [i.strip() for i in items if i.strip()]
    return ";".join(escape(i).replace(";", "\\;") for i in items) + ";" if items else ""


def split_env(exec_line: str) -> Tuple[List[str], str]:
    """`env A=1 B=2 prog` -> (["A=1", "B=2"], "prog"). Anything fancier is
    left in the command as it is."""
    m = _ENV_PREFIX.match(exec_line.strip())
    if not m:
        return [], exec_line.strip()
    env = [v.strip('"') for v in re.findall(r'"[^"]*"|\S+', m.group(1))]
    return env, m.group(2).strip()


def join_env(env: List[str], command: str) -> str:
    env = [e.strip() for e in env if e.strip()]
    if not env:
        return command.strip()
    args = ['"%s"' % e if (" " in e or "\t" in e) else e for e in env]
    return "env " + " ".join(args) + " " + command.strip()


# ---------------------------------------------------------------------------
# Reading


def _source_text(app: de.App) -> str:
    path = app.override_path or app.base_path or app.source_path
    if app.override_path and app.base_path:
        own = read_text(app.override_path)
        if own is not None and not DesktopFile(own).group_dict().get("Exec", "").strip():
            path = app.base_path  # a bare hide file: edit the full entry instead
    text = read_text(path)
    if text is None:
        raise OverrideError(path, "the entry file is missing")
    return text


def read_fields(app: de.App, env=None) -> Fields:
    """The values a launcher uses now, as the editor shows them."""
    df = DesktopFile(_source_text(app))
    d = df.group_dict()
    locales = de.locale_names(env)
    env_vars, command = split_env(de.unescape(d.get("Exec", "")))
    main = {c for c, _n in MAIN_CATEGORIES}
    only, never = split_list(d.get("OnlyShowIn", "")), split_list(d.get("NotShowIn", ""))
    enabled = split_list(d.get("Actions", ""))
    actions = []
    for group in df.groups():
        if group.startswith("Desktop Action "):
            aid = group[len("Desktop Action "):]
            name = de.localized(df.group_dict(group), "Name", locales) or aid
            actions.append(Action(aid, name, aid in enabled))
    return Fields(
        name=de.localized(d, "Name", locales),
        generic_name=de.localized(d, "GenericName", locales),
        comment=de.localized(d, "Comment", locales),
        keywords=split_list(de.localized(d, "Keywords", locales)),
        icon=de.localized(d, "Icon", locales),
        command=command,
        env=env_vars,
        terminal=is_true(d.get("Terminal")),
        prefers_gpu=is_true(d.get("PrefersNonDefaultGPU")),
        wm_class=de.unescape(d.get("StartupWMClass", "")),
        categories=[c for c in split_list(d.get("Categories", "")) if c in main],
        show_in="only" if only else "except" if never else "all",
        desktops=only or never,
        actions=actions,
        hidden=app.hidden,
    )


# ---------------------------------------------------------------------------
# Checking and writing


def validate(fields: Fields) -> List[str]:
    """Problems that stop saving, in plain words."""
    problems = []
    if not fields.name.strip():
        problems.append("The name can't be empty.")
    if not fields.command.strip():
        problems.append("The command can't be empty.")
    bad = [e for e in fields.env if e.strip() and not _ENV_NAME.match(e.strip())]
    if bad:
        problems.append("Environment variables need the form NAME=value: %s" % ", ".join(bad))
    if fields.show_in != "all" and not fields.desktops:
        problems.append("Pick at least one desktop, or choose “Every desktop”.")
    return problems


def _set_text(df: DesktopFile, key: str, value: str) -> None:
    """Set a (possibly translated) key so the new value shows in any language."""
    _remove_translations(df, key)
    if value.strip():
        df.set(key, escape(value.strip()))
    else:
        df.remove(key)


def _remove_translations(df: DesktopFile, key: str) -> None:
    for k, _v in list(df.items()):
        if k.startswith(key + "["):
            df.remove(k)


def _set_bool(df: DesktopFile, key: str, on: bool) -> None:
    if on:
        df.set(key, "true")
    else:
        df.remove(key)


def _set_list(df: DesktopFile, key: str, items: List[str]) -> None:
    value = join_list(items)
    if value:
        df.set(key, value)
    else:
        df.remove(key)


def plan_edit(app: de.App, new: Fields, env=None) -> Optional[Change]:
    """The change that saves `new`, or None if nothing changed."""
    problems = validate(new)
    if problems:
        raise ValueError(" ".join(problems))
    old = read_fields(app, env)
    path = override_path(app, env)
    before = read_text(path)
    bare = before is not None and not DesktopFile(before).group_dict().get("Exec", "").strip()
    df = DesktopFile(before if before is not None and not bare else _source_text(app))
    if before is None or bare:
        df.lines[:0] = [
            "# Copy made by App Entries with your changes to %s." % app.id,
            "# Use Restore original in App Entries, or delete this file, to undo.",
        ]
        df.set(MANAGED_KEY, "true")
    else:
        df.remove(CHECKSUM_KEY)  # it's been edited now

    changed = False
    for attr, key in (("name", "Name"), ("generic_name", "GenericName"), ("comment", "Comment"),
                      ("icon", "Icon"), ("wm_class", "StartupWMClass")):
        if getattr(new, attr).strip() != getattr(old, attr).strip():
            _set_text(df, key, getattr(new, attr))
            changed = True
    if [k.strip() for k in new.keywords if k.strip()] != old.keywords:
        changed = True
        _remove_translations(df, "Keywords")
        _set_list(df, "Keywords", new.keywords)
    if (new.command.strip(), [e.strip() for e in new.env if e.strip()]) != (old.command, old.env):
        changed = True
        df.set("Exec", escape(join_env(new.env, new.command)))
    if new.terminal != old.terminal:
        changed = True
        _set_bool(df, "Terminal", new.terminal)
    if new.prefers_gpu != old.prefers_gpu:
        changed = True
        _set_bool(df, "PrefersNonDefaultGPU", new.prefers_gpu)
    if sorted(new.categories) != sorted(old.categories):
        changed = True
        main = {c for c, _n in MAIN_CATEGORIES}
        others = [c for c in split_list(df.group_dict().get("Categories", "")) if c not in main]
        ordered = [c for c, _n in MAIN_CATEGORIES if c in new.categories]
        _set_list(df, "Categories", ordered + others)
    if (new.show_in, sorted(new.desktops)) != (old.show_in, sorted(old.desktops)):
        changed = True
        df.remove("OnlyShowIn")
        df.remove("NotShowIn")
        if new.show_in == "only":
            _set_list(df, "OnlyShowIn", new.desktops)
        elif new.show_in == "except":
            _set_list(df, "NotShowIn", new.desktops)
    if [(a.id, a.enabled) for a in new.actions] != [(a.id, a.enabled) for a in old.actions]:
        changed = True
        _set_list(df, "Actions", [a.id for a in new.actions if a.enabled])

    if new.hidden != old.hidden:
        changed = True
        df.remove("Hidden")
        if new.hidden:
            df.set("NoDisplay", "true")
        elif app.base_hidden and app.base_path:
            df.set("NoDisplay", "false")  # its package hides it: show it anyway
        else:
            df.remove("NoDisplay")
        df.remove(HIDDEN_KEY)

    if not changed:
        return None
    return Change(app.id, new.name.strip() or app.name, path, before, df.text(), new.hidden)


def preview(app: de.App, new: Fields, env=None) -> str:
    """The entry file as it will be after saving `new` (or as it is now)."""
    try:
        change = plan_edit(app, new, env)
    except ValueError:
        change = None
    if change is not None:
        return change.after
    return read_text(override_path(app, env)) or _source_text(app)


def copy_fields(fields: Fields, **changes) -> Fields:
    """A changed copy (lists copied too), for the editor and tests."""
    f = replace(fields, **changes)
    f.keywords, f.env, f.categories, f.desktops = list(f.keywords), list(f.env), list(f.categories), list(f.desktops)
    f.actions = [Action(a.id, a.name, a.enabled) for a in f.actions]
    return f
