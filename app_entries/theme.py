"""Material 3 Expressive dark palette, derived from one seed colour."""
import colorsys
import re

DEFAULT_SEED = "53dbb0"
NEUTRAL_SAT = 0.14

ERROR_COLORS = {
    True: {
        "ERROR": "#ffb4ab",
        "ERROR_CONTAINER": "#93000a",
        "ERROR_HOVER": "#b3261e",
        "ON_ERROR_CONTAINER": "#ffdad6",
    },
    False: {
        "ERROR": "#ba1a1a",
        "ERROR_CONTAINER": "#ffdad6",
        "ERROR_HOVER": "#ba1a1a",
        "ON_ERROR_CONTAINER": "#410002",
    },
}

# Shadows aren't palette colours, so they're swapped rather than blended.
SHADOWS = {
    True: {"SHADOW_S": "rgba(0,0,0,.25)", "SHADOW_M": "rgba(0,0,0,.35)", "SHADOW_L": "rgba(0,0,0,.5)"},
    False: {"SHADOW_S": "rgba(0,0,0,.08)", "SHADOW_M": "rgba(0,0,0,.14)", "SHADOW_L": "rgba(0,0,0,.22)"},
}


def valid_seed(seed: str) -> str:
    seed = (seed or "").strip().lstrip("#").lower()
    return seed if re.fullmatch(r"[0-9a-f]{6}", seed) else DEFAULT_SEED


def _hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)), max(0.0, min(1.0, s)))
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


def _hue_sat(seed: str):
    seed = valid_seed(seed)
    r, g, b = (int(seed[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, _, sat = colorsys.rgb_to_hls(r, g, b)
    return hue, max(0.45, min(0.85, sat))


def tone(seed: str, lightness: float) -> str:
    """The seed's hue and (clamped) saturation at a given lightness."""
    hue, sat = _hue_sat(seed)
    return _hex(hue, sat, lightness)


def palette(seed: str = DEFAULT_SEED, dark: bool = True) -> dict:
    hue, sat = _hue_sat(seed)
    ns = NEUTRAL_SAT
    th = hue + 0.17
    if dark:
        p = {
            "SURFACE_DIM": _hex(hue, ns, .065),
            "SURFACE_CONTAINER_LOWEST": _hex(hue, ns, .05),
            "SURFACE_CONTAINER_LOW": _hex(hue, ns, .095),
            "SURFACE_CONTAINER": _hex(hue, ns, .115),
            "SURFACE_CONTAINER_HIGH": _hex(hue, ns, .15),
            "SURFACE_CONTAINER_HIGHEST": _hex(hue, ns, .19),
            "SURFACE_BRIGHT": _hex(hue, ns, .23),
            "PRIMARY": _hex(hue, sat, .66),
            "PRIMARY_HOVER": _hex(hue, sat, .74),
            "ON_PRIMARY": _hex(hue, sat, .12),
            "PRIMARY_CONTAINER": _hex(hue, sat * .8, .24),
            "ON_PRIMARY_CONTAINER": _hex(hue, sat, .84),
            "SECONDARY_CONTAINER": _hex(hue, .20, .26),
            "SECONDARY_CONTAINER_HOVER": _hex(hue, .22, .31),
            "ON_SECONDARY_CONTAINER": _hex(hue, .25, .88),
            "TERTIARY": _hex(th, .45, .72),
            "TERTIARY_CONTAINER": _hex(th, .25, .28),
            "ON_TERTIARY_CONTAINER": _hex(th, .35, .88),
            "ON_SURFACE": _hex(hue, .10, .90),
            "ON_SURFACE_VARIANT": _hex(hue, .08, .76),
            "OUTLINE": _hex(hue, .07, .57),
            "OUTLINE_VARIANT": _hex(hue, .09, .27),
            "INVERSE_SURFACE": _hex(hue, .10, .89),
            "INVERSE_ON_SURFACE": _hex(hue, .12, .18),
            "INVERSE_PRIMARY": _hex(hue, sat, .38),
        }
    else:
        # The same roles in light tones: pale tinted surfaces, deep accents.
        p = {
            "SURFACE_DIM": _hex(hue, ns * 1.6, .955),
            "SURFACE_CONTAINER_LOWEST": _hex(hue, ns, 1.0),
            "SURFACE_CONTAINER_LOW": _hex(hue, ns * 1.6, .97),
            "SURFACE_CONTAINER": _hex(hue, ns * 2, .985),
            "SURFACE_CONTAINER_HIGH": _hex(hue, ns * 1.6, .925),
            "SURFACE_CONTAINER_HIGHEST": _hex(hue, ns * 1.6, .895),
            "SURFACE_BRIGHT": _hex(hue, ns, .99),
            "PRIMARY": _hex(hue, sat, .34),
            "PRIMARY_HOVER": _hex(hue, sat, .28),
            "ON_PRIMARY": _hex(hue, sat, .99),
            "PRIMARY_CONTAINER": _hex(hue, sat * .8, .86),
            "ON_PRIMARY_CONTAINER": _hex(hue, sat, .14),
            "SECONDARY_CONTAINER": _hex(hue, .28, .86),
            "SECONDARY_CONTAINER_HOVER": _hex(hue, .28, .81),
            "ON_SECONDARY_CONTAINER": _hex(hue, .30, .14),
            "TERTIARY": _hex(th, .45, .40),
            "TERTIARY_CONTAINER": _hex(th, .45, .89),
            "ON_TERTIARY_CONTAINER": _hex(th, .40, .16),
            "ON_SURFACE": _hex(hue, .12, .11),
            "ON_SURFACE_VARIANT": _hex(hue, .08, .30),
            "OUTLINE": _hex(hue, .07, .46),
            "OUTLINE_VARIANT": _hex(hue, .10, .80),
            "INVERSE_SURFACE": _hex(hue, .10, .19),
            "INVERSE_ON_SURFACE": _hex(hue, .12, .94),
            "INVERSE_PRIMARY": _hex(hue, sat, .78),
        }
    p.update(ERROR_COLORS[dark])
    p.update(SHADOWS[dark])
    return p


def _rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix_palette(old: dict, new: dict, t: float) -> dict:
    out = {}
    for k, v in new.items():
        if not v.startswith("#"):
            out[k] = v
            continue
        a, b = _rgb(old.get(k, v)), _rgb(v)
        out[k] = "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))
    return out


# Accent choices offered in Preferences.
# More colours for icons (not used as accents); the last ones are neutral.
EXTRA_COLORS = [
    ("e5484d", "Red"),
    ("2e9e7e", "Teal"),
    ("8b5e3c", "Brown"),
    ("6b7280", "Grey"),
    ("1b1b1f", "Black"),
    ("f4f4f5", "White"),
]

SEEDS = [
    ("53dbb0", "Mint"),
    ("6aa6ff", "Sky"),
    ("b38cff", "Lilac"),
    ("ff8fb1", "Rose"),
    ("ffb35c", "Amber"),
    ("9ccc65", "Leaf"),
]
