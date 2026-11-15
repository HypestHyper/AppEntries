import io
import os
from typing import ClassVar

import pytest

from app_entries import github_apps as gh

A = gh.Asset


def env(tmp_path):
    return {"HOME": str(tmp_path), "XDG_STATE_HOME": str(tmp_path / "state")}


def test_finding_the_project(tmp_path):
    e = env(tmp_path)
    s = gh.source_of("o.desktop", "gh-releases-zsync|obsidianmd|obsidian-releases|latest|Obsidian-*.AppImage.zsync",
                     env=e)
    assert (s.name, s.tag, s.pattern, s.how) == ("obsidianmd/obsidian-releases", "latest", "Obsidian-*.AppImage",
                                                 "appimage")
    s = gh.source_of("o.desktop", "", "https://github.com/owner/tool/releases/download/v1/Tool.AppImage", env=e)
    assert (s.name, s.how) == ("owner/tool", "download")
    assert gh.source_of("o.desktop", "zsync|https://example.org/x.zsync", "https://example.org/x", env=e) is None
    # Linked by hand wins, and can be forgotten.
    gh.link("o.desktop", "https://github.com/me/thing.git", e)
    assert gh.source_of("o.desktop", env=e).name == "me/thing"
    gh.unlink("o.desktop", e)
    assert gh.source_of("o.desktop", env=e) is None
    with pytest.raises(gh.GitHubError):
        gh.link("o.desktop", "not a project", e)
    assert gh.parse_project("owner/repo") == ("owner", "repo")


def test_picking_the_file_for_this_computer():
    assets = [A("Tool-2.0-arm64.AppImage", "u1"), A("Tool-2.0-x86_64.AppImage", "u2"), A("Tool-2.0.tar.gz", "u3"),
              A("Tool-2.0-i386.AppImage", "u4"), A("Tool-2.0-x86_64.AppImage.zsync", "u5")]
    assert gh.pick_asset(assets, machine="x86_64").name == "Tool-2.0-x86_64.AppImage"
    assert gh.pick_asset(assets, machine="aarch64").name == "Tool-2.0-arm64.AppImage"
    # No processor in the name: fine, unless another processor is named.
    plain = [A("Obsidian-1.8.0.AppImage", "a"), A("Obsidian-1.8.0-arm64.AppImage", "b")]
    assert gh.pick_asset(plain, machine="x86_64").name == "Obsidian-1.8.0.AppImage"
    assert gh.pick_asset(plain, "Obsidian-*-arm64.AppImage", machine="aarch64").name == "Obsidian-1.8.0-arm64.AppImage"
    # Several fit: the one named most like the file in use.
    two = [A("Cool-Studio-3.1.AppImage", "a"), A("Cool-Player-3.1.AppImage", "b")]
    assert gh.pick_asset(two, current="Cool-Player-3.0.AppImage", machine="x86_64").name == "Cool-Player-3.1.AppImage"
    assert gh.pick_asset([A("Tool.tar.gz", "x")], machine="x86_64") is None


def test_versions():
    assert gh.version_in("v1.8.10") == "1.8.10" and gh.version_in("Obsidian-1.7.7.AppImage") == "1.7.7"
    assert gh.version_in("Tool-x86_64.AppImage") == "" and gh.version_in("release-42") == "42"


