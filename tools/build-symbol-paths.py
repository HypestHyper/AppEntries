#!/usr/bin/env python3
"""Build app_entries/data/material-symbols.json.gz from the Material Symbols
Rounded variable font: every icon's outline as SVG path data, outlined
(FILL 0) and filled (FILL 1), at weight 400 on a 960-unit grid, plus its
codepoint. Also writes two static fonts with every icon, used to draw the
icon picker's grid quickly (app_entries/ui/fonts/PickerSymbols-*.ttf).

Usage: tools/build-symbol-paths.py MaterialSymbolsRounded.(ttf|woff2)
Needs fontTools (and brotli for .woff2 input).
"""
import gzip
import json
import os
import sys

from fontTools import subset
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "app_entries", "data", "material-symbols.json.gz")
FONTS = os.path.join(ROOT, "app_entries", "ui", "fonts")
FAMILIES = ("App Entries Symbols Outlined", "App Entries Symbols Filled")
GRID = 960


def paths(font, names):
    gs = font.getGlyphSet()
    out = {}
    for name in names:
        pen = SVGPathPen(gs, ntos=lambda v: ("%.1f" % v).rstrip("0").rstrip("."))
        # Font units are y-up; SVG is y-down.
        gs[name].draw(TransformPen(pen, (1, 0, 0, -1, 0, GRID)))
        out[name] = pen.getCommands()
    return out


def rename(font, family):
    for rec in font["name"].names:
        if rec.nameID in (1, 4, 16):
            rec.string = family
        elif rec.nameID == 6:
            rec.string = family.replace(" ", "")
        elif rec.nameID in (2, 17):
            rec.string = "Regular"


def picker_font(inst, codepoints, family, path):
    opts = subset.Options()
    opts.layout_features = []
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=codepoints)
    sub.subset(inst)
    rename(inst, family)
    inst.flavor = None
    inst.save(path)


def main():
    src = sys.argv[1]
    base = TTFont(src)
    cmap = {}
    for cp, g in base.getBestCmap().items():
        if cp >= 0xE000:
            cmap.setdefault(g, cp)
    names = sorted(cmap)
    styles = []
    for fill in (0, 1):
        inst = instancer.instantiateVariableFont(TTFont(src), {"FILL": fill, "wght": 400, "GRAD": 0, "opsz": 24})
        styles.append(paths(inst, names))
        picker_font(inst, sorted(cmap.values()), FAMILIES[fill],
                    os.path.join(FONTS, "PickerSymbols-%s.ttf" % ("Filled" if fill else "Outlined")))
    data = {
        "source": "Material Symbols Rounded (Apache 2.0), weight 400, optical size 24",
        "grid": GRID,
        "icons": {n: [styles[0][n], styles[1][n], cmap[n]] for n in names},
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(data, f, separators=(",", ":"))
    print("%d icons, %d KB" % (len(names), os.path.getsize(OUT) // 1024))


if __name__ == "__main__":
    main()
