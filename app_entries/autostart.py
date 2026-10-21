"""Programs that start when you log in: the XDG autostart folders.

System entries live in /etc/xdg/autostart (XDG_CONFIG_DIRS), yours in
~/.config/autostart. A file of yours with the same name replaces a system
one, so turning a system entry off writes a copy with Hidden=true there;
the system file is never changed. Every change is an overrides.Change, so
it can be undone. Pure Python, no GTK.
"""
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import desktop_entries as de
from .editing import escape
from .overrides import Change, OverrideError, _digest, is_pristine, read_text, show_here

CREATED_KEY = "X-AppEntries-Created"
GNOME_ENABLED = "X-GNOME-Autostart-enabled"
# Desktops that don't run autostart entries themselves: there it's up to the
# session (uwsm, systemd's xdg-autostart generator, or dex in the config).
NO_AUTOSTART = {"HYPRLAND", "SWAY", "NIRI", "RIVER", "WAYFIRE", "LABWC", "I3", "BSPWM", "DWM", "QTILE",
                "AWESOME", "OPENBOX", "MANGO", "DWL"}


def user_dir(env=None) -> str:
    env = os.environ if env is None else env
    home = env.get("HOME") or os.path.expanduser("~")
    d = env.get("XDG_CONFIG_HOME") or ""
    return os.path.join(d if os.path.isabs(d) else os.path.join(home, ".config"), "autostart")


def system_dirs(env=None) -> List[str]:
    env = os.environ if env is None else env
    dirs = [d for d in (env.get("XDG_CONFIG_DIRS") or "").split(":") if os.path.isabs(d)] or ["/etc/xdg"]
    return [os.path.join(d, "autostart") for d in dirs]


@dataclass
class Item:
    id: str                 # the file name, like nm-applet.desktop
    name: str
    comment: str
    icon: str
    exec: str
    enabled: bool           # it starts at login (on this desktop)
    path: str               # the file in effect
    user_path: str = ""     # your file, if there is one
    system_path: str = ""   # the system file, if there is one
    managed: bool = False   # your file was made by App Entries and not edited since
    created: bool = False   # added with App Entries
    excluded_here: bool = False   # OnlyShowIn/NotShowIn leave it out on this desktop
    only_show_in: Tuple[str, ...] = ()
    not_show_in: Tuple[str, ...] = ()

    @property
    def system(self) -> bool:
        return bool(self.system_path)


def _off(d: Dict[str, str]) -> bool:
    return de.is_true(d.get("Hidden")) or (d.get(GNOME_ENABLED, "").strip().lower() == "false")


def scan(env=None) -> List[Item]:
    env = os.environ if env is None else env
    locales = de.locale_names(env)
    desktops = de.current_desktops(env)
    files: Dict[str, Dict[str, str]] = {}   # id -> {"user": path, "system": path}
    for folder, kind in [(user_dir(env), "user")] + [(d, "system") for d in system_dirs(env)]:
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            continue
        for name in names:
            if name.endswith(".desktop"):
                files.setdefault(name, {}).setdefault(kind, os.path.join(folder, name))
    items = []
    for did, where in files.items():
        path = where.get("user") or where["system"]
        try:
            df = de.DesktopFile.load(path)
        except OSError:
            continue
        d = df.group_dict()
        shown = d
        if where.get("user") and where.get("system") and not d.get("Exec", "").strip():
            try:  # a bare "Hidden=true" file: the details come from the system one
                shown = de.DesktopFile.load(where["system"]).group_dict()
            except OSError:
                pass
        if shown.get("Type", "Application").strip() != "Application":
            continue
        excluded = de.excluded_on(d, desktops)
        items.append(Item(
            id=did,
            name=de.localized(shown, "Name", locales) or did[:-len(".desktop")],
            comment=de.localized(shown, "Comment", locales),
            icon=de.localized(shown, "Icon", locales),
            exec=de.unescape(shown.get("Exec", "")),
            enabled=not _off(d) and not excluded,
            path=path,
            user_path=where.get("user", ""),
            system_path=where.get("system", ""),
            managed=bool(where.get("user")) and is_pristine(df),
            created=bool(where.get("user")) and de.is_true(d.get(CREATED_KEY)),
            excluded_here=excluded,
            only_show_in=tuple(x for x in d.get("OnlyShowIn", "").split(";") if x.strip()),
            not_show_in=tuple(x for x in d.get("NotShowIn", "").split(";") if x.strip()),
        ))
    items.sort(key=lambda i: (i.name.casefold(), i.id))
    return items


def runs_autostart(env=None) -> bool:
    """False on desktops known not to start these entries by themselves."""
    return not any(d.upper() in NO_AUTOSTART for d in de.current_desktops(env))


# How each window manager runs a command at login, for the dex line.
_STARTUP_LINE = {
    "HYPRLAND": "exec-once = dex -a",
    "SWAY": "exec dex -a",
    "I3": "exec --no-startup-id dex -a",
    "NIRI": 'spawn-at-startup "dex" "-a"',
    "RIVER": "riverctl spawn 'dex -a'",
    "WAYFIRE": "autostart_dex = dex -a  (in the [autostart] section)",
    "LABWC": "dex -a &  (in ~/.config/labwc/autostart)",
    "BSPWM": "dex -a &  (in bspwmrc)",
    "OPENBOX": "dex -a &  (in ~/.config/openbox/autostart)",
}


