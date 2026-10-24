"""The system's package manager: which package owns a file, what removing
it would do, and the command that removes it. Pure Python, no GTK.

Nothing here removes anything or asks for a password. Each manager is
asked, without root, what it would do (its own dry run where it has one,
otherwise its list of packages that need this one), and the command is
built for the user to run in their own terminal, where the manager asks
for the password and shows everything itself.

Covered: pacman (Arch, Manjaro, EndeavourOS, CachyOS), apt (Debian,
Ubuntu, Mint, Pop!_OS), dnf (Fedora, RHEL and its rebuilds), zypper
(openSUSE), rpm-ostree (Silverblue, Kinoite, Bazzite), xbps (Void), apk
(Alpine, postmarketOS), eopkg (Solus), Portage (Gentoo) and Nix.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

# run(argv) -> (exit code, stdout and stderr together), or None if it couldn't run.
Run = Callable[[List[str]], Optional[Tuple[int, str]]]


def run(argv: List[str], timeout: int = 60) -> Optional[Tuple[int, str]]:
    try:
        out = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             text=True, timeout=timeout, env=dict(os.environ, LC_ALL="C", LANG="C"))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return out.returncode, out.stdout


def _ok(r: Optional[Tuple[int, str]]) -> str:
    """The output when the command worked, "" otherwise."""
    return r[1] if r is not None and r[0] == 0 else ""


@dataclass
class Option:
    """A choice the user can make before uninstalling."""
    key: str
    title: str
    explanation: str
    warning: str = ""              # shown in red while it's on
    default: bool = False
    excludes: Tuple[str, ...] = ()  # options turned off when this one is turned on


@dataclass
class Preview:
    """What the manager would do, asked before anything changes."""
    removed: List[str] = field(default_factory=list)      # every package that would go, the targets first
    dependents: List[str] = field(default_factory=list)   # installed packages that need the targets
    dependents_go: bool = False    # they're removed too (otherwise the manager stops, or they break)
    optional_for: List[str] = field(default_factory=list)  # packages that work without it, with less
    unneeded: List[str] = field(default_factory=list)     # packages removed because nothing needs them any more
    stops: str = ""                # why the manager would refuse, in plain words, or ""
    group_packages: List[str] = field(default_factory=list)  # metapackages that go too (apt)
    exact: bool = False            # from the manager's own dry run
    output: str = ""               # what it printed


@dataclass
class Info:
    name: str
    version: str = ""
    size: int = 0                  # bytes installed, 0 if unknown
    foreign: bool = False          # not from the distribution's repositories (AUR and the like)


# Packages that are never uninstalled from here, and why.
SYSTEM_NEEDS = {
    "base", "filesystem", "glibc", "musl", "libc6", "libc-bin", "glibc-common", "systemd", "systemd-libs",
    "systemd-sysvcompat", "udev", "eudev", "openrc", "runit", "s6", "dinit", "sudo", "doas", "opendoas",
    "bash", "dash", "coreutils", "util-linux", "shadow", "pam", "linux-pam", "libpam-runtime", "base-files",
    "base-passwd", "init", "init-system-helpers", "dbus", "dbus-broker", "dbus-daemon", "polkit", "elogind",
    "linux", "linux-lts", "linux-zen", "linux-hardened", "linux-cachyos", "linux-firmware", "kernel",
    "kernel-core", "kernel-default", "linux-image-generic", "linux-generic", "grub", "grub2", "grub-common",
    "grub-pc", "grub-efi-amd64", "systemd-boot", "efibootmgr", "dracut", "mkinitcpio", "initramfs-tools",
    "pacman", "apt", "dpkg", "rpm", "dnf", "dnf5", "libdnf", "zypper", "libzypp", "rpm-ostree", "xbps",
    "apk-tools", "alpine-base", "eopkg", "portage", "nix", "networkmanager", "network-manager",
    "NetworkManager", "mesa", "libgl1-mesa-dri", "mesa-dri-drivers", "xorg-server", "xserver-xorg-core",
    "xwayland", "xorg-x11-server-Xwayland", "pipewire", "wireplumber", "pulseaudio",
}
DESKTOP_NEEDS = {
    "gnome-shell", "mutter", "gnome-session", "gnome-session-bin", "gdm", "gdm3", "plasma-workspace",
    "plasma-desktop", "kwin", "kwin-wayland", "kwin-x11", "sddm", "xfce4-session", "xfwm4", "xfdesktop",
    "xfce4-panel", "lightdm", "cinnamon", "muffin", "mate-session-manager", "marco", "budgie-desktop",
    "lxqt-session", "lxsession", "hyprland", "sway", "niri", "river", "wayfire", "labwc", "greetd",
    "cosmic-session", "cosmic-comp", "xdg-desktop-portal", "xdg-desktop-portal-gtk", "gnome-control-center",
    "systemsettings", "ubuntu-desktop", "ubuntu-desktop-minimal", "kubuntu-desktop", "xubuntu-desktop",
    "task-gnome-desktop", "task-kde-desktop", "task-xfce-desktop", "task-desktop", "gnome", "plasma",
    "plasma-meta", "kde-plasma-desktop", "xfce4", "pop-desktop", "elementary-desktop",
}
# What App Entries itself runs on.
SELF_NEEDS = {
    "python", "python3", "python3-minimal", "python3.12", "python3.13", "python3.14", "python3-gi",
    "python-gobject", "python3-gobject", "py3-gobject3", "python3-gobject-base", "gtk4", "libgtk-4-1",
    "gtk4-tools", "gir1.2-gtk-4.0", "typelib-1_0-Gtk-4_0", "libgtk-4-0", "glib2", "libglib2.0-0",
    "libglib2.0-0t64", "gobject-introspection", "gobject-introspection-runtime", "libgirepository-1.0-1",
    "pygobject3", "app-entries",
}


def needed_by_system(pkg: str) -> str:
    """Why a package must stay, in plain words, or "" if it can go."""
    base = pkg.split("/")[-1]   # Gentoo's category/name
    if base in SELF_NEEDS:
        return "App Entries itself needs it"
    if base in SYSTEM_NEEDS or base.startswith(("linux-image-", "kernel-")):
        return "the system needs it to start or run"
    if base in DESKTOP_NEEDS:
        return "your desktop needs it"
    return ""


def privilege(which: Callable = shutil.which) -> List[str]:
    """How to run a command as root in a terminal: sudo, doas or run0."""
    for tool in ("sudo", "doas", "run0"):
        if which(tool):
            return [tool]
    return []


def as_root(argv: List[str], which: Callable = shutil.which) -> List[str]:
    p = privilege(which)
    if p:
        return p + argv
    return ["su", "-c", shlex.join(argv)]


def _names_after(text: str, pattern: str) -> List[str]:
    return list(dict.fromkeys(re.findall(pattern, text, flags=re.M)))


def _human_size(text: str) -> int:
    """'112.34 MiB', '1.2 GB', '340 KiB' or '23MB' as bytes, 0 if unreadable."""
    m = re.search(r"([\d.,]+)\s*([KMGT]?)(i?)B", text or "", flags=re.I)
    if not m:
        return 0
    try:
        n = float(m.group(1).replace(",", "."))
    except ValueError:
        return 0
    power = "KMGT".find(m.group(2).upper()) + 1 if m.group(2) else 0
    return int(n * ((1024 if m.group(3) else 1000) ** power))


class Manager:
    """One package manager. Subclasses fill in the queries they can answer."""
    name = ""          # pacman, apt, …
    label = ""         # shown to the user
    tools: Tuple[str, ...] = ()   # one of these must be installed
    needs_root = True
    options: List[Option] = []
    asks_first = True  # the remove command shows what it does and asks before going ahead

    def __init__(self, run: Run = run, which: Callable = shutil.which):
        self.run = run
        self.which = which

    def owner(self, path: str) -> str:
        return ""

    def info(self, pkg: str) -> Info:
        return Info(pkg)

    def files(self, pkg: str) -> List[str]:
        return []

    def preview(self, pkgs: Sequence[str], opts: Sequence[str]) -> Preview:
        return Preview(removed=list(pkgs))

    def commands(self, pkgs: Sequence[str], opts: Sequence[str]) -> List[List[str]]:
        """The commands that remove them, as run in the terminal (with sudo)."""
        return []

    def reinstall(self, pkgs: Sequence[str], info: Optional[Dict[str, Info]] = None) -> List[List[str]]:
        return []

    def blocked(self, pkg: str) -> str:
        """Why this package can't be uninstalled here at all, or ""."""
        return ""

    def protected(self) -> List[str]:
        """Packages this manager itself refuses to remove."""
        return []

    def _root(self, argv: List[str]) -> List[str]:
        return as_root(argv, self.which) if self.needs_root else argv


