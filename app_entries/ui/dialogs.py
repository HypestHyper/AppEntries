"""Modal dialogs and the background-work helper."""
import os
import threading
from gettext import gettext as _

from gi.repository import Gdk, Gio, GLib, Gtk

from .widgets import button, hbox, icon, label, vbox


def run_bg(fn, done=None):
    """Run fn() in a daemon thread, then done(result) on the GTK thread.

    Exceptions are passed to done() as the result, so callers can tell them
    apart with isinstance()."""

    def work():
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001 - handed to the UI
            result = e
        if done is not None:
            GLib.idle_add(lambda: (done(result), False)[1])

    threading.Thread(target=work, daemon=True).start()


class Dialog(Gtk.Window):
    """A small modal card: icon, title, text and buttons.

    buttons is a list of (response, text, style). on_response(response) is
    called once, with None if the dialog is closed with Escape."""

    def __init__(self, parent, title, body, buttons, on_response=None, icon_name="info",
                 icon_class="accent", detail=None, extra=None):
        super().__init__(transient_for=parent, modal=True, resizable=False, decorated=False)
        self.add_css_class("dialog")
        self.set_title(title)
        self._cb = on_response
        self._answered = False

        box = vbox(12)
        box.set_margin_top(24)
        box.set_margin_bottom(20)
        box.set_margin_start(24)
        box.set_margin_end(24)
        ic = icon(icon_name, ("big", icon_class))
        ic.set_halign(Gtk.Align.START)
        box.append(ic)
        box.append(label(title, ("title",), wrap=True, chars=36))
        box.append(label(body, ("body", "dim"), wrap=True, chars=48))
        detail_label = None
        if detail:
            detail_label = label(detail, ("mono", "faint"), wrap=True, chars=48)
            detail_label.set_selectable(True)
            box.append(detail_label)
        if extra is not None:
            box.append(extra)

        row = hbox(8)
        row.set_halign(Gtk.Align.END)
        row.set_margin_top(12)
        first = None
        for resp, text, style in buttons:
            b = button(text, style=style, cb=lambda _b, r=resp: self._respond(r))
            row.append(b)
            if "filled" in style or "danger" in style or first is None:
                first = b
        box.append(row)
        self.set_child(box)
        self.set_default_size(420, -1)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        self.connect("close-request", lambda *_: (self._respond(None), False)[1])
        if first is not None:
            self.set_default_widget(first)

            def focus():
                if extra is None:
                    first.grab_focus()
                if detail_label is not None:
                    detail_label.select_region(0, 0)  # don't start with the path selected
                return False

            GLib.idle_add(focus)

    def _on_key(self, _c, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        return False

    def _respond(self, resp):
        if self._answered:
            return
        self._answered = True
        if self._cb:
            self._cb(resp)
        self.destroy()


def error_dialog(parent, title, body, path=None):
    d = Dialog(parent, title, body, [("ok", _("OK"), "filled")],
               icon_name="error", icon_class="error-text", detail=path)
    d.present()
    return d


def choose_icon_file(parent, on_chosen, start=None):
    """Pick an image and copy it into the icon library, so the entry keeps
    working if the original is moved. on_chosen gets the copy's path."""
    from .. import icon_library

    def copied(result):
        if isinstance(result, Exception):
            error_dialog(parent, _("Couldn't use that icon"), str(result))
        else:
            on_chosen(result)

    def chosen(path):
        if path.lower().endswith((".svg", ".png")):
            run_bg(lambda: icon_library.add_file(path), copied)
        else:
            on_chosen(path)  # other formats (XPM) are used where they are

    choose_file(parent, _("Choose an icon"), chosen, patterns=("*.svg", "*.png", "*.xpm"), start=start)


def choose_file(parent, title, on_chosen, folder=False, patterns=None, start=None, save_as=None,
                filter_name=None):
    """Pick a file or folder with GTK's own dialog.

    It doesn't need xdg-desktop-portal, whose file chooser is missing on some
    desktops (xdg-desktop-portal-hyprland has none), where the portal dialog
    silently never opens. With `save_as` (a file name) it asks where to save."""
    action = (Gtk.FileChooserAction.SAVE if save_as else
              Gtk.FileChooserAction.SELECT_FOLDER if folder else Gtk.FileChooserAction.OPEN)
    dialog = Gtk.FileChooserDialog(title=title, transient_for=parent, modal=True, action=action)
    dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    dialog.add_button(_("Save") if save_as else _("Choose") if folder else _("Open"), Gtk.ResponseType.ACCEPT)
    dialog.set_default_response(Gtk.ResponseType.ACCEPT)
    if patterns:
        filt = Gtk.FileFilter()
        filt.set_name(filter_name or _("Images"))
        for p in patterns:
            filt.add_pattern(p)
        dialog.add_filter(filt)
        everything = Gtk.FileFilter()
        everything.set_name(_("All files"))
        everything.add_pattern("*")
        dialog.add_filter(everything)
    begin = start if start and os.path.isdir(start) else os.path.expanduser("~")
    try:
        dialog.set_current_folder(Gio.File.new_for_path(begin))
    except GLib.Error:
        pass
    if save_as:
        dialog.set_current_name(save_as)

    def response(d, resp):
        f = d.get_file() if resp == Gtk.ResponseType.ACCEPT else None
        d.destroy()
        if f is not None and f.get_path():
            on_chosen(f.get_path())

    dialog.connect("response", response)
    dialog.present()
    return dialog
