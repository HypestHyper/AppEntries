"""Small widget helpers used everywhere in the UI."""
import json
import os
from gettext import gettext as _

from gi.repository import Gdk, GLib, GObject, Graphene, Gsk, Gtk, Pango

_HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_HERE, "icons.json"), encoding="utf-8") as _f:
    ICONS = json.load(_f)

WRAP_CLASSES = {"small", "tiny", "faint"}


def glyph(name: str) -> str:
    cp = ICONS.get(name)
    return chr(cp) if cp else "?"


def _classes(w, classes):
    for c in classes or ():
        w.add_css_class(c)
    return w


def label(text, classes=(), wrap=False, xalign=0, chars=0, ellipsize=False):
    lb = Gtk.Label(label=text, xalign=xalign)
    _classes(lb, classes)
    if not wrap and len(text) > 60 and WRAP_CLASSES & set(classes):
        wrap = True
    if wrap:
        lb.set_wrap(True)
        lb.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        lb.set_max_width_chars(chars or 90)
        lb.set_width_chars(min(chars or 20, 20))
    elif chars:
        lb.set_max_width_chars(chars)
    if ellipsize:
        lb.set_ellipsize(Pango.EllipsizeMode.END)
    return lb


def icon(name, classes=()):
    lb = Gtk.Label(label=glyph(name), accessible_role=Gtk.AccessibleRole.PRESENTATION)
    lb.add_css_class("icon")
    return _classes(lb, classes)


def hbox(spacing=0, *children):
    b = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=spacing)
    for c in children:
        b.append(c)
    return b


def vbox(spacing=0, *children):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    for c in children:
        b.append(c)
    return b


def wrap_row(spacing=10, *children):
    fb = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=False,
                     min_children_per_line=1, max_children_per_line=24,
                     column_spacing=spacing, row_spacing=spacing, hexpand=True)
    for c in children:
        fb.append(c)
    return fb


def button(text="", icon_name=None, style="tonal", cb=None, small=False, tooltip=None,
           toggle=False):
    b = Gtk.ToggleButton() if toggle else Gtk.Button()
    for c in style.split():
        b.add_css_class(c)
    if small:
        b.add_css_class("small")
    if icon_name and text:
        b.set_child(hbox(8, icon(icon_name), Gtk.Label(label=text)))
    elif icon_name:
        b.set_child(icon(icon_name))
        b.add_css_class("circle")
        if tooltip is None:
            tooltip = text
    else:
        b.set_label(text)
    if tooltip:
        b.set_tooltip_text(tooltip)
        b.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
    if cb:
        b.connect("toggled" if toggle else "clicked", cb)
    return b


def option_button(icon_name, title, explanation, cb=None, danger=False):
    """A flat, full-width button with a title and a line saying what it does."""
    b = Gtk.Button()
    b.add_css_class("option")
    if danger:
        b.add_css_class("option-danger")
    text = vbox(2, label(title, ("body", "option-title")),
                label(explanation, ("small", "dim"), wrap=True, chars=36))
    text.set_hexpand(True)
    b.set_child(hbox(12, icon(icon_name), text))
    b.update_property([Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.DESCRIPTION],
                      [title, explanation])
    if cb:
        b.connect("clicked", cb)
    return b


class _WrapLayout(Gtk.LayoutManager):
    """Lays children out left to right, starting a new line when one doesn't
    fit, each at its natural width (unlike FlowBox, which uses columns)."""

    def __init__(self, spacing, row_spacing):
        super().__init__()
        self.spacing, self.row_spacing = spacing, row_spacing

    @staticmethod
    def _children(widget):
        c = widget.get_first_child()
        while c is not None:
            if c.get_visible():
                yield c
            c = c.get_next_sibling()

    def _rows(self, widget, width):
        rows, row, x = [], [], 0
        for c in self._children(widget):
            w = c.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
            if row and width >= 0 and x + self.spacing + w > width:
                rows.append(row)
                row, x = [], 0
            x += (self.spacing if row else 0) + w
            row.append((c, w))
        if row:
            rows.append(row)
        return rows

    def do_get_request_mode(self, widget):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, widget, orientation, for_size):
        kids = list(self._children(widget))
        if not kids:
            return 0, 0, -1, -1
        if orientation == Gtk.Orientation.HORIZONTAL:
            widths = [c.measure(orientation, -1)[1] for c in kids]
            return max(widths), sum(widths) + self.spacing * (len(widths) - 1), -1, -1
        height = 0
        for i, row in enumerate(self._rows(widget, for_size)):
            height += max(c.measure(orientation, w)[1] for c, w in row) + (self.row_spacing if i else 0)
        return height, height, -1, -1

    def do_allocate(self, widget, width, height, baseline):
        y = 0
        for row in self._rows(widget, width):
            row_h = max(c.measure(Gtk.Orientation.VERTICAL, w)[1] for c, w in row)
            x = 0
            for c, w in row:
                w = min(w, width)
                c.allocate(w, row_h, -1, Gsk.Transform().translate(Graphene.Point().init(x, y)))
                x += w + self.spacing
            y += row_h + self.row_spacing


