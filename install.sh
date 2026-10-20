#!/bin/sh
# Install App Entries for the current user (~/.local) or system-wide.
#
#   ./install.sh                  install to ~/.local
#   sudo ./install.sh --system    install to /usr/local
#   ./install.sh --prefix DIR     install to DIR
#   ./install.sh --yes            install missing packages without asking
#
# Uninstall with ./uninstall.sh and the same options.
set -eu

APP_ID="io.github.HypestHyper.AppEntries"
SHORT_NAME="app-entries"
PREFIX="${HOME}/.local"
ASSUME_YES=0
while [ $# -gt 0 ]; do
    case "$1" in
        --system) PREFIX="/usr/local" ;;
        --prefix) PREFIX="$2"; shift ;;
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

SRC="$(cd "$(dirname "$0")" && pwd)"
APPDIR="$PREFIX/share/$APP_ID"
BINDIR="$PREFIX/bin"
SCHEMADIR="$PREFIX/share/glib-2.0/schemas"

say() { printf '\033[1m%s\033[0m\n' "$*"; }

# --- dependencies -----------------------------------------------------------

have_python() {
    command -v python3 >/dev/null 2>&1 &&
        python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null
}
have_gtk() {
    python3 -c 'import gi; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk' 2>/dev/null
}

# Prints "<manager> <packages...>" for this distribution, or nothing.
packages_for_distro() {
    [ -r /etc/os-release ] || return 0
    # shellcheck disable=SC1091
    ids="$(. /etc/os-release; echo "${ID:-} ${ID_LIKE:-}")"
    for id in $ids; do
        case "$id" in
            arch|manjaro|cachyos|endeavouros|garuda)
                echo "pacman python python-gobject gtk4"; return ;;
            debian|ubuntu|linuxmint|pop|elementary|zorin)
                echo "apt python3 python3-gi gir1.2-gtk-4.0"; return ;;
            fedora|rhel|centos|nobara)
                echo "dnf python3 python3-gobject gtk4"; return ;;
            opensuse*|suse|sles)
                echo "zypper python3 python3-gobject typelib-1_0-Gtk-4_0"; return ;;
        esac
    done
}

install_command() {
    manager="$1"; shift
    case "$manager" in
        pacman) echo "pacman -S --needed --noconfirm $*" ;;
        apt)    echo "apt-get install -y $*" ;;
        dnf)    echo "dnf install -y $*" ;;
        zypper) echo "zypper install -y $*" ;;
    esac
}

ensure_dependencies() {
    if have_python && have_gtk; then
        return
    fi
    found="$(packages_for_distro)"
    if [ -z "$found" ]; then
        cat >&2 <<'EOF'
Python 3.9+ with GTK 4 (PyGObject) is required. Install it with your package manager:
  Arch / CachyOS / Manjaro:  sudo pacman -S python-gobject gtk4
  Debian / Ubuntu:           sudo apt install python3-gi gir1.2-gtk-4.0
  Fedora:                    sudo dnf install python3-gobject gtk4
  openSUSE:                  sudo zypper install python3-gobject typelib-1_0-Gtk-4_0
EOF
        exit 1
    fi
    # shellcheck disable=SC2086
    set -- $found
    manager="$1"; shift
    cmd="$(install_command "$manager" "$@")"
    sudo=""
    if [ "$(id -u)" -ne 0 ]; then
        if command -v sudo >/dev/null 2>&1; then sudo="sudo"
        elif command -v doas >/dev/null 2>&1; then sudo="doas"
        else echo "Run this as root to install: $cmd" >&2; exit 1
        fi
    fi

    say "Python 3.9+ with GTK 4 is missing. These packages provide it:"
    echo "  $sudo $cmd"
    if [ "$ASSUME_YES" = 0 ]; then
        if [ ! -t 0 ]; then
            echo "Run the command above, or run ./install.sh --yes to install them automatically." >&2
            exit 1
        fi
        printf 'Install them now? [y/N] '
        read -r answer
        case "$answer" in
            y|Y|yes|Yes) ;;
            *) echo "Nothing was installed."; exit 1 ;;
        esac
    fi

    if [ "$manager" = "apt" ]; then
        $sudo apt-get update -q
    fi
    # shellcheck disable=SC2086
    $sudo $cmd

    if ! have_python || ! have_gtk; then
        echo "GTK 4 for Python still can't be loaded. Check the package manager output above." >&2
        exit 1
    fi
}

