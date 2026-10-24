"""How long GTK takes to create an empty window, outside App Entries.

    python3 tools/time-window.py icon|noicon     (GSK_RENDERER=gl|vulkan|cairo to compare)

"icon" creates it with a default window icon name, as most apps do, so GTK
looks the icon up in the icon theme; "noicon" without one. The difference
is the wait for the icon theme; what's left is the renderer and the display.
"""
import ctypes
import os
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

Gtk.Window.set_default_icon_name("io.github.HypestHyper.AppEntries")


class Test(Gtk.Application):
    def do_activate(self):
        if sys.argv[1:] == ["noicon"]:
            unset = ctypes.CDLL("libgtk-4.so.1").gtk_window_set_default_icon_name
            unset.argtypes = [ctypes.c_char_p]
            unset(None)
        w = Gtk.Window(application=self)
        t = time.perf_counter()
        w.realize()
        print("%-7s %-8s %5.0f ms  %s" % ((sys.argv[1:] or ["icon"])[0], os.environ.get("GSK_RENDERER", "default"),
                                          (time.perf_counter() - t) * 1000, type(w.get_renderer()).__name__))
        self.quit()


app = Test(application_id="io.github.HypestHyper.TimeWindow")
app.set_resource_base_path(None)
app.run([])
