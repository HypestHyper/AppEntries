"""Adding AppImages, app folders, Windows programs, jars, downloaded .desktop
files and Distrobox apps: choose it, App Entries reads it, and the launcher
form opens filled in, with a card saying what else saving does."""
import os
from gettext import gettext as _

from gi.repository import GLib, Gtk

from .. import desktop_entries as de
from .. import importers, launchers
from ..overrides import Change, read_text
from .dialogs import Dialog, choose_file, error_dialog, run_bg
from .widgets import Group, Toggle, button, card, hbox, label, vbox

# (key, menu title, icon, explanation)
KINDS = [
    ("launcher", _("Launcher"), "rocket_launch", _("A program, a script or commands")),
    ("webapp", _("Web app"), "language", _("A site in its own window")),
    ("appimage", _("AppImage…"), "deployed_code", _("Reads its name, icon and file types")),
    ("folder", _("App folder…"), "folder_open", _("An app you unpacked from a tar.gz or zip")),
    ("exe", _("Windows program…"), "computer", _("An .exe, run with Wine or Proton")),
    ("jar", _("Java app…"), "code", _("A .jar file, run with Java")),
    ("desktop", _("A .desktop file…"), "description", _("An entry that came with an app")),
    ("distrobox", _("Distrobox app…"), "package_2", _("An app inside a container")),
]

PATTERNS = {
    "appimage": (["*.AppImage", "*.appimage"], _("AppImages")),
    "exe": (["*.exe", "*.EXE", "*.msi", "*.bat"], _("Windows programs")),
    "jar": (["*.jar"], _("Java apps")),
    "desktop": (["*.desktop"], _("Launcher entries")),
}


def menu(win, menu_button):
    """The New ▾ menu."""
    from .widgets import option_button
    box = vbox(2)
    box.set_size_request(300, -1)
    for key, title, glyph, what in KINDS:
        if key == "distrobox" and not importers.shutil.which("distrobox"):
            continue

        def go(*_a, key=key):
            menu_button.popdown()
            GLib.idle_add(lambda: (start(win, key), False)[1])
        box.append(option_button(glyph, title, what, go))
    pop = Gtk.Popover()
    pop.add_css_class("options")
    pop.set_child(box)
    menu_button.set_popover(pop)


def start(win, key, path=None):
    """Begin adding one; `path` skips choosing (from the scan, or a drop)."""
    if key == "launcher":
        win.new_launcher()
        return
    if key == "webapp":
        win.new_web_app()
        return
    if key == "distrobox":
        DistroboxPicker(win).present()
        return
    if path:
        _read(win, key, path)
        return
    patterns, name = PATTERNS.get(key, (None, None))
    choose_file(win, {k: t for k, t, _g, _w in KINDS}[key].rstrip("…"),
                lambda p: _read(win, key, p), folder=key == "folder", patterns=patterns, filter_name=name,
                start=importers.applications_dir() if os.path.isdir(importers.applications_dir()) else None)


def _read(win, key, path, allow_run=False, runner=None):
    def work():
        if key == "appimage":
            return importers.read_appimage(path, allow_run=allow_run)
        if key == "folder":
            return importers.read_folder(path)
        if key == "exe":
            return importers.read_exe(path, runner or (importers.runners() or [("wine", "")])[0][0])
        if key == "jar":
            return importers.read_jar(path)
        return importers.read_desktop_file(path)

    def done(result):
        if isinstance(result, importers.NeedsRun):
            _ask_to_run(win, key, path)
        elif isinstance(result, Exception):
            error_dialog(win, _("Couldn't read it"), str(result), path)
        elif key == "desktop":
            _confirm_desktop(win, result)
        else:
            _open_form(win, result)

    run_bg(work, done)


def _ask_to_run(win, key, path):
    def on_response(resp):
        if resp == "run":
            _read(win, key, path, allow_run=True)
        elif resp == "skip":
            _open_form(win, importers.Import("appimage", path, launchers.Spec(
                name=importers._pretty(path), kind="program", program=path), how="name",
                notes=[_("Its name and icon weren't read from the file, so check them below.")]))

    Dialog(win, _("Read it by running it?"),
           _("App Entries reads an AppImage's name, icon and file types with unsquashfs, which isn't installed. "
             "Without it, the AppImage's own extractor can read them, but that runs the file. Only do this if "
             "you trust where it came from. Installing squashfs-tools avoids the question."),
           [("cancel", _("Cancel"), "tonal"), ("skip", _("Fill it in myself"), "tonal"),
            ("run", _("Run its extractor"), "filled")], on_response, icon_name="warning",
           icon_class="warn-text", detail=path).present()


