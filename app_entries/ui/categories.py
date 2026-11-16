"""Menu folders for a launcher: the main categories, and under each one
picked, the more detailed ones that go with it."""
from gettext import gettext as _

from gi.repository import Gtk

from .. import editing
from .widgets import WrapBox, label, vbox


class CategoryPicker(Gtk.Box):
    """Chips for the main categories; picking one shows its detailed ones
    (Photography, Web browser, Strategy…). A detailed one that goes with
    several main ones is one choice, shown under each. Categories it
    doesn't know are kept as they are. `on_change()` runs after each change."""

    def __init__(self, selected, on_change=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        selected = list(selected)
        self._on_change = on_change
        self._quiet = False
        self._extra = {c for c in selected if c in editing.EXTRA_KEYS}
        self._kept = [c for c in selected if not editing.known_category(c)]
        self.main_buttons = {}
        self._extra_buttons = {}        # key -> [chips under each main it goes with]
        self._rows = {}
        mains = WrapBox(6, 6)
        self.append(mains)
        more = vbox(12)
        self.append(more)
        for key, text in editing.MAIN_CATEGORIES:
            b = Gtk.ToggleButton(label=_(text), active=key in selected)
            b.add_css_class("filter")
            b.connect("toggled", self._main_toggled, key)
            mains.append(b)
            self.main_buttons[key] = b
            chips = WrapBox(6, 6)
            for ekey, etext in editing.EXTRA_CATEGORIES.get(key, []):
                c = Gtk.ToggleButton(label=_(etext), active=ekey in self._extra)
                c.add_css_class("filter")
                c.add_css_class("small")
                c.connect("toggled", self._extra_toggled, ekey)
                chips.append(c)
                self._extra_buttons.setdefault(ekey, []).append(c)
            row = vbox(6, label(_("More detail in {folder}").format(folder=_(text)), ("small", "dim")), chips)
            row.set_visible(b.get_active())
            more.append(row)
            self._rows[key] = row

    def _main_toggled(self, b, key):
        self._rows[key].set_visible(b.get_active())
        self._changed()

    def _extra_toggled(self, b, key):
        if self._quiet:
            return
        on = b.get_active()
        (self._extra.add if on else self._extra.discard)(key)
        self._quiet = True
        for other in self._extra_buttons[key]:
            if other is not b:
                other.set_active(on)
        self._quiet = False
        self._changed()

    def _changed(self):
        if self._on_change:
            self._on_change()

    def selected(self) -> list[str]:
        """The categories to write: main ones picked, detailed ones whose
        main one is picked, and any it doesn't know, kept."""
        mains = [k for k, b in self.main_buttons.items() if b.get_active()]
        extra = [k for k in editing.EXTRA_KEYS if k in self._extra and
                 any(k in dict(editing.EXTRA_CATEGORIES.get(m, [])) for m in mains)]
        return editing.order_categories(mains + extra + self._kept)
