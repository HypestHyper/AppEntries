"""The app page: everything about one app, beside the list. How it looks in a
launcher, whether it's hidden, what it runs, which files open with it,
whether it starts at login, helper apps, the changes made to it, and
uninstalling. Nothing changes until a button or switch is used, and every
change can be undone."""
from gettext import gettext as _

from gi.repository import Gio, GLib, Gtk, Pango

from .. import APP_ID, autostart, defaults, history, uninstall
from .app_card import UNINSTALL_HINTS, gicon_later, label_for_source
from .dialogs import run_bg
from .widgets import Toggle, WrapBox, button, card, clear, hbox, icon, label, section, vbox

SELF_ID = APP_ID + ".desktop"


def _tile(name, size, small=False):
    img = Gtk.Image(pixel_size=size, accessible_role=Gtk.AccessibleRole.PRESENTATION)
    gicon_later(name, img.set_from_gicon)
    t = Gtk.Box(valign=Gtk.Align.CENTER, halign=Gtk.Align.START)
    t.add_css_class("icon-tile")
    if small:
        t.add_css_class("small-tile")
    t.append(img)
    return t


def _when(ts):
    dt = GLib.DateTime.new_from_unix_local(int(ts))
    now = GLib.DateTime.new_now_local()
    days = (now.get_day_of_year() - dt.get_day_of_year()) if now.get_year() == dt.get_year() else 99
    if days == 0:
        return _("Today, {time}").format(time=dt.format("%H:%M"))
    if days == 1:
        return _("Yesterday, {time}").format(time=dt.format("%H:%M"))
    return dt.format("%-d %B %Y")


