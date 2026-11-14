"""The main window."""
import os
import subprocess
from gettext import gettext as _
from gettext import ngettext

from gi.repository import Gdk, Gio, GLib, Gtk

from .. import (
    APP_ID,
    APP_NAME,
    appimages,
    autostart,
    desktop_entries,
    editing,
    health,
    history,
    icon_lookup,
    launcher_refresh,
    launchers,
    overrides,
    packages,
    profile,
    seen,
    symbols,
    terminal,
    timing,
    trash,
    uninstall,
    webapps,
)
from ..model import AppItem, AppStore
from .app_card import forget_icons, label_for_source
from .app_row import AppRow
from .dialogs import Dialog, choose_file, error_dialog, run_bg
from .style import SIZES
from .widgets import (
    Clamp,
    NavRail,
    SearchField,
    Segmented,
    Snackbar,
    WrapBox,
    button,
    hbox,
    icon,
    label,
    set_text,
    spinner,
    vbox,
)


def _lazy(module, name):
    """A window class loaded the first time it's opened, so its code doesn't
    slow down start-up."""
    def make(*args, **kwargs):
        import importlib
        return getattr(importlib.import_module(module, __package__), name)(*args, **kwargs)
    return make


HelpersWindow = _lazy(".helpers_window", "HelpersWindow")
HistoryWindow = _lazy(".history_window", "HistoryWindow")
UninstallWindow = _lazy(".uninstall_window", "UninstallWindow")
BatchUninstallWindow = _lazy(".uninstall_window", "BatchUninstallWindow")
IconPicker = _lazy(".icon_picker", "IconPicker")
LauncherWindow = _lazy(".launcher_window", "LauncherWindow")
WebAppWindow = _lazy(".webapp_window", "WebAppWindow")
IssuesPage = _lazy(".issues", "IssuesPage")
AutostartPage = _lazy(".autostart_page", "AutostartPage")
DefaultsPage = _lazy(".defaults_page", "DefaultsPage")
SettingsPage = _lazy(".settings_page", "SettingsPage")
UpdatesPage = _lazy(".updates", "UpdatesPage")
from .app_page import AppPage  # noqa: E402 - shown with the list, so not lazy
from .status_bar import StatusBar  # noqa: E402

