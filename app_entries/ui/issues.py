"""The Issues page: problems found in the app list, each with an explanation
and a button to fix it. Nothing is changed until a button is pressed."""
from gettext import gettext as _

from gi.repository import Gtk, Pango

from .app_card import SOURCES, gicon_for
from .widgets import Toggle, button, card, clear, hbox, icon, label, section, vbox


def _app_icon(name):
    img = Gtk.Image(pixel_size=32, accessible_role=Gtk.AccessibleRole.PRESENTATION)
    img.set_from_gicon(gicon_for(name))
    tile = Gtk.Box(valign=Gtk.Align.CENTER)
    tile.add_css_class("icon-tile")
    tile.add_css_class("small-tile")
    tile.append(img)
    return tile


def _glyph_tile(icon_name):
    tile = Gtk.Box(valign=Gtk.Align.CENTER)
    tile.add_css_class("icon-tile")
    tile.add_css_class("small-tile")
    g = icon(icon_name)
    g.set_size_request(32, 32)
    tile.append(g)
    return tile


def _row(lead, title, detail, *actions, extra=()):
    """extra: further (text, classes) lines under the detail."""
    text = vbox(2, label(title, ("body", "app-name"), ellipsize=True))
    for line, classes in [(detail, ("small", "dim"))] + list(extra):
        d = label(line, classes, ellipsize=True)
        d.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        d.set_tooltip_text(line)
        d.set_selectable(False)
        text.append(d)
    text.set_hexpand(True)
    text.set_valign(Gtk.Align.CENTER)
    for a in actions:
        a.set_valign(Gtk.Align.CENTER)
    row = hbox(14, lead, text, *actions)
    row.add_css_class("issue-row")
    return row


class IssuesPage(Gtk.ScrolledWindow):
    """`fix(kind, targets)` is called when a button is pressed; `toggle(app,
    hidden)` when a duplicate's switch is flipped."""

    def __init__(self, fix, toggle, copy):
        super().__init__(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self._fix = fix
        self._toggle = toggle
        self._copy = copy
        self._signature = None
        self.page = vbox(0)
        self.page.set_margin_bottom(96)
        self.page.set_margin_start(4)
        self.page.set_margin_end(4)
        self.set_child(self.page)

    def update(self, report):
        sig = (tuple(a.id for a in report.legacy), tuple(l.path for l in report.leftovers),
               tuple((a.id, a.missing) for a in report.missing),
               tuple(sorted((k, o.command) for k, o in report.owners.items())),
               tuple(tuple((a.id, a.hidden) for a in g) for g in report.duplicates))
        if sig == self._signature:
            return
        self._signature = sig
        clear(self.page)

        if not report.count:
            empty = vbox(10, icon("check_circle", ("big", "accent")),
                         label(_("Nothing to fix"), ("title",), xalign=0.5),
                         label(_("No leftover files, missing programs or duplicates were found. "
                                 "This page checks again whenever your apps change."),
                               ("body", "dim"), wrap=True, xalign=0.5, chars=50))
            empty.set_margin_top(80)
            self.page.append(empty)
            return

        if report.legacy:
            self._section(
                _("Hidden the old way"),
                _("An earlier test version of App Entries hid these apps with Hidden=true, which can stop "
                  "them opening links and files. Updating rewrites each hide file the new way "
                  "(NoDisplay=true). They stay hidden."),
                _("Update all"), "legacy", report.legacy,
                [_row(_app_icon(a.icon), a.name, a.override_path,
                      button(_("Update"), style="tonal", small=True,
                             tooltip=_("Rewrite this hide file the new way; the app stays hidden"),
                             cb=lambda _b, a=a: self._fix("legacy", [a])))
                 for a in report.legacy])

        if report.leftovers:
            self._section(
                _("Leftover files"),
                _("Files in your applications folder for apps that are no longer installed. They don't "
                  "do anything now. Removing deletes only these files, and you can undo it."),
                _("Remove all"), "leftovers", report.leftovers,
                [_row(_glyph_tile("cleaning_services"), l.name, l.path,
                      button(_("Remove"), style="tonal", small=True,
                             tooltip=_("Delete this leftover file"),
                             cb=lambda _b, l=l: self._fix("leftovers", [l])))
                 for l in report.leftovers])

        if report.missing:
            rows = []
            for a in report.missing:
                actions = [button(_("Hide"), style="tonal", small=True,
                                  tooltip=_("Keep it out of launcher menus; nothing is deleted"),
                                  cb=lambda _b, a=a: self._fix("missing", [a]))]
                if a.source == "user" and a.override_path and not a.override_managed:
                    actions.insert(0, button(_("Delete"), style="text", small=True,
                                             tooltip=_("Delete this launcher file (you'll be asked first)"),
                                             cb=lambda _b, a=a: self._fix("delete", [a])))
                extra = [(_("Runs: {command}").format(command=a.exec), ("mono", "faint"))]
                owner = report.owners.get(a.id)
                if owner is not None:
                    extra.append((_("Installed by the package {package}").format(package=owner.package),
                                  ("small", "dim")))
                    actions.insert(0, button(_("Copy remove command"), style="text", small=True,
                                             tooltip=_("Copies “{command}” so you can run it in a terminal. "
                                                       "App Entries doesn't run it.").format(command=owner.command),
                                             cb=lambda _b, c=owner.command: self._copy(c)))
                rows.append(_row(_app_icon(a.icon), a.name,
                                 _("Needs {program}, which wasn't found").format(program=a.missing),
                                 *actions, extra=extra))
            self._section(
                _("Missing programs"),
                _("These entries start a program that wasn't found in your PATH or the usual program "
                  "folders, so clicking them does nothing or shows an error. Hide keeps an entry out of "
                  "your menus without deleting anything. For entries installed by a package, the cleanest "
                  "fix is removing that package: copy its remove command and run it in a terminal, after "
                  "checking what else it would remove. Launchers you made yourself can also be deleted."),
                _("Hide all"), "missing", report.missing, rows)

        if report.duplicates:
            rows = []
            for group in report.duplicates:
                rows.append(label(group[0].name, ("subheading",)))
                for a in group:
                    sw = Toggle(a.hidden, lambda v, a=a: self._toggle(a, v))
                    sw.update_property([Gtk.AccessibleProperty.LABEL],
                                       [_("Hide {name} ({id})").format(name=a.name, id=a.id)])
                    sw.set_tooltip_text(_("Hidden from launcher"))
                    src = _(SOURCES.get(a.source, SOURCES["system"])[1])
                    rows.append(_row(_app_icon(a.icon), "%s · %s" % (a.id, src), a.exec,
                                     label(_("Hidden"), ("small", "dim")), sw))
            self._section(
                _("Duplicates"),
                _("These names appear more than once in your launcher, usually because the app is "
                  "installed two ways (for example as a system package and as a Flatpak). Hide the "
                  "copies you don't use."),
                None, "duplicates", report.duplicates, rows)

    def _section(self, title, explanation, fix_all, kind, targets, rows):
        head = section(title, explanation)
        head.set_hexpand(True)
        top = hbox(12, head)
        if fix_all and len(targets) > 1:
            b = button(fix_all, style="tonal", small=True, cb=lambda *_: self._fix(kind, list(targets)))
            b.set_valign(Gtk.Align.END)
            b.set_margin_bottom(6)
            top.append(b)
        self.page.append(top)
        c = card()
        for r in rows:
            c.append(r)
        self.page.append(c)