def has_systemd() -> bool:
    """Whether systemd is the running init (the check its own tools use)."""
    return os.path.isdir("/run/systemd/system")


def how_to_run(env=None, systemd: Optional[bool] = None, have_dex: Optional[bool] = None) -> str:
    """What makes these entries run on this desktop, in plain words, or ""
    when the desktop runs them itself."""
    if runs_autostart(env):
        return ""
    import shutil
    desktops = de.current_desktops(env)
    name = desktops[0] if desktops else "This desktop"
    systemd = has_systemd() if systemd is None else systemd
    have_dex = bool(shutil.which("dex")) if have_dex is None else have_dex
    line = next((_STARTUP_LINE[d.upper()] for d in desktops if d.upper() in _STARTUP_LINE), "dex -a")
    dex = ("add this to your config: %s" % line) if have_dex else \
        ("install dex (it's in most distributions' repositories) and add this to your config: %s" % line)
    if systemd:
        return ("%s doesn't start these by itself. They run if your session starts them: through uwsm, "
                "systemd's xdg-autostart support, or dex. For dex, %s." % (name, dex))
    return ("%s doesn't start these by itself, and this system doesn't use systemd, so dex is the way to run "
            "them: %s." % (name, dex))


# ---------------------------------------------------------------------------
# Planning


def _managed_copy(system_text: str, enabled: bool, env=None) -> str:
    df = de.DesktopFile(system_text)
    df.lines[:0] = ["# Copy made by App Entries to turn this off at login. Delete it to undo."]
    df.remove("Hidden")
    if enabled:
        df.remove(GNOME_ENABLED)
        show_here(df, env)
    else:
        df.set("Hidden", "true")
    df.set(de.MANAGED_KEY, "true")
    df.set(de.CHECKSUM_KEY, _digest(df))
    return df.text()


def plan_set_enabled(item: Item, enabled: bool, env=None) -> Optional[Change]:
    if item.enabled == enabled:
        return None
    target = item.user_path or os.path.join(user_dir(env), item.id)
    before = read_text(target)
    if item.system and (before is None or is_pristine(de.DesktopFile(before))):
        system_text = read_text(item.system_path)
        if system_text is None:
            raise OverrideError(item.system_path, "the system entry is missing")
        sys_d = de.DesktopFile(system_text).group_dict()
        sys_on = not _off(sys_d) and not de.excluded_on(sys_d, de.current_desktops(env))
        after = None if sys_on == enabled else _managed_copy(system_text, enabled, env)
        if after is None and before is None:
            return None
        return Change(item.id, item.name, target, before, after, not enabled)
    if before is None:
        raise OverrideError(target, "the file is missing")
    df = de.DesktopFile(before)
    if enabled:
        df.remove("Hidden")
        if df.group_dict().get(GNOME_ENABLED, "").strip().lower() == "false":
            df.set(GNOME_ENABLED, "true")
        show_here(df, env)
    else:
        df.set("Hidden", "true")
    return Change(item.id, item.name, target, before, df.text(), not enabled)


def plan_restore(item: Item) -> Change:
    """Delete your file, so the system entry is used again."""
    if not (item.user_path and item.system_path):
        raise OverrideError(item.user_path or item.id, "there's no system entry to go back to")
    sys_d = de.DesktopFile(read_text(item.system_path) or "").group_dict()
    return Change(item.id, item.name, item.user_path, read_text(item.user_path), None, _off(sys_d))


def plan_delete(item: Item) -> Change:
    """Delete an entry that's only in your folder."""
    if not item.user_path or item.system_path:
        raise OverrideError(item.path, "only entries in your own folder can be deleted")
    return Change(item.id, item.name, item.user_path, read_text(item.user_path), None, True)


def _free_id(base: str, env=None) -> str:
    folder = user_dir(env)
    stem = base[:-len(".desktop")] if base.endswith(".desktop") else base
    did, n = stem + ".desktop", 2
    while os.path.exists(os.path.join(folder, did)):
        did, n = "%s-%d.desktop" % (stem, n), n + 1
    return did


def plan_add_app(app: de.App, env=None) -> Change:
    """Start an installed app at login: a copy of its entry in your folder."""
    text = read_text(app.source_path)
    if text is None:
        raise OverrideError(app.source_path, "the app's entry is missing")
    df = de.DesktopFile(text)
    for key in ("Hidden", "NoDisplay", "OnlyShowIn", "NotShowIn", "DBusActivatable"):
        df.remove(key)
    # Field codes like %U would be passed as nothing at login.
    d = df.group_dict()
    df.set("Exec", " ".join(p for p in d.get("Exec", "").split() if not (len(p) == 2 and p.startswith("%"))))
    df.lines[:0] = ["# Added by App Entries to start %s when you log in." % app.name]
    df.set(CREATED_KEY, "true")
    did = _free_id(app.id, env)
    return Change(did, app.name, os.path.join(user_dir(env), did), None, df.text(), False)


def plan_add_command(name: str, command: str, env=None) -> Change:
    name, command = name.strip(), command.strip()
    if not name or not command:
        raise ValueError("A name and a command are needed.")
    slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "program"
    did = _free_id("app-entries-" + slug, env)
    text = "\n".join([
        "[Desktop Entry]",
        "# Added by App Entries to run this when you log in.",
        "Type=Application",
        "Name=" + escape(name),
        "Exec=" + escape(command),
        CREATED_KEY + "=true",
    ]) + "\n"
    return Change(did, name, os.path.join(user_dir(env), did), None, text, False)
