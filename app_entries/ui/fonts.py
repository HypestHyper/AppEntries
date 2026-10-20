"""Register the bundled fonts for this process only."""
import ctypes
import ctypes.util
import glob
import os

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")


def register() -> int:
    """Add every bundled .ttf to fontconfig. Returns how many were added."""
    name = ctypes.util.find_library("fontconfig") or "libfontconfig.so.1"
    try:
        fc = ctypes.CDLL(name)
    except OSError:
        return 0
    fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    fc.FcConfigAppFontAddFile.restype = ctypes.c_int
    added = 0
    for path in sorted(glob.glob(os.path.join(FONT_DIR, "*.ttf"))):
        added += bool(fc.FcConfigAppFontAddFile(None, path.encode()))
    return added