def test_is_it_newer(tmp_path):
    e = env(tmp_path)
    f = tmp_path / "Obsidian-1.7.7.AppImage"
    f.write_bytes(b"x" * 10)
    rel = gh.Release("v1.8.0")
    assert gh.compare("o", str(f), rel, A("Obsidian-1.8.0.AppImage", "u", 99), e).newer
    assert not gh.compare("o", str(f), gh.Release("v1.7.7"), A("Obsidian-1.7.7.AppImage", "u", 10), e).newer
    assert not gh.compare("o", str(f), gh.Release("v1.7.6"), None, e).newer
    assert gh.compare("o", str(f), gh.Release("v1.7.10"), None, e).newer      # 10 > 7, not "1" < "7"
    # No version in the name: the same size means the same file.
    g = tmp_path / "Tool.AppImage"
    g.write_bytes(b"x" * 10)
    assert not gh.compare("t", str(g), gh.Release("nightly"), A("Tool-x86_64.AppImage", "u", 10), e).newer
    assert gh.compare("t", str(g), gh.Release("nightly"), A("Tool-x86_64.AppImage", "u", 12), e).newer
    # After App Entries updated it, it knows exactly which release is in use.
    gh.remember_installed("t", "nightly", "Tool.AppImage", "owner/tool", env=e)
    assert gh.source_of("t", env=e).name == "owner/tool" and gh.source_of("t", env=e).how == "updated"
    assert not gh.compare("t", str(g), gh.Release("nightly"), A("Tool-x86_64.AppImage", "u", 12), e).newer
    assert gh.compare("t", str(g), gh.Release("nightly-2"), A("Tool-x86_64.AppImage", "u", 12), e).newer


def test_reading_releases():
    seen = []

    def get(url):
        seen.append(url)
        if url.endswith("/releases/latest"):
            return {"tag_name": "v2", "assets": [{"name": "T.AppImage", "browser_download_url": "d", "size": 5}],
                    "body": "notes", "html_url": "page"}
        if "?per_page" in url:
            return [{"tag_name": "v3-beta", "prerelease": True}, {"tag_name": "v2"}, {"tag_name": "x", "draft": True}]
        return {"tag_name": url.rsplit("/", 1)[1]}
    r = gh.latest(gh.Source("o", "r"), get)
    assert (r.tag, r.notes, r.url, r.assets[0].size) == ("v2", "notes", "page", 5)
    assert gh.latest(gh.Source("o", "r", "latest-pre"), get).tag == "v3-beta"
    assert gh.latest(gh.Source("o", "r", "continuous"), get).tag == "continuous"
    assert seen[0] == "https://api.github.com/repos/o/r/releases/latest"


class Response(io.BytesIO):
    headers: ClassVar[dict] = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def test_downloading(tmp_path):
    body = b"\x7fELF" + b"x" * 2_000_000
    seen = []
    new = gh.download(A("Tool-2.0.AppImage", "https://x/T", len(body)), str(tmp_path),
                      lambda done, total: seen.append(done), opener=lambda req, timeout: Response(body))
    assert new == str(tmp_path / "Tool-2.0.AppImage")
    with open(new, "rb") as f:
        assert f.read() == body
    assert os.stat(new).st_mode & 0o111 and seen[-1] == len(body)
    # Already there: a new name, never overwritten.
    again = gh.download(A("Tool-2.0.AppImage", "https://x/T", len(body)), str(tmp_path),
                        opener=lambda r, timeout: Response(body))
    assert again == str(tmp_path / "Tool-2.0-2.AppImage")
    for asset, data, why in ((A("Bad.AppImage", "https://x/B", 99), body, "cut short"),
                             (A("Page.AppImage", "https://x/P", 0), b"<html>", "isn't an AppImage")):
        with pytest.raises(gh.GitHubError, match=why):
            gh.download(asset, str(tmp_path), opener=lambda r, timeout, d=data: Response(d))
    with pytest.raises(gh.GitHubError, match="secure"):
        gh.download(A("Plain.AppImage", "http://x/P", 0), str(tmp_path), opener=lambda r, timeout: Response(body))
    with pytest.raises(gh.GitHubError, match="Stopped"):
        gh.download(A("Stop.AppImage", "https://x/S", 0), str(tmp_path), opener=lambda r, timeout: Response(body),
                    cancelled=lambda: True)
    left = sorted(os.listdir(tmp_path))
    assert left == ["Tool-2.0-2.AppImage", "Tool-2.0.AppImage"]      # no half-written files left behind
