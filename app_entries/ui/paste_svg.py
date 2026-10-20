"""Paste SVG code, preview it, name it and save it to your icon library."""
import os
import tempfile
from gettext import gettext as _

from gi.repository import Gdk, GLib, Gtk

from .. import icon_library, symbols
from .widgets import button, hbox, label, vbox


class PasteSvgWindow(Gtk.Window):
    """on_saved(path) is called with the new library file."""

    def __init__(self, parent, on_saved):
        super().__init__(transient_for=parent, modal=True, title=_("Paste an SVG"))
        self.add_css_class("prefs")
        self.set_default_size(760, 660)
        self._on_saved = on_saved
        self._name_edited = False

        hb = Gtk.HeaderBar()
        hb.set_show_title_buttons(False)
        hb.set_title_widget(label(_("Paste an SVG"), ("title",)))
        cancel = button(_("Cancel"), style="tonal", small=True, cb=lambda *_a: self.close())
        self.save = button(_("Save to your icons"), style="filled", small=True, cb=self._save)
        for b in (cancel, self.save):
            b.set_valign(Gtk.Align.CENTER)
        hb.pack_start(cancel)
        hb.pack_end(self.save)
        self.set_titlebar(hb)

        self.code = Gtk.TextView(monospace=True, wrap_mode=Gtk.WrapMode.CHAR, top_margin=10, bottom_margin=10,
                                 left_margin=12, right_margin=12, accepts_tab=False)
        self.code.add_css_class("textarea")
        self.code.update_property([Gtk.AccessibleProperty.LABEL], [_("SVG code")])
        self.code.get_buffer().connect("changed", lambda *_a: self._changed())
        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroll.set_child(self.code)
        sources = vbox(6)
        for name, url, _link, how in icon_library.SOURCES:
            link = Gtk.LinkButton(uri=url, label=name, halign=Gtk.Align.START)
            sources.append(vbox(0, link, label(how, ("small", "dim"), wrap=True, chars=40)))
        left = vbox(8, label(_("SVG code"), ("body", "option-title")), scroll,
                    label(_("Paste the whole <svg>…</svg> code."), ("small", "dim"), wrap=True, chars=40),
                    label(_("Where to find icons"), ("body", "option-title")), sources,
                    label(_("Check each icon's license before sharing what you make with it."),
                          ("small", "faint"), wrap=True, chars=40))

        self.name = Gtk.Entry(placeholder_text=_("Icon name"))
        self.name.connect("changed", self._on_name)
        self.big = Gtk.Image(pixel_size=112, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.on_light = Gtk.Image(pixel_size=32, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.on_dark = Gtk.Image(pixel_size=32, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        light = Gtk.Box()
        light.add_css_class("light-sample")
        light.append(self.on_light)
        dark = Gtk.Box()
        dark.add_css_class("dark-sample")
        dark.append(self.on_dark)
        prev = vbox(10, self.big, hbox(10, light, dark))
        prev.get_last_child().set_halign(Gtk.Align.CENTER)
        prev.add_css_class("card-inner")
        self.status = label("", ("small",), wrap=True, chars=30)
        right = vbox(12, label(_("Name"), ("body", "option-title")), self.name,
                     label(_("Saved as this name in your icon library."), ("small", "dim"), wrap=True, chars=30),
                     label(_("Preview"), ("body", "option-title")), prev, self.status)
        right.set_size_request(260, -1)

        body = hbox(20, left, right)
        for side in ("start", "end", "bottom"):
            getattr(body, "set_margin_" + side)(20)
        body.set_margin_top(4)
        self.set_child(body)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, *_a: kv == Gdk.KEY_Escape and (self.close() or True))
        self.add_controller(keys)

        # Start with whatever is on the clipboard, if it looks like SVG.
        self.get_clipboard().read_text_async(None, self._clipboard)
        self._changed()

    def _clipboard(self, clipboard, result):
        try:
            text = clipboard.read_text_finish(result)
        except GLib.Error:
            return
        if text and "<svg" in text and not self._text().strip():
            self.code.get_buffer().set_text(text.strip())

    def _text(self):
        buf = self.code.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _on_name(self, entry):
        if entry.has_focus():
            self._name_edited = True
        self._changed()

    def _changed(self):
        text = self._text()
        if not self._name_edited:
            title = icon_library.title_of(text)
            if title and title != self.name.get_text():
                self.name.set_text(title)
        try:
            icon_library.check_text(text)
        except icon_library.IconError as e:
            self._show(None, str(e) if text.strip() else _("Paste SVG code on the left to see it here."))
            return
        fd, tmp = tempfile.mkstemp(suffix=".svg")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            from .icon_picker import texture
            svgs = [symbols.render(symbols.IconChoice(source="file", path=tmp, shape="none", recolor=False), s)
                    for s in (112, 32)]
            self.big.set_from_paintable(texture(svgs[0], 112))
            self.on_light.set_from_paintable(texture(svgs[1], 32))
            self.on_dark.set_from_paintable(texture(svgs[1], 32))
            self._show(True, _("Looks good. You can recolour it and add a tile or border after saving."))
        except Exception as e:  # noqa: BLE001 - any parse or render problem is shown, not raised
            self._show(None, _("It couldn't be drawn: {reason}").format(reason=e))
        finally:
            os.unlink(tmp)

    def _show(self, ok, message):
        if not ok:
            for img in (self.big, self.on_light, self.on_dark):
                img.clear()
        self.status.set_label(message)
        for cls in ("accent", "error-text", "dim"):
            self.status.remove_css_class(cls)
        self.status.add_css_class("accent" if ok else ("error-text" if self._text().strip() else "dim"))
        self.save.set_sensitive(bool(ok) and bool(self.name.get_text().strip()))

    def _save(self, *_a):
        try:
            path = icon_library.add_text(self._text(), self.name.get_text())
        except (OSError, icon_library.IconError) as e:
            self._show(None, str(e))
            return
        self._on_saved(path)
        self.close()
