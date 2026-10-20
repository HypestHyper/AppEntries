"""Your own icons: a folder of SVG and PNG files App Entries keeps safe,
plus fitting them onto the icon grid, recolouring them and drawing a border.
Pure Python, no GTK.

Icons you pick from elsewhere are copied here, so a launcher keeps its icon
even if the original file is moved or deleted. The folder is
~/.local/share/app-entries/icons, and uninstalling App Entries keeps it.
"""
import base64
import os
import re
import shutil
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import List, Optional

from .desktop_entries import user_data_dir

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)

EXTENSIONS = (".svg", ".png")
MAX_DOWNLOAD = 2 * 1024 * 1024
GRID = 960


class IconError(Exception):
    pass


# Where to find icons: name, address, how to get a link (Add from link), and
# how to get the code (Paste SVG).
SOURCES = [
    ("Iconify", "https://icon-sets.iconify.design",
     "200,000+ icons from 150 sets. Open an icon and copy its SVG link, like "
     "https://api.iconify.design/mdi/firefox.svg",
     "200,000+ icons from 150 sets. Open an icon and use Copy SVG."),
    ("Dashboard Icons", "https://dashboardicons.com",
     "Logos for thousands of apps and services, in colour, as SVG and PNG",
     "Logos for thousands of apps and services. Open the SVG version and copy its code."),
    ("Simple Icons", "https://simpleicons.org", "Brand logos as one-colour SVGs, made for recolouring",
     "Brand logos as one-colour SVGs. Use Copy SVG on any logo."),
    ("Papirus", "https://github.com/PapirusDevelopmentTeam/papirus-icon-theme",
     "A complete Linux app icon theme (use the files under Papirus/64x64/apps)",
     "A complete Linux app icon theme. Open a file under Papirus/64x64/apps, then Raw, and copy it."),
]


def folder(env=None) -> str:
    return os.path.join(user_data_dir(env), "app-entries", "icons")


def list_icons(env=None) -> List[str]:
    d = folder(env)
    try:
        names = sorted(os.listdir(d), key=str.casefold)
    except OSError:
        return []
    return [os.path.join(d, n) for n in names if n.lower().endswith(EXTENSIONS)]


def in_library(path: str, env=None) -> bool:
    return os.path.dirname(os.path.abspath(path)) == os.path.abspath(folder(env))


def _unique(name: str, env=None) -> str:
    base, ext = os.path.splitext(os.path.basename(name))
    base = re.sub(r"[^\w.-]+", "-", base).strip("-.") or "icon"
    ext = ext.lower() if ext.lower() in EXTENSIONS else ".svg"
    path, n = os.path.join(folder(env), base + ext), 2
    while os.path.exists(path):
        path, n = os.path.join(folder(env), "%s-%d%s" % (base, n, ext)), n + 1
    return path


