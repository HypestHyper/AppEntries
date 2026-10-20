from conftest import entry
from app_entries import desktop_entries as de


def ids(apps):
    return [a.id for a in apps]


def test_application_dirs_order_and_defaults(xdg):
    dirs = de.application_dirs(xdg.env)
    assert dirs[0] == str(xdg.user)
    assert dirs[1:3] == [str(xdg.sys_a), str(xdg.sys_b)]
    assert len(dirs) == 3
    env = dict(xdg.env, XDG_DATA_DIRS="")
    assert de.application_dirs(env)[1:] == ["/usr/local/share/applications", "/usr/share/applications"]


def test_xdg_data_home_respected(xdg, tmp_path):
    env = dict(xdg.env, XDG_DATA_HOME=str(tmp_path / "data"))
    assert de.application_dirs(env)[0] == str(tmp_path / "data" / "applications")
    env["XDG_DATA_HOME"] = "relative/is/ignored"
    assert de.application_dirs(env)[0] == str(xdg.user)


def test_filters_type_and_exec(xdg):
    xdg.write(xdg.sys_b, "good.desktop", entry("Good"))
    xdg.write(xdg.sys_b, "link.desktop", "[Desktop Entry]\nType=Link\nName=L\nURL=x\n")
    xdg.write(xdg.sys_b, "noexec.desktop", "[Desktop Entry]\nType=Application\nName=N\nExec=\n")
    xdg.write(xdg.sys_b, "nogroup.desktop", "[Other]\nType=Application\n")
    xdg.write(xdg.sys_b, "notes.txt", entry("Txt"))
    assert ids(de.scan(xdg.env)) == ["good.desktop"]


def test_precedence_and_subdir_ids(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("Low"))
    xdg.write(xdg.sys_a, "app.desktop", entry("High"))
    xdg.write(xdg.sys_b, "kde4/tool.desktop", entry("Tool"))
    apps = {a.id: a for a in de.scan(xdg.env)}
    assert apps["app.desktop"].name == "High"
    assert apps["app.desktop"].source_path == str(xdg.sys_a / "app.desktop")
    assert apps["app.desktop"].shadowed == [str(xdg.sys_b / "app.desktop")]
    assert "kde4-tool.desktop" in apps


def test_user_full_override_wins(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("System"))
    xdg.write(xdg.user, "app.desktop", entry("Mine"))
    (app,) = de.scan(xdg.env)
    assert app.name == "Mine" and app.has_override and not app.override_managed
    assert app.system


def test_bare_override_shows_system_details(xdg):
    xdg.write(xdg.sys_b, "app.desktop", entry("System", Icon="sys-icon", Comment="Hi"))
    xdg.write(xdg.user, "app.desktop",
              "[Desktop Entry]\nType=Application\nName=System\nHidden=true\n%s=true\n" % de.MANAGED_KEY)
    (app,) = de.scan(xdg.env)
    assert app.hidden and app.override_managed
    assert app.icon == "sys-icon" and app.comment == "Hi"
    assert app.source_path == str(xdg.sys_b / "app.desktop")
    assert app.override_path == str(xdg.user / "app.desktop")


def test_user_only_app_is_not_system(xdg):
    xdg.write(xdg.user, "mine.desktop", entry("Mine"))
    (app,) = de.scan(xdg.env)
    assert not app.system


def test_no_display_filter(xdg):
    xdg.write(xdg.sys_b, "a.desktop", entry("A", NoDisplay="true"))
    xdg.write(xdg.sys_b, "b.desktop", entry("B"))
    assert ids(de.scan(xdg.env, include_no_display=False)) == ["b.desktop"]
    apps = de.scan(xdg.env)
    assert ids(apps) == ["a.desktop", "b.desktop"] and apps[0].no_display


def test_sorting_is_case_insensitive(xdg):
    for n in ("banana", "Apple", "cherry"):
        xdg.write(xdg.sys_b, n + ".desktop", entry(n))
    assert [a.name for a in de.scan(xdg.env)] == ["Apple", "banana", "cherry"]


def test_localized_strings():
    env = {"LANG": "de_DE.UTF-8"}
    locales = de.locale_names(env)
    assert locales == ["de_DE", "de"]
    d = {"Name": "Files", "Name[de]": "Dateien", "Comment[de_DE]": "Ordner", "Comment": "Folders"}
    assert de.localized(d, "Name", locales) == "Dateien"
    assert de.localized(d, "Comment", locales) == "Ordner"
    assert de.locale_names({"LC_ALL": "sr_RS@latin"}) == ["sr_RS@latin", "sr_RS", "sr@latin", "sr"]
    assert de.locale_names({"LANG": "C.UTF-8"}) == []


def test_executable_name():
    assert de.executable_name("env FOO=1 /usr/bin/firefox %u") == "firefox"
    assert de.executable_name('"/opt/My App/run" --x') == "run"
    assert de.executable_name("flatpak run org.x.Y") == "flatpak"


def test_escapes_and_search():
    d = de.DesktopFile("[Desktop Entry]\nName=A\\sB\n")
    assert de.unescape(d.group_dict()["Name"]) == "A B"


def test_desktop_file_edit_preserves_rest():
    text = "# top\n[Desktop Entry]\nName=X\n# keep me\nExec=x\n\n[Desktop Action new]\nName=New\nExec=x --new\n"
    df = de.DesktopFile(text)
    df.set("Hidden", "true")
    assert df.text() == ("# top\n[Desktop Entry]\nName=X\n# keep me\nExec=x\nHidden=true\n\n"
                         "[Desktop Action new]\nName=New\nExec=x --new\n")
    assert df.remove("Hidden")
    assert df.text() == text
    df.set("Name", "Y")
    assert "Name=Y" in df.text() and df.group_dict("Desktop Action new")["Name"] == "New"


def test_search_text(xdg):
    xdg.write(xdg.sys_b, "org.x.Edit.desktop", entry("Editor", "gedit %F", GenericName="Text Editor"))
    (app,) = de.scan(xdg.env)
    for q in ("editor", "text", "gedit", "org.x"):
        assert q in app.search_text()


def test_unreadable_dir_is_skipped(xdg):
    assert de.scan_dir(str(xdg.tmp / "missing"), False) == {}