class AppPage(Gtk.Box):
    """`win` is the main window: its actions do the work."""

    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
        self.add_css_class("app-page")
        self.win = win
        self.item = None
        self._handler = 0
        self._gen = 0
        self._narrow = False

        self.back = button(_("Apps"), "chevron_left", "text", small=True, tooltip=_("Back to the list (Esc)"),
                           cb=lambda *_: win.close_app())
        self.back.set_halign(Gtk.Align.START)
        self.back.set_visible(False)
        self.page = vbox(0)
        self.page.set_margin_bottom(32)
        self.page.set_margin_start(4)
        self.page.set_margin_end(12)
        self.scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.scroll.set_child(self.page)
        self.append(self.back)
        self.append(self.scroll)
        self._empty()

    # -- showing ------------------------------------------------------------

    def set_narrow(self, narrow):
        self._narrow = narrow
        self.back.set_visible(narrow)

    def show(self, item):
        """Show this AppItem, or nothing (None)."""
        if self.item is not None and self._handler:
            self.item.disconnect(self._handler)
        self.item, self._handler = item, 0
        if item is None:
            self._empty()
            return
        self._handler = item.connect("changed", lambda *_: self._build(keep_scroll=True))
        self.back.set_label(_("Launchers") if self.win.settings.get("filter") == "mine" else _("Apps"))
        self._build()

    def _empty(self):
        clear(self.page)
        e = vbox(10, icon("apps", ("big", "empty-icon")),
                 label(_("Choose an app"), ("title",), xalign=0.5),
                 label(_("Everything about it shows here: how it looks in your launcher, what it runs, which "
                         "files it opens and more."), ("body", "dim"), wrap=True, xalign=0.5, chars=40))
        e.set_margin_top(120)
        e.set_halign(Gtk.Align.CENTER)
        e.get_last_child().set_justify(Gtk.Justification.CENTER)
        self.page.append(e)

    def _build(self, keep_scroll=False):
        a = self.item.app if self.item is not None else None
        if a is None:
            return
        self._gen += 1
        adj = self.scroll.get_vadjustment()
        y = adj.get_value() if keep_scroll else 0
        clear(self.page)
        self.page.append(self._head(a))
        for w in self._notes(a):
            self.page.append(w)
        self.page.append(self._details(a))
        self._file_types(a)
        self._login(a)
        self._helpers(a)
        self._changes(a)
        self.page.append(self._actions(a))
        adj.set_value(y)
        GLib.idle_add(lambda: (adj.set_value(y), False)[1])

    # -- parts --------------------------------------------------------------

    def _head(self, a):
        box = vbox(16)
        box.add_css_class("page-head")
        src = a.source or ("system" if a.system else "user")
        origin = (_("Made with App Entries") if a.created else
                  _("From {source}").format(source=label_for_source(src)))
        name = label(a.name, ("title", "page-title"), wrap=True)
        ident = label(a.id, ("mono", "faint"), ellipsize=True)
        ident.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        ident.set_tooltip_text(a.source_path)
        text = vbox(2, name, label(origin, ("small", "dim")), ident)
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)
        top = hbox(18, _tile(a.icon, 64), text)
        if not (a.missing or a.uninstalled):
            run = button(_("Open"), "play_arrow", "tonal", small=True, tooltip=_("Start {name}").format(name=a.name),
                         cb=lambda *_: self.win._on_card_action(self.item, "launch"))
            run.set_valign(Gtk.Align.CENTER)
            top.append(run)
        box.append(top)
        box.append(self._preview(a))

        is_self = a.id == SELF_ID and not a.hidden
        sw = Toggle(a.hidden, lambda v: self.win._on_toggle(self.item, v))
        sw.set_sensitive(not self.item.busy and not is_self)
        sw.update_property([Gtk.AccessibleProperty.LABEL], [_("Hide {name} from launcher").format(name=a.name)])
        if is_self:
            sw.set_tooltip_text(_("App Entries can't hide itself, or you'd have no way back"))
        what = label(_("Hidden from launcher"), ("body",))
        what.set_hexpand(True)
        row = hbox(12, icon("visibility_off"), what, sw)
        row.add_css_class("page-switch")
        box.append(row)
        return box

    def _preview(self, a):
        """The app among its neighbours, as a launcher lists them (by name)."""
        listed = sorted((i.app for i in self.win.apps.items()
                         if not i.app.hidden and not i.app.no_display and i.app.id != a.id),
                        key=lambda x: x.name.casefold())
        key = a.name.casefold()
        at = next((n for n, x in enumerate(listed) if x.name.casefold() > key), len(listed))
        before = listed[at - 1] if at > 0 else None
        after = listed[at] if at < len(listed) else None
        box = vbox(2)
        box.add_css_class("launcher-preview")
        box.append(label(_("Not in your launcher: it's hidden") if a.hidden else _("In your launcher"),
                         ("small", "dim")))
        for x, me in ((before, False), (a, True), (after, False)):
            if x is None:
                continue
            desc = x.generic_name or x.comment
            r = hbox(12, _tile(x.icon, 28, small=True),
                     vbox(0, label(x.name, ("body", "app-name"), ellipsize=True),
                          label(desc, ("small", "dim"), ellipsize=True)))
            r.get_last_child().set_hexpand(True)
            r.add_css_class("preview-row")
            if me and not a.hidden:
                r.add_css_class("is-me")
            else:
                r.add_css_class("is-faded")
            if me and a.hidden:
                r.append(icon("visibility_off", ("dim",)))
            box.append(r)
        box.set_tooltip_text(_("How a launcher lists it, between the apps before and after it by name. Launchers "
                               "differ in looks; the name, icon and description are what they show."))
        return box

    def _notes(self, a):
        out = []
        if a.uninstalled:
            out.append(self._note(
                "inventory_2",
                (_("{name} was uninstalled. Your edits are kept, hidden from menus; remove them in Issues.")
                 if a.hidden else
                 _("{name} was uninstalled. Your edits are kept, but it still shows in menus and starts nothing."))
                .format(name=a.name),
                [(_("Open Issues"), "issues")]))
        elif a.missing:
            out.append(self._note(
                "link_off",
                _("{program} wasn't found in your PATH or the usual program folders, so this entry can't start "
                  "anything.").format(program=a.missing),
                [(_("Open Issues"), "issues")]))
        return out

    def _note(self, glyph, text, actions):
        t = label(text, ("body",), wrap=True, chars=40)
        t.set_hexpand(True)
        row = hbox(12, icon(glyph), t)
        for text_, action in actions:
            b = button(text_, style="text", small=True, cb=lambda *_a, ac=action: self.win._on_card_action(
                self.item, ac))
            b.set_valign(Gtk.Align.CENTER)
            row.append(b)
        row.add_css_class("page-note")
        return row

    def _details(self, a):
        box = vbox(0)
        head = hbox(12, section(_("Name, icon and command")))
        head.get_first_child().set_hexpand(True)
        edit = button(_("Edit…"), "edit_note", "tonal", small=True,
                      tooltip=_("Change the name, icon, command, folders and where it appears"),
                      cb=lambda *_: self.win._on_card_action(self.item, "edit"))
        edit.set_valign(Gtk.Align.END)
        edit.set_margin_bottom(6)
        head.append(edit)
        box.append(head)
        c = card()

        def line(title, value, mono=False):
            v = label(value or _("None"), ("mono",) if mono else ("body",), wrap=not mono, ellipsize=mono)
            if mono:
                v.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
                v.set_tooltip_text(value)
            if not value:
                v.add_css_class("dim")
            return vbox(2, label(title, ("small", "dim")), v)

        c.append(line(_("Name"), a.name))
        if a.generic_name:
            c.append(line(_("Kind of app"), a.generic_name))
        c.append(line(_("Description"), a.comment))
        c.append(line(_("Runs"), a.exec, mono=True))
        if a.customised:
            c.append(label(_("Customised: launchers use your copy of this entry. Restore original, below, puts "
                             "the version its package installed back."), ("small", "dim"), wrap=True, chars=50))
        box.append(c)
        return box

    def _file_types(self, a):
        if not a.mime_types:
            return
        holder = vbox(0)
        self.page.append(holder)
        gen = self._gen
        apps = [i.app for i in self.win.apps.items()]
        mimes = list(a.mime_types)

        def work():
            return [defaults.type_state(m, apps) for m in mimes]

        def done(states):
            if gen != self._gen or isinstance(states, Exception):
                return
            by_id = {x.id: x for x in apps}
            head = hbox(12, section(_("Opens these files"),
                                    _("Double-clicking one of these files opens the app shown.")))
            head.get_first_child().set_hexpand(True)
            more = button(_("All in Defaults"), style="text", small=True,
                          tooltip=_("See and change every file type it opens"),
                          cb=lambda *_: self.win._on_card_action(self.item, "file-types"))
            more.set_valign(Gtk.Align.END)
            more.set_margin_bottom(6)
            head.append(more)
            holder.append(head)
            c = card()
            # Its own types first: the ones no other app opens by default.
            states.sort(key=lambda t: (bool(t.category), t.mime))
            for t in states[:6]:
                d = Gio.content_type_get_description(t.mime) or t.mime
                ends = "  ".join(defaults.extensions(t.mime)) or t.mime
                txt = vbox(0, label(d[:1].upper() + d[1:], ("body",), ellipsize=True),
                           label(ends, ("mono", "faint"), ellipsize=True))
                txt.set_hexpand(True)
                txt.set_tooltip_text(t.mime)
                now = by_id.get(t.app_id)
                if now is not None and now.id == a.id:
                    right = hbox(6, icon("check", ("accent",)),
                                 label(_("Opens with {app}").format(app=a.name), ("small", "dim")))
                else:
                    right = hbox(8)
                    if now is not None:
                        right.append(label(now.name, ("small", "dim"), ellipsize=True))
                    right.append(button(_("Make default"), style="text", small=True,
                                        tooltip=_("Open this type with {app}").format(app=a.name),
                                        cb=lambda *_x, m=t.mime: self._make_default(m)))
                right.set_valign(Gtk.Align.CENTER)
                c.append(hbox(12, txt, right))
            if len(states) > 6:
                c.append(label(_("And {n} more, in Defaults.").format(n=len(states) - 6), ("small", "dim")))
            holder.append(c)

        run_bg(work, done)

    def _make_default(self, mime):
        app = self.item.app
        d = Gio.content_type_get_description(mime) or mime
        self.win._run_changes(lambda: defaults.plan_set_types([mime], app),
                              lambda n: _("{app} opens {what} now").format(app=app.name, what=d),
                              _("Couldn't set {app}").format(app=app.name),
                              after=lambda _r: (self._build(keep_scroll=True), [])[1])

    def _login(self, a):
        if a.uninstalled or a.missing:
            return
        holder = vbox(0)
        self.page.append(holder)
        gen = self._gen

        def done(items):
            if gen != self._gen or isinstance(items, Exception):
                return
            mine = next((i for i in items if i.id == a.id or (i.created and i.exec.split()[:1] ==
                                                             a.exec.split()[:1])), None)
            holder.append(section(_("Starts at login")))
            c = card()
            on = mine is not None and mine.enabled
            sw = Toggle(on, lambda v: self._set_login(mine, v))
            text = label(_("Start {name} when you log in").format(name=a.name), ("body",))
            text.set_hexpand(True)
            c.append(hbox(12, text, sw))
            holder.append(c)

        run_bg(autostart.scan, done)

    def _set_login(self, item, on):
        app = self.item.app
        if item is None:
            plan = lambda: [autostart.plan_add_app(app)]  # noqa: E731
        else:
            plan = lambda: [autostart.plan_set_enabled(item, on)]  # noqa: E731
        msg = (_("{name} starts when you log in") if on else _("{name} no longer starts at login"))
        self.win._run_changes(plan, lambda n: msg.format(name=app.name),
                              _("Couldn't change {name}").format(name=app.name),
                              after=lambda _r: (self._build(keep_scroll=True), [])[1])

    def _helpers(self, a):
        from .helpers_window import HelperActions, shortcuts_for
        items = [x for x in shortcuts_for(a, self.win._all_apps()) if x.installed]
        if not items:
            return
        self.page.append(section(_("Helper apps"),
                                 _("Apps that set up what App Entries doesn't, opened on {name} where they "
                                   "can.").format(name=a.name)))
        c = card()
        acts = HelperActions(self.win)
        row = WrapBox(8, 8)
        for x in items:
            b = button(x.name, "open_in_new", "tonal", small=True, tooltip=x.what,
                       cb=lambda *_a, s=x: acts.open(s))
            row.append(b)
        c.append(row)
        self.page.append(c)

    def _changes(self, a):
        holder = vbox(0)
        self.page.append(holder)
        gen = self._gen
        app_id = a.id

        def done(entries):
            if gen != self._gen or isinstance(entries, Exception):
                return
            mine = [e for e in entries if any(c.app_id == app_id for c in e.changes)][:5]
            if not mine:
                return
            holder.append(section(_("Changes to {name}").format(name=a.name)))
            c = card()
            for e in mine:
                t = vbox(0, label(e.message, ("body",), wrap=True, chars=36),
                         label(_when(e.when) + (_(" (undone)") if e.undone else ""), ("small", "dim")))
                t.set_hexpand(True)
                r = hbox(12, t)
                if e.can_undo:
                    b = button(_("Undo"), style="text", small=True, cb=lambda *_x, i=e.id: self.win.undo_entry(i))
                    b.set_valign(Gtk.Align.CENTER)
                    r.append(b)
                c.append(r)
            holder.append(c)

        run_bg(history.load, done)

    def _actions(self, a):
        row = WrapBox(8, 8)
        row.set_margin_top(24)

        def add(text, glyph, action, style="tonal", tip=None):
            row.append(button(text, glyph, style, small=True, tooltip=tip,
                              cb=lambda *_: self.win._on_card_action(self.item, action)))

        kind = uninstall.kind_of(a)
        if kind:
            add(_("Uninstall {name}…").format(name=a.name), "delete_forever", "uninstall", "danger",
                _(UNINSTALL_HINTS[kind]))
        if a.has_override and a.system:
            add(_("Restore original"), "restart_alt", "restore", tip=_(
                "Deletes your file for this app, so the version installed by the system is used again. You can "
                "undo this."))
        if a.created:
            add(_("Duplicate"), "content_copy", "duplicate", tip=_("Makes a new launcher with the same settings"))
        if a.source == "webapp":
            add(_("Delete this web app"), "delete", "delete", "danger")
        elif (a.source == "user" or a.created) and a.override_path and not a.override_managed:
            add(_("Delete this launcher"), "delete", "delete", "danger")
        add(_("Open file location"), "folder_open", "open-folder",
            tip=_("Opens the folder that holds this app's entry file in your file manager."))
        return row

