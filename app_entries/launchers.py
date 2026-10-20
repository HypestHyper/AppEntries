"""Launchers you make yourself: build the .desktop entry for a script or
program, its icon, and check hand-written entries. Pure Python, no GTK.

A launcher made here is a file app-entries-<name>.desktop in the user's
applications folder. It records the choices it was made from (X-AppEntries-*
keys), so it can be opened in the same form again later.
"""
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field, fields
from typing import List, Optional, Tuple

from . import desktop_entries as de
from . import symbols
from .editing import escape, join_list, split_list
from .overrides import Change, read_text

CREATED_KEY = "X-AppEntries-Created"
PREFIX = "app-entries-"
# Characters the spec says must be quoted in an Exec argument.
_RESERVED = set(" \t\n\"'\\><~|&;$*?#()`")
_ICON_PREFIX = "X-AppEntries-Icon-"


def _icon_key(field_name: str) -> str:
    """name -> X-AppEntries-Icon-Name, border_width -> X-AppEntries-Icon-BorderWidth."""
    return _ICON_PREFIX + "".join(p.capitalize() for p in field_name.split("_"))


def icon_lines(ic: symbols.IconChoice) -> List[str]:
    out = []
    for f in fields(ic):
        v = getattr(ic, f.name)
        out.append("%s=%s" % (_icon_key(f.name), ("true" if v else "false") if isinstance(v, bool) else escape(str(v))))
    return out


def icon_from(d) -> symbols.IconChoice:
    ic = symbols.IconChoice()
    for f in fields(ic):
        raw = d.get(_icon_key(f.name))
        if raw is None:
            continue
        default = getattr(ic, f.name)
        if isinstance(default, bool):
            setattr(ic, f.name, de.is_true(raw))
        elif isinstance(default, int):
            try:
                setattr(ic, f.name, int(raw))
            except ValueError:
                pass
        else:
            setattr(ic, f.name, de.unescape(raw))
    return ic


@dataclass
class Spec:
    name: str = ""
    comment: str = ""
    program: str = ""            # the script or program file, or a command name
    args: str = ""               # arguments, written as in a shell
    workdir: str = ""            # working folder, empty for the user's home
    terminal: bool = False
    keep_open: bool = False      # with terminal: wait for Enter when it finishes
    accepts_files: bool = False  # pass files opened with it as arguments (%F)
    categories: List[str] = field(default_factory=lambda: ["Utility"])
    keywords: List[str] = field(default_factory=list)
    icon_kind: str = "symbol"    # symbol, theme or file
    icon: symbols.IconChoice = field(default_factory=symbols.IconChoice)
    icon_value: str = ""         # theme icon name or image path
    hidden: bool = False         # kept out of launcher menus
    web_url: str = ""            # a web app: the site it opens in its own window
    web_browser: str = ""        # the browser's ID in webapps.BROWSERS
    web_profile: bool = False    # its own sign-ins and data, apart from the browser's
    wm_class: str = ""           # StartupWMClass: lets docks match the window to the launcher


def split_program(program: str, args: str = "") -> Tuple[str, str]:
    """The program field may hold a whole command (`htop --help`). An existing
    file path is taken as it is, even with spaces; otherwise the first word is
    the program and the rest go in front of the arguments."""
    p = program.strip()
    if not p or os.path.exists(os.path.expanduser(p)):
        return p, args
    try:
        words = shlex.split(p)
    except ValueError:
        return p, args
    if len(words) < 2:
        return (words[0] if words else p), args
    rest = shlex.join(words[1:])
    return words[0], (rest + " " + args).strip() if args.strip() else rest


# ---------------------------------------------------------------------------
# Exec


def quote_arg(arg: str) -> str:
    """Quote one Exec argument as the Desktop Entry spec requires."""
    arg = arg.replace("%", "%%")
    if arg and not (set(arg) & _RESERVED):
        return arg
    inner = re.sub(r'(["`$\\])', r"\\\1", arg)
    return '"%s"' % inner


