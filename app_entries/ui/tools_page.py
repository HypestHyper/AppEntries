"""The Tools tab: command-line tools in your home folder that have no menu
entry, from cargo, go, pipx, uv and npm, or put in ~/.local/bin by hand.
Only looked at; updating or removing one runs its own command in your
terminal, where you see what it does, and a file you put there yourself
goes to the Trash, with Undo."""
from gettext import gettext as _
from gettext import ngettext

from gi.repository import Gio, GLib, Gtk

from .. import cli_tools, terminal, trash
from .dialogs import Dialog, run_bg
from .widgets import Clamp, WrapBox, button, card, clear, hbox, icon, label, section, spinner, vbox

GLYPHS = {"cargo": "deployed_code", "go": "deployed_code", "pipx": "terminal", "uv": "terminal", "npm": "deployed_code",
          "file": "description"}
KIND_NAMES = {
    "cargo": _("Rust, installed with cargo"), "go": _("Go, installed with go install"),
    "pipx": _("Python, installed with pipx"), "uv": _("Python, installed with uv"),
    "npm": _("Node, installed with npm"), "file": _("Files in ~/.local/bin and ~/bin"),
}


class ToolsPage(Gtk.ScrolledWindow):
    def __init__(self, win):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.win = win
        page = vbox(0)
        page.set_margin_bottom(32)
        head = hbox(12, section(_("Command-line tools"),
                                _("Tools in your home folder that have no menu entry: installed with cargo, go, "
                                  "pipx, uv or npm, or put in ~/.local/bin yourself. Updating or removing one runs "
                                  "its own command in your terminal, so you see what it does.")))
        head.get_first_child().set_hexpand(True)
        refresh = button(icon_name="refresh", style="tonal", small=True, tooltip=_("Look again"),
                         cb=lambda *_a: self.reload())
        refresh.set_valign(Gtk.Align.END)
        refresh.set_margin_bottom(6)
        head.append(refresh)
        page.append(head)
        self.list = vbox(10)
        page.append(self.list)
        self.set_child(Clamp(page, 900))
        self.reload()

    def reload(self):
        clear(self.list)
        self.list.append(hbox(10, spinner(), label(_("Looking for tools…"), ("body", "dim"))))
        apps = [i.app for i in self.win.apps.items()] if hasattr(self.win, "apps") else []
        run_bg(lambda: cli_tools.scan(apps=apps), self._fill)

    def _fill(self, tools):
        clear(self.list)
        if isinstance(tools, Exception):
            self.list.append(label(str(tools), ("body", "error-text"), wrap=True))
            return
        if not tools:
            self.list.append(label(_("No command-line tools found in your home folder."), ("body", "dim")))
            return
        for kind, items in cli_tools.by_kind(tools):
            self.list.append(label(f"{KIND_NAMES[kind]} ({len(items)})", ("subheading",)))
            c = card()
            for t in items:
                c.append(self._row(t))
            self.list.append(c)

    def _row(self, t):
        title = hbox(8, label(t.name, ("body", "app-name"), ellipsize=True))
        if t.version:
            title.append(label(t.version, ("small", "dim")))
        bits = []
        if t.commands and t.commands != [t.name]:
            bits.append(ngettext("Adds {cmds}", "Adds {cmds}", len(t.commands)).format(cmds=", ".join(t.commands)))
        if t.github:
            bits.append(_("from GitHub: {project}").format(project=t.github))
        elif t.project:
            bits.append(_("from {where}").format(where=t.project))
        if t.size:
            bits.append(GLib.format_size(t.size))
        text = vbox(2, title, label(" · ".join(bits), ("small", "dim"), wrap=True))
        text.set_hexpand(True)
        row = hbox(12, icon(GLYPHS.get(t.kind, "terminal")), text)
        acts = WrapBox(6, 6)
        acts.set_halign(Gtk.Align.END)
        acts.set_valign(Gtk.Align.CENTER)
        if t.update:
            acts.append(button(_("Update"), "sync", "tonal", small=True,
                               tooltip=_("Runs this in your terminal:\n{cmd}").format(cmd=terminal.shown(t.update)),
                               cb=lambda *_a: self._terminal(t.update)))
        if t.github:
            acts.append(button(icon_name="open_in_new", style="text", small=True, tooltip=_("Project page"),
                               cb=lambda *_a: Gio.AppInfo.launch_default_for_uri(
                                   f"https://github.com/{t.github}", None)))
        acts.append(button(icon_name="delete", style="text", small=True,
                           tooltip=(_("Runs this in your terminal:\n{cmd}").format(cmd=terminal.shown(t.remove))
                                    if t.remove else _("Moves {path} to the Trash. Undo puts it back.").format(
                                        path=", ".join(t.trash))),
                           cb=lambda *_a: self._remove(t)))
        row.append(acts)
        row.add_css_class("tool-row")
        return row

    def _terminal(self, commands):
        try:
            terminal.start(commands)
        except (terminal.NoTerminal, OSError) as e:
            Dialog(self.win, _("Couldn't open a terminal"), _("{error}. Run this yourself:\n{cmd}").format(
                error=e, cmd=terminal.shown(commands)), [("ok", _("Close"), "tonal")]).present()

    def _remove(self, t):
        what = (_("Runs this in your terminal:\n{cmd}").format(cmd=terminal.shown(t.remove)) if t.remove else
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
                self.reload()

        Dialog(self.win, _("Remove {name}?").format(name=t.name), what,
               [("cancel", _("Keep it"), "tonal"), ("remove", _("Remove"), "danger")], answer,
               icon_name="delete", icon_class="error-text").present()
