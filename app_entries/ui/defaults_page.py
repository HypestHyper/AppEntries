"""The Default apps tab: which app opens links, PDFs, pictures and so on.
Nothing changes until you pick an app, and every change can be undone."""
from gettext import gettext as _

from gi.repository import Gio, GLib, Gtk

from .. import defaults
from .app_card import gicon_for, label_for_source
from .dialogs import Dialog, run_bg
from .widgets import Clamp, button, card, clear, hbox, icon, label, section, vbox


def N_(s):
    return s


# What a choice does, for the confirmation: "Firefox opens links now".
OPENS = {
    "browser": N_("links"), "mail": N_("email links"), "files": N_("folders"), "text": N_("text files"),
    "pdf": N_("PDFs"), "images": N_("pictures"), "video": N_("videos"), "music": N_("music"),
    "archives": N_("archives"),
}

NAMES = {
    "browser": (N_("Web browser"), N_("Links, and web pages saved on your computer")),
    "mail": (N_("Email"), N_("Email links (mailto:)")),
    "files": (N_("Files and folders"), N_("Opening folders, from other apps and Open containing folder")),
    "text": (N_("Text files"), N_("Plain text files")),
    "pdf": (N_("PDF documents"), N_("PDF files")),
    "images": (N_("Pictures"), N_("PNG, JPEG, GIF, WebP and other images")),
    "video": (N_("Videos"), N_("MP4, MKV, WebM and other videos")),
    "music": (N_("Music"), N_("MP3, FLAC, Ogg and other audio")),
    "archives": (N_("Archives"), N_("ZIP, TAR, 7z, RAR and other archives")),
}


