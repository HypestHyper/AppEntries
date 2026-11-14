import os
import shutil
import stat
import subprocess

import pytest

from app_entries import importers as im
from app_entries import launchers
from app_entries import overrides as ov

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><rect width="8" height="8"/></svg>'

needs_squashfs = pytest.mark.skipif(not (shutil.which("mksquashfs") and shutil.which("unsquashfs")),
                                    reason="squashfs-tools isn't installed")


def make_appimage(tmp_path, name="Tool-2.4.1-x86_64.AppImage", entry=None, icon=("tool.svg", SVG), link=True):
    """A real ELF program (/bin/true) with a squashfs after it, marked as a
    type 2 AppImage, the way appimagetool builds them."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "tool.desktop").write_text(entry or (
        "[Desktop Entry]\nType=Application\nName=Tool\nComment=Does tool things\nExec=tool %U\nIcon=tool\n"
        "Categories=Graphics;\nMimeType=image/png;image/x-tool;\nStartupWMClass=ToolWin\n"
        "X-AppImage-Version=2.4.1\n"))
    if icon:
        (src / "usr").mkdir()
        (src / "usr" / icon[0]).write_bytes(icon[1])
        if link:
            os.symlink("usr/" + icon[0], src / ".DirIcon")
    fs = tmp_path / "fs.sqfs"
    subprocess.run(["mksquashfs", str(src), str(fs), "-quiet", "-noappend", "-all-root"], check=True,
                   stdout=subprocess.DEVNULL)
    out = tmp_path / name
    from pathlib import Path
    elf = bytearray(Path("/bin/true").read_bytes())
    elf[8:11] = b"AI\x02"
    out.write_bytes(bytes(elf) + fs.read_bytes())
    return out


@needs_squashfs
def test_appimage_is_read_without_running_it(tmp_path):
    p = make_appimage(tmp_path)
    assert im.detect(str(p)) == "appimage"
    assert im.squashfs_offset(str(p)) == os.path.getsize("/bin/true")
    imp = im.read_appimage(str(p))
    s = imp.spec
    assert imp.how == "squashfs"
    assert (s.name, s.comment, s.categories) == ("Tool", "Does tool things", ["Graphics"])
    assert s.mime_types == ["image/png", "image/x-tool"] and s.wm_class == "ToolWin" and s.accepts_files
    assert s.program == str(p) and imp.version == "2.4.1"
    assert imp.icon == (SVG, "tool.svg")      # followed .DirIcon into usr/


@needs_squashfs
def test_appimage_without_unsquashfs_asks_before_running(tmp_path, monkeypatch):
    p = make_appimage(tmp_path)
    monkeypatch.setattr(im, "_unsquash", lambda *a: False)
    with pytest.raises(im.NeedsRun):
        im.read_appimage(str(p))


def test_a_file_that_isnt_one_falls_back_to_its_name(tmp_path):
    p = tmp_path / "Thing-1.0.AppImage"
    p.write_bytes(b"not an elf at all")
    imp = im.read_appimage(str(p))
    assert imp.how == "name" and imp.spec.name == "Thing" and imp.notes


@needs_squashfs
def test_saving_an_appimage_makes_a_working_entry(tmp_path, xdg):
    p = make_appimage(tmp_path)
    imp = im.read_appimage(str(p))
    icon, changes = im.plan_icon(imp, xdg.env)
    imp.spec.icon_kind, imp.spec.icon_value = "file", icon
    did, more = launchers.plan_save(imp.spec, None, xdg.env)
    ov.apply_all(changes + more)
    text = (xdg.user / did).read_text()
    assert "MimeType=image/png;image/x-tool;" in text and "StartupWMClass=ToolWin" in text
    from pathlib import Path
    assert f"Icon={icon}" in text and Path(icon).read_bytes() == SVG
    assert launchers.read_spec(text).mime_types == ["image/png", "image/x-tool"]


def test_moving_to_applications(tmp_path):
    env = {"HOME": str(tmp_path)}
    dl = tmp_path / "Downloads"
    dl.mkdir()
    f = dl / "App.AppImage"
    f.write_bytes(b"x")
    (tmp_path / "Applications").mkdir()
    (tmp_path / "Applications" / "App.AppImage").write_bytes(b"other")    # never overwritten
    new = im.move(str(f), env)
    assert new == str(tmp_path / "Applications" / "App-2.AppImage") and not f.exists()
    assert im.in_applications(new, env)
    assert im.make_executable(new) and os.stat(new).st_mode & stat.S_IXUSR
    assert not im.make_executable(new)


def test_app_folder_finds_the_program_and_icon(tmp_path):
    app = tmp_path / "Zed-0.160.4"
    (app / "bin").mkdir(parents=True)
    (app / "resources").mkdir()
    for n, body in (("zed", b"\x7fELF...."), ("chrome-sandbox", b"\x7fELF"), ("bin/cli", b"#!/bin/sh\n")):
        (app / n).write_bytes(body)
        os.chmod(app / n, 0o755)
    (app / "resources" / "zed.png").write_bytes(PNG)
    imp = im.read_folder(str(app))
    assert im.detect(str(app)) == "folder"
    assert imp.spec.name == "Zed" and imp.spec.program == str(app / "zed") and imp.spec.workdir == str(app)
    assert imp.icon == (PNG, "zed.png") and imp.version == "0.160.4"
    im.repoint(imp, str(app), "/new/Zed")
    assert imp.spec.program == "/new/Zed/zed" and imp.spec.workdir == "/new/Zed"


def test_app_folder_with_its_own_entry(tmp_path):
    app = tmp_path / "Discord"
    app.mkdir()
    (app / "Discord").write_bytes(b"\x7fELF")
    os.chmod(app / "Discord", 0o755)
    (app / "discord.png").write_bytes(PNG)
    (app / "discord.desktop").write_text("[Desktop Entry]\nType=Application\nName=Discord\nExec=Discord\n"
                                         "Icon=discord.png\nCategories=Network;InstantMessaging;\n")
    imp = im.read_folder(str(app))
    assert imp.spec.program == str(app / "Discord") and imp.spec.categories == ["Network", "InstantMessaging"]
    assert imp.icon == (PNG, "discord.png")


def test_windows_and_java(tmp_path, monkeypatch):
    exe = tmp_path / "Games" / "Some Game" / "game.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    monkeypatch.setattr(im.shutil, "which", lambda p: "/usr/bin/" + p if p == "wine" else None)
    imp = im.read_exe(str(exe), "wine")
    assert imp.spec.program == f"wine '{exe}'" and imp.spec.workdir == str(exe.parent)
    assert imp.spec.categories == ["Game"] and imp.icon is None and not imp.notes
    assert im.runners(im.shutil.which) == [("wine", "Wine")]
    assert im.read_exe(str(exe), "umu").notes        # umu-run isn't installed
    jar = tmp_path / "tool.jar"
    jar.write_bytes(b"PK")
    assert im.read_jar(str(jar)).spec.program == f"java -jar {jar}"


def test_a_downloaded_desktop_file_points_to_its_folder(tmp_path):
    d = tmp_path / "app"
    d.mkdir()
    (d / "run.sh").write_text("#!/bin/sh\n")
    (d / "icon.png").write_bytes(PNG)
    (d / "thing.desktop").write_text("[Desktop Entry]\nType=Application\nName=Thing\nExec=run.sh --go\n"
                                     "Icon=icon.png\n")
    imp = im.read_desktop_file(str(d / "thing.desktop"))
    assert f"Exec={d / 'run.sh'} --go" in imp.entry_text and f"Icon={d / 'icon.png'}" in imp.entry_text
    assert imp.entry_id == "thing.desktop" and len(imp.notes) == 2


@needs_squashfs
def test_finds_apps_without_a_launcher(tmp_path):
    from app_entries import desktop_entries as de
    env = {"HOME": str(tmp_path)}
    apps_dir = tmp_path / "Applications"
    apps_dir.mkdir()
    (tmp_path / "x").mkdir()
    shutil.move(str(make_appimage(tmp_path / "x", name="A.AppImage")), apps_dir / "A.AppImage")
    shutil.copy(apps_dir / "A.AppImage", apps_dir / "B.AppImage")
    game = tmp_path / "Games" / "Solitaire"
    game.mkdir(parents=True)
    (game / "solitaire.exe").write_bytes(b"MZ")
    (game / "unins000.exe").write_bytes(b"MZ")
    known = [de.App(id="b.desktop", name="B", exec=f"{apps_dir / 'B.AppImage'} %U")]
    assert im.find_without_launcher(known, env) == [(str(apps_dir / "A.AppImage"), "appimage"),
                                                    (str(game / "solitaire.exe"), "exe")]
