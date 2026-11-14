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
    assert seen.update(de.scan(xdg.env), xdg.env, now=7000) == {"c.desktop"}   # until it's opened
    seen.mark_seen(["c.desktop"], xdg.env)
    assert seen.update(de.scan(xdg.env), xdg.env, now=7500) == set()

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


def test_new_stays_until_opened(xdg):
    xdg.write(xdg.sys_b, "a.desktop", entry("A"))
    seen.update(de.scan(xdg.env), xdg.env, now=1000)              # first run: nothing new
    xdg.write(xdg.sys_b, "b.desktop", entry("B"))
    xdg.write(xdg.sys_b, "c.desktop", entry("C"))
    assert seen.update(de.scan(xdg.env), xdg.env, now=2000) == {"b.desktop", "c.desktop"}
    # Next start: still New, as neither was opened.
    assert seen.update(de.scan(xdg.env), xdg.env, now=3000) == {"b.desktop", "c.desktop"}
    assert seen.mark_seen(["b.desktop"], xdg.env) == {"c.desktop"}
    assert seen.update(de.scan(xdg.env), xdg.env, now=4000) == {"c.desktop"}
    # Removed before you looked: forgotten.
    (xdg.sys_b / "c.desktop").unlink()
    assert seen.update(de.scan(xdg.env), xdg.env, now=5000) == set()
    assert seen.load_unseen(xdg.env) == set()
