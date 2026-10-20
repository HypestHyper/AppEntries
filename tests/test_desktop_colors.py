from app_entries import desktop_colors as dc
from app_entries import theme


def env_for(tmp_path):
    return {"HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "cfg")}


def test_colours_in_every_form():
    assert dc.parse_color("#abc") == "#aabbcc"
    assert dc.parse_color("#8AB4F8ff") == "#8ab4f8"
    assert dc.parse_color("rgb(255, 128, 0)") == "#ff8000"
    assert dc.parse_color("rgba(100%, 0%, 50%, 0.5)") == "#ff0080"
    assert dc.parse_color("@base", {"base": "@deep", "deep": "#123456"}) == "#123456"
    assert dc.parse_color("@loop", {"loop": "@loop"}) is None
    assert dc.parse_color("mix(@a, @b, 0.5)") is None


def test_matugen_style_gtk_css_with_imports(tmp_path):
    env = env_for(tmp_path)
    gtk4 = tmp_path / "cfg" / "gtk-4.0"
    gtk4.mkdir(parents=True)
    # What Noctalia / matugen templates typically write: an import of generated colours.
    (gtk4 / "colors.css").write_text("/* generated */\n@define-color accent_bg_color #8ab4f8;\n"
                                     "@define-color accent_color @accent_bg_color;\n")
    (gtk4 / "gtk.css").write_text('@import url("colors.css");\nwindow { color: red; }\n')
    color, path, watch = dc.gtk_accent(env)
    assert color == "#8ab4f8" and path.endswith("gtk-4.0/gtk.css")
    assert any(p.endswith("colors.css") for p in watch)

    # Later definitions win, and gtk-3.0 is used when gtk-4.0 has nothing.
    (gtk4 / "gtk.css").write_text('@import "colors.css";\n@define-color accent_color #ff0000;\n')
    assert dc.gtk_accent(env)[0] == "#ff0000"
    (gtk4 / "gtk.css").write_text("")
    gtk3 = tmp_path / "cfg" / "gtk-3.0"
    gtk3.mkdir()
    (gtk3 / "gtk.css").write_text("@define-color theme_selected_bg_color rgb(10, 20, 30);")
    assert dc.gtk_accent(env)[0] == "#0a141e"


def test_kde_and_portal_values(tmp_path):
    env = env_for(tmp_path)
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "kdeglobals").write_text("[General]\nAccentColor=61,174,233\n")
    assert dc.kde_accent(env) == "#3daee9"
    assert dc.portal_color((0.2, 0.4, 0.6)) == "#336699"
    assert dc.portal_color((-1.0, -1.0, -1.0)) is None   # the desktop has no accent set
    assert dc.prefers_portal(["GNOME"]) and dc.prefers_portal(["KDE"]) and not dc.prefers_portal(["Hyprland"])


def test_palettes_are_readable_and_keep_a_chosen_accent():
    for key in theme.PRESETS:
        for dark in (True, False):
            p = theme.palette("", dark, key)
            assert theme.contrast(p["ON_SURFACE"], p["SURFACE_CONTAINER"]) >= 4.5, (key, dark)
            assert theme.contrast(p["ON_PRIMARY"], p["PRIMARY"]) >= 4.5, (key, dark)
            assert p["SURFACE_DIM"] == theme.PRESETS[key][1][dark]["window"]
    mint = theme.palette("53dbb0", True, "nord")
    assert mint["SURFACE_CONTAINER"] == "#3b4252" and mint["PRIMARY"].startswith("#")
    assert theme.palette("", True, "nord")["PRIMARY"] != mint["PRIMARY"]
    # Without a palette nothing changes.
    assert theme.palette("53dbb0", True, "") == theme.palette("53dbb0", True)
