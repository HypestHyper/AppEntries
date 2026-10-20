"""Pick an icon: a Material Symbol or one of your own SVG/PNG files, with a
tile shape, colour and border, and a live preview."""
import dataclasses
import os
from collections import OrderedDict
from gettext import gettext as _
from gettext import ngettext

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk

from .. import icon_library, symbols, theme
from .color_picker import ColorDot, ColorPicker
from .dialogs import Dialog, choose_file, error_dialog, run_bg
from .widgets import Group, Toggle, WrapBox, button, hbox, label, scroll_passes_through, vbox

_textures: "OrderedDict[tuple, Gdk.Texture]" = OrderedDict()


def texture(svg: str, size: int, key=None) -> Gdk.Texture:
    """A texture for SVG text, cached by key (the last 600 are kept)."""
    if key is not None and key in _textures:
        _textures.move_to_end(key)
        return _textures[key]
    loader = GdkPixbuf.PixbufLoader()
    loader.set_size(size, size)
    loader.write(svg.encode("utf-8"))
    loader.close()
    tex = Gdk.Texture.new_for_pixbuf(loader.get_pixbuf())
    if key is not None:
        _textures[key] = tex
        if len(_textures) > 600:
            _textures.popitem(last=False)
    return tex


def file_texture(path: str, size: int, ink: str = "") -> Gdk.Texture:
    """The file as it is, or, when `ink` is given and the file is a
    one-colour SVG, painted in `ink` so dark icons stay visible on a dark
    theme (and light ones on a light theme)."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = 0
    key = ("file", path, mtime, size, ink)
    if key in _textures:
        return _textures[key]
    if ink and icon_library.is_one_colour(path):
        try:
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                   'width="%d" height="%d" viewBox="0 0 960 960">%s</svg>'
                   % (size, size, icon_library.symbol_svg(path, ink, 0, "")))
            return texture(svg, size, key)
        except (OSError, ValueError, SyntaxError, GLib.Error, icon_library.IconError):
            pass  # draw the file as it is
    pb = GdkPixbuf.Pixbuf.new_from_file_at_size(path, size, size)
    tex = Gdk.Texture.new_for_pixbuf(pb)
    _textures[key] = tex
    return tex


def preview_texture(choice: symbols.IconChoice, size: int) -> Gdk.Texture:
    return texture(symbols.render(choice, size), size, ("full", choice.key(), size))


RECENT = 8  # how many recently used colours to keep


def _settings():
    app = Gio.Application.get_default()
    return getattr(app, "settings", None)


class IconPicker(Gtk.Window):
    """`on_pick(IconChoice)` is called when Use icon is pressed.

    With `style_for` (a number of icons), only the look is chosen: colour,
    background, border. Each of those icons keeps its own symbol."""

    def __init__(self, parent, choice, on_pick, glyph_color="#888888", style_for=0):
        super().__init__(transient_for=parent, modal=True, title=_("Choose an icon"))
        self._style_for = style_for
        self.add_css_class("prefs")
        self.set_default_size(980, 720)
        self.choice = dataclasses.replace(choice)
        self._on_pick = on_pick
        self._ink = glyph_color

        hb = Gtk.HeaderBar()
        hb.set_show_title_buttons(False)
        title = (ngettext("Style {n} icon", "Style {n} icons", style_for).format(n=style_for) if style_for
                 else _("Choose an icon"))
        hb.set_title_widget(label(title, ("title",)))
        cancel = button(_("Cancel"), style="tonal", small=True, cb=lambda *_a: self.close())
        self.use = button(ngettext("Apply to {n}", "Apply to {n}", style_for).format(n=style_for) if style_for
                          else _("Use icon"), style="filled", small=True, cb=self._use)
        for b in (cancel, self.use):
            b.set_valign(Gtk.Align.CENTER)
        hb.pack_start(cancel)
        hb.pack_end(self.use)
        self.set_titlebar(hb)

        # Left: which collection, search, and the grid.
        self.source = Group([("material", _("Material Symbols")), ("file", _("Your icons"))],
                            self.choice.source, self._on_source)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=150,
                               vexpand=True)
        self.stack.add_named(self._build_material(), "material")
        self.stack.add_named(self._build_library(), "file")
        left = vbox(12, self.source, self.stack)
        left.set_hexpand(True)
        if style_for:
            note = vbox(10, label(_("One look for all of them"), ("title",)),
                        label(_("Pick a colour, background and border on the right. Each icon keeps its own "
                                "symbol; only its look changes. The preview shows the first one."),
                              ("body", "dim"), wrap=True, chars=40))
            note.set_size_request(220, -1)
            note.set_valign(Gtk.Align.START)
            self.set_default_size(820, 720)
            note.set_margin_top(8)
            left = note

        # Right: preview and options, each explained.
        self.preview = Gtk.Image(pixel_size=96, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.preview_small = Gtk.Image(pixel_size=32, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.preview_dark = Gtk.Image(pixel_size=32, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        dark_tile = Gtk.Box(valign=Gtk.Align.CENTER)
        dark_tile.add_css_class("dark-sample")
        dark_tile.append(self.preview_dark)
        light_tile = Gtk.Box(valign=Gtk.Align.CENTER)
        light_tile.add_css_class("light-sample")
        light_tile.append(self.preview_small)
        self.name_label = label("", ("subheading",), xalign=0.5, ellipsize=True)
        samples = hbox(16, self.preview, vbox(8, light_tile, dark_tile))
        samples.set_halign(Gtk.Align.CENTER)
        prev = vbox(8, samples, self.name_label)
        prev.add_css_class("card-inner")
        prev.set_tooltip_text(_("How it looks large, and small on a light and a dark panel"))

        self.style_group = Group([("outlined", _("Outlined")), ("filled", _("Filled"))], self.choice.style,
                                 lambda v: self._set(style=v))
        self.style_box = self._option(_("Style"), _("Outlined icons are drawn with lines; filled ones are solid."),
                                      self.style_group)
        self.recolor = Toggle(self.choice.recolor, lambda v: self._set(recolor=v))
        self.recolor_box = self._switch(_("Recolour"), _("Paint the whole icon in the colour below. Turn off to "
                                                         "keep the file's own colours."), self.recolor)
        self.shape_group = Group([("none", _("None")), ("circle", _("Circle")), ("rounded", _("Square")),
                                  ("squircle", _("Soft"))], self.choice.shape, lambda v: self._set(shape=v))
        self.gradient_group = Group([("flat", _("Flat")), ("soft", _("Soft")), ("strong", _("Strong"))],
                                    self.choice.gradient, lambda v: self._set(gradient=v))
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 40, 80, 5)
        self.scale.set_value(self.choice.scale)
        self.scale.set_draw_value(True)
        self.scale.set_digits(0)
        self.scale.set_hexpand(True)
        if hasattr(self.scale, "set_format_value_func"):  # GTK 4.10+
            self.scale.set_format_value_func(lambda _s, v: "%d%%" % v)
        self.scale.update_property([Gtk.AccessibleProperty.LABEL], [_("Symbol size")])
        self.scale.connect("value-changed", lambda sc: self._set(scale=int(round(sc.get_value() / 5) * 5)))
        scroll_passes_through(self.scale)
        self.tile_detail = vbox(10, hbox(10, label(_("Shading"), ("body", "dim")), self.gradient_group),
                                hbox(10, label(_("Symbol size"), ("body", "dim")), self.scale),
                                label(_("Shading lights the tile from the top: Flat is one even colour, Strong adds "
                                        "depth. Symbol size is how much of the tile the symbol fills."),
                                      ("small", "dim"), wrap=True, chars=34))
        swatches = WrapBox(8, 8)
        self._swatches = {}
        first = None
        colors = [(s, _(n)) for s, n in theme.SEEDS] + [(s, _(n)) for s, n in theme.EXTRA_COLORS]
        for hexv, name in colors:
            b = Gtk.ToggleButton(tooltip_text=name)
            for c in ("swatch", "swatch-small", "swatch-" + hexv):
                b.add_css_class(c)
            b.update_property([Gtk.AccessibleProperty.LABEL], [_("Colour: {name}").format(name=name)])
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect("toggled", lambda btn, h=hexv: btn.get_active() and self._set(color="#" + h))
            swatches.append(b)
            self._swatches["#" + hexv] = b
        # Any other colour: picked right here, so the preview follows as you drag.
        self.color_picker = ColorPicker(self.choice.color, _("Icon colour"))
        self.color_picker.connect("changed", lambda _p, hexv: self._set(color=hexv))
        self.color_reveal = Gtk.Revealer(child=self.color_picker,
                                         transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.color_more = Gtk.ToggleButton(label=_("Other colour…"), halign=Gtk.Align.START)
        self.color_more.add_css_class("tonal")
        self.color_more.connect("toggled", lambda b: self.color_reveal.set_reveal_child(b.get_active()))
        self.color_more.set_active(("#" + self.choice.color.lstrip("#").lower()) not in self._swatches)
        self.recent = WrapBox(8, 8)
        self.recent_box = vbox(6, label(_("Recently used"), ("small", "dim")), self.recent)
        self._fill_recent()
        custom = vbox(10, self.recent_box, self.color_more, self.color_reveal)

        # Border
        self.border = Toggle(self.choice.border, lambda v: self._set(border=v))
        self.border_width = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 10, 1)
        self.border_width.set_value(self.choice.border_width)
        self.border_width.set_draw_value(True)
        self.border_width.set_digits(0)
        self.border_width.set_hexpand(True)
        self.border_width.update_property([Gtk.AccessibleProperty.LABEL], [_("Border width")])
        self.border_width.connect("value-changed", lambda s: self._set(border_width=int(round(s.get_value()))))
        scroll_passes_through(self.border_width)
        self.border_inner = Toggle(self.choice.border_inner, lambda v: self._set(border_inner=v))
        bc = self.choice.border_color
        self.border_color = Group([("auto", _("Auto")), ("white", _("White")), ("black", _("Black")),
                                   ("custom", _("Custom"))], "custom" if bc.startswith("#") else bc,
                                  self._on_border_kind)
        self.border_custom = ColorPicker(bc if bc.startswith("#") else "#6aa6ff", _("Border colour"))
        self.border_custom.connect("changed", lambda _p, hexv: self.border_color.active() == "custom"
                                   and self._set(border_color=hexv))
        self.border_reveal = Gtk.Revealer(child=self.border_custom, reveal_child=bc.startswith("#"),
                                          transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.inner_box = self._switch(_("Inner edges too"), _("Also outline the edges inside the icon, such as the "
                                                              "hole in a gear or the rings in a logo. On a tile, "
                                                              "this outlines the symbol itself."), self.border_inner)
        self.border_detail = vbox(10, hbox(10, label(_("Width"), ("body", "dim")), self.border_width),
                                  self.inner_box,
                                  label(_("Colour"), ("body", "dim")),
                                  self.border_color, self.border_reveal,
                                  label(_("Auto picks white or black, whichever stands out against the icon. "
                                          "Custom lets you pick any colour, and the preview follows as you drag."),
                                        ("small", "dim"), wrap=True, chars=34))

        right = vbox(16, self.style_box, self.recolor_box,
                     self._option(_("Background"), _("A coloured tile behind the icon, like most app icons. "
                                                     "None draws just the symbol in the colour."), self.shape_group),
                     self.tile_detail,
                     self._option(_("Colour"), _("The tile colour, or the symbol's colour when there's no tile. "
                                                 "The symbol turns dark or white to stay readable."),
                                  vbox(8, swatches, custom)),
                     vbox(10, self._switch(_("Border"), _("A thin outline around the icon, so it stays visible "
                                                          "when its colour is close to your panel's."), self.border),
                          self.border_detail))
        right.set_size_request(300, -1)
        right.set_margin_bottom(12)
        right.set_margin_end(14)  # room for the scrollbar
        self._options_scroll = rs = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_width=True,
                                vexpand=True)
        rs.set_child(right)
        # The preview stays in view while the options scroll under it.
        column = vbox(14, prev, rs)

        column.set_hexpand(bool(style_for))
        body = hbox(20, left, column)
        for side in ("start", "end", "bottom"):
            getattr(body, "set_margin_" + side)(20)
        body.set_margin_top(4)
        self.set_child(body)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, *_a: kv == Gdk.KEY_Escape and (self.close() or True))
        self.add_controller(keys)
        self._apply_style_class()
        self._refilter(select=self.choice.name)
        self._reload_library(select=self.choice.path)
        self.stack.set_visible_child_name(self.choice.source)
        self._update()

    # -- building -----------------------------------------------------------

    def _build_material(self):
        self.search = Gtk.SearchEntry(placeholder_text=_("Search {n} icons, for example: terminal, backup, game")
                                      .format(n=len(symbols.icons())))
        self.search.add_css_class("search-entry")
        self.search.connect("search-changed", lambda *_a: self._refilter())
        self.store = Gtk.StringList()
        self.selection = Gtk.SingleSelection(model=self.store, autoselect=False, can_unselect=False)
        self.selection.connect("selection-changed", self._on_selected)
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_glyph)
        factory.connect("bind", self._bind_glyph)
        self.grid = Gtk.GridView(model=self.selection, factory=factory, max_columns=14, min_columns=4)
        self.grid.add_css_class("icon-grid")
        self.grid.connect("activate", lambda *_a: self._use())
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, hexpand=True)
        scroll.set_child(self.grid)
        self.count = label("", ("small", "faint"))
        return vbox(10, self.search, scroll, self.count)

    def _build_library(self):
        self.lib_store = Gtk.StringList()
        self.lib_selection = Gtk.SingleSelection(model=self.lib_store, autoselect=False, can_unselect=False)
        self.lib_selection.connect("selection-changed", self._on_lib_selected)
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_file)
        factory.connect("bind", self._bind_file)
        self.lib_grid = Gtk.GridView(model=self.lib_selection, factory=factory, max_columns=10, min_columns=3)
        self.lib_grid.add_css_class("icon-grid")
        self.lib_grid.connect("activate", lambda *_a: self._use())
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, hexpand=True)
        scroll.set_child(self.lib_grid)
        self.lib_empty = label(_("No icons yet. Add an SVG or PNG file, or paste a link to one."),
                               ("body", "dim"), wrap=True, xalign=0.5, chars=40)
        self.lib_stack = Gtk.Stack(vexpand=True)
        self.lib_stack.add_named(scroll, "grid")
        self.lib_stack.add_named(self.lib_empty, "empty")
        add = button(_("Add file…"), "folder_open", "tonal", self._add_file, small=True,
                     tooltip=_("Copy an SVG or PNG into your icon library"))
        link = button(_("Add from link…"), "add", "tonal", self._add_link, small=True,
                      tooltip=_("Download an SVG or PNG into your icon library"))
        self.remove = button(_("Remove"), "delete", "text", self._remove, small=True,
                             tooltip=_("Delete the selected icon from your library"))
        paste = button(_("Paste SVG…"), "content_copy", "tonal", self._paste, small=True,
                       tooltip=_("Paste SVG code, preview it and save it to your icon library"))
        actions = hbox(8, add, link, paste)
        actions.get_last_child().set_hexpand(False)
        self.remove.set_halign(Gtk.Align.END)
        self.remove.set_hexpand(True)
        actions.append(self.remove)
        note = label(_("Your icons are kept in {folder}. Files you add are copied there, so a launcher keeps "
                       "its icon even if the original file is moved or deleted.")
                     .format(folder=icon_library.folder().replace(os.path.expanduser("~"), "~")),
                     ("small", "dim"), wrap=True, chars=60)
        return vbox(10, actions, self.lib_stack, note)

    def _option(self, title, explanation, widget):
        return vbox(6, label(title, ("body", "option-title")), widget,
                    label(explanation, ("small", "dim"), wrap=True, chars=34))

    def _switch(self, title, explanation, sw):
        head = hbox(12, label(title, ("body", "option-title")), sw)
        head.get_first_child().set_hexpand(True)
        sw.update_property([Gtk.AccessibleProperty.LABEL], [title])
        return vbox(4, head, label(explanation, ("small", "dim"), wrap=True, chars=34))

    def _on_border_kind(self, kind):
        self.border_reveal.set_reveal_child(kind == "custom")
        self._set(border_color=self.border_custom.hex() if kind == "custom" else kind)

    # -- state --------------------------------------------------------------

    def _on_source(self, source):
        self.stack.set_visible_child_name(source)
        self._set(source=source)

    def _set(self, **changes):
        for k, v in changes.items():
            setattr(self.choice, k, v)
        if "style" in changes:
            self._apply_style_class()
        self._update()

    def _apply_style_class(self):
        self.grid.remove_css_class("filled" if self.choice.style == "outlined" else "outlined")
        self.grid.add_css_class(self.choice.style)

    def _ready(self):
        if self._style_for:
            return True
        if self.choice.source == "file":
            return bool(self.choice.path) and os.path.isfile(self.choice.path)
        return self.choice.name in symbols.icons()

    def _update(self):
        c = self.choice
        is_file = c.source == "file"
        self.style_box.set_visible(not is_file)
        self.recolor_box.set_visible(is_file)
        self.border_detail.set_visible(c.border)
        self.tile_detail.set_visible(c.shape != "none")
        self.remove.set_sensitive(bool(c.path) and is_file)
        ready = self._ready()
        self.use.set_sensitive(ready)
        if ready:
            try:
                for img, size in ((self.preview, 96), (self.preview_small, 32), (self.preview_dark, 32)):
                    img.set_from_paintable(preview_texture(c, size))
            except (GLib.Error, OSError, KeyError, ValueError):
                self.preview.clear()
            name = os.path.basename(c.path) if is_file else c.name.replace("_", " ")
            self.name_label.set_label(name)
        else:
            for img in (self.preview, self.preview_small, self.preview_dark):
                img.clear()
            self.name_label.set_label(_("Pick an icon") if not is_file else _("Add or pick an icon"))
        b = self._swatches.get(c.color.lower())
        for other in self._swatches.values():
            if other is not b and other.get_active():
                other.set_active(False)
        if b is not None and not b.get_active():
            b.set_active(True)
        if self.color_picker.hex() != c.color.lower():
            self.color_picker.set_hex(c.color, emit=False)

    # -- Material grid ------------------------------------------------------

    def _refilter(self, select=None):
        names = symbols.search(self.search.get_text())
        self.store.splice(0, self.store.get_n_items(), names)
        self.count.set_label(_("{n} icons").format(n=len(names)) if names else _("No icons match"))
        if select in names:
            pos = names.index(select)
            self.selection.set_selected(pos)
            if hasattr(self.grid, "scroll_to"):
                GLib.idle_add(lambda: (self.grid.scroll_to(pos, Gtk.ListScrollFlags.NONE, None), False)[1])
        elif names and self.search.get_text():
            self.selection.set_selected(0)

    def _setup_glyph(self, _f, item):
        # A text label in an icon font: GTK caches the glyphs, so scrolling
        # through thousands of icons stays smooth.
        lb = Gtk.Label(accessible_role=Gtk.AccessibleRole.PRESENTATION)
        lb.add_css_class("picker-glyph")
        item.set_child(lb)

    def _bind_glyph(self, _f, item):
        name = item.get_item().get_string()
        lb = item.get_child()
        lb.set_label(chr(symbols.codepoint(name)))
        lb.set_tooltip_text(name.replace("_", " "))
        lb.update_property([Gtk.AccessibleProperty.LABEL], [name.replace("_", " ")])

    def _on_selected(self, sel, *_a):
        it = sel.get_selected_item()
        if it is not None and (it.get_string() != self.choice.name or self.choice.source != "material"):
            self.choice.name = it.get_string()
            self._update()

    # -- library grid -------------------------------------------------------

    def _reload_library(self, select=None):
        paths = icon_library.list_icons()
        self.lib_store.splice(0, self.lib_store.get_n_items(), paths)
        self.lib_stack.set_visible_child_name("grid" if paths else "empty")
        if select in paths:
            self.lib_selection.set_selected(paths.index(select))
        elif paths and self.choice.source == "file" and self.choice.path not in paths:
            self.choice.path = ""

    def _setup_file(self, _f, item):
        img = Gtk.Image(pixel_size=40, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        cell = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        cell.add_css_class("icon-cell")
        cell.append(img)
        item.set_child(cell)

    def _bind_file(self, _f, item):
        path = item.get_item().get_string()
        img = item.get_child().get_first_child()
        try:
            img.set_from_paintable(file_texture(path, 40, self._ink))
        except GLib.Error:
            img.set_from_icon_name("image-missing")
        item.get_child().set_tooltip_text(os.path.basename(path))
        item.get_child().update_property([Gtk.AccessibleProperty.LABEL], [os.path.basename(path)])

    def _on_lib_selected(self, sel, *_a):
        it = sel.get_selected_item()
        if it is not None:
            path = it.get_string()
            if path != self.choice.path:
                # Recolouring a full-colour icon turns it into a flat shape,
                # so it starts on only for one-colour icons.
                self.choice.recolor = icon_library.is_one_colour(path)
                self.recolor.set_value(self.choice.recolor)
            self.choice.path = path
            self.choice.source = "file"
            self._update()

    def _added(self, result):
        if isinstance(result, Exception):
            error_dialog(self, _("Couldn't add the icon"), str(result))
            return
        self._reload_library(select=result)
        self.choice.path = result
        self._update()

    def _add_file(self, *_a):
        def chosen(path):
            run_bg(lambda: icon_library.add_file(path), self._added)
        choose_file(self, _("Choose an SVG or PNG icon"), chosen, patterns=("*.svg", "*.png"))

    def _paste(self, *_a):
        from .paste_svg import PasteSvgWindow
        PasteSvgWindow(self, lambda path: self._added(path)).present()

    def _add_link(self, *_a):
        entry = Gtk.Entry(placeholder_text="https://…/icon.svg", hexpand=True, activates_default=True)
        entry.add_css_class("mono")
        where = vbox(4)
        for name, url, what, _paste in icon_library.SOURCES:
            link = Gtk.LinkButton(uri=url, label=name, halign=Gtk.Align.START)
            where.append(vbox(0, link, label(what, ("small", "dim"), wrap=True, chars=48)))

        def on_response(resp):
            url = entry.get_text().strip()
            if resp == "download" and url:
                run_bg(lambda: icon_library.download(url), self._added)

        d = Dialog(self, _("Add an icon from a link"),
                   _("Paste a link straight to an SVG or PNG file. It's downloaded into your icon library when "
                     "you press Download, and nothing else is fetched."),
                   [("cancel", _("Cancel"), "tonal"), ("download", _("Download"), "filled")], on_response,
                   icon_name="add")
        box = d.get_child()
        box.insert_child_after(entry, box.get_first_child().get_next_sibling().get_next_sibling())
        box.insert_child_after(vbox(6, label(_("Where to find icons"), ("body", "option-title")), where), entry)
        d.present()
        entry.grab_focus()

    def _remove(self, *_a):
        path = self.choice.path
        if not path:
            return

        def on_response(resp):
            if resp != "remove":
                return
            try:
                icon_library.remove(path)
            except (OSError, icon_library.IconError) as e:
                error_dialog(self, _("Couldn't remove the icon"), str(e), path)
                return
            self.choice.path = ""
            self._reload_library()
            self._update()

        Dialog(self, _("Remove {name} from your icons?").format(name=os.path.basename(path)),
               _("The file is deleted from your icon library. Launchers already using it keep a copy drawn "
                 "from it, so they aren't affected."),
               [("cancel", _("Cancel"), "tonal"), ("remove", _("Remove"), "danger")], on_response,
               icon_name="delete", icon_class="error-text", detail=path).present()

    def _use(self, *_a):
        if not self._ready():
            return
        self._remember_colors()
        self._on_pick(dataclasses.replace(self.choice))
        self.close()

    # -- recent colours -----------------------------------------------------

    def _fill_recent(self):
        settings = _settings()
        colors = [c for c in (settings.get("recent-colors") if settings else []) if c.startswith("#")]
        child = self.recent.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            child.unparent()
            child = nxt
        for hexv in colors[:RECENT]:
            b = Gtk.Button(tooltip_text=hexv)
            b.add_css_class("color-dot")
            b.set_child(ColorDot(hexv))
            b.update_property([Gtk.AccessibleProperty.LABEL], [_("Colour {hex}").format(hex=hexv)])
            b.connect("clicked", lambda _b, h=hexv: self._set(color=h))
            self.recent.append(b)
        self.recent_box.set_visible(bool(colors))

    def _remember_colors(self):
        settings = _settings()
        if settings is None:
            return
        used = [self.choice.color.lower()]
        if self.choice.border and self.choice.border_color.startswith("#"):
            used.append(self.choice.border_color.lower())
        known = {"#" + h for h, _n in theme.SEEDS + theme.EXTRA_COLORS}
        recent = [c for c in used if c not in known]
        recent += [c for c in settings.get("recent-colors") if c not in recent]
        settings.set("recent-colors", recent[:RECENT])
