"""The Edit window: change an app's launcher entry, every field explained.
Nothing is written until Save is pressed."""
import os
from gettext import gettext as _

from gi.repository import Gdk, Gtk

from .. import editing, health, launchers, overrides, symbols
from .app_card import gicon_for
from .dialogs import choose_icon_file
from .entry_view import EntryView
from .icon_picker import IconPicker, preview_texture
from .widgets import Group, Toggle, WrapBox, button, card, hbox, label, section, vbox


def _field(title, explanation, widget):
    """A titled field with a sentence under it saying what it does."""
    box = vbox(6, label(title, ("body", "option-title")), widget,
               label(explanation, ("small", "dim"), wrap=True, chars=60))
    return box


def _entry(text, placeholder="", mono=False):
    e = Gtk.Entry(text=text, placeholder_text=placeholder, hexpand=True)
    if mono:
        e.add_css_class("mono")
    return e


def _switch_field(title, explanation, active, cb):
    sw = Toggle(active, cb)
    sw.update_property([Gtk.AccessibleProperty.LABEL], [title])
    head = hbox(12, label(title, ("body", "option-title")), sw)
    head.get_first_child().set_hexpand(True)
    return vbox(4, head, label(explanation, ("small", "dim"), wrap=True, chars=60)), sw


def _chips(options, selected):
    box = WrapBox(6, 6)
    buttons = {}
    for key, text in options:
        b = Gtk.ToggleButton(label=text, active=key in selected)
        b.add_css_class("filter")
        box.append(b)
        buttons[key] = b
    return box, buttons


