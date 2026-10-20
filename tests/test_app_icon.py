import os

from app_entries import APP_ID, app_icon, theme

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIPPED = os.path.join(ROOT, "data", "icons", "hicolor", "scalable", "apps", APP_ID + ".svg")


def test_shipped_icon_matches_render():
    with open(SHIPPED, encoding="utf-8") as f:
        assert f.read() == app_icon.render(marker=False)


def test_render_uses_accent_and_marker():
    svg = app_icon.render("6aa6ff")
    for c in app_icon.colors_for("6aa6ff"):
        assert c in svg
    assert app_icon.MARKER in svg
    assert app_icon.MARKER not in app_icon.render(marker=False)


def _env(monkeypatch, tmp_path, installed):
    data = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setenv("XDG_DATA_DIRS", str(tmp_path / "sys"))
    if installed:
        (data / "applications").mkdir(parents=True)
        (data / "applications" / (APP_ID + ".desktop")).write_text("[Desktop Entry]\n")
    return data / "icons" / "hicolor" / "scalable" / "apps" / (APP_ID + ".svg")


def test_update_writes_icon_when_installed(monkeypatch, tmp_path):
    target = _env(monkeypatch, tmp_path, installed=True)
    app_icon.update("ff8fb1")
    assert target.read_text() == app_icon.render("ff8fb1")
    app_icon.update("ff8fb1", themed=False)
    assert target.read_text() == app_icon.render(theme.DEFAULT_SEED)


def test_update_skips_source_checkout(monkeypatch, tmp_path):
    target = _env(monkeypatch, tmp_path, installed=False)
    app_icon.update("ff8fb1")
    assert not target.exists()