def check(data: bytes, name: str = "") -> str:
    """The file type ("svg" or "png") if the data is a usable icon."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        raise IconError("It isn't an SVG or PNG image.")
    if root.tag not in ("{%s}svg" % SVG_NS, "svg"):
        raise IconError("It's XML, but not an SVG image.")
    return "svg"


def _same_file(a: str, b: str) -> bool:
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def add_file(path: str, env=None) -> str:
    """Copy an image into the library (unless it's already there) and return
    the copy's path."""
    if in_library(path, env):
        return path
    with open(path, "rb") as f:
        data = f.read()
    kind = check(data, path)
    for existing in list_icons(env):
        if os.path.getsize(existing) == len(data) and _same_file(existing, path):
            return existing
    os.makedirs(folder(env), exist_ok=True)
    target = _unique(os.path.splitext(path)[0] + "." + kind, env)
    shutil.copyfile(path, target)
    return target


def download(url: str, env=None, opener=urllib.request.urlopen) -> str:
    """Download an SVG or PNG into the library and return its path."""
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in ("https", "http"):
        raise IconError("The link has to start with https://")
    try:
        with opener(urllib.request.Request(url.strip(), headers={"User-Agent": "App Entries"}),
                    timeout=20) as resp:
            data = resp.read(MAX_DOWNLOAD + 1)
    except OSError as e:
        raise IconError("Couldn't download it: %s" % getattr(e, "reason", e))
    if len(data) > MAX_DOWNLOAD:
        raise IconError("It's bigger than 2 MB, which is too big for an icon.")
    kind = check(data)
    name = os.path.basename(parsed.path) or "icon"
    os.makedirs(folder(env), exist_ok=True)
    target = _unique(os.path.splitext(name)[0] + "." + kind, env)
    with open(target, "wb") as f:
        f.write(data)
    return target


def add_data(data: bytes, name: str, env=None) -> str:
    """Save an SVG or PNG given as bytes (unless it's already there) and
    return its path."""
    kind = check(data)
    for existing in list_icons(env):
        if os.path.getsize(existing) == len(data):
            with open(existing, "rb") as f:
                if f.read() == data:
                    return existing
    os.makedirs(folder(env), exist_ok=True)
    target = _unique(os.path.splitext(name)[0] + "." + kind, env)
    with open(target, "wb") as f:
        f.write(data)
    return target


def remove(path: str, env=None) -> None:
    if not in_library(path, env):
        raise IconError("Only icons in your library can be removed here.")
    os.unlink(path)


# ---------------------------------------------------------------------------
# Fitting a file onto the grid


def _length(value: Optional[str]) -> Optional[float]:
    m = re.match(r"\s*([\d.]+)", value or "")
    return float(m.group(1)) if m else None


def _viewbox(root) -> List[float]:
    vb = root.get("viewBox")
    if vb:
        nums = [float(n) for n in re.split(r"[\s,]+", vb.strip()) if n]
        if len(nums) == 4 and nums[2] > 0 and nums[3] > 0:
            return nums
    w, h = _length(root.get("width")) or 24.0, _length(root.get("height")) or 24.0
    return [0.0, 0.0, w, h]



def _prefix_ids(root, prefix: str) -> None:
    ids = {}
    for el in root.iter():
        i = el.get("id")
        if i:
            ids[i] = prefix + i
            el.set("id", prefix + i)
    if not ids:
        return
    pattern = re.compile(r"url\(\s*#([^)\s]+)\s*\)")
    for el in root.iter():
        for k, v in list(el.attrib.items()):
            if "url(#" in v:
                el.set(k, pattern.sub(lambda m: "url(#%s)" % ids.get(m.group(1), m.group(1)), v))
            elif k in ("href", "{%s}href" % XLINK_NS) and v.startswith("#") and v[1:] in ids:
                el.set(k, "#" + ids[v[1:]])
        if el.text and "url(#" in el.text:
            el.text = pattern.sub(lambda m: "url(#%s)" % ids.get(m.group(1), m.group(1)), el.text)


def _strip(root) -> None:
    for bad in ("{%s}script" % SVG_NS, "{%s}foreignObject" % SVG_NS, "{%s}metadata" % SVG_NS,
                "{%s}title" % SVG_NS):
        for parent in root.iter():
            for child in [c for c in parent if c.tag == bad]:
                parent.remove(child)
    for el in root.iter():
        for k in [k for k in el.attrib if k.startswith("on")]:
            del el.attrib[k]


def _fit(vb: List[float]) -> str:
    """Transform from the file's viewBox to the 960 grid, centred."""
    minx, miny, w, h = vb
    scale = GRID / max(w, h)
    dx = (GRID - w * scale) / 2 - minx * scale
    dy = (GRID - h * scale) / 2 - miny * scale
    return "translate(%g %g) scale(%g)" % (dx, dy, scale), scale


_counter = [0]

_SHAPES = ("path", "rect", "circle", "ellipse", "polygon", "polyline", "line", "use", "text")
_PAINT_KEYS = ("fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "opacity",
               "fill-opacity", "stroke-opacity", "fill-rule", "display", "visibility", "color")


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _class_rules(root) -> dict:
    """Simple `.name { prop: value }` rules from <style> elements."""
    rules = {}
    for st in root.iter("{%s}style" % SVG_NS):
        for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", st.text or ""):
            decls = dict((k.strip(), v.strip()) for k, v in
                         (d.split(":", 1) for d in body.split(";") if ":" in d))
            for one in sel.split(","):
                one = one.strip()
                if re.fullmatch(r"\.[\w-]+", one):
                    rules.setdefault(one[1:], {}).update(decls)
    return rules


def _declared(el, rules) -> dict:
    """Paint properties set on this element: class rules, then attributes,
    then its style attribute (later wins, as in CSS)."""
    out = {}
    for cls in (el.get("class") or "").split():
        out.update({k: v for k, v in rules.get(cls, {}).items() if k in _PAINT_KEYS})
    out.update({k: el.get(k) for k in _PAINT_KEYS if el.get(k) is not None})
    for d in (el.get("style") or "").split(";"):
        if ":" in d:
            k, v = (x.strip() for x in d.split(":", 1))
            if k in _PAINT_KEYS:
                out[k] = v
    return out


def _visible(value: Optional[str]) -> bool:
    return value is not None and value.strip() not in ("none", "transparent")


def _set_paint(el, **props) -> None:
    """Write paint as attributes, removing the same properties from class
    and style so the new values are the ones that count."""
    style = el.get("style")
    if style:
        kept = [d for d in style.split(";") if ":" in d and d.split(":", 1)[0].strip() not in props]
        if kept:
            el.set("style", ";".join(kept))
        else:
            del el.attrib["style"]
    for k, v in props.items():
        if v is None:
            el.attrib.pop(k, None)
        else:
            el.set(k, v)


def _walk(el, inherited, rules, visit):
    """Call visit(shape, computed) for every shape, with its computed paint."""
    computed = dict(inherited)
    computed.update(_declared(el, rules))
    tag = _local(el.tag)
    if tag in ("defs", "clipPath", "mask", "symbol", "linearGradient", "radialGradient", "pattern", "style"):
        return
    if computed.get("display") == "none":
        return
    if tag in _SHAPES:
        visit(el, computed)
    for child in list(el):
        _walk(child, computed, rules, visit)


def _resolve(value: str, computed: dict, ink_default: str) -> str:
    if value.strip() == "currentColor":
        c = computed.get("color")
        return c if _visible(c) and c != "currentColor" else ink_default
    return value


# -- paths: absolute subpaths, to tell outer edges from holes --------------

_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}


