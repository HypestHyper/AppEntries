"""The Installation section at the bottom of an app's page: where it came
from, when, by whom, its size, and what it depends on.

The page opens without waiting: this section starts as a placeholder the
size of the finished card and fills in from a background thread. The
dependency lists are read only when they're opened. Answers are
remembered (install_info), so a page opened again fills in at once."""
from gettext import gettext as _
from gettext import ngettext

from gi.repository import Gio, GLib, Gtk, Pango

from .. import github_apps, install_info, terminal
from .dialogs import run_bg
from .widgets import WrapBox, button, card, clear, hbox, icon, label, section, spinner, vbox

SHOWN = 40      # names shown in a list before "and N more"

REPO = {
    "distribution": _("Your distribution's repositories"),
    "foreign": _("Not from your distribution's repositories (the AUR, another repository or a downloaded file)"),
    "local": _("A package file installed by hand: no repository has this version"),
    "unknown": _("Not recorded"),
}
WHEN = {
    "installed": _("Installed"),
    "updated": _("Installed or last updated"),
    "file": _("File date"),
}
NOTES = {
    "steam": _("Steam installed this game and keeps it up to date. Its files, size and updates are in Steam."),
    "distrobox": _("This app is installed inside the {box} container. Its package details are in there."),
}


def _date(ts):
    dt = GLib.DateTime.new_from_unix_local(int(ts))
    return dt.format("%e %B %Y, %H:%M").strip() if dt else ""


