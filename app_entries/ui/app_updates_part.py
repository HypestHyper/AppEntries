"""On the Updates page: every app and tool from GitHub in one list, checked
when you ask (or once a day, if you turn that on), and how many system,
Flatpak and Snap updates are waiting. AppImages are updated here, with
Undo; everything else runs its own command in your terminal."""
import os
import time
from gettext import gettext as _
from gettext import ngettext

from gi.repository import Gio, GLib, Gtk

from .. import app_updates, github_apps, terminal
from .dialogs import run_bg
from .widgets import WrapBox, button, card, clear, hbox, label, section, spinner, switch_row, vbox

KINDS = {
    "appimage": _("AppImage"), "command": _("Updated with its own command"), "aur": _("AUR package"),
    "package": _("Package file from GitHub"), "tool": _("Command-line tool"),
}


class AppUpdates(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.items = []
        self.rows = {}
        self.append(section(_("App updates"),
                            _("Apps and tools that come from a GitHub project: AppImages, apps installed with pip, "
                              "pipx or uv, git copies, AUR packages and package files from GitHub, and tools in "
                              "Tools. GitHub is only asked when you check.")))
        c = card()
        self.check_btn = button(_("Check all"), "sync", "tonal", small=True, cb=lambda *_a: self.check_all())
        self.state = label("", ("small", "dim"), wrap=True)
        self.state.set_hexpand(True)
        c.append(hbox(12, self.check_btn, self.state))
        self.list = vbox(10)
        c.append(self.list)
        row, _sw = switch_row(_("Check once a day, when App Entries starts"),
                              win.settings.get("check-app-updates"),
                              lambda v: win.settings.set("check-app-updates", v))
        c.append(row)
        c.append(label(_("A daily check asks GitHub for each project's latest release, sends nothing about you, and "
                         "never downloads or changes anything. Without an account GitHub allows 60 questions an "
                         "hour."), ("small", "faint"), wrap=True, chars=60))
        self.append(c)
        self.append(SystemUpdates())
        self._gather()

    # -- the list -------------------------------------------------------------

    def _gather(self):
        clear(self.list)
        self.list.append(hbox(10, spinner(), label(_("Looking for apps from GitHub…"), ("small", "dim"))))
        apps = [i.app for i in self.win.apps.items()]
        run_bg(lambda: app_updates.gather(apps), self._gathered)

    def _gathered(self, items):
        clear(self.list)
        if isinstance(items, Exception):
            self.list.append(label(str(items), ("small", "error-text"), wrap=True))
            return
        self.items = items
        self.check_btn.set_sensitive(bool(items))
        if not items:
            self.state.set_label(_("No apps or tools from GitHub found."))
            return
        known = getattr(self.win, "app_update_results", {})
        for c in items:
            if c.key in known:
                c.result, c.error = known[c.key]
            self.rows[c.key] = row = vbox(6)
            row.add_css_class("tool-row")
            self.list.append(row)
            self._show(c)
        checked = app_updates.load_state().get("checked", 0)
        self.state.set_label(ngettext("{n} app or tool", "{n} apps and tools", len(items)).format(n=len(items)) +
                             (" · " + _("last checked {when}").format(when=_ago(checked)) if checked else ""))

    def _show(self, c, busy=""):
        row = self.rows[c.key]
        clear(row)
        name = hbox(8, label(c.name, ("body", "app-name")), label(c.version, ("small", "dim")))
        sub = KINDS.get(c.kind, "") + " · GitHub: " + c.src.name
        text = vbox(2, name, label(sub, ("small", "dim"), wrap=True))
        text.set_hexpand(True)
        line = hbox(12, text)
        acts = WrapBox(6, 6)
        acts.set_valign(Gtk.Align.CENTER)
        if busy:
            acts.append(hbox(8, spinner(), label(busy, ("small", "dim"))))
        elif c.error:
            acts.append(label(c.error, ("small", "error-text"), wrap=True, chars=30))
        elif c.result is not None:
            v = github_apps.version_in(c.result.release.tag) or c.result.release.tag
            if c.result.newer:
                acts.append(label(_("{version} is out").format(version=v), ("small", "accent")))
                b = self._update_button(c)
                if b is not None:
                    acts.append(b)
            else:
                acts.append(label(_("Up to date"), ("small", "dim")))
            acts.append(button(icon_name="open_in_new", style="text", small=True, tooltip=_("Release page"),
                               cb=lambda *_a: Gio.AppInfo.launch_default_for_uri(c.result.release.url, None)))
        line.append(acts)
        row.append(line)

    def _update_button(self, c):
        if c.kind == "appimage" and c.result.asset is not None:
            return button(_("Update"), "download", "filled", small=True,
                          tooltip=_("Downloads {file} next to the one you have and points the launcher at it. The "
                                    "old file goes to the Trash; Undo puts it back.").format(file=c.result.asset.name),
                          cb=lambda *_a: self._update_appimage(c))
        if c.kind in ("command", "tool") and c.update_cmd:
            return button(_("Update"), "terminal", "tonal", small=True,
                          tooltip=_("Runs this in your terminal:\n{cmd}").format(cmd=terminal.shown(c.update_cmd)),
                          cb=lambda *_a: _terminal(self, c.update_cmd))
        if c.kind == "aur":
            helper = next((h for h in ("paru", "yay") if GLib.find_program_in_path(h)), "")
            if helper:
                return button(_("Update"), "terminal", "tonal", small=True,
                              tooltip=_("Runs {cmd} in your terminal. The AUR package may lag behind GitHub.")
                              .format(cmd=f"{helper} -S {c.name}"),
                              cb=lambda *_a: _terminal(self, [[helper, "-S", c.name]]))
        if c.kind == "package" and c.result.asset is not None:
            return button(_("Update"), "download", "tonal", small=True,
                          tooltip=_("Downloads {file} to Downloads and installs it with apt in your terminal.")
                          .format(file=c.result.asset.name), cb=lambda *_a: self._update_package(c))
        return None

    # -- checking ---------------------------------------------------------------

    def check_all(self):
        self.check_btn.set_sensitive(False)
        items = list(self.items)
        for c in items:
            self._show(c, _("Asking GitHub…"))

        def work():
            for c in items:
                app_updates.check(c)
                GLib.idle_add(lambda c=c: (self._show(c), False)[1])
            return items

        def done(_r):
            self.check_btn.set_sensitive(True)
            newer = [c.key for c in items if c.result is not None and c.result.newer]
            app_updates.save_state(time.time(), newer)
            self.win.app_update_results = {c.key: (c.result, c.error) for c in items}
            self.win.set_app_updates(newer)
            self.state.set_label(ngettext("{n} update", "{n} updates", len(newer)).format(n=len(newer)) +
                                 " · " + _("checked just now"))

        run_bg(work, done)

    # -- updating ---------------------------------------------------------------

    def _update_appimage(self, c):
        path = c.details.path
        self._show(c, _("Downloading…"))

        last = {"t": 0.0}

        def progress(done, total):
            now = time.monotonic()
            if total and (now - last["t"] > 0.25 or done == total):
                last["t"] = now
                text = _("Downloading: {done} of {total}").format(done=GLib.format_size(done),
                                                                   total=GLib.format_size(total))
                GLib.idle_add(lambda: (self._show(c, text), False)[1])

        def downloaded(new):
            if isinstance(new, Exception):
                c.error = str(new)
                self._show(c)
                return
            version = github_apps.version_in(c.result.release.tag) or c.result.release.tag

            def finished(ok):
                if ok:
                    github_apps.remember_installed(c.key, c.result.release.tag, os.path.basename(new), c.src.name)
                    c.result.newer = False
                elif os.path.exists(new):
                    os.remove(new)
                self._show(c)
            self.win.use_newer(c.app, path, new, downloaded=True, done=finished,
                               message=lambda _n: _("{name} updated to {version}").format(name=c.name,
                                                                                          version=version))
        run_bg(lambda: github_apps.download(c.result.asset, os.path.dirname(path), progress), downloaded)

    def _update_package(self, c):
        from .install_section import _downloads, _install_command
        self._show(c, _("Downloading…"))

        def downloaded(path):
            if isinstance(path, Exception):
                c.error = str(path)
            else:
                _terminal(self, [_install_command(c.manager, path)])
            self._show(c)
        run_bg(lambda: github_apps.download(c.result.asset, _downloads()), downloaded)


class SystemUpdates(Gtk.Box):
    """How many updates the system's package manager, Flatpak and Snap have
    waiting, and the command that installs them, run in your terminal."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.append(section(_("System, Flatpak and Snap"),
                            _("How many updates are waiting. Updating runs the usual command in your terminal, where "
                              "it asks for your password and shows what it does.")))
        self.card = card()
        self.btn = button(_("Look for updates"), "sync", "tonal", small=True, cb=lambda *_a: self._check())
        self.btn.set_halign(Gtk.Align.START)
        self.card.append(self.btn)
        self.body = vbox(10)
        self.card.append(self.body)
        self.append(self.card)

    def _check(self):
        self.btn.set_sensitive(False)
        clear(self.body)
        self.body.append(hbox(10, spinner(), label(_("Asking…"), ("small", "dim"))))
        run_bg(app_updates.system_updates, self._show)

    def _show(self, found):
        self.btn.set_sensitive(True)
        clear(self.body)
        if isinstance(found, Exception) or not found:
            self.body.append(label(str(found) if isinstance(found, Exception) else
                                   _("No package manager, Flatpak or Snap could say."), ("small", "dim"), wrap=True))
            return
        everything = []
        for w in found:
            text = vbox(2, label(w.source, ("body", "app-name")),
                        label(ngettext("{n} update waiting", "{n} updates waiting", w.count).format(n=w.count)
                              if w.count else _("Up to date"), ("small", "accent" if w.count else "dim")))
            text.set_hexpand(True)
            if w.count:
                text.set_tooltip_text(", ".join(w.names[:60]) + ("…" if len(w.names) > 60 else ""))
                everything += w.command
            row = hbox(12, text)
            if w.count:
                row.append(button(_("Update"), "terminal", "tonal", small=True,
                                  tooltip=_("Runs this in your terminal:\n{cmd}").format(cmd=terminal.shown(w.command)),
                                  cb=lambda *_a, cmd=w.command: _terminal(self, cmd)))
            self.body.append(row)
        if len([w for w in found if w.count]) > 1:
            all_btn = button(_("Update everything"), "terminal", "filled", small=True,
                             tooltip=_("Runs these one after another in your terminal:\n{cmd}").format(
                                 cmd=terminal.shown(everything)), cb=lambda *_a: _terminal(self, everything))
            all_btn.set_halign(Gtk.Align.START)
            self.body.append(all_btn)


def _ago(ts) -> str:
    dt = GLib.DateTime.new_from_unix_local(int(ts))
    return dt.format("%e %B, %H:%M").strip() if dt else ""


def _terminal(widget, commands):
    """Run commands in the user's terminal; if there's none, say what to run."""
    try:
        terminal.start(commands)
    except (terminal.NoTerminal, OSError) as e:
        from .dialogs import Dialog
        Dialog(widget.get_root(), _("Couldn't open a terminal"), _("{error}. Run this yourself:\n{cmd}").format(
            error=e, cmd=terminal.shown(commands)), [("ok", _("Close"), "tonal")]).present()
