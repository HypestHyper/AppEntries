"""Make or change a launcher for a script or program. Every option is
explained, and nothing is written until Create (or Save) is pressed."""
import os
from gettext import gettext as _

from gi.repository import Gdk, Gtk

from .. import desktop_entries as de
from .. import editing, launchers, symbols
from .app_card import gicon_for
from .dialogs import choose_file, choose_icon_file
from .entry_view import EntryView
from .icon_picker import IconPicker, preview_texture
from .widgets import Group, Toggle, WrapBox, button, card, hbox, label, section, set_text, vbox


def _explained(title, explanation, widget):
    return vbox(6, label(title, ("body", "option-title")), widget,
                label(explanation, ("small", "dim"), wrap=True, chars=60))


def _switch(title, explanation, active, cb):
    sw = Toggle(active, cb)
    sw.update_property([Gtk.AccessibleProperty.LABEL], [title])
    head = hbox(12, label(title, ("body", "option-title")), sw)
    head.get_first_child().set_hexpand(True)
    box = vbox(4, head, label(explanation, ("small", "dim"), wrap=True, chars=60))
    return box, sw


def _entry(text="", placeholder="", mono=False):
    e = Gtk.Entry(text=text, placeholder_text=placeholder, hexpand=True)
    if mono:
        e.add_css_class("mono")
    return e