_NUMBER = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


def _read_args(d: str, i: int, cmd: str):
    """Read one set of arguments for `cmd` starting at d[i]. Arc flags are
    single digits that may be written run together ("a1 1 0 00-.5.5")."""
    n = _ARGS[cmd.upper()]
    args = []
    while len(args) < n:
        while i < len(d) and d[i] in " ,\t\r\n":
            i += 1
        if i >= len(d):
            return None, i
        if cmd.upper() == "A" and len(args) in (3, 4):
            if d[i] not in "01":
                return None, i
            args.append(float(d[i]))
            i += 1
            continue
        m = _NUMBER.match(d, i)
        if not m:
            return None, i
        args.append(float(m.group(0)))
        i = m.end()
    return args, i


def subpaths(d: str) -> List[List[tuple]]:
    """Split path data into subpaths of absolute (command, args) segments."""
    return _parse(d)[0]


def _parse(d: str):
    """(subpaths, whether all of the data could be read)."""
    d = d or ""
    ok = True
    out, cur, i = [], [], 0
    x = y = sx = sy = 0.0
    cmd = None
    while i < len(d):
        c = d[i]
        if c in " ,\t\r\n":
            i += 1
            continue
        if c.isalpha():
            if c.upper() not in _ARGS:
                ok = False
                break
            cmd = c
            i += 1
            if cmd in "Zz":
                if cur:
                    cur.append(("Z", ()))
                x, y = sx, sy
                cmd = None
            continue
        if cmd is None:
            ok = False
            break
        args, i = _read_args(d, i, cmd)
        if args is None:
            ok = False
            break
        rel = cmd.islower()
        up = cmd.upper()
        if up == "M":
            if cur:
                out.append(cur)
            x, y = (x + args[0], y + args[1]) if rel else (args[0], args[1])
            sx, sy = x, y
            cur = [("M", (x, y))]
            cmd = "l" if rel else "L"  # extra pairs are line-tos
            continue
        if up == "H":
            x = x + args[0] if rel else args[0]
            cur.append(("L", (x, y)))
        elif up == "V":
            y = y + args[0] if rel else args[0]
            cur.append(("L", (x, y)))
        elif up == "A":
            ex, ey = (x + args[5], y + args[6]) if rel else (args[5], args[6])
            cur.append(("A", tuple(args[:5]) + (ex, ey)))
            x, y = ex, ey
        else:
            pts = []
            for k in range(0, len(args), 2):
                px, py = args[k], args[k + 1]
                pts += [x + px, y + py] if rel else [px, py]
            cur.append((up, tuple(pts)))
            x, y = pts[-2], pts[-1]
    if cur:
        out.append(cur)
    return out, ok


