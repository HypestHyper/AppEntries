"""How things move: Material 3 Expressive motion, in one place.

M3 Expressive moves things with springs. GTK has no springs in CSS, so this
uses the curve-and-duration pairs Material publishes for exactly that case.
Two kinds, three speeds each:

- spatial: position, size, rotation, corners. Overshoots a little and settles.
- effects: colour and opacity. Never overshoots.

Small parts (buttons, switches) move fast, panels at the default speed,
whole-window changes slowly.

Rules, checked by tests/test_motion.py:
- every transition in the stylesheet takes its timing from here;
- colour and opacity only ever use effects timings;
- nothing animates a size (width, height, margin, padding), so the window
  is never laid out again frame by frame;
- Python only switches style classes; GTK does the animating, so a change
  takes effect at once even with animations off or cut short.

No GTK here, so the tests can read it anywhere."""

# name: (cubic-bezier, milliseconds), from the M3 Expressive spring tokens.
SPATIAL = {
    "fast": ((0.42, 1.67, 0.21, 0.90), 350),
    "default": ((0.38, 1.21, 0.22, 1.00), 500),
    "slow": ((0.39, 1.29, 0.35, 0.98), 650),
}
EFFECTS = {
    "fast": ((0.31, 0.94, 0.34, 1.00), 150),
    "default": ((0.34, 0.80, 0.34, 1.00), 200),
    "slow": ((0.34, 0.88, 0.34, 1.00), 300),
}

# What each kind may animate. Anything else (sizes above all) isn't animated.
SPATIAL_PROPS = {"transform", "border-radius"}
EFFECT_PROPS = {"opacity", "color", "background-color", "border-color", "box-shadow", "outline-color"}

# GTK's own slides and crossfades (revealers, stacks) have a fixed easing
# with no overshoot, so they take effects timings.
SLIDE = EFFECTS["slow"][1]
FADE = EFFECTS["default"][1]

# A style class that stops transitions, for a row being reused for another
# app while scrolling, or a part about to come in. Loaded with a higher
# priority than the stylesheet, so it always wins.
STILL = ".m-still, .m-still *, .m-from, .m-from * { transition: none; }"


def timing(kind: str, speed: str) -> str:
    """CSS for one timing, e.g. "350ms cubic-bezier(0.42, 1.67, 0.21, 0.9)"."""
    (x1, y1, x2, y2), ms = (SPATIAL if kind == "spatial" else EFFECTS)[speed]
    return f"{ms}ms cubic-bezier({x1}, {y1}, {x2}, {y2})"


def tokens() -> dict:
    """The stylesheet's placeholders: SP_FAST, SP_DEFAULT, SP_SLOW,
    FX_FAST, FX_DEFAULT, FX_SLOW."""
    out = {}
    for kind, short in (("spatial", "SP"), ("effects", "FX")):
        for speed in ("fast", "default", "slow"):
            out[f"{short}_{speed.upper()}"] = timing(kind, speed)
    return out
