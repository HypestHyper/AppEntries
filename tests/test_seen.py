import os

from conftest import entry

from app_entries import desktop_entries as de
from app_entries import seen


def test_first_run_marks_nothing_new_then_notes_new_apps(xdg):
    a = xdg.write(xdg.sys_b, "a.desktop", entry("A"))
    xdg.write(xdg.sys_b, "b.desktop", entry("B"))
    assert seen.update(de.scan(xdg.env), xdg.env, now=5000) == set()
    known = seen.load(xdg.env)
    assert set(known) == {"a.desktop", "b.desktop"} and known["a.desktop"] == os.stat(a).st_ctime  # file times

    xdg.write(xdg.sys_b, "c.desktop", entry("C"))
    apps = de.scan(xdg.env)
    assert seen.update(apps, xdg.env, now=6000) == {"c.desktop"}
    assert next(x for x in apps if x.id == "c.desktop").first_seen == 6000
    assert seen.update(de.scan(xdg.env), xdg.env, now=7000) == set()   # seen now

    # Removed, then installed again: new again.
    (xdg.sys_b / "c.desktop").unlink()
    seen.update(de.scan(xdg.env), xdg.env, now=8000)
    xdg.write(xdg.sys_b, "c.desktop", entry("C"))
    assert seen.update(de.scan(xdg.env), xdg.env, now=9000) == {"c.desktop"}


def test_a_damaged_file_starts_again(xdg):
    xdg.write(xdg.sys_b, "a.desktop", entry("A"))
    p = seen.path(xdg.env)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write("{not json")
    assert seen.update(de.scan(xdg.env), xdg.env) == set()
    assert "a.desktop" in seen.load(xdg.env)
