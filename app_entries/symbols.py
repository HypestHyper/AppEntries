"""Material Symbols as SVG: search the full set and draw an icon, optionally
on a coloured tile. Pure Python, no GTK.

The paths come from data/material-symbols.json.gz, built by
tools/build-symbol-paths.py (Material Symbols Rounded, Apache 2.0).
"""
import base64
import colorsys
import gzip
import json
import os
import re
from dataclasses import dataclass, fields
from typing import Dict, List, Optional

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "material-symbols.json.gz")
GRID = 960

_icons: Optional[Dict[str, List[str]]] = None

STYLES = ("outlined", "filled")
# Tile shapes, drawn on the same 960 grid.
SHAPES = ("none", "circle", "rounded", "squircle")
GRADIENTS = ("flat", "soft", "strong")
# Fields that make up an icon's look, as opposed to which symbol it shows.
STYLE_FIELDS = ("style", "shape", "color", "recolor", "border", "border_width", "border_inner", "border_color",
                "gradient", "scale")
_CHOICE_MARK = "app-entries-choice "


def icons() -> Dict[str, List[str]]:
    global _icons
    if _icons is None:
        with gzip.open(DATA, "rt", encoding="utf-8") as f:
            _icons = json.load(f)["icons"]
    return _icons


def names() -> List[str]:
    return sorted(icons())


def search(query: str, limit: int = 0) -> List[str]:
    """Names matching every word of the query; names that start with the
    query come first, then shorter names."""
    words = [w for w in query.casefold().replace("-", " ").replace("_", " ").split() if w]
    if not words:
        return names()[:limit] if limit else names()
    joined = "_".join(words)
    found = []
    for name in icons():
        parts = name.replace("_", " ")
        if all(w in parts for w in words):
            found.append(name)
    found.sort(key=lambda n: (not n.startswith(joined), n != joined, len(n), n))
    return found[:limit] if limit else found


@dataclass
class IconChoice:
    name: str = "terminal"        # Material icon name (source "material")
    style: str = "outlined"
    shape: str = "rounded"
    color: str = "#2e9e7e"
    source: str = "material"      # material, or file: an SVG or PNG in the icon library
    path: str = ""                # the library file (source "file")
    recolor: bool = True          # file: paint it in `color` instead of its own colours
    border: bool = False
    border_width: int = 3         # 1 to 10
    border_inner: bool = False    # also outline the symbol's inner edges (holes)
    border_color: str = "auto"    # auto, white, black or a #hex colour
    gradient: str = "soft"        # tile shading: flat, soft or strong
    scale: int = 60               # the symbol's size on a tile, in % of the tile (40 to 80)

    def key(self) -> str:
        return "|".join(str(getattr(self, f.name)) for f in fields(self))


