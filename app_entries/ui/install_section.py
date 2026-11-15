"""The Installation section at the bottom of an app's page: where it came
from, when, by whom, its size, and what it depends on.

The page opens without waiting: this section starts as a placeholder the
size of the finished card and fills in from a background thread. The
dependency lists are read only when they're opened. Answers are
remembered (install_info), so a page opened again fills in at once."""
from gettext import gettext as _
from gettext import ngettext

from gi.repository import Gio, GLib, Gtk, Pango

from .. import github_apps, install_info
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

    def __init__(self, app, still_here):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self._here = still_here
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
        if d.note:
            c.append(label(NOTES[d.note].format(box=d.package), ("body",), wrap=True))
            return
        grid = WrapBox(28, 14)
        c.append(grid)

        def add(title, value, mono=False, tip=None):
            if not value:
                return None
            v = label(value, ("mono",) if mono else ("body",), wrap=not mono, ellipsize=mono, chars=34)
            if mono:
                v.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            v.set_selectable(True)
            v.set_tooltip_text(tip or (value if mono else None))
            grid.append(vbox(2, label(title, ("small", "dim")), v))
            return v

        if d.kind == "package":
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
            if d.kind == "file":
                add(_("From"), _("Not from a package: copied, downloaded or built by hand"))
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
        if d.size:
            add(_("Size"), GLib.format_size(d.size))
        if d.origin:
            add(_("Downloaded from"), d.origin, mono=True)
        src = None
        if d.kind in ("appimage", "file"):
            src = github_apps.source_of(self.app.id, d.raw.get("update_info", ""), d.origin)
        if d.updates_from and src is None:
            add(_("Updates come from"), d.updates_from)
        if d.kind in ("package", "flatpak", "snap"):
            c.append(self._deps_expander(d))
        if d.kind in ("appimage", "file") and (src is not None or d.kind == "appimage"):
            c.append(GitHubPart(self.app, d, src, self._here))

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
                text = _("Runs on {runtime}.").format(runtime=d.depends[0].name)
                if d.shared_with:
                    text += " " + ngettext("{n} other app uses it too.", "{n} other apps use it too.",
                                           d.shared_with).format(n=d.shared_with)
                self.deps.append(label(text, ("body",), wrap=True))
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


HOW = {
    "appimage": _("The AppImage says its updates come from this project."),
    "download": _("Your browser downloaded it from this project's releases."),
    "linked": _("You linked it to this project."),
    "updated": _("App Entries updated it from this project's releases."),
}


class GitHubPart(Gtk.Box):
    """The GitHub project an app comes from: check for a newer release and,
    for an AppImage, update it. Nothing is asked of GitHub until a button
    is pressed."""

    def __init__(self, app, d, src, still_here):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("card-inner")
        self.app, self.d, self.src, self._here = app, d, src, still_here
        self.path = d.path
        self._stop = False
        self._show()

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
        app_id, path, src = self.app.id, self.path, self.src
        run_bg(lambda: github_apps.check(app_id, path, src), self._checked)

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