class LauncherWindow(Gtk.Window):
    """on_save(did_or_None, spec, make_executable) for the form, or
    on_save_raw(did, name, text) for Advanced mode."""

    def __init__(self, parent, on_save, on_save_raw, did=None, text=None, glyph_color="#888888", highlight=None):
        editing_existing = did is not None
        super().__init__(transient_for=parent, modal=True,
                         title=_("Edit launcher") if editing_existing else _("New launcher"))
        self.add_css_class("prefs")
        self.set_default_size(760, 860)
        self.did = did
        self._on_save = on_save
        self._on_save_raw = on_save_raw
        self._glyph = glyph_color
        self._highlight = highlight
        self._original_text = text
        spec = launchers.read_spec(text) if text else None
        self.spec = spec or launchers.Spec()
        if not text:
            self.spec.icon = symbols.IconChoice("terminal", "outlined", "rounded", "#2e9e7e")
        if self.spec.kind == "program" and self.spec.args.strip():
            # One field now: older launchers' arguments join the program.
            self.spec.program = (self.spec.program.strip() + " " + self.spec.args.strip()).strip()
            self.spec.args = ""
        self._frames = []   # (frame, text view, header label, remove button) for each set of commands

        hb = Gtk.HeaderBar()
        hb.set_show_title_buttons(False)
        self.title = label(self.get_title(), ("title",))
        hb.set_title_widget(self.title)
        cancel = button(_("Cancel"), style="tonal", small=True, cb=lambda *_: self.close())
        self.save = button(_("Save") if editing_existing else _("Create"), style="filled", small=True,
                           cb=self._save)
        self.advanced = Gtk.ToggleButton(label=_("Advanced"))
        self.advanced.add_css_class("small")
        self.advanced.set_tooltip_text(_("Edit the entry file's text directly"))
        self.advanced.connect("toggled", self._on_mode)
        for b in (cancel, self.save, self.advanced):
            b.set_valign(Gtk.Align.CENTER)
        hb.pack_start(cancel)
        hb.pack_end(self.save)
        hb.pack_end(self.advanced)
        self.set_titlebar(hb)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=150)
        self.stack.add_named(self._build_form(), "form")
        self.stack.add_named(self._build_raw(), "raw")
        self.set_child(self.stack)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        if text and spec is None:
            # Changed by hand: the form can't show it, so open the text.
            self.raw.get_buffer().set_text(text)
            self.advanced.set_active(True)
            self.raw_note.set_label(_("This launcher was changed by hand, so it opens as text. Save keeps it "
                                      "exactly as written, after a check."))
        self._changed()

    # -- form ---------------------------------------------------------------

    def _build_form(self):
        s = self.spec
        page = vbox(0)
        page.set_margin_start(20)
        page.set_margin_end(20)
        page.set_margin_bottom(24)

        # Preview of how it'll look in a launcher
        self.prev_icon = Gtk.Image(pixel_size=48, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.prev_name = label("", ("heading",), ellipsize=True)
        self.prev_comment = label("", ("small", "dim"), ellipsize=True)
        prev_text = vbox(2, self.prev_name, self.prev_comment)
        prev_text.set_valign(Gtk.Align.CENTER)
        prev_text.set_hexpand(True)
        prev = hbox(14, self.prev_icon, prev_text)
        prev.add_css_class("card-inner")
        prev.set_margin_top(12)
        page.append(prev)

        # What it runs
        page.append(section(_("What it runs")))
        c = card()
        self.kind = Group([("program", _("A program or script"), "deployed_code"),
                           ("commands", _("Commands"), "terminal")], s.kind, lambda _v: self._kind_changed())
        c.append(_explained(_("Kind"), _("A program or script file runs as it is. Commands are written as in a "
                                         "terminal and run by a shell: several in a row (paru -Syu && flatpak "
                                         "update), pipes, loops, a whole script."), self.kind))

        # A program or script
        self.program = _entry(s.program, _("htop --tree, or ~/bin/backup.sh --quick"), mono=True)
        choose = button(_("Choose…"), "folder_open", "tonal", self._choose_program, small=True)
        choose.set_valign(Gtk.Align.CENTER)
        self.program_box = vbox(10)
        self.program_box.append(_explained(
            _("Program or script"), _("The file to run, or a command on your PATH, with anything that goes after "
                                      "it. Quote paths or words with spaces. Scripts need to be executable."),
            hbox(10, self.program, choose)))
        self.status = label("", ("small",), wrap=True, chars=60)
        self.as_commands = button(_("Run it as commands"), "terminal", "tonal", small=True,
                                  cb=lambda *_a: self._to_commands())
        self.as_commands.set_halign(Gtk.Align.START)
        self.program_box.append(self.status)
        self.program_box.append(self.as_commands)
        self.exec_box, self.make_exec = _switch(
            _("Make it executable when saving"),
            _("The file isn't marked as runnable yet. With this on, App Entries marks it executable (like chmod +x) "
              "when you press Create. That step isn't undone by Undo."), True, lambda _v: self._changed())
        self.program_box.append(self.exec_box)
        c.append(self.program_box)

        # Commands
        shells = launchers.available_shells()
        if s.shell not in shells:
            shells.append(s.shell)
        self.shell = Group([(n, n) for n in shells], s.shell, lambda _v: self._changed())
        self.frames = vbox(10)
        add = button(_("Add commands in another terminal"), "add", "tonal", small=True,
                     cb=lambda *_a: (self._add_frame(""), self._changed()))
        add.set_halign(Gtk.Align.START)
        self.commands_box = vbox(10, _explained(
            _("Shell"), _("What runs the commands. sh is on every system; the others are listed when they're "
                          "installed."), self.shell),
            label(_("Commands"), ("body", "option-title")), self.frames, add,
            label(_("Written as in a terminal, one or more lines. Each set opens in its own terminal when there's "
                    "more than one. They're kept in a small script file the launcher runs, so they work in any "
                    "launcher."), ("small", "dim"), wrap=True, chars=60))
        for text in (s.commands or [""]):
            self._add_frame(text)
        c.append(self.commands_box)
        self.workdir = _entry(s.workdir, _("Your home folder"), mono=True)
        pick_dir = button(_("Choose…"), "folder_open", "tonal", self._choose_folder, small=True)
        pick_dir.set_valign(Gtk.Align.CENTER)
        c.append(_explained(_("Working folder"), _("The folder it starts in. Leave empty for your home folder."),
                            hbox(10, self.workdir, pick_dir)))
        box, self.files = _switch(_("Pass files opened with it"),
                                  _("Files you open with the launcher (from a file manager's Open With, or by "
                                    "dropping them on it) are added as arguments. Commands get them as \"$@\" "
                                    "($argv in fish)."), s.accepts_files,
                                  lambda _v: self._changed())
        c.append(box)
        page.append(c)

        # How it runs
        page.append(section(_("How it runs")))
        c = card()
        box, self.terminal = _switch(_("Run in a terminal"),
                                     _("Opens a terminal window and runs it there, so you can see its output and "
                                       "type into it. Turn off for programs with their own window."),
                                     s.terminal, lambda _v: self._changed())
        c.append(box)
        box, self.hidden = _switch(_("Hidden from launcher"),
                                   _("Keeps it out of launcher menus while you're not using it. You can still "
                                     "find it here under My launchers."), s.hidden, lambda _v: self._changed())
        self.keep_box, self.keep_open = _switch(
            _("Keep the terminal open when it finishes"),
            _("Waits for you to press Enter before closing, and shows whether it succeeded, so you can read the "
              "output."), s.keep_open, lambda _v: self._changed())
        c.append(self.keep_box)
        self.several_note = label(_("With commands in more than one terminal, each set opens in its own "
                                    "terminal."), ("small", "dim"), wrap=True, chars=60)
        c.append(self.several_note)
        c.append(box)
        page.append(c)

        # Name and menu
        page.append(section(_("Name and menu")))
        c = card()
        self.name = _entry(s.name, _("For example: Back up photos"))
        c.append(_explained(_("Name"), _("What launchers show and what you search for."), self.name))
        self.comment = _entry(s.comment, _("Optional"))
        c.append(_explained(_("Description"), _("A short line about what it does, often shown as a tooltip."),
                            self.comment))
        cats = WrapBox(6, 6)
        self.cat_buttons = {}
        for key, text in editing.MAIN_CATEGORIES:
            b = Gtk.ToggleButton(label=_(text), active=key in s.categories)
            b.add_css_class("filter")
            b.connect("toggled", lambda *_: self._changed())
            cats.append(b)
            self.cat_buttons[key] = b
        c.append(_explained(_("Menu folders"), _("Where it's listed in launchers that sort apps into folders."),
                            cats))
        self.keywords = _entry(", ".join(s.keywords), _("Optional, separated by commas"))
        c.append(_explained(_("Search words"), _("Extra words that find it when you search a launcher."),
                            self.keywords))
        page.append(c)

        # Icon
        page.append(section(_("Icon")))
        c = card()
        self.icon_kind = Group([("symbol", _("Styled icon")), ("theme", _("Icon name or file"))],
                               "symbol" if s.icon_kind == "symbol" else "theme", lambda _v: self._changed())
        c.append(_explained(_("Kind"), _("A styled icon is a Material Symbol or one of your own icons, drawn "
                                         "with your tile, colour and border, and saved as a file every launcher "
                                         "can show. Or use an icon name from your icon theme, or an image file "
                                         "as it is (it's copied to your icon library first)."), self.icon_kind))
        self.icon_tile = Gtk.Image(pixel_size=56, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.pick = button(_("Choose icon…"), "palette", "tonal", self._pick_icon, small=True)
        self.pick.set_valign(Gtk.Align.CENTER)
        self.icon_name = label("", ("small", "dim"))
        self.symbol_row = hbox(14, self.icon_tile, vbox(4, self.pick, self.icon_name))
        c.append(self.symbol_row)
        self.icon_value = _entry(s.icon_value, _("For example: utilities-terminal, or /path/to/icon.svg"), mono=True)
        self.icon_value.connect("changed", lambda *_: self._changed())
        pick_file = button(_("Choose file…"), "folder_open", "tonal", self._choose_icon_file, small=True)
        pick_file.set_valign(Gtk.Align.CENTER)
        self.theme_row = hbox(10, self.icon_value, pick_file)
        c.append(self.theme_row)
        page.append(c)

        page.append(section(_("The entry file"), _("Launchers read this file. It updates as you fill in the "
                                                    "form. When you edit a launcher, highlighted lines are "
                                                    "what Save changes.")))
        self.code = EntryView(_("Each line is a key and its value. Advanced (at the top) lets you edit "
                                "this text directly."))
        if self._highlight is not None:
            self.code.set_colors(self._highlight)
        c = card()
        c.append(self.code)
        page.append(c)

        self.problems = label("", ("small", "error-text"), wrap=True, chars=60)
        self.problems.set_margin_top(12)
        page.append(self.problems)
        where = os.path.join("~/.local/share/applications", self.did or launchers.PREFIX + "….desktop")
        page.append(label(_("Saved as {path}. A Material icon is saved next to your other icons, in "
                            "~/.local/share/icons. You can undo right after.").format(path=where),
                          ("small", "faint"), wrap=True, chars=60))

        for e in (self.program, self.workdir, self.name, self.comment, self.keywords):
            e.connect("changed", lambda *_: self._changed())
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroll.set_child(page)
        return scroll

    def _add_frame(self, text):
        view = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=10, bottom_margin=10,
                            left_margin=12, right_margin=12, accepts_tab=False)
        view.add_css_class("textarea")
        view.get_buffer().set_text(text)
        view.get_buffer().connect("changed", lambda *_a: self._changed())
        view.update_property([Gtk.AccessibleProperty.LABEL], [_("Commands")])
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, min_content_height=150,
                                    max_content_height=420, propagate_natural_height=True)
        scroll.set_child(view)
        head = label("", ("small", "option-title"))
        head.set_hexpand(True)
        remove = button(icon_name="close", style="text", small=True, tooltip=_("Remove these commands"))
        frame = vbox(6, hbox(8, head, remove), scroll)
        entry = (frame, view, head, remove)
        remove.connect("clicked", lambda *_a: self._remove_frame(entry))
        self._frames.append(entry)
        self.frames.append(frame)
        view.grab_focus()

    def _remove_frame(self, entry):
        if len(self._frames) > 1:
            self._frames.remove(entry)
            self.frames.remove(entry[0])
            self._changed()

    def _commands(self):
        out = []
        for _f, view, _h, _r in self._frames:
            buf = view.get_buffer()
            out.append(buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False))
        return out

    def _kind_changed(self):
        # Commands like paru -Syu need a terminal to ask for a password and
        # show what they do, so a new launcher starts with one.
        if self.kind.active() == "commands" and self.did is None and not self.terminal.get_active():
            self.terminal.set_active(True)
            self.keep_open.set_active(True)
        self._changed()

    def _to_commands(self):
        """Move what's in the program field into the commands."""
        text = self.program.get_text().strip()
        first = self._frames[0][1].get_buffer()
        if not first.get_text(first.get_start_iter(), first.get_end_iter(), False).strip():
            first.set_text(text)
        self.kind.set_active("commands")
        self._kind_changed()

    def _build_raw(self):
        page = vbox(10)
        for side in ("start", "end"):
            getattr(page, "set_margin_" + side)(20)
        page.set_margin_bottom(20)
        page.set_margin_top(8)
        self.raw_note = label(_("Edit the entry file directly, for keys the form doesn't cover. It's checked "
                                "before saving. A launcher changed here opens as text next time."),
                              ("small", "dim"), wrap=True, chars=70)
        page.append(self.raw_note)
        self.raw = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.CHAR, top_margin=10, bottom_margin=10,
                                left_margin=12, right_margin=12, vexpand=True)
        self.raw.add_css_class("textarea")
        self.raw.get_buffer().connect("changed", lambda *_: self._changed())
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(self.raw)
        page.append(scroll)
        self.raw_check = label("", ("small",), wrap=True, chars=70, xalign=0)
        self.raw_check.set_selectable(True)
        page.append(self.raw_check)
        return page

    # -- state --------------------------------------------------------------

    def form_spec(self):
        kind = self.icon_kind.active() or "symbol"
        return launchers.Spec(
            name=self.name.get_text(),
            comment=self.comment.get_text(),
            kind=self.kind.active() or "program",
            program=self.program.get_text(),
            commands=self._commands(),
            shell=self.shell.active() or "sh",
            workdir=self.workdir.get_text(),
            terminal=self.terminal.get_active() or (self.kind.active() == "commands" and len(self._frames) > 1),
            keep_open=(self.terminal.get_active() or len(self._frames) > 1) and self.keep_open.get_active(),
            accepts_files=self.files.get_active(),
            categories=[k for k, b in self.cat_buttons.items() if b.get_active()],
            keywords=[k.strip() for k in self.keywords.get_text().split(",") if k.strip()],
            icon_kind=kind,
            icon=self.spec.icon,
            icon_value="" if kind == "symbol" else self.icon_value.get_text().strip(),
            hidden=self.hidden.get_active(),
        )

    def _raw_text(self):
        buf = self.raw.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _changed(self):
        if self.advanced.get_active():
            errors, warnings = launchers.check_raw(self._raw_text())
            lines = [_("Can't save: {e}").format(e=e) for e in errors] + [_("Note: {w}").format(w=w) for w in warnings]
            self.raw_check.set_label("\n".join(lines) if lines else _("The entry looks good."))
            for cls in ("error-text", "accent"):
                self.raw_check.remove_css_class(cls)
            self.raw_check.add_css_class("error-text" if errors else "accent")
            self.save.set_sensitive(not errors)
            return
        spec = self.form_spec()
        is_commands = spec.kind == "commands"
        self.program_box.set_visible(not is_commands)
        self.commands_box.set_visible(is_commands)
        several = len(self._frames) > 1
        for n, (_f, _v, head, remove) in enumerate(self._frames, 1):
            set_text(head, _("Terminal {n}").format(n=n) if several else "")
            head.set_visible(several)
            remove.set_visible(several)
        shell_syntax = not is_commands and launchers.uses_shell_syntax(spec.program) and \
            not os.path.exists(os.path.expanduser(spec.program.strip()))
        self.as_commands.set_visible(shell_syntax)
        status = launchers.program_status(spec.program)
        msg = {
            "ok": _("Found, and executable."),
            "command": _("Found as a command on your PATH."),
            "not-executable": _("Found, but not marked executable."),
            "missing": _("Not found yet. Check the path.") if spec.program.strip() else "",
        }[status]
        set_text(self.status, msg)
        for cls in ("accent", "warn-text", "error-text"):
            self.status.remove_css_class(cls)
        self.status.add_css_class({"ok": "accent", "command": "accent", "not-executable": "warn-text"}
                                  .get(status, "error-text"))
        if shell_syntax:
            set_text(self.status, _("This is more than one command, or uses shell syntax like && or |, which only "
                                    "a shell understands. Run as a program, it would all go to the first one as "
                                    "arguments."))
            for cls in ("accent", "warn-text"):
                self.status.remove_css_class(cls)
            self.status.add_css_class("error-text")
            msg = "x"
        self.status.set_visible(bool(msg))
        self.exec_box.set_visible(status == "not-executable" and not is_commands)
        several_terminals = is_commands and len([c for c in spec.commands if c.strip()]) > 1
        self.several_note.set_visible(several_terminals)
        self.terminal.set_sensitive(not several_terminals)
        self.keep_box.set_sensitive(self.terminal.get_active() or several_terminals)
        is_symbol = spec.icon_kind == "symbol"
        self.symbol_row.set_visible(is_symbol)
        self.theme_row.set_visible(not is_symbol)

        if is_symbol:
            tex = preview_texture(spec.icon, 56)
            self.icon_tile.set_from_paintable(tex)
            self.prev_icon.set_from_paintable(preview_texture(spec.icon, 48))
            set_text(self.icon_name, os.path.basename(spec.icon.path) if spec.icon.source == "file"
                     else spec.icon.name.replace("_", " "))
        else:
            self.prev_icon.set_from_gicon(gicon_for(spec.icon_value or "application-x-executable"))
        set_text(self.prev_name, spec.name.strip() or _("Launcher name"))
        set_text(self.prev_comment, spec.comment.strip() or (
            (spec.commands[0].strip().splitlines() or [" "])[0] if is_commands
            else os.path.basename(spec.program.strip()) or " "))

        problems = launchers.problems(spec)
        try:
            text = launchers.build_entry(spec, self.did or launchers.new_id(spec.name or "launcher"))
        except ValueError:
            text = self._original_text or ""
        # A new launcher is all new, so nothing is marked.
        self.code.show(text, self._original_text if self.did else None)
        set_text(self.problems, " ".join(_(p) for p in problems))
        self.problems.set_visible(bool(problems))
        self.save.set_sensitive(not problems)

    def _on_mode(self, toggle):
        if toggle.get_active():
            if not self._raw_text().strip():
                try:
                    text = launchers.build_entry(self.form_spec(), self.did or launchers.new_id(
                        self.name.get_text() or "launcher"))
                except ValueError:
                    text = ""
                self.raw.get_buffer().set_text(text)
            self.stack.set_visible_child_name("raw")
        else:
            self.stack.set_visible_child_name("form")
        self._changed()

    def _on_key(self, _c, keyval, _code, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if keyval in (Gdk.KEY_s, Gdk.KEY_S) and state & Gdk.ModifierType.CONTROL_MASK:
            if self.save.get_sensitive():
                self._save()
            return True
        return False

    # -- pickers ------------------------------------------------------------

    def _pick_icon(self, *_):
        def picked(choice):
            self.spec.icon = choice
            self._changed()
        IconPicker(self, self.spec.icon, picked, self._glyph).present()

    def _open_file(self, title, cb, folder=False, patterns=None, start=None):
        choose_file(self, title, cb, folder=folder, patterns=patterns, start=start)

    def _choose_program(self, *_args):
        def chosen(path):
            self.program.set_text(path)
            if not self.name.get_text().strip():
                base = os.path.splitext(os.path.basename(path))[0]
                self.name.set_text(base.replace("-", " ").replace("_", " ").strip().capitalize())
        current = os.path.expanduser(self.program.get_text().strip())
        self._open_file(_("Choose a script or program"), chosen,
                        start=os.path.dirname(current) if os.path.isabs(current) else None)

    def _choose_folder(self, *_args):
        self._open_file(_("Choose the working folder"), self.workdir.set_text, folder=True)

    def _choose_icon_file(self, *_args):
        choose_icon_file(self, self.icon_value.set_text)

    # -- save ---------------------------------------------------------------

    def _save(self, *_args):
        if not self.save.get_sensitive():
            return
        if self.advanced.get_active():
            text = self._raw_text()
            name = de.unescape(de.DesktopFile(text).group_dict().get("Name", "")) or _("Launcher")
            did = self.did or launchers.new_id(name)
            self._on_save_raw(did, name, text)
        else:
            spec = self.form_spec()
            make_exec = (self.exec_box.get_visible() and self.make_exec.get_active())
            self._on_save(self.did, spec, make_exec)
        self.close()
