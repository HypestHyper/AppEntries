"""Start-up timing, printed when APP_ENTRIES_TIMING=1. Times are from when
the process started. APP_ENTRIES_QUIT_ON_FIRST_FRAME=1 closes the app once
the window has drawn ("listed" waits until the apps are listed). No GTK."""
import os
import sys
import time

ON = os.environ.get("APP_ENTRIES_TIMING") == "1"
QUIT = os.environ.get("APP_ENTRIES_QUIT_ON_FIRST_FRAME", "")


def _process_age_ms() -> float:
    """How long ago the process started (Linux), so Python's own start counts."""
    try:
        with open("/proc/uptime") as f:
            uptime = float(f.read().split()[0])
        with open("/proc/self/stat") as f:
            started = int(f.read().rsplit(")", 1)[1].split()[19]) / os.sysconf("SC_CLK_TCK")
        return max(0.0, (uptime - started) * 1000)
    except (OSError, ValueError, IndexError):
        return 0.0


_t0 = time.perf_counter()
_base = _process_age_ms() if ON else 0.0


def mark(name: str) -> None:
    if ON:
        print("%7.1f ms  %s" % (_base + (time.perf_counter() - _t0) * 1000, name), file=sys.stderr, flush=True)