def _sub_area(sub) -> float:
    pts = []
    for c, a in sub:
        if c == "A":
            pts.append(a[-2:])
        else:
            pts += [a[k:k + 2] for k in range(0, len(a), 2)]
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1])) / 2 if len(pts) > 2 else 0.0


def _sub_d(sub) -> str:
    return "".join(c + " ".join("%g" % v for v in a) for c, a in sub)


def _points(sub):
    pts = []
    for c, a in sub:
        if c == "A":
            pts.append(a[-2:])
        elif a:
            pts += [a[k:k + 2] for k in range(0, len(a), 2)]
    return pts


def _inside(pt, poly) -> bool:
    x, y = pt
    hit = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-12) + x1:
            hit = not hit
    return hit


def outer_only(d: str) -> str:
    """Path data with only the outer outlines: those no other outline in the
    same path encloses. Holes, and islands inside holes, are left out."""
    subs, ok = _parse(d)
    if not ok or len(subs) < 2:
        return d  # can't read it all: outline everything rather than lose parts
    polys = [_points(x) for x in subs]
    keep = []
    for i, sub in enumerate(subs):
        if abs(_sub_area(sub)) < 1e-9:
            continue  # degenerate: nothing to outline
        probe = polys[i][0] if polys[i] else (0.0, 0.0)
        enclosed = any(j != i and len(polys[j]) > 2 and abs(_sub_area(subs[j])) > abs(_sub_area(sub))
                       and _inside(probe, polys[j]) for j in range(len(subs)))
        if not enclosed:
            keep.append(_sub_d(sub))
    return "".join(keep) or d


