#!/usr/bin/env bash
# Validate the desktop entry, GSettings schema, metainfo, icons and version numbers.
# Usage: tests/validate-desktop.sh [source-dir]
set -u
root="${1:-$(dirname "$0")/..}"
cd "$root"
APP_ID="io.github.HypestHyper.AppEntries"
desktop="data/$APP_ID.desktop"
fail=0
ok()   { echo "  ok    $1"; }
bad()  { echo "  FAIL  $1"; fail=1; }
skip() { echo "  skip  $1 ($2 not installed)"; }

echo "Validating App Entries data files"

if command -v desktop-file-validate >/dev/null; then
  if out=$(desktop-file-validate "$desktop" 2>&1) && ! grep -qE "error|warning" <<<"$out"; then
    ok "desktop entry"
  else
    echo "$out"; bad "desktop entry"
  fi
else
  skip "desktop entry" desktop-file-validate
fi

# The keys the spec requires, checked without any tools.
for key in "Type=Application" "Name=App Entries" "Exec=$APP_ID" "Icon=$APP_ID" "StartupWMClass=$APP_ID"; do
  grep -qx "$key" "$desktop" && ok "has $key" || bad "missing $key"
done

if command -v glib-compile-schemas >/dev/null; then
  glib-compile-schemas --strict --dry-run data && ok "GSettings schema" || bad "GSettings schema"
else
  skip "GSettings schema" glib-compile-schemas
fi

if command -v appstreamcli >/dev/null; then
  appstreamcli validate --no-net --explain "data/$APP_ID.metainfo.xml" >/dev/null && ok "metainfo" || bad "metainfo"
else
  skip "metainfo" appstreamcli
fi

for svg in "data/icons/hicolor/scalable/apps/$APP_ID.svg:0 0 128 128" \
           "data/icons/hicolor/symbolic/apps/$APP_ID-symbolic.svg:0 0 16 16"; do
  file="${svg%%:*}"; box="${svg#*:}"
  if python3 -c "import sys, xml.etree.ElementTree as E; assert E.parse(sys.argv[1]).getroot().get('viewBox') == sys.argv[2]" "$file" "$box" 2>/dev/null; then
    ok "$(basename "$file") is square and well formed"
  else
    bad "$(basename "$file")"
  fi
done

version=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' app_entries/__init__.py)
grep -q "^## $version " CHANGELOG.md && ok "CHANGELOG.md has $version" || bad "CHANGELOG.md has no '## $version' section"
grep -q "<release version=\"$version\"" "data/$APP_ID.metainfo.xml" && ok "metainfo has release $version" \
  || bad "metainfo has no release $version"
grep -q "^pkgver=$version$" packaging/arch/PKGBUILD && ok "PKGBUILD is $version" || bad "PKGBUILD version isn't $version"

exit $fail