class EditWindow(Gtk.Window):
    def __init__(self, parent, app, on_save, glyph_color="#888888", highlight=None):
        super().__init__(transient_for=parent, modal=True,
                         title=_("Edit {name}").format(name=app.name))
        self.add_css_class("prefs")
        self.set_default_size(620, 720)
        self.app = app
        self._on_save = on_save
        self._glyph = glyph_color
        self.original = editing.read_fields(app)
        f = self.original

        hb = Gtk.HeaderBar()
        hb.set_show_title_buttons(False)
        hb.set_title_widget(label(_("Edit {name}").format(name=app.name), ("title",), ellipsize=True))
        cancel = button(_("Cancel"), style="tonal", small=True, cb=lambda *_: self.close())
        self.save = button(_("Save"), style="filled", small=True, cb=self._save)
        for b in (cancel, self.save):
            b.set_valign(Gtk.Align.CENTER)
        hb.pack_start(cancel)
        hb.pack_end(self.save)
        self.set_titlebar(hb)

        page = vbox(0)
        page.set_margin_start(20)
        page.set_margin_end(20)
        page.set_margin_bottom(24)

        # Shown in launchers
        c = card()
        c.set_margin_top(12)
        box, self.hidden = _switch_field(
            _("Hidden from launcher"),
            _("Keeps it out of launcher menus. It still opens files and links as before. Saved with your other "
              "changes when you press Save."), f.hidden, lambda _v: self._changed())
        c.append(box)
        page.append(c)

        # Name and description
        page.append(section(_("Name and description"), _("What launchers show for this app.")))
        c = card()
        self.name = _entry(f.name)
        c.append(_field(_("Name"), _("The app's name in launchers and menus."), self.name))
        self.generic = _entry(f.generic_name, _("For example: Web Browser"))
        c.append(_field(_("Kind of app"), _("A short description of what kind of app it is. Some launchers show it "
                                            "under the name or search it."), self.generic))
        self.comment = _entry(f.comment)
        c.append(_field(_("Description"), _("A longer description, often shown as a tooltip."), self.comment))
        self.keywords = _entry(", ".join(f.keywords), _("For example: browser, internet, web"))
        c.append(_field(_("Search words"), _("Extra words that find this app when you search a launcher, "
                                             "separated by commas."), self.keywords))
        page.append(c)

        # Icon
        page.append(section(_("Icon")))
        c = card()
        self.preview = Gtk.Image(pixel_size=48, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        tile = Gtk.Box(valign=Gtk.Align.CENTER)
        tile.add_css_class("icon-tile")
        tile.append(self.preview)
        self.icon = _entry(f.icon, _("An icon name or an image file"), mono=True)
        self.icon.set_valign(Gtk.Align.CENTER)
        choose = button(_("File…"), "folder_open", "tonal", self._choose_icon, small=True,
                        tooltip=_("Use an image file"))
        material = button(_("Styled…"), "palette", "tonal", self._pick_material, small=True,
                          tooltip=_("A Material Symbol or one of your own icons, with your tile, colour and border"))
        for b in (choose, material):
            b.set_valign(Gtk.Align.CENTER)
        c.append(_field(_("Icon"), _("An icon name from your icon theme, like firefox, or an image file. File… "
                                     "copies the image to your icon library first, so it stays safe. Styled… draws "
                                     "a Material Symbol or one of your icons with a tile, colour and border, saved "
                                     "when you press Save."),
                        hbox(12, tile, self.icon, material, choose)))
        self.picked = None
        page.append(c)

        # Command
        page.append(section(_("Command")))
        c = card()
        self.command = _entry(f.command, mono=True)
        c.append(_field(_("Command"), _("What runs when you open the app. Codes like %U and %F are replaced by the "
                                        "files or links you open it with."), self.command))
        self.command_warning = label("", ("small", "warn-text"), wrap=True, chars=60)
        c.append(self.command_warning)
        self.env = Gtk.TextView(accepts_tab=False, wrap_mode=Gtk.WrapMode.CHAR, top_margin=8, bottom_margin=8,
                                left_margin=10, right_margin=10)
        self.env.add_css_class("mono")
        self.env.add_css_class("textarea")
        self.env.get_buffer().set_text("\n".join(f.env))
        self.env.set_size_request(-1, 64)
        c.append(_field(_("Environment variables"), _("Settings passed to this app only, one per line, like "
                                                      "GDK_SCALE=2 or GTK_THEME=Adwaita:dark."), self.env))
        box, self.terminal = _switch_field(
            _("Run in a terminal"), _("Opens a terminal window and runs the command in it. For command-line "
                                      "programs."), f.terminal, lambda _v: self._changed())
        c.append(box)
        box, self.gpu = _switch_field(
            _("Use the dedicated graphics card"), _("On computers with two graphics cards, asks to start the app "
                                                    "on the more powerful one."), f.prefers_gpu, lambda _v: self._changed())
        c.append(box)
        self.wm_class = _entry(f.wm_class, mono=True)
        c.append(_field(_("Window class"), _("Lets docks and taskbars match the app's windows to this entry. "
                                             "Only change it if a running app shows a generic icon."), self.wm_class))
        page.append(c)

        # Where it appears
        current = editing.current_desktops()
        here = ", ".join(current) if current else _("unknown")
        page.append(section(_("Where it appears")))
        c = card()
        cats, self.cat_buttons = _chips([(k, _(n)) for k, n in editing.MAIN_CATEGORIES], f.categories)
        c.append(_field(_("Menu folders"), _("The folders it's listed in, for launchers that sort apps into "
                                             "folders. Apps can be in more than one."), cats))
        self.show_in = Group([("all", _("Every desktop")), ("only", _("Only these")),
                              ("except", _("All except these"))], f.show_in, lambda _v: self._changed())
        known = [k for k, _n in editing.DESKTOPS]
        options = list(editing.DESKTOPS) + [(d, d) for d in current + f.desktops if d not in known]
        options = list(dict(options).items())
        desks, self.desk_buttons = _chips(options, f.desktops)
        c.append(_field(_("Desktops"), _("Some desktops and launchers only show apps meant for them. Choose "
                                         "where this app is listed. Your current desktop: {desktop}.")
                        .format(desktop=here), vbox(10, self.show_in, desks)))
        page.append(c)

        # Quick actions
        self.action_switches = []
        if f.actions:
            page.append(section(_("Quick actions"), _("Extra commands in the app's right-click menu in some "
                                                      "launchers and docks. Turn one off to leave it out.")))
            c = card()
            for a in f.actions:
                sw = Toggle(a.enabled, lambda _v: self._changed())
                sw.update_property([Gtk.AccessibleProperty.LABEL], [a.name])
                row = hbox(12, label(a.name, ("body",)), sw)
                row.get_first_child().set_hexpand(True)
                c.append(row)
                self.action_switches.append((a, sw))
            page.append(c)

        # The file itself
        page.append(section(_("The entry file"), _("Launchers read this file. It updates as you make changes; "
                                                    "highlighted lines are what Save changes.")))
        self.code = EntryView(_("Each line is a key and its value. Everything above is a friendlier way to "
                                "change these lines."))
        if highlight is not None:
            self.code.set_colors(highlight)
        c = card()
        c.append(self.code)
        page.append(c)
        self._current_text = editing.preview(app, f)

        self.problems = label("", ("small", "error-text"), wrap=True, chars=60)
        self.problems.set_margin_top(12)
        page.append(self.problems)
        where = app.override_path or os.path.join("~/.local/share/applications", app.id)
        page.append(label(_("Saving writes your own copy of this entry to {path}. Restore original in the card's "
                            "menu puts the system version back.").format(path=where) if app.system and
                          not app.override_path else
                          _("Saving changes {path}. You can undo it right after.").format(path=where),
                          ("small", "faint"), wrap=True, chars=60))

        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroll.set_child(page)
        self.set_child(scroll)

        for e in (self.name, self.generic, self.comment, self.keywords, self.icon, self.command, self.wm_class):
            e.connect("changed", lambda *_: self._changed())
        self.env.get_buffer().connect("changed", lambda *_: self._changed())
        for b in list(self.cat_buttons.values()) + list(self.desk_buttons.values()):
            b.connect("toggled", lambda *_: self._changed())

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
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

    def fields(self):
        buf = self.env.get_buffer()
        env_text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        actions = [editing.Action(a.id, a.name, sw.get_active()) for a, sw in self.action_switches]
        return editing.Fields(
            name=self.name.get_text(),
            generic_name=self.generic.get_text(),
            comment=self.comment.get_text(),
            keywords=[k.strip() for k in self.keywords.get_text().split(",") if k.strip()],
            icon=self.icon.get_text().strip(),
            command=self.command.get_text(),
            env=[line.strip() for line in env_text.splitlines() if line.strip()],
            terminal=self.terminal.get_active(),
            prefers_gpu=self.gpu.get_active(),
            wm_class=self.wm_class.get_text().strip(),
            categories=[k for k, b in self.cat_buttons.items() if b.get_active()],
            show_in=self.show_in.active() or "all",
            desktops=[k for k, b in self.desk_buttons.items() if b.get_active()],
            actions=actions,
            hidden=self.hidden.get_active(),
        )

    def _changed(self):
        f = self.fields()
        problems = editing.validate(f)
        self.problems.set_label(" ".join(_(p) for p in problems))
        self.problems.set_visible(bool(problems))
        self.save.set_sensitive(not problems)
        self.code.show(editing.preview(self.app, f), self._current_text)
        if self.picked is not None and f.icon == self._picked_path():
            self.preview.set_from_paintable(preview_texture(self.picked, 48))
        else:
            self.preview.set_from_gicon(gicon_for(f.icon))
        program = health.program_of(f.command)
        if program and not health.is_installed(program, os.environ):
            self.command_warning.set_label(_("{program} wasn't found in your PATH or the usual program folders. "
                                             "You can still save it.").format(program=program))
            self.command_warning.set_visible(True)
        else:
            self.command_warning.set_visible(False)

    def _picked_path(self):
        return launchers.icon_path(launchers.PREFIX + "icon-" + self.app.id)

    def _pick_material(self, *_):
        def picked(choice):
            self.picked = choice
            self.icon.set_text(self._picked_path())
            self.preview.set_from_paintable(preview_texture(choice, 48))

        current = self.icon.get_text().strip()
        previous = None
        if os.path.isabs(current) and current.endswith(".svg"):
            # An icon App Entries drew before opens with the same settings.
            try:
                previous = symbols.choice_from_svg(overrides.read_text(current) or "")
            except overrides.OverrideError:
                previous = None
        start = self.picked or previous or symbols.IconChoice("apps", "outlined", "rounded", "#2e9e7e")
        IconPicker(self, start, picked, self._glyph).present()

    def _choose_icon(self, *_args):
        current = self.icon.get_text()
        choose_icon_file(self, self.icon.set_text, start=os.path.dirname(current) if os.path.isabs(current) else None)

    def _save(self, *_):
        fields = self.fields()
        if editing.validate(fields):
            return
        if self.picked is not None and fields.icon == self._picked_path():
            self._on_save(self.app, fields, self.picked)
        else:
            self._on_save(self.app, fields, None)
        self.close()