def symbol_svg(path: str, ink: Optional[str], border_width: float, border: str, inner: bool = True) -> str:
    """An SVG fragment drawing the file on the 960 grid: recoloured to `ink`
    (or in its own colours when ink is None), with an optional border that
    outlines the outer edges, and the inner ones too when `inner`."""
    with open(path, "rb") as f:
        data = f.read()
    if check(data, path) == "png":
        href = "data:image/png;base64," + base64.b64encode(data).decode()
        return '<image x="0" y="0" width="960" height="960" xlink:href="%s" href="%s"/>' % (href, href)
    root = ET.fromstring(data)
    _strip(root)
    _counter[0] += 1
    _prefix_ids(root, "ae%d-" % _counter[0])
    transform, scale = _fit(_viewbox(root))
    rules = _class_rules(root)
    base = {"fill": "#000000", "stroke": "none", "stroke-width": "1"}
    base.update(_declared(root, rules))
    out = []

    if border_width:
        back = ET.fromstring(ET.tostring(root))
        extra = 2 * border_width / scale

        def outline(el, c):
            fill_on = _visible(c.get("fill"))
            stroke_on = _visible(c.get("stroke"))
            if not (fill_on or stroke_on):
                _set_paint(el, fill="none", stroke="none")
                return
            own = (_length(c.get("stroke-width")) or 1.0) if stroke_on else 0.0
            # Only the outline: a filled copy would paint over holes (Discord's eyes).
            _set_paint(el, fill="none", stroke=border,
                       **{"stroke-width": "%g" % (own + extra), "stroke-linejoin": "round",
                          "stroke-linecap": "round", "opacity": None, "fill-opacity": None,
                          "stroke-opacity": None})
            if fill_on and not inner and _local(el.tag) == "path":
                el.set("d", outer_only(el.get("d", "")))

        _walk(back, {}, rules, lambda el, c: outline(el, {**base, **c}))
        for st in list(back.iter("{%s}style" % SVG_NS)):
            st.text = ""
        out.append('<g transform="%s">%s</g>' % (transform, _children(back)))

    front = root
    if ink:
        def paint(el, c):
            fill = _resolve(c.get("fill", "#000000"), c, ink)
            stroke = _resolve(c.get("stroke", "none"), c, ink)
            _set_paint(el, fill=ink if _visible(fill) else "none", stroke=ink if _visible(stroke) else "none")
        _walk(front, {}, rules, lambda el, c: paint(el, {**base, **c}))
        for st in front.iter("{%s}style" % SVG_NS):
            st.text = re.sub(r"(fill|stroke|stop-color)\s*:\s*(?!none)[^;}]+", r"\1:%s" % ink, st.text or "")
    else:
        # Keep its own colours, but currentColor has nothing to inherit here.
        def dark(el, c):
            for k in ("fill", "stroke"):
                if c.get(k, "").strip() == "currentColor":
                    _set_paint(el, **{k: "#1b1b1f"})
        _walk(front, {}, rules, lambda el, c: dark(el, {**base, **c}))
    root_paint = {k: v for k, v in _declared(root, rules).items() if k in ("fill", "stroke", "stroke-width",
                                                                          "stroke-linecap", "stroke-linejoin")}
    attrs = "".join(' %s="%s"' % (k, v.replace('"', "&quot;")) for k, v in root_paint.items()
                    if not (ink and k in ("fill", "stroke")))
    out.append('<g transform="%s"%s>%s</g>' % (transform, attrs, _children(front)))
    return "".join(out)


def _children(el) -> str:
    return "".join(_inner(c) for c in el)


def _inner(el) -> str:
    text = ET.tostring(el, encoding="unicode")
    # Drop the namespace declaration ET adds; the outer <svg> has it.
    text = text.replace(' xmlns="%s"' % SVG_NS, "").replace(' xmlns:xlink="%s"' % XLINK_NS, "")
    return text


def is_one_colour(path: str) -> bool:
    """Whether an SVG uses a single colour (so recolouring keeps its look).
    PNGs and multi-coloured SVGs count as not."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        if check(data, path) != "svg":
            return False
        text = data.decode("utf-8", "replace")
    except (OSError, IconError):
        return False
    colours = set()
    for m in re.finditer(r"(?:fill|stroke|stop-color)\s*[:=]\s*\"?\s*(#[0-9a-fA-F]{3,8}|rgb\([^)]*\)|[a-zA-Z]+)",
                         text):
        v = m.group(1).lower()
        if v not in ("none", "transparent", "currentcolor", "inherit"):
            colours.add(v)
    return len(colours) <= 1


def title_of(svg_text: str) -> str:
    """The <title> inside SVG code, for a default name."""
    try:
        root = ET.fromstring(svg_text.strip().encode("utf-8"))
    except ET.ParseError:
        return ""
    for t in root.iter("{%s}title" % SVG_NS):
        if (t.text or "").strip():
            return t.text.strip()
    return ""


def check_text(svg_text: str) -> None:
    """Raise IconError if pasted text isn't a usable SVG."""
    text = svg_text.strip()
    if not text:
        raise IconError("Paste the SVG code first.")
    if check(text.encode("utf-8")) != "svg":
        raise IconError("That isn't SVG code.")


def add_text(svg_text: str, name: str, env=None) -> str:
    """Save pasted SVG code into the library as <name>.svg."""
    check_text(svg_text)
    os.makedirs(folder(env), exist_ok=True)
    target = _unique((name.strip() or "pasted icon") + ".svg", env)
    with open(target, "w", encoding="utf-8") as f:
        f.write(svg_text.strip() + "\n")
    return target