def build_exec(spec: Spec) -> str:
    """The Exec value (before string escaping) for a spec."""
    program, args = split_program(spec.program, spec.args)
    try:
        extra = shlex.split(args)
    except ValueError as e:
        raise ValueError("The arguments have an unclosed quote: %s" % e)
    argv = [os.path.expanduser(program)] + extra
    if spec.terminal and spec.keep_open:
        script = (shlex.join(argv) + (' "$@"' if spec.accepts_files else "") +
                  '; status=$?; printf "\\n[Finished with exit code %s. Press Enter to close.]" "$status"; read _')
        argv = ["sh", "-c", script, "sh"]
    line = " ".join(quote_arg(a) for a in argv)
    if spec.accepts_files:
        line += " %F"
    return line


def parse_exec(line: str) -> List[str]:
    """Split an Exec value into arguments, undoing quote_arg (field codes are
    kept as they are). For tests and the raw-entry check."""
    out, cur, i, quoted, started = [], [], 0, False, False
    while i < len(line):
        c = line[i]
        if quoted:
            if c == "\\" and i + 1 < len(line) and line[i + 1] in '"`$\\':
                cur.append(line[i + 1])
                i += 2
                continue
            if c == '"':
                quoted = False
            else:
                cur.append(c)
        elif c == '"':
            quoted, started = True, True
        elif c in " \t":
            if cur or started:
                out.append("".join(cur))
            cur, started = [], False
        else:
            cur.append(c)
        i += 1
    if quoted:
        raise ValueError("An opening quote in the command has no closing quote.")
    if cur or started:
        out.append("".join(cur))
    return [a.replace("%%", "%") for a in out]


# ---------------------------------------------------------------------------
# Files


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return s[:40] or "launcher"


def new_id(name: str, env=None, taken=()) -> str:
    folder = de.user_apps_dir(env)
    base = PREFIX + slug(name)
    did, n = base + ".desktop", 2
    while did in taken or os.path.exists(os.path.join(folder, did)):
        did, n = "%s-%d.desktop" % (base, n), n + 1
    return did


def icon_path(did: str, env=None) -> str:
    return os.path.join(de.user_data_dir(env), "icons", "hicolor", "scalable", "apps",
                        did[:-len(".desktop")] + ".svg")


def problems(spec: Spec) -> List[str]:
    out = []
    if not spec.name.strip():
        out.append("Give the launcher a name.")
    if not spec.program.strip():
        out.append("Choose the script or program it runs.")
    try:
        shlex.split(spec.args)
    except ValueError:
        out.append("The arguments have an unclosed quote.")
    if spec.workdir.strip() and not os.path.isdir(os.path.expanduser(spec.workdir.strip())):
        out.append("The working folder doesn't exist.")
    if spec.icon_kind == "symbol":
        if spec.icon.source == "file":
            if not os.path.isfile(spec.icon.path):
                out.append("The icon file is missing from your icon library.")
        elif spec.icon.name not in symbols.icons():
            out.append("Pick an icon.")
    return out


def program_status(program: str, env=None) -> str:
    """ok, missing, not-executable or command (found on PATH or in the usual
    program folders)."""
    p = os.path.expanduser(split_program(program)[0])
    if not p:
        return "missing"
    if os.sep in p:
        if not os.path.isfile(p):
            return "missing"
        return "ok" if os.access(p, os.X_OK) else "not-executable"
    from .health import search_dirs
    env = os.environ if env is None else env
    return "command" if shutil.which(p, path=":".join(search_dirs(env))) else "missing"


