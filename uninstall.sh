#!/bin/sh
# Remove App Entries. Use the same --system / --prefix option as for install.
#
#   --restore-apps  also delete the hide files App Entries made, so every app it
#                   hid shows up in your launcher again
#   --purge         also delete its settings
#
# Without --restore-apps, apps you hid stay hidden after uninstalling, and
# login programs you turned off stay off.
set -eu

APP_ID="io.github.HypestHyper.AppEntries"
SHORT_NAME="app-entries"
PREFIX="${HOME}/.local"
PURGE=0
RESTORE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --system) PREFIX="/usr/local" ;;
        --prefix) PREFIX="$2"; shift ;;
        --purge) PURGE=1 ;;
        --restore-apps) RESTORE=1 ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

BINDIR="$PREFIX/bin"
APPDIR="$PREFIX/share/$APP_ID"
SCHEMADIR="$PREFIX/share/glib-2.0/schemas"
USER_APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

# Only files App Entries made and that nobody has edited since are deleted. This
# doesn't need the app itself, so it also works after a plain uninstall.
USER_AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
if [ "$RESTORE" = 1 ]; then
    python3 - "$USER_APPS" "$USER_AUTOSTART" <<'PY'
import glob, hashlib, os, sys

MARKER = "X-AppEntries-Managed"
CHECKSUM = "X-AppEntries-Checksum"
MINIMAL = {"Type", "Name", "Hidden", MARKER}


def untouched(text, keys, groups):
    """Made by App Entries and not edited since (the app's is_pristine)."""
    if groups == ["[Desktop Entry]"] and set(keys) <= MINIMAL:
        return True  # a hide file from the first test version
    lines = [l for l in text.splitlines() if l.strip().split("=", 1)[0].strip() != CHECKSUM]
    digest = hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()[:16]
    return keys.get(CHECKSUM) == digest


for folder in sys.argv[1:]:
    for path in sorted(glob.glob(os.path.join(folder, "**", "*.desktop"), recursive=True)):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        lines = [l.strip() for l in text.splitlines()]
        groups = [l for l in lines if l.startswith("[") and l.endswith("]")]
        keys = {}
        for l in lines:
            if "=" in l and not l.startswith("#") and not l.startswith("["):
                k, v = l.split("=", 1)
                keys.setdefault(k.strip(), v.strip())
        if keys.get(MARKER) != "true":
            continue
        if untouched(text, keys, groups):
            os.unlink(path)
            print("  restored", os.path.basename(path))
        else:
            print("  kept, edited since:", path)
PY
fi

if [ -L "$BINDIR/$SHORT_NAME" ] && [ "$(readlink "$BINDIR/$SHORT_NAME")" = "$APP_ID" ]; then
    rm -f "$BINDIR/$SHORT_NAME"
fi
rm -f "$BINDIR/$APP_ID" \
      "$PREFIX/share/applications/$APP_ID.desktop" \
      "$PREFIX/share/metainfo/$APP_ID.metainfo.xml" \
      "$SCHEMADIR/$APP_ID.gschema.xml" \
      "$PREFIX/share/icons/hicolor/scalable/apps/$APP_ID.svg" \
      "$PREFIX/share/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg"
rm -rf "$APPDIR"

# The app keeps an accent-coloured copy of its icon in the user's icon folder.
USER_ICON="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/$APP_ID.svg"
if [ -f "$USER_ICON" ] && grep -q "App Entries accent icon" "$USER_ICON"; then
    rm -f "$USER_ICON"
fi

if [ "$PURGE" = 1 ]; then
    rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/$APP_ID"
    command -v gsettings >/dev/null 2>&1 && gsettings reset-recursively "$APP_ID" 2>/dev/null || true
fi
command -v glib-compile-schemas >/dev/null 2>&1 && [ -d "$SCHEMADIR" ] && \
    glib-compile-schemas "$SCHEMADIR" >/dev/null 2>&1 || true
command -v update-desktop-database >/dev/null 2>&1 && \
    update-desktop-database -q "$PREFIX/share/applications" 2>/dev/null || true
echo "App Entries removed from $PREFIX."
if ls "$USER_APPS"/app-entries-*.desktop >/dev/null 2>&1; then
    echo "Launchers you made with it are kept, in $USER_APPS (app-entries-*.desktop)."
fi
if [ "$RESTORE" = 0 ] && grep -rlq "X-AppEntries-Managed=true" "$USER_APPS" 2>/dev/null; then
    echo "Apps you hid are still hidden. To show them again, run ./uninstall.sh --restore-apps"
    echo "or delete their files in $USER_APPS."
fi