# ---------------------------------------------------------------------------
# pacman


class Pacman(Manager):
    name, label, tools = "pacman", "pacman", ("pacman",)
    options = [
        Option("deps", "Remove packages only it needed",
               "Packages that were installed for it and that nothing else uses go too.", default=True),
        Option("nosave", "Also remove its config backups",
               "pacman normally keeps a .pacsave copy of system config files you changed. This deletes them "
               "too."),
        Option("cascade", "Also remove packages that need it",
               "Removes everything that depends on it as well, so pacman doesn't stop.",
               warning="Also removes: {dependents}.", excludes=("nodeps",)),
        Option("nodeps", "Skip dependency checks",
               "Removes it even though other packages need it.",
               warning="The packages that need it can stop working: {dependents}.", excludes=("cascade",)),
    ]

    def owner(self, path):
        out = _ok(self.run(["pacman", "-Qoq", path]))
        return out.split()[0] if out.strip() else ""

    def _qi(self, pkg) -> Dict[str, str]:
        out = _ok(self.run(["pacman", "-Qi", pkg]))
        fields, key = {}, None
        for line in out.splitlines():
            m = re.match(r"^(\S[^:]*?)\s*:\s?(.*)$", line)
            if m:
                key = m.group(1).strip()
                fields[key] = m.group(2).strip()
            elif key and line.startswith(" "):
                fields[key] += " " + line.strip()
        return fields

    def info(self, pkg):
        f = self._qi(pkg)
        foreign = _ok(self.run(["pacman", "-Qqm", pkg])).strip() == pkg
        return Info(pkg, f.get("Version", ""), _human_size(f.get("Installed Size", "")), foreign)

    def files(self, pkg):
        return [l for l in _ok(self.run(["pacman", "-Qlq", pkg])).splitlines() if l and not l.endswith("/")]

    def _flags(self, opts) -> str:
        flags = "-R"
        if "nosave" in opts:
            flags += "n"
        if "deps" in opts:
            flags += "s"
        if "cascade" in opts:
            flags += "c"
        if "nodeps" in opts:
            flags += "dd"
        return flags

    def preview(self, pkgs, opts):
        p = Preview()
        needed, optional = [], []
        for pkg in pkgs:
            f = self._qi(pkg)
            needed += [x for x in f.get("Required By", "").split() if x != "None" and x not in pkgs]
            optional += [x for x in f.get("Optional For", "").split() if x != "None" and x not in pkgs]
        p.dependents = list(dict.fromkeys(needed))
        p.optional_for = list(dict.fromkeys(optional))
        r = self.run(["pacman", self._flags(opts) + "p", "--print-format", "%n"] + list(pkgs))
        if r is not None:
            p.output = r[1]
            if r[0] == 0:
                names = [l.strip() for l in r[1].splitlines() if re.fullmatch(r"[\w@.+-]+", l.strip() or "-")]
                p.removed = list(pkgs) + [n for n in names if n not in pkgs]
                p.exact = True
            else:
                broken = _names_after(r[1], r"breaks dependency '[^']+' required by (\S+)")
                p.dependents = list(dict.fromkeys(p.dependents + broken))
        if not p.removed:
            p.removed = list(pkgs)
        if "cascade" in opts:
            p.dependents_go = True
        p.unneeded = [n for n in p.removed if n not in pkgs and n not in p.dependents]
        if p.dependents and not ({"cascade", "nodeps"} & set(opts)):
            p.stops = ("pacman would stop, because {deps} need{s} it. Remove {them} first, or turn on "
                       "“Also remove packages that need it”.").format(
                deps=", ".join(p.dependents), s="s" if len(p.dependents) == 1 else "",
                them="that" if len(p.dependents) == 1 else "those")
        return p

    def commands(self, pkgs, opts):
        return [self._root(["pacman", self._flags(opts)] + list(pkgs))]

    def reinstall(self, pkgs, info=None):
        info = info or {}
        repo = [p for p in pkgs if not (info.get(p) and info[p].foreign)]
        foreign = [p for p in pkgs if p not in repo]
        out = [self._root(["pacman", "-S", "--needed"] + repo)] if repo else []
        if foreign:
            helper = next((h for h in ("paru", "yay", "pikaur", "trizen") if self.which(h)), "")
            out.append([helper, "-S"] + foreign if helper else ["# from the AUR:"] + foreign)
        return out

    def protected(self):
        try:
            with open("/etc/pacman.conf", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            return []
        out = []
        for m in re.finditer(r"^\s*HoldPkg\s*=\s*(.+)$", text, flags=re.M):
            out += m.group(1).split()
        return out


# ---------------------------------------------------------------------------
# apt / dpkg


class Apt(Manager):
    name, label, tools = "apt", "apt", ("dpkg-query",)
    options = [
        Option("autoremove", "Also remove packages nothing needs any more",
               "Packages installed only for it go too. apt also removes any that were left over from earlier "
               "removals; the list above shows them all while this is on."),
        Option("purge", "Also remove its system-wide settings",
               "Deletes its configuration files in /etc too. Your own settings in your home folder aren't "
               "affected either way."),
        Option("nodeps", "Skip dependency checks",
               "Removes only this package with dpkg, leaving the packages that need it installed.",
               warning="The packages that need it can stop working, and apt will want to fix or remove them "
                       "next time: {dependents}."),
    ]

    def owner(self, path):
        out = _ok(self.run(["dpkg-query", "-S", path]))
        for line in out.splitlines():
            if ": " in line and not line.startswith(("diversion ", "local diversion")):
                return line.split(": ", 1)[0].split(",")[0].strip().split(":")[0]
        return ""

    def _fields(self, pkg) -> List[str]:
        out = _ok(self.run(["dpkg-query", "-W", "-f",
                            "${Version}\t${Installed-Size}\t${Essential}\t${Priority}\t${Section}\n", pkg]))
        parts = out.splitlines()[0].split("\t") if out else []
        return parts + [""] * (5 - len(parts))

    def info(self, pkg):
        version, size, *_rest = self._fields(pkg)
        return Info(pkg, version, int(size) * 1024 if size.isdigit() else 0)

    def files(self, pkg):
        return [l for l in _ok(self.run(["dpkg-query", "-L", pkg])).splitlines() if l.startswith("/")]

    def _simulate(self, pkgs, autoremove, purge):
        argv = ["apt-get", "-s"] + (["--auto-remove"] if autoremove else []) + (["--purge"] if purge else []) + \
            ["remove"] + list(pkgs)
        return self.run(argv)

    def preview(self, pkgs, opts):
        p = Preview()
        r = self._simulate(pkgs, False, "purge" in opts)
        if r is None:
            p.removed = list(pkgs)
            return p
        p.output = r[1]
        plain = _names_after(r[1], r"^(?:Remv|Purg) (\S+)")
        p.dependents = [n.split(":")[0] for n in plain if n.split(":")[0] not in pkgs]
        p.dependents_go = "nodeps" not in opts
        p.removed = list(pkgs) + (p.dependents if p.dependents_go else [])
        if "autoremove" in opts:
            r2 = self._simulate(pkgs, True, "purge" in opts)
            if r2 is not None:
                p.output = r2[1]
                every = [n.split(":")[0] for n in _names_after(r2[1], r"^(?:Remv|Purg) (\S+)")]
                p.unneeded = [n for n in every if n not in p.removed]
                p.removed += p.unneeded
        p.exact = r[0] == 0
        m = re.search(r"essential packages will be removed\.?\s*\n.*?\n((?:\s+\S.*\n)+)", r[1], flags=re.I)
        if m:
            p.stops = "apt would remove packages the system can't run without: %s." % \
                ", ".join(m.group(1).split())
        elif r[0] != 0:
            err = [l[3:] if l.startswith("E: ") else l for l in r[1].splitlines() if l.startswith("E: ")]
            p.stops = "apt says: " + (" ".join(err) or "it can't remove this")
        for d in p.dependents:
            section = self._fields(d)[4]
            if section.endswith("metapackages"):
                p.group_packages.append(d)
        return p

    def commands(self, pkgs, opts):
        if "nodeps" in opts:
            return [self._root(["dpkg", "--remove", "--force-depends"] + list(pkgs))]
        argv = ["apt", "remove"] + (["--purge"] if "purge" in opts else []) + \
            (["--autoremove"] if "autoremove" in opts else []) + list(pkgs)
        return [self._root(argv)]

    def reinstall(self, pkgs, info=None):
        return [self._root(["apt", "install"] + list(pkgs))]

    def blocked(self, pkg):
        _v, _s, essential, priority, _sec = self._fields(pkg)
        if essential == "yes":
            return "Debian marks it as essential to the system"
        if priority == "required":
            return "Debian marks it as required by the system"
        return ""


# ---------------------------------------------------------------------------
# rpm-based: dnf, zypper, rpm-ostree


def _rpm_name(nevra: str) -> str:
    """gimp-2.10.38-1.fc40.x86_64 -> gimp."""
    parts = nevra.rsplit("-", 2)
    return parts[0] if len(parts) == 3 else nevra


class _Rpm(Manager):
    tools = ("rpm",)

    def owner(self, path):
        out = _ok(self.run(["rpm", "-qf", "--qf", "%{NAME}\\n", path]))
        line = out.splitlines()[0].strip() if out.strip() else ""
        return "" if not line or "not owned" in line else line

    def info(self, pkg):
        out = _ok(self.run(["rpm", "-q", "--qf", "%{VERSION}-%{RELEASE}\\t%{SIZE}\\n", pkg]))
        parts = out.splitlines()[0].split("\t") if out.strip() else ["", ""]
        size = parts[1] if len(parts) > 1 else ""
        return Info(pkg, parts[0], int(size) if size.isdigit() else 0)

    def files(self, pkg):
        return [l for l in _ok(self.run(["rpm", "-ql", pkg])).splitlines() if l.startswith("/")]

    def _needed_by(self, pkgs) -> List[str]:
        r = self.run(["rpm", "-e", "--test"] + list(pkgs))
        if r is None:
            return []
        names = [_rpm_name(n) for n in re.findall(r"is needed by \(installed\) (\S+)", r[1])]
        return [n for n in dict.fromkeys(names) if n not in pkgs]

    @staticmethod
    def _table(text: str) -> Dict[str, List[str]]:
        """Package names under each heading of dnf's transaction table,
        by heading: {"removing dependent packages": [...], ...}."""
        sections: Dict[str, List[str]] = {}
        current = None
        for line in text.splitlines():
            if not line.strip():
                current = None
            elif not line.startswith(" ") and line.rstrip().endswith(":"):
                current = line.strip().rstrip(":").lower()
                sections.setdefault(current, [])
            elif current is not None and line.startswith(" "):
                word = line.split()[0]
                if word != "replacing":
                    sections[current].append(word)
            else:
                current = None
        return sections

    def nodeps_command(self, pkgs):
        return [self._root(["rpm", "-e", "--nodeps"] + list(pkgs))]


class Dnf(_Rpm):
    name, label, tools = "dnf", "dnf", ("dnf", "dnf5")
    options = [
        Option("deps", "Remove packages only it needed",
               "Packages that were installed for it and that nothing else uses go too.", default=True),
        Option("nodeps", "Skip dependency checks",
               "Removes only this package with rpm, leaving the packages that need it installed.",
               warning="The packages that need it can stop working: {dependents}."),
    ]

    def _dnf(self):
        return "dnf" if self.which("dnf") else "dnf5"

    def preview(self, pkgs, opts):
        p = Preview()
        p.dependents = self._needed_by(pkgs)
        p.dependents_go = "nodeps" not in opts    # dnf removes what needs it
        p.removed = list(pkgs) + (p.dependents if p.dependents_go else [])
        argv = [self._dnf(), "remove", "--assumeno", "-C"]
        if "deps" not in opts:
            argv.append("--setopt=clean_requirements_on_remove=False")
        r = self.run(argv + list(pkgs))
        if r is not None and "Removing" in r[1]:
            p.output = r[1]
            table = self._table(r[1])
            dependent = table.get("removing dependent packages", [])
            unused = table.get("removing unused dependencies", [])
            p.dependents = list(dict.fromkeys(p.dependents + dependent))
            p.unneeded = [n for n in unused if n not in p.dependents]
            if p.dependents_go:
                p.removed = list(pkgs) + p.dependents + p.unneeded
            p.exact = True
        return p

    def commands(self, pkgs, opts):
        if "nodeps" in opts:
            return self.nodeps_command(pkgs)
        argv = [self._dnf(), "remove"]
        if "deps" not in opts:
            argv.append("--setopt=clean_requirements_on_remove=False")
        return [self._root(argv + list(pkgs))]

    def reinstall(self, pkgs, info=None):
        return [self._root([self._dnf(), "install"] + list(pkgs))]

    def protected(self):
        out = []
        for d in ("/etc/dnf/protected.d", "/usr/share/dnf5/libdnf.conf.d"):
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for n in names:
                if n.endswith(".conf") and d.endswith("protected.d"):
                    try:
                        with open(os.path.join(d, n), encoding="utf-8", errors="replace") as f:
                            out += [l.strip() for l in f if l.strip() and not l.startswith("#")]
                    except OSError:
                        pass
        return out


class Zypper(_Rpm):
    name, label, tools = "zypper", "zypper", ("zypper",)
    options = [
        Option("deps", "Remove packages only it needed",
               "Packages that were installed for it and that nothing else uses go too.", default=True),
        Option("nodeps", "Skip dependency checks",
               "Removes only this package with rpm, leaving the packages that need it installed.",
               warning="The packages that need it can stop working: {dependents}."),
    ]

    def preview(self, pkgs, opts):
        p = Preview()
        p.dependents = self._needed_by(pkgs)
        p.dependents_go = "nodeps" not in opts    # zypper removes what needs it
        p.removed = list(pkgs) + (p.dependents if p.dependents_go else [])
        argv = ["zypper", "--non-interactive", "--no-refresh", "remove", "--dry-run"]
        if "deps" in opts:
            argv.append("--clean-deps")
        r = self.run(argv + list(pkgs))
        if r is not None and r[0] == 0:
            p.output = r[1]
            m = re.search(r"going to be REMOVED:\s*\n((?:\s+\S.*\n?)+)", r[1])
            if m:
                every = m.group(1).split()
                p.unneeded = [n for n in every if n not in pkgs and n not in p.dependents]
                if p.dependents_go:
                    p.removed = list(pkgs) + p.dependents + p.unneeded
                p.exact = True
        return p

    def commands(self, pkgs, opts):
        if "nodeps" in opts:
            return self.nodeps_command(pkgs)
        return [self._root(["zypper", "remove"] + (["--clean-deps"] if "deps" in opts else []) + list(pkgs))]

    def reinstall(self, pkgs, info=None):
        return [self._root(["zypper", "install"] + list(pkgs))]


class RpmOstree(_Rpm):
    """Image-based Fedora (Silverblue, Kinoite, Bazzite): only packages you
    layered on top can be removed, and that takes effect after a restart."""
    name, label, tools = "rpm-ostree", "rpm-ostree", ("rpm-ostree",)
    needs_root = False   # it asks for the password itself
    options = []

    def _layered(self) -> List[str]:
        out = _ok(self.run(["rpm-ostree", "status", "--json"]))
        try:
            data = json.loads(out)
        except ValueError:
            return []
        for d in data.get("deployments", []):
            if d.get("booted"):
                return list(d.get("requested-packages", [])) + list(d.get("packages", []))
        return []

    def blocked(self, pkg):
        if pkg not in self._layered():
            return ("it's part of the system image, which can't be changed from here. You can still hide it "
                    "from your menus with its switch")
        return ""

    def preview(self, pkgs, opts):
        p = Preview(removed=list(pkgs))
        p.dependents = self._needed_by(pkgs)
        return p

    def commands(self, pkgs, opts):
        return [["rpm-ostree", "uninstall"] + list(pkgs)]

    def reinstall(self, pkgs, info=None):
        return [["rpm-ostree", "install"] + list(pkgs)]


# ---------------------------------------------------------------------------
# xbps (Void)


def _xbps_name(pkgver: str) -> str:
    """firefox-128.0_1 -> firefox."""
    return pkgver.rsplit("-", 1)[0] if "-" in pkgver else pkgver


class Xbps(Manager):
    name, label, tools = "xbps", "xbps", ("xbps-query",)
    options = [
        Option("deps", "Remove packages only it needed",
               "Packages that were installed for it and that nothing else uses go too.", default=True),
        Option("force", "Remove even if other packages need it",
               "xbps normally stops when something depends on it.",
               warning="The packages that need it can stop working: {dependents}."),
    ]

    def owner(self, path):
        out = _ok(self.run(["xbps-query", "-o", path]))
        m = re.match(r"^(\S+?):\s", out)
        return _xbps_name(m.group(1)) if m else ""

    def info(self, pkg):
        version = _ok(self.run(["xbps-query", "-p", "pkgver", pkg])).strip()
        size = _ok(self.run(["xbps-query", "-p", "installed_size", pkg])).strip()
        return Info(pkg, version[len(pkg) + 1:] if version.startswith(pkg + "-") else version, _human_size(size))

    def files(self, pkg):
        return [l.split(" -> ")[0] for l in _ok(self.run(["xbps-query", "-f", pkg])).splitlines()
                if l.startswith("/")]

    def preview(self, pkgs, opts):
        p = Preview()
        needed = []
        for pkg in pkgs:
            needed += [_xbps_name(l.strip()) for l in _ok(self.run(["xbps-query", "-X", pkg])).splitlines()
                       if l.strip()]
        p.dependents = [n for n in dict.fromkeys(needed) if n not in pkgs]
        argv = ["xbps-remove", "-n"] + (["-R"] if "deps" in opts else []) + (["-F"] if "force" in opts else [])
        r = self.run(argv + list(pkgs))
        if r is not None:
            p.output = r[1]
            names = [_xbps_name(n) for n in re.findall(r"^(\S+) remove\b", r[1], flags=re.M)]
            if r[0] == 0 and names:
                p.removed = list(pkgs) + [n for n in names if n not in pkgs]
                p.exact = True
        if not p.removed:
            p.removed = list(pkgs)
        p.unneeded = [n for n in p.removed if n not in pkgs]
        if p.dependents and "force" not in opts:
            p.stops = "xbps would stop, because %s need%s it." % (", ".join(p.dependents),
                                                                  "s" if len(p.dependents) == 1 else "")
        return p

    def commands(self, pkgs, opts):
        return [self._root(["xbps-remove"] + (["-R"] if "deps" in opts else []) +
                           (["-F"] if "force" in opts else []) + list(pkgs))]

    def reinstall(self, pkgs, info=None):
        return [self._root(["xbps-install"] + list(pkgs))]


# ---------------------------------------------------------------------------
# apk (Alpine, postmarketOS)


def _apk_name(pkgver: str) -> str:
    """firefox-128.0-r0 -> firefox."""
    parts = pkgver.rsplit("-", 2)
    return parts[0] if len(parts) == 3 and parts[2].startswith("r") else pkgver


class Apk(Manager):
    name, label, tools = "apk", "apk", ("apk",)
    options = [
        Option("rdepends", "Also remove packages that need it",
               "apk normally keeps it while something you installed needs it.",
               warning="Also removes: {dependents}."),
    ]

    def owner(self, path):
        out = _ok(self.run(["apk", "info", "--who-owns", path]))
        m = re.search(r"is owned by (\S+)", out)
        return _apk_name(m.group(1)) if m else ""

    def info(self, pkg):
        out = _ok(self.run(["apk", "info", "-s", pkg]))
        m = re.search(r"installed size:\s*\n\s*(.+)", out)
        return Info(pkg, "", _human_size(m.group(1)) if m else 0)

    def files(self, pkg):
        return ["/" + l.strip() for l in _ok(self.run(["apk", "info", "-L", pkg])).splitlines()[1:]
                if l.strip() and "contains" not in l]

    def preview(self, pkgs, opts):
        p = Preview()
        needed = []
        for pkg in pkgs:
            out = _ok(self.run(["apk", "info", "-r", pkg]))
            needed += [_apk_name(l.strip()) for l in out.splitlines()[1:] if l.strip()]
        p.dependents = [n for n in dict.fromkeys(needed) if n not in pkgs]
        p.dependents_go = "rdepends" in opts
        r = self.run(["apk", "del", "-s"] + (["-r"] if "rdepends" in opts else []) + list(pkgs))
        if r is not None:
            p.output = r[1]
            names = [_apk_name(n) for n in re.findall(r"\(\d+/\d+\) (?:Purging|Deleting) (\S+)", r[1])]
            if names:
                p.removed = list(pkgs) + [n for n in names if n not in pkgs]
                p.exact = True
            m = re.search(r"not removed due to:\s*\n((?:\s+.*\n?)+)", r[1])
            if m:
                p.stops = ("apk would keep it, because something you installed needs it: %s. Turn on "
                           "“Also remove packages that need it” to remove those too."
                           % " ".join(m.group(1).split()))
        if not p.removed:
            p.removed = list(pkgs) + (p.dependents if p.dependents_go else [])
        p.unneeded = [n for n in p.removed if n not in pkgs and n not in p.dependents]
        return p

    def commands(self, pkgs, opts):
        return [self._root(["apk", "del"] + (["-r"] if "rdepends" in opts else []) + list(pkgs))]

    def reinstall(self, pkgs, info=None):
        return [self._root(["apk", "add"] + list(pkgs))]

    def _root(self, argv):
        # Alpine usually has doas rather than sudo.
        for tool in ("doas", "sudo"):
            if self.which(tool):
                return [tool] + argv
        return as_root(argv, self.which)


# ---------------------------------------------------------------------------
# eopkg (Solus)


class Eopkg(Manager):
    name, label, tools = "eopkg", "eopkg", ("eopkg",)
    options = [
        Option("purge", "Also remove its system-wide settings",
               "Deletes its configuration files in /etc too. Your own settings aren't affected."),
    ]

    def owner(self, path):
        out = _ok(self.run(["eopkg", "search-file", path]))
        m = re.search(r"Package (\S+) has file", out)
        return m.group(1) if m else ""

    def info(self, pkg):
        out = _ok(self.run(["eopkg", "info", "-s", pkg]))
        m = re.search(r"version:\s*([^,\s]+)", out)
        return Info(pkg, m.group(1) if m else "")

    def preview(self, pkgs, opts):
        # eopkg lists everything it would remove, dependents included, and asks first.
        return Preview(removed=list(pkgs))

    def commands(self, pkgs, opts):
        return [self._root(["eopkg", "remove"] + (["--purge"] if "purge" in opts else []) + list(pkgs))]

    def reinstall(self, pkgs, info=None):
        return [self._root(["eopkg", "install"] + list(pkgs))]


# ---------------------------------------------------------------------------
# Portage (Gentoo)


class Portage(Manager):
    name, label, tools = "portage", "Portage", ("emerge",)
    options = [
        Option("unmerge", "Remove even if other packages need it",
               "Portage normally keeps it while something needs it.",
               warning="The packages that need it can stop working, and the next update may install it "
                       "again: {dependents}."),
    ]

    def owner(self, path):
        if self.which("qfile"):
            out = _ok(self.run(["qfile", "-qC", path]))
            if out.strip():
                return out.split()[0]
        if self.which("equery"):
            out = _ok(self.run(["equery", "-q", "-C", "belongs", path]))
            if out.strip():
                return re.sub(r"-\d.*$", "", out.split()[0])
        return ""

    def info(self, pkg):
        out = _ok(self.run(["qlist", "-ICv", pkg])) if self.which("qlist") else ""
        version = out.split()[0][len(pkg) + 1:] if out.startswith(pkg + "-") else ""
        return Info(pkg, version)

    def files(self, pkg):
        return [l for l in _ok(self.run(["qlist", "-C", pkg])).splitlines() if l.startswith("/")] \
            if self.which("qlist") else []

    def preview(self, pkgs, opts):
        p = Preview(removed=list(pkgs))
        if "unmerge" in opts:
            return p
        r = self.run(["emerge", "--pretend", "--depclean", "--quiet"] + list(pkgs))
        if r is None:
            return p
        p.output = r[1]
        m = re.search(r"pulled in by:\s*\n((?:\s{2,}\S.*\n?)+)", r[1])
        if m:
            deps = [l.split()[0] for l in m.group(1).splitlines() if l.strip()]
            p.dependents = [re.sub(r"-\d.*$", "", d) for d in deps if not d.startswith("@")]
            if p.dependents:
                p.stops = "Portage would keep it, because %s need%s it." % (
                    ", ".join(p.dependents), "s" if len(p.dependents) == 1 else "")
        p.exact = r[0] == 0
        return p

    def commands(self, pkgs, opts):
        if "unmerge" in opts:
            return [self._root(["emerge", "--ask", "--unmerge"] + list(pkgs))]
        return [self._root(["emerge", "--ask", "--deselect"] + list(pkgs)),
                self._root(["emerge", "--ask", "--depclean"] + list(pkgs))]

    def reinstall(self, pkgs, info=None):
        return [self._root(["emerge", "--ask"] + list(pkgs))]


# ---------------------------------------------------------------------------
# Nix


def _store_name(path: str) -> str:
    """/nix/store/<hash>-gimp-2.10.38/share/... -> gimp-2.10.38."""
    m = re.search(r"/nix/store/[0-9a-z]{32}-([^/]+)", path)
    return m.group(1) if m else ""


class Nix(Manager):
    """Packages in your own Nix profile can be removed; ones in the NixOS or
    home-manager configuration come from there and go when you take them out."""
    name, label, tools = "nix", "Nix", ("nix-env", "nix")
    needs_root = False
    options = []
    asks_first = False

    def __init__(self, run: Run = run, which: Callable = shutil.which, home: str = ""):
        super().__init__(run, which)
        self.home = home or os.path.expanduser("~")
        self._where: Dict[str, str] = {}

    def owner(self, path):
        real = os.path.realpath(path)
        name = _store_name(real)
        if not name:
            return ""
        pkg = re.sub(r"-\d[\w.+-]*$", "", name) or name
        user_profiles = (os.path.join(self.home, ".nix-profile"), os.path.join(self.home, ".local", "state", "nix"),
                         "/nix/var/nix/profiles/per-user")
        self._where[pkg] = "user" if path.startswith(user_profiles) else "system"
        return pkg

    def _new_cli(self) -> bool:
        return os.path.isfile(os.path.join(self.home, ".nix-profile", "manifest.json")) or \
            os.path.isfile(os.path.join(self.home, ".local", "state", "nix", "profile", "manifest.json"))

    def blocked(self, pkg):
        if self._where.get(pkg) == "system":
            return ("it comes from your NixOS or home-manager configuration. Take it out of the configuration "
                    "and rebuild, and it goes. You can still hide it from your menus with its switch")
        return ""

    def commands(self, pkgs, opts):
        if self._new_cli():
            return [["nix", "profile", "remove"] + list(pkgs)]
        return [["nix-env", "--uninstall"] + list(pkgs)]

    def reinstall(self, pkgs, info=None):
        if self._new_cli():
            return [["nix", "profile", "install"] + ["nixpkgs#" + p for p in pkgs]]
        return [["nix-env", "-iA"] + ["nixpkgs." + p for p in pkgs]]


# ---------------------------------------------------------------------------

# In the order they're tried: image-based and Nix systems also have rpm or
# nix around, so they come before the managers they'd be mistaken for.
MANAGERS = [RpmOstree, Nix, Pacman, Apt, Dnf, Zypper, Xbps, Apk, Eopkg, Portage]


def detect(run: Run = run, which: Callable = shutil.which, booted_ostree: Optional[bool] = None) -> List[Manager]:
    """The package managers on this system, most specific first."""
    ostree = os.path.exists("/run/ostree-booted") if booted_ostree is None else booted_ostree
    found = []
    for cls in MANAGERS:
        if cls is RpmOstree and not ostree:
            continue
        if any(which(t) for t in cls.tools):
            found.append(cls(run, which))
    return found


def owner_of(path: str, managers: Sequence[Manager]) -> Tuple[Optional[Manager], str]:
    """(the manager, the package) that installed `path`, or (None, "")."""
    for m in managers:
        if isinstance(m, Nix) and "/nix/" not in os.path.realpath(path):
            continue
        pkg = m.owner(path)
        if pkg:
            return m, pkg
    return None, ""


def blocked(manager: Manager, pkgs: Sequence[str]) -> str:
    """Why these packages can't be uninstalled here, or ""."""
    held = set(manager.protected())
    for pkg in pkgs:
        why = manager.blocked(pkg) or needed_by_system(pkg)
        if not why and pkg in held:
            why = "%s keeps it protected" % manager.label
        if why:
            return "%s can't be uninstalled here, because %s." % (pkg, why)
    return ""
