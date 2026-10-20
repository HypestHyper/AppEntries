import pytest

from conftest import entry
from app_entries import defaults as df
from app_entries import desktop_entries as de
from app_entries import overrides as ov

BROWSER = df.CATEGORIES[0]
PDF = next(c for c in df.CATEGORIES if c.key == "pdf")


@pytest.fixture
def env(xdg):
    xdg.write(xdg.sys_b, "firefox.desktop", entry("Firefox", "firefox %u",
                                                  MimeType="text/html;x-scheme-handler/http;x-scheme-handler/https;"))
    xdg.write(xdg.sys_b, "chromium.desktop", entry("Chromium", "chromium %U",
                                                   MimeType="text/html;x-scheme-handler/http;x-scheme-handler/https;"
                                                            "application/pdf;"))
    xdg.write(xdg.sys_b, "evince.desktop", entry("Evince", "evince %U", MimeType="application/pdf;"))
    xdg.env["XDG_CURRENT_DESKTOP"] = "GNOME"
    xdg.env["XDG_CONFIG_DIRS"] = str(xdg.tmp / "etc")
    xdg.config = xdg.tmp / "home" / ".config"
    return xdg


def apps(env):
    return {a.id: a for a in de.scan(env.env)}


def test_candidates_put_apps_that_open_more_types_first(env):
    a = apps(env)
    assert [x.id for x in df.candidates(BROWSER, list(a.values()))] == ["chromium.desktop", "firefox.desktop"]
    assert [x.id for x in df.candidates(PDF, list(a.values()))] == ["chromium.desktop", "evince.desktop"]


def test_set_reset_and_undo(env):
    a = apps(env)
    changes, notes = df.plan_set(BROWSER, a["firefox.desktop"], env.env)
    assert not notes
    ov.apply_all(changes)
    text = (env.config / "mimeapps.list").read_text()
    assert "[Default Applications]" in text and "x-scheme-handler/https=firefox.desktop;" in text
    assert "[Added Associations]" in text
    s = df.state(BROWSER, list(a.values()), env.env)
    assert s.app_id == "firefox.desktop" and s.chosen_by_you and not s.mixed

    reset = df.plan_reset(BROWSER, env.env)
    ov.apply_all(reset)
    s = df.state(BROWSER, list(a.values()), env.env)
    assert s.app_id == "" and not s.chosen_by_you
    ov.undo_all(reset)       # undo in order: the reset, then the choice
    ov.undo_all(changes)
    assert not (env.config / "mimeapps.list").exists()


def test_desktop_specific_files_and_removed_associations_are_followed(env):
    env.config.mkdir(parents=True)
    # A system default, overridden by the user's GNOME-specific file, which also
    # removed Firefox from PDFs.
    (env.tmp / "etc").mkdir()
    (env.tmp / "etc" / "mimeapps.list").write_text("[Default Applications]\ntext/html=chromium.desktop;\n")
    (env.config / "gnome-mimeapps.list").write_text(
        "[Default Applications]\ntext/html=evince.desktop;missing.desktop;\n"
        "[Removed Associations]\napplication/pdf=chromium.desktop;\n")
    installed = set(apps(env))
    assert df.default_for("text/html", installed, env.env)[0] == "evince.desktop"
    (env.config / "gnome-mimeapps.list").write_text("[Default Applications]\ntext/html=missing.desktop;\n")
    assert df.default_for("text/html", installed, env.env)[0] == "chromium.desktop"  # skips what's not installed

    # Setting a default also updates the desktop-specific file that would win.
    (env.config / "gnome-mimeapps.list").write_text(
        "[Default Applications]\ntext/html=chromium.desktop;\n[Removed Associations]\ntext/html=firefox.desktop;\n")
    ov.apply_all(df.plan_set(BROWSER, apps(env)["firefox.desktop"], env.env)[0])
    assert df.default_for("text/html", installed, env.env)[0] == "firefox.desktop"
    assert "firefox" not in (env.config / "gnome-mimeapps.list").read_text().split("[Removed Associations]")[-1]


def test_xfce_kde_and_the_browser_variable(env):
    helpers = env.tmp / "usr" / "xfce4" / "helpers"
    helpers.mkdir(parents=True)
    (helpers / "firefox.desktop").write_text("[Desktop Entry]\nX-XFCE-Category=WebBrowser\nX-XFCE-Binaries=firefox;\n")
    env.env["XDG_DATA_DIRS"] += ":" + str(env.tmp / "usr")
    env.env["XDG_CURRENT_DESKTOP"] = "XFCE"
    a = apps(env)
    changes, notes = df.plan_set(BROWSER, a["firefox.desktop"], env.env)
    ov.apply_all(changes)
    assert "WebBrowser=firefox" in (env.config / "xfce4" / "helpers.rc").read_text()
    _c, notes = df.plan_set(BROWSER, a["chromium.desktop"], env.env)
    assert any("Xfce" in n for n in notes)  # no helper for Chromium: says so

    env.env["XDG_CURRENT_DESKTOP"] = "KDE"
    (env.config / "kdeglobals").write_text("[General]\nBrowserApplication=chromium.desktop\n")
    env.env["BROWSER"] = "librewolf"
    changes, notes = df.plan_set(BROWSER, a["firefox.desktop"], env.env)
    ov.apply_all(changes)
    assert "BrowserApplication=firefox.desktop" in (env.config / "kdeglobals").read_text()
    assert any("BROWSER" in n for n in notes)