class InstallSection(Gtk.Box):
    """`still_here()` says whether the page still shows this app, so an
    answer that arrives after the user moved on is dropped."""

    def __init__(self, app, still_here, win=None, key=None):
        """`win` is the main window, for what the update watch found (`key`
        is the app's or tool's key there, its ID by default)."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self._here = still_here
        self.win = win
        self.key = key or app.id
        self.append(section(_("Installation"),
                            _("Where {name} came from, as recorded by what installed it.").format(name=app.name)))
        self.card = card()
        self.append(self.card)
        d = install_info.cached(app)
        if d is not None:
            self._fill(d)
            return
        # The placeholder takes about the room the details will, so nothing moves.
        self.card.set_size_request(-1, 150)
        wait = hbox(10, spinner(), label(_("Reading package details…"), ("body", "dim")))
        wait.set_valign(Gtk.Align.CENTER)
        wait.set_vexpand(True)
        self.card.append(wait)
        run_bg(lambda: install_info.summary(app), self._loaded)

    def _loaded(self, d):
        if not self._here():
            return
        clear(self.card)
        self.card.set_size_request(-1, -1)
        if isinstance(d, Exception):
            self.card.append(label(_("The package details couldn't be read: {error}").format(error=d),
                                   ("body", "dim"), wrap=True))
            return
        self._fill(d)

    # -- the summary --------------------------------------------------------

    def _fill(self, d):
        c = self.card
        if not d.kind:
            c.append(label(_("App Entries couldn't tell what installed this app: no package owns its entry or "
                             "its program."), ("body", "dim"), wrap=True))
            return
        if d.note and d.note != "managed":
            c.append(label(NOTES[d.note].format(box=d.package), ("body",), wrap=True))
            return
        grid = WrapBox(28, 14)
        c.append(grid)

        def add(title, value, mono=False, tip=None):
            if not value:
                return None
            v = label(value, ("mono",) if mono else ("body",), wrap=True, chars=34)
            v.set_wrap_mode(Pango.WrapMode.WORD_CHAR)     # long paths wrap, shown whole
            v.set_selectable(True)
            v.set_tooltip_text(tip or (value if mono else None))
            grid.append(vbox(2, label(title, ("small", "dim")), v))
            return v

        home = GLib.get_home_dir()

        def short(path):
            return "~" + path[len(home):] if path.startswith(home + "/") else path

        if d.kind == "managed" and d.manager != "Bottles":
            c.prepend(label(_("{launcher} installed this and starts it. Update or uninstall it there; its files are "
                              "{launcher}'s to manage.").format(launcher=d.manager), ("body",), wrap=True))
        if d.made:
            add(_("Launcher"), _("Made with App Entries"))
            if d.made_date:
                add(_("Launcher last changed"), _date(d.made_date))
        if d.kind == "wine":
            add(_("Windows program"), d.path, mono=True)
            add(_("Run with"), _("Wine"))
            add(_("Its Wine prefix"), short(d.folder), mono=True, tip=d.folder)
        elif d.kind == "managed" and d.manager == "Bottles":
            add(_("Runs in"), _("Bottles, in the bottle “{bottle}”").format(bottle=d.package))
            add(_("Program"), d.raw.get("program", ""))
            add(_("The bottle's folder"), short(d.folder), mono=True, tip=d.folder)
        elif d.kind == "managed":
            add(_("Installed and started by"), d.manager)
            add(_("From"), d.store)
            add(_("Version"), d.version)
            add(_("Its folder"), short(d.folder), mono=True, tip=d.folder)
            if d.manager != "JetBrains Toolbox":
                add(_("Its ID in {launcher}").format(launcher=d.manager), d.package, mono=True)
        elif d.kind == "self":
            add(_("Version"), d.version)
            add(_("Installed in"), short(d.folder), mono=True, tip=d.folder)
            add(_("Updates"), _("From GitHub: HypestHyper/AppEntries, in Updates"))
        elif d.made == "webapp":
            add(_("Opens"), d.site, mono=True)
            add(_("In"), d.browser)
            if d.folder:
                add(_("Its own sign-ins and data"), GLib.format_size(d.data_size) + " · " + short(d.folder),
                    tip=d.folder)
            else:
                add(_("Sign-ins"), _("Shared with the browser"))
        elif d.made == "commands":
            add(_("Runs"), _("Commands you wrote, with {shell}").format(shell=d.shell or "sh"))
        elif d.kind == "package":
            add(_("Package"), _("{name} {version} ({manager})").format(name=d.package, version=d.version,
                                                                      manager=d.manager).replace("  ", " "))
            where = add(_("From"), REPO.get(d.repo, d.repo) or _("Checking…"))
            if not d.repo and d.manager == "apt":
                # apt takes a moment to say; the rest is shown meanwhile.
                where.add_css_class("dim")

                def found(r):
                    if self._here() and not isinstance(r, Exception):
                        where.set_label(REPO.get(r.repo, r.repo))
                        where.remove_css_class("dim")
                        later = getattr(self, "_apt_github", None)
                        if later and r.repo in ("local", "unknown"):
                            later[0].append(GitHubPart(self.app, r, later[1], self._here))
                run_bg(lambda: install_info.origin(self.app), found)
        elif d.kind == "flatpak":
            add(_("Flatpak"), f"{d.package} {d.version}".strip(), mono=True)
            add(_("From"), d.repo)
        elif d.kind == "snap":
            add(_("Snap"), f"{d.package} {d.version}".strip())
            add(_("Channel"), d.repo)
            add(_("Publisher"), d.publisher)
        else:
            home = GLib.get_home_dir()
            shown = "~" + d.path[len(home):] if d.path.startswith(home + "/") else d.path
            add(_("AppImage") if d.kind == "appimage" else _("Program"), shown, mono=True, tip=d.path)
            if d.folder:
                add(_("Its folder"), short(d.folder), mono=True, tip=d.folder)
            if d.kind == "file":
                add(_("From"), INSTALLERS.get(d.installer, INSTALLERS[""]))
                if d.installer:
                    add(_("Version"), f"{d.package} {d.version}".strip())
        # Package managers record whether it was asked for by name or came
        # in for another package; only some record who asked.
        how = {"you": _("installed directly"), "dependency": _("pulled in by another package")}.get(d.reason, "")
        if d.date:
            when = _date(d.date)
            add(WHEN.get(d.date_label, _("Installed")), f"{when}, {how}" if how else when)
        elif how:
            add(_("Installed"), how[0].upper() + how[1:])
        if d.by:
            add(_("Installed by"), d.by)
        if d.scope:
            add(_("For"), _("All users") if d.scope == "system" else _("Just you"))
        if d.size and d.made not in ("webapp", "commands"):
            add(_("Size of the prefix") if d.kind == "wine" else _("Size of the bottle") if d.manager == "Bottles"
                else _("Size") if not d.folder or d.kind == "self" else _("Size of its folder"),
                GLib.format_size(d.size))
        if d.origin:
            add(_("Downloaded from"), d.origin, mono=True)
        src = None
        if d.kind in ("appimage", "file", "package") and d.made != "webapp":
            src = github_apps.source_of(self.app.id, d.raw.get("update_info", ""), d.origin,
                                        project=d.project or d.homepage, how=d.installer or "homepage")
        if d.updates_from and src is None:
            add(_("Updates come from"), d.updates_from)
        if d.kind in ("package", "flatpak", "snap") and d.made != "webapp":
            c.append(self._deps_expander(d))
        if d.kind == "flatpak":
            c.append(self._permissions_expander(d))
            note = self.win.update_note(self.key) if self.win is not None else ""
            if note:
                # Flatpak updates it, not the system's package manager.
                cmd = [["flatpak", "update", "--user" if d.scope == "user" else "--system", d.package]]
                waiting = vbox(8)
                waiting.add_css_class("card-inner")
                waiting.append(hbox(10, Gtk.Box(css_classes=["update-dot"], valign=Gtk.Align.CENTER),
                                    label(_("An update is waiting in Flatpak."), ("body",))))
                waiting.append(_start(button(_("Update in terminal"), "terminal", "tonal", small=True,
                                             tooltip=terminal.shown(cmd), cb=lambda *_a: _run_terminal(self, cmd))))
                c.append(waiting)
        if d.kind in ("appimage", "file") and d.made not in ("webapp", "commands"):
            c.append(GitHubPart(self.app, d, src, self._here, self.win, self.key))
        elif d.kind == "package" and src is not None and d.made != "webapp":
            # Only for packages your distribution doesn't keep up to date.
            if d.foreign or d.repo in ("local", "unknown") or (d.manager not in ("pacman", "apt") and not any(
                    v in d.repo for v in ("Fedora", "openSUSE", "SUSE", "Red Hat", "CentOS", "Rocky", "Alma"))):
                c.append(GitHubPart(self.app, d, src, self._here, self.win, self.key))
            elif d.manager == "apt" and not d.repo:
                self._apt_github = (c, src)     # shown if apt says it was installed from a file

    # -- the dependency lists, read when opened ------------------------------

    def _deps_expander(self, d):
        ex = Gtk.Expander()
        ex.add_css_class("entry-expander")
        ex.set_label_widget(hbox(8, icon("account_tree"), label(_("Dependencies"), ("body",))))
        self.deps = vbox(14)
        self.deps.set_margin_top(6)
        ex.set_child(self.deps)
        started = {"yes": False}

        def opened(*_a):
            if not ex.get_expanded() or started["yes"]:
                return
            started["yes"] = True
            if d.full:
                self._deps(d)
                return
            self.deps.append(hbox(10, spinner(), label(_("Reading dependencies…"), ("small", "dim"))))
            run_bg(lambda: install_info.dependencies(self.app), self._deps_loaded)

        ex.connect("notify::expanded", opened)
        return ex

    def _permissions_expander(self, d):
        ex = Gtk.Expander()
        ex.add_css_class("entry-expander")
        ex.set_label_widget(hbox(8, icon("shield"), label(_("What it can reach"), ("body",))))
        box = vbox(12)
        box.set_margin_top(6)
        ex.set_child(box)
        started = {"yes": False}

        def opened(*_a):
            if not ex.get_expanded() or started["yes"]:
                return
            started["yes"] = True
            box.append(hbox(10, spinner(), label(_("Reading its permissions…"), ("small", "dim"))))
            run_bg(lambda: install_info.flatpak_permissions(d.package), lambda r: self._permissions(box, r))

        ex.connect("notify::expanded", opened)
        return ex

    def _permissions(self, box, perms):
        if not self._here():
            return
        clear(box)
        if isinstance(perms, Exception):
            box.append(label(str(perms), ("small", "error-text"), wrap=True))
            return
        box.append(label(_("Flatpak apps are shut off from the rest of the computer and reach only what's listed "
                           "here, including changes made with Flatseal. Those marked are worth a look."),
                         ("small", "dim"), wrap=True))
        groups = [("files", _("Files")), ("network", _("Network")), ("display", _("Display")),
                  ("sound", _("Sound")), ("devices", _("Devices")), ("other", _("Other"))]
        if not perms:
            box.append(label(_("Nothing outside its own sandbox."), ("body",)))
        for key, title in groups:
            mine = [x for x in perms if x.group == key]
            if not mine:
                continue
            row = WrapBox(6, 6)
            for x in mine:
                chip = label(x.text, ("small", "dep-chip") + (("dep-wide",) if x.wide else ()))
                if x.wide:
                    chip.set_tooltip_text(_("This reaches a lot. Fine if the app needs it; Flatseal can take it "
                                            "away."))
                row.append(chip)
            box.append(vbox(6, label(title, ("subheading",)), row))
        from .helpers_window import HelperActions, shortcuts_for
        win = self.get_root()
        flatseal = next((x for x in shortcuts_for(self.app, win._all_apps()) if x.key == "flatseal"), None) \
            if win is not None and hasattr(win, "_all_apps") else None
        if flatseal is not None:
            acts = HelperActions(win)
            text = _("Change in Flatseal") if flatseal.installed else _("Get Flatseal to change these")
            box.append(_start(button(text, "tune", "tonal", small=True, tooltip=flatseal.what,
                                     cb=lambda *_a: acts.open(flatseal))))

    def _deps_loaded(self, d):
        if not self._here():
            return
        clear(self.deps)
        if isinstance(d, Exception):
            self.deps.append(label(_("They couldn't be read: {error}").format(error=d), ("small", "dim"), wrap=True))
            return
        self._deps(d)

    def _deps(self, d):
        if d.kind == "flatpak":
            if d.depends:
                name = runtime_name(d.depends[0].name)
                size = f" ({GLib.format_size(d.runtime_size)})" if d.runtime_size else ""
                self.deps.append(label(_("Runtime: {runtime}{size}").format(runtime=name, size=size),
                                       ("subheading",), wrap=True))
                text = _("Flatpak apps don't use the libraries installed on your system. Each runs on a runtime: a "
                         "shared set of libraries, installed once for all the apps that need it.")
                if d.shared_with:
                    text += " " + ngettext(
                        "{n} other app uses this one too, so it stays when {name} is uninstalled.",
                        "{n} other apps use this one too, so it stays when {name} is uninstalled.",
                        d.shared_with).format(n=d.shared_with, name=self.app.name)
                else:
                    text += " " + _("Only {name} uses this one. After uninstalling {name}, “flatpak uninstall "
                                    "--unused” removes it too.").format(name=self.app.name)
                self.deps.append(label(text, ("small", "dim"), wrap=True))
                tech = label(d.depends[0].name, ("mono", "faint"))
                tech.set_selectable(True)
                self.deps.append(tech)
            return
        self._list(_("Needs"), [(x.name, x.installed, "") for x in d.depends],
                   _("Nothing listed."))
        self._list(_("Needed by"), [(n, True, "") for n in d.required_by],
                   _("Nothing installed needs it, so removing it breaks nothing else."))
        if d.optional:
            self._list(_("Optional extras"), [(x.name, x.installed, x.why) for x in d.optional], "")

    def _list(self, title, items, empty):
        head = label(f"{title} ({len(items)})" if items else title, ("subheading",))
        box = vbox(6, head)
        if not items:
            if empty:
                box.append(label(empty, ("small", "dim"), wrap=True))
            self.deps.append(box)
            return
        row = WrapBox(6, 6)
        for name, installed, why in items[:SHOWN]:
            chip = label(name, ("small", "dep-chip") + (() if installed else ("dep-missing",)))
            tip = why or ""
            if not installed:
                tip = (tip + "\n" if tip else "") + _("Not installed")
            chip.set_tooltip_text(tip or None)
            chip.set_selectable(True)
            row.append(chip)
        if len(items) > SHOWN:
            row.append(label(_("and {n} more").format(n=len(items) - SHOWN), ("small", "dim")))
        box.append(row)
        self.deps.append(box)


INSTALLERS = {
    "": _("Not from a package: copied, downloaded or built by hand"),
    "pipx": _("Installed with pipx, in its own Python environment"),
    "uv": _("Installed with uv, in its own Python environment"),
    "pip": _("Installed with pip, in its own Python environment"),
    "git": _("A copy of a git project (cloned and run from there)"),
}
HOW = {
    "pip": _("pip installed it from this project."),
    "pipx": _("pipx installed it from this project."),
    "uv": _("uv installed it from this project."),
    "git": _("Its folder is a git copy of this project."),
    "homepage": _("Its package names this project as its home."),
    "appimage": _("The AppImage says its updates come from this project."),
    "download": _("Your browser downloaded it from this project's releases."),
    "linked": _("You linked it to this project."),
    "updated": _("App Entries updated it from this project's releases."),
}


class GitHubPart(Gtk.Box):
    """The GitHub project an app comes from: check for a newer release and,
    for an AppImage, update it. Nothing is asked of GitHub until a button
    is pressed."""

    def __init__(self, app, d, src, still_here, win=None, key=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("card-inner")
        self.app, self.d, self.src, self._here = app, d, src, still_here
        self.win, self.key = win, key or app.id
        self.path = d.path
        self._stop = False
        self._show()
        if src is not None and win is not None and win.update_note(self.key):
            # The watch found a newer version: show it now (one page read, remembered for an hour).
            self._check()

    def _show(self):
        clear(self)
        src = self.src
        if src is None:
            self.append(label(_("Is it from a GitHub project? Link it, and App Entries can check for new releases "
                                "and update it."), ("body",), wrap=True))
            row = hbox(8)
            self.entry = Gtk.Entry(placeholder_text=_("owner/name, or the project's address"), hexpand=True)
            self.entry.connect("activate", lambda *_a: self._link())
            row.append(self.entry)
            row.append(button(_("Link"), "link", "tonal", small=True, cb=lambda *_a: self._link()))
            self.append(row)
            self.status = label("", ("small", "error-text"), wrap=True)
            self.status.set_visible(False)
            self.append(self.status)
            return
        head = hbox(10, icon("deployed_code"))
        text = vbox(0, label(_("GitHub: {project}").format(project=src.name), ("body", "subheading")),
                    label(HOW.get(src.how, ""), ("small", "dim"), wrap=True))
        text.set_hexpand(True)
        head.append(text)
        self.append(head)
        self.status = vbox(8)
        self.append(self.status)
        row = WrapBox(8, 8)
        self.check_btn = button(_("Check for updates"), "sync", "tonal", small=True,
                                tooltip=_("Asks GitHub for the project's latest release. Nothing about you is sent."),
                                cb=lambda *_a: self._check())
        row.append(self.check_btn)
        if self.d.update_cmd:
            # pip, pipx, uv or git update it themselves: run that, where you can see it.
            row.append(button(_("Update in terminal"), "terminal", "tonal", small=True,
                              tooltip=_("Runs this in your terminal:\n{cmd}").format(
                                  cmd=terminal.shown(self.d.update_cmd)),
                              cb=lambda *_a: self._run(self.d.update_cmd)))
        row.append(button(_("Project page"), "open_in_new", "text", small=True,
                          cb=lambda *_a: _open(src.page)))
        if src.how == "linked":
            row.append(button(_("Unlink"), "link_off", "text", small=True,
                              tooltip=_("Forget that it comes from this project"), cb=lambda *_a: self._unlink()))
        self.append(row)

    # -- linking --------------------------------------------------------------

    def _link(self):
        try:
            self.src = github_apps.link(self.app.id, self.entry.get_text())
        except (github_apps.GitHubError, OSError) as e:
            self.status.set_label(str(e))
            self.status.set_visible(True)
            return
        self._show()

    def _unlink(self):
        github_apps.unlink(self.app.id)
        self.src = github_apps.source_of(self.app.id, self.d.raw.get("update_info", ""), self.d.origin)
        self._show()

    # -- checking ---------------------------------------------------------------

    def _busy(self, text):
        clear(self.status)
        self.status.append(hbox(10, spinner(), label(text, ("small", "dim"))))

    def _check(self):
        self.check_btn.set_sensitive(False)
        self._busy(_("Asking GitHub…"))
        app_id, path, src, d = self.app.id, self.path, self.src, self.d
        if d.kind == "appimage":
            run_bg(lambda: github_apps.check(app_id, path, src), self._checked)
        else:
            run_bg(lambda: github_apps.check_version(src, d.version, d.manager if d.kind == "package" else ""),
                   self._checked)

    def _checked(self, r):
        if not self._here():
            return
        self.check_btn.set_sensitive(True)
        clear(self.status)
        if isinstance(r, Exception):
            self.status.append(label(str(r), ("small", "error-text"), wrap=True))
            return
        rel = r.release
        version = github_apps.version_in(rel.tag) or rel.tag
        if self.win is not None and hasattr(self.win, "check_result"):
            self.win.check_result(self.key, r.newer, version)
        if not r.newer:
            self.status.append(label(_("Up to date: {version} is the latest release.").format(version=version),
                                     ("body",), wrap=True))
            return
        title = _("Version {version} is out").format(version=version)
        if r.current:
            title += " " + _("(you have {current})").format(current=r.current)
        self.status.append(label(title, ("body", "subheading"), wrap=True))
        if rel.notes.strip():
            ex = Gtk.Expander(label=_("What's new"))
            ex.add_css_class("entry-expander")
            notes = label(_short(rel.notes), ("small",), wrap=True, chars=60)
            notes.set_selectable(True)
            ex.set_child(notes)
            self.status.append(ex)
        row = WrapBox(8, 8)
        if self.d.kind == "appimage" and r.asset is not None:
            row.append(button(_("Update to {version}").format(version=version), "download", "filled", small=True,
                              tooltip=_("Downloads {file} ({size}) next to the one you have, then points the "
                                        "launcher at it. The old file goes to the Trash, and Undo puts it back.")
                              .format(file=r.asset.name, size=GLib.format_size(r.asset.size)),
                              cb=lambda *_a: self._update(r)))
        elif self.d.kind == "appimage":
            self.status.append(label(_("This release has no AppImage for this computer, so it can't be updated "
                                       "from here."), ("small", "dim"), wrap=True))
        elif self.d.kind == "package" and r.asset is not None:
            row.append(button(_("Update to {version}").format(version=version), "download", "filled", small=True,
                              tooltip=_("Downloads {file} ({size}) to your Downloads folder, then installs it with "
                                        "{manager} in your terminal, where it asks for your password and shows what "
                                        "it does.").format(file=r.asset.name, size=GLib.format_size(r.asset.size),
                                                           manager=self.d.manager),
                              cb=lambda *_a: self._update_package(r)))
        elif self.d.kind == "package" and self.d.foreign and self.d.manager == "pacman":
            self.status.append(label(_("Your AUR helper updates it, for example with “paru -Syu” or “yay -Syu”."),
                                     ("small", "dim"), wrap=True))
        elif self.d.kind == "package":
            self.status.append(label(_("This release has no package file for this computer, so it can't be updated "
                                       "from here."), ("small", "dim"), wrap=True))
        elif self.d.update_cmd:
            row.append(button(_("Update in terminal"), "terminal", "filled", small=True,
                              tooltip=terminal.shown(self.d.update_cmd), cb=lambda *_a: self._run(self.d.update_cmd)))
        row.append(button(_("Release page"), "open_in_new", "text", small=True, cb=lambda *_a: _open(rel.url)))
        self.status.append(row)

    # -- updating ---------------------------------------------------------------

    def _update(self, r):
        import os
        clear(self.status)
        self.check_btn.set_sensitive(False)
        self._stop = False
        bar = Gtk.ProgressBar(hexpand=True)
        text = label(_("Downloading {file}…").format(file=r.asset.name), ("small", "dim"), ellipsize=True)
        stop = button(_("Stop"), style="text", small=True, cb=lambda *_a: self._cancel())
        self.status.append(text)
        self.status.append(hbox(10, bar, stop))
        folder = os.path.dirname(self.path)
        self._win = self.get_root()     # the update finishes even if you move to another app meanwhile

        def progress(done, total):
            def show():
                if total:
                    bar.set_fraction(min(1.0, done / total))
                    text.set_label(_("Downloading {file}: {done} of {total}").format(
                        file=r.asset.name, done=GLib.format_size(done), total=GLib.format_size(total)))
                else:
                    bar.pulse()
                return False
            GLib.idle_add(show)

        run_bg(lambda: github_apps.download(r.asset, folder, progress, cancelled=lambda: self._stop),
               lambda new: self._downloaded(r, new))

    def _cancel(self):
        self._stop = True

    def _run(self, commands):
        try:
            terminal.start(commands)
        except (terminal.NoTerminal, OSError) as e:
            clear(self.status)
            self.status.append(label(_("Couldn't open a terminal: {error}. Run this yourself:\n{cmd}").format(
                error=e, cmd=terminal.shown(commands)), ("small", "error-text"), wrap=True))
            return
        clear(self.status)
        self.status.append(label(_("Updating in your terminal. The page shows the new version once it's done."),
                                 ("small", "dim"), wrap=True))

    def _update_package(self, r):
        clear(self.status)
        self.check_btn.set_sensitive(False)
        self._stop = False
        bar = Gtk.ProgressBar(hexpand=True)
        text = label(_("Downloading {file}…").format(file=r.asset.name), ("small", "dim"), ellipsize=True)
        self.status.append(text)
        self.status.append(hbox(10, bar, button(_("Stop"), style="text", small=True, cb=lambda *_a: self._cancel())))

        def progress(done, total):
            GLib.idle_add(lambda: (bar.set_fraction(min(1.0, done / total)) if total else bar.pulse(), False)[1])

        def done(path):
            if not self._here():
                return
            self.check_btn.set_sensitive(True)
            if isinstance(path, Exception):
                clear(self.status)
                self.status.append(label(str(path), ("small", "error-text"), wrap=True))
                return
            self._run([_install_command(self.d.manager, path)])
        run_bg(lambda: github_apps.download(r.asset, _downloads(), progress, cancelled=lambda: self._stop), done)

    def _downloaded(self, r, new):
        import os
        if isinstance(new, Exception):
            if self._here():
                self.check_btn.set_sensitive(True)
                clear(self.status)
                self.status.append(label(str(new), ("small", "error-text"), wrap=True))
            return
        win = self._win
        version = github_apps.version_in(r.release.tag) or r.release.tag
        app_id, tag, name, project = self.app.id, r.release.tag, os.path.basename(new), self.src.name

        def done(ok):
            if ok:
                github_apps.remember_installed(app_id, tag, name, project)
                if self.win is not None:
                    self.win.updated(self.key)
            elif os.path.exists(new):
                os.remove(new)      # the launcher wasn't changed, so the download goes
        if self._here():
            self._busy(_("Putting it in place…"))
        win.use_newer(self.app, self.path, new,
                      message=lambda _n: _("{name} updated to {version}").format(name=self.app.name, version=version),
                      done=done, downloaded=True)


def _short(notes: str, lines: int = 14) -> str:
    """Release notes as plain text, cut to a few lines."""
    import re
    text = re.sub(r"<!--.*?-->", "", notes, flags=re.DOTALL)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[*_`#>]+", "", text)
    out = [l.rstrip() for l in text.splitlines() if l.strip()]
    return "\n".join(out[:lines]) + ("\n…" if len(out) > lines else "")


def _open(url):
    if url:
        Gio.AppInfo.launch_default_for_uri(url, None)


PLATFORMS = {"org.gnome.Platform": "GNOME", "org.kde.Platform": "KDE", "org.freedesktop.Platform": "Freedesktop",
             "io.elementary.Platform": "elementary", "org.gtk.Gtk3theme": "GTK theme"}


def runtime_name(ref: str) -> str:
    """"org.gnome.Platform/x86_64/50" in words: "GNOME Platform 50"."""
    parts = ref.split("/")
    rid, branch = parts[0], parts[-1] if len(parts) >= 3 else ""
    who = PLATFORMS.get(rid)
    if who is None:
        return ref
    return f"{who} Platform {branch}".strip()


def _install_command(manager: str, path: str) -> list:
    from .. import pkgmanagers
    return pkgmanagers.as_root([{"apt": "apt", "dnf": "dnf", "zypper": "zypper"}[manager], "install", path])


def _downloads() -> str:
    return GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) or GLib.get_home_dir()


def _start(w):
    w.set_halign(Gtk.Align.START)
    return w


def _run_terminal(widget, commands):
    try:
        terminal.start(commands)
    except (terminal.NoTerminal, OSError) as e:
        from .dialogs import Dialog
        Dialog(widget.get_root(), _("Couldn't open a terminal"), _("{error}. Run this yourself:\n{cmd}").format(
            error=e, cmd=terminal.shown(commands)), [("ok", _("Close"), "tonal")]).present()
