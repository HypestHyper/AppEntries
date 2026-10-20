import io
import tarfile

import pytest

from app_entries import APP_ID, updater


def test_versions_compare_numerically_and_test_versions_come_first():
    assert updater.is_newer("1.0.10", "1.0.9")
    assert updater.is_newer("v2.0", "1.9.9")
    assert not updater.is_newer("1.0.0", "1.0.0")
    assert updater.is_newer("1.1.0", "1.1.0-beta2")
    assert not updater.is_newer("1.1.0-beta2", "1.1.0")


def test_picks_the_newest_release_and_skips_test_versions_unless_asked():
    data = [
        {"tag_name": "v1.2.0-beta", "prerelease": True, "tarball_url": "t3"},
        {"tag_name": "v1.1.0", "tarball_url": "t2", "body": "Notes"},
        {"tag_name": "v1.0.0", "tarball_url": "t1"},
        {"tag_name": "v9.0.0", "draft": True, "tarball_url": "t9"},
    ]
    found = updater.releases_from(data)
    assert updater.pick(found, False).version == "1.1.0"
    assert updater.pick(found, True).version == "1.2.0-beta"
    tags = updater.tags_from([{"name": "v1.3.0", "tarball_url": "x"}, {"name": "nightly", "tarball_url": "y"}])
    assert [t.version for t in tags] == ["1.3.0"]


def test_location_tells_home_installs_from_checkouts(tmp_path):
    pkg = tmp_path / "prefix" / "share" / APP_ID / "app_entries"
    pkg.mkdir(parents=True)
    (tmp_path / "prefix" / "bin").mkdir()
    where = updater.location(str(pkg))
    assert where.kind == "home" and where.prefix == str(tmp_path / "prefix")
    checkout = tmp_path / "src" / "app_entries"
    checkout.mkdir(parents=True)
    (tmp_path / "src" / ".git").mkdir()
    assert updater.location(str(checkout)).kind == "source"


def _tarball(path, files):
    with tarfile.open(path, "w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def _prefix(tmp_path):
    prefix = tmp_path / "prefix"
    pkg = prefix / "share" / APP_ID / "app_entries"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("VERSION = 'old'\n")
    (prefix / "bin").mkdir()
    return prefix, pkg


INSTALL = """#!/bin/sh
set -eu
PREFIX="$2"
rm -rf "$PREFIX/share/%s/app_entries"
mkdir -p "$PREFIX/share/%s"
cp -r app_entries "$PREFIX/share/%s/app_entries"
""" % (APP_ID, APP_ID, APP_ID)


def test_install_replaces_the_package(tmp_path):
    prefix, pkg = _prefix(tmp_path)
    archive = tmp_path / "r.tar.gz"
    _tarball(archive, {"AppEntries-abc/install.sh": INSTALL,
                       "AppEntries-abc/app_entries/__init__.py": "VERSION = 'new'\n"})
    rel = updater.Release("9.0.0", "9.0.0", "", archive.as_uri(), "", False)
    updater.install(rel, updater.Install("home", str(prefix), str(prefix / "bin" / APP_ID)))
    assert "new" in (pkg / "__init__.py").read_text()


def test_failed_install_puts_the_old_version_back(tmp_path):
    prefix, pkg = _prefix(tmp_path)
    archive = tmp_path / "r.tar.gz"
    broken = "#!/bin/sh\nrm -rf \"$2/share/%s/app_entries\"\nexit 3\n" % APP_ID
    _tarball(archive, {"AppEntries-abc/install.sh": broken,
                       "AppEntries-abc/app_entries/__init__.py": "VERSION = 'new'\n"})
    rel = updater.Release("9.0.0", "9.0.0", "", archive.as_uri(), "", False)
    with pytest.raises(updater.UpdateError):
        updater.install(rel, updater.Install("home", str(prefix), ""))
    assert "old" in (pkg / "__init__.py").read_text()


def test_unsafe_archives_are_refused(tmp_path):
    archive = tmp_path / "evil.tar.gz"
    _tarball(archive, {"../outside.txt": "x"})
    with pytest.raises(updater.UpdateError):
        updater._extract(str(archive), str(tmp_path / "out"))
    assert not (tmp_path / "outside.txt").exists()
    with pytest.raises(updater.UpdateError):
        updater.install(updater.Release("1", "1", "", "", "", False), updater.Install("source"))
