"""An inline colour picker: a saturation/brightness square, a hue bar and a
hex field. It lives inside the window, so the preview updates as you drag."""
import colorsys
import re
from gettext import gettext as _

from gi.repository import Gdk, GObject, Graphene, Gsk, Gtk

from .widgets import hbox, label


def _rgba(r, g, b, a=1.0):
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r, g, b, a
    return c


def _stop(offset, rgba):
    s = Gsk.ColorStop()
    s.offset, s.color = offset, rgba
    return s


def _rect(x, y, w, h):
    return Graphene.Rect().init(x, y, w, h)


def _round(x, y, w, h, r):
    rr = Gsk.RoundedRect()
    rr.init_from_rect(_rect(x, y, w, h), r)
    return rr


def _ring(snapshot, cx, cy, radius):
    """A white ring with a dark edge, so the handle shows on any colour."""
    for r, color in ((radius + 1, _rgba(0, 0, 0, .45)), (radius, _rgba(1, 1, 1, 1))):
        snapshot.append_border(_round(cx - r, cy - r, 2 * r, 2 * r, r), [2, 2, 2, 2], [color] * 4)


class _Swatch(Gtk.Widget):
    """The picked colour."""

    def __init__(self, picker):
        super().__init__(accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.picker = picker
        self.set_size_request(36, 36)
        self.set_valign(Gtk.Align.CENTER)

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        snapshot.push_rounded_clip(_round(0, 0, w, h, 10))
        snapshot.append_color(_rgba(*colorsys.hsv_to_rgb(self.picker.h, self.picker.s, self.picker.v)),
                              _rect(0, 0, w, h))
        snapshot.pop()
        snapshot.append_border(_round(0, 0, w, h, 10), [1] * 4, [_rgba(.5, .5, .5, .4)] * 4)


class ColorDot(Gtk.Widget):
    """A round sample of one colour."""

    def __init__(self, hex_color, size=28):
        super().__init__(accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.set_size_request(size, size)
        self.rgba = Gdk.RGBA()
        self.rgba.parse(hex_color)

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        r = min(w, h) / 2
        snapshot.push_rounded_clip(_round(0, 0, w, h, r))
        snapshot.append_color(self.rgba, _rect(0, 0, w, h))
        snapshot.pop()
        snapshot.append_border(_round(0, 0, w, h, r), [1] * 4, [_rgba(.5, .5, .5, .45)] * 4)


class _Area(Gtk.Widget):
    """Saturation left to right, brightness bottom to top."""

    def __init__(self, picker):
        super().__init__(focusable=True, accessible_role=Gtk.AccessibleRole.SLIDER)
        self.picker = picker
        self.set_size_request(-1, 150)
        self.set_hexpand(True)
        self.set_cursor(Gdk.Cursor.new_from_name("crosshair"))
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", lambda g, x, y: self._at(x, y))
        drag.connect("drag-update", lambda g, dx, dy: self._at(g.get_start_point().x + dx,
                                                               g.get_start_point().y + dy))
        self.add_controller(drag)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)

    def _at(self, x, y):
        w, h = self.get_width(), self.get_height()
        self.picker.set_hsv(self.picker.h, min(1, max(0, x / max(w, 1))), min(1, max(0, 1 - y / max(h, 1))))
        self.grab_focus()

    def _key(self, _c, keyval, _code, _state):
        p, step = self.picker, 0.02
        moves = {Gdk.KEY_Left: (-step, 0), Gdk.KEY_Right: (step, 0), Gdk.KEY_Up: (0, step), Gdk.KEY_Down: (0, -step)}
        if keyval in moves:
            ds, dv = moves[keyval]
            p.set_hsv(p.h, min(1, max(0, p.s + ds)), min(1, max(0, p.v + dv)))
            return True
        return False

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        r, g, b = colorsys.hsv_to_rgb(self.picker.h, 1, 1)
        snapshot.push_rounded_clip(_round(0, 0, w, h, 12))
        snapshot.append_color(_rgba(r, g, b), _rect(0, 0, w, h))
        snapshot.append_linear_gradient(_rect(0, 0, w, h), Graphene.Point().init(0, 0), Graphene.Point().init(w, 0),
                                        [_stop(0, _rgba(1, 1, 1, 1)), _stop(1, _rgba(1, 1, 1, 0))])
        snapshot.append_linear_gradient(_rect(0, 0, w, h), Graphene.Point().init(0, 0), Graphene.Point().init(0, h),
                                        [_stop(0, _rgba(0, 0, 0, 0)), _stop(1, _rgba(0, 0, 0, 1))])
        snapshot.pop()
        _ring(snapshot, self.picker.s * w, (1 - self.picker.v) * h, 7)


class _HueBar(Gtk.Widget):
    def __init__(self, picker):
        super().__init__(focusable=True, accessible_role=Gtk.AccessibleRole.SLIDER)
        self.picker = picker
        self.set_size_request(-1, 18)
        self.set_hexpand(True)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", lambda g, x, y: self._at(x))
        drag.connect("drag-update", lambda g, dx, dy: self._at(g.get_start_point().x + dx))
        self.add_controller(drag)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)

    def _at(self, x):
        p = self.picker
        p.set_hsv(min(1, max(0, x / max(self.get_width(), 1))), p.s, p.v)
        self.grab_focus()

    def _key(self, _c, keyval, _code, _state):
        p = self.picker
        d = {Gdk.KEY_Left: -0.01, Gdk.KEY_Right: 0.01}.get(keyval)
        if d is None:
            return False
        p.set_hsv((p.h + d) % 1.0, p.s, p.v)
        return True

    def do_snapshot(self, snapshot):
        w, h = self.get_width(), self.get_height()
        stops = [_stop(i / 6, _rgba(*colorsys.hsv_to_rgb(i / 6 % 1.0, 1, 1))) for i in range(7)]
        snapshot.push_rounded_clip(_round(0, 3, w, h - 6, (h - 6) / 2))
        snapshot.append_linear_gradient(_rect(0, 3, w, h - 6), Graphene.Point().init(0, 0),
                                        Graphene.Point().init(w, 0), stops)
        snapshot.pop()
        _ring(snapshot, self.picker.h * w, h / 2, 8)