class WrapBox(Gtk.Widget):
    """A box whose children wrap onto new lines like words."""

    def __init__(self, spacing=6, row_spacing=4):
        super().__init__()
        self.set_layout_manager(_WrapLayout(spacing, row_spacing))

    def append(self, child):
        child.set_parent(self)

    def do_dispose(self):
        c = self.get_first_child()
        while c is not None:
            nxt = c.get_next_sibling()
            c.unparent()
            c = nxt
        Gtk.Widget.do_dispose(self)


class _ClampLayout(Gtk.LayoutManager):
    def __init__(self, maximum):
        super().__init__()
        self.maximum = maximum

    def do_get_request_mode(self, widget):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, widget, orientation, for_size):
        child = widget.get_first_child()
        if child is None:
            return 0, 0, -1, -1
        if orientation == Gtk.Orientation.VERTICAL and for_size >= 0:
            for_size = min(for_size, self.maximum)
        mn, nat, _b1, _b2 = child.measure(orientation, for_size)
        if orientation == Gtk.Orientation.HORIZONTAL:
            nat = max(mn, min(nat, self.maximum))
        return mn, nat, -1, -1

    def do_allocate(self, widget, width, height, baseline):
        child = widget.get_first_child()
        if child is None:
            return
        w = max(min(width, self.maximum), child.measure(Gtk.Orientation.HORIZONTAL, -1)[0])
        x = max(0, (width - w) // 2)
        child.allocate(w, height, -1, Gsk.Transform().translate(Graphene.Point().init(x, 0)))


class Clamp(Gtk.Widget):
    """Centres one child and keeps it at most `maximum` pixels wide."""

    def __init__(self, child, maximum=760):
        super().__init__(hexpand=True)
        self.set_layout_manager(_ClampLayout(maximum))
        child.set_parent(self)

    def do_dispose(self):
        c = self.get_first_child()
        if c is not None:
            c.unparent()
        Gtk.Widget.do_dispose(self)


def scroll_passes_through(widget):
    """Let the mouse wheel scroll the page instead of changing a slider or
    menu under the pointer."""
    def on_scroll(ctrl, dx, dy):
        parent = widget.get_parent()
        while parent is not None and not isinstance(parent, Gtk.ScrolledWindow):
            parent = parent.get_parent()
        if parent is not None:
            adj = parent.get_vadjustment()
            adj.set_value(adj.get_value() + dy * 48)
        return True  # never change the widget's value

    ctrl = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
    ctrl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
    ctrl.connect("scroll", on_scroll)
    widget.add_controller(ctrl)


def card(inner=False):
    b = vbox(12)
    b.add_css_class("card-inner" if inner else "card")
    return b


def section(title, sub=None):
    b = vbox(2)
    b.set_margin_top(18)
    b.set_margin_bottom(6)
    b.set_margin_start(4)
    b.append(label(title, ("title",)))
    if sub:
        b.append(label(sub, ("small", "dim"), wrap=True, chars=90))
    return b


def divider():
    return Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)


def clear(container):
    child = container.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        container.remove(child)
        child = nxt


def set_text(lb: Gtk.Label, text: str):
    """set_label only when the text changed."""
    if lb.get_label() != text:
        lb.set_label(text)


def spinner():
    """A spinning progress glyph. GTK's Spinner draws its icon from the icon
    theme, which can hold up the first frame."""
    s = icon("progress_activity", ("spinner-glyph", "accent"))
    s.set_halign(Gtk.Align.CENTER)
    return s


