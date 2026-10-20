import os
import xml.etree.ElementTree as ET

import pytest

from app_entries import icon_library as lib
from app_entries import symbols

STROKE = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
          'stroke="currentColor" stroke-width="2"><path d="M4 17l6-6-6-6"/><path d="M12 19h8"/></svg>')
MULTI = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 48"><defs><linearGradient id="g">'
         '<stop offset="0" stop-color="#ff5f6d"/></linearGradient></defs>'
         '<rect width="64" height="48" fill="url(#g)"/><circle cx="24" cy="24" r="10" style="fill:#2b2d42"/>'
         '<script>alert(1)</script></svg>')
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
       b"\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


@pytest.fixture
def env(tmp_path):
    return {"HOME": str(tmp_path / "home"), "XDG_DATA_DIRS": str(tmp_path / "usr")}


def write(tmp_path, name, data):
    p = tmp_path / name
    p.write_bytes(data if isinstance(data, bytes) else data.encode())
    return str(p)


def test_add_file_copies_into_library_once(tmp_path, env):
    src = write(tmp_path, "my icon.svg", STROKE)
    copy = lib.add_file(src, env)
    assert lib.in_library(copy, env) and os.path.basename(copy) == "my-icon.svg"
    assert lib.add_file(src, env) == copy           # same file again: no duplicate
    assert lib.add_file(copy, env) == copy
    os.unlink(src)
    assert os.path.exists(copy)                     # safe even when the original goes
    assert lib.list_icons(env) == [copy]
    lib.remove(copy, env)
    assert lib.list_icons(env) == []


def test_rejects_non_images(tmp_path, env):
    with pytest.raises(lib.IconError):
        lib.add_file(write(tmp_path, "x.svg", "<html></html>"), env)
    with pytest.raises(lib.IconError):
        lib.add_file(write(tmp_path, "x.png", b"not a png"), env)
    assert lib.check(PNG) == "png"


def test_download_checks_scheme_size_and_type(tmp_path, env):
    class Resp:
        def __init__(self, data): self.data = data
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, n): return self.data[:n]

    path = lib.download("https://example.org/icons/term.svg", env, opener=lambda req, timeout: Resp(STROKE.encode()))
    assert path.endswith("term.svg") and lib.in_library(path, env)
    with pytest.raises(lib.IconError):
        lib.download("file:///etc/passwd", env)
    with pytest.raises(lib.IconError):
        lib.download("https://x/big.svg", env, opener=lambda r, timeout: Resp(b"x" * (lib.MAX_DOWNLOAD + 5)))
    with pytest.raises(lib.IconError):
        lib.download("https://x/page", env, opener=lambda r, timeout: Resp(b"<html/>"))


def test_file_icons_recolour_border_and_stay_plain(tmp_path):
    stroke = write(tmp_path, "s.svg", STROKE)
    multi = write(tmp_path, "m.svg", MULTI)
    svg = symbols.render(symbols.IconChoice(source="file", path=stroke, shape="none", color="#e5484d",
                                            border=True, border_width=3))
    ET.fromstring(svg)
    assert 'stroke="#e5484d"' in svg and "currentColor" not in svg
    kept = symbols.render(symbols.IconChoice(source="file", path=multi, shape="rounded", recolor=False))
    assert "#ff5f6d" in kept and "<script" not in kept and "alert" not in kept
    assert 'id="ae' in kept and "url(#ae" in kept          # ids made unique
    painted = symbols.render(symbols.IconChoice(source="file", path=multi, shape="none", color="#123456"))
    shapes = [el for el in ET.fromstring(painted).iter() if el.tag.split("}")[-1] in ("rect", "circle")]
    assert shapes and all(el.get("fill") == "#123456" for el in shapes)   # the unused gradient doesn't matter


def test_png_icons_are_embedded(tmp_path):
    png = write(tmp_path, "p.png", PNG)
    svg = symbols.render(symbols.IconChoice(source="file", path=png, shape="circle"))
    assert "data:image/png;base64," in svg


def test_material_borders():
    plain = symbols.render(symbols.IconChoice("settings", shape="none"))
    outer = symbols.render(symbols.IconChoice("settings", shape="none", border=True))
    inner = symbols.render(symbols.IconChoice("settings", shape="none", border=True, border_inner=True))
    assert plain.count("<path") == 1 and outer.count("<path") == 2
    assert len(inner) > len(outer)                      # holes outlined too
    tile = symbols.render(symbols.IconChoice("home", shape="circle", border=True, border_color="black"))
    # The border is the full circle, with the tile on top, smaller by the border's width,
    # so the tile's colour never shows around the outside.
    assert '<circle cx="480" cy="480" r="456" fill="#1b1b1f"/>' in tile
    assert 'r="%g" fill="url(#bg)"' % (456 - 24) in tile


def test_outer_edges_drops_holes():
    d = "M0 0L10 0L10 10L0 10ZM3 3L3 7L7 7L7 3Z"
    assert symbols.outer_edges(d) == "M0 0L10 0L10 10L0 10Z"


def test_one_colour_detection(tmp_path):
    assert lib.is_one_colour(write(tmp_path, "s.svg", STROKE))
    assert not lib.is_one_colour(write(tmp_path, "m.svg", MULTI))
    assert not lib.is_one_colour(write(tmp_path, "p.png", PNG))


