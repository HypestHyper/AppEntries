"""The motion rules in app_entries/ui/motion.py, checked so later changes
can't quietly break them."""
import ast
import pathlib
import re
import string

import pytest

from app_entries.ui import motion

UI = pathlib.Path(__file__).resolve().parent.parent / "app_entries" / "ui"


def _template():
    """The stylesheet as written in style.py, read without importing GTK."""
    for node in ast.walk(ast.parse((UI / "style.py").read_text())):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "CSS" for t in node.targets):
            return node.value.value
    raise AssertionError("no CSS in style.py")


def _filled():
    """The stylesheet with the real timings and any colour."""
    names = {f for _t, f, _s, _c in string.Formatter().parse(_template()) if f}
    values = {n: "#123456" for n in names}
    values.update(FONT="sans-serif", ICON="sans-serif", **motion.tokens())
    return _template().format(**values)


def _split(value):
    """Split a transition list on the commas between items, not in brackets."""
    out, depth, cur = [], 0, ""
    for ch in value:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return out + [cur.strip()] if cur.strip() else out


def _transitions():
    css = re.sub(r"/\*.*?\*/", "", _filled(), flags=re.DOTALL)
    for m in re.finditer(r"(?<![-\w])transition:\s*([^;}]+)", css):
        if m.group(1).strip() == "none":
            continue
        for item in _split(m.group(1)):
            prop, timing = item.split(None, 1)
            yield prop, timing.strip()


def test_effects_never_overshoot_and_spatial_does():
    for (_x1, y1, _x2, y2), ms in motion.EFFECTS.values():
        assert 0 <= y1 <= 1 and 0 <= y2 <= 1 and ms <= 300
    for (_x1, y1, _x2, _y2), _ms in motion.SPATIAL.values():
        assert y1 > 1     # the bounce


def test_every_transition_uses_a_motion_timing():
    assert "cubic-bezier" not in _template() and not re.search(r"transition:[^;]*\d+m?s\b", _template())
    spatial = {motion.timing("spatial", s) for s in motion.SPATIAL}
    effects = {motion.timing("effects", s) for s in motion.EFFECTS}
    seen = 0
    for prop, timing in _transitions():
        seen += 1
        if prop in motion.SPATIAL_PROPS:
            assert timing in spatial, (prop, timing)
        else:
            # Colour and opacity never overshoot; sizes aren't animated at all.
            assert prop in motion.EFFECT_PROPS, f"{prop} can't be animated (it would lay the window out each frame)"
            assert timing in effects, (prop, timing)
    assert seen > 20


def test_gtk_slides_and_crossfades_take_motion_timings():
    """Every revealer, and every stack that animates, gets its duration from
    motion, so Reduce motion and the timings stay in one place."""
    bad = []
    for path in UI.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr == "set_transition_duration":
                bad.append(f"{path.name}:{node.lineno}")    # set it where the widget is made
            if node.func.attr not in ("Revealer", "Stack"):
                continue
            kw = {k.arg: k.value for k in node.keywords}
            if node.func.attr == "Stack" and "transition_type" not in kw:
                continue
            d = kw.get("transition_duration")
            if not (isinstance(d, ast.Attribute) and getattr(d.value, "id", "") == "motion"):
                bad.append(f"{path.name}:{node.lineno}")
    assert bad == []


def test_parts_coming_in_and_still_rows_have_no_transition():
    assert ".m-from" in motion.STILL and ".m-still" in motion.STILL and "transition: none" in motion.STILL
    css = _filled()
    # Each place parts come in from has somewhere to go.
    for cls in ("m-float", "m-page"):
        assert re.search(r"\." + cls + r" \{[^}]*transition:", css), cls


def test_stylesheet_loads_in_gtk_without_errors():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk
    except (ValueError, ImportError):
        pytest.skip("GTK 4 isn't installed")
    from app_entries import theme
    from app_entries.ui import style
    errors = []
    for dark in (True, False):
        provider = Gtk.CssProvider()
        provider.connect("parsing-error", lambda _p, section, e: errors.append(f"{section.to_string()}: {e.message}"))
        style.load_css(provider, style.stylesheet(theme.palette(theme.DEFAULT_SEED, dark, ""), 0.9))
        style.load_css(provider, style.STILL + style.REDUCE_MOTION)
    assert errors == []
