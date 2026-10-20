import os

from conftest import entry
from app_entries import appimages, launchers, trash, webapps
from app_entries import desktop_entries as de
from app_entries import overrides as ov


def test_trash_move_and_restore(xdg):
    f = xdg.tmp / "big.AppImage"
    f.write_bytes(b"ELF...")
    t = trash.move(str(f), xdg.env)
    assert not f.exists() and os.path.exists(t.file)
    info = open(t.info).read()
    assert "Path=%s" % f in info and "DeletionDate=" in info
    f2 = xdg.tmp / "big.AppImage"
    f2.write_bytes(b"other")
    t2 = trash.move(str(f2), xdg.env)
    assert t2.file != t.file  # a second file with the same name gets its own
    trash.restore(t2)
    assert f2.read_bytes() == b"other" and not os.path.exists(t2.info)


def test_appimage_removal_finds_every_entry_icon_and_file_type(xdg):
    home_data = xdg.tmp / "home" / ".local" / "share"
    image = xdg.tmp / "home" / "Applications" / "Tool-1.2.AppImage"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\x7fELF" + b"0" * 100)
    kit = "appimagekit_" + "a" * 32
    # What AppImageLauncher / appimaged set up, plus a second launcher someone made.
    xdg.write(xdg.user, kit + "-Tool.desktop", entry("Tool", '"%s" %%U' % image, Icon=kit + "_tool"))
    xdg.write(xdg.user, "tool-mine.desktop", entry("Tool (mine)", "env FOO=1 %s" % image, Icon="shared-icon"))
    xdg.write(xdg.user, "other.desktop", entry("Other", "other", Icon="shared-icon"))
    icon = home_data / "icons" / "hicolor" / "256x256" / "apps" / (kit + "_tool.png")
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"\x89PNG\r\n\x1a\nxx")
    mime = home_data / "mime" / "packages" / (kit + "-tool.xml")
    mime.parent.mkdir(parents=True)
    mime.write_text("<mime-info/>")
    sys_entry = xdg.write(xdg.sys_b, "tool-system.desktop", entry("Tool sys", str(image)))

    app = next(a for a in de.scan(xdg.env) if a.id == kit + "-Tool.desktop")
    assert appimages.appimage_of(app.exec) == str(image)
    r = appimages.plan(app, xdg.env)
    assert sorted(os.path.basename(p) for p in r.entries) == [kit + "-Tool.desktop", "tool-mine.desktop"]
    assert r.icons == [str(icon)]               # shared-icon is used by another app, so it stays
    assert r.others == [str(mime)]
    assert r.blocked == [str(sys_entry)]
    assert appimages.problem(r) is None

    changes = appimages.changes(r, app.id, app.name)
    ov.apply_all(changes)
    trashed = trash.move(r.appimage, xdg.env)
    assert not image.exists() and not icon.exists() and not mime.exists()
    assert (xdg.user / "other.desktop").exists()

    ov.undo_all(changes)  # Undo
    trash.restore(trashed)
    assert image.exists() and icon.read_bytes().startswith(b"\x89PNG") and mime.exists()
    assert (xdg.user / (kit + "-Tool.desktop")).exists()


def test_web_app_addresses_names_and_args():
    assert webapps.normalize("web.whatsapp.com") == "https://web.whatsapp.com"
    assert webapps.name_for("https://mail.proton.me/u/0") == "Mail Proton"
    assert webapps.name_for("www.youtube.com") == "Youtube"
    for bad in ("", "ftp://x.org", "not an address"):
        try:
            webapps.normalize(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    assert webapps.args_for("https://a.b/?x=1&y", "/p q") == "'--app=https://a.b/?x=1&y' '--user-data-dir=/p q'"


def test_web_app_launcher_round_trips(xdg):
    spec = launchers.Spec(name="Mail", program="/usr/bin/chromium",
                          args=webapps.args_for("https://mail.example.com"),
                          web_url="https://mail.example.com", web_browser="chromium", web_profile=False)
    did, changes = launchers.plan_save(spec, env=xdg.env)
    ov.apply_all(changes)
    back = launchers.read_spec((xdg.user / did).read_text())
    assert back.web_url == "https://mail.example.com" and back.web_browser == "chromium"
    d = de.DesktopFile((xdg.user / did).read_text()).group_dict()
    assert d["Exec"] == "/usr/bin/chromium --app=https://mail.example.com"


def test_site_icons_are_ranked():
    page = ('<link rel="icon" href="/fav-16.png" sizes="16x16">'
            '<link rel="apple-touch-icon" href="/touch.png">'
            '<link rel="icon" type="image/svg+xml" href="/logo.svg">')
    c = webapps.icon_candidates("https://x.org/app", page)
    assert c[:3] == ["https://x.org/logo.svg", "https://x.org/touch.png", "https://x.org/fav-16.png"]
    assert c[-1] == "https://x.org/favicon.ico"
    assert webapps.sniff(b"\x89PNG\r\n\x1a\n") == "png" and webapps.sniff(b"<svg/>") == "svg"
    assert webapps.sniff(b"\x00\x00\x01\x00") == "other" and webapps.sniff(b"<html>") is None


def test_only_a_web_apps_own_folder_can_be_deleted(xdg):
    own = xdg.tmp / "home" / ".local" / "share" / "app-entries" / "web-apps" / "mail-abc123"
    own.mkdir(parents=True)
    browser = xdg.tmp / "home" / ".config" / "chromium"
    browser.mkdir(parents=True)
    assert webapps.own_data(webapps.args_for("https://m.x", str(own)), xdg.env) == str(own)
    # Sharing the browser's sign-ins: nothing of the browser's is ever offered.
    assert webapps.own_data(webapps.args_for("https://m.x"), xdg.env) == ""
    assert webapps.own_data(webapps.args_for("https://m.x", str(browser)), xdg.env) == ""
    sneaky = str(own.parent) + "/../../../../.config/chromium"
    assert webapps.own_data(webapps.args_for("https://m.x", sneaky), xdg.env) == ""


def test_web_app_dark_mode_and_window_name(xdg):
    args = webapps.args_for("https://m.x/inbox", "", "force")
    assert webapps.dark_of(args) == "force" and "--force-dark-mode" in args
    assert webapps.dark_of(webapps.args_for("https://m.x", "", "dark")) == "dark"
    assert webapps.dark_of(webapps.args_for("https://m.x")) == "system"
    assert webapps.window_class("web.whatsapp.com", "chrome") == "chrome-web.whatsapp.com__-Default"
    assert webapps.window_class("https://mail.google.com/mail/u/0", "edge") == "msedge-mail.google.com__mail_u_0-Default"
    spec = launchers.Spec(name="Chat", program="/usr/bin/brave", args=args, web_url="https://m.x/inbox",
                          web_browser="brave", wm_class=webapps.window_class("https://m.x/inbox", "brave"))
    did, changes = launchers.plan_save(spec, env=xdg.env)
    ov.apply_all(changes)
    text = (xdg.user / did).read_text()
    assert "StartupWMClass=brave-m.x__inbox-Default" in text
    back = launchers.read_spec(text)
    assert back.wm_class == spec.wm_class and webapps.dark_of(back.args) == "force"