def build_entry(spec: Spec, did: str, env=None) -> str:
    """The .desktop text for a spec."""
    lines = [
        "[Desktop Entry]",
        "# Launcher made with App Entries. Open it there to change it.",
        "Type=Application",
        "Version=1.5",
        "Name=" + escape(spec.name.strip()),
    ]
    if spec.comment.strip():
        lines.append("Comment=" + escape(spec.comment.strip()))
    lines.append("Exec=" + escape(build_exec(spec)))
    if spec.workdir.strip():
        lines.append("Path=" + escape(os.path.expanduser(spec.workdir.strip())))
    if spec.icon_kind == "symbol":
        lines.append("Icon=" + escape(icon_path(did, env)))
    elif spec.icon_value.strip():
        lines.append("Icon=" + escape(spec.icon_value.strip()))
    lines.append("Terminal=" + ("true" if spec.terminal else "false"))
    if spec.wm_class.strip():
        lines.append("StartupWMClass=" + escape(spec.wm_class.strip()))
    if spec.hidden:
        lines.append("NoDisplay=true")
    cats = join_list(spec.categories)
    if cats:
        lines.append("Categories=" + cats)
    kw = join_list(spec.keywords)
    if kw:
        lines.append("Keywords=" + kw)
    lines += [
        CREATED_KEY + "=true",
        "X-AppEntries-Program=" + escape(spec.program.strip()),
        "X-AppEntries-Args=" + escape(spec.args),
        "X-AppEntries-KeepOpen=" + ("true" if spec.keep_open else "false"),
        "X-AppEntries-AcceptsFiles=" + ("true" if spec.accepts_files else "false"),
        "X-AppEntries-Icon-Kind=" + spec.icon_kind,
    ]
    if spec.web_url:
        lines += [
            "X-AppEntries-WebApp=" + escape(spec.web_url),
            "X-AppEntries-WebApp-Browser=" + escape(spec.web_browser),
            "X-AppEntries-WebApp-Profile=" + ("true" if spec.web_profile else "false"),
        ]
    if spec.icon_kind == "symbol":
        ic = spec.icon
        lines += icon_lines(ic)
    return "\n".join(lines) + "\n"


def read_spec(text: str) -> Optional[Spec]:
    """The spec a launcher was made from, or None if it was changed by hand
    so the form can't show it faithfully."""
    d = de.DesktopFile(text).group_dict()
    if not de.is_true(d.get(CREATED_KEY)) or "X-AppEntries-Program" not in d:
        return None
    icon = icon_from(d)
    kind = d.get("X-AppEntries-Icon-Kind", "symbol")
    spec = Spec(
        name=de.unescape(d.get("Name", "")),
        comment=de.unescape(d.get("Comment", "")),
        program=de.unescape(d.get("X-AppEntries-Program", "")),
        args=de.unescape(d.get("X-AppEntries-Args", "")),
        workdir=de.unescape(d.get("Path", "")),
        terminal=de.is_true(d.get("Terminal")),
        keep_open=de.is_true(d.get("X-AppEntries-KeepOpen")),
        accepts_files=de.is_true(d.get("X-AppEntries-AcceptsFiles")),
        categories=split_list(d.get("Categories", "")),
        keywords=split_list(d.get("Keywords", "")),
        icon_kind=kind,
        icon=icon,
        icon_value="" if kind == "symbol" else de.unescape(d.get("Icon", "")),
        hidden=de.is_true(d.get("NoDisplay")) or de.is_true(d.get("Hidden")),
        web_url=de.unescape(d.get("X-AppEntries-WebApp", "")),
        web_browser=de.unescape(d.get("X-AppEntries-WebApp-Browser", "")),
        web_profile=de.is_true(d.get("X-AppEntries-WebApp-Profile")),
        wm_class=de.unescape(d.get("StartupWMClass", "")),
    )
    try:
        if build_exec(spec) != de.unescape(d.get("Exec", "")):
            return None
    except ValueError:
        return None
    return spec


def plan_save(spec: Spec, did: Optional[str] = None, env=None) -> Tuple[str, List[Change]]:
    """Changes that write the launcher (and its icon). `did` is the existing
    ID when editing, None for a new launcher. Returns (id, changes)."""
    errs = problems(spec)
    if errs:
        raise ValueError(" ".join(errs))
    did = did or new_id(spec.name, env)
    folder = de.user_apps_dir(env)
    path = os.path.join(folder, did)
    changes = []
    ipath = icon_path(did, env)
    old_icon = read_text(ipath)
    if spec.icon_kind == "symbol":
        svg = symbols.render(spec.icon, title=spec.name.strip())
        if svg != old_icon:
            changes.append(Change(did, spec.name, ipath, old_icon, svg, False))
    elif old_icon is not None and symbols_icon(old_icon):
        changes.append(Change(did, spec.name, ipath, old_icon, None, False))
    before = read_text(path)
    after = build_entry(spec, did, env)
    if after != before:
        changes.append(Change(did, spec.name, path, before, after, False))
    return did, changes


def plan_raw(text: str, did: str, name: str, env=None) -> Change:
    """Save hand-written entry text (after check_raw found no errors)."""
    path = os.path.join(de.user_apps_dir(env), did)
    if not text.endswith("\n"):
        text += "\n"
    return Change(did, name, path, read_text(path), text, False)


