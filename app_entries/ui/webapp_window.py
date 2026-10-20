"""Make or change a web app: a site in its own window, without the browser's
address bar or tabs. Nothing is written until Create (or Save) is pressed."""
import secrets
from gettext import gettext as _

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from .. import icon_library, launchers, symbols, webapps
from .dialogs import error_dialog, run_bg
from .icon_picker import IconPicker, preview_texture
from .widgets import Group, Toggle, button, card, hbox, label, section, set_text, vbox


def _explained(title, explanation, widget):
    return vbox(6, label(title, ("body", "option-title")), widget,
                label(explanation, ("small", "dim"), wrap=True, chars=60))


def _png(data: bytes) -> bytes:
    """ICO, JPEG, WebP or GIF to PNG, at the largest size it has."""
    loader = GdkPixbuf.PixbufLoader()
    loader.write(data)
    loader.close()
    pb = loader.get_pixbuf()
    ok, out = pb.save_to_bufferv("png", [], [])
    if not ok:
        raise ValueError("The icon couldn't be converted.")
    return bytes(out)


class WebAppWindow(Gtk.Window):
    """on_save(did_or_None, spec, False), the same as the launcher window's."""

    def __init__(self, parent, on_save, did=None, text=None, glyph_color="#888888"):
        editing = did is not None
        super().__init__(transient_for=parent, modal=True, title=_("Edit web app") if editing else _("New web app"))
        self.add_css_class("prefs")
        self.set_default_size(620, 720)
        self.did = did
        self._on_save = on_save
        self._glyph = glyph_color
        spec = launchers.read_spec(text) if text else None
        self.spec = spec or launchers.Spec(categories=["Network"])
        if spec is None:
            self.spec.icon = symbols.IconChoice("language", "outlined", "rounded", "#3b82f6")
        self._name_touched = bool(spec)
        self.browsers = webapps.installed()

        hb = Gtk.HeaderBar()
        hb.set_show_title_buttons(False)
        hb.set_title_widget(label(self.get_title(), ("title",)))
        cancel = button(_("Cancel"), style="tonal", small=True, cb=lambda *_a: self.close())
        self.save = button(_("Save") if editing else _("Create"), style="filled", small=True, cb=self._save)
        for b in (cancel, self.save):
            b.set_valign(Gtk.Align.CENTER)
        hb.pack_start(cancel)
        hb.pack_end(self.save)
        self.set_titlebar(hb)

        page = vbox(0)
        for side in ("start", "end"):
            getattr(page, "set_margin_" + side)(20)
        page.set_margin_bottom(24)

        self.prev_icon = Gtk.Image(pixel_size=48, accessible_role=Gtk.AccessibleRole.PRESENTATION)
        self.prev_name = label("", ("heading",), ellipsize=True)
        self.prev_url = label("", ("small", "dim", "mono"), ellipsize=True)
        prev_text = vbox(2, self.prev_name, self.prev_url)
        prev_text.set_valign(Gtk.Align.CENTER)
        prev = hbox(14, self.prev_icon, prev_text)
        prev.add_css_class("card-inner")
        prev.set_margin_top(12)
        page.append(prev)

        # Site
        page.append(section(_("Site")))
        c = card()
        self.url = Gtk.Entry(text=self.spec.web_url, placeholder_text="web.whatsapp.com", hexpand=True)
        self.url.add_css_class("mono")
        self.url.connect("changed", self._on_url)
        c.append(_explained(_("Address"), _("The page it opens. https:// is added if you leave it out."), self.url))
        self.name = Gtk.Entry(text=self.spec.name, placeholder_text=_("WhatsApp"), hexpand=True)
        self.name.connect("changed", self._on_name)
        c.append(_explained(_("Name"), _("How it's listed in your launcher. It's filled in from the address "
                                         "until you change it."), self.name))
        self.comment = Gtk.Entry(text=self.spec.comment, placeholder_text=_("Optional"), hexpand=True)
        self.comment.connect("changed", lambda *_a: self._changed())
        c.append(_explained(_("Description"), _("A short line some launchers show under the name."), self.comment))
        page.append(c)

        # Browser
        page.append(section(_("Window"), _("It opens without the address bar, tabs or menus: just the page, in a "
                                           "window of its own. This uses the app mode of Chromium-based browsers.")))
        c = card()
        if self.browsers:
            current = self.spec.web_browser if any(b[0] == self.spec.web_browser for b in self.browsers) \
                else self.browsers[0][0]
            self.browser = Group([(b[0], b[1]) for b in self.browsers], current, lambda _v: self._changed())
            c.append(_explained(_("Browser"), _("Which browser runs it. Its extensions and settings apply."),
                                self.browser))
        else:
            self.browser = None
            note = _("Web apps need a Chromium-based browser, such as Chromium, Brave, Vivaldi, Google Chrome "
                     "or Microsoft Edge, and none was found.")
            if webapps.has_firefox():
                note += " " + _("Firefox can't open a page without its address bar and tabs, so it can't be used.")
            c.append(label(note, ("body", "warn-text"), wrap=True, chars=60))
        profile_box = vbox(4)
        # On: shares the browser's cookies, so you're already signed in.
        self.shared = Toggle(not self.spec.web_profile, lambda _v: self._changed())
        self.shared.update_property([Gtk.AccessibleProperty.LABEL], [_("Use your browser's sign-ins")])
        head = hbox(12, label(_("Use your browser's sign-ins"), ("body", "option-title")), self.shared)
        head.get_first_child().set_hexpand(True)
        profile_box.append(head)
        profile_box.append(label(_("On, it shares your browser's cookies, so accounts you're signed into there "
                                   "are already signed in here. Turn off to give it separate cookies and logins, "
                                   "for example to use another account in it."),
                                 ("small", "dim"), wrap=True, chars=60))
        c.append(profile_box)

        self.dark = Group([("system", _("Follow system")), ("dark", _("Dark")), ("force", _("Dark everywhere"))],
                          webapps.dark_of(self.spec.args), lambda _v: self._changed())
        c.append(_explained(_("Dark mode"), _("Dark uses the site's own dark theme when it has one. Dark everywhere "
                                              "also darkens sites that don't, which can make some look odd."),
                            self.dark))
        self.dark_note = label(_("While your browser is open, the web app joins it and this is ignored. It "
                                 "always applies with separate sign-ins."), ("small", "warn-text"), wrap=True,
                               chars=60)
        c.append(self.dark_note)

        self.wm_class = label("", ("mono", "dim"), ellipsize=True)
        self.wm_class.set_hexpand(True)
        self.wm_class.set_selectable(True)
        copy = button(_("Copy"), "content_copy", "tonal", self._copy_class, small=True)
        c.append(_explained(_("Window name"), _("What its window is usually called. It's saved in the launcher so "
                                                "docks and taskbars show the window with this icon, and you can "
                                                "use it in window rules, like Hyprland's windowrule = float, "
                                                "class:… If a rule doesn't match, check the real name with your "
                                                "desktop's window list (hyprctl clients on Hyprland)."),
                            hbox(10, self.wm_class, copy)))
        page.append(c)

        # Icon
        page.append(section(_("Icon")))
        c = card()
        self.site_icon_btn = button(_("Use the site's icon"), "download", "tonal", self._fetch_icon, small=True)
        self.spinner = Gtk.Spinner(visible=False)
        c.append(hbox(10, self.site_icon_btn,
                      button(_("Styled icon…"), "palette", "tonal", self._pick_icon, small=True), self.spinner))
        c.append(label(_("The site's icon is downloaded only when you press the button, and kept in your icon "
                         "library. A styled icon is any of 4,000 symbols on a coloured tile."),
                       ("small", "dim"), wrap=True, chars=60))
        page.append(c)

        self.problems = label("", ("small", "error-text"), wrap=True, chars=60)
        self.problems.set_margin_top(12)
        page.append(self.problems)

        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        scroll.set_child(page)
        self.set_child(scroll)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        self._changed()

    # -- state --------------------------------------------------------------

    def _on_url(self, *_a):
        if not self._name_touched:
            try:
                name = webapps.name_for(self.url.get_text())
            except ValueError:
                name = ""
            self._quiet_name = True
            self.name.set_text(name)
            self._quiet_name = False
        self._changed()

    def _on_name(self, *_a):
        if not getattr(self, "_quiet_name", False):
            self._name_touched = True
        self._changed()

    def _profile_path(self):
        # Keep the folder a web app already has; a new one gets a fresh name.
        if getattr(self, "_profile", None) is None:
            self._profile = webapps.profile_of(self.spec.args)
            if not self._profile:
                stem = launchers.slug(self.name.get_text() or "web-app") + "-" + secrets.token_hex(3)
                self._profile = webapps.profile_dir(stem + ".desktop")
        return self._profile

    def form_spec(self):
        s = self.spec
        try:
            url = webapps.normalize(self.url.get_text())
        except ValueError:
            url = ""
        browser = self.browser.active() if self.browser else ""
        program = next((b[2] for b in self.browsers if b[0] == browser), "")
        profile = "" if self.shared.get_active() else self._profile_path()
        dark = self.dark.active() or "system"
        return launchers.Spec(
            name=self.name.get_text().strip(), comment=self.comment.get_text().strip(),
            program=program, args=webapps.args_for(url, profile, dark) if url else "",
            wm_class=webapps.window_class(url, browser) if url else "",
            categories=s.categories or ["Network"], keywords=s.keywords,
            icon_kind="symbol", icon=s.icon, hidden=s.hidden,
            web_url=url, web_browser=browser, web_profile=not self.shared.get_active())

    def _changed(self):
        spec = self.form_spec()
        set_text(self.prev_name, spec.name or _("Web app"))
        set_text(self.prev_url, spec.web_url or _("No address yet"))
        set_text(self.wm_class, spec.wm_class or _("Shown once there's an address"))
        self.dark_note.set_visible(self.dark.active() != "system" and self.shared.get_active())
        try:
            self.prev_icon.set_from_paintable(preview_texture(spec.icon, 48))
        except (GLib.Error, OSError, KeyError, ValueError):
            self.prev_icon.set_from_icon_name("web-browser")
        problems = []
        try:
            webapps.normalize(self.url.get_text())
        except ValueError as e:
            if self.url.get_text().strip():
                problems.append(str(e))
            else:
                problems.append(_("Enter the site's address."))
        if not spec.name:
            problems.append(_("Give it a name."))
        if not self.browsers:
            problems.append(_("Install a Chromium-based browser first."))
        set_text(self.problems, " ".join(problems))
        self.problems.set_visible(bool(problems))
        self.save.set_sensitive(not problems)

    # -- icon ---------------------------------------------------------------

    def _copy_class(self, *_a):
        text = self.form_spec().wm_class
        if text:
            self.get_clipboard().set(text)

    def _pick_icon(self, *_a):
        def picked(choice):
            self.spec.icon = choice
            self._changed()

        IconPicker(self, self.spec.icon, picked, self._glyph).present()

    def _fetch_icon(self, *_a):
        url = self.url.get_text()
        try:
            webapps.normalize(url)
        except ValueError as e:
            error_dialog(self, _("Couldn't get the icon"), str(e))
            return
        self.site_icon_btn.set_sensitive(False)
        self.spinner.set_visible(True)
        self.spinner.start()

        def work():
            data, kind = webapps.fetch_icon(url)
            return data, kind

        def done(result):
            self.site_icon_btn.set_sensitive(True)
            self.spinner.stop()
            self.spinner.set_visible(False)
            if isinstance(result, Exception):
                error_dialog(self, _("Couldn't get the icon"), str(result) if isinstance(result, ValueError)
                             else _("The site couldn't be reached."))
                return
            data, kind = result
            try:
                if kind == "other":
                    data = _png(data)
                host = (webapps.name_for(url) or "site").lower().replace(" ", "-")
                path = icon_library.add_data(data, host + "." + ("svg" if kind == "svg" else "png"))
            except (GLib.Error, ValueError, OSError, icon_library.IconError) as e:
                error_dialog(self, _("Couldn't use the icon"), str(e))
                return
            self.spec.icon = symbols.IconChoice(source="file", path=path, shape="none", recolor=False)
            self._changed()

        run_bg(work, done)

    # -- saving -------------------------------------------------------------

    def _on_key(self, _c, keyval, _code, state):
        if keyval == Gdk.KEY_Escape:
            self.close()
            return True
        if keyval in (Gdk.KEY_s, Gdk.KEY_S) and state & Gdk.ModifierType.CONTROL_MASK:
            if self.save.get_sensitive():
                self._save()
            return True
        return False

    def _save(self, *_a):
        if not self.save.get_sensitive():
            return
        spec = self.form_spec()
        self._on_save(self.did, spec, False)
        self.close()