# The places in the navigation rail: (setting value, label, icon).
RAIL = [
    ("all", _("Apps"), "apps"),
    ("mine", _("Launchers"), "rocket_launch"),
    ("issues", _("Issues"), "healing"),
    ("autostart", _("Autostart"), "power_settings_new"),
    ("defaults", _("Defaults"), "star"),
]
RAIL_BOTTOM = [
    ("updates", _("Updates"), "system_update_alt"),
    ("settings", _("Settings"), "tune"),
]
# Older versions had Hidden and Customised as tabs; they're views of Apps now.
LEGACY_FILTERS = {"hidden": ("view", "hidden"), "customised": ("only", "customised"), "system": None}
PAGES = ("issues", "autostart", "defaults", "settings", "updates")  # tabs that aren't app lists
SELF_ID = APP_ID + ".desktop"
COMPACT_BELOW = 900
SPLIT_FROM = 860        # window width from which the list and the app page sit side by side
LIST_WIDTH = 440
LIST_MAX = 600          # the list is never wider, so each row's eye stays near its name
HISTORY_WIDTH = 400     # the History panel, with its margins
HYSTERESIS = 60


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app, settings, style):
        super().__init__(application=app, title=APP_NAME)
        self.settings = settings
        self.style = style
        self.apps = AppStore()
        self._scan_gen = 0
        self._rescan_timer = 0
        self._monitors = []
        self._compact = None
        self._loaded = False
        self._query = ""
        self._selecting = False
        self.history_window = None

        self.set_default_size(settings.get("window-width"), settings.get("window-height"))
        if settings.get("maximized"):
            self.maximize()

        self._build_header()
        self._build_body()
        self._build_actions()
        self._apply_window_controls()
        settings.connect(self._on_setting)
        self.connect("close-request", self._save_size)
        self.connect("close-request", self._close_with_drafts)

        self.rescan()
        self._watch_dirs()

    # ------------------------------------------------------------------ UI

    def _build_header(self):
        hb = Gtk.HeaderBar()
        hb.set_show_title_buttons(False)
        hb.set_title_widget(Gtk.Box())
        self.logo = Gtk.Image(pixel_size=40, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.refresh_logo()
        title = label(APP_NAME, ("app-title",))
        self._start = hbox(12, self.logo, title)
        self._start.set_margin_start(4)
        hb.pack_start(self._start)

        self.refresh_btn = button(icon_name="refresh", style="tonal", small=True,
                                  tooltip=_("Refresh applications (Ctrl+R)"))
        self.refresh_btn.set_action_name("app.refresh")

        self.refresh_btn.set_valign(Gtk.Align.CENTER)

        self.winctl = hbox(4)
        self.winctl.add_css_class("winctl")
        self.winctl.set_valign(Gtk.Align.CENTER)
        self.history_btn = button(icon_name="history", style="tonal", small=True,
                                  tooltip=_("History: undo any change you made (Ctrl+H)"),
                                  cb=self.show_history)
        self.history_btn.set_valign(Gtk.Align.CENTER)
        self._end = hbox(8, self.history_btn, self.refresh_btn)
        self._end.set_margin_end(4)
        hb.pack_end(self._end)
        self.header = hb
        self.set_titlebar(hb)

    def _build_body(self):
        content = vbox(14)
        content.set_margin_top(4)
        content.set_margin_bottom(14)
        content.set_margin_end(20)
        content.set_hexpand(True)

        self._only = set()      # extra filters from the Filter menu: customised, new
        f = self.settings.get("filter")
        if f in LEGACY_FILTERS:
            what = LEGACY_FILTERS[f]
            if what and what[0] == "view":
                self.settings.set("view", what[1])
            elif what:
                self._only.add(what[1])
            self.settings.set("filter", "all")
        elif f in ("settings", "updates", "autostart", "defaults"):
            self.settings.set("filter", "all")  # start on the apps, not where you left off
        self.rail = NavRail(RAIL, RAIL_BOTTOM, self.settings.get("filter"))
        self.rail.connect("changed", lambda _r, key: self.settings.set("filter", key))
        self.rail.set_margin_start(8)
        self.rail.set_margin_end(8)
        self.rail.set_margin_bottom(10)

        # Always-visible search; typing anywhere in the window starts it.
        self.search_entry = SearchField(_("Search apps"), 14, _("Search apps"))
        self.search_entry.set_tooltip_text(_("Search by name, description, command or file ID (Ctrl+F)"))
        self.search_entry.set_key_capture_widget(self)
        self.search_entry.connect("search-changed", self._on_search)
        self.search_entry.connect("search-activate", self._on_search_activate)

        # Shown, Hidden or All: hidden apps stay out of the way unless asked for.
        self.view_seg = Segmented([("shown", _("Shown")), ("hidden", _("Hidden")), ("all", _("All"))],
                                  self.settings.get("view"))
        self.view_seg.connect("changed", lambda _s, key: self.settings.set("view", key))
        self.view_seg.set_tooltip_text(_("Apps shown in launcher menus, the ones hidden from them, or both"))

        # Where apps come from, and the other filters, in one menu.
        current = self.settings.get("source")
        self._sources = [("any", _("All sources"))] + ([(current, label_for_source(current))]
                                                         if current in health.SOURCES else [])
        # A menu button with the app's own arrow: GTK's DropDown draws its arrow
        # from the icon theme, which holds up the first frame.
        self.filter_label = Gtk.Label(label=_("Filter"))
        self.filter_menu = Gtk.MenuButton(valign=Gtk.Align.CENTER)
        self.filter_dot = Gtk.Box(valign=Gtk.Align.START, visible=False)
        self.filter_dot.add_css_class("draft-dot")
        self.filter_menu.set_child(hbox(4, icon("tune"), self.filter_dot))
        self.filter_menu.add_css_class("tonal")
        self.filter_menu.add_css_class("list-tool")
        self.filter_menu.add_css_class("source-menu")
        self.filter_menu.set_tooltip_text(_("Only list apps from one source, customised ones or new ones, and "
                                            "whether to include apps that aren't in menus"))
        self.filter_menu.update_property([Gtk.AccessibleProperty.LABEL], [_("Filter")])
        self.filter_menu.set_create_popup_func(self._filter_popup)
        self.sort_label = Gtk.Label(label=self._sort_text())
        self.sort_menu = Gtk.MenuButton(valign=Gtk.Align.CENTER)
        self.sort_menu.set_child(icon("sort"))
        self.sort_menu.add_css_class("tonal")
        self.sort_menu.add_css_class("list-tool")
        self.sort_menu.add_css_class("source-menu")
        self.sort_menu.set_tooltip_text(_("Sort: {how}").format(how=self._sort_text()))
        self.sort_menu.update_property([Gtk.AccessibleProperty.LABEL], [_("Sort")])
        self.sort_menu.set_create_popup_func(self._sort_popup)
        self.select_btn = Gtk.ToggleButton(valign=Gtk.Align.CENTER)
        self.select_btn.set_child(icon("checklist"))
        self.select_btn.add_css_class("tonal")
        self.select_btn.add_css_class("list-tool")
        self.select_btn.set_tooltip_text(_("Pick several apps, then hide, show or restore them together"))
        self.select_btn.update_property([Gtk.AccessibleProperty.LABEL], [_("Select several apps")])
        self.select_btn.connect("toggled", lambda b: self.set_selecting(b.get_active()))
        # On Launchers, making a new one takes the place of Shown/Hidden/All.
        self.new_btns = hbox(8,
                             button(_("New launcher"), "add", "filled", small=True,
                                    tooltip=_("Make a launcher for a program, a script or commands (Ctrl+N)"),
                                    cb=lambda *_: self.new_launcher()),
                             button(_("New web app"), "language", "tonal", small=True,
                                    tooltip=_("Open a site in its own window, without the address bar "
                                              "(Ctrl+Shift+N)"),
                                    cb=lambda *_: self.new_web_app()))
        self.new_btns.set_valign(Gtk.Align.CENTER)
        # The list's own controls, at its top: search, then which apps and how.
        row = hbox(8, self.view_seg, self.new_btns)
        gap = Gtk.Box(hexpand=True)
        row.append(gap)
        for w in (self.filter_menu, self.sort_menu, self.select_btn):
            row.append(w)
        self.toolbar = Clamp(vbox(10, self.search_entry, row), LIST_MAX, start=True)
        self.toolbar.set_margin_end(4)
        # While searching Shown or Hidden, a line says when the other view
        # has matches too, with a button to see them.
        self.hint_text = label("", ("small", "dim"))
        self.hint_btn = button("", style="text", small=True, cb=lambda *_: self.settings.set("view", "all"))
        self.hint = hbox(8, icon("info", ("dim",)), self.hint_text, self.hint_btn)
        self.hint.set_margin_start(8)
        self.hint.set_visible(False)


        # Model: store -> filter -> sort -> grid
        self.filter = Gtk.CustomFilter.new(self._match)
        filtered = Gtk.FilterListModel(model=self.apps.store, filter=self.filter)
        self.sorter = Gtk.CustomSorter.new(self._compare)
        self.sorted = Gtk.SortListModel(model=filtered, sorter=self.sorter)
        self.sorted.connect("items-changed", lambda *_: self._update_state())

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup_card)
        factory.connect("bind", lambda _f, li: li.get_child().bind(li.get_item()))
        factory.connect("unbind", lambda _f, li: li.get_child().unbind())
        self.grid = Gtk.ListView(model=Gtk.NoSelection(model=self.sorted), factory=factory,
                                 single_click_activate=False)
        self.grid.add_css_class("app-list")
        self.grid.connect("activate", self._on_activate)
        # Space hides or shows the app whose row has focus; Menu or
        # Shift+F10 opens its options.
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_list_key)
        self.grid.add_controller(keys)
        self.grid.update_property([Gtk.AccessibleProperty.LABEL], [_("Applications")])
        grid_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        grid_scroll.set_child(self.grid)
        self.grid_scroll = grid_scroll

        self.empty_title = label("", ("title",), xalign=0.5)
        self.empty_body = label("", ("body", "dim"), wrap=True, xalign=0.5, chars=50)
        self.empty_body.set_justify(Gtk.Justification.CENTER)
        self.empty_actions = WrapBox(8, 8)
        self.empty_actions.set_halign(Gtk.Align.CENTER)
        self.empty_actions.set_margin_top(8)
        empty = vbox(10, icon("search_off", ("big", "empty-icon")), self.empty_title, self.empty_body,
                     self.empty_actions)
        empty.set_valign(Gtk.Align.CENTER)
        empty.set_halign(Gtk.Align.CENTER)
        empty.set_margin_bottom(60)

        loading = vbox(12, spinner(),
                       label(_("Looking for apps…"), ("body", "dim"), xalign=0.5))
        loading.set_valign(Gtk.Align.CENTER)
        loading.set_halign(Gtk.Align.CENTER)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE,
                               transition_duration=180, hhomogeneous=False, vexpand=True)
        self.stack.add_named(loading, "loading")
        self.stack.add_named(Clamp(grid_scroll, LIST_MAX, start=True), "grid")
        self.stack.add_named(empty, "empty")
        # The other tabs' pages are built the first time they're opened
        # (_ensure_page), so they don't slow down start-up.
        self.issues = self.autostart = self.defaults = None
        updates = self.get_application().updates
        updates.connect(lambda: self.rail.set_count("updates", "1" if updates.release else ""))
        self.report = None
        self._auto_busy = False
        self._sort_newest = self.settings.get("sort") == "newest"
        self._new_ids = set()   # apps that appeared this session: marked New until App Entries closes

        self.snackbar = Snackbar()
        overlay = Gtk.Overlay(vexpand=True)
        overlay.set_child(self.stack)
        overlay.add_overlay(self.snackbar)
        overlay.add_overlay(self._build_selection_bar())
        self.list_area = vbox(10, self.toolbar, self.hint, overlay)
        self._current = None        # the AppItem whose page is open
        self.drafts = {}            # app ID -> (fields, picked icon): unsaved edits kept while elsewhere
        self._narrow = False
        self.app_page = AppPage(self)
        # Status chips: above the app page when it's beside the list, else at
        # the top of the window's main area.
        self._scanning = self._scan_failed = self._scan_done = False
        self.status = StatusBar(self)
        self.status.set_size_request(-1, 56)   # level with the search box
        self.page_col = vbox(10, self.app_page)
        self.page_col.set_hexpand(True)
        self.top_status = vbox(0)
        self.top_status.set_visible(False)
        self.status.on_change = self._place_status
        self.split = hbox(16, self.list_area, self.page_col)
        self.split.set_vexpand(True)
        self._update_tab_controls()
        content.append(self.top_status)
        content.append(self.split)
        updates.connect(self.status.update)
        # History slides in at the side, so changes can be watched as they're made.
        self.history_reveal = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT,
                                           reveal_child=False, hexpand=False)
        body = hbox(0, self.rail, content, self.history_reveal)
        self.set_child(body)

    def _ensure_page(self, name):
        """Build a tab's page the first time it's shown."""
        if name not in PAGES or self.stack.get_child_by_name(name) is not None:
            return
        apps = lambda: [i.app for i in self.apps.items()]  # noqa: E731
        if name == "issues":
            self.issues = page = IssuesPage(self._fix, self._toggle_app, self._copy_text, self.settings)
            if self.report is not None:
                page.update(self.report)
        elif name == "autostart":
            self.autostart = page = AutostartPage(self, self._run_changes, apps)
        elif name == "defaults":
            self.defaults = page = DefaultsPage(self, self._run_changes, apps)
            page.reload()   # it's filled from the app list, which may be in already
        elif name == "settings":
            page = SettingsPage(self, self.settings)
        elif name == "updates":
            inner = UpdatesPage(self.get_application().updates, self.settings)
            inner.set_margin_bottom(24)
            page = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            page.set_child(Clamp(inner, 760))
        else:
            return
        self.stack.add_named(page, name)

    def _setup_card(self, _f, list_item):
        list_item.set_child(AppRow(self._on_toggle, self._on_card_action, lambda: self._selecting,
                                   lambda: self._current.app.id if self._current is not None else None,
                                   lambda did: did in self.drafts))

    def _focused_row(self):
        w = self.grid.get_focus_child()
        row = w.get_first_child() if w is not None else None
        return row if isinstance(row, AppRow) and row.item is not None else None

    def _on_list_key(self, _c, keyval, _code, state):
        row = self._focused_row()
        if row is None or self._selecting:
            return False
        if keyval == Gdk.KEY_space:
            row.toggle()
            return True
        if keyval == Gdk.KEY_Menu or (keyval == Gdk.KEY_F10 and state & Gdk.ModifierType.SHIFT_MASK):
            row.open_menu()
            return True
        return False

    def _build_selection_bar(self):
        self.sel_count = label("", ("body", "sel-count"))
        self.sel_hide = button(_("Hide"), "visibility_off", "filled", small=True,
                               tooltip=_("Hide the selected apps from launcher menus"),
                               cb=lambda *_: self._batch("hide"))
        self.sel_show = button(_("Show"), "visibility", "tonal", small=True,
                               tooltip=_("Show the selected apps in launcher menus again"),
                               cb=lambda *_: self._batch("show"))
        self.sel_restore = button(_("Restore"), "restart_alt", "tonal", small=True,
                                  tooltip=_("Delete your files for the selected system apps, so their original "
                                            "entries are used again"),
                                  cb=lambda *_: self._batch("restore"))
        self.sel_style = button(_("Style icons"), "palette", "tonal", small=True,
                                tooltip=_("Give the selected apps' styled icons one colour, background and border"),
                                cb=lambda *_: self._batch("style"))
        self.sel_uninstall = button(_("Uninstall"), "delete_forever", "tonal", small=True,
                                    tooltip=_("Uninstall the selected apps. Shows everything that goes first."),
                                    cb=lambda *_: self._batch("uninstall"))
        all_btn = button(_("Select all"), "select_all", "text", small=True,
                         tooltip=_("Select every app in the list as it's filtered now"),
                         cb=lambda *_: self._select_all())
        done = button(icon_name="close", style="text", small=True, tooltip=_("Stop selecting (Esc)"),
                      cb=lambda *_: self.set_selecting(False))
        bar = hbox(8, self.sel_count, all_btn, self.sel_hide, self.sel_show, self.sel_restore, self.sel_style,
                   self.sel_uninstall, done)
        bar.add_css_class("selection-bar")
        self.sel_bar = Gtk.Revealer(child=bar, transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
                                    halign=Gtk.Align.CENTER, valign=Gtk.Align.END, reveal_child=False)
        self.sel_bar.set_can_target(False)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        return self.sel_bar

    def _build_actions(self):
        filt = Gio.SimpleAction.new_stateful("filter", GLib.VariantType.new("s"),
                                             GLib.Variant("s", self.settings.get("filter")))
        filt.connect("change-state", lambda a, v: self.settings.set("filter", v.get_string()))
        self.add_action(filt)
        self._filter_action = filt

        nd = Gio.SimpleAction.new_stateful("show-no-display", None,
                                           GLib.Variant("b", self.settings.get("show-no-display")))
        nd.connect("change-state", lambda a, v: self.settings.set("show-no-display", v.get_boolean()))
        self.add_action(nd)
        self._nd_action = nd

        new = Gio.SimpleAction.new("new-launcher", None)
        new.connect("activate", lambda *_: self.new_launcher())
        self.add_action(new)
        web = Gio.SimpleAction.new("new-web-app", None)
        web.connect("activate", lambda *_: self.new_web_app())
        self.add_action(web)

        unhide = Gio.SimpleAction.new("unhide-all", None)
        unhide.connect("activate", lambda *_: self._unhide_all())
        self.add_action(unhide)

        for name, cb in (("select", lambda *_: self.set_selecting(True)),
                         ("export", lambda *_: self._export()),
                         ("import", lambda *_: self._import()),
                         ("refresh-launchers", lambda *_: self._refresh_launchers())):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)

        hist = Gio.SimpleAction.new("history", None)
        hist.connect("activate", self.show_history)
        self.add_action(hist)
        undo_last = Gio.SimpleAction.new("undo-last", None)
        undo_last.connect("activate", lambda *_a: self._undo_last())
        self.add_action(undo_last)

        search = Gio.SimpleAction.new("search", None)
        search.connect("activate", lambda *_: self.search_entry.grab_focus())
        self.add_action(search)

    # -------------------------------------------------------------- settings

    def _update_sources(self):
        """List the sources that have apps, plus the chosen one."""
        current = self.settings.get("source")
        have = {i.app.source for i in self.apps.items()} | {current}
        self._sources = [("any", _("All sources"))] + [(k, label_for_source(k)) for k in health.SOURCES
                                                         if k in have]
        self._update_filter_label()

    def _update_filter_label(self):
        """"Filter", or what's filtering: "Flatpak", "Customised", "2 filters"."""
        on = []
        source = self.settings.get("source")
        if source != "any":
            on.append(dict(self._sources).get(source, label_for_source(source)))
        names = {"customised": _("Customised"), "new": _("New")}
        on += [names[k] for k in ("customised", "new") if k in self._only]
        if not self.settings.get("show-no-display"):
            on.append(_("In menus only"))
        text = _("Filter") if not on else _("Filter: {on}").format(on=", ".join(on))
        set_text(self.filter_label, text)
        self.filter_menu.set_tooltip_text(text if on else _(
            "Only list apps from one source, customised ones or new ones, and whether to include apps that "
            "aren't in menus"))
        self.filter_dot.set_visible(bool(on))
        if on:
            self.filter_menu.add_css_class("filter-on")
        else:
            self.filter_menu.remove_css_class("filter-on")

    def _filter_popup(self, menu_button):
        current = self.settings.get("source")
        box = vbox(2)
        box.set_size_request(240, -1)

        def heading(text):
            h = label(text, ("small", "dim"))
            h.set_margin_start(12)
            h.set_margin_top(6)
            h.set_margin_bottom(2)
            return h

        def row(text, on, cb):
            b = Gtk.Button()
            b.add_css_class("flat")
            b.add_css_class("source-item")
            mark = icon("check", ("accent",))
            mark.set_opacity(1 if on else 0)
            b.set_child(hbox(10, mark, label(text, ("body",))))
            b.connect("clicked", lambda _b: (menu_button.popdown(), GLib.idle_add(lambda: (cb(), False)[1])))
            return b

        box.append(heading(_("Source")))
        for key, text in self._sources:
            box.append(row(text, key == current, lambda k=key: self.settings.set("source", k)))
        box.append(heading(_("Only")))
        box.append(row(_("Customised"), "customised" in self._only, lambda: self._toggle_only("customised")))
        box.append(row(_("New since last time"), "new" in self._only, lambda: self._toggle_only("new")))
        box.append(heading(_("Include")))
        box.append(row(_("Apps not in menus"), self.settings.get("show-no-display"),
                       lambda: self.settings.set("show-no-display", not self.settings.get("show-no-display"))))
        pop = Gtk.Popover()
        pop.add_css_class("options")
        pop.set_child(box)
        menu_button.set_popover(pop)

    def _toggle_only(self, key):
        if key is not None:
            self._only ^= {key}
        self._update_filter_label()
        self.filter.changed(Gtk.FilterChange.DIFFERENT)
        self._update_counts()

    def _choose_source(self, key):
        GLib.idle_add(lambda: (self.settings.set("source", key), False)[1])

    def _on_setting(self, key):
        if key == "filter":
            v = self.settings.get("filter")
            if v in LEGACY_FILTERS:
                self.settings.set("filter", "all")
                return
            self.rail.set_active(v)
            self.status.update()
            if self._current is not None and (v == "mine") != self._current.app.created:
                self.close_app()
            self._filter_action.set_state(GLib.Variant("s", v))
            self.filter.changed(Gtk.FilterChange.DIFFERENT)
            self._update_tab_controls()
            self._update_state()
        elif key == "sort":
            self._sort_newest = self.settings.get("sort") == "newest"
            self.sort_label.set_label(self._sort_text())
            self.sort_menu.set_tooltip_text(_("Sort: {how}").format(how=self._sort_text()))
            self.sorter.changed(Gtk.SorterChange.DIFFERENT)
        elif key == "source":
            if self._loaded:
                self._update_sources()
            self._update_filter_label()
            self.filter.changed(Gtk.FilterChange.DIFFERENT)
            self._update_counts()
        elif key == "view":
            self.view_seg.set_active(self.settings.get("view"))
            self.filter.changed(Gtk.FilterChange.DIFFERENT)
            self._update_counts()
        elif key == "show-no-display":
            v = self.settings.get("show-no-display")
            self._nd_action.set_state(GLib.Variant("b", v))
            self._update_filter_label()
            self.filter.changed(Gtk.FilterChange.DIFFERENT)
            self._update_counts()
        elif key in ("hide-uninstalled-edits", "restore-reinstalled-edits"):
            if self.issues is not None and self.report is not None:
                self.issues.update(self.report, force=True)
            if self.settings.get(key) and self.report is not None:
                self._handle_uninstalled(self.report)
        elif key == "window-controls":
            self._apply_window_controls()
        elif key == "size":
            self._compact = None
            self._apply_size(self.get_width())

    def _close_with_drafts(self, *_a):
        """Unsaved edits aren't lost without asking."""
        if not self.drafts or getattr(self, "_closing", False):
            return False
        names = [self.apps.by_id[d].app.name for d in self.drafts if d in self.apps.by_id] or [_("an app")]

        def on_response(resp):
            if resp == "discard":
                self._closing = True
                self.close()

        Dialog(self, ngettext("Close without saving your changes to {names}?",
                              "Close without saving your changes to {names}?", len(names))
               .format(names=", ".join(names)),
               _("Your changes haven't been saved. Go back to save them, or close and lose them."),
               [("cancel", _("Go back"), "tonal"), ("discard", _("Close without saving"), "danger")],
               on_response, icon_name="warning", icon_class="warn-text").present()
        return True

    def _save_size(self, *_):
        self.settings.set("maximized", self.is_maximized())
        if not self.is_maximized():
            w, h = self.get_default_size()
            self.settings.set("window-width", w)
            self.settings.set("window-height", h)
        return False

    # -------------------------------------------------------- window buttons

    def _apply_window_controls(self):
        parent = self.winctl.get_parent()
        if parent is not None:
            parent.remove(self.winctl)
        child = self.winctl.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.winctl.remove(child)
            child = nxt
        if not self.settings.get("window-controls"):
            return
        layout = Gtk.Settings.get_default().get_property("gtk-decoration-layout") or ":minimize,maximize,close"
        left, _sep, right = layout.partition(":")
        side, names = (self._start, left) if not right and left else (self._end, right)
        made = 0
        for name in names.split(","):
            b = None
            if name == "minimize":
                b = button(icon_name="minimize", style="text", small=True, tooltip=_("Minimize"),
                           cb=lambda *_: self.minimize())
            elif name == "maximize":
                b = button(icon_name="crop_square", style="text", small=True, tooltip=_("Maximize"),
                           cb=lambda *_: self.unmaximize() if self.is_maximized() else self.maximize())
            elif name == "close":
                b = button(icon_name="close", style="text close", small=True, tooltip=_("Close"),
                           cb=lambda *_: self.close())
            if b is not None:
                self.winctl.append(b)
                made += 1
        if made:
            if side is self._end:
                side.append(self.winctl)
            else:
                side.prepend(self.winctl)

    # ------------------------------------------------------------ responsive

    def do_size_allocate(self, width, height, baseline):
        Gtk.ApplicationWindow.do_size_allocate(self, width, height, baseline)
        self._apply_size(width)
        self._apply_split(width)

    def _apply_split(self, width, now=False):
        # With History open, the list and page share what's left of the width.
        room = width - (HISTORY_WIDTH if getattr(self, "_history_open", False) else 0)
        # Side by side only when the page gets at least the width it needs.
        need = self.rail.measure(Gtk.Orientation.HORIZONTAL, -1)[0] + LIST_WIDTH + 16 + 40
        if self.app_page.get_visible():
            need += self.app_page.measure(Gtk.Orientation.HORIZONTAL, -1)[0]
        narrow = room < max(SPLIT_FROM, need)
        if narrow != self._narrow:
            self._narrow = narrow
            if now:
                self._update_split()
            else:
                GLib.idle_add(lambda: (self._update_split(), False)[1])


    def _apply_size(self, width):
        size = self.settings.get("size")
        if size != "auto":
            want = size
        else:
            compact = self._compact
            if compact is None:
                compact = width < COMPACT_BELOW
            elif compact and width >= COMPACT_BELOW + HYSTERESIS:
                compact = False
            elif not compact and width < COMPACT_BELOW:
                compact = True
            if compact == self._compact:
                return
            self._compact = compact
            want = "compact" if compact else "default"
        f = SIZES[want]
        if f != self.style.factor:
            GLib.idle_add(lambda: (self.style.set_size(f), False)[1])

    # --------------------------------------------------------------- filters

    def _visible_base(self, a):
        # Entries their package keeps out of menus are listed only on request,
        # unless the user has already changed them.
        return self.settings.get("show-no-display") or not a.no_display or a.has_override

    def _matches_query(self, item):
        return all(t in item.search for t in self._query.split())

    def _match(self, item, lift=()):
        """Whether the app is listed on this page. `lift` names filters to
        ignore: query, source, only, hidden (the Shown/Hidden view), nodisplay."""
        a = item.app
        if "nodisplay" not in lift and not self._visible_base(a):
            return False
        if "query" not in lift and not self._matches_query(item):
            return False
        source = self.settings.get("source")
        if "source" not in lift and source != "any" and a.source != source:
            return False
        if "customised" in self._only and "only" not in lift and not a.customised:
            return False
        if "new" in self._only and "only" not in lift and not a.new:
            return False
        if self.settings.get("filter") == "mine":
            return a.created
        view = self.settings.get("view")
        return "hidden" in lift or view == "all" or a.hidden == (view == "hidden")

    def _update_tab_controls(self):
        f = self.settings.get("filter")
        # Issues, Autostart, Defaults, Settings and Updates aren't app lists.
        self.toolbar.set_visible(f in ("all", "mine"))
        if hasattr(self, "app_page"):
            self._update_split()
        self.view_seg.set_visible(f == "all")
        self.new_btns.set_visible(f == "mine")

    def _compare(self, a, b, *_):
        ka = (a.app.name.casefold(), a.app.id)
        kb = (b.app.name.casefold(), b.app.id)
        if self._sort_newest:
            ka, kb = (-a.app.first_seen,) + ka, (-b.app.first_seen,) + kb
        return (ka > kb) - (ka < kb)

    @staticmethod
    def _sort_choices():
        return [("name", _("A–Z")), ("newest", _("Newest first"))]

    def _sort_text(self):
        return dict(self._sort_choices()).get(self.settings.get("sort"), _("A–Z"))

    def _sort_popup(self, menu_button):
        current = self.settings.get("sort")
        box = vbox(2)
        box.set_size_request(200, -1)
        for key, text in self._sort_choices():
            b = Gtk.Button()
            b.add_css_class("flat")
            b.add_css_class("source-item")
            mark = icon("check", ("accent",))
            mark.set_opacity(1 if key == current else 0)
            b.set_child(hbox(10, mark, label(text, ("body",))))
            b.connect("clicked", lambda _b, k=key: (menu_button.popdown(),
                                                    GLib.idle_add(lambda: (self.settings.set("sort", k), False)[1])))
            box.append(b)
        note = label(_("Newest first goes by when App Entries first saw each app; ones that appeared since it "
                       "last looked are marked New."), ("small", "dim"), wrap=True, chars=26)
        note.set_margin_start(12)
        note.set_margin_end(12)
        note.set_margin_top(6)
        note.set_margin_bottom(6)
        box.append(note)
        pop = Gtk.Popover()
        pop.add_css_class("options")
        pop.set_child(box)
        menu_button.set_popover(pop)

    def _on_search(self, entry):
        q = entry.get_text().strip().casefold()
        if q == self._query:
            return
        self._query = q
        if q and self.settings.get("filter") in PAGES:
            self.settings.set("filter", "all")  # those pages aren't searchable
        self.filter.changed(Gtk.FilterChange.DIFFERENT)
        self._update_counts()

    def _on_search_activate(self, _entry):
        if not self.sorted.get_n_items():
            return
        if hasattr(self.grid, "scroll_to"):  # GTK 4.12+
            self.grid.scroll_to(0, Gtk.ListScrollFlags.FOCUS, None)
        else:
            self.grid.grab_focus()

    # ---------------------------------------------------------------- state

    def _update_counts(self):
        # Each tab's total, whatever the search, source and switches.
        total = self.apps.items()
        hidden = sum(1 for i in total if i.app.hidden)
        self.view_seg.set_text("shown", _("Shown {n}").format(n=len(total) - hidden))
        self.view_seg.set_text("hidden", _("Hidden {n}").format(n=hidden))
        # A list that stays empty doesn't say it changed, so the empty page's
        # filter buttons are brought up to date here.
        if self._loaded and self.stack.get_visible_child_name() == "empty":
            self._update_state()

    def _update_hint(self):
        view = self.settings.get("view")
        n = 0
        if self._query and view != "all" and self.settings.get("filter") == "all":
            n = sum(1 for i in self.apps.items()
                    if i.app.hidden == (view == "shown") and self._match(i, ("hidden",)))
        if n and self.sorted.get_n_items():
            set_text(self.hint_text, (ngettext("{n} hidden app also matches.", "{n} hidden apps also match.", n)
                                      if view == "shown" else
                                      ngettext("{n} shown app also matches.", "{n} shown apps also match.", n))
                     .format(n=n))
            self.hint_btn.set_label(_("Show all"))
            self.hint.set_visible(True)
        else:
            self.hint.set_visible(False)

    def _update_state(self):
        self._update_hint()
        if not self._loaded:
            if self.settings.get("filter") in ("autostart", "defaults", "settings", "updates"):
                self._ensure_page(self.settings.get("filter"))
                self.stack.set_visible_child_name(self.settings.get("filter"))
            return
        page = "grid" if self.sorted.get_n_items() else "empty"
        if self.settings.get("filter") in PAGES:
            page = self.settings.get("filter")
        elif page == "empty":
            f = self.settings.get("filter")
            self.empty_actions.remove_all()
            n_out, lifts, kept = self._filters_hiding_apps()
            if lifts:
                q = self.search_entry.get_text().strip()
                if kept:
                    set_text(self.empty_title, _("Nothing here with these filters"))
                    set_text(self.empty_body, ngettext("{n} app matching “{q}” is left out by the filters.",
                                                       "{n} apps matching “{q}” are left out by the filters.", n_out)
                             .format(n=n_out, q=q))
                elif self._query and len(lifts) == 1:
                    set_text(self.empty_title, _("No apps match “{q}”").format(q=q))
                    set_text(self.empty_body, _("Try a different name, command or file ID."))
                else:
                    set_text(self.empty_title, _("Nothing here with these filters"))
                    set_text(self.empty_body, ngettext("{n} app on this tab is left out by the filters.",
                                                       "{n} apps on this tab are left out by the filters.", n_out)
                             .format(n=n_out))
                row = self.empty_actions
                for text, do in lifts:
                    row.append(button(text, style="tonal", small=True, cb=lambda *_a, do=do: do()))
                if len(lifts) > 1:
                    row.append(button((_("Show all matches ({n})") if kept else _("Clear all filters ({n})"))
                                      .format(n=n_out), style="filled", small=True,
                                      cb=lambda *_a: [do() for _t, do in lifts]))
            elif self._query:
                set_text(self.empty_title, _("No apps match “{q}”").format(q=self.search_entry.get_text().strip()))
                set_text(self.empty_body, _("Try a different name, command or file ID."))
            elif "customised" in self._only:
                set_text(self.empty_title, _("Nothing is customised"))
                set_text(self.empty_body, _("Apps you change with Edit, or that have your own copy of their entry, "
                                            "are listed here. Restore original puts the system version back."))
            elif self.settings.get("source") != "any" and not self._query:
                set_text(self.empty_title, _("No apps from this source"))
                set_text(self.empty_body, _("Choose All sources in the Filter menu to see everything."))
            elif f == "mine":
                set_text(self.empty_title, _("No launchers yet"))
                set_text(self.empty_body, _("Use New launcher to make one for a program, a script or commands, or "
                                            "New web app to open a site in its own window. What you make is "
                                            "listed here."))
            elif self.settings.get("view") == "hidden":
                set_text(self.empty_title, _("Nothing is hidden"))
                set_text(self.empty_body,
                         _("Turn on “Hidden from launcher” on any app to hide it from your app menus."))
            else:
                set_text(self.empty_title, _("No apps found"))
                set_text(self.empty_body, _("No application entries were found in your XDG data folders."))
        if self.stack.get_visible_child_name() != page:
            self._ensure_page(page)
            self.stack.set_visible_child_name(page)

    def _filters_hiding_apps(self):
        """What the filters leave out of this tab, for the empty page:
        (apps left out, [(button text, how to lift it)], whether a search
        is kept). While searching, only apps that match the search count,
        and the search stays unless nothing would match it anyway. An app
        can be left out by more than one filter at once (hidden and not in
        menus), so a filter plays a part if lifting all but it shows fewer."""
        items = self.apps.items()

        def clear_query():
            self.search_entry.set_text("")
            self._on_search(self.search_entry)

        others = [(key, text, do) for key, on, text, do in (
            ("source", self.settings.get("source") != "any", _("Show all sources"),
             lambda: self.settings.set("source", "any")),
            ("hidden", self.settings.get("filter") == "all" and self.settings.get("view") != "all",
             _("Show shown and hidden apps"), lambda: self.settings.set("view", "all")),
            ("only", bool(self._only), _("Show all, not only customised or new"),
             lambda: (self._only.clear(), self._toggle_only(None))),
            ("nodisplay", not self.settings.get("show-no-display"), _("Show apps not in menus"),
             lambda: self.settings.set("show-no-display", True)),
        ) if on]
        query = [("query", _("Clear the search"), clear_query)] if self._query else []

        def count(lift):
            return sum(1 for i in items if self._match(i, lift))

        if query and not count(tuple(k for k, _t, _d in others)) and count(("query",)):
            # Nothing matches the search, whatever the other filters: just that.
            return count(("query",)), [(query[0][1] + f" ({count(('query',))})", clear_query)], False
        for active, kept in ((others, bool(query)), (query + others, False)):
            keys = tuple(k for k, _t, _d in active)
            n = count(keys) if keys else 0
            if not n:
                continue
            out = []
            for key, text, do in active:
                if count(tuple(k for k in keys if k != key)) < n:
                    alone = count((key,))
                    out.append((text + (f" ({alone})" if alone else ""), do))
            return n, out, kept
        return 0, [], False

    # ---------------------------------------------------------------- scan

    def _cards_in_view(self):
        """(item, y) for each card on screen, top first; y is from the top of
        the visible area."""
        out = []
        height = self.grid_scroll.get_height()

        def walk(w):
            if isinstance(w, AppRow):
                if w.item is not None and w.get_mapped():
                    ok, r = w.compute_bounds(self.grid_scroll)
                    if ok and r.get_y() + r.get_height() > 0 and r.get_y() < height:
                        out.append((r.get_y(), w.item))
                return
            c = w.get_first_child()
            while c is not None:
                walk(c)
                c = c.get_next_sibling()

        walk(self.grid)
        out.sort(key=lambda t: t[0])
        return [(item, y) for y, item in out]

    def refresh_logo(self):
        """The logo in the accent colour, drawn from its own file. Looking it
        up in the icon theme would hold up the first frame until the whole
        theme has loaded."""
        from .. import app_icon, theme
        app = self.get_application()
        seed = app.effective_seed() if app is not None else theme.DEFAULT_SEED
        folder = os.path.join(GLib.get_user_runtime_dir() or GLib.get_user_cache_dir(), "app-entries")
        path = os.path.join(folder, "logo-{}.svg".format(seed.lstrip("#")))
        try:
            if not os.path.isfile(path):
                os.makedirs(folder, exist_ok=True)
                with open(path + ".tmp", "w", encoding="utf-8") as f:
                    f.write(app_icon.render(seed, marker=False))
                os.replace(path + ".tmp", path)
            self.logo.set_from_paintable(Gtk.IconPaintable.new_for_file(Gio.File.new_for_path(path), 40, 2))
            timing.mark(f"  logo drawn from {path}")
        except Exception as e:  # noqa: BLE001 - only the logo
            # Not from the icon theme even then: that would hold up the window.
            self.logo.clear()
            timing.mark(f"  logo couldn't be drawn: {e!r}")

    def after_first_frame(self):
        """Called once the window has drawn for the first time."""

    def _keeping_place(self, change):
        """Make a change to the list without moving the view: the card at the
        top before stays where it was afterwards. GTK can otherwise jump,
        often to the top, when the card that has focus (the one whose switch
        was just clicked) leaves the list, and pixel positions shift as cards
        above change height, so the place is kept by card, not by pixels."""
        before = self._cards_in_view() if self.grid_scroll.get_vadjustment().get_value() > 0 else []
        change()
        anchors = [(item, y) for item, y in before
                   if self.apps.by_id.get(item.app.id) is item and self.filter.match(item)]
        if not anchors:
            return
        item, y0 = anchors[0]
        adj = self.grid_scroll.get_vadjustment()
        frames = [0]

        def hold(*_a):
            frames[0] += 1
            now = next((y for it, y in self._cards_in_view() if it is item), None)
            if now is None:
                # Off screen: bring it into view first, then line it up.
                pos = next((i for i in range(self.sorted.get_n_items()) if self.sorted.get_item(i) is item), -1)
                if pos >= 0 and hasattr(self.grid, "scroll_to"):
                    self.grid.scroll_to(pos, Gtk.ListScrollFlags.NONE, None)
            elif abs(now - y0) > 1:
                adj.set_value(adj.get_value() + (now - y0))
            return frames[0] < 30

        self.grid.add_tick_callback(hold)

    def rescan(self, *_args):
        self._scan_gen += 1
        gen = self._scan_gen
        self._scanning = False

        def slow():
            # Only a scan that takes a while says so, or the chip would
            # flash after every change.
            if gen == self._scan_gen and not self._scan_done:
                self._scanning = True
                self.status.update()
            return False

        self._scan_done = False
        GLib.timeout_add(600, slow)

        def done(result):
            if gen != self._scan_gen:
                return
            self._scanning = False
            self._scan_done = True
            self._scan_failed = isinstance(result, Exception)
            self.status.update()
            if isinstance(result, Exception):
                return
            apps, report = result
            if not self._loaded:
                timing.mark("  list being filled")
            self._keeping_place(lambda: self.apps.sync(apps))
            if self._current is not None:
                now = self.apps.by_id.get(self._current.app.id)
                if now is None:
                    self.close_app()
                elif now is not self._current:
                    self._open_app(now)
            self._update_sources()
            if self.defaults is not None:
                self.defaults.reload()
            self.report = report
            if self.issues is not None:
                self.issues.update(report)
            self.rail.set_count("issues", report.count)
            self.status.update()
            self._handle_uninstalled(report)
            first = not self._loaded
            self._loaded = True
            if first:
                timing.mark("apps listed")
                if timing.QUIT == "listed":
                    GLib.idle_add(lambda: (self.get_application().quit(), False)[1])
            self._update_counts()
            self._update_state()
            if first and self.sorted.get_n_items():
                GLib.idle_add(lambda: (self.grid.grab_focus(), False)[1])

        icon_lookup.clear_cache()
        forget_icons()
        # Which package each app with a missing program came from is only for
        # the Issues page, and asks the package manager once per app, so it's
        # looked up after the list is shown.
        def owners_found(found):
            if gen != self._scan_gen or isinstance(found, Exception) or self.report is None:
                return
            self.report.owners = found
            if self.issues is not None:
                self.issues.update(self.report)

        def scanned(result):
            done(result)
            if not isinstance(result, Exception) and result[1].missing:
                missing = list(result[1].missing)
                run_bg(lambda: packages.owners(missing), owners_found)

        def scan():
            apps, report = health.scan_and_check(owners=False)
            new = seen.update(apps)
            return apps, report, new

        def marked(result):
            if isinstance(result, Exception):
                return scanned(result)
            apps, report, new = result
            self._new_ids |= new
            for a in apps:
                a.new = a.id in self._new_ids
            return scanned((apps, report))

        run_bg(scan, marked)
        if self.autostart is not None:
            self.autostart.reload()

    def queue_rescan(self, delay=300):
        if self._rescan_timer:
            GLib.source_remove(self._rescan_timer)

        def fire():
            self._rescan_timer = 0
            self.rescan()
            return False

        self._rescan_timer = GLib.timeout_add(delay, fire)

    def _watch_dirs(self):
        for d in desktop_entries.application_dirs() + [autostart.user_dir()] + autostart.system_dirs():
            f = Gio.File.new_for_path(d)
            try:
                m = f.monitor_directory(Gio.FileMonitorFlags.WATCH_MOVES, None)
            except GLib.Error:
                continue
            m.connect("changed", lambda *_: self.queue_rescan())
            self._monitors.append(m)

    # -------------------------------------------------------------- toggling

    def _on_activate(self, _grid, position):
        item = self.sorted.get_item(position)
        if item is not None and self._selecting:
            item.set_selected(not item.selected)
            self._update_selection()
        elif item is not None:
            self._open_app(item)

    def _open_app(self, item):
        """A click or Enter on a row: its page, beside the list or (in a
        narrow window) instead of it."""
        if self.app_page.form_open():
            self.app_page.close_form()
        old, self._current = self._current, item
        self.app_page.show(item)
        self.status.update()
        for it in (old, item):
            if it is not None:
                it.emit("changed")
        self._update_split()

    def open_draft(self, item):
        """A status chip for unsaved edits: back to that app's page."""
        want = "mine" if item.app.created else "all"
        if self.settings.get("filter") != want:
            self.settings.set("filter", want)
        self._open_app(item)

    def close_app(self):
        old, self._current = self._current, None
        self.app_page.show(None)
        if old is not None:
            old.emit("changed")
        self._update_split()
        if old is not None:
            pos = next((i for i in range(self.sorted.get_n_items()) if self.sorted.get_item(i) is old), -1)
            if pos >= 0 and hasattr(self.grid, "scroll_to"):
                self.grid.scroll_to(pos, Gtk.ListScrollFlags.FOCUS, None)

    def _update_split(self):
        """List and page side by side, or one of them in a narrow window."""
        lists = self.settings.get("filter") in ("all", "mine")
        busy = self._current is not None or self.app_page.form_open()
        page = lists and (not self._narrow or busy)
        listing = not lists or not self._narrow or not busy
        self.app_page.set_visible(page)
        self.page_col.set_visible(page)
        self.app_page.set_narrow(self._narrow)
        self.list_area.set_visible(listing)
        self.toolbar.set_visible(lists)
        side = lists and not self._narrow
        self.list_area.set_hexpand(not side)
        self.list_area.set_size_request(LIST_WIDTH if side else -1, -1)
        self._place_status()

    def _place_status(self):
        """Above the page, always taking its room so the page doesn't move
        as chips come and go; or at the top, only while there's a chip."""
        beside = self.page_col.get_visible() and not self._narrow
        want = self.page_col if beside else self.top_status
        if self.status.get_parent() is not want:
            if self.status.get_parent() is not None:
                self.status.get_parent().remove(self.status)
            want.prepend(self.status)
        self.status.set_size_request(-1, 56 if beside else -1)
        self.top_status.set_visible(not beside and self.status.has_items)

    def _on_toggle(self, item: AppItem, hidden: bool, allow_delete=False):
        if item.busy or (hidden and item.app.id == SELF_ID):
            item.emit("changed")
            return
        app = item.app
        item.set_busy(True)

        def done(result):
            item.set_busy(False)
            if isinstance(result, overrides.NeedsConfirmation):
                item.emit("changed")
                self._confirm_delete(item, result.path)
                return
            if isinstance(result, overrides.OverrideError):
                item.emit("changed")
                verb = _("Couldn't hide {name}") if hidden else _("Couldn't unhide {name}")
                error_dialog(self, verb.format(name=app.name),
                             _("The file below couldn't be changed: {reason}. Nothing else was changed. "
                               "Check that you own the folder and it isn't read-only.").format(reason=result.reason),
                             result.path)
                self.queue_rescan(0)
                return
            if isinstance(result, Exception):
                item.emit("changed")
                error_dialog(self, _("Something went wrong"), str(result))
                return
            self.queue_rescan(0)
            if result is not None:
                self._announce(result)

        run_bg(lambda: overrides.set_hidden(app, hidden, allow_delete=allow_delete), done)

    def _announce(self, change):
        text = _("Hid {name}") if change.hidden else _("Showed {name}")
        self._record(text.format(name=change.app_name), [change])

    def _confirm_delete(self, item, path):
        name = item.app.name

        def on_response(resp):
            if resp == "delete":
                self._on_toggle(item, False, allow_delete=True)

        Dialog(self, _("Delete this file to unhide {name}?").format(name=name),
               _("{name} is hidden by a file that App Entries didn't create, or that has been "
                 "edited since. To show the app again, the file has to be deleted. You can undo this "
                 "right after.").format(name=name),
               [("cancel", _("Cancel"), "tonal"), ("delete", _("Delete file"), "danger")],
               on_response, icon_name="warning", icon_class="warn-text", detail=path).present()

    # ------------------------------------------------------- explicit actions
    # Everything below runs only when the user presses a button, and every
    # change can be undone from the snackbar.

    def _copy_text(self, text):
        clipboard = self.get_clipboard()
        try:
            clipboard.set(text)
        except (TypeError, AttributeError):
            clipboard.set_content(Gdk.ContentProvider.new_for_value(text))
        self.snackbar.show(_("Copied: {text}").format(text=text))

    def _toggle_app(self, app, hidden):
        item = self.apps.by_id.get(app.id)
        if item is not None:
            self._on_toggle(item, hidden)

    def _run_changes(self, plan, message, failed_title, after=None, allow_empty=False, done_anyway=None):
        """Plan (in the background), apply all-or-nothing, record it in the
        history and offer Undo. `after(changes)` runs once they're applied and
        returns anything it moved to the Trash, so Undo can put it back."""
        def work():
            changes = [c for c in plan() if c is not None]
            return overrides.apply_all(changes)

        def done(result):
            self.queue_rescan(0)
            if done_anyway is not None:
                done_anyway()
            if isinstance(result, overrides.OverrideError):
                error_dialog(self, failed_title,
                             _("The file below couldn't be changed: {reason}. Nothing was changed.")
                             .format(reason=result.reason), result.path)
            elif isinstance(result, Exception):
                error_dialog(self, failed_title, str(result))
            elif result or allow_empty:
                trashed = (after(result) or []) if after is not None else []
                self._record(message(len(result)), result, trashed)

        run_bg(work, done)

    def _record(self, text, changes, trashed=(), reinstall=None, reinstall_steam=False):
        """Log a change in the history and show it with Undo."""
        entry = history.record(text, changes, list(trashed), reinstall=reinstall, reinstall_steam=reinstall_steam)
        if entry is not None and entry.can_undo:
            self.snackbar.show(text, _("Undo"), lambda: self.undo_entry(entry.id))
        else:
            self.snackbar.show(text)
        self.history_changed()

    def undo_entry(self, entry_id):
        def work():
            e = history.undo(entry_id)
            if any("/mime/packages/" in p for p in e.paths):
                appimages.refresh_mime()
            return e

        def done(result):
            self.queue_rescan(0)
            self.history_changed()
            if isinstance(result, history.UndoError):
                error_dialog(self, _("Couldn't undo"), str(result), result.path or None)
            elif isinstance(result, Exception):
                error_dialog(self, _("Couldn't undo"), str(result))
            else:
                self.snackbar.show(_("Undone: {what}").format(what=result.message))

        run_bg(work, done)

    def _undo_last(self):
        def found(entries):
            e = next((x for x in entries if x.can_undo), None) if not isinstance(entries, Exception) else None
            if e is None:
                self.snackbar.show(_("Nothing to undo"))
            else:
                self.undo_entry(e.id)

        run_bg(history.load, found)

    def history_changed(self):
        if self.history_window is not None:
            self.history_window.reload()

    def show_history(self, *_a):
        """Ctrl+H or the History button: open the panel, or close it."""
        if self.history_reveal.get_reveal_child():
            self._close_history()
            return
        if self.history_window is None:
            self.history_window = HistoryWindow(self, self.undo_entry, self.reinstall_entry,
                                                on_close=self._close_history)
            self.history_window.set_margin_bottom(14)
            self.history_reveal.set_child(self.history_window)
        else:
            self.history_window.reload()
        self._history_open = True
        self._apply_split(self.get_width(), now=True)
        self.history_reveal.set_reveal_child(True)
        self.history_btn.add_css_class("panel-open")

    def _close_history(self):
        self.history_reveal.set_reveal_child(False)
        self.history_btn.remove_css_class("panel-open")
        self._history_open = False
        self._apply_split(self.get_width(), now=True)

    def _handle_uninstalled(self, report):
        """Edited apps uninstalled elsewhere leave your copy of their entry
        behind, still in menus but starting nothing. Hide those (keeping the
        edits), and take that hide off when the app comes back. Each is done
        once, is recorded in the history and can be undone; both are options
        on the Issues page."""
        if self._auto_busy:
            return
        hide = [lo for lo in report.uninstalled if self.settings.get("hide-uninstalled-edits")]
        back = [lo for lo in report.reinstalled if self.settings.get("restore-reinstalled-edits")]
        if not hide and not back:
            return
        self._auto_busy = True

        def plan():
            return ([overrides.plan_hide_uninstalled(lo.id, lo.name, lo.path) for lo in hide]
                    + [overrides.plan_bring_back(lo.id, lo.name, lo.path) for lo in back])

        def message(_n):
            gone = [lo.name for lo in hide]
            again = [lo.name for lo in back]
            parts = []
            if len(gone) == 1:
                parts.append(_("Hid {name}: it was uninstalled. Your edits are kept").format(name=gone[0]))
            elif gone:
                parts.append(ngettext("Hid {n} uninstalled app; your edits are kept",
                                      "Hid {n} uninstalled apps; your edits are kept", len(gone))
                             .format(n=len(gone)))
            if len(again) == 1:
                parts.append(_("{name} is back: your edits apply again").format(name=again[0]))
            elif again:
                parts.append(ngettext("{n} app is back: your edits apply again",
                                      "{n} apps are back: your edits apply again", len(again))
                             .format(n=len(again)))
            return ". ".join(parts)

        def finished():
            self._auto_busy = False

        self._run_changes(plan, message, _("Couldn't update your edited copies"), done_anyway=finished)

    def _fix(self, kind, targets):
        n_ = ngettext
        if kind == "legacy":
            self._run_changes(lambda: [overrides.plan_update_legacy(a) for a in targets],
                              lambda n: n_("Updated {n} hide file", "Updated {n} hide files", n).format(n=n),
                              _("Couldn't update the hide files"))
        elif kind == "leftovers":
            self._run_changes(lambda: [overrides.plan_delete(l.id, l.name, l.path, False) for l in targets],
                              lambda n: n_("Removed {n} leftover file", "Removed {n} leftover files", n).format(n=n),
                              _("Couldn't remove the leftover files"))
        elif kind == "missing":
            self._run_changes(lambda: [overrides.plan_set_hidden(a, True) for a in targets],
                              lambda n: n_("Hid {n} app", "Hid {n} apps", n).format(n=n),
                              _("Couldn't hide the apps"))
        elif kind == "delete":
            self._confirm_delete_launcher(targets[0])
        elif kind == "hide-uninstalled":
            self._run_changes(lambda: [overrides.plan_hide_uninstalled(l.id, l.name, l.path) for l in targets],
                              lambda n: n_("Hid {n} uninstalled app; your edits are kept",
                                           "Hid {n} uninstalled apps; your edits are kept", n).format(n=n),
                              _("Couldn't hide the apps"))
        elif kind == "remove-edits":
            self._run_changes(lambda: [overrides.plan_delete(l.id, l.name, l.path, False) for l in targets],
                              lambda n: n_("Removed your edits for {n} uninstalled app",
                                           "Removed your edits for {n} uninstalled apps", n).format(n=n),
                              _("Couldn't remove the edits"))
        elif kind == "bring-back":
            self._run_changes(lambda: [overrides.plan_bring_back(l.id, l.name, l.path) for l in targets],
                              lambda n: n_("Your edits apply again to {n} app",
                                           "Your edits apply again to {n} apps", n).format(n=n),
                              _("Couldn't bring the edits back"))

    def _save_edit(self, app, fields, picked=None, after=None):
        def plan():
            changes = []
            if picked is not None:
                path = fields.icon
                svg = symbols.render(picked, title=fields.name.strip())
                before = overrides.read_text(path)
                if svg != before:
                    changes.append(overrides.Change(app.id, app.name, path, before, svg, app.hidden))
            return changes + [editing.plan_edit(app, fields)]

        self._run_changes(plan,
                          lambda n: _("Saved your changes to {name}").format(name=fields.name.strip()),
                          _("Couldn't save your changes"),
                          after=(lambda _r: (after(), [])[1]) if after is not None else None)

    def new_launcher(self):
        self._show_form(LauncherWindow(self, self._save_launcher, self._save_raw,
                                       glyph_color=self.style.palette["ON_SURFACE"], highlight=self._highlight(),
                                       on_close=self._close_form))

    def new_web_app(self):
        self._show_form(WebAppWindow(self, self._save_launcher, glyph_color=self.style.palette["ON_SURFACE"],
                                     on_close=self._close_form))

    def _show_form(self, form, back_to=None):
        """A launcher or web app form, in the page beside the list. When it
        closes, `back_to` (the launcher being edited) shows again."""
        self._form_back_to = back_to
        if self.settings.get("filter") != "mine":
            self.settings.set("filter", "mine")
        old, self._current = self._current, None
        if old is not None:
            old.emit("changed")
        self.app_page.show_form(form)
        self._update_split()
        GLib.idle_add(lambda: (form.child_focus(Gtk.DirectionType.TAB_FORWARD), False)[1])

    def _close_form(self):
        self.app_page.close_form()
        back = getattr(self, "_form_back_to", None)
        self._form_back_to = None
        if back is not None and self.apps.by_id.get(back.app.id) is not None:
            self._open_app(self.apps.by_id[back.app.id])
        self._update_split()

    def _highlight(self):
        rgba = Gdk.RGBA()
        rgba.parse(self.style.palette["PRIMARY"])
        rgba.alpha = 0.24
        return rgba

    def _save_launcher(self, did, spec, make_executable):
        is_new = did is None

        def plan():
            if make_executable:
                launchers.make_executable(spec.program)
            return launchers.plan_save(spec, did)[1]

        made = _("Created the {name} web app") if spec.web_url else _("Created the {name} launcher")
        self._run_changes(plan, lambda n: (made if is_new else _("Saved {name}")).format(name=spec.name.strip()),
                          _("Couldn't save the launcher"))
        if is_new and self.settings.get("filter") not in ("all", "mine"):
            self.settings.set("filter", "mine")

    def _save_raw(self, did, name, text):
        self._run_changes(lambda: [launchers.plan_raw(text, did, name)],
                          lambda n: _("Saved {name}").format(name=name), _("Couldn't save the launcher"))

    @staticmethod
    def _web_spec(app):
        if not app.created or not app.override_path:
            return None
        try:
            spec = launchers.read_spec(overrides.read_text(app.override_path) or "")
        except overrides.OverrideError:
            return None
        return spec if spec is not None and spec.web_url else None

    def _confirm_delete_launcher(self, app):
        spec = self._web_spec(app)
        profile = ""
        if spec is not None and spec.web_profile:
            profile = webapps.own_data(spec.args)

        def on_response(resp):
            if resp not in ("delete", "delete-data"):
                return
            def plan():
                changes = (launchers.plan_delete(app) if app.created else
                           [overrides.plan_delete(app.id, app.name, app.override_path, False)])
                return changes

            def after(result):
                if resp == "delete-data" and profile:
                    try:
                        return [trash.move(profile)]
                    except trash.TrashError as e:
                        error_dialog(self, _("Couldn't move its data to the Trash"), str(e), profile)
                return []

            done_text = _("Deleted the {name} web app") if spec else _("Deleted the {name} launcher")
            self._run_changes(plan, lambda n: done_text.format(name=app.name),
                              _("Couldn't delete {name}").format(name=app.name), after=after)

        what = _("web app") if spec else _("launcher")
        body = (_("This deletes the {what} file from your applications folder, so {name} disappears from your "
                  "menus. You can undo this right after.").format(what=what, name=app.name))
        if not spec:
            body = body.replace(".", ". " + _("The program itself isn't touched."), 1)
        else:
            body += " " + _("Your browser and its cookies and sign-ins aren't touched.")
        buttons = [("cancel", _("Cancel"), "tonal"), ("delete", _("Delete"), "danger")]
        if profile:
            body += " " + _("This web app also has sign-ins of its own, kept apart from your browser. Delete "
                            "with data moves only that folder to the Trash.")
            buttons = [("cancel", _("Cancel"), "tonal"), ("delete", _("Keep data"), "tonal"),
                       ("delete-data", _("Delete with data"), "danger")]
        Dialog(self, _("Delete {name}?").format(name=app.name), body, buttons,
               on_response, icon_name="delete", icon_class="error-text", detail=app.override_path).present()

    # ------------------------------------------------------------ uninstalling

    def _all_apps(self):
        return [i.app for i in self.apps.items()]

    def uninstall(self, app):
        UninstallWindow(self, app, self._all_apps(), self.finish_uninstall).present()

    def finish_uninstall(self, items, message, done):
        """Once apps are uninstalled: remove the files App Entries keeps for
        them and the ones they were given, move the chosen data to the Trash,
        and record it all in History with the reinstall commands.
        done(error or None) is called afterwards."""
        apps = self._all_apps()
        reinstall, steam = [], False
        for p, opts in items:
            reinstall += p.reinstall(opts)
            steam = steam or p.kind == "steam"

        def work():
            changes = []
            for p, _opts in items:
                changes += uninstall.file_changes(p, apps)
            applied = overrides.apply_all(changes)
            trashed, errors = [], []
            for p, opts in items:
                for path in uninstall.to_trash(p, opts):
                    try:
                        trashed.append(trash.move(path))
                    except trash.TrashError as e:
                        errors.append(str(e))
            if any("/mime/packages/" in c.path for c in applied):
                appimages.refresh_mime()
            return applied, trashed, errors

        def finished(result):
            self.queue_rescan(0)
            if isinstance(result, Exception):
                why = (f"{result.reason} ({result.path})" if isinstance(result, overrides.OverrideError)
                       else str(result))
                self._record(message, [], [], reinstall, steam)
                done(why)
                return
            applied, trashed, errors = result
            self._record(message, applied, trashed, reinstall, steam)
            done("; ".join(errors) if errors else None)

        run_bg(work, finished)

    def reinstall_entry(self, entry_id):
        e = next((x for x in history.load() if x.id == entry_id), None)
        if e is None or not e.reinstall:
            return
        if e.reinstall_steam:
            for argv in e.reinstall:
                try:
                    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
                except OSError as err:
                    error_dialog(self, _("Couldn't open Steam"), str(err.strerror or err))
                    return
            self.snackbar.show(_("Opened Steam to install it again"))
            return
        try:
            terminal.start(e.reinstall)
        except terminal.NoTerminal:
            error_dialog(self, _("No terminal app was found"),
                         _("Run this in a terminal to install it again:"), terminal.shown(e.reinstall))
            return
        except OSError as err:
            error_dialog(self, _("The terminal couldn't be started"), str(err.strerror or err),
                         terminal.shown(e.reinstall))
            return
        self.snackbar.show(_("Opened your terminal to install it again"))

    def _on_card_action(self, item, action):
        app = item.app
        if action == "selected":
            self._update_selection()
        elif action == "restore":
            def plan():
                changes = [overrides.plan_restore_original(app)]
                # An icon drawn for this app in the Edit window goes too.
                icon = launchers.icon_path(launchers.PREFIX + "icon-" + app.id)
                text = overrides.read_text(icon)
                if text is not None and launchers.symbols_icon(text):
                    changes.append(overrides.Change(app.id, app.name, icon, text, None, app.base_hidden))
                return changes

            self._run_changes(plan,
                              lambda n: _("Restored the original {name}").format(name=app.name),
                              _("Couldn't restore {name}").format(name=app.name))
        elif action == "delete":
            self._confirm_delete_launcher(app)
        elif action == "edit" and app.created and self._web_spec(app):
            self._show_form(WebAppWindow(self, self._save_launcher, did=app.id,
                                         text=overrides.read_text(app.override_path),
                                         glyph_color=self.style.palette["ON_SURFACE"], on_close=self._close_form),
                            back_to=item)
        elif action == "uninstall":
            self.uninstall(app)
        elif action == "helpers":
            HelpersWindow(self, app, self._all_apps()).present()
        elif action == "edit" and app.created:
            text = overrides.read_text(app.override_path)
            self._show_form(LauncherWindow(self, self._save_launcher, self._save_raw, did=app.id, text=text,
                                           glyph_color=self.style.palette["ON_SURFACE"],
                                           highlight=self._highlight(), on_close=self._close_form),
                            back_to=item)
        elif action == "duplicate":
            spec = launchers.duplicate(overrides.read_text(app.override_path) or "")
            if spec is None:
                error_dialog(self, _("Couldn't duplicate {name}").format(name=app.name),
                             _("It was changed by hand, so it can't be copied through the form. Use Open file "
                               "location and copy the file instead."), app.override_path)
            else:
                self._save_launcher(None, spec, False)
        elif action == "edit":
            # Editing is on the app's page.
            if self._current is not item:
                self._open_app(item)
            self.app_page.focus_form()
        elif action.startswith("find:"):
            self.settings.set("filter", "all")
            self.search_entry.set_text(action[len("find:"):])
        elif action == "open":
            self._open_app(item)
        elif action == "toggle-hidden":
            self._on_toggle(item, not app.hidden)
        elif action == "hide-uninstalled":
            self._fix("hide-uninstalled", [health.Leftover(app.id, app.name, app.override_path)])
        elif action == "issues":
            self.settings.set("filter", "issues")
        elif action == "file-types":
            self._ensure_page("defaults")
            self.settings.set("filter", "defaults")
            self.defaults.show_app(app.id)
        elif action == "launch":
            self._launch(app)
        elif action == "open-folder":
            path = app.override_path or app.source_path
            try:
                Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(os.path.dirname(path)).get_uri(), None)
            except GLib.Error as e:
                error_dialog(self, _("Couldn't open the folder"), e.message, os.path.dirname(path))

    def _launch(self, app):
        """Start the app the way a launcher would, from the entry launchers use."""
        path = app.override_path or app.source_path
        try:
            info = Gio.DesktopAppInfo.new_from_filename(path)
        except (TypeError, GLib.Error):
            info = None
        if info is None:
            error_dialog(self, _("Couldn't open {name}").format(name=app.name),
                         _("Its entry file couldn't be read."), path)
            return
        ctx = self.get_display().get_app_launch_context()
        try:
            info.launch([], ctx)
        except GLib.Error as e:
            error_dialog(self, _("Couldn't open {name}").format(name=app.name), e.message,
                         _("Runs: {cmd}").format(cmd=app.exec))
            return
        self.snackbar.show(_("Opening {name}…").format(name=app.name))

    def _unhide_all(self):
        apps = [i.app for i in self.apps.items()]

        def planned(result):
            if isinstance(result, Exception):
                error_dialog(self, _("Couldn't unhide the apps"), str(result))
                return
            changes, skipped = result
            if not changes:
                self.snackbar.show(_("Nothing to unhide: no apps are hidden by you or App Entries"))
                return
            body = _("Every app hidden by App Entries or by your own files is shown in launchers again. "
                     "Apps hidden by their own package, such as helpers and settings panels, stay as they are. "
                     "You can undo this right after.")
            if skipped:
                body += " " + ngettext(
                    "{n} app hidden by a file App Entries didn't make is skipped; unhide it on its own card.",
                    "{n} apps hidden by files App Entries didn't make are skipped; unhide them on their own cards.",
                    len(skipped)).format(n=len(skipped))

            def on_response(resp):
                if resp == "show":
                    self._run_changes(lambda: changes,
                                      lambda n: ngettext("Unhid {n} app", "Unhid {n} apps", n).format(n=n),
                                      _("Couldn't unhide the apps"))

            Dialog(self, ngettext("Show {n} hidden app?", "Show {n} hidden apps?", len(changes))
                   .format(n=len(changes)), body,
                   [("cancel", _("Cancel"), "tonal"), ("show", _("Show all"), "filled")],
                   on_response, icon_name="visibility").present()

        run_bg(lambda: overrides.plan_unhide_all(apps), planned)

    # ------------------------------------------------------------ selecting

    def set_selecting(self, on):
        if on == self._selecting:
            return
        self._selecting = on
        if self.select_btn.get_active() != on:
            self.select_btn.set_active(on)
        for item in self.apps.items():
            item.selected = False
            item.emit("changed")
        self.sel_bar.set_reveal_child(on)
        self.sel_bar.set_can_target(on)
        self.snackbar.set_margin_bottom(72 if on else 0)
        self._update_tab_controls()
        self._update_selection()

    def _on_key(self, _c, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape and self._selecting:
            self.set_selecting(False)
            return True
        if keyval in (Gdk.KEY_s, Gdk.KEY_S) and _state & Gdk.ModifierType.CONTROL_MASK:
            return self.app_page.save()
        if keyval == Gdk.KEY_Escape and self._current is not None and self._narrow:
            self.close_app()
            return True
        return False

    def _selected(self):
        return [i.app for i in self.apps.items() if i.selected]

    def _select_all(self):
        shown = [self.sorted.get_item(i) for i in range(self.sorted.get_n_items())]
        everything = all(i.selected for i in shown)
        for item in shown:
            item.set_selected(not everything)
        self._update_selection()

    def _update_selection(self):
        apps = self._selected()
        set_text(self.sel_count, ngettext("{n} selected", "{n} selected", len(apps)).format(n=len(apps)))
        self.sel_hide.set_sensitive(any(not a.hidden and a.id != SELF_ID for a in apps))
        self.sel_show.set_sensitive(any(a.hidden for a in apps))
        self.sel_restore.set_sensitive(any(a.has_override and a.system for a in apps))
        self.sel_style.set_sensitive(bool(apps))
        self.sel_uninstall.set_sensitive(any(uninstall.kind_of(a) for a in apps))

    def _batch(self, what):
        apps = self._selected()
        n_ = ngettext
        if what == "uninstall":
            chosen = [a for a in apps if uninstall.kind_of(a)]
            if len(chosen) == 1:
                self.uninstall(chosen[0])
            elif chosen:
                BatchUninstallWindow(self, chosen, self._all_apps(), self.finish_uninstall).present()
            return
        if what == "hide":
            targets = [a for a in apps if not a.hidden and a.id != SELF_ID]
            self._run_changes(lambda: [overrides.plan_set_hidden(a, True) for a in targets],
                              lambda n: n_("Hid {n} app", "Hid {n} apps", n).format(n=n),
                              _("Couldn't hide the apps"))
        elif what == "show":
            def planned(result):
                if isinstance(result, Exception):
                    error_dialog(self, _("Couldn't show the apps"), str(result))
                    return
                changes, skipped = result
                if changes:
                    self._run_changes(lambda: changes, lambda n: n_("Showed {n} app", "Showed {n} apps", n)
                                      .format(n=n), _("Couldn't show the apps"))
                if skipped:
                    error_dialog(self, n_("{n} app was left hidden", "{n} apps were left hidden", len(skipped))
                                 .format(n=len(skipped)),
                                 _("They're hidden by files App Entries didn't make, which would have to be "
                                   "deleted. Turn them on one at a time to be asked about each file."),
                                 "\n".join(a.name for a in skipped))
            hidden = [a for a in apps if a.hidden]
            run_bg(lambda: self._plan_show(hidden), planned)
        elif what == "style":
            self._style_icons(apps)
        elif what == "restore":
            targets = [a for a in apps if a.has_override and a.system]

            def on_response(resp):
                if resp == "restore":
                    self._run_changes(lambda: [overrides.plan_restore_original(a) for a in targets],
                                      lambda n: n_("Restored {n} app", "Restored {n} apps", n).format(n=n),
                                      _("Couldn't restore the apps"))

            Dialog(self, n_("Restore {n} app?", "Restore {n} apps?", len(targets)).format(n=len(targets)),
                   _("Your files for these apps are deleted, so the versions installed by the system are used "
                     "again. Edits and hide settings for them go away. You can undo this right after."),
                   [("cancel", _("Cancel"), "tonal"), ("restore", _("Restore"), "filled")],
                   on_response, icon_name="restart_alt",
                   detail=", ".join(a.name for a in targets[:12]) + ("…" if len(targets) > 12 else "")).present()

    def _style_icons(self, apps):
        def found(result):
            if isinstance(result, Exception):
                error_dialog(self, _("Couldn't read the icons"), str(result))
                return
            styled = [(a, f) for a, f in result if f is not None]
            if not styled:
                Dialog(self, _("No styled icons selected"),
                       _("Only icons made in App Entries can be restyled: launchers you made, and apps you gave a "
                         "styled icon with Edit. Give an app one with Edit → Styled… first."),
                       [("ok", _("OK"), "filled")], icon_name="palette").present()
                return
            targets = [a for a, _f in styled]
            start = styled[0][1][2]

            def picked(style):
                def plan():
                    changes, _skipped = launchers.plan_restyle(targets, style)
                    return changes

                self._run_changes(plan, lambda n: ngettext("Restyled {n} icon", "Restyled {n} icons", len(targets))
                                  .format(n=len(targets)), _("Couldn't restyle the icons"))

            IconPicker(self, start, picked, self.style.palette["ON_SURFACE"], style_for=len(targets)).present()
            if len(styled) < len(apps):
                self.snackbar.show(ngettext("{n} selected app has no styled icon and stays as it is",
                                            "{n} selected apps have no styled icon and stay as they are",
                                            len(apps) - len(styled)).format(n=len(apps) - len(styled)), seconds=6)

        run_bg(lambda: [(a, launchers.styled_icon(a)) for a in apps], found)

    @staticmethod
    def _plan_show(apps):
        changes, skipped = [], []
        for a in apps:
            try:
                c = overrides.plan_set_hidden(a, False)
            except overrides.NeedsConfirmation:
                skipped.append(a)
                continue
            if c is not None:
                changes.append(c)
        return changes, skipped

    # ------------------------------------------------------- export / import

    def _export(self, parent=None):
        parent = parent or self
        apps = [i.app for i in self.apps.items()]

        def counted(result):
            if isinstance(result, Exception):
                error_dialog(parent, _("Couldn't export"), str(result))
                return
            items, others = result
            if not items and not others:
                self.snackbar.show(_("Nothing to export yet: you haven't hidden, edited or made any apps"))
                return
            body = _("Saves a file with the apps you hid, the entries you edited and the launchers you made, "
                     "with their icons. Import it on another computer, or after reinstalling, to get them back. "
                     "Hidden apps are saved by name only, so they're hidden whichever version is installed there.")
            buttons = [("cancel", _("Cancel"), "tonal")]
            if others:
                body += " " + ngettext(
                    "{n} other file in your applications folder wasn't made by App Entries. Include it too "
                    "if you want a full copy of the folder.",
                    "{n} other files in your applications folder weren't made by App Entries. Include them "
                    "too if you want a full copy of the folder.", others).format(n=others)
                buttons.append(("all", _("Include them"), "tonal"))
            if items:
                buttons.append(("ours", ngettext("Export {n} item", "Export {n} items", len(items))
                                .format(n=len(items)), "filled"))

            def on_response(resp):
                if resp in ("ours", "all"):
                    self._export_to(apps, resp == "all", parent)

            Dialog(parent, _("Export your changes"), body, buttons, on_response, icon_name="upload").present()

        run_bg(lambda: profile.collect(apps), counted)

    def _export_to(self, apps, include_others, parent):
        def chosen(path):
            if not path.endswith(".json"):
                path += ".json"

            def done(result):
                if isinstance(result, Exception):
                    error_dialog(parent, _("Couldn't export"), str(result), path)
                else:
                    self.snackbar.show(ngettext("Exported {n} item", "Exported {n} items", len(result[0]))
                                       .format(n=len(result[0])))

            run_bg(lambda: profile.export(path, apps, include_others), done)

        choose_file(parent, _("Export your changes"), chosen, patterns=("*.json",), filter_name=_("Exports"),
                    save_as="app-entries-{}.json".format(GLib.DateTime.new_now_local().format("%Y-%m-%d")))

    def _import(self, parent=None):
        parent = parent or self
        apps = [i.app for i in self.apps.items()]

        def chosen(path):
            def planned(result):
                if isinstance(result, Exception):
                    error_dialog(parent, _("Couldn't import"), str(result), path)
                    return
                self._confirm_import(result, parent)

            run_bg(lambda: profile.plan_import(profile.read(path), apps), planned)

        choose_file(parent, _("Import changes"), chosen, patterns=("*.json",), filter_name=_("Exports"))

    def _confirm_import(self, plan, parent=None):
        parent = parent or self
        lines = list(plan.adds)
        icons = sum(1 for c in plan.changes if not c.app_id)
        if icons:
            lines.append(ngettext("Add {n} icon file", "Add {n} icon files", icons).format(n=icons))
        lines += [_("Skip {name}: {why}").format(name=n, why=w) for n, w in plan.skipped]
        if plan.unchanged:
            lines.append(ngettext("{n} item already matches", "{n} items already match", plan.unchanged)
                         .format(n=plan.unchanged))
        detail = "\n".join(lines[:20]) + ("\n…" if len(lines) > 20 else "")
        if not plan.changes:
            Dialog(parent, _("Nothing to import"), _("Everything in the file already matches this computer."),
                   [("ok", _("OK"), "filled")], icon_name="download", detail=detail or None).present()
            return

        def on_response(resp):
            if resp == "import":
                self._run_changes(lambda: plan.changes,
                                  lambda n: ngettext("Imported {n} change", "Imported {n} changes", n).format(n=n),
                                  _("Couldn't import"))

        Dialog(parent, ngettext("Make {n} change?", "Make {n} changes?", len(plan.changes))
               .format(n=len(plan.changes)),
               _("These are the changes the file asks for. Apps that aren't installed here are skipped. "
                 "Files in your applications folder are replaced where the file has a different version. "
                 "You can undo all of it right after."),
               [("cancel", _("Cancel"), "tonal"), ("import", _("Import"), "filled")],
               on_response, icon_name="download", detail=detail).present()

    # ------------------------------------------------------ refresh launchers

    def _refresh_launchers(self):
        def on_response(resp):
            if resp != "refresh":
                return

            def done(result):
                if isinstance(result, Exception):
                    error_dialog(self, _("Couldn't refresh"), str(result))
                elif any("failed" in line or "Couldn't" in line for line in result):
                    error_dialog(self, _("Part of the refresh didn't work"), _("Here's what happened:"),
                                 "\n".join(result))
                else:
                    self.snackbar.show(_("Asked launchers to reload their app lists"))

            run_bg(launcher_refresh.refresh, done)

        Dialog(self, _("Refresh launcher menus?"),
               _("Most launchers notice changes on their own. If yours still shows an app you hid, or misses "
                 "one you showed, this nudges it. Your files aren't changed. It does this:"),
               [("cancel", _("Cancel"), "tonal"), ("refresh", _("Refresh"), "filled")],
               on_response, icon_name="sync", detail="\n".join("• " + s for s in launcher_refresh.steps())).present()