def codepoint(name: str) -> int:
    return icons()[name][2]


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def lin(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _shade(hex_color: str, lightness_delta: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    light = max(0.0, min(1.0, light + lightness_delta))
    r, g, b = colorsys.hls_to_rgb(hue, light, sat)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def glyph_color(tile: str) -> str:
    """White or near-black, whichever reads better on the tile."""
    return "#1b1b1f" if _luminance(tile) > 0.45 else "#ffffff"


# ---------------------------------------------------------------------------
# Drawing


def _tile_shape(shape: str, inset: float = 0.0) -> str:
    """The tile's outline as an SVG element (without paint attributes),
    shrunk by `inset` grid units on every side."""
    if shape == "circle":
        return '<circle cx="480" cy="480" r="%g"' % (456 - inset)
    if shape == "rounded":
        return ('<rect x="%g" y="%g" width="%g" height="%g" rx="%g"'
                % (24 + inset, 24 + inset, 912 - 2 * inset, 912 - 2 * inset, max(0, 216 - inset)))
    k = (912 - 2 * inset) / 912
    return ('<path transform="translate(480 480) scale(%g) translate(-480 -480)" '
            'd="M480 24C820 24 936 140 936 480S820 936 480 936 24 820 24 480 140 24 480 24Z"' % k)


def outer_edges(d: str) -> str:
    """Only the outer outlines of a glyph, without holes or what's in them."""
    from .icon_library import outer_only
    return outer_only(d)


def border_paint(choice: IconChoice, base: str) -> str:
    if choice.border_color.startswith("#"):
        return choice.border_color
    if choice.border_color == "white":
        return "#ffffff"
    if choice.border_color == "black":
        return "#1b1b1f"
    return glyph_color(base)  # contrasts with what it surrounds


def _border_units(choice: IconChoice) -> float:
    return max(1, min(10, int(choice.border_width))) * 8.0


def _gradient(top: str, bottom: str) -> str:
    return ('<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="960" gradientUnits="userSpaceOnUse">'
            '<stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient></defs>'
            % (top, bottom))


def dataclasses_asdict(choice: IconChoice) -> dict:
    return {f.name: getattr(choice, f.name) for f in fields(choice)}


def _tile_colors(color: str, gradient: str):
    if gradient == "strong":
        # Lighter and a little warmer at the top, deeper at the bottom.
        return _hue_shift(_shade(color, 0.14), -0.03), _hue_shift(_shade(color, -0.14), 0.03)
    return _shade(color, 0.06), _shade(color, -0.06)


def _hue_shift(hex_color: str, delta: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb((hue + delta) % 1.0, light, sat)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def choice_from_svg(text: str) -> Optional[IconChoice]:
    """The choice an App Entries icon was drawn from, or None for other SVGs."""
    m = re.search(r"<!-- %s([A-Za-z0-9+/=]+) -->" % _CHOICE_MARK, text or "")
    if not m:
        return None
    try:
        data = json.loads(base64.b64decode(m.group(1)))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    choice = IconChoice()
    for f in fields(choice):
        v = data.get(f.name)
        if v is not None and type(v) is type(getattr(choice, f.name)):
            setattr(choice, f.name, v)
    return choice


def restyle(choice: IconChoice, style: IconChoice) -> IconChoice:
    """`choice`'s symbol with `style`'s look."""
    out = IconChoice(**dataclasses_asdict(choice))
    for name in STYLE_FIELDS:
        setattr(out, name, getattr(style, name))
    return out


def render(choice: IconChoice, size: int = 128, title: str = "") -> str:
    """An SVG file for this icon choice. Only plain shapes, paths and
    strokes are used, so every launcher's SVG renderer can show it."""
    color = choice.color if choice.color.startswith("#") else "#" + choice.color
    tiled = choice.shape in ("circle", "rounded", "squircle")
    bw = _border_units(choice) if choice.border else 0
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
             'width="%d" height="%d" viewBox="0 0 %d %d">' % (size, size, GRID, GRID)]
    if title:
        parts.append("<title>%s</title>" % (title.replace("&", "&amp;").replace("<", "&lt;")))
    what = ("Material Symbols “%s” (Apache 2.0)" % choice.name if choice.source == "material"
            else "an icon from your library")
    parts.append("<!-- %s, made with App Entries -->" % what)
    # The choice itself, so the icon can be opened again or restyled later.
    data = base64.b64encode(json.dumps(dataclasses_asdict(choice), sort_keys=True).encode()).decode("ascii")
    parts.append("<!-- %s%s -->" % (_CHOICE_MARK, data))

    if tiled:
        # With a border, the border is the full shape and the tile sits on it,
        # shrunk by the border's width. Their edges never line up, so no thin
        # line of tile colour shows around the outside of the border.
        if bw:
            parts.append(_tile_shape(choice.shape) + ' fill="%s"/>' % border_paint(choice, color))
        if choice.gradient == "flat":
            parts.append(_tile_shape(choice.shape, bw) + ' fill="%s"/>' % color)
        else:
            top, bottom = _tile_colors(color, choice.gradient)
            parts.append(_gradient(top, bottom))
            parts.append(_tile_shape(choice.shape, bw) + ' fill="url(#bg)"/>')
        ink = glyph_color(color)
        # The symbol sits centred, at `scale` % of the tile.
        k = max(40, min(80, int(choice.scale))) / 100
        parts.append('<g transform="translate(%g %g) scale(%g)">' % (480 * (1 - k), 480 * (1 - k), k))
        inner_bw = bw / k if (bw and choice.border_inner) else 0
        parts.append(_symbol(choice, ink, inner_bw, border_paint(choice, ink), outer_only=False))
        parts.append("</g>")
    else:
        if bw:
            # Keep the border inside the canvas.
            scale = (GRID - 2 * bw) / GRID
            parts.append('<g transform="translate(%g %g) scale(%g)">' % (bw, bw, scale))
        parts.append(_symbol(choice, color, bw / (((GRID - 2 * bw) / GRID) or 1) if bw else 0,
                             border_paint(choice, color), outer_only=not choice.border_inner))
        if bw:
            parts.append("</g>")
    parts.append("</svg>\n")
    return "".join(parts)


def _symbol(choice: IconChoice, ink: str, bw: float, border: str, outer_only: bool) -> str:
    """The symbol on the 960 grid in `ink`, with a `bw`-wide border behind it."""
    if choice.source == "file":
        from . import icon_library
        return icon_library.symbol_svg(choice.path, ink if choice.recolor else None, bw, border,
                                       inner=not outer_only)
    paths = icons().get(choice.name)
    if paths is None:
        raise KeyError(choice.name)
    d = paths[1 if choice.style == "filled" else 0]
    out = ""
    if bw:
        edge = outer_edges(d) if outer_only else d
        out += ('<path d="%s" fill="none" stroke="%s" stroke-width="%g" stroke-linejoin="round"/>'
                % (edge, border, bw * 2))
    return out + '<path fill="%s" d="%s"/>' % (ink, d)