YTM = ('<svg role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><title>YouTube Music</title>'
       '<path d="M12 0C5.376 0 0 5.376 0 12s5.376 12 12 12 12-5.376 12-12S18.624 0 12 0zm0 19.104c-3.924 0-7.104'
       '-3.18-7.104-7.104S8.076 4.896 12 4.896s7.104 3.18 7.104 7.104-3.18 7.104-7.104 7.104zM9.684 15.54V8.46L'
       '15.816 12l-6.132 3.54z"/></svg>')
NESTED = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect width="24" height="24" fill="none"/>'
          '<g fill="none" stroke="currentColor" stroke-width="2"><path d="m8 9l13-2"/></g></svg>')


def test_subpaths_handle_relative_commands():
    subs = lib.subpaths("M10 10h4v4h-4z m1 1 h2 v2 h-2z")
    assert len(subs) == 2
    assert subs[1][0] == ("M", (11.0, 11.0))
    assert subs[0][2] == ("L", (14.0, 14.0))


def test_outer_only_keeps_the_outline_and_drops_holes():
    one = lib.outer_only("M0 0h10v10h-10z M3 3v4h4v-4z")
    assert len(lib.subpaths(one)) == 1


def test_borders_follow_inherited_paint_and_skip_invisible_shapes(tmp_path):
    path = write(tmp_path, "n.svg", NESTED)
    svg = symbols.render(symbols.IconChoice(source="file", path=path, shape="none", color="#ff8fb1",
                                            border=True, border_width=3, border_color="#6aa6ff"))
    root = ET.fromstring(svg)
    ns = "{http://www.w3.org/2000/svg}"
    rects = [r for r in root.iter(ns + "rect")]
    assert all(r.get("stroke") in ("none", None) and r.get("fill") in ("none", None) for r in rects)
    widths = [float(p.get("stroke-width")) for p in root.iter(ns + "path") if p.get("stroke") == "#6aa6ff"]
    assert widths and min(widths) > 2               # wider than the line it outlines


def test_inner_edges_switch_for_file_icons(tmp_path):
    path = write(tmp_path, "y.svg", YTM)
    outer = symbols.render(symbols.IconChoice(source="file", path=path, shape="none", border=True))
    inner = symbols.render(symbols.IconChoice(source="file", path=path, shape="none", border=True,
                                              border_inner=True))
    assert len(inner) > len(outer)


def test_paste_svg(tmp_path, env):
    assert lib.title_of(YTM) == "YouTube Music"
    path = lib.add_text(YTM, "YouTube Music", env)
    assert os.path.basename(path) == "YouTube-Music.svg" and lib.in_library(path, env)
    with pytest.raises(lib.IconError):
        lib.add_text("not svg", "x", env)
    with pytest.raises(lib.IconError):
        lib.check_text("   ")


DISCORD_D = ("M20.317 4.3698a19.7913 19.7913 0 00-4.8851-1.5152.0741.0741 0 00-.0785.0371c-.211.3753-.4447.8648-"
             ".6083 1.2495-1.8447-.2762-3.68-.2762-5.4868 0-.1636-.3933-.4058-.8742-.6177-1.2495a.077.077 0 00-"
             ".0785-.037 19.7363 19.7363 0 00-4.8852 1.515.0699.0699 0 00-.0321.0277C.5334 9.0458-.319 13.5799."
             "0992 18.0578a.0824.0824 0 00.0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929 3.0294a.0777.0777 0 00."
             "0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9942a.076.076 0 00-.0416-.1057c-.6528-.2476-1.2743-.5495"
             "-1.8722-.8923a.077.077 0 01-.0076-.1277zM8.02 15.3312c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332"
             ".9555-2.4189 2.157-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.9555 2.4189-2.1569 2.4189z")


def test_arc_flags_written_together():
    subs, ok = lib._parse(DISCORD_D)
    assert ok and len(subs) == 2
    arc = [seg for seg in subs[0] if seg[0] == "A"][0]
    assert arc[1][:5] == (19.7913, 19.7913, 0.0, 0.0, 0.0)
    assert abs(arc[1][5] - (20.317 - 4.8851)) < 1e-9          # end point read right after the flags
    assert len(lib.subpaths(lib.outer_only(DISCORD_D))) == 1   # the eye is a hole: dropped


def test_unreadable_path_is_outlined_whole():
    assert lib.outer_only("M0 0h10v10h-10z M3 3 X 7") == "M0 0h10v10h-10z M3 3 X 7"


def test_discord_border_keeps_the_logo(tmp_path):
    svg = ('<svg role="img" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><title>Discord</title>'
           '<path d="%s"/></svg>' % DISCORD_D)
    path = write(tmp_path, "d.svg", svg)
    out = symbols.render(symbols.IconChoice(source="file", path=path, shape="none", border=True))
    border_paths = [p for p in ET.fromstring(out).iter("{http://www.w3.org/2000/svg}path") if p.get("stroke") not in (None, "none")]
    assert border_paths and len(border_paths[0].get("d")) > 100


def test_outer_edges_by_enclosure_not_winding():
    # The gear's centre dot winds the same way as its hole but is filled:
    # only the outline that nothing else encloses counts as outer.
    d = symbols.icons()["settings"][0]
    assert len(lib.subpaths(symbols.outer_edges(d))) == 1
    ring = "M0 0h20v20h-20z M5 5h10v10h-10z M8 8h4v4h-4z"   # outline, hole, island
    assert lib.outer_only(ring) == "M0 0L20 0L20 20L0 20Z"
