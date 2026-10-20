"""The Settings tab of the main window, built from section + card pairs."""
import os
from gettext import gettext as _

from gi.repository import Gio, GLib, Gtk

from .. import APP_NAME, VERSION, desktop_entries, theme
from .widgets import Clamp, Group, button, card, hbox, label, section, switch_row, vbox, wrap_row

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
        page.append(section(_("Appearance"), _("One accent colour sets the whole palette.")))
        c = card()
        swatches = hbox(10)
        first = None
        current = theme.valid_seed(settings.get("accent"))
        for seed, name in theme.SEEDS:
            b = Gtk.ToggleButton(tooltip_text=_(name))
            b.add_css_class("swatch")
            b.add_css_class("swatch-" + seed)
            b.update_property([Gtk.AccessibleProperty.LABEL], [_("Accent: {name}").format(name=_(name))])
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.set_active(seed == current)
            b.connect("toggled", self._on_swatch, seed)
            swatches.append(b)
        c.append(hbox(12, label(_("Accent"), ("body", "dim")), swatches))

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

    def _on_swatch(self, b, seed):
        if b.get_active():
            self.settings.set("accent", seed)

    def _on_setting(self, key):
        if key == "show-no-display":
            self._nd.set_value(self.settings.get("show-no-display"))

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