class ColorPicker(Gtk.Box):
    """Emits `changed(hex)` while you pick."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, hex_color="#6aa6ff", title=""):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("color-picker")
        self.h = self.s = self.v = 0.0
        self.area = _Area(self)
        self.area.update_property([Gtk.AccessibleProperty.LABEL],
                                  [_("{what}: saturation and brightness").format(what=title or _("Colour"))])
        self.hue = _HueBar(self)
        self.hue.update_property([Gtk.AccessibleProperty.LABEL], [_("{what}: hue").format(what=title or _("Colour"))])
        self.swatch = _Swatch(self)
        self.entry = Gtk.Entry(max_length=7, width_chars=8, hexpand=True)
        self.entry.add_css_class("mono")
        self.entry.update_property([Gtk.AccessibleProperty.LABEL], [_("Hex colour")])
        self.entry.connect("changed", self._typed)
        self.append(self.area)
        self.append(self.hue)
        self.append(hbox(10, self.swatch, label(_("Hex"), ("body", "dim")), self.entry))
        self._quiet = False
        self.set_hex(hex_color, emit=False)

    def hex(self):
        r, g, b = colorsys.hsv_to_rgb(self.h, self.s, self.v)
        return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))

    def set_hex(self, value, emit=True):
        m = re.fullmatch(r"#?([0-9a-fA-F]{6})", (value or "").strip())
        if not m:
            return
        v = m.group(1)
        r, g, b = (int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))
        h, s, val = colorsys.rgb_to_hsv(r, g, b)
        # Keep the hue when the colour is grey, so the bar doesn't jump.
        self.set_hsv(h if s > 0 else self.h, s, val, emit=emit)

    def set_hsv(self, h, s, v, emit=True):
        self.h, self.s, self.v = h, s, v
        hexv = self.hex()
        if self.entry.get_text().lower() != hexv:
            self._quiet = True
            self.entry.set_text(hexv)
            self._quiet = False
        self.swatch.queue_draw()
        self.area.queue_draw()
        self.hue.queue_draw()
        if emit:
            self.emit("changed", hexv)

    def _typed(self, entry):
        if not self._quiet and re.fullmatch(r"#?[0-9a-fA-F]{6}", entry.get_text().strip()):
            self.set_hex(entry.get_text())
