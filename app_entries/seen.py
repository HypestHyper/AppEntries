"""When each app first appeared on this computer, for sorting by newest and
for the New badge.

Package managers keep the build date as an entry file's modification time and
rewrite the file on every update, so neither file time says when an app was
installed. Instead App Entries notes when it first saw each app. The first
time it runs, it starts from the file times, and marks nothing as new.
"""
import json
import os
import tempfile
import time

from . import desktop_entries as de


def path(env=None) -> str:
    env = os.environ if env is None else env
    home = env.get("HOME") or os.path.expanduser("~")
    state = env.get("XDG_STATE_HOME") or ""
    base = state if os.path.isabs(state) else os.path.join(home, ".local", "state")
    return os.path.join(base, "app-entries", "seen.json")


def load(env=None):
    """{app id: when first seen}, or None if App Entries hasn't noted any yet."""
    try:
        with open(path(env), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {k: float(v) for k, v in data.items() if isinstance(k, str) and isinstance(v, (int, float))}


def _save(seen, env=None) -> None:
    p = path(env)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), prefix=".seen-", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(seen, f, sort_keys=True)
        os.replace(tmp, p)
    except OSError:
        pass  # sorting by newest just starts again next time


def _file_time(app: de.App) -> float:
    try:
        return os.stat(app.base_path or app.source_path).st_ctime
    except OSError:
        return 0.0


def update(apps, env=None, now=None) -> set:
    """Note apps not seen before and set each app's `first_seen`. Returns the
    IDs that are new since the last time. An app that's removed is forgotten,
    so installing it again counts as new."""
    now = time.time() if now is None else now
    known = load(env)
    first_run = known is None
    known = known or {}
    new = set()
    out = {}
    for a in apps:
        when = known.get(a.id)
        if when is None:
            when = _file_time(a) if first_run else now
            if not first_run:
                new.add(a.id)
        out[a.id] = when
        a.first_seen = when
    if out != known:
        _save(out, env)
    return new
