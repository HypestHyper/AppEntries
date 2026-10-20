from app_entries import icon_lookup


def _env(tmp_path):
    icon_lookup.clear_cache()
    home = tmp_path / "home"
    return {"HOME": str(home), "XDG_DATA_DIRS": str(tmp_path / "usr")}, home / ".local" / "share", tmp_path / "usr"


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")
    return str(path)


def test_finds_user_hicolor_icon_even_with_a_stale_cache(tmp_path):
    env, user, _usr = _env(tmp_path)
    touch(user / "icons" / "hicolor" / "icon-theme.cache")
    want = touch(user / "icons" / "hicolor" / "32x32" / "apps" / "steam_icon_440.png")
    assert icon_lookup.find("steam_icon_440", env=env) == want


def test_prefers_current_theme_then_hicolor_then_others(tmp_path):
    env, _user, usr = _env(tmp_path)
    papirus = touch(usr / "icons" / "Papirus" / "48x48" / "apps" / "imv.svg")
    assert icon_lookup.find("imv", env=env) == papirus
    icon_lookup.clear_cache()
    hicolor = touch(usr / "icons" / "hicolor" / "scalable" / "apps" / "imv.svg")
    assert icon_lookup.find("imv", env=env) == hicolor
    icon_lookup.clear_cache()
    assert icon_lookup.find("imv", ("Papirus",), env=env) == papirus


def test_largest_size_first_and_pixmaps_last(tmp_path):
    env, _user, usr = _env(tmp_path)
    touch(usr / "icons" / "hicolor" / "16x16" / "apps" / "tool.png")
    big = touch(usr / "icons" / "hicolor" / "128x128" / "apps" / "tool.png")
    assert icon_lookup.find("tool", env=env) == big
    pix = touch(usr / "pixmaps" / "auto-cpufreq.png")
    assert icon_lookup.find("auto-cpufreq", env=env) == pix


def test_extension_and_absolute_paths(tmp_path):
    env, _user, usr = _env(tmp_path)
    pix = touch(usr / "pixmaps" / "old.xpm")
    assert icon_lookup.find("old.xpm", env=env) == pix
    assert icon_lookup.find(pix, env=env) == pix
    assert icon_lookup.find(str(tmp_path / "missing.png"), env=env) is None
    assert icon_lookup.find("nothing-here", env=env) is None
