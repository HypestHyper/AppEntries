"""Shows an entry file as code, with the lines a save would change marked."""
import difflib
from gettext import gettext as _

from gi.repository import Gtk

from .widgets import label, vbox

# What the common keys do, shown under the code.
KEY_HELP = [
    ("Name", _("the name launchers show")),
    ("Exec", _("the command that runs; %U, %F and friends are replaced by the files or links you open")),
    ("Icon", _("an icon name from your theme, or a path to an image")),
    ("Terminal", _("true runs it in a terminal window")),
    ("NoDisplay", _("true keeps it out of launcher menus; it still works for opening files and links")),
    ("Categories", _("the menu folders it's listed in")),
    ("OnlyShowIn / NotShowIn", _("the desktops that list it, or don't")),
    ("X-AppEntries-…", _("notes App Entries keeps for itself; launchers ignore keys starting with X-")),
]


class EntryView(Gtk.Box):
    def __init__(self, explanation):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.append(label(explanation, ("small", "dim"), wrap=True, chars=60))
        self.view = Gtk.TextView(monospace=True, editable=False, cursor_visible=False,
                                 wrap_mode=Gtk.WrapMode.CHAR, top_margin=10, bottom_margin=10,
                                 left_margin=12, right_margin=12)
        self.view.add_css_class("textarea")
        self.view.update_property([Gtk.AccessibleProperty.LABEL], [_("The entry file")])
        buf = self.view.get_buffer()
        self.changed_tag = buf.create_tag("changed", paragraph_background_rgba=None)
        self.append(self.view)
        lines = vbox(2)
        for key, text in KEY_HELP:
            lines.append(label("%s — %s" % (key, text), ("small", "faint"), wrap=True, chars=60))
        self.append(lines)
        self._last = None

    def set_colors(self, rgba):
        self.changed_tag.set_property("paragraph-background-rgba", rgba)

    def show(self, text, original=None):
        if (text, original) == self._last:
            return
        self._last = (text, original)
        buf = self.view.get_buffer()
        buf.set_text(text.rstrip("\n"))
        if original is None:
            return
        old = original.splitlines()
        new = text.splitlines()
        for tag, _i1, _i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new).get_opcodes():
            if tag in ("replace", "insert"):
                for line in range(j1, j2):
                    start = buf.get_iter_at_line(line)
                    start = start[1] if isinstance(start, tuple) else start
                    end = start.copy()
                    end.forward_to_line_end()
                    buf.apply_tag(self.changed_tag, start, end)
