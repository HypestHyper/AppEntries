"""The Uninstall window: what goes, what else it affects, the command that
will run, and only then the uninstall itself. Also the one for several
apps at once."""
import os
import subprocess
from gettext import gettext as _
from gettext import ngettext

from gi.repository import Gdk, GLib, Gtk, Pango

from .. import terminal, uninstall
from .app_card import gicon_for
from .dialogs import run_bg
from .widgets import Chip, Toggle, button, card, clear, hbox, icon, label, section, set_text, vbox


def _short(p):
    home = os.path.expanduser("~")
    return "~" + p[len(home):] if p.startswith(home + os.sep) else p


def _size(n):
    return GLib.format_size(n) if n else ""


def _mono(text, wrap=False):
    lb = label(text, ("mono",), wrap=wrap, chars=52 if wrap else 0, ellipsize=not wrap)
    if not wrap:
        lb.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        lb.set_tooltip_text(text)
    return lb


def _file_row(glyph, text, size=0):
    lb = label(text, ("body",), wrap=True, chars=48)
    lb.set_hexpand(True)
    row = hbox(10, icon(glyph, ("dim",)), lb)
    if size:
        row.append(label(_size(size), ("small", "faint", "tnum")))
    return row


def _tile(icon_name, px=48):
    img = Gtk.Image(pixel_size=px, accessible_role=Gtk.AccessibleRole.PRESENTATION)
    img.set_from_gicon(gicon_for(icon_name))
    tile = Gtk.Box(valign=Gtk.Align.CENTER)
    tile.add_css_class("icon-tile")
    if px < 48:
        tile.add_css_class("small-tile")
    tile.append(img)
    return tile


def _what_runs(in_terminal, password, steam=False, manager=""):
    """The note under the command."""
    if steam:
        return _("Opens Steam, which asks you to confirm and removes the game itself.")
    if in_terminal and password:
        return (_("Opens your terminal running this, so you see everything it does. {tool} asks for your "
                  "password there; App Entries never sees it.").format(tool=manager or _("It")))
    if in_terminal:
        return _("Opens your terminal running this, so you see everything it does.")
    return _("Runs here. No password needed.")


