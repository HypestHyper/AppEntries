"""The Tools tab: command-line tools that have no menu entry. Ones in your
home folder (from cargo, go, pipx, uv and npm, or put in ~/.local/bin by
hand) and terminal programs you installed with your package manager.

The list is on the left; a tool's page opens beside it (or instead of it in
a narrow window) with what it is, its commands, where it came from and what
it depends on. Only looked at: updating or removing one runs its own
command in your terminal, where you see what it does, and a file you put
there yourself goes to the Trash, with Undo."""
import os
import shlex
from gettext import gettext as _
from gettext import ngettext

from gi.repository import Gdk, Gio, GLib, Gtk

from .. import cli_tools, terminal, trash
from .. import desktop_entries as de
from .dialogs import Dialog, run_bg
from .widgets import WrapBox, button, card, clear, hbox, icon, label, long_text, section, spinner, vbox

GLYPHS = {"cargo": "deployed_code", "go": "deployed_code", "pipx": "terminal", "uv": "terminal", "npm": "deployed_code",
          "file": "description"}
KIND_NAMES = {
    "cargo": _("Rust, installed with cargo"), "go": _("Go, installed with go install"),
    "pipx": _("Python, installed with pipx"), "uv": _("Python, installed with uv"),
    "npm": _("Node, installed with npm"), "file": _("Files in ~/.local/bin and ~/bin"),
}
for _k in cli_tools.SYSTEM_KINDS:
    KIND_NAMES[_k] = _("Installed with {manager}").format(manager=cli_tools.KINDS[_k])
    GLYPHS[_k] = "inventory_2"
ABOUT_GROUP = {
    "file": _("Your own command folders. Anything here runs by name in a terminal, for you only: scripts you "
              "wrote, programs downloaded as a single file, or ones an installer put here."),
}
for _k in cli_tools.SYSTEM_KINDS:
    ABOUT_GROUP[_k] = _("Terminal programs you installed that have no menu entry. They update with the rest of "
                        "the system; Remove uninstalls one in your terminal.")
LIST_WIDTH = 460