class _Options(Gtk.Box):
    """The card under the preview: where it came from and what saving also does."""

    def __init__(self, imp, on_runner=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.imp = imp
        c = card()
        c.set_margin_top(12)
        kind_name = {"appimage": _("AppImage"), "folder": _("App folder"), "exe": _("Windows program"),
                     "jar": _("Java app")}.get(imp.kind, "")
        head = label(kind_name + (f" {imp.version}" if imp.version else ""), ("body", "option-title"))
        where = label(imp.source, ("mono", "faint"), ellipsize=True)
        where.set_tooltip_text(imp.source)
        c.append(vbox(2, head, where))
        self.move = None
        if imp.kind in ("appimage", "folder") and not importers.in_applications(imp.source):
            self.move = Toggle(True)
            text = vbox(2, label(_("Move it to your Applications folder"), ("body",)),
                        label(_("To {path}, so it keeps working if you tidy up Downloads.")
                              .format(path=importers.moved_path(imp.source)), ("small", "dim"), wrap=True,
                              chars=40))
            text.set_hexpand(True)
            c.append(hbox(12, text, self.move))
        if imp.kind == "appimage":
            note = (_("It isn't executable yet, so it'll be made executable.")
                    if not os.access(imp.source, os.X_OK) else "")
            if note:
                c.append(label(note, ("small", "dim"), wrap=True))
        if imp.spec.mime_types:
            c.append(label(_("Opens {n} kinds of file, so it'll be in Open With and Defaults for them.")
                           .format(n=len(imp.spec.mime_types)), ("small", "dim"), wrap=True))
        if imp.kind == "exe" and on_runner is not None:
            choices = importers.runners() or [("wine", "Wine")]
            current = "umu" if imp.spec.program.startswith("umu-run") else "wine"
            c.append(vbox(6, label(_("Run it with"), ("body",)),
                          Group([(k, n) for k, n in choices], current, on_runner)))
        for n in imp.notes:
            c.append(label(n, ("small", "warn-text"), wrap=True, chars=50))
        self.append(c)


def _open_form(win, imp):
    from .launcher_window import LauncherWindow
    icon_preview = None
    if imp.icon is not None:
        # Shown from a cache copy until saving puts it in your icon library.
        cache = os.path.join(GLib.get_user_cache_dir(), "app-entries", "import")
        os.makedirs(cache, exist_ok=True)
        icon_preview = os.path.join(cache, imp.icon[1])
        with open(icon_preview, "wb") as f:
            f.write(imp.icon[0])
        imp.spec.icon_kind, imp.spec.icon_value = "theme", icon_preview
    holder = {}

    def on_runner(key):
        form = holder.get("form")
        new = importers.read_exe(imp.source, key)
        imp.spec.program = new.spec.program
        if form is not None:
            form.program.set_text(new.spec.program)

    options = _Options(imp, on_runner if imp.kind == "exe" else None)
    titles = {"appimage": _("New launcher for an AppImage"), "folder": _("New launcher for an app folder"),
              "exe": _("New launcher for a Windows program"), "jar": _("New launcher for a Java app")}

    def on_save(_did, spec, make_exec):
        _save(win, imp, spec, make_exec, options, icon_preview)

    form = LauncherWindow(win, on_save, win._save_raw, glyph_color=win.style.palette["ON_SURFACE"],
                          highlight=win._highlight(), on_close=win._close_form, start=imp.spec,
                          title=titles.get(imp.kind), extra=options)
    holder["form"] = form
    win._show_form(form)


def _save(win, imp, spec, make_exec, options, icon_preview):
    moving = options.move is not None and options.move.get_active()

    def plan():
        notes = []
        if moving:
            old = imp.source
            new = importers.move(old)
            spec.program = spec.program.replace(old, new)
            if spec.workdir == old or spec.workdir.startswith(old + os.sep):
                spec.workdir = new + spec.workdir[len(old):]
            imp.source = new
            notes.append(new)
        if imp.kind == "appimage":
            importers.make_executable(imp.source)
        elif make_exec:
            launchers.make_executable(spec.program)
        changes = []
        if icon_preview and spec.icon_kind != "symbol" and spec.icon_value == icon_preview:
            path, changes = importers.plan_icon(imp)
            spec.icon_value = path
        did, more = launchers.plan_save(spec, None)
        win.open_after_scan = did
        return changes + more

    def after(_changes):
        from .. import appimages
        if spec.mime_types:
            appimages.refresh_mime()
            _update_desktop_database()
        return []

    win._run_changes(plan, lambda n: _("Added {name}").format(name=spec.name.strip()),
                     _("Couldn't add the launcher"), after=after)


def _update_desktop_database():
    """So file managers see the new file types now."""
    import shutil
    import subprocess

    from .. import desktop_entries as de
    tool = shutil.which("update-desktop-database")
    if tool:
        try:
            subprocess.run([tool, de.user_apps_dir()], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            pass


def _confirm_desktop(win, imp):
    """A downloaded entry is installed as it is (after a check), so show it first."""
    errors, warnings = launchers.check_raw(imp.entry_text)
    body = _("It's copied into your applications folder as {id}, so launchers list it.").format(id=imp.entry_id)
    if imp.notes:
        body += " " + " ".join(imp.notes)
    if errors:
        error_dialog(win, _("This entry has problems"), " ".join(errors), imp.source)
        return
    if warnings:
        body += " " + " ".join(warnings)

    def on_response(resp):
        if resp == "add":
            target = os.path.join(de.user_apps_dir(), imp.entry_id)
            win._run_changes(lambda: [Change(imp.entry_id, imp.spec.name, target, read_text(target),
                                             imp.entry_text, False)],
                             lambda n: _("Added {name}").format(name=imp.spec.name), _("Couldn't add it"))

    Dialog(win, _("Add {name}?").format(name=imp.spec.name or imp.entry_id), body,
           [("cancel", _("Cancel"), "tonal"), ("add", _("Add"), "filled")], on_response,
           icon_name="description", detail=imp.entry_text).present()


class DistroboxPicker(Gtk.Window):
    """Choose a container, then the apps in it to add to your menus."""

    def __init__(self, win):
        super().__init__(transient_for=win, modal=True, title=_("Add a Distrobox app"))
        self.win = win
        self.add_css_class("prefs")
        self.set_default_size(460, 520)
        hb = Gtk.HeaderBar()
        hb.set_show_title_buttons(False)
        hb.set_title_widget(label(_("Add a Distrobox app"), ("title",)))
        close = button(_("Close"), style="tonal", small=True, cb=lambda *_a: self.close())
        close.set_valign(Gtk.Align.CENTER)
        hb.pack_end(close)
        self.set_titlebar(hb)
        self.page = vbox(10)
        for side in ("start", "end", "bottom", "top"):
            getattr(self.page, "set_margin_" + side)(16)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroll.set_child(self.page)
        self.set_child(scroll)
        self.page.append(label(_("Looking for containers…"), ("body", "dim")))
        run_bg(importers.containers, self._containers)

    def _clear(self):
        c = self.page.get_first_child()
        while c is not None:
            n = c.get_next_sibling()
            self.page.remove(c)
            c = n

    def _containers(self, names):
        self._clear()
        if isinstance(names, Exception) or not names:
            self.page.append(label(_("No Distrobox containers were found."), ("body", "dim"), wrap=True))
            return
        self.page.append(label(_("Choose a container. Its apps are listed next."), ("small", "dim"), wrap=True))
        for n in names:
            self.page.append(button(n, "package_2", "tonal", cb=lambda *_a, n=n: self._apps(n)))

    def _apps(self, container):
        self._clear()
        self.page.append(label(_("Starting {name} to list its apps…").format(name=container), ("body", "dim")))
        run_bg(lambda: importers.container_apps(container), lambda apps: self._list(container, apps))

    def _list(self, container, apps):
        self._clear()
        if isinstance(apps, Exception) or not apps:
            self.page.append(label(_("No apps were found in {name}.").format(name=container), ("body", "dim")))
            return
        self.page.append(label(_("Add puts the app in your menus with distrobox-export, which runs inside "
                                 "{name}.").format(name=container), ("small", "dim"), wrap=True))
        c = card()
        for did, title in apps:
            t = label(title, ("body",), ellipsize=True)
            t.set_hexpand(True)
            c.append(hbox(12, t, button(_("Add"), style="tonal", small=True,
                                       cb=lambda b, did=did: self._export(b, container, did))))
        self.page.append(c)

    def _export(self, btn, container, did):
        btn.set_sensitive(False)

        def work():
            import subprocess
            r = subprocess.run(importers.export_argv(container, did), capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip() or r.stdout.strip() or _("distrobox-export failed."))

        def done(result):
            if isinstance(result, Exception):
                btn.set_sensitive(True)
                error_dialog(self, _("Couldn't add it"), str(result))
                return
            btn.set_label(_("Added"))
            self.win.queue_rescan(0)
            self.win.snackbar.show(_("Added from {name}").format(name=container))

        run_bg(work, done)
