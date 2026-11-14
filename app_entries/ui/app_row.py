"""One app in the list: its icon, name and description, with badges only for
what needs saying. Hidden apps carry a crossed-out eye; on the row you point
at or move to, an eye button hides or shows the app. Right-click for the
rest of its options."""
from gettext import gettext as _

from gi.repository import Gdk, Gtk, Pango

from .. import APP_ID
from .app_card import Badge, gicon_later, menu_box
from .widgets import glyph, icon, label, set_text, vbox


class AppRow(Gtk.Box):
    """Shows one AppItem. `on_toggle(item, hidden)` hides or shows it,
    `on_action(item, name)` runs a menu action. While `selecting()` is
    true, a click selects the row instead."""

    def __init__(self, on_toggle, on_action, selecting=lambda: False, current=lambda: None):
        super().__init__(spacing=12)
        self.add_css_class("app-row")
        self.add_css_class("no-copy")   # a click opens the app, it doesn't select text
        self._current = current
        self._on_toggle = on_toggle
        self._on_action = on_action
        self._selecting = selecting
        self.item = None
        self._handler = 0
        self._icon_name = None
        self._pointer = False

        self.check = Gtk.CheckButton(valign=Gtk.Align.CENTER, visible=False)
        self.check.set_can_target(False)  # the whole row takes the click
        self.check.set_focusable(False)
        self.image = Gtk.Image(pixel_size=32, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        tile = Gtk.Box(valign=Gtk.Align.CENTER)
        tile.add_css_class("icon-tile")
        tile.add_css_class("small-tile")
        tile.append(self.image)

        self.name = label("", ("body", "app-name"), ellipsize=True)
        self.name.set_hexpand(False)
        self.new_badge = Badge("auto_awesome", _("New"), "custom",
                               _("Appeared since App Entries last looked. Marked until you close App Entries."))
        self.custom_badge = Badge("edit_note", _("Customised"), "custom",
                                  _("Changed from the version its package installed."))
        self.missing_badge = Badge("link_off", _("Missing program"), "error")
        self.gone_badge = Badge("inventory_2", _("Uninstalled"), "error",
                                _("The app was uninstalled, but your edited copy of its entry is still here."))
        self.nodisplay_badge = Badge("bedtime", _("Not in menus"), "neutral",
                                     _("Its package asks for it to be left out of menus (NoDisplay)."))
        top = Gtk.Box(spacing=8)
        top.append(self.name)
        for b in (self.new_badge, self.custom_badge, self.missing_badge, self.gone_badge, self.nodisplay_badge):
            b.add_css_class("row-badge")
            top.append(b)
        self.desc = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.desc.add_css_class("small")
        self.desc.add_css_class("dim")
        text = vbox(1, top, self.desc)
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)

        # Hide or show: always there for hidden apps (it says they're hidden),
        # and on the row you point at or move to for the others.
        self.eye = Gtk.Button(valign=Gtk.Align.CENTER)
        self.eye.add_css_class("flat")
        self.eye.add_css_class("circle")
        self.eye.add_css_class("row-eye")
        self.eye_glyph = icon("visibility_off")
        self.eye.set_child(self.eye_glyph)
        self.eye.connect("clicked", self._eye_clicked)

        for w in (self.check, tile, text, self.eye):
            self.append(w)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_: self._set_pointer(True))
        motion.connect("leave", lambda *_: self._set_pointer(False))
        self.add_controller(motion)
        menu = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        menu.connect("pressed", self._menu_pressed)
        self.add_controller(menu)
        opening = Gtk.GestureClick(button=Gdk.BUTTON_PRIMARY)
        opening.connect("released", self._released)
        self.add_controller(opening)
        select = Gtk.GestureClick()
        select.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        select.connect("pressed", self._select_pressed)
        self.add_controller(select)

    # -- binding ------------------------------------------------------------

    def bind(self, item):
        self.unbind()
        self.item = item
        self._handler = item.connect("changed", lambda *_: self.refresh())
        self.refresh()

    def unbind(self):
        if self.item is not None and self._handler:
            self.item.disconnect(self._handler)
        self.item, self._handler = None, 0

    def refresh(self):
        item = self.item
        if item is None:
            return
        a = item.app
        set_text(self.name, a.name)
        second = a.comment or a.generic_name
        if not second and a.source == "webapp":
            second = next((w[len("--app="):] for w in a.exec.split() if w.startswith("--app=")), "")
        set_text(self.desc, second or a.id)
        self.desc.set_tooltip_text(a.id)
        if a.icon != self._icon_name:
            self._icon_name = name = a.icon
            self.image.clear()

            def show(gicon, name=name):
                if self._icon_name == name:
                    self.image.set_from_gicon(gicon)
            gicon_later(name, show)
        self.new_badge.set_visible(a.new)
        self.custom_badge.set_visible(a.customised and not a.uninstalled)
        self.missing_badge.set_visible(bool(a.missing) and not a.uninstalled)
        if a.missing:
            self.missing_badge.set_tooltip_text(
                _("{program} wasn't found, so this entry can't start anything.").format(program=a.missing))
        self.gone_badge.set_visible(a.uninstalled)
        self.nodisplay_badge.set_visible(a.no_display and not a.hidden)
        if a.hidden:
            self.add_css_class("is-hidden")
        else:
            self.remove_css_class("is-hidden")
        selecting = self._selecting()
        self.check.set_visible(selecting)
        self.check.set_active(item.selected)
        if selecting and item.selected:
            self.add_css_class("is-selected")
        else:
            self.remove_css_class("is-selected")
        if a.id == self._current() and not selecting:
            self.add_css_class("is-current")
        else:
            self.remove_css_class("is-current")
        self._update_eye()
        state = _("hidden from launcher") if a.hidden else _("shown in launcher")
        self.update_property([Gtk.AccessibleProperty.LABEL],
                             [_("{name}, {state}").format(name=a.name, state=state)])

    def _update_eye(self):
        if self.item is None:
            return
        a = self.item.app
        is_self = a.id == APP_ID + ".desktop" and not a.hidden
        selecting = self._selecting()
        # Hidden apps always show the eye; others when pointed at.
        self.eye.set_opacity(1 if a.hidden or (self._pointer and not selecting) else 0)
        self.eye.set_sensitive(not self.item.busy and not is_self and not selecting)
        if a.hidden:
            set_text(self.eye_glyph, glyph("visibility" if self._pointer else "visibility_off"))
            tip = _("Hidden from launcher. Click to show {name} again.").format(name=a.name)
        else:
            set_text(self.eye_glyph, glyph("visibility_off"))
            tip = (_("App Entries can't hide itself, or you'd have no way back") if is_self
                   else _("Hide {name} from launcher").format(name=a.name))
        self.eye.set_tooltip_text(tip)
        self.eye.update_property([Gtk.AccessibleProperty.LABEL],
                                 [(_("Show {name}") if a.hidden else _("Hide {name}")).format(name=a.name)])
        if a.hidden:
            self.eye.add_css_class("is-on")
        else:
            self.eye.remove_css_class("is-on")

    # -- input --------------------------------------------------------------

    def _set_pointer(self, on):
        self._pointer = on
        self._update_eye()

    def _eye_clicked(self, *_):
        if self.item is not None and not self._selecting():
            self._on_toggle(self.item, not self.item.app.hidden)

    def toggle(self):
        """Space on the row: hide or show it."""
        if self.item is not None and self.eye.get_sensitive():
            self._eye_clicked()

    def _released(self, gesture, _n, x, y):
        if self.item is None or self._selecting():
            return
        picked = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        while picked is not None and picked is not self:
            if picked is self.eye:
                return
            picked = picked.get_parent()
        self._on_action(self.item, "open")

    def _select_pressed(self, gesture, _n, _x, _y):
        if self.item is None or not self._selecting():
            return
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.item.set_selected(not self.item.selected)
        self._on_action(self.item, "selected")

    def _menu_pressed(self, gesture, _n, x, y):
        if self.item is None or self._selecting():
            return
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.open_menu(x, y)

    def open_menu(self, x=None, y=None):
        """The app's options, at the pointer or (from the keyboard) the row."""
        a = self.item.app
        pop = Gtk.Popover()
        pop.add_css_class("options")
        pop.set_has_arrow(False)
        item = self.item

        def act(name):
            def cb(*_):
                pop.popdown()
                self._on_action(item, name)
            return cb

        pop.set_child(menu_box(a, act, hide_item=True))
        pop.set_parent(self)
        pop.connect("closed", lambda p: p.unparent())
        if x is not None:
            rect = Gdk.Rectangle()
            rect.x, rect.y, rect.width, rect.height = int(x), int(y), 1, 1
            pop.set_pointing_to(rect)
        pop.popup()

