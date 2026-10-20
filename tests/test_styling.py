from conftest import entry
from app_entries import desktop_entries as de
from app_entries import launchers as ln
from app_entries import overrides as ov
from app_entries import symbols


def test_icons_carry_their_settings():
    c = symbols.IconChoice("gamepad", "filled", "circle", "#ff5500", border=True, gradient="strong", scale=70)
    back = symbols.choice_from_svg(symbols.render(c))
    assert back == c
    assert symbols.choice_from_svg("<svg/>") is None
    assert symbols.choice_from_svg("<!-- app-entries-choice bm90IGpzb24= -->") is None


def test_shading_and_symbol_size():
    flat = symbols.render(symbols.IconChoice(gradient="flat"))
    assert "linearGradient" not in flat and 'fill="#2e9e7e"' in flat
    soft = symbols.render(symbols.IconChoice())
    strong = symbols.render(symbols.IconChoice(gradient="strong"))
    assert "linearGradient" in soft and "linearGradient" in strong and soft != strong
    assert 'translate(192 192) scale(0.6)' in soft  # the default is unchanged
    assert 'translate(96 96) scale(0.8)' in symbols.render(symbols.IconChoice(scale=80))
    assert 'scale(0.4)' in symbols.render(symbols.IconChoice(scale=10))  # clamped


def test_restyle_keeps_the_symbol():
    a = symbols.IconChoice("terminal", source="material")
    style = symbols.IconChoice("ignored", "filled", "circle", "#123456", border=True, gradient="flat")
    out = symbols.restyle(a, style)
    assert out.name == "terminal" and out.style == "filled" and out.shape == "circle"
    assert out.color == "#123456" and out.border and out.gradient == "flat"


def test_plan_restyle_updates_launchers_and_edited_icons_and_skips_others(xdg):
    did, changes = ln.plan_save(ln.Spec(name="Tool", program="/bin/true",
                                        icon=symbols.IconChoice("build", color="#2e9e7e")), env=xdg.env)
    ov.apply_all(changes)
    # A system app whose icon was drawn in the Edit window.
    icon = xdg.tmp / "home" / ".local" / "share" / "icons" / "edited.svg"
    icon.write_text(symbols.render(symbols.IconChoice("star")))
    xdg.write(xdg.sys_b, "sys.desktop", entry("Sys"))
    xdg.write(xdg.user, "sys.desktop", entry("Sys", Icon=str(icon)))
    xdg.write(xdg.sys_b, "plain.desktop", entry("Plain", Icon="firefox"))
    apps = {a.id: a for a in de.scan(xdg.env)}

    style = symbols.IconChoice(shape="circle", color="#aa0000", gradient="strong")
    changes, skipped = ln.plan_restyle([apps[did], apps["sys.desktop"], apps["plain.desktop"]], style)
    assert [a.id for a in skipped] == ["plain.desktop"]
    ov.apply_all(changes)

    tool = symbols.choice_from_svg(open(ln.icon_path(did, xdg.env)).read())
    assert tool.name == "build" and tool.color == "#aa0000" and tool.shape == "circle"
    spec = ln.read_spec((xdg.user / did).read_text())
    assert spec.icon.color == "#aa0000" and spec.icon.gradient == "strong"  # the form shows the new look
    star = symbols.choice_from_svg(icon.read_text())
    assert star.name == "star" and star.color == "#aa0000"