class SearchField(Gtk.Box):
    """A search box drawn with the app's own icons. GTK's SearchEntry looks
    its icons up in the icon theme, which waits until the whole theme has
    loaded (a tenth of a second or more with big themes, before the window
    can first appear); this doesn't. It works like SearchEntry:
    "search-changed" a moment after typing stops, "search-activate" on
    Enter, Esc clears it, and set_key_capture_widget() starts a search when
    you type anywhere in that widget."""
    __gsignals__ = {
        "search-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "search-activate": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }
    DELAY = 150   # ms, as SearchEntry

    def __init__(self, placeholder="", width_chars=14, label_text=""):
        super().__init__(spacing=10, hexpand=True, valign=Gtk.Align.CENTER)
        self.add_css_class("search-field")
        self.append(icon("search", ("dim",)))
        self.text = Gtk.Text(hexpand=True, width_chars=width_chars, placeholder_text=placeholder,
                             valign=Gtk.Align.CENTER)
        if label_text:
            self.text.update_property([Gtk.AccessibleProperty.LABEL], [label_text])
        self.append(self.text)
        self.clear_btn = button(icon_name="close", style="text", small=True, tooltip=_("Clear the search"),
                                cb=lambda *_a: (self.set_text(""), self.text.grab_focus()))
        self.clear_btn.set_visible(False)
        self.clear_btn.set_valign(Gtk.Align.CENTER)
        self.append(self.clear_btn)
        self._timer = 0
        self.text.connect("changed", self._changed)
        self.text.connect("activate", lambda *_a: self._fire() or self.emit("search-activate"))
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.text.add_controller(keys)
        click = Gtk.GestureClick()
        click.connect("pressed", lambda *_a: self.text.grab_focus())
        self.add_controller(click)

    def get_text(self):
        return self.text.get_text()

    def set_text(self, value):
        self.text.set_text(value)
        self.text.set_position(-1)

    def grab_focus(self):
        return self.text.grab_focus()

    def _changed(self, *_a):
        self.clear_btn.set_visible(bool(self.text.get_text()))
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(self.DELAY, self._fire)

    def _fire(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
            self.emit("search-changed")
        return False

    def _key(self, _c, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape and self.text.get_text():
            self.set_text("")
            return True
        return False

    def set_key_capture_widget(self, widget):
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._captured, widget)
        widget.add_controller(keys)

    def _captured(self, _c, keyval, _code, state, widget):
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK | Gdk.ModifierType.SUPER_MASK):
            return False
        root = widget.get_root()
        focus = root.get_focus() if root is not None else None
        if isinstance(focus, Gtk.Editable) or (focus is not None and focus.is_ancestor(self)):
            return False
        ch = chr(Gdk.keyval_to_unicode(keyval) or 0)
        if not ch.isprintable() or ch in ("", " ", "\x00"):
            return False
        self.text.grab_focus()
        self.set_text(self.text.get_text() + ch)
        return True


class Toggle(Gtk.Switch):
    """A switch whose callback fires only on user changes."""

    def __init__(self, active=False, cb=None):
        super().__init__(active=active, valign=Gtk.Align.CENTER)
        # The on/off icons inside are transparent in this app's style, but
        # drawing them still looks them up in the icon theme, which holds up
        # the first frame until the whole theme has loaded. So they're hidden.
        child = self.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.Image):
                child.set_visible(False)
            child = child.get_next_sibling()
        self._quiet = False
        self._cb = cb
        self.connect("notify::active", self._changed)

    def _changed(self, *_):
        if not self._quiet and self._cb:
            self._cb(self.get_active())

    def set_value(self, v):
        if self.get_active() != bool(v):
            self._quiet = True
            self.set_active(bool(v))
            self._quiet = False


def switch_row(text, active, cb):
    sw = Toggle(active, cb)
    lb = label(text, ("body",))
    lb.set_hexpand(True)
    sw.update_property([Gtk.AccessibleProperty.LABEL], [text])
    return hbox(12, lb, sw), sw


