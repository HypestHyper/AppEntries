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


def palette(seed: str = DEFAULT_SEED, dark: bool = True, preset: str = "") -> dict:
    """The colours for an accent (`seed`, six hex digits) in dark or light.
    With a `preset` (a key of PRESETS), that scheme's surfaces and text are
    used; its own accent too, unless `seed` is given."""
    if preset in PRESETS:
        base = palette(seed or preset_accent(preset, dark), dark)
        return apply_preset(base, preset, dark, ("#" + valid_seed(seed)) if seed else "")
    seed = seed or DEFAULT_SEED
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


# ---------------------------------------------------------------------------
# Palettes: well-known colour schemes that replace the generated surfaces and
# text, each with a dark and a light version. Values are from each scheme's
# published colours.

def _p(window, card, inner, highest, text, dim, outline, accent, accent2):
    return {"window": window, "card": card, "inner": inner, "highest": highest, "text": text, "dim": dim,
            "outline": outline, "accent": accent, "accent2": accent2}


PRESETS = {
    "catppuccin": ("Catppuccin", {
        True: _p("#181825", "#1e1e2e", "#313244", "#45475a", "#cdd6f4", "#a6adc8", "#6c7086", "#cba6f7", "#fab387"),
        False: _p("#e6e9ef", "#eff1f5", "#dce0e8", "#ccd0da", "#4c4f69", "#6c6f85", "#9ca0b0", "#8839ef", "#fe640b"),
    }),
    "gruvbox": ("Gruvbox", {
        True: _p("#1d2021", "#282828", "#3c3836", "#504945", "#ebdbb2", "#a89984", "#7c6f64", "#fe8019", "#8ec07c"),
        False: _p("#f2e5bc", "#fbf1c7", "#ebdbb2", "#d5c4a1", "#3c3836", "#7c6f64", "#a89984", "#af3a03", "#427b58"),
    }),
    "nord": ("Nord", {
        True: _p("#2e3440", "#3b4252", "#434c5e", "#4c566a", "#eceff4", "#d8dee9", "#7b88a1", "#88c0d0", "#b48ead"),
        False: _p("#e5e9f0", "#eceff4", "#d8dee9", "#cbd2de", "#2e3440", "#4c566a", "#7b88a1", "#5e81ac", "#b48ead"),
    }),
    "rosepine": ("Rosé Pine", {
        True: _p("#191724", "#1f1d2e", "#26233a", "#403d52", "#e0def4", "#908caa", "#6e6a86", "#c4a7e7", "#ebbcba"),
        False: _p("#faf4ed", "#fffaf3", "#f2e9e1", "#dfdad9", "#575279", "#797593", "#9893a5", "#907aa9", "#d7827e"),
    }),
    "tokyonight": ("Tokyo Night", {
        True: _p("#16161e", "#1a1b26", "#292e42", "#414868", "#c0caf5", "#a9b1d6", "#565f89", "#7aa2f7", "#bb9af7"),
        False: _p("#d0d5e3", "#e1e2e7", "#c4c8da", "#b6bfe2", "#3760bf", "#6172b0", "#848cb5", "#2e7de9", "#9854f1"),
    }),
    "everforest": ("Everforest", {
        True: _p("#232a2e", "#2d353b", "#343f44", "#475258", "#d3c6aa", "#9da9a0", "#859289", "#a7c080", "#83c092"),
        False: _p("#efebd4", "#fdf6e3", "#f4f0d9", "#e6e2cc", "#5c6a72", "#829181", "#939f91", "#8da101", "#35a77c"),
    }),
    "solarized": ("Solarized", {
        True: _p("#00212b", "#002b36", "#073642", "#0e4351", "#93a1a1", "#839496", "#586e75", "#268bd2", "#2aa198"),
        False: _p("#eee8d5", "#fdf6e3", "#e7e0cb", "#ddd6c1", "#586e75", "#657b83", "#93a1a1", "#268bd2", "#2aa198"),
    }),
}


def _mix(a: str, b: str, t: float) -> str:
    x, y = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(round(i + (j - i) * t) for i, j in zip(x, y))


def _lum(h: str) -> float:
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(h)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _readable_on(color: str, dark_choice: str) -> str:
    """White, or a very dark shade of the scheme, whichever reads better on `color`."""
    dark = _mix(dark_choice, "#000000", 0.55)
    return "#ffffff" if contrast("#ffffff", color) >= contrast(dark, color) else dark


def _usable_accent(acc: str, window: str, dark: bool) -> str:
    """The accent, deepened (light schemes) or lightened (dark ones) just
    enough for button text on it to read well (4.5:1)."""
    toward = "#ffffff" if dark else "#000000"
    out = acc
    for i in range(1, 11):
        if contrast(_readable_on(out, window), out) >= 4.5:
            break
        out = _mix(acc, toward, i * 0.06)
    return out


def preset_accent(preset: str, dark: bool) -> str:
    """The palette's own accent, as six hex digits (like a seed)."""
    return PRESETS[preset][1][dark]["accent"].lstrip("#")


def apply_preset(p: dict, preset: str, dark: bool, accent: str = "") -> dict:
    """The generated palette `p` with a scheme's surfaces, text and accent.
    `accent` (#hex) replaces the scheme's own accent when given."""
    c = PRESETS[preset][1][dark]
    acc = _usable_accent(accent or c["accent"], c["window"], dark)
    on_acc = _readable_on(acc, c["window"])
    q = dict(p)
    q.update({
        "SURFACE_DIM": c["window"],
        "SURFACE_CONTAINER_LOWEST": _mix(c["window"], "#000000" if dark else "#ffffff", 0.25),
        "SURFACE_CONTAINER_LOW": _mix(c["window"], c["card"], 0.5),
        "SURFACE_CONTAINER": c["card"],
        "SURFACE_CONTAINER_HIGH": c["inner"],
        "SURFACE_CONTAINER_HIGHEST": c["highest"],
        "SURFACE_BRIGHT": _mix(c["highest"], c["text"], 0.12),
        "PRIMARY": acc,
        "PRIMARY_HOVER": _mix(acc, "#ffffff" if dark else "#000000", 0.15),
        "ON_PRIMARY": on_acc,
        "PRIMARY_CONTAINER": _mix(c["card"], acc, 0.32 if dark else 0.25),
        "ON_PRIMARY_CONTAINER": c["text"],
        "SECONDARY_CONTAINER": _mix(c["highest"], acc, 0.22),
        "SECONDARY_CONTAINER_HOVER": _mix(c["highest"], acc, 0.32),
        "ON_SECONDARY_CONTAINER": c["text"],
        "TERTIARY": c["accent2"],
        "TERTIARY_CONTAINER": _mix(c["card"], c["accent2"], 0.28 if dark else 0.22),
        "ON_TERTIARY_CONTAINER": c["text"],
        "ON_SURFACE": c["text"],
        "ON_SURFACE_VARIANT": c["dim"],
        "OUTLINE": c["outline"],
        "OUTLINE_VARIANT": _mix(c["highest"], c["outline"], 0.35),
        "INVERSE_SURFACE": c["text"],
        "INVERSE_ON_SURFACE": c["window"],
        "INVERSE_PRIMARY": _mix(acc, c["window"], 0.35),
    })
    return q