ensure_dependencies
if ! python3 -c 'import gi, sys; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk; sys.exit(Gtk.get_minor_version() < 6)' 2>/dev/null; then
    v="$(python3 -c 'import gi; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk; print("4.%d" % Gtk.get_minor_version())' 2>/dev/null || echo unknown)"
    echo "GTK 4.6 or newer is required; this system has GTK $v." >&2
    exit 1
fi

# --- files ------------------------------------------------------------------
say "Installing to $PREFIX"
rm -rf "$APPDIR/app_entries"
mkdir -p "$APPDIR" "$BINDIR" "$SCHEMADIR" \
    "$PREFIX/share/applications" "$PREFIX/share/metainfo" \
    "$PREFIX/share/icons/hicolor/scalable/apps" "$PREFIX/share/icons/hicolor/symbolic/apps"

cp -r "$SRC/app_entries" "$APPDIR/app_entries"
find "$APPDIR/app_entries" -name '__pycache__' -type d -prune -exec rm -rf {} +
# Launchers often run without ~/.local/bin in PATH, so name the program by its full path.
case "$BINDIR" in
    *" "*) EXEC="\"$BINDIR/$APP_ID\"" ;;
    *) EXEC="$BINDIR/$APP_ID" ;;
esac
sed "s|^Exec=.*|Exec=$EXEC|" "$SRC/data/$APP_ID.desktop" > "$PREFIX/share/applications/$APP_ID.desktop"
cp "$SRC/data/$APP_ID.metainfo.xml" "$PREFIX/share/metainfo/"
cp "$SRC/data/$APP_ID.gschema.xml" "$SCHEMADIR/"
cp "$SRC/data/icons/hicolor/scalable/apps/$APP_ID.svg" "$PREFIX/share/icons/hicolor/scalable/apps/"
cp "$SRC/data/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg" "$PREFIX/share/icons/hicolor/symbolic/apps/"

# --- launcher ---------------------------------------------------------------
cat > "$BINDIR/$APP_ID" <<EOF
#!/bin/sh
APPDIR="$APPDIR"
APP_ENTRIES_SCHEMA_DIR="$SCHEMADIR" PYTHONPATH="\$APPDIR\${PYTHONPATH:+:\$PYTHONPATH}" \\
    exec python3 -m app_entries "\$@"
EOF
chmod 755 "$BINDIR/$APP_ID"

# Short command, only if nothing else already owns the name.
if [ -L "$BINDIR/$SHORT_NAME" ] && [ "$(readlink "$BINDIR/$SHORT_NAME")" = "$APP_ID" ]; then
    SHORT="$SHORT_NAME"
elif [ ! -e "$BINDIR/$SHORT_NAME" ] && ! command -v "$SHORT_NAME" >/dev/null 2>&1; then
    ln -s "$APP_ID" "$BINDIR/$SHORT_NAME"
    SHORT="$SHORT_NAME"
else
    SHORT="$APP_ID"
fi

# --- caches -----------------------------------------------------------------
command -v glib-compile-schemas >/dev/null 2>&1 && \
    glib-compile-schemas "$SCHEMADIR" >/dev/null 2>&1 || true
# Only refresh an icon cache that already exists. A new one would go stale as soon as
# another app adds icons (Steam does), and GTK would then stop finding those icons.
if [ -f "$PREFIX/share/icons/hicolor/icon-theme.cache" ]; then
    if command -v gtk4-update-icon-cache >/dev/null 2>&1; then
        gtk4-update-icon-cache -q -t -f "$PREFIX/share/icons/hicolor" 2>/dev/null || true
    elif command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f "$PREFIX/share/icons/hicolor" 2>/dev/null || true
    fi
fi
command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database -q "$PREFIX/share/applications" 2>/dev/null || true

say "Done. Start it from your launcher or run: $SHORT"
case ":$PATH:" in
    *":$BINDIR:"*) ;;
    *) echo "Note: $BINDIR is not in your PATH." ;;
esac