class _Base(Gtk.Window):
    def __init__(self, win, title):
        super().__init__(transient_for=win, modal=True, title=title)
        self.win = win
        self.add_css_class("prefs")
        self.set_default_size(600, 720)
        self._hb = Gtk.HeaderBar()
        self._hb.set_show_title_buttons(False)
        self._hb.set_title_widget(label(title, ("title",)))
        self.set_titlebar(self._hb)
        self._buttons = []
        self._scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.set_child(self._scroll)
        self._busy = False
        self._timer = 0
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", lambda _c, kv, *_a: kv == Gdk.KEY_Escape and not self._busy
                     and (self.close() or True))
        self.add_controller(keys)
        self.connect("close-request", lambda *_a: self._busy)
        self.connect("destroy", lambda *_a: self._stop_timer())

    def _page(self, *children, top=0):
        page = vbox(0, *children)
        self._current = page
        for s in ("start", "end", "bottom"):
            getattr(page, "set_margin_" + s)(20)
        page.set_margin_top(top)
        self._scroll.set_child(page)
        return page

    def _set_buttons(self, *items):
        for b in self._buttons:
            self._hb.remove(b)
        self._buttons = []
        for side, b in items:
            b.set_valign(Gtk.Align.CENTER)
            (self._hb.pack_start if side == "start" else self._hb.pack_end)(b)
            self._buttons.append(b)

    def _copy(self, text):
        clip = self.get_clipboard()
        try:
            clip.set(text)
        except (TypeError, AttributeError):
            clip.set_content(Gdk.ContentProvider.new_for_value(text))
        self.win.snackbar.show(_("Copied"))

    def _command_card(self, title, text, note, glyph="info"):
        c = card()
        c.add_css_class("card-inner")
        c.set_margin_top(16)
        self._cmd_title = label(title, ("body", "option-title"))
        c.append(self._cmd_title)
        self._cmd_label = _mono(text, wrap=True)
        self._cmd_label.set_selectable(True)
        self._cmd_label.set_hexpand(True)
        copy = button(_("Copy"), "content_copy", "tonal", small=True,
                      cb=lambda *_a: self._copy(self._cmd_label.get_label()))
        copy.set_valign(Gtk.Align.START)
        self._cmd_copy = copy
        c.append(hbox(10, self._cmd_label, copy))
        self._cmd_note = label(note, ("small", "dim"), wrap=True, chars=58)
        self._cmd_note.set_hexpand(True)
        c.append(hbox(8, icon(glyph, ("dim",)), self._cmd_note))
        return c

    def _stop_timer(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    # -- running ------------------------------------------------------------

    def _progress_page(self, header, steps):
        self._steps = []
        self._active = -1
        box = card()
        for text in steps:
            ic = icon("radio_button_unchecked", ("faint",))
            lb = label(text, ("body", "faint"), wrap=True, chars=50)
            box.append(hbox(10, ic, lb))
            self._steps.append((ic, lb))
        self._log = Gtk.TextView(monospace=True, editable=False, cursor_visible=False, top_margin=10,
                                 bottom_margin=10, left_margin=12, right_margin=12,
                                 wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self._log.add_css_class("textarea")
        self._log.set_size_request(-1, 160)
        self._wait_label = label("", ("small", "dim"), wrap=True, chars=60)
        self._wait_label.set_margin_top(10)
        self._page(header, section(_("Progress")), box, self._wait_label,
                   section(_("Details"), _("What it printed.")), self._log)
        cancel = button(_("Cancel"), style="tonal", small=True)
        cancel.set_sensitive(False)
        cancel.set_tooltip_text(_("It can't be stopped once it has started"))
        self._set_buttons(("start", cancel))

    def _step(self, n, state):
        """state: 'run', 'done' or 'fail'."""
        if not 0 <= n < len(self._steps):
            return
        ic, lb = self._steps[n]
        glyph, cls = {"run": ("progress_activity", "accent"), "done": ("check_circle", "accent"),
                      "fail": ("error", "error-text")}[state]
        set_text(ic, {"progress_activity": ""}.get(glyph, ic.get_label()))
        ic.set_label(_glyph(glyph))
        for c in ("faint", "accent", "error-text"):
            ic.remove_css_class(c)
            lb.remove_css_class(c)
        ic.add_css_class(cls)
        if state == "fail":
            lb.add_css_class("error-text")

    def _print(self, text):
        buf = self._log.get_buffer()
        buf.insert(buf.get_end_iter(), text + "\n")
        mark = buf.create_mark(None, buf.get_end_iter(), False)
        self._log.scroll_mark_onscreen(mark)

    def _run(self, title, here, term, steam, on_done):
        """Run the commands that need no password here, then the rest in a
        terminal (or open Steam), and call on_done(ok, message)."""
        def after_here(code):
            if code != 0:
                on_done(False, _("It stopped with exit code {code}.").format(code=code))
            elif term:
                self._in_terminal(title, term, on_done)
            elif steam:
                self._in_steam(steam, on_done)
            else:
                on_done(True, "")

        if here:
            def work():
                code = 0
                for argv in here:
                    GLib.idle_add(self._print, "$ " + terminal.shown([argv]))
                    code = uninstall.stream(argv, lambda line: GLib.idle_add(self._print, line))
                    if code != 0:
                        break
                return code
            run_bg(work, lambda code: after_here(code if isinstance(code, int) else 1))
        else:
            after_here(0)

    def _in_terminal(self, title, cmds, on_done):
        """Hand the commands to the user's terminal, which handles everything
        from there. This waits until what was uninstalled is gone."""
        self._print(_("Opened in your terminal:"))
        for text in terminal.shown(cmds).splitlines():
            self._print("$ " + text)
        try:
            terminal.start(cmds)
        except terminal.NoTerminal:
            on_done(False, _("No terminal app was found. Run the command yourself in a terminal."),
                    copy=terminal.shown(cmds))
            return
        except OSError as e:
            on_done(False, _("The terminal couldn't be started: {why}.").format(why=e.strerror or e))
            return
        set_text(self._wait_label, _("Follow what your terminal asks. This continues once it's uninstalled; "
                                     "the terminal stays open so you can read what it printed."))
        self._wait_for_gone(on_done)

    def _wait_for_gone(self, on_done):
        checking = [False]

        def finish(gone):
            self._stop_timer()
            self._set_buttons()
            on_done(True if gone else None, "")

        stop = button(_("Stop waiting"), style="tonal", small=True,
                      tooltip=_("For when it stopped or you closed the terminal. App Entries checks once more "
                                "whether it was uninstalled."),
                      cb=lambda *_a: run_bg(self._check_gone, lambda g: finish(g is True)))
        self._set_buttons(("start", stop))

        def checked(gone):
            checking[0] = False
            if gone is True and self._timer:
                finish(True)

        def poll():
            if not checking[0]:
                checking[0] = True
                run_bg(self._check_gone, checked)
            return True

        self._timer = GLib.timeout_add(1500, poll)

    def _in_steam(self, cmds, on_done):
        for argv in cmds:
            self._print("$ " + terminal.shown([argv]))
            try:
                subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError as e:
                on_done(False, _("Steam couldn't be opened: {why}.").format(why=e.strerror or e))
                return
        set_text(self._wait_label, _("Confirm in Steam's window. This continues once Steam has removed it."))
        self._wait_for_gone(on_done)

    def _check_gone(self):
        return False


def _glyph(name):
    from .widgets import glyph
    return glyph(name)


# ---------------------------------------------------------------------------


class UninstallWindow(_Base):
    """`finish(items, message, done)` removes App Entries' own files and
    records it (the main window's finish_uninstall)."""

    def __init__(self, win, app, apps, finish):
        super().__init__(win, _("Uninstall {name}").format(name=app.name))
        self.app = app
        self.apps = apps
        self._finish = finish
        self.plan = None
        self.opts = []
        self._updating = False
        self._pending = False
        self._toggles = {}
        self._warn_labels = {}
        self._page(self._header(_("Looking at what would be removed…")), top=8)
        cancel = button(_("Cancel"), style="tonal", small=True, cb=lambda *_a: self.close())
        self._set_buttons(("start", cancel))
        run_bg(lambda: uninstall.plan(app, apps), self._planned)

    def _header(self, sub, chip=""):
        t = vbox(4, label(self.app.name, ("title",), wrap=True, chars=40),
                 label(sub, ("small", "dim"), wrap=True, chars=50))
        if chip:
            c = Chip(chip, "")
            c.set_halign(Gtk.Align.START)
            t.append(c)
        t.set_hexpand(True)
        t.set_valign(Gtk.Align.CENTER)
        h = hbox(16, _tile(self.app.icon), t)
        h.add_css_class("card-inner")
        h.set_margin_top(8)
        return h

    def _sub(self):
        p = self.plan
        bits = [p.target]
        if p.version:
            bits.append(p.version)
        if p.size:
            bits.append(_size(p.size))
        return " · ".join(bits)

    # -- review -------------------------------------------------------------

    def _planned(self, result):
        if isinstance(result, Exception):
            self._page(self._header(_("Couldn't look at it")), self._problem(str(result)), top=8)
            return
        self.plan = result
        self.opts = result.defaults()
        self._review()

    def _problem(self, text, title=None):
        c = card()
        c.add_css_class("warn-card")
        c.set_margin_top(14)
        c.append(hbox(10, icon("error"), label(title or _("Can't be uninstalled here"),
                                               ("body", "option-title"))))
        c.append(label(text, ("small",), wrap=True, chars=60))
        return c

    def _review(self):
        p = self.plan
        body = vbox(0, self._header(self._sub(), p.kind_label))
        if p.blocked:
            body.append(self._problem(p.blocked))
            self._page(body, top=8)
            self._set_buttons(("end", button(_("Close"), style="filled", small=True, cb=lambda *_a: self.close())))
            return

        if p.kind == "package" and p.manager is not None:
            exact = p.preview is not None and p.preview.exact
            body.append(section(_("What {tool} would do").format(tool=p.manager.label),
                                _("Its own dry run, before anything changes.") if exact else
                                _("Worked out from its list of what needs what. It shows the full list and asks "
                                  "before it removes anything.")))
        else:
            body.append(section(_("What's removed"), _("Removed when you press Uninstall.")))
        self._removes = card()
        body.append(self._removes)

        self._warn = card()
        self._warn.add_css_class("warn-card")
        self._warn.set_margin_top(14)
        body.append(self._warn)

        if p.also:
            body.append(section(_("Also remove"), _("Off unless you turn them on.")))
            c = card()
            for o in p.also:
                c.append(self._switch(o))
                for f in p.folders.get(o.key, []):
                    c.append(_file_row("folder", _short(f)))
                size = p.folder_sizes.get(o.key, 0)
                c.append(label(o.explanation + ((" " + _size(size) + ".") if size else ""), ("small", "dim"),
                               wrap=True, chars=60))
            body.append(c)

        if p.advanced:
            exp = Gtk.Expander(label=_("Advanced"), expanded=any(o.key in self.opts and o.warning
                                                                 for o in p.advanced))
            exp.add_css_class("advanced")
            inner = vbox(10)
            inner.set_margin_top(10)
            for o in p.advanced:
                inner.append(self._switch(o))
                inner.append(label(o.explanation, ("small", "dim"), wrap=True, chars=60))
                if o.warning:
                    w = label("", ("small", "error-text"), wrap=True, chars=56)
                    w.set_hexpand(True)
                    row = hbox(8, icon("warning", ("error-text",)), w)
                    self._warn_labels[o.key] = (row, w)
                    inner.append(row)
            exp.set_child(inner)
            c = card()
            c.append(exp)
            c.set_margin_top(14)
            body.append(c)

        body.append(self._command_card("", "", ""))
        self._page(body, top=8)
        self._go = button(_("Uninstall in terminal") if p.in_terminal else _("Uninstall"), style="danger",
                          small=True, cb=lambda *_a: self._start())
        cancel = button(_("Cancel"), style="tonal", small=True, cb=lambda *_a: self.close())
        self._set_buttons(("start", cancel), ("end", self._go))
        self._refresh()

    def _switch(self, o):
        lb = label(o.title, ("body",), wrap=True, chars=44)
        lb.set_hexpand(True)
        sw = Toggle(o.key in self.opts, lambda v, k=o.key: self._toggled(k, v))
        sw.update_property([Gtk.AccessibleProperty.LABEL], [o.title])
        self._toggles[o.key] = sw
        return hbox(12, lb, sw)

    def _toggled(self, key, on):
        opts = [k for k in self.opts if k != key]
        if on:
            opts.append(key)
            o = next(x for x in self.plan.options if x.key == key)
            for other in o.excludes:
                if other in opts:
                    opts.remove(other)
                    if other in self._toggles:
                        self._toggles[other].set_value(False)
        self.opts = opts
        self._update()

    def _update(self):
        if self._updating:
            self._pending = True
            return
        self._updating = True
        self._go.set_sensitive(False)
        opts = list(self.opts)

        def done(result):
            self._updating = False
            if self._pending:
                self._pending = False
                self._update()
                return
            if isinstance(result, Exception):
                self.plan.stops = str(result)
            self._refresh()

        run_bg(lambda: self.plan.update(opts), done)

    def _refresh(self):
        p = self.plan
        clear(self._removes)
        for line in p.removes:
            self._removes.append(_file_row(line.glyph, line.text, line.size))
        if p.app_ids and p.kind in ("package", "flatpak", "snap"):
            self._removes.append(_file_row("history", _("App Entries' own settings for it, if any (hidden, "
                                                        "edited, icons it drew). Undo puts them back.")))

        clear(self._warn)
        lines = []
        pv = p.preview
        if p.stops:
            lines.append(p.stops)
        if p.goes_too:
            lines.append(ngettext("This app goes too: {apps}.", "These apps go too: {apps}.", len(p.goes_too))
                         .format(apps=", ".join(p.goes_too)))
        if pv is not None and pv.dependents and pv.dependents_go and not p.stops:
            lines.append(ngettext("{n} package needs it and is removed with it: {pkgs}.",
                                  "{n} packages need it and are removed with it: {pkgs}.", len(pv.dependents))
                         .format(n=len(pv.dependents), pkgs=", ".join(pv.dependents)))
        if p.stop_working:
            lines.append(ngettext("This stays in your menus but stops working: {apps}.",
                                  "These stay in your menus but stop working: {apps}.", len(p.stop_working))
                         .format(apps=", ".join(p.stop_working)))
        if pv is not None and pv.optional_for:
            lines.append(_("These can use it and keep working without it, with fewer features: {pkgs}.")
                         .format(pkgs=", ".join(pv.optional_for)))
        if pv is not None and pv.group_packages:
            lines.append(_("{pkgs} goes too. It's a package that only groups others, so nothing else is removed "
                           "now, but later updates won't add new apps from that group.")
                         .format(pkgs=", ".join(pv.group_packages)))
        lines += p.notes
        self._warn.set_visible(bool(lines))
        if lines:
            title = _("{tool} would stop").format(tool=p.manager.label) if p.stops and p.manager else \
                _("Before you uninstall")
            self._warn.append(hbox(10, icon("warning"), label(title, ("body", "option-title"))))
            for text in lines:
                self._warn.append(label(text, ("small",), wrap=True, chars=60))

        for key, (row, w) in self._warn_labels.items():
            row.set_visible(key in self.opts)
            set_text(w, p.warnings.get(key, ""))

        cmds = p.commands(self.opts)
        title = ngettext("Command that will run", "Commands that will run", len(cmds)) if cmds else \
            _("Nothing to run")
        set_text(self._cmd_title, title)
        self._cmd_label.set_visible(bool(cmds))
        self._cmd_copy.set_visible(bool(cmds))
        set_text(self._cmd_label, terminal.shown(cmds))
        if cmds:
            note = _what_runs(p.in_terminal, p.password, p.opens_steam,
                              p.manager.label if p.manager else ("snap" if p.kind == "snap" else "Flatpak"))
        else:
            note = _("App Entries removes these files itself.")
        again = p.reinstall(self.opts)
        note += " " + (_("Everything App Entries removes comes back with Undo, and History has a Reinstall "
                         "button.") if again else _("Everything comes back with Undo."))
        set_text(self._cmd_note, note)
        self._go.set_sensitive(p.can_go(self.opts) and not self._updating)

    # -- uninstalling -------------------------------------------------------

    def _start(self):
        p, opts = self.plan, list(self.opts)
        self._busy = True
        cmds = p.commands(opts)
        how = (_("Uninstall it in your terminal") if p.in_terminal else
               _("Open Steam to uninstall it") if p.opens_steam else _("Uninstall {name}").format(name=p.app.name))
        steps = ([how] if cmds else []) + [_("Remove its menu entries and App Entries' files for it"),
                                           _("Record it in History")]
        self._progress_page(self._header(_("Uninstalling…"), p.kind_label), steps)
        offset = 0 if cmds else -1
        if cmds:
            self._step(0, "run")
        here = [] if (p.in_terminal or p.opens_steam) else cmds
        term = cmds if p.in_terminal else []
        steam = cmds if p.opens_steam else []

        def ran(ok, message, copy=""):
            if message:
                self._print(message)
            if ok is False:
                self._failed(message, copy)
                return
            run_bg(p.gone, lambda gone: checked(gone is True))

        def checked(gone):
            if not gone:
                self._failed(_("{name} is still installed.").format(name=p.app.name))
                return
            if cmds:
                self._step(0, "done")
            self._step(1 + offset, "run")
            self._finish([(p, opts)], _("Uninstalled {name}").format(name=p.app.name), finished)

        def finished(error):
            if error:
                self._step(1 + offset, "fail")
                self._print(error)
                self._failed(_("{name} was uninstalled, but App Entries couldn't remove its own files: {why}")
                             .format(name=p.app.name, why=error), done=True)
                return
            self._step(1 + offset, "done")
            self._step(2 + offset, "done")
            self._done(opts)

        self._run(_("uninstalling {name}").format(name=p.app.name), here, term, steam, ran)

    def _check_gone(self):
        try:
            return self.plan.gone()
        except Exception:  # noqa: BLE001 - keep waiting
            return False

    def _failed(self, message, copy="", done=False):
        self._busy = False
        if not done and self._active >= 0:
            self._step(self._active, "fail")
        text = message + ("" if done else " " + _("Nothing else was changed."))
        box = self._problem(text, _("It didn't finish") if not done else _("Partly done"))
        if copy:
            box.append(hbox(10, _mono(copy, wrap=True), button(_("Copy"), "content_copy", "tonal", small=True,
                                                               cb=lambda *_a: self._copy(copy))))
        self._current.insert_child_after(box, self._current.get_first_child())
        self._set_buttons(("end", button(_("Close"), style="filled", small=True, cb=lambda *_a: self.close())))

    def _done(self, opts):
        self._busy = False
        p = self.plan
        body = vbox(14)
        body.set_margin_top(40)
        i = icon("check_circle", ("big", "accent"))
        i.set_halign(Gtk.Align.CENTER)
        body.append(i)
        body.append(label(_("{name} is uninstalled").format(name=p.app.name), ("title",), xalign=0.5))
        bits = []
        if p.size:
            bits.append(_("{size} freed.").format(size=_size(p.size)))
        kept = [f for k, fs in p.folders.items() if k not in opts for f in fs]
        if kept:
            bits.append(_("Kept: {folders}.").format(folders=", ".join(_short(f) for f in kept)))
        if p.manager is not None and p.manager.name == "rpm-ostree":
            bits.append(_("It's gone after you restart."))
        if bits:
            body.append(label(" ".join(bits), ("body", "dim"), xalign=0.5, wrap=True, chars=50))
        again = p.reinstall(opts)
        if again:
            c = card()
            c.set_margin_top(12)
            c.append(label(_("To reinstall it"), ("body", "option-title")))
            text = terminal.shown(again)
            c.append(hbox(10, _mono(text, wrap=True), button(_("Copy"), "content_copy", "tonal", small=True,
                                                            cb=lambda *_a: self._copy(text))))
            c.append(label(_("Also in History, with a Reinstall button."), ("small", "dim")))
            body.append(c)
        self._page(body)
        self._set_buttons(("end", button(_("Close"), style="filled", small=True, cb=lambda *_a: self.close())))


# ---------------------------------------------------------------------------


_GROUP_TITLES = {"flatpak": "Flatpak", "snap": "Snap", "appimage": "AppImage", "distrobox": "Distrobox"}


class BatchUninstallWindow(_Base):
    """Several apps at once, grouped by what installed them. Each group runs
    with one command, so a package manager asks once for all of them."""

    def __init__(self, win, chosen, apps, finish):
        n = len(chosen)
        super().__init__(win, ngettext("Uninstall {n} app", "Uninstall {n} apps", n).format(n=n))
        self.apps = apps
        self._finish = finish
        self.batch = None
        self.data = {}           # app id -> data folders on
        self._page(label(_("Looking at what would be removed…"), ("body", "dim")), top=20)
        self._set_buttons(("start", button(_("Cancel"), style="tonal", small=True, cb=lambda *_a: self.close())))
        run_bg(lambda: uninstall.plan_batch(chosen, apps), self._planned)

    def _opts(self):
        return {p.app.id: p.defaults() + (["data"] if self.data.get(p.app.id) else [])
                for p in self.batch.plans}

    def _planned(self, result):
        if isinstance(result, Exception):
            self._page(label(str(result), ("body", "error-text"), wrap=True), top=20)
            return
        self.batch = result
        body = vbox(0)
        body.append(label(_("Grouped by what installed them. Each group is removed with one command. For the "
                            "advanced options, uninstall apps one at a time."), ("small", "dim"), wrap=True,
                          chars=70))
        for key, plans in result.groups().items():
            if key.startswith("package:"):
                m = plans[0].manager
                title = _("{tool} packages").format(tool=m.label if m else _("System"))
            else:
                title = _GROUP_TITLES.get(key, key)
            body.append(section(title))
            c = card()
            for p in plans:
                bits = [p.target] + ([_size(p.size)] if p.size else [])
                text = vbox(2, label(p.app.name, ("body", "app-name"), ellipsize=True),
                            label(" · ".join(bits), ("small", "dim"), ellipsize=True))
                text.set_hexpand(True)
                row = hbox(12, _tile(p.app.icon, 32), text)
                c.append(row)
                if "data" in p.folders:
                    lb = label(_("Also its data ({size})").format(size=_size(p.folder_sizes.get("data", 0)) or
                                                                  _("size unknown")), ("small",))
                    lb.set_hexpand(True)
                    sw = Toggle(False, lambda v, i=p.app.id: (self.data.__setitem__(i, v), self._refresh()))
                    sw.set_tooltip_text(", ".join(_short(f) for f in p.folders["data"]))
                    sw.update_property([Gtk.AccessibleProperty.LABEL],
                                       [_("Also remove {name}'s data").format(name=p.app.name)])
                    r = hbox(12, lb, sw)
                    r.set_margin_start(44)
                    c.append(r)
                aware = []
                if p.stops:
                    aware.append(p.stops)
                if p.goes_too:
                    aware.append(_("Goes too: {apps}.").format(apps=", ".join(p.goes_too)))
                pv = p.preview
                if pv is not None and pv.dependents and pv.dependents_go:
                    aware.append(_("Removed with it, because they need it: {pkgs}.")
                                 .format(pkgs=", ".join(pv.dependents)))
                if p.stop_working:
                    aware.append(_("Stops working: {apps}.").format(apps=", ".join(p.stop_working)))
                aware += p.notes
                for a in aware:
                    w = hbox(8, icon("warning", ("warn-text",)), label(a, ("small", "warn-text"), wrap=True,
                                                                         chars=56))
                    w.set_margin_start(44)
                    c.append(w)
            body.append(c)
        if result.skipped:
            body.append(section(_("Not included")))
            c = card()
            for name, why in result.skipped:
                c.append(_file_row("error", "%s: %s" % (name, why)))
            body.append(c)
        body.append(self._command_card(_("Commands that will run"), "", ""))
        self._page(body, top=8)
        self._go = button(_("Uninstall"), style="danger", small=True, cb=lambda *_a: self._start())
        self._set_buttons(("start", button(_("Cancel"), style="tonal", small=True, cb=lambda *_a: self.close())),
                          ("end", self._go))
        self._refresh()

    def _refresh(self):
        here, term = self.batch.commands(self._opts())
        cmds = here + term
        set_text(self._cmd_label, terminal.shown(cmds) or _("Nothing to run: App Entries removes the files itself."))
        notes = []
        if here:
            notes.append(_("The first runs here, with no password needed.") if len(here) == 1 else
                         _("The first {n} run here, with no password needed.").format(n=len(here)))
        if term:
            notes.append((_("Then your terminal opens for the rest") if here else _("Your terminal opens")) +
                         _(", so you see everything they do. The package manager asks for your password there, "
                           "once; App Entries never sees it."))
        notes.append(_("Everything App Entries removes comes back with Undo, and History has a Reinstall button."))
        set_text(self._cmd_note, " ".join(notes))
        ok = bool(self.batch.plans) and not any(p.stops for p in self.batch.plans)
        self._go.set_sensitive(ok)
        if term:
            self._go.set_label(_("Uninstall in terminal"))

    def _start(self):
        opts = self._opts()
        here, term = self.batch.commands(opts)
        self._busy = True
        steps = ([_("Uninstall the ones that need no password")] if here else []) + \
            ([_("Uninstall the rest in your terminal")] if term else []) + \
            [_("Remove their menu entries and App Entries' files for them"), _("Record it in History")]
        self._progress_page(label(self.get_title(), ("title",)), steps)
        n_cmd = int(bool(here)) + int(bool(term))
        for n in range(n_cmd):
            self._step(n, "run")

        def ran(ok, message, copy=""):
            if message:
                self._print(message)
            if ok is False and not term:
                self._failed(message)
                return
            run_bg(lambda: [p for p in self.batch.plans if p.gone()], checked)

        def checked(gone):
            if isinstance(gone, Exception):
                gone = []
            for n in range(n_cmd):
                self._step(n, "done" if gone else "fail")
            if not gone:
                self._failed(_("None of them were uninstalled."))
                return
            self._gone = gone
            self._step(n_cmd, "run")
            names = ", ".join(p.app.name for p in gone)
            self._finish([(p, opts[p.app.id]) for p in gone],
                         ngettext("Uninstalled {names}", "Uninstalled {names}", len(gone)).format(names=names),
                         finished)

        def finished(error):
            self._step(n_cmd, "fail" if error else "done")
            self._step(n_cmd + 1, "done")
            self._busy = False
            left = [p.app.name for p in self.batch.plans if p not in self._gone]
            body = vbox(14)
            body.set_margin_top(40)
            i = icon("check_circle" if not left else "warning", ("big", "accent" if not left else "warn-text"))
            i.set_halign(Gtk.Align.CENTER)
            body.append(i)
            body.append(label(ngettext("{n} app uninstalled", "{n} apps uninstalled", len(self._gone))
                              .format(n=len(self._gone)), ("title",), xalign=0.5))
            if left:
                body.append(label(_("Still installed: {names}.").format(names=", ".join(left)), ("body", "dim"),
                                  xalign=0.5, wrap=True, chars=50))
            if error:
                body.append(label(_("App Entries couldn't remove its own files: {why}").format(why=error),
                                  ("body", "error-text"), xalign=0.5, wrap=True, chars=50))
            body.append(label(_("History has a Reinstall button for them."), ("body", "dim"), xalign=0.5))
            self._page(body)
            self._set_buttons(("end", button(_("Close"), style="filled", small=True, cb=lambda *_a: self.close())))

        self._run(_("uninstalling {n} apps").format(n=len(self.batch.plans)), here, term, [], ran)

    def _check_gone(self):
        try:
            return all(p.gone() for p in self.batch.plans)
        except Exception:  # noqa: BLE001 - keep waiting
            return False

    def _failed(self, message, copy=""):
        self._busy = False
        self._print(message)
        set_text(self._wait_label, message + " " + _("Nothing else was changed."))
        self._wait_label.add_css_class("error-text")
        self._set_buttons(("end", button(_("Close"), style="filled", small=True, cb=lambda *_a: self.close())))
