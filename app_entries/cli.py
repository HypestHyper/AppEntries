"""The command line: list, hide, show, export and import without the window.
Pure Python, no GTK. Nothing changes unless you ask for it, and changes
that delete a file you didn't make ask first (or need --yes)."""
import argparse
import os
import sys
from typing import List, Optional

from . import APP_NAME, VERSION, history, launcher_refresh, profile
from . import desktop_entries as de
from .overrides import NeedsConfirmation, OverrideError, apply_all, plan_set_hidden

COMMANDS = ("--list", "--hide", "--unhide", "--show", "--export", "--import", "--uninstall", "--refresh-launchers",
            "-h", "--help")


def wants_cli(argv: List[str]) -> bool:
    return any(a.split("=", 1)[0] in COMMANDS for a in argv[1:])


def _parser():
    p = argparse.ArgumentParser(
        prog="app-entries",
        description="%s %s: show, hide and restore apps in your launcher menus. "
                    "Run without options to open the window." % (APP_NAME, VERSION))
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true",
                   help="list apps: ID, state and name. Add --hidden or --shown to filter.")
    g.add_argument("--hide", nargs="+", metavar="APP", help="hide apps, by ID (firefox or firefox.desktop) or name")
    g.add_argument("--unhide", "--show", nargs="+", metavar="APP", dest="unhide", help="show hidden apps again")
    g.add_argument("--export", metavar="FILE", help="save your hidden apps, edits and launchers to FILE")
    g.add_argument("--import", metavar="FILE", dest="import_", help="apply an export file; shows what changes first")
    g.add_argument("--uninstall", metavar="APP",
                   help="uninstall an app (Flatpak, Snap, AppImage, Steam, Distrobox or a package); shows "
                        "everything that goes and the command first")
    g.add_argument("--refresh-launchers", action="store_true",
                   help="ask the desktop to reload its app list (for launchers that don't notice changes)")
    p.add_argument("--hidden", action="store_true", help="with --list: only hidden apps")
    p.add_argument("--shown", action="store_true", help="with --list: only apps in menus")
    p.add_argument("--all-files", action="store_true",
                   help="with --export: also include files in your folder that App Entries didn't make")
    p.add_argument("--with-data", action="store_true",
                   help="with --uninstall: also move its data folders to the Trash")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask before changing files")
    return p


def _confirm(question: str, yes: bool) -> bool:
    if yes:
        return True
    if not sys.stdin.isatty():
        print("%s Run again with --yes to go ahead." % question, file=sys.stderr)
        return False
    try:
        return input("%s [y/N] " % question).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def find(apps: List[de.App], query: str) -> List[de.App]:
    """Apps matching an ID (with or without .desktop) or an exact name."""
    q = query.strip()
    did = q if q.endswith(".desktop") else q + ".desktop"
    exact = [a for a in apps if a.id == did]
    if exact:
        return exact
    low = q.casefold()
    by_id = [a for a in apps if a.id[:-len(".desktop")].casefold().split(".")[-1] == low]
    by_name = [a for a in apps if a.name.casefold() == low]
    return by_id or by_name


def _state(app: de.App) -> str:
    if not app.hidden:
        return "shown"
    if app.base_hidden and not app.has_override:
        return "hidden-by-package"
    return "hidden"


def _list(apps, args):
    rows = []
    for a in apps:
        st = _state(a)
        if (args.hidden and st == "shown") or (args.shown and st != "shown"):
            continue
        rows.append((a.id, st, a.name))
    width = max((len(r[0]) for r in rows), default=0)
    for did, st, name in rows:
        print("%-*s  %-17s  %s" % (width, did, st, name))
    return 0


def _set_hidden(apps, queries, hidden: bool, yes: bool):
    changes, failed = [], False
    for q in queries:
        found = find(apps, q)
        if not found:
            print("No app matches %r. Try --list to see IDs." % q, file=sys.stderr)
            failed = True
            continue
        if len(found) > 1:
            print("%r matches more than one app: %s. Use the ID." % (q, ", ".join(a.id for a in found)),
                  file=sys.stderr)
            failed = True
            continue
        app = found[0]
        if app.id.startswith("io.github.HypestHyper.AppEntries") and hidden:
            print("App Entries won't hide itself.", file=sys.stderr)
            failed = True
            continue
        try:
            change = plan_set_hidden(app, hidden)
        except NeedsConfirmation as e:
            if not _confirm("%s is hidden by a file App Entries didn't make (%s). Delete that file?"
                            % (app.name, e.path), yes):
                failed = True
                continue
            change = plan_set_hidden(app, hidden, allow_delete=True)
        except OverrideError as e:
            print("%s: %s" % (app.name, e.reason), file=sys.stderr)
            failed = True
            continue
        if change is None:
            print("%s is already %s." % (app.name, "hidden" if hidden else "shown"))
        else:
            changes.append(change)
    if changes:
        apply_all(changes)
        names = ", ".join(c.app_name for c in changes)
        history.record(("Hid %s" if hidden else "Showed %s") % names + " (command line)", changes)
        for c in changes:
            print("%s %s  (%s)" % ("Hid" if hidden else "Showed", c.app_name, c.path))
    return 1 if failed else 0


