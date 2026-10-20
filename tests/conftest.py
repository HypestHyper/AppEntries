import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def xdg(tmp_path):
    """A fake XDG layout: one user dir and two system dirs."""
    home = tmp_path / "home"
    user = home / ".local" / "share" / "applications"
    sys_a = tmp_path / "usr_local" / "applications"
    sys_b = tmp_path / "usr" / "applications"
    for d in (user, sys_a, sys_b):
        d.mkdir(parents=True)
    env = {
        "HOME": str(home),
        "XDG_DATA_DIRS": "%s:%s" % (sys_a.parent, sys_b.parent),
        "LANG": "C",
    }

    class X:
        pass

    x = X()
    x.env, x.user, x.sys_a, x.sys_b, x.tmp = env, user, sys_a, sys_b, tmp_path

    def write(folder, name, text):
        p = folder / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    x.write = write
    return x


def entry(name="Thing", exec_="thing %U", **extra):
    lines = ["[Desktop Entry]", "Type=Application", "Name=%s" % name, "Exec=%s" % exec_]
    lines += ["%s=%s" % kv for kv in extra.items()]
    return "\n".join(lines) + "\n"
