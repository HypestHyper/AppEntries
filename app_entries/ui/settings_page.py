"""The Settings tab of the main window, built from section + card pairs."""
import os
from gettext import gettext as _

from gi.repository import Gio, GLib, Gtk

from .. import APP_NAME, VERSION, desktop_entries, theme
from .color_picker import ColorDot, ColorPicker
from .widgets import (Clamp, Group, WrapBox, button, card, hbox, icon, label, section, set_text, switch_row,
                      vbox, wrap_row)

REPO_URL = "https://github.com/HypestHyper/AppEntries"


def _explained(c, text):
    c.append(label(text, ("small", "faint"), wrap=True, chars=60))


class SettingsPage(Gtk.ScrolledWindow):
    """`win` is the main window: the buttons here call its actions."""

    def __init__(self, win, settings):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.settings = settings
        page = vbox(0)
        page.set_margin_bottom(24)

        # Appearance
        page.append(section(_("Appearance"), _("One accent colour sets the whole palette, or pick a well-known "
                                               "colour scheme.")))
        c = card()
        self._accent_buttons = {}
        first = None
        swatches = WrapBox(10, 10)
        accent = settings.get("accent")

        def toggle(key, child, tip):
            nonlocal first
            b = Gtk.ToggleButton(tooltip_text=tip)
            b.set_child(child)
            b.update_property([Gtk.AccessibleProperty.LABEL], [tip])
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect("toggled", lambda btn, k=key: btn.get_active() and self._set_accent(k))
            self._accent_buttons[key] = b
            swatches.append(b)
            return b

        desk = toggle("desktop", hbox(6, icon("wallpaper"), label(_("Desktop"))),
                      _("Use your desktop's accent colour, and follow it when it changes"))
        desk.add_css_class("tonal")
        desk.add_css_class("small")
        pal = toggle("palette", hbox(6, icon("palette"), label(_("Palette's"))),
                     _("Use the chosen palette's own accent colour"))
        pal.add_css_class("tonal")
        pal.add_css_class("small")
        for seed, name in theme.SEEDS:
            b = toggle(seed, Gtk.Box(), _("Accent: {name}").format(name=_(name)))
            b.add_css_class("swatch")
            b.add_css_class("swatch-" + seed)
        self._custom_btn = Gtk.ToggleButton(tooltip_text=_("Any other colour"))
        self._custom_btn.set_child(hbox(6, icon("colorize"), label(_("Other…"))))
        self._custom_btn.add_css_class("tonal")
        self._custom_btn.add_css_class("small")
        self._custom_btn.set_group(first)
        self._custom_btn.update_property([Gtk.AccessibleProperty.LABEL], [_("Any other accent colour")])
        swatches.append(self._custom_btn)
        self._picker = ColorPicker("#" + theme.valid_seed(accent), _("Accent"))
        self._picker.connect("changed", lambda _p, hexv: self._custom_btn.get_active()
                             and self.settings.set("accent", hexv.lstrip("#")))
        self._picker_reveal = Gtk.Revealer(child=self._picker,
                                           transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._custom_btn.connect("toggled", self._on_custom)
        c.append(vbox(8, label(_("Accent"), ("body", "dim")), swatches, self._picker_reveal))
        self._accent_note = label("", ("small", "faint"), wrap=True, chars=60)
        c.append(self._accent_note)

        # Palettes
        self._palette_buttons = {}
        palettes = WrapBox(8, 8)
        pfirst = None
        dark = getattr(win.get_application().style, "dark", True)
        for key, name in [("generated", _("From accent"))] + [(k, v[0]) for k, v in theme.PRESETS.items()]:
            b = Gtk.ToggleButton()
            b.add_css_class("palette-chip")
            if key == "generated":
                dots = [ColorDot(theme.palette(theme.DEFAULT_SEED, dark)[r], 14)
                        for r in ("SURFACE_DIM", "SURFACE_CONTAINER", "PRIMARY")]
            else:
                c_ = theme.PRESETS[key][1][dark]
                dots = [ColorDot(c_[r], 14) for r in ("window", "card", "accent")]
            b.set_child(hbox(8, hbox(2, *dots), label(name)))
            b.update_property([Gtk.AccessibleProperty.LABEL], [_("Palette: {name}").format(name=name)])
            if pfirst is None:
                pfirst = b
            else:
                b.set_group(pfirst)
            b.connect("toggled", lambda btn, k=key: btn.get_active() and self._set_palette(k))
            self._palette_buttons[key] = b
            palettes.append(b)
        c.append(vbox(8, label(_("Palette"), ("body", "dim")), palettes))
        c.append(label(_("A palette replaces the background and text colours with a well-known colour scheme, in "
                         "light and dark. The accent above still applies; choose Palette's to use the scheme's own."),
                       ("small", "faint"), wrap=True, chars=60))
        self._win = win
        win.get_application().accent_listeners.append(self._sync_accent)
        self.connect("destroy", lambda *_a: win.get_application().accent_listeners.remove(self._sync_accent)
                     if self._sync_accent in win.get_application().accent_listeners else None)

        r = wrap_row(10)
        r.append(hbox(10, label(_("Theme"), ("body", "dim")),
                      Group([("system", _("System")), ("light", _("Light")), ("dark", _("Dark"))],
                            settings.get("theme"), lambda v: settings.set("theme", v))))
        c.append(r)
        r = wrap_row(10)
        r.append(hbox(10, label(_("Size"), ("body", "dim")),
                      Group([("auto", _("Auto")), ("compact", _("Compact")),
                             ("default", _("Default")), ("large", _("Large"))],
                            settings.get("size"), lambda v: settings.set("size", v))))
        c.append(r)
        c.append(label(_("Auto uses Compact when the window is narrower than 900 pixels."), ("small", "faint")))
        row, _sw = switch_row(_("Colour the app icon to match"), settings.get("themed-icon"),
                              lambda v: settings.set("themed-icon", v))
        c.append(row)
        row, _sw = switch_row(_("Reduce motion"), settings.get("reduce-motion"),
                              lambda v: settings.set("reduce-motion", v))
        c.append(row)
        row, _sw = switch_row(_("Show window buttons"), settings.get("window-controls"),
                              lambda v: settings.set("window-controls", v))
        c.append(row)
        page.append(c)

        # App list
        page.append(section(_("App list"), _("Some apps ask not to be listed in menus, such as helpers "
                                             "and settings panels. You can still hide them.")))
        c = card()
        row, self._nd = switch_row(_("Include apps not shown in menus"), settings.get("show-no-display"),
                                   lambda v: settings.set("show-no-display", v))
        c.append(row)
        c.append(hbox(10, button(_("Unhide all…"), "visibility", "tonal", lambda *_: win._unhide_all(), small=True),
                      button(_("Refresh launcher menus…"), "sync", "tonal", lambda *_: win._refresh_launchers(),
                             small=True)))
        _explained(c, _("Unhide all shows every app you or App Entries hid, after telling you what it will "
                        "change. Refresh launcher menus nudges launchers that don't notice changes on their own; "
                        "it says what it does before doing it."))
        page.append(c)

        # Files
        folder = desktop_entries.user_apps_dir()
        page.append(section(_("Where changes go"),
                            _("Hiding an app writes a small file to your own applications folder. "
                              "Files in system folders are never changed.")))
        c = card()
        path = label(folder, ("mono", "dim"), ellipsize=True)
        path.set_hexpand(True)
        path.set_selectable(True)
        c.append(hbox(10, path, button(_("Open folder"), "folder_open", "tonal", self._open_folder, small=True)))
        page.append(c)

        # Export and import
        page.append(section(_("Your changes"),
                            _("Move what you've done in App Entries to another computer, or keep a backup "
                              "before reinstalling.")))
        c = card()
        c.append(hbox(10, button(_("Export…"), "upload", "tonal", lambda *_: win._export(), small=True),
                      button(_("Import…"), "download", "tonal", lambda *_: win._import(), small=True)))
        _explained(c, _("Export saves the apps you hid, the entries you edited and the launchers you made, "
                        "with their icons, to one file. Import shows every change it would make, and what it "
                        "skips, before anything is written, and you can undo it."))
        page.append(c)

        # About
        page.append(section(_("About")))
        c = card()
        c.append(label("%s %s" % (APP_NAME, VERSION), ("heading",)))
        c.append(label(_("Hides, shows and edits app launcher entries. Also makes launchers and web apps, manages "
                         "autostart, chooses default apps and removes AppImages. Only changes files in your home "
                         "folder."),
                       ("body", "dim"), wrap=True, chars=60))
        source = button(_("Source code"), "open_in_new", "tonal", lambda *_: self._open(REPO_URL), small=True)
        source.set_halign(Gtk.Align.START)
        c.append(source)
        _explained(c, _("MIT License. Fonts: Google Sans Flex (SIL OFL 1.1) and Material Symbols Rounded "
                        "(Apache 2.0)."))
        page.append(c)

        self.set_child(Clamp(page, 760))
        settings.connect(self._on_setting)
        self._sync_accent()

    # -- accent and palette ---------------------------------------------------

    def _set_accent(self, key):
        self._picker_reveal.set_reveal_child(False)
        self.settings.set("accent", key)

    def _on_custom(self, b):
        self._picker_reveal.set_reveal_child(b.get_active())
        if b.get_active():
            self.settings.set("accent", self._picker.hex().lstrip("#"))

    def _set_palette(self, key):
        self.settings.set("palette", key)
        # A scheme looks right with its own accent; you can pick another after.
        if key != "generated" and self.settings.get("accent") in [s for s, _n in theme.SEEDS]:
            self.settings.set("accent", "palette")
        elif key == "generated" and self.settings.get("accent") == "palette":
            self.settings.set("accent", theme.DEFAULT_SEED)

    def _sync_accent(self):
        accent, palette = self.settings.get("accent"), self.settings.get("palette")
        preset = palette in theme.PRESETS
        self._accent_buttons["palette"].set_visible(preset)
        if accent not in self._accent_buttons and self._picker.hex().lstrip("#") != accent:
            self._picker.set_hex("#" + theme.valid_seed(accent), emit=False)
        b = self._accent_buttons.get(accent)
        if b is not None:
            if not b.get_active():
                b.set_active(True)
        elif not self._custom_btn.get_active():
            self._custom_btn.set_active(True)
        pb = self._palette_buttons.get(palette if preset else "generated")
        if pb is not None and not pb.get_active():
            pb.set_active(True)
        if accent == "desktop":
            color, where = self._win.get_application().desktop_accent.value()
            if color:
                note = _("Following {source}: {color}.").format(source=where, color=color)
            else:
                note = _("Your desktop doesn't share an accent colour, so {fallback} is used. GNOME and KDE "
                         "share theirs; on Hyprland, Sway and similar, theme tools like Noctalia, matugen or "
                         "wallust write it to ~/.config/gtk-4.0/gtk.css.").format(
                    fallback=_("the palette's own") if preset else _("Mint"))
        elif accent == "palette":
            note = _("Using the palette's own accent colour.")
        else:
            note = _("Desktop follows your desktop's accent colour: GNOME and KDE settings, or the colours "
                     "theme tools like Noctalia and matugen write for GTK apps.")
        set_text(self._accent_note, note)

    def _on_setting(self, key):
        if key == "show-no-display":
            self._nd.set_value(self.settings.get("show-no-display"))
        elif key in ("accent", "palette"):
            self._sync_accent()

    @staticmethod
    def _open(uri):
        try:
            Gio.AppInfo.launch_default_for_uri(uri, None)
        except GLib.Error:
            pass

    def _open_folder(self, *_):
        folder = desktop_entries.user_apps_dir()
        try:
            os.makedirs(folder, exist_ok=True)
            Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(folder).get_uri(), None)
        except (OSError, GLib.Error):
            pass  # no file manager, or no folder: nothing useful to report
