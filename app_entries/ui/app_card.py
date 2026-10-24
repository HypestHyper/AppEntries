"""The card shown for each application."""
import os
from gettext import gettext as _

from gi.repository import Gdk, Gio, Gtk, Pango

from .. import APP_ID, desktop_entries, icon_lookup, packages, uninstall
from .widgets import Toggle, WrapBox, glyph, hbox, icon, label, option_button, set_text, vbox


def N_(s):
    """Marks a string for translation; it's translated where it's shown."""
    return s


FALLBACK_ICON = "application-x-executable"


def gicon_for(name: str) -> Gio.Icon:
    """The current icon theme's icon if it has one, else a file found by
    searching the icon folders (other themes, pixmaps), else a generic icon."""
    if name and not os.path.isabs(name):
        base, ext = os.path.splitext(name)
        if ext.lower() in icon_lookup.EXTENSIONS:
            name = base
        display = Gdk.Display.get_default()
        theme = Gtk.IconTheme.get_for_display(display) if display else None
        if theme is not None and theme.has_icon(name):
            return Gio.ThemedIcon.new(name)
        current = theme.get_theme_name() if theme is not None else None
        path = icon_lookup.find(name, (current,))
    else:
        path = icon_lookup.find(name)
    if path:
        return Gio.FileIcon.new(Gio.File.new_for_path(path))
    return Gio.ThemedIcon.new(FALLBACK_ICON)


class Badge(Gtk.Box):
    """A small labelled pill; its tooltip says what it means."""

    def __init__(self, icon_name="", text="", kind="neutral", tooltip=""):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, valign=Gtk.Align.CENTER,
                         halign=Gtk.Align.START)
        self.add_css_class("badge")
        self._icon = icon(icon_name or "info", ("filled",))
        self._label = Gtk.Label()
        self.append(self._icon)
        self.append(self._label)
        self._kind = ""
        self.set(icon_name, text, kind, tooltip)

    def set(self, icon_name, text, kind="neutral", tooltip=""):
        set_text(self._icon, glyph(icon_name))
        set_text(self._label, text)
        if kind != self._kind:
            if self._kind:
                self.remove_css_class(self._kind)
            self.add_css_class(kind)
            self._kind = kind
        if self.get_tooltip_text() != tooltip:
            self.set_tooltip_text(tooltip or None)


# icon, label, explanation (shown as the badge's tooltip)
SOURCES = {
    "system": ("computer", N_("System"), N_("Installed by your package manager ({manager}).")),
    "flatpak": ("package_2", N_("Flatpak"), N_("Installed as a Flatpak.")),
    "snap": ("package_2", N_("Snap"), N_("Installed as a Snap.")),
    "appimage": ("deployed_code", N_("AppImage"), N_("Starts an AppImage file rather than an installed program.")),
    "steam": ("sports_esports", N_("Steam"), N_("A game shortcut that Steam added to your applications folder.")),
    "distrobox": ("deployed_code", N_("Distrobox"), N_("Runs inside a Distrobox container, added to your menus "
                                                       "with distrobox-export.")),
    "webapp": ("language", N_("Web app"), N_("A site that opens in its own window, without the browser's address "
                                            "bar. Made with App Entries.")),
    "user": ("person", N_("Local"), N_("A launcher in your own applications folder (~/.local/share/applications), "
                                       "not installed by a package.")),
}


# What Uninstall does, by how the app was installed. Each shows the full list first.
UNINSTALL_HINTS = {
    "flatpak": N_("Removes the Flatpak and everything set up for it. Shows the full list first."),
    "snap": N_("Removes the snap with snap's own command, in your terminal. Shows the full list first."),
    "appimage": N_("Moves the AppImage to the Trash and removes its menu entries, icons and file types. Shows "
                   "the full list first."),
    "steam": N_("Asks Steam to uninstall the game, then removes its menu entry. Shows the full list first."),
    "distrobox": N_("Removes what distrobox-export added to your menus. Shows the full list first."),
    "package": N_("Removes its package with your package manager, in your terminal. Shows what else goes, and "
                  "which apps need it, first."),
}