def _export(apps, args):
    items, others = profile.export(args.export, apps, args.all_files)
    print("Saved %d item(s) to %s." % (len(items), args.export))
    if others:
        print("%d file(s) in your folder weren't made by App Entries and were left out; "
              "add --all-files to include them." % others)
    return 0


def _import(apps, args):
    doc = profile.read(args.import_)
    plan = profile.plan_import(doc, apps)
    for line in plan.adds:
        print("  " + line)
    icons = sum(1 for c in plan.changes if not c.app_id)
    if icons:
        print("  Add %d icon file(s)" % icons)
    for name, why in plan.skipped:
        print("  Skip %s: %s" % (name, why))
    if plan.unchanged:
        print("  %d item(s) already match." % plan.unchanged)
    if not plan.changes:
        print("Nothing to change.")
        return 0
    if not _confirm("Make these %d change(s)?" % len(plan.changes), args.yes):
        return 1
    apply_all(plan.changes)
    history.record("Imported %d change(s) from %s (command line)" % (len(plan.changes), os.path.basename(args.import_)),
                   plan.changes)
    print("Done.")
    return 0


def _uninstall(apps, args):
    import subprocess
    from . import health, trash, uninstall
    from .terminal import shown
    health.check(apps, dict(os.environ))
    found = find(apps, args.uninstall)
    if len(found) != 1:
        print("No app matches %r. Try --list to see IDs." % args.uninstall if not found else
              "%r matches more than one app: %s. Use the ID." % (args.uninstall, ", ".join(a.id for a in found)),
              file=sys.stderr)
        return 1
    app = found[0]
    try:
        p = uninstall.plan(app, apps)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    if p.blocked:
        print(p.blocked, file=sys.stderr)
        return 1
    opts = p.defaults() + (["data"] if args.with_data and "data" in p.folders else [])
    p.update(opts)
    print("%s  (%s%s)" % (app.name, p.kind_label, ", " + p.target if p.target else ""))
    for line in p.removes:
        print("  remove: " + line.text)
    for f in uninstall.to_trash(p, opts):
        print("  to the Trash: " + f)
    if p.goes_too:
        print("  These apps go too: " + ", ".join(p.goes_too))
    if p.preview is not None and p.preview.dependents and p.preview.dependents_go:
        print("  Removed with it, because they need it: " + ", ".join(p.preview.dependents))
    if p.stop_working:
        print("  These stay in your menus but stop working: " + ", ".join(p.stop_working))
    for n in p.notes:
        print("  " + n)
    if p.stops:
        print(p.stops, file=sys.stderr)
        return 1
    cmds = p.commands(opts)
    if cmds:
        print("Runs:\n  " + shown(cmds).replace("\n", "\n  "))
    if not _confirm("Uninstall %s?" % app.name, args.yes):
        return 1
    for argv in cmds:
        if argv[0].startswith("#"):
            print(" ".join(argv))
            continue
        try:
            if p.opens_steam:
                subprocess.Popen(argv, start_new_session=True)
                print("Steam asks you to confirm. Run this again once Steam has removed it, to tidy up.")
                return 0
            code = subprocess.call(argv)
        except OSError as e:
            print("Couldn't run %s: %s" % (argv[0], e.strerror or e), file=sys.stderr)
            return 1
        if code != 0:
            print("It stopped with exit code %d. Nothing else was changed." % code, file=sys.stderr)
            return code
    if not p.gone():
        print("%s is still installed. Nothing else was changed." % app.name, file=sys.stderr)
        return 1
    changes = apply_all(uninstall.file_changes(p, apps))
    trashed = []
    for f in uninstall.to_trash(p, opts):
        try:
            trashed.append(trash.move(f))
        except trash.TrashError as e:
            print(str(e), file=sys.stderr)
    history.record("Uninstalled %s (command line)" % app.name, changes, trashed, reinstall=p.reinstall(opts),
                   reinstall_steam=p.kind == "steam")
    print("Uninstalled %s. It's in History, where its files can be put back and it can be reinstalled." % app.name)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args((argv or sys.argv)[1:])
    try:
        if args.refresh_launchers:
            for line in launcher_refresh.refresh():
                print(line)
            return 0
        apps = de.scan(dict(os.environ))
        if args.list:
            return _list(apps, args)
        if args.hide:
            return _set_hidden(apps, args.hide, True, args.yes)
        if args.unhide:
            return _set_hidden(apps, args.unhide, False, args.yes)
        if args.export:
            return _export(apps, args)
        if args.import_:
            return _import(apps, args)
        if args.uninstall:
            return _uninstall(apps, args)
    except (OverrideError, profile.ProfileError) as e:
        print(str(e), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 2
