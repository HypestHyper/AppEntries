"""The Installation section at the bottom of an app's page: where it came
from, when, by whom, its size, and what it depends on.

The page opens without waiting: this section starts as a placeholder the
size of the finished card and fills in from a background thread. The
dependency lists are read only when they're opened. Answers are
remembered (install_info), so a page opened again fills in at once."""
from gettext import gettext as _
from gettext import ngettext

from gi.repository import GLib, Gtk, Pango

from .. import install_info
from .dialogs import run_bg
from .widgets import WrapBox, card, clear, hbox, icon, label, section, spinner, vbox

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
        if d.updates_from:
            add(_("Updates come from"), d.updates_from)
        if d.kind in ("package", "flatpak", "snap"):
            c.append(self._deps_expander(d))

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