class DefaultsPage(Gtk.ScrolledWindow):
    """`run(plan, message, failed_title, after=…)` is the main window's
    _run_changes; `apps()` lists installed apps."""

    def __init__(self, win, run, apps):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.win = win
        self._run = run
        self._apps = apps
        self._signature = None
        page = vbox(0)
        page.set_margin_bottom(32)
        page.append(section(_("Default apps"),
                            _("Which app opens links and files when you double-click them or an app asks. Your "
                              "choices go in ~/.config/mimeapps.list, which every major desktop and most apps "
                              "read. Reset goes back to your desktop's own choice.")))
        self.list = vbox(10)
        self.list.set_margin_top(10)
        page.append(self.list)
        self.by_app_head = section(_("By app"),
                                   _("Every file type one app says it opens, including ones not listed above, "
                                     "and what opens each now."))
        page.append(self.by_app_head)
        self.by_app = vbox(0)
        page.append(self.by_app)
        self._open = set()        # categories showing each type
        self._app_id = ""         # the app picked in By app
        self._show_all = False    # By app lists every type, not just the first ones
        self._scroll_to_app = False
        self._scroll_tries = 0
        self._content = Clamp(page, 900)
        self.set_child(self._content)

    def show_app(self, app_id):
        """Pick this app in By app and scroll to it."""
        self._app_id = app_id
        self._show_all = False
        self._scroll_to_app = True
        self._signature = None
        self.reload()

    def reload(self):
        apps = self._apps()
        if not apps:
            return

        app_id = self._app_id

        def work():
            rows = []
            for cat in defaults.CATEGORIES:
                types = [defaults.type_state(m, apps) for m in defaults.opened_types(cat, apps)]
                rows.append((cat, defaults.candidates(cat, apps), defaults.state(cat, apps), types))
            chosen = next((a for a in apps if a.id == app_id), None)
            app_types = [defaults.type_state(m, apps) for m in chosen.mime_types] if chosen else []
            return rows, app_types

        def done(result):
            if isinstance(result, Exception):
                return
            rows, app_types = result
            sig = (tuple((c.key, tuple(a.id for a in cands), s.app_id, s.mixed, s.chosen_by_you,
                          tuple((t.mime, t.app_id, t.chosen_by_you) for t in types))
                         for c, cands, s, types in rows),
                   app_id, tuple((t.mime, t.app_id) for t in app_types), frozenset(self._open), self._show_all)
            if sig == self._signature:
                return
            self._signature = sig
            adj = self.get_vadjustment()
            y = adj.get_value()
            clear(self.list)
            by_id = {a.id: a for a in apps}
            for cat, cands, s, types in rows:
                self.list.append(self._row(cat, cands, s, types, apps, by_id))
            clear(self.by_app)
            self.by_app.append(self._by_app_card(apps, by_id, app_types))
            if self._scroll_to_app:
                self._scroll_to_app = False
                self._scroll_tries = 12
                GLib.timeout_add(50, self._scroll_down)
            elif not self._scroll_tries:
                GLib.idle_add(lambda: (adj.set_value(y), False)[1])

        run_bg(work, done)

    def _scroll_down(self):
        """Until the page is laid out, its height is wrong, so this tries
        again for a few frames."""
        ok, rect = self.by_app_head.compute_bounds(self._content)
        if ok and rect.origin.y > 0:
            self.get_vadjustment().set_value(max(0, rect.origin.y - 12))
        self._scroll_tries -= 1
        return self._scroll_tries > 0

    def _row(self, cat, cands, s, types, apps, by_id):
        name, what = NAMES.get(cat.key, (cat.name, ""))
        glyph = icon(cat.icon)
        glyph.add_css_class("default-glyph")
        text = vbox(2, label(_(name), ("body", "app-name")), label(_(what), ("small", "dim"), wrap=True, chars=40))
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)

        current = by_id.get(s.app_id)
        if not cands:
            picker = label(_("No installed app opens these"), ("small", "dim"))
        else:
            picker = self._picker(cat, cands, current, s)
        picker.set_valign(Gtk.Align.CENTER)
        reset = button(icon_name="restart_alt", style="text", small=True,
                       tooltip=_("Reset: let your desktop choose again"), cb=lambda *_a: self._reset(cat))
        reset.set_valign(Gtk.Align.CENTER)
        reset.set_visible(s.chosen_by_you)
        c = card()
        c.add_css_class("autostart-row")
        top = hbox(14, glyph, text)
        is_open = cat.key in self._open
        if len(types) > 1:
            more = button(_("Hide types") if is_open else _("Each type"), style="text", small=True,
                          tooltip=_("Choose an app for each type, like PNG or JPEG, on its own"),
                          cb=lambda *_a: self._toggle_types(cat.key))
            more.set_valign(Gtk.Align.CENTER)
            top.append(more)
        top.append(picker)
        top.append(reset)
        c.append(top)
        if s.mixed and not is_open:
            c.append(label(_("Some of these open in different apps. Picking one sets it for all of them; "
                             "Each type shows which."), ("small", "warn-text"), wrap=True, chars=70))
        if is_open and len(types) > 1:
            inner = vbox(4)
            inner.set_margin_start(52)
            inner.set_margin_top(4)
            for t in types:
                inner.append(self._type_row(t, apps, by_id))
            c.append(inner)
        return c

    def _toggle_types(self, key):
        self._open ^= {key}
        self._signature = None
        self.reload()

    @staticmethod
    def _type_text(mime, extra=""):
        d = Gio.content_type_get_description(mime) or mime
        d = d[:1].upper() + d[1:]
        ends = "  ".join(defaults.extensions(mime)) or mime
        if extra:
            ends = f"{ends} · {extra}"
        t = vbox(0, label(d, ("body",), ellipsize=True), label(ends, ("mono", "faint"), ellipsize=True))
        t.set_hexpand(True)
        t.set_valign(Gtk.Align.CENTER)
        t.set_tooltip_text(mime)
        return t

    def _type_row(self, t, apps, by_id):
        cands = defaults.type_candidates(t.mime, apps)
        current = by_id.get(t.app_id)
        if cands:
            picker = self._pick_button(cands, current, False, lambda a, m=t.mime: self._set_types([m], a),
                                       _("Choose the app for this type"), small=True)
        else:
            picker = label(_("No installed app opens it"), ("small", "dim"))
        picker.set_valign(Gtk.Align.CENTER)
        reset = button(icon_name="restart_alt", style="text", small=True,
                       tooltip=_("Reset: let your desktop choose again"),
                       cb=lambda *_a, m=t.mime: self._reset_types([m]))
        reset.set_valign(Gtk.Align.CENTER)
        reset.set_visible(t.chosen_by_you)
        return hbox(12, self._type_text(t.mime), picker, reset)

    # -- By app ---------------------------------------------------------------

    def _by_app_card(self, apps, by_id, types):
        c = card()
        with_types = defaults.apps_with_types(apps)
        chosen = by_id.get(self._app_id)
        pick = self._pick_button(with_types, chosen, False, self._choose_app, _("Choose an app"),
                                 placeholder=_("Choose an app"))
        pick.set_valign(Gtk.Align.CENTER)
        lead = label(_("Show the file types of"), ("body",))
        lead.set_valign(Gtk.Align.CENTER)
        head = hbox(12, lead, pick)
        if chosen is None or not types:
            c.append(head)
            if chosen is not None:
                c.append(label(_("{app} doesn't say it opens any file types.").format(app=chosen.name),
                               ("small", "dim")))
            return c
        not_yet = [t.mime for t in types if t.app_id != chosen.id]
        gap = Gtk.Box(hexpand=True)
        head.append(gap)
        if not_yet:
            every = button(_("{app} for all of them").format(app=chosen.name), style="tonal", small=True,
                           tooltip=_("Make {app} the default for all {n} types it opens that something else "
                                     "opens now").format(app=chosen.name, n=len(not_yet)),
                           cb=lambda *_a: self._set_types(not_yet, chosen))
            every.set_valign(Gtk.Align.CENTER)
            head.append(every)
        c.append(head)
        n_mine = len(types) - len(not_yet)
        c.append(label(_("Opens {n} of the {total} types it says it can.").format(n=n_mine, total=len(types)),
                       ("small", "dim")))
        names = {cat.key: _(NAMES.get(cat.key, (cat.name,))[0]) for cat in defaults.CATEGORIES}
        # Types with no category first: they can only be changed here.
        ordered = sorted(types, key=lambda t: (bool(t.category), t.mime))
        limit = len(ordered) if self._show_all else 25
        for t in ordered[:limit]:
            where = _("in {category}").format(category=names[t.category]) if t.category else ""
            if t.app_id == chosen.id:
                right = hbox(6, icon("check", ("accent",)),
                             label(_("Opens with {app}").format(app=chosen.name), ("small", "dim")))
            else:
                now = by_id.get(t.app_id)
                right = hbox(8)
                if now is not None:
                    img = Gtk.Image(pixel_size=18, accessible_role=Gtk.AccessibleRole.PRESENTATION)
                    img.set_from_gicon(gicon_for(now.icon))
                    right.append(img)
                    right.append(label(now.name, ("small", "dim"), ellipsize=True))
                else:
                    right.append(label(_("Not chosen"), ("small", "dim")))
                right.append(button(_("Make default"), style="text", small=True,
                                    tooltip=_("Open this type with {app}").format(app=chosen.name),
                                    cb=lambda *_a, m=t.mime: self._set_types([m], chosen)))
            right.set_valign(Gtk.Align.CENTER)
            row = hbox(14, self._type_text(t.mime, where), right)
            row.add_css_class("issue-row")
            c.append(row)
        if len(ordered) > limit:
            more = button(_("Show all {n}").format(n=len(ordered)), style="text", small=True,
                          cb=lambda *_a: self._more())
            more.set_halign(Gtk.Align.START)
            c.append(more)
        return c

    def _choose_app(self, app):
        self._app_id = app.id
        self._show_all = False
        self._signature = None
        self.reload()

    def _more(self):
        self._show_all = True
        self._signature = None
        self.reload()

    def _set_types(self, mimes, app):
        def after(_result):
            self.reload()
            return []

        if len(mimes) == 1:
            d = Gio.content_type_get_description(mimes[0]) or mimes[0]
            msg = _("{app} opens {what} now").format(app=app.name, what=d)
        else:
            msg = _("{app} opens {n} more file types now").format(app=app.name, n=len(mimes))
        self._run(lambda: defaults.plan_set_types(mimes, app), lambda n: msg,
                  _("Couldn't set {app}").format(app=app.name), after=after)

    def _reset_types(self, mimes):
        def after(_result):
            self.reload()
            return []

        d = Gio.content_type_get_description(mimes[0]) or mimes[0]
        self._run(lambda: defaults.plan_reset_types(mimes),
                  lambda n: _("{what}: back to your desktop's choice").format(what=d),
                  _("Couldn't reset {what}").format(what=d), after=after)

    def _picker(self, cat, cands, current, s):
        what = _(NAMES.get(cat.key, (cat.name,))[0]).lower()
        return self._pick_button(cands, current, s.mixed, lambda app: self._set(cat, app),
                                 _("Choose the app for {what}").format(what=what))

    def _pick_button(self, cands, current, mixed, on_pick, tooltip, small=False, placeholder=None):
        """A button showing the current app; it opens the list to choose from."""
        b = Gtk.MenuButton()
        b.add_css_class("tonal")
        b.add_css_class("default-pick")
        if small:
            b.add_css_class("small")
        size = 20 if small else 24
        if current is not None:
            img = Gtk.Image(pixel_size=size, accessible_role=Gtk.AccessibleRole.PRESENTATION)
            img.set_from_gicon(gicon_for(current.icon))
            b.set_child(hbox(8, img, label(current.name, ("body",), ellipsize=True), icon("expand_more")))
        else:
            b.set_child(hbox(8, label(placeholder or _("Not chosen"), ("body", "dim")), icon("expand_more")))
        b.set_tooltip_text(tooltip)

        box = vbox(2)
        names = [a.name.casefold() for a in cands]
        for a in cands:
            img = Gtk.Image(pixel_size=24, accessible_role=Gtk.AccessibleRole.PRESENTATION)
            img.set_from_gicon(gicon_for(a.icon))
            row = Gtk.Button()
            row.add_css_class("flat")
            row.add_css_class("pick-row")
            mark = icon("check")
            mark.set_visible(current is not None and a.id == current.id and not mixed)
            name = label(a.name, ("body",), ellipsize=True)
            text = vbox(0, name)
            text.set_hexpand(True)
            if names.count(a.name.casefold()) > 1:
                # Two entries with the same name: say which is which.
                src = a.source or ("system" if a.system else "user")
                text.append(label(f"{label_for_source(src)} · {a.id}", ("small", "dim", "mono"),
                                  ellipsize=True))
            row.set_child(hbox(10, img, text, mark))
            row.connect("clicked", lambda _r, app=a: (b.popdown(), on_pick(app)))
            box.append(row)
        pop = Gtk.Popover()
        pop.add_css_class("options")
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                    max_content_height=420)
        scroll.set_child(box)
        box.set_size_request(260, -1)
        pop.set_child(scroll)
        b.set_popover(pop)
        return b

    def _set(self, cat, app):
        notes = []

        def plan():
            changes, n = defaults.plan_set(cat, app)
            notes.extend(n)
            return changes

        def after(_result):
            if notes:
                Dialog(self.win, _("{app} is set, with a note").format(app=app.name), " ".join(notes),
                       [("ok", _("OK"), "filled")], icon_name="info").present()
            self.reload()
            return []

        what = _(OPENS.get(cat.key, cat.name))
        self._run(plan, lambda n: _("{app} opens {what} now").format(app=app.name, what=what),
                  _("Couldn't set {app}").format(app=app.name), after=after)

    def _reset(self, cat):
        name = _(NAMES.get(cat.key, (cat.name,))[0])

        def after(_result):
            self.reload()
            return []

        self._run(lambda: defaults.plan_reset(cat),
                  lambda n: _("{what}: back to your desktop's choice").format(what=name),
                  _("Couldn't reset {what}").format(what=name.lower()), after=after)

