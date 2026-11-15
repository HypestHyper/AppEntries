import hashlib
import io
import os
import tarfile
import zipfile

import pytest

from app_entries import github_apps as gh
from app_entries import github_install as gi

A = gh.Asset


def test_files_are_ranked_for_this_computer():
    rel = gh.Release("v2", assets=[
        A("tool-2.0-windows-x64.zip", "u"), A("tool-2.0.dmg", "u"), A("tool-2.0-aarch64.AppImage", "u"),
        A("tool-2.0-x86_64.AppImage", "u"), A("tool-2.0-x86_64.AppImage.zsync", "u"), A("SHA256SUMS", "u"),
        A("tool_2.0_amd64.deb", "u"), A("tool-2.0.x86_64.rpm", "u"), A("tool-2.0-linux-x64.tar.gz", "u"),
        A("tool-2.0-src.tar.gz", "u"), A("tool-2.0-linux-arm64.tar.gz", "u")])
    got = [(c.kind, c.asset.name, c.fits) for c in gi.choices(rel, "apt", "x86_64")]
    assert got == [("appimage", "tool-2.0-x86_64.AppImage", True),
                   ("archive", "tool-2.0-linux-x64.tar.gz", True),
                   ("package", "tool_2.0_amd64.deb", True),
                   ("package", "tool-2.0.x86_64.rpm", False)]          # an .rpm on an apt system: last, and said so
    assert gi.choices(rel, "dnf", "aarch64")[0].asset.name == "tool-2.0-aarch64.AppImage"


def test_checksums(tmp_path):
    f = tmp_path / "tool.AppImage"
    f.write_bytes(b"\x7fELF data")
    good = hashlib.sha256(f.read_bytes()).hexdigest()
    assert gi.verify(str(f), "tool.AppImage", f"{good}  tool.AppImage\n{'0' * 64}  other\n") is True
    assert gi.verify(str(f), "tool.AppImage", f"{'1' * 64} *tool.AppImage\n") is False
    assert gi.verify(str(f), "tool.AppImage", f"{'1' * 64}  something-else\n") is None
    assert gi.verify(str(f), "tool.AppImage", good + "\n") is True       # a .sha256 file with just the sum
    rel = gh.Release("v1", assets=[A("tool.AppImage", "u"), A("tool.AppImage.sha256", "c"), A("SHA256SUMS", "s")])
    assert gi.checksum_asset(rel, "tool.AppImage").name == "tool.AppImage.sha256"


def _tar(path, members):
    with tarfile.open(path, "w:gz") as t:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            t.addfile(info, io.BytesIO(data))


def test_unpacking_an_app_archive(tmp_path):
    apps = tmp_path / "Applications"
    apps.mkdir()
    arc = tmp_path / "tool.tar.gz"
    _tar(arc, [("Tool-2.0/tool", b"\x7fELF"), ("Tool-2.0/lib/x.so", b"x")])
    folder = gi.unpack(str(arc), str(apps), "Tool")
    assert folder == str(apps / "Tool") and os.access(apps / "Tool" / "tool", os.X_OK)
    assert gi.unpack(str(arc), str(apps), "Tool") == str(apps / "Tool-2")       # never over an existing folder
    z = tmp_path / "flat.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("run", "#!/bin/sh\n")
        zf.writestr("data/a", "x")
    assert sorted(os.listdir(gi.unpack(str(z), str(apps), "Flat"))) == ["data", "run"]


def test_an_archive_that_writes_outside_its_folder_is_refused(tmp_path):
    apps = tmp_path / "Applications"
    apps.mkdir()
    arc = tmp_path / "evil.tar.gz"
    _tar(arc, [("../../.bashrc", b"oops")])
    with pytest.raises(gi.UnsafeArchive):
        gi.unpack(str(arc), str(apps), "Evil")
    assert os.listdir(apps) == [] and not (tmp_path / ".bashrc").exists()


def test_reading_a_project_and_its_source(tmp_path):
    page = (b'<html><meta property="og:description" content="A fast tool. Contribute to o/tool development by '
            b'creating an account on GitHub."></html>')

    def web(url, follow=True):
        if url == "https://github.com/o/tool":
            return 200, {}, page
        if url.endswith("/HEAD/Cargo.toml"):
            return 200, {}, b"[package]\nname = 'tool'\n"
        if url.endswith("/HEAD/go.mod"):
            return 200, {}, b"module example.com/tool/v2\n"
        return 404, {}, b""
    p = gi.fetch("github.com/o/tool", web)
    assert (p.name, p.description) == ("o/tool", "A fast tool.")
    got = [(c.title, c.commands) for c in gi.from_source(p, web, lambda t: "/usr/bin/" + t, str(tmp_path))]
    assert got == [("Rust, with cargo", [["cargo", "install", "--git", "https://github.com/o/tool"]]),
                   ("Go, with go install", [["go", "install", "example.com/tool/v2@latest"]]),
                   ("A copy of the code, with git", [["git", "clone", "https://github.com/o/tool",
                                                      str(tmp_path / "Apps" / "tool")]])]
    with pytest.raises(gh.GitHubError, match="no project"):
        gi.fetch("o/missing", lambda url, follow=True: (404, {}, b""))