class ToolsPage(Gtk.Box):
    def __init__(self, win):
        super().__init__(spacing=16)
        self.win = win
        self.tools = []
        self.current = None
        self._kinds = [""]
        self._gen = 0

        # The list: search, a group filter and the tools.
        left = vbox(10)
        head = hbox(8)
        self.search = Gtk.SearchEntry(placeholder_text=_("Search tools"), hexpand=True)
        self.search.connect("search-changed", lambda *_a: self._filter())
        head.append(self.search)
        refresh = button(icon_name="refresh", style="tonal", small=True, tooltip=_("Look again"),
                         cb=lambda *_a: self.reload())
        refresh.set_valign(Gtk.Align.CENTER)
        head.append(refresh)
        left.append(head)
        row = hbox(8)
        self.groups = Gtk.DropDown()
        self.groups.set_hexpand(True)
        self.groups.connect("notify::selected", lambda *_a: self._filter())
        row.append(self.groups)
        row.append(button(_("Add from GitHub…"), "cloud_download", "tonal", small=True,
                          tooltip=_("Paste a project's link: installs a tool with the command its code uses"),
                          cb=lambda *_a: self._add_from_github()))
        left.append(row)
        self.summary = label("", ("small", "dim"), wrap=True)
        left.append(self.summary)
        self.list = vbox(10)
        self.list.set_margin_bottom(32)
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroll.set_child(self.list)
        left.append(scroll)
        self.left = left
        self.append(left)

        # A tool's page.
        self.detail = vbox(14)
        self.detail.set_margin_bottom(32)
        self.detail.set_margin_end(12)
        self.right = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, hexpand=True)
        self.right.set_child(self.detail)
        self.append(self.right)
        self._empty_detail()
        self._layout()
        self.reload()

    # -- narrow or wide -----------------------------------------------------------

    def _narrow(self):
        return bool(getattr(self.win, "_narrow", False))

    def _layout(self):
        narrow = self._narrow()
        showing = self.current is not None
        self.left.set_visible(not narrow or not showing)
        self.right.set_visible(not narrow or showing)
        self.left.set_hexpand(narrow)
        self.left.set_size_request(-1 if narrow else LIST_WIDTH, -1)

    # -- the list -------------------------------------------------------------------

    def reload(self):
        clear(self.list)
        self.list.append(hbox(10, spinner(), label(_("Looking for tools…"), ("body", "dim"))))
        apps = [i.app for i in self.win.apps.items()] if hasattr(self.win, "apps") else []
        run_bg(lambda: cli_tools.scan(apps=apps, system=True), self._loaded)

    def _loaded(self, tools):
        if isinstance(tools, Exception):
            clear(self.list)
            self.list.append(label(str(tools), ("body", "error-text"), wrap=True))
            return
        self.tools = tools
        kinds = [k for k, _items in cli_tools.by_kind(tools)]
        self._kinds = [""] + kinds
        self.groups.set_model(Gtk.StringList.new([_("All groups")] + [KIND_NAMES[k] for k in kinds]))
        self.groups.set_selected(0)
        if self.current is not None:
            again = next((t for t in tools if (t.kind, t.name) == (self.current.kind, self.current.name)), None)
            if again is not None:
                self.show(again)
            else:
                self.close_tool()
        self._filter()
        self._layout()

    def _filter(self):
        clear(self.list)
        q = self.search.get_text().strip().casefold()
        i = self.groups.get_selected()
        kind = self._kinds[i] if 0 <= i < len(self._kinds) else ""
        shown = [t for t in self.tools if (not q or q in t.search_text) and (not kind or t.kind == kind)]
        total = sum(t.size for t in shown)
        self.summary.set_label(ngettext("{n} tool", "{n} tools", len(shown)).format(n=len(shown)) +
                               (" · " + GLib.format_size(total) if total else ""))
        if not shown:
            self.list.append(label(_("No tools match.") if (q or kind) else
                                   _("No command-line tools found."), ("body", "dim")))
            return
        for k, items in cli_tools.by_kind(shown):
            size = sum(t.size for t in items)
            count = f"{len(items)}" + (f" · {GLib.format_size(size)}" if size else "")
            self.list.append(label(f"{KIND_NAMES[k]} ({count})", ("subheading",)))
            if k in ABOUT_GROUP:
                self.list.append(label(ABOUT_GROUP[k], ("small", "dim"), wrap=True, chars=50))
            c = card()
            for t in items:
                c.append(self._row(t))
            self.list.append(c)

    def _row(self, t):
        title = hbox(8, label(t.name, ("body", "app-name"), ellipsize=True))
        if t.version:
            title.append(label(t.version, ("small", "dim"), ellipsize=True))
        bits = [t.description] if t.description else []
        if t.size:
            bits.append(GLib.format_size(t.size))
        text = vbox(2, title, label(" · ".join(bits), ("small", "dim"), ellipsize=True))
        text.set_hexpand(True)
        row = hbox(12, icon(GLYPHS.get(t.kind, "terminal")), text, icon("chevron_right", ("faint",)))
        row.add_css_class("tool-row")
        if self.current is not None and (t.kind, t.name) == (self.current.kind, self.current.name):
            row.add_css_class("is-current")
        click = Gtk.GestureClick()
        click.connect("released", lambda *_a: self.show(t))
        row.add_controller(click)
        row.set_cursor(Gdk.Cursor.new_from_name("pointer", None))
        return row

    # -- a tool's page ----------------------------------------------------------------

    def _empty_detail(self):
        clear(self.detail)
        e = vbox(10, icon("terminal", ("big", "empty-icon")), label(_("Choose a tool"), ("title",), xalign=0.5),
                 label(_("What it is, its commands, where it came from and what it depends on show here."),
                       ("body", "dim"), wrap=True, xalign=0.5, chars=40))
        e.set_margin_top(120)
        e.set_halign(Gtk.Align.CENTER)
        self.detail.append(e)

    def close_tool(self):
        self.current = None
        self._empty_detail()
        self._layout()
        self._filter()

    def show(self, t):
        self.current = t
        self._gen += 1
        gen = self._gen
        clear(self.detail)
        if self._narrow():
            back = button(_("Back to Tools"), "arrow_back", "tonal", small=True, cb=lambda *_a: self.close_tool())
            back.add_css_class("back-button")
            back.set_halign(Gtk.Align.START)
            self.detail.append(back)
        self.detail.append(self._head(t))
        what = self._what(t)
        if what is not None:
            self.detail.append(what)
        self.detail.append(self._commands(t))
        fake = _as_app(t)
        if fake is not None:
            from .install_section import InstallSection
            self.detail.append(InstallSection(fake, lambda: gen == self._gen))
        self.right.get_vadjustment().set_value(0)
        self._layout()
        self._filter()

    def _head(self, t):
        box = vbox(12)
        box.add_css_class("page-head")
        tile = hbox(0, icon(GLYPHS.get(t.kind, "terminal"), ("big",)))
        tile.add_css_class("icon-tile")
        tile.set_valign(Gtk.Align.START)
        sub = KIND_NAMES.get(t.kind, t.kind) + (f" · {t.version}" if t.version else "") + \
            (f" · {GLib.format_size(t.size)}" if t.size else "")
        text = vbox(2, label(t.name, ("title", "page-title"), wrap=True), label(sub, ("small", "dim"), wrap=True))
        if t.description:
            text.append(label(t.description, ("body",), wrap=True, chars=50))
        text.set_hexpand(True)
        box.append(hbox(16, tile, text))
        acts = WrapBox(8, 8)
        if t.update:
            acts.append(button(_("Update"), "sync", "tonal", small=True,
                               tooltip=_("Runs this in your terminal:\n{cmd}").format(cmd=terminal.shown(t.update)),
                               cb=lambda *_a: self._terminal(t.update)))
        folder = t.folder or (os.path.dirname(os.path.realpath(t.paths[0])) if t.paths else "")
        if folder and os.path.isdir(folder):
            acts.append(button(_("Open folder"), "folder_open", "tonal", small=True, tooltip=folder,
                               cb=lambda *_a: _open_uri(Gio.File.new_for_path(folder).get_uri())))
        if t.kind == "file" and t.paths and cli_tools.describe_file(os.path.realpath(t.paths[0]))[2]:
            acts.append(button(_("Open in text editor"), "edit_note", "tonal", small=True,
                               cb=lambda *_a: _edit(os.path.realpath(t.paths[0]))))
        if t.github:
            acts.append(button(_("Project page"), "open_in_new", "text", small=True,
                               cb=lambda *_a: _open_uri(f"https://github.com/{t.github}")))
        acts.append(button(_("Remove…"), "delete", "danger", small=True, cb=lambda *_a: self._remove(t)))
        box.append(acts)
        return box

    def _what(self, t):
        """For a file of your own: what kind it is, and the start of a script."""
        if t.kind != "file" or not t.paths:
            return None
        real = os.path.realpath(t.paths[0])
        kind, comment, lines = cli_tools.describe_file(real)
        box = vbox(0, section(_("What it is")))
        c = card()
        c.append(label(kind, ("body",)))
        if comment:
            c.append(label(comment, ("body", "dim"), wrap=True))
        if real != t.paths[0]:
            c.append(label(_("A link to {path}").format(path=_short(real)), ("small", "dim"), wrap=True))
        if lines:
            c.append(vbox(2, label(_("How it starts"), ("small", "dim")), long_text("\n".join(lines))))
        box.append(c)
        return box

    def _commands(self, t):
        box = vbox(0, section(ngettext("Its command", "Its commands", len(t.commands)),
                              _("Type these in a terminal to use it. Help opens its manual, or its own --help.")))
        c = card()
        paths = t.paths if len(t.paths) == len(t.commands) else [""] * len(t.commands)
        for name, path in list(zip(t.commands, paths))[:40]:
            text = vbox(0, label(name, ("mono", "body")))
            if path:
                p = label(_short(path), ("mono", "faint"), wrap=True)
                p.set_selectable(True)
                text.append(p)
            text.set_hexpand(True)
            c.append(hbox(12, text, button(_("Help"), "help", "text", small=True,
                                           tooltip=_("Opens its manual in your terminal, or its --help if it has no "
                                                     "manual"), cb=lambda *_a, n=name: self._help(n))))
        if len(t.commands) > 40:
            c.append(label(_("And {n} more.").format(n=len(t.commands) - 40), ("small", "dim")))
        box.append(c)
        return box

    # -- actions --------------------------------------------------------------------------

    def _help(self, cmd):
        q = shlex.quote(cmd)
        script = f"man {q} 2>/dev/null || {{ {q} --help 2>&1 || {q} -h 2>&1; }} | ${{PAGER:-less}}"
        self._terminal([["sh", "-c", script]])

    def _add_from_github(self):
        from .github_installer import GitHubInstaller
        dlg = GitHubInstaller(self.win)
        dlg.connect("close-request", lambda *_a: (GLib.timeout_add_seconds(2, lambda: (self.reload(), False)[1]),
                                                  False)[1])
        dlg.present()

    def _terminal(self, commands):
        try:
            terminal.start(commands)
        except (terminal.NoTerminal, OSError) as e:
            Dialog(self.win, _("Couldn't open a terminal"), _("{error}. Run this yourself:\n{cmd}").format(
                error=e, cmd=terminal.shown(commands)), [("ok", _("Close"), "tonal")]).present()

    def _remove(self, t):
        what = ((_("Runs this in your terminal, where it asks for your password and shows what else would go "
                   "before anything changes:\n{cmd}") if t.needs_password else
                 _("Runs this in your terminal:\n{cmd}")).format(cmd=terminal.shown(t.remove)) if t.remove else
                _("Moves {path} to the Trash. Undo puts it back.").format(path=", ".join(t.trash)))

        def answer(resp):
            if resp != "remove":
                return
            if t.remove:
                self._terminal(t.remove)
                return
            moved = []
            for p in t.trash:
                try:
                    moved.append(trash.move(p))
                except trash.TrashError as e:
                    Dialog(self.win, _("Couldn't remove {name}").format(name=t.name), str(e),
                           [("ok", _("Close"), "tonal")]).present()
                    break
            if moved:
                self.win._record(_("Removed the command {name}").format(name=t.name), [], moved)
                self.current = None
                self.reload()

        Dialog(self.win, _("Remove {name}?").format(name=t.name), what,
               [("cancel", _("Keep it"), "tonal"), ("remove", _("Remove"), "danger")], answer,
               icon_name="delete", icon_class="error-text").present()


def _as_app(t):
    """The tool as an app with no menu entry, so its page shows the same
    Installation details (package, date, dependencies, GitHub) as an app's."""
    if not t.paths:
        return None
    path = t.paths[0]
    system = t.kind in cli_tools.SYSTEM_KINDS
    return de.App(id=f"tool:{t.kind}:{t.name}", name=t.name, exec=shlex.quote(path),
                  base_path=path if system else "", system=system, source="system" if system else "user")


def _short(path):
    home = GLib.get_home_dir()
    return "~" + path[len(home):] if path.startswith(home + "/") else path


def _open_uri(uri):
    try:
        Gio.AppInfo.launch_default_for_uri(uri, None)
    except GLib.Error:
        pass


def _edit(path):
    info = Gio.AppInfo.get_default_for_type("text/plain", False)
    if info is not None:
        try:
            info.launch([Gio.File.new_for_path(path)], None)
        except GLib.Error:
            pass
