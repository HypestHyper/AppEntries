#!/usr/bin/env python3
"""Rebuild the bundled fonts from upstream files.

Usage:
    tools/subset-fonts.py --symbols MaterialSymbolsRounded.(ttf|woff2) \
                          --text GoogleSansFlex-latin.woff2 [--text ...]

Writes app_entries/ui/fonts/*.ttf and app_entries/ui/icons.json.
Needs fontTools (and brotli for .woff2 input).
"""
import argparse
import json
import os
import sys

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = os.path.join(ROOT, "app_entries", "ui")
FONTS = os.path.join(UI, "fonts")


def icon_names():
    with open(os.path.join(UI, "icon-names.txt"), encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]


def build_symbols(src):
    font = TTFont(src)
    by_glyph = {}
    for cp, glyph in font.getBestCmap().items():
        by_glyph.setdefault(glyph, cp)
    names = icon_names()
    missing = [n for n in names if n not in by_glyph]
    if missing:
        sys.exit("Unknown icon names: " + ", ".join(missing))
    # Keep FILL, wght and opsz; pin the grade axis to save space.
    font = instancer.instantiateVariableFont(font, {"GRAD": 0})
    opts = subset.Options()
    opts.layout_features = []
    opts.notdef_outline = True
    opts.name_IDs = ["*"]
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=[by_glyph[n] for n in names])
    sub.subset(font)
    font.flavor = None
    font.save(os.path.join(FONTS, "MaterialSymbolsRounded.ttf"))
    with open(os.path.join(UI, "icons.json"), "w", encoding="utf-8") as f:
        json.dump({n: by_glyph[n] for n in names}, f, indent=1, sort_keys=True)
        f.write("\n")


def build_text(srcs):
    for i, src in enumerate(srcs):
        font = TTFont(src)
        font.flavor = None
        font.save(os.path.join(FONTS, "GoogleSansFlex-%d.ttf" % i))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--text", action="append", default=[])
    args = ap.parse_args()
    os.makedirs(FONTS, exist_ok=True)
    build_symbols(args.symbols)
    build_text(args.text)


if __name__ == "__main__":
    main()