class Group(Gtk.Box):
    """Connected toggle buttons, exactly one checked."""

    def __init__(self, items, active, cb=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.add_css_class("group")
        self._cb = cb
        self._quiet = False
        self._buttons = {}
        first = None
        for item in items:
            key, text = item[0], item[1]
            b = Gtk.ToggleButton()
            b.set_child(hbox(6, icon(item[2]), Gtk.Label(label=text)) if len(item) > 2 else Gtk.Label(label=text))
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect("toggled", self._toggled, key)
            self._buttons[key] = b
            self.append(b)
        self.set_active(active)

    def _toggled(self, b, key):
        if b.get_active() and not self._quiet and self._cb:
            self._cb(key)

    def set_active(self, key):
        b = self._buttons.get(key)
        if b and not b.get_active():
            self._quiet = True
            b.set_active(True)
            self._quiet = False

    def active(self):
        for k, b in self._buttons.items():
            if b.get_active():
                return k
        return None


class Chip(Gtk.Box):
    """Status pill with a leading icon."""
    KINDS = {"ok": "check_circle", "warn": "bedtime", "error": "error", "": "info"}

    def __init__(self, text="", kind="ok"):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.add_css_class("chip")
        self.add_css_class("tnum")
        self._icon = icon(self.KINDS.get(kind, "info"), ("filled",))
        self._label = Gtk.Label(label=text)
        self.append(self._icon)
        self.append(self._label)
        self._kind = ""
        self.set(text, kind)

    def set(self, text, kind="ok"):
        set_text(self._label, text)
        if kind != self._kind:
            if self._kind:
                self.remove_css_class(self._kind)
            if kind:
                self.add_css_class(kind)
            self._kind = kind
            set_text(self._icon, glyph(self.KINDS.get(kind, "info")))


class TabBar(Gtk.Box):
    """A scrollable tab bar; chevrons show only when the tabs overflow."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, (str,))}

    def __init__(self, items, active):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.bar = hbox(2)
        self.bar.add_css_class("tabbar")
        self.bar.set_halign(Gtk.Align.START)
        self._buttons = {}
        self._counts = {}
        self._quiet = False
        first = None
        for item in items:
            # (key, text, icon) or (key, text, icon, True) for a tab shown as just its icon.
            key, text, icon_name = item[:3]
            b = Gtk.ToggleButton()
            count = Gtk.Label(label="", visible=False)
            count.add_css_class("tabcount")
            count.add_css_class("tnum")
            if len(item) > 3 and item[3]:
                b.set_child(hbox(6, icon(icon_name), count))
                b.set_tooltip_text(text)
                b.add_css_class("icon-tab")
            else:
                b.set_child(hbox(8, icon(icon_name), Gtk.Label(label=text), count))
            b.update_property([Gtk.AccessibleProperty.LABEL], [text])
            if first is None:
                first = b
            else:
                b.set_group(first)
            b.connect("toggled", self._toggled, key)
            self._buttons[key] = b
            self._counts[key] = count
            self.bar.append(b)

        self.scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.EXTERNAL,
                                           vscrollbar_policy=Gtk.PolicyType.NEVER,
                                           propagate_natural_width=True, hexpand=True)
        self.scroller.set_child(self.bar)
        self._left = button(icon_name="chevron_left", style="flat", small=True, tooltip=_("Scroll left"),
                            cb=lambda *_: self._scroll(-1))
        self._right = button(icon_name="chevron_right", style="flat", small=True, tooltip=_("Scroll right"),
                             cb=lambda *_: self._scroll(1))
        for b in (self._left, self._right):
            b.set_valign(Gtk.Align.CENTER)
            b.set_visible(False)
        self.append(self._left)
        self.append(self.scroller)
        self.append(self._right)
        adj = self.scroller.get_hadjustment()
        adj.connect("changed", self._update_arrows)
        adj.connect("value-changed", self._update_arrows)
        self.set_active(active)

    def _scroll(self, d):
        adj = self.scroller.get_hadjustment()
        adj.set_value(adj.get_value() + d * adj.get_page_size() * 0.6)

    def _update_arrows(self, adj):
        over = adj.get_upper() - adj.get_page_size() > 1
        left = over and adj.get_value() > 1
        right = over and adj.get_value() < adj.get_upper() - adj.get_page_size() - 1
        if self._left.get_visible() != left:
            self._left.set_visible(left)
        if self._right.get_visible() != right:
            self._right.set_visible(right)

    def _toggled(self, b, key):
        if b.get_active() and not self._quiet:
            self.emit("changed", key)

    def set_active(self, key):
        b = self._buttons.get(key)
        if b and not b.get_active():
            self._quiet = True
            b.set_active(True)
            self._quiet = False

    def set_count(self, key, n):
        lb = self._counts.get(key)
        if lb is not None:
            set_text(lb, str(n))
            lb.set_visible(str(n) != "")


class Snackbar(Gtk.Revealer):
    """Bottom-centre confirmation with an optional action. Shows for 3.5 s."""

    def __init__(self):
        super().__init__(transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
                         transition_duration=220, halign=Gtk.Align.CENTER,
                         valign=Gtk.Align.END, reveal_child=False)
        self._label = Gtk.Label(xalign=0, wrap=True, max_width_chars=48)
        self._action = Gtk.Button()
        self._action.connect("clicked", self._on_action)
        box = hbox(16, self._label, self._action)
        box.add_css_class("snackbar")
        self._label.set_hexpand(True)
        self.set_child(box)
        self._timer = 0
        self._cb = None
        self.set_can_target(False)
        self.connect("notify::child-revealed", self._on_revealed)

    def show(self, text, action=None, cb=None, seconds=3.5):
        self._label.set_label(text)
        self._cb = cb
        self._action.set_visible(bool(action))
        if action:
            self._action.set_label(action)
        self.set_can_target(True)
        self.set_reveal_child(True)
        self._label.update_property([Gtk.AccessibleProperty.LABEL], [text])
        if hasattr(self._label, "announce"):  # GTK 4.14+
            self._label.announce(text, Gtk.AccessibleAnnouncementPriority.MEDIUM)
        if self._timer:
            GLib.source_remove(self._timer)
        self._timer = GLib.timeout_add(int(seconds * 1000), self._hide)

    def _hide(self):
        self._timer = 0
        self.set_reveal_child(False)
        return False

    def _on_revealed(self, *_):
        if not self.get_child_revealed():
            self.set_can_target(False)

    def _on_action(self, *_):
        cb, self._cb = self._cb, None
        if self._timer:
            GLib.source_remove(self._timer)
        self._hide()
        if cb:
            cb()