def label_for_source(key):
    """What a source is called in the UI; system apps are named after the
    package manager, like pacman or apt."""
    if key == "system":
        return packages.system_manager() or _("System")
    return _(SOURCES[key][1])


def _source_tip(key):
    tip = _(SOURCES[key][2])
    return tip.format(manager=packages.system_manager() or _("unknown")) if key == "system" else tip


class AppCard(Gtk.Box):
    """Shows one AppItem. `on_toggle(item, hidden)` is called on user changes.
    While `selecting()` is true, a click selects the card instead."""

    def __init__(self, on_toggle, on_action, selecting=lambda: False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.add_css_class("app-card")
        self.set_size_request(320, -1)
        self._on_toggle = on_toggle
        self._on_action = on_action
        self._selecting = selecting
        self.item = None
        self._handler = 0
        self._icon_name = None

        self.image = Gtk.Image(pixel_size=48, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        tile = Gtk.Box(halign=Gtk.Align.START, valign=Gtk.Align.START)
        tile.add_css_class("icon-tile")
        tile.append(self.image)

        self.name = label("", ("heading", "app-name"), ellipsize=True)
        self.name.set_hexpand(True)
        self.hidden_badge = Badge("visibility_off", _("Hidden"), "hidden",
                                  _("Launchers leave this app out of their menus."))
        self.more = Gtk.MenuButton(valign=Gtk.Align.START, tooltip_text=_("More options"))
        self.more.set_child(icon("more_horiz"))
        self.more.add_css_class("flat")
        self.more.add_css_class("circle")
        self.more.add_css_class("small")
        self.more.update_property([Gtk.AccessibleProperty.LABEL], [_("More options")])
        self.more.set_create_popup_func(self._build_menu)
        self.secondary = Gtk.Label(xalign=0, yalign=0, wrap=True, lines=2,
                                   ellipsize=Pango.EllipsizeMode.END, width_chars=10,
                                   max_width_chars=40, wrap_mode=Pango.WrapMode.WORD_CHAR)
        self.secondary.add_css_class("small")
        self.secondary.add_css_class("dim")
        self.tertiary = label("", ("mono", "faint"), ellipsize=True)
        self.tertiary.set_ellipsize(Pango.EllipsizeMode.MIDDLE)

        self.source_badge = Badge()
        self.custom_badge = Badge("edit_note", _("Customised"), "custom",
                                  _("Changed from the version its package installed: launchers use your own "
                                    "copy of this entry. Restore original in the ⋯ menu puts the system "
                                    "version back."))
        self.missing_badge = Badge("link_off", _("Missing program"), "error")
        self.nodisplay_badge = Badge("bedtime", _("Not in menus"), "neutral",
                                     _("Its package asks for it to be left out of menus (NoDisplay), "
                                       "usually because it's a helper or a settings panel. You're showing "
                                       "it anyway."))
        # Wraps onto a second line rather than making the card wider.
        self.badges = WrapBox(6, 4)
        for b in (self.hidden_badge, self.source_badge, self.custom_badge, self.missing_badge,
                  self.nodisplay_badge):
            self.badges.append(b)

        # "Another entry for this app is shown: …" — click to search for it.
        self.related = Gtk.Button(halign=Gtk.Align.START)
        self.related.add_css_class("related-hint")
        self.related_label = label("", ("small",), wrap=True, chars=30)
        self.related.set_child(self.related_label)
        self.related.connect("clicked", self._find_related)

        self.check = Gtk.CheckButton(valign=Gtk.Align.START, visible=False)
        self.check.add_css_class("card-check")
        self.check.set_can_target(False)  # the whole card takes the click
        self.check.set_focusable(False)
        text = vbox(4, hbox(4, self.name, self.more, self.check), self.secondary, self.tertiary,
                    self.badges, self.related)
        text.set_hexpand(True)
        self.append(hbox(14, tile, text))

        spacer = Gtk.Box(vexpand=True)
        self.append(spacer)

        self.switch = Toggle(False, self._toggled)
        self.switch_label = label(_("Hidden from launcher"), ("body",))
        self.switch_label.set_hexpand(True)
        self.switch_icon = icon("visibility_off")
        row = hbox(10, self.switch_icon, self.switch_label, self.switch)
        row.add_css_class("card-switch-row")
        click = Gtk.GestureClick()
        click.connect("released", self._row_clicked)
        row.add_controller(click)
        self.append(row)
        self.switch_row = row

        # In selection mode, a click anywhere picks the card; nothing inside it runs.
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
        second = a.generic_name if a.generic_name and a.generic_name != a.name else a.comment
        if not second and a.source == "webapp":
            second = next((w[len("--app="):] for w in a.exec.split() if w.startswith("--app=")), "")
        if a.comment and second != a.comment and len(second) < 30:
            second = "%s · %s" % (second, a.comment)
        set_text(self.secondary, second or _("No description"))
        set_text(self.tertiary, a.id)
        if a.icon != self._icon_name:
            self._icon_name = a.icon
            self.image.set_from_gicon(gicon_for(a.icon))

        self.hidden_badge.set_visible(a.hidden)
        if a.hidden:
            here = (desktop_entries.current_desktops() or [_("this desktop")])[0]
            if a.excluded_here and not (a.has_override and a.override_managed and not a.base_hidden):
                rule = (_("Its entry is only for {desktops} (OnlyShowIn), so launchers on {here} leave it out.")
                        .format(desktops=", ".join(a.only_show_in), here=here) if a.only_show_in else
                        _("Its entry says not to show it on {here} (NotShowIn), so launchers there leave it out.")
                        .format(here=here))
                self.hidden_badge.set("visibility_off", _("Not shown on {here}").format(here=here), "hidden",
                                      rule + " " + _("Turn the switch off to show it here too."))
            elif a.has_override:
                self.hidden_badge.set("visibility_off", _("Hidden by you"), "hidden",
                                      _("A file in your applications folder keeps it out of launcher menus. "
                                        "Turn the switch off to show it again."))
            else:
                self.hidden_badge.set("visibility_off", _("Hidden by its package"), "hidden",
                                      _("The entry installed with the app asks launchers not to show it "
                                        "(NoDisplay or Hidden), usually because it's a background service or "
                                        "a helper. Turn the switch off to show it anyway."))
        self.related.set_visible(bool(a.related))
        if a.related:
            others = ", ".join(a.related)
            text = (_("Another entry for this app is shown in launchers: {names}") if a.hidden
                    else _("Another entry for this app is hidden: {names}")).format(names=others)
            set_text(self.related_label, text)
            self.related.set_tooltip_text(_("Search for {names}").format(names=others))
        src = a.source or ("system" if a.system else "user")
        self.source_badge.set(SOURCES[src][0], label_for_source(src), "neutral", _source_tip(src))
        self.custom_badge.set_visible(a.customised)
        if a.customised:
            self.add_css_class("is-custom")
        else:
            self.remove_css_class("is-custom")
        self.missing_badge.set_visible(bool(a.missing))
        if a.missing:
            self.missing_badge.set("link_off", _("Missing program"), "error",
                                   _("{program} wasn't found in your PATH or the usual program folders, "
                                     "so this entry can't start anything. It runs: {command}")
                                   .format(program=a.missing, command=a.exec))
        # Only worth saying when the app is shown anyway; when it's hidden,
        # "Hidden by its package" already says it.
        self.nodisplay_badge.set_visible(a.no_display and not a.hidden)
        self.badges.queue_resize()
        if a.hidden:
            self.add_css_class("is-hidden")
        else:
            self.remove_css_class("is-hidden")
        selecting = self._selecting()
        self.check.set_visible(selecting)
        self.more.set_visible(not selecting)
        self.switch_row.set_sensitive(not selecting)
        self.check.set_active(item.selected)
        if selecting and item.selected:
            self.add_css_class("is-selected")
        else:
            self.remove_css_class("is-selected")
        self.switch.set_value(a.hidden)
        is_self = a.id == APP_ID + ".desktop" and not a.hidden
        self.switch.set_sensitive(not item.busy and not is_self)

        state = _("hidden from launcher") if a.hidden else _("shown in launcher")
        self.update_property([Gtk.AccessibleProperty.LABEL],
                             [_("{name}, {state}").format(name=a.name, state=state)])
        self.switch.update_property([Gtk.AccessibleProperty.LABEL],
                                    [_("Hide {name} from launcher").format(name=a.name)])
        if is_self:
            tip = _("App Entries can't hide itself, or you'd have no way back")
        else:
            tip = (_("Turn off to show {name} in app launchers again") if a.hidden
                   else _("Turn on to hide {name} from app launchers")).format(name=a.name)
        self.switch.set_tooltip_text(tip)
        details = [_("Runs: {cmd}").format(cmd=a.exec), a.source_path]
        if a.has_override and a.override_path != a.source_path:
            details.append(_("Override: {path}").format(path=a.override_path))
        self.tertiary.set_tooltip_text("\n".join(details))

    def _find_related(self, *_):
        if self.item is not None and self.item.app.related:
            self._on_action(self.item, "find:" + self.item.app.related[0])

    # -- menu ---------------------------------------------------------------

    def _build_menu(self, menu_button):
        a = self.item.app if self.item else None
        if a is None:
            return
        box = vbox(2)
        box.set_size_request(300, -1)

        def act(name):
            def cb(*_):
                menu_button.popdown()
                self._on_action(self.item, name)
            return cb

        box.append(option_button(
            "edit_note", _("Edit…"),
            (_("Change what it runs, its name, icon and folders. Nothing is saved until you press Save.")
             if a.created else
             _("Change the name, icon, command and where it appears. Nothing is saved until you press Save.")),
            act("edit")))
        if a.created:
            box.append(option_button(
                "content_copy", _("Duplicate"),
                _("Makes a new launcher with the same settings, named “(copy)”, to change from there."),
                act("duplicate")))
        if a.has_override and a.system:
            box.append(option_button(
                "restart_alt", _("Restore original"),
                _("Deletes your file for this app, so the version installed by the system is used again. "
                  "You can undo this."), act("restore")))
        if a.source == "webapp":
            box.append(option_button(
                "delete", _("Delete this web app"),
                _("Deletes this web app from your menus. Your browser and its sign-ins aren't touched. "
                  "You can undo this."), act("delete"), danger=True))
        elif (a.source == "user" or a.created) and a.override_path and not a.override_managed:
            box.append(option_button(
                "delete", _("Delete this launcher"),
                _("Deletes this launcher file from your applications folder. "
                  "The program itself isn't touched. You can undo this."), act("delete"), danger=True))
        box.append(option_button(
            "open_in_new", _("Helper apps…"),
            _("Shortcuts to apps that change its permissions, versions or setup, like Flatseal. Each opens that "
              "app."), act("helpers")))
        kind = uninstall.kind_of(a)
        if kind:
            box.append(option_button(
                "delete_forever", _("Uninstall {name}…").format(name=a.name),
                _(UNINSTALL_HINTS[kind]), act("uninstall"), danger=True))
        box.append(option_button(
            "folder_open", _("Open file location"),
            _("Opens the folder that holds this app's entry file in your file manager."), act("open-folder")))
        pop = Gtk.Popover()
        pop.add_css_class("options")
        pop.set_child(box)
        menu_button.set_popover(pop)

    # -- input --------------------------------------------------------------

    def _select_pressed(self, gesture, _n, _x, _y):
        if self.item is None or not self._selecting():
            return
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.item.set_selected(not self.item.selected)
        self._on_action(self.item, "selected")

    def _toggled(self, active):
        if self.item is not None:
            self._on_toggle(self.item, active)

    def _row_clicked(self, gesture, _n, x, y):
        # Clicking anywhere on the row flips the switch, like a settings row.
        picked = gesture.get_widget().pick(x, y, Gtk.PickFlags.DEFAULT)
        w = picked
        while w is not None and w is not gesture.get_widget():
            if w is self.switch:
                return
            w = w.get_parent()
        if self.switch.get_sensitive():
            self.switch.set_active(not self.switch.get_active())
