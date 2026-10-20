"""Checking for and installing updates, and the Updates page in Preferences."""
import subprocess
import time
from gettext import gettext as _

from gi.repository import Gio, GLib, Gtk

from .. import APP_NAME, VERSION, updater
from .dialogs import run_bg
from .widgets import button, card, glyph, hbox, label, section, set_text, switch_row, vbox


class UpdateManager:
    """Shared by the app (the check at startup) and the Updates page."""

    def __init__(self, app, settings):
        self.app = app
        self.settings = settings
        self.where = updater.location()
        self.release = None       # the newest release found, if newer than this version
        self.checked = False      # a check finished in this session
        self.checking = False
        self.installing = False
        self.installed = ""       # version installed in this session; restart to use it
        self.error = ""
        self._listeners = []

    def connect(self, cb):
        self._listeners.append(cb)

    def disconnect(self, cb):
        if cb in self._listeners:
            self._listeners.remove(cb)

    def _changed(self):
        for cb in list(self._listeners):
            cb()

    def startup(self):
        """The automatic check: only when it's turned on, and at most every few hours."""
        if not self.settings.get("check-updates") or self.where.kind == "source":
            return
        if time.time() - self.settings.get("last-update-check") >= updater.CHECK_EVERY:
            self.check(auto=True)

    def check(self, auto=False):
        if self.checking or self.installing:
            return
        self.checking, self.error = True, ""
        self._changed()
        test = self.settings.get("update-test")

        def done(result):
            self.checking = False
            if isinstance(result, Exception):
                self.error = str(result) if isinstance(result, updater.UpdateError) else _("The check failed.")
            else:
                self.checked = True
                self.settings.set("last-update-check", int(time.time()))
                self.release = result if result and updater.is_newer(result.version) else None
                self.settings.set("latest-version", result.version if result else "")
                if auto and self.release:
                    self._announce()
            self._changed()

        run_bg(lambda: updater.latest(test), done)

    def _announce(self):
        r = self.release
        win = self.app.window
        if win is not None and hasattr(win, "snackbar"):
            win.snackbar.show(_("{app} {version} is available").format(app=APP_NAME, version=r.version),
                              _("See"), lambda: self.app.activate_action("updates", None), seconds=8)
        if self.settings.get("update-notify"):
            n = Gio.Notification.new(_("{app} {version} is available").format(app=APP_NAME, version=r.version))
            n.set_body(_("Open App Entries to see what's new and update."))
            n.set_default_action("app.updates")
            self.app.send_notification("update", n)

    def install(self):
        if not self.release or self.installing:
            return
        self.installing, self.error = True, ""
        self._changed()
        release = self.release

        def done(result):
            self.installing = False
            if isinstance(result, Exception):
                self.error = str(result)
            else:
                self.installed = release.version
                self.release = None
            self._changed()

        run_bg(lambda: updater.install(release, self.where), done)

    def restart(self):
        try:
            subprocess.Popen([self.where.launcher], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            self.error = _("Couldn't start the new version: {reason}").format(reason=e.strerror or e)
            self._changed()
            return
        self.app.quit()


class UpdatesPage(Gtk.Box):
    def __init__(self, manager, settings):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.m = manager
        self.settings = settings

        self.append(section(_("Updates"), _("New versions of App Entries come from its releases on GitHub.")))
        c = card()
        self.title = label("", ("title",))
        self.status = label("", ("body", "dim"), wrap=True, chars=50)
        self.spinner = Gtk.Spinner(visible=False)
        self.action = button(_("Check now"), "refresh", "tonal", cb=self._on_action)
        self.action.set_halign(Gtk.Align.START)
        self.page_btn = button(_("Release page"), "open_in_new", "text", small=True,
                               tooltip=_("Open the release on GitHub in your browser"), cb=self._open_page)
        self.notes = label("", ("small",), wrap=True, chars=60)
        self.notes.set_selectable(True)
        self.notes_box = vbox(4, label(_("What's new"), ("body", "option-title")), self.notes)
        self.foot = label("", ("small", "faint"), wrap=True, chars=60)
        c.append(self.title)
        c.append(self.status)
        c.append(hbox(10, self.action, self.spinner, self.page_btn))
        c.append(self.notes_box)
        c.append(self.foot)
        self.append(c)

        self.append(section(_("Checking")))
        c = card()
        for key, text in (("check-updates", _("Look for updates when App Entries starts")),
                          ("update-notify", _("Show a notification when there's a new version")),
                          ("update-test", _("Include test versions"))):
            row, _sw = switch_row(text, settings.get(key), lambda v, k=key: settings.set(k, v))
            c.append(row)
        c.append(label(_("App Entries asks GitHub for its list of releases at most once every six hours, when it "
                         "starts, and sends nothing about you. Test versions are releases marked as pre-releases; "
                         "they get new features first and may have rough edges."),
                       ("small", "faint"), wrap=True, chars=60))
        self.append(c)

        manager.connect(self.refresh)
        self.connect("destroy", lambda *_: manager.disconnect(self.refresh))
        self.refresh()

    def refresh(self):
        m = self.m
        r = m.release
        set_text(self.title, "%s %s" % (APP_NAME, VERSION))
        self.spinner.set_visible(m.checking or m.installing)
        self.spinner.set_spinning(m.checking or m.installing)
        self.notes_box.set_visible(bool(r and r.notes.strip()))
        if r:
            set_text(self.notes, r.notes.strip()[:1500])
        self.page_btn.set_visible(bool(r) or m.where.kind == "system")

        if m.installing:
            status = _("Installing {version}…").format(version=r.version if r else "")
        elif m.installed:
            status = _("Version {version} is installed. Restart App Entries to use it.").format(version=m.installed)
        elif m.checking:
            status = _("Checking…")
        elif m.error:
            status = m.error
        elif r:
            status = _("Version {version} is available.").format(version=r.version)
        elif m.checked:
            status = _("You have the latest version.")
        else:
            known = self.settings.get("latest-version")
            if known and updater.is_newer(known):
                status = _("Version {version} was found earlier. Check again to update.").format(version=known)
            else:
                status = _("Press Check now to see if there's a newer version.")
        set_text(self.status, status)

        self._set_action()
        kind = m.where.kind
        if kind == "home":
            foot = _("Updating needs no password: the new version installs like the old one, into your home "
                     "folder. Your settings, icons and launchers aren't touched, and the current version is put "
                     "back if anything goes wrong.")
        elif kind == "system":
            foot = _("App Entries is installed for all users (in {prefix}), so updating needs administrator "
                     "rights: download the release and run sudo ./install.sh --system.").format(prefix=m.where.prefix)
        elif kind == "source":
            foot = _("You're running App Entries from its source folder. Update it there with git pull.")
        else:
            foot = _("App Entries wasn't installed with install.sh, so it can't update itself. "
                     "Update it the way you installed it.")
        set_text(self.foot, foot)

    def _set_action(self):
        m = self.m
        child = self.action.get_child()
        if m.installed:
            text, glyph_name, style = _("Restart now"), "restart_alt", "filled"
        elif m.release and m.where.can_update:
            text, glyph_name, style = _("Update to {version}").format(version=m.release.version), "download", "filled"
        else:
            text, glyph_name, style = _("Check now"), "refresh", "tonal"
        set_text(child.get_first_child(), glyph(glyph_name))
        set_text(child.get_last_child(), text)
        for s in ("filled", "tonal"):
            (self.action.add_css_class if s == style else self.action.remove_css_class)(s)
        self.action.set_sensitive(not (m.checking or m.installing))

    def _on_action(self, *_a):
        m = self.m
        if m.installed:
            m.restart()
        elif m.release and m.where.can_update:
            m.install()
        else:
            m.check()

    def _open_page(self, *_a):
        url = self.m.release.url if self.m.release else updater.PAGE
        try:
            Gio.AppInfo.launch_default_for_uri(url, None)
        except GLib.Error:
            pass