def symbols_icon(svg_text: str) -> bool:
    return "made with App Entries" in svg_text


def plan_delete(app: de.App, env=None) -> List[Change]:
    """Delete a launcher made with App Entries, and its icon."""
    changes = []
    ipath = icon_path(app.id, env)
    icon = read_text(ipath)
    if icon is not None and symbols_icon(icon):
        changes.append(Change(app.id, app.name, ipath, icon, None, False))
    before = read_text(app.override_path)
    if before is not None:
        changes.append(Change(app.id, app.name, app.override_path, before, None, False))
    return changes


def styled_icon(app: de.App) -> Optional[Tuple[str, str, symbols.IconChoice]]:
    """(icon file, its text, the choice it was drawn from) when the app's
    icon was made with App Entries, else None."""
    path = app.icon
    if not (path and os.path.isabs(path) and path.endswith(".svg")):
        return None
    try:
        text = read_text(path)
    except OSError:
        return None
    if text is None or not symbols_icon(text):
        return None
    choice = symbols.choice_from_svg(text)
    if choice is None and app.created and app.override_path:
        # Made before icons carried their settings: the launcher has them.
        spec = read_spec(read_text(app.override_path) or "")
        if spec is not None and spec.icon_kind == "symbol":
            choice = spec.icon
    return (path, text, choice) if choice is not None else None


def plan_restyle(apps: List[de.App], style: symbols.IconChoice) -> Tuple[List[Change], List[de.App]]:
    """Give every app's styled icon `style`'s look, keeping its symbol.
    Returns the changes and the apps skipped because their icon wasn't made
    with App Entries."""
    changes, skipped = [], []
    for app in apps:
        found = styled_icon(app)
        if found is None:
            skipped.append(app)
            continue
        path, before, choice = found
        new = symbols.restyle(choice, style)
        svg = symbols.render(new, title=app.name)
        if svg != before:
            changes.append(Change(app.id, app.name, path, before, svg, app.hidden))
        if app.created and app.override_path:
            text = read_text(app.override_path)
            if text is None:
                continue
            df = de.DesktopFile(text)
            if de.is_true(df.group_dict().get(CREATED_KEY)):
                for line in icon_lines(new):
                    k, v = line.split("=", 1)
                    df.set(k, v)
                if df.text() != text:
                    changes.append(Change(app.id, app.name, app.override_path, text, df.text(), app.hidden))
    return changes, skipped


def duplicate(text: str) -> Optional[Spec]:
    spec = read_spec(text)
    if spec is not None:
        spec.name = "%s (copy)" % spec.name
    return spec


def make_executable(path: str) -> None:
    p = os.path.expanduser(split_program(path)[0])
    mode = os.stat(p).st_mode
    os.chmod(p, mode | ((mode & 0o444) >> 2))  # add x wherever there's r


# ---------------------------------------------------------------------------
# Checking hand-written entries


def check_raw(text: str) -> Tuple[List[str], List[str]]:
    """(errors, warnings) for hand-written entry text. Errors stop saving."""
    errors, warnings = [], []
    df = de.DesktopFile(text)
    if not df.has_group(de.GROUP):
        return ["The first section must be [Desktop Entry]."], []
    d = df.group_dict()
    if d.get("Type") != "Application":
        errors.append("Type must be Application.")
    if not d.get("Name", "").strip():
        errors.append("Name is missing.")
    exec_line = de.unescape(d.get("Exec", ""))
    if not exec_line.strip():
        errors.append("Exec is missing: that's the command it runs.")
    else:
        try:
            parse_exec(exec_line)
        except ValueError as e:
            errors.append(str(e))
    tool = shutil.which("desktop-file-validate")
    if tool:
        fd, tmp = tempfile.mkstemp(suffix=".desktop")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            out = subprocess.run([tool, tmp], capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        finally:
            os.unlink(tmp)
        for line in out.splitlines():
            msg = line.split(": ", 1)[-1].strip()
            if msg.startswith("error:"):
                errors.append("desktop-file-validate: " + msg[len("error:"):].strip())
            elif msg.startswith("warning:"):
                warnings.append("desktop-file-validate: " + msg[len("warning:"):].strip())
    return list(dict.fromkeys(errors)), list(dict.fromkeys(warnings))
