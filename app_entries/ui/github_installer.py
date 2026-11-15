"""Install from GitHub: paste a project's link, pick a version and a file,
and App Entries installs it the way that kind of file is installed. An
AppImage or app archive opens the usual launcher form afterwards (filled in
from the app itself); a package or Flatpak bundle, or a project with only
source code, installs in your terminal, where you see everything it does."""
import os
from gettext import gettext as _

from gi.repository import Gio, GLib, Gtk

from .. import github_apps, github_install, importers, pkgmanagers, terminal
from .dialogs import run_bg
from .widgets import WrapBox, button, card, clear, hbox, label, section, spinner, switch_row, vbox

KIND_GLYPH = {"appimage": "deployed_code", "archive": "folder_zip", "package": "inventory_2",
              "flatpak": "deployed_code", "source": "terminal"}


def _manager() -> str:
    found = pkgmanagers.detect()
    return found[0].name if found else ""


class GitHubInstaller(Gtk.Window):
    def __init__(self, win, start_text=""):
        super().__init__(transient_for=win, modal=True, title=_("Install from GitHub"))
        self.win = win
        self.add_css_class("prefs")
        self.set_default_size(640, 760)
        self.project = None
        self.rels = []
        self.choice = None
        self._stop = False
        hb = Gtk.HeaderBar()
        hb.set_show_title_buttons(False)
        hb.set_title_widget(label(_("Install from GitHub"), ("title",)))
        cancel = button(_("Cancel"), style="tonal", small=True, cb=lambda *_a: self._cancel())
        self.go = button(_("Install"), style="filled", small=True, cb=lambda *_a: self._install())
        self.go.set_sensitive(False)
        hb.pack_start(cancel)
        hb.pack_end(self.go)
        self.set_titlebar(hb)

        page = vbox(14)
        for m in ("start", "end", "bottom"):
            getattr(page, f"set_margin_{m}")(20)
        page.append(label(_("Paste a project's link from GitHub. App Entries reads its releases and suggests the "
                            "file that fits this computer. Nothing is downloaded until you press Install."),
                          ("body", "dim"), wrap=True, chars=60))
        self.entry = Gtk.Entry(placeholder_text=_("github.com/owner/name, or owner/name"), hexpand=True)
        self.entry.set_text(start_text)
        self.entry.connect("activate", lambda *_a: self._look())
        page.append(hbox(8, self.entry, button(_("Look"), "search", "tonal", small=True, cb=lambda *_a: self._look())))
        self.body = vbox(14)
        page.append(self.body)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroll.set_child(page)
        self.set_child(scroll)
        if start_text:
            GLib.idle_add(lambda: (self._look(), False)[1])

    # -- the project ----------------------------------------------------------

    def _busy(self, box, text):
        clear(box)
        box.append(hbox(10, spinner(), label(text, ("small", "dim"))))

    def _look(self):
        text = self.entry.get_text().strip()
        if not text:
            return
        self.go.set_sensitive(False)
        self._busy(self.body, _("Reading the project…"))

        def work():
            p = github_install.fetch(text)
            return p, github_install.releases(p, include_test=True)
        run_bg(work, self._found)

    def _found(self, r):
        clear(self.body)
        if isinstance(r, Exception):
            self.body.append(label(str(r), ("body", "error-text"), wrap=True))
            return
        self.project, self.rels = r
        p = self.project
        head = card()
        head.append(label(p.name, ("title",), wrap=True))
        if p.description:
            head.append(label(p.description, ("body",), wrap=True, chars=60))
        links = WrapBox(8, 8)
        links.append(button(_("Project page"), "open_in_new", "text", small=True,
                            cb=lambda *_a: Gio.AppInfo.launch_default_for_uri(p.url, None)))
        head.append(links)
        if p.archived:
            head.append(label(_("Its owner has archived this project: it doesn't get updates any more."),
                              ("small", "warn-text"), wrap=True))
        head.append(label(_("This is software from the internet. Install it only if you trust {owner}. When the "
                            "release lists checksums, the download is checked against them.").format(owner=p.owner),
                          ("small", "dim"), wrap=True, chars=60))
        self.body.append(head)

        self.body.append(section(_("Version")))
        self.versions = Gtk.DropDown()
        self.versions.connect("notify::selected", lambda *_a: self._pick_version())
        self.test = False
        row, self.test_switch = switch_row(_("Include test versions"), False, self._toggle_test)
        vc = card()
        vc.append(self.versions)
        vc.append(row)
        self.notes = vbox(4)
        vc.append(self.notes)
        self.body.append(vc)

        self.body.append(section(_("How to install it")))
        self.ways = vbox(8)
        self.body.append(self.ways)
        self.progress = vbox(6)
        self.body.append(self.progress)
        self._fill_versions()

    def _shown_rels(self):
        return [r for r in self.rels if self.test or not github_install.is_test(r)]

    def _toggle_test(self, on):
        self.test = on
        self._fill_versions()

    def _fill_versions(self):
        rels = self._shown_rels()
        names = [r.tag + (f" · {r.published[:10]}" if r.published else "") +
                 (_(" (test version)") if github_install.is_test(r) else "") for r in rels]
        if not names:
            names = [_("No releases: install from its code")]
        self.versions.set_model(Gtk.StringList.new(names))
        self.versions.set_selected(0)
        self._pick_version()

    # -- the version and its files --------------------------------------------

    def _pick_version(self):
        rels = self._shown_rels()
        i = self.versions.get_selected()
        rel = rels[i] if rels and 0 <= i < len(rels) else None
        clear(self.notes)
        if rel is not None and rel.notes.strip():
            ex = Gtk.Expander(label=_("What's new"))
            ex.add_css_class("entry-expander")
            n = label(rel.notes.strip()[:2000], ("small",), wrap=True, chars=60)
            n.set_selectable(True)
            ex.set_child(n)
            self.notes.append(ex)
        self.choice = None
        self.go.set_sensitive(False)
        self._busy(self.ways, _("Reading its files…"))
        p = self.project

        def work():
            found = []
            if rel is not None:
                github_install.files(p, rel)
                found = github_install.choices(rel, _manager())
            return rel, found, github_install.from_source(p)
        run_bg(work, self._show_ways)

    def _show_ways(self, r):
        clear(self.ways)
        if isinstance(r, Exception):
            self.ways.append(label(str(r), ("small", "error-text"), wrap=True))
            return
        self.rel, found, source = r
        group = None
        first = None
        c = card()
        if not found:
            c.append(label(_("This release has no file for this computer, so it can be installed from its code:")
                           if self.rel is not None else _("It has no releases, so it can be installed from its "
                                                         "code:"), ("small", "dim"), wrap=True))
        for n, ch in enumerate(found + source):
            if found and n == len(found):
                c.append(label(_("Or from its code"), ("subheading",)))
            check = Gtk.CheckButton()
            if group is None:
                group = check
            else:
                check.set_group(group)
            title = hbox(8, label(ch.title, ("body", "app-name")))
            if ch.asset is not None:
                title.append(label(ch.asset.name + (f" · {GLib.format_size(ch.asset.size)}" if ch.asset.size else ""),
                                   ("small", "dim"), ellipsize=True))
            why = ch.why + ("" if not ch.commands else "\n" + terminal.shown(ch.commands))
            text = vbox(2, title, label(why, ("small", "dim") if ch.fits else ("small", "faint"), wrap=True,
                                        chars=56))
            text.set_hexpand(True)
            row = hbox(10, check, text)
            row.set_sensitive(ch.fits)
            check.connect("toggled", lambda b, ch=ch: b.get_active() and self._choose(ch))
            c.append(row)
            if first is None and ch.fits:
                first = check
        self.ways.append(c)
        if first is not None:
            first.set_active(True)

    def _choose(self, ch):
        self.choice = ch
        self.go.set_sensitive(True)
        self.go.set_label(_("Install in terminal") if ch.kind in ("package", "flatpak", "source") else _("Install"))

    # -- installing ---------------------------------------------------------------

    def _cancel(self):
        self._stop = True
        self.close()

    def _install(self):
        if getattr(self, "_done", False):
            self.close()
            return
        ch = self.choice
        if ch is None:
            return
        if ch.kind == "source":
            self._terminal(ch.commands)
            return
        self.go.set_sensitive(False)
        bar = Gtk.ProgressBar(hexpand=True)
        text = label(_("Downloading {file}…").format(file=ch.asset.name), ("small", "dim"), ellipsize=True)
        clear(self.progress)
        self.progress.append(text)
        self.progress.append(bar)
        if ch.kind == "appimage":
            folder = importers.applications_dir()
        elif ch.kind == "archive":
            folder = os.path.join(GLib.get_user_cache_dir(), "app-entries", "downloads")
        else:
            folder = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD) or GLib.get_home_dir()
        os.makedirs(folder, exist_ok=True)
        rel, p = self.rel, self.project

        def progress(done, total):
            GLib.idle_add(lambda: (bar.set_fraction(min(1.0, done / total)) if total else bar.pulse(), False)[1])

        def work():
            path = github_apps.download(ch.asset, folder, progress, cancelled=lambda: self._stop)
            sums = github_install.checksum_asset(rel, ch.asset.name)
            checked = None
            if sums is not None:
                checked = github_install.verify(path, ch.asset.name, github_install.fetch_text(sums))
                if checked is False:
                    os.remove(path)
                    raise github_apps.GitHubError(_("The download doesn't match the checksum the release lists, so "
                                                    "it was deleted. Nothing was installed."))
            if ch.kind == "archive":
                try:
                    target = github_install.unpack(path, importers.applications_dir(), p.repo)
                finally:
                    os.remove(path)
                github_install.mark_origin(target, ch.asset.url)
                path = target
            return path, checked
        run_bg(work, self._downloaded)

    def _downloaded(self, r):
        clear(self.progress)
        if isinstance(r, Exception):
            self.go.set_sensitive(True)
            self.progress.append(label(str(r), ("small", "error-text"), wrap=True))
            return
        path, checked = r
        ch = self.choice
        if ch.kind in ("appimage", "archive"):
            # The usual form for an AppImage or app folder, filled in from the app itself.
            from . import importing
            self.close()
            importing.start(self.win, "appimage" if ch.kind == "appimage" else "folder", path)
            return
        if ch.kind == "package":
            from .install_section import _install_command
            cmd = ([pkgmanagers.as_root(["pacman", "-U", path])] if path.endswith(".pkg.tar.zst")
                   else [_install_command(_manager(), path)])
        else:
            cmd = [["flatpak", "install", "--user", path]]
        note = _("Checked against the release's checksum.") if checked else ""
        self._terminal(cmd, note)

    def _terminal(self, commands, note=""):
        try:
            terminal.start(commands)
        except (terminal.NoTerminal, OSError) as e:
            clear(self.progress)
            self.progress.append(label(_("Couldn't open a terminal: {error}. Run this yourself:\n{cmd}").format(
                error=e, cmd=terminal.shown(commands)), ("small", "error-text"), wrap=True))
            return
        clear(self.progress)
        self.progress.append(label(((note + " ") if note else "") + _(
            "Installing in your terminal. App Entries lists it once it's done."), ("small", "dim"), wrap=True))
        self._done = True
        self.go.set_label(_("Close"))
        self.go.set_sensitive(True)
