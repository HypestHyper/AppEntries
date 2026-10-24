"""The app's single stylesheet, generated from the palette."""
import re

from gi.repository import Gdk, GLib, Gtk

from .. import theme

EASE = "cubic-bezier(0.2, 0, 0, 1)"
SPRING = "cubic-bezier(0.34, 1.36, 0.64, 1)"
FONT = '"Google Sans Flex", "Google Sans", sans-serif'
ICON = '"Material Symbols Rounded"'

SIZES = {"compact": 0.8, "default": 0.9, "large": 1.0}

CSS = """
window, dialog {{ font-family: {FONT}; color: {ON_SURFACE}; }}
window {{ background: {SURFACE_DIM}; }}
window.dialog {{ background: {SURFACE_CONTAINER}; }}
window, window.background {{ border-radius: 0; }}

headerbar {{
  background: {SURFACE_DIM}; box-shadow: none; border: none;
  min-height: 64px; padding: 0 12px; color: {ON_SURFACE};
}}
window.dialog headerbar {{ background: {SURFACE_CONTAINER}; }}

/* Type scale */
.app-title {{ font-size: 24px; font-weight: 700; }}
.display {{ font-size: 28px; font-weight: 700; }}
.title {{ font-size: 20px; font-weight: 700; }}
.heading {{ font-size: 15px; font-weight: 700; }}
.subheading {{ font-size: 13px; font-weight: 600; }}
.body {{ font-size: 14px; }}
.small {{ font-size: 13px; }}
.tiny {{ font-size: 11.5px; }}
.dim {{ color: {ON_SURFACE_VARIANT}; }}
.faint {{ color: {OUTLINE}; }}
.accent {{ color: {PRIMARY}; }}
.error-text {{ color: {ERROR}; }}
.warn-text {{ color: {TERTIARY}; }}
.mono {{ font-family: monospace; font-size: 12.5px; }}
.tnum {{ font-feature-settings: "tnum"; }}

.icon {{
  font-family: {ICON}; font-size: 20px; font-weight: 400;
  font-variation-settings: "FILL" 0, "wght" 400, "opsz" 24;
  min-width: 20px;
}}
.icon.filled {{ font-variation-settings: "FILL" 1, "wght" 500, "opsz" 24; }}
.icon.big {{ font-size: 64px; min-width: 64px; }}

/* Theme-proofing */
button, button:hover, button:checked, button:active, dropdown, switch, check, radio,
row, row:hover {{ transform: none; }}
button label {{ font-weight: inherit; font-size: inherit; letter-spacing: inherit; }}
label {{ font-size: inherit; letter-spacing: inherit; }}
box {{ margin: 0; padding: 0; border-spacing: 0; }}

/* Buttons */
button {{
  border: none; box-shadow: none; background-image: none; outline: none;
  border-radius: 20px; min-height: 40px; padding: 0 20px;
  font-weight: 600; font-size: 14px;
  background-color: {SECONDARY_CONTAINER}; color: {ON_SECONDARY_CONTAINER};
  transition: border-radius 200ms {EASE}, background-color 200ms {EASE}, color 200ms {EASE};
}}
button:hover {{ background-color: {SECONDARY_CONTAINER_HOVER}; }}
button:active {{ border-radius: 10px; }}
button:focus-visible {{ box-shadow: 0 0 0 2px {PRIMARY}; }}
button:disabled {{ opacity: .45; }}
button.filled {{ background-color: {PRIMARY}; color: {ON_PRIMARY}; }}
button.filled:hover {{ background-color: {PRIMARY_HOVER}; }}
button.tonal {{ background-color: {SECONDARY_CONTAINER}; color: {ON_SECONDARY_CONTAINER}; }}
button.tonal:checked {{ background-color: {PRIMARY}; color: {ON_PRIMARY}; }}
button.text {{ background-color: transparent; color: {PRIMARY}; }}
button.text:hover {{ background-color: alpha({PRIMARY}, .10); }}
button.outlined {{ background-color: transparent; color: {PRIMARY}; box-shadow: inset 0 0 0 1px {OUTLINE}; }}
button.danger {{ background-color: {ERROR_CONTAINER}; color: {ON_ERROR_CONTAINER}; }}
button.danger:hover {{ background-color: {ERROR_HOVER}; color: white; }}
button.small {{ min-height: 32px; padding: 0 14px; font-size: 13px; border-radius: 16px; }}
button.small:active {{ border-radius: 8px; }}
button.circle {{ min-width: 40px; min-height: 40px; padding: 0; }}
button.circle.small {{ min-width: 32px; min-height: 32px; }}
button.toggled, button.circle:checked {{ background-color: {PRIMARY}; color: {ON_PRIMARY}; border-radius: 10px; }}
button.flat {{ background-color: transparent; color: {ON_SURFACE_VARIANT}; }}
button.flat:hover {{ background-color: alpha({ON_SURFACE}, .08); }}
menubutton > button {{ min-width: 40px; padding: 0; }}

/* Connected button group */
.group > button {{
  border-radius: 6px; margin: 0 1px; min-height: 36px; font-size: 13px; padding: 0 16px;
}}
.group > button:first-child {{ border-radius: 18px 6px 6px 18px; }}
.group > button:last-child {{ border-radius: 6px 18px 18px 6px; }}
.group > button:checked {{ background-color: {PRIMARY}; color: {ON_PRIMARY}; border-radius: 18px; }}
.group > button:active {{ border-radius: 4px; }}

/* Filter chips */
button.filter {{
  border-radius: 8px; padding: 4px 12px; min-height: 24px; font-weight: 500; font-size: 13px;
  background-color: transparent; color: {ON_SURFACE_VARIANT};
  box-shadow: inset 0 0 0 1px {OUTLINE_VARIANT};
}}
button.filter:hover {{ background-color: alpha({ON_SURFACE}, .06); }}
button.filter:checked {{ background-color: {SECONDARY_CONTAINER}; color: {ON_SECONDARY_CONTAINER}; box-shadow: none; }}
button.filter:active {{ border-radius: 8px; }}

/* Tab bar */
.tabbar {{ background: {SURFACE_CONTAINER_LOW}; border-radius: 24px; padding: 4px; }}
.tabbar > button {{
  background-color: transparent; color: {ON_SURFACE_VARIANT};
  border-radius: 20px; min-height: 40px; padding: 0 14px; font-weight: 600;
  transition: border-radius 220ms {EASE}, background-color 220ms {EASE}, color 220ms {EASE};
}}
.tabbar > button:hover {{ background-color: {SURFACE_CONTAINER_HIGH}; }}
.tabbar > button.icon-tab {{ padding: 0 12px; }}
.tabbar > button:checked {{ background-color: {SECONDARY_CONTAINER}; color: {ON_SECONDARY_CONTAINER}; border-radius: 12px; }}
.tabbar > button:checked .icon {{ font-variation-settings: "FILL" 1, "wght" 500, "opsz" 24; }}
.tabcount {{ font-size: 12px; font-weight: 600; color: {OUTLINE}; }}
.tabbar > button:checked .tabcount {{ color: {ON_SECONDARY_CONTAINER}; }}

/* Surfaces */
.card {{ background: {SURFACE_CONTAINER}; border-radius: 28px; padding: 20px; }}
.card-inner {{ background: {SURFACE_CONTAINER_HIGH}; border-radius: 20px; padding: 16px; }}
.hero {{ background: {PRIMARY_CONTAINER}; color: {ON_PRIMARY_CONTAINER}; border-radius: 32px; padding: 20px 24px; }}
.hero .dim {{ color: {ON_PRIMARY_CONTAINER}; opacity: .8; }}
.warn-card {{ background: {ERROR_CONTAINER}; color: {ON_ERROR_CONTAINER}; border-radius: 20px; padding: 16px; }}
expander.advanced > title {{ font-weight: 600; }}
.floating-toolbar {{ background: {SURFACE_CONTAINER_HIGHEST}; border-radius: 28px; box-shadow: 0 4px 16px {SHADOW_M}; }}
separator {{ background: {OUTLINE_VARIANT}; min-height: 1px; min-width: 1px; }}

/* Status chips */
.chip {{
  border-radius: 999px; padding: 6px 14px; font-weight: 600; font-size: 13px;
  background: {SURFACE_CONTAINER_HIGHEST}; color: {ON_SURFACE};
}}
.chip.ok {{ background: {PRIMARY_CONTAINER}; color: {ON_PRIMARY_CONTAINER}; }}
.chip.warn {{ background: {TERTIARY_CONTAINER}; color: {ON_TERTIARY_CONTAINER}; }}
.chip.error {{ background: {ERROR_CONTAINER}; color: {ON_ERROR_CONTAINER}; }}
.chip .icon {{ font-size: 16px; min-width: 16px; }}
.badge {{ border-radius: 999px; padding: 2px 10px; font-size: 12px; font-weight: 600; }}
.badge.hidden {{ background: {TERTIARY_CONTAINER}; color: {ON_TERTIARY_CONTAINER}; }}
.badge.neutral {{ background: {SURFACE_CONTAINER_HIGHEST}; color: {ON_SURFACE_VARIANT}; }}
.badge.custom {{ background: {PRIMARY_CONTAINER}; color: {ON_PRIMARY_CONTAINER}; }}
.badge.error {{ background: alpha({ERROR}, .14); color: {ERROR}; }}
menubutton.flat > button {{ background-color: transparent; color: {ON_SURFACE_VARIANT}; }}
menubutton.flat > button:hover {{ background-color: alpha({ON_SURFACE}, .08); }}
menubutton.flat > button:checked {{ background-color: {SECONDARY_CONTAINER}; }}
.badge .icon {{ font-size: 14px; min-width: 14px; }}

/* App cards */
gridview {{ background: transparent; color: {ON_SURFACE}; padding: 4px 0 96px 0; }}
/* The default theme spaces out every box inside a grid item; undo that. */
gridview > child box {{ margin: 0; padding: 0; border-spacing: 0; }}
gridview > child {{ padding: 6px; background: none; border-radius: 34px; outline: none; }}
gridview > child:focus-visible {{ box-shadow: inset 0 0 0 2px {PRIMARY}; }}
gridview > child:hover, gridview > child:selected {{ background: none; }}
.app-card {{
  background: {SURFACE_CONTAINER}; border-radius: 28px; padding: 16px 18px 12px 18px;
  border: 2px solid transparent;
  transition: background-color 220ms {EASE}, border-radius 260ms {SPRING}, box-shadow 220ms {EASE},
              border-color 220ms {EASE};
  box-shadow: 0 1px 2px {SHADOW_S};
}}
.app-card:hover {{ background: {SURFACE_CONTAINER_HIGH}; box-shadow: 0 4px 14px {SHADOW_M}; }}
.app-card.is-hidden {{ background: {SURFACE_CONTAINER_LOW}; border-radius: 20px; box-shadow: inset 0 0 0 1px {OUTLINE_VARIANT}; }}
.app-card.is-hidden:hover {{ background: {SURFACE_CONTAINER}; }}
.icon-tile {{
  background: {SURFACE_CONTAINER_HIGHEST}; border-radius: 18px; padding: 8px;
  transition: border-radius 300ms {SPRING}, background-color 220ms {EASE}, opacity 220ms {EASE};
}}
.app-card:hover .icon-tile {{ border-radius: 24px; }}
.app-card.is-custom {{ border-color: alpha({PRIMARY}, .55); }}
.app-card.is-custom:hover {{ border-color: alpha({PRIMARY}, .8); }}
.app-card.is-selected, .app-card.is-selected:hover {{ border-color: {PRIMARY}; background: alpha({PRIMARY}, .10); }}
.app-card.is-hidden .icon-tile {{ background: {SURFACE_CONTAINER_HIGH}; border-radius: 28px; opacity: .55; }}
.app-card.is-hidden .app-name {{ color: {ON_SURFACE_VARIANT}; }}
.card-switch-row {{ background: {SURFACE_CONTAINER_HIGH}; border-radius: 16px; padding: 6px 8px 6px 14px; }}
.app-card:hover .card-switch-row {{ background: {SURFACE_CONTAINER_HIGHEST}; }}
.app-card.is-hidden .card-switch-row {{ background: {TERTIARY_CONTAINER}; color: {ON_TERTIARY_CONTAINER}; }}

/* Switch */
switch {{
  min-width: 44px; min-height: 24px; border-radius: 16px; padding: 0;
  border: 2px solid {OUTLINE}; background: {SURFACE_CONTAINER_HIGHEST}; box-shadow: none;
  transition: background-color 250ms {EASE}, border-color 250ms {EASE};
}}
switch:checked {{ background: {PRIMARY}; border-color: {PRIMARY}; }}
switch:focus-visible {{ box-shadow: 0 0 0 2px {SURFACE_CONTAINER}, 0 0 0 4px {PRIMARY}; }}
switch image {{ color: transparent; }}
switch slider {{
  min-width: 16px; min-height: 16px; margin: 4px; border-radius: 999px;
  background: {OUTLINE}; border: none; box-shadow: none; outline: none;
  transition: min-width 250ms {SPRING}, min-height 250ms {SPRING}, margin 250ms {SPRING}, background-color 250ms {EASE};
}}
switch:checked slider {{ min-width: 20px; min-height: 20px; margin: 2px; background: {ON_PRIMARY}; }}
switch:hover slider {{ background: {ON_SURFACE_VARIANT}; }}
switch:checked:hover slider {{ background: {PRIMARY_CONTAINER}; }}
switch:disabled {{ opacity: .45; }}

/* Entries */
entry, spinbutton, searchbar entry {{
  background: {SURFACE_CONTAINER_HIGHEST}; border: none; border-radius: 12px;
  min-height: 38px; padding: 0 10px; color: {ON_SURFACE}; box-shadow: none; outline: none;
  caret-color: {PRIMARY};
}}
entry:focus-within, spinbutton:focus-within {{ box-shadow: inset 0 0 0 2px {PRIMARY}; }}
entry > image {{ color: {ON_SURFACE_VARIANT}; }}
entry selection {{ background: alpha({PRIMARY}, .35); }}
.search-entry {{ border-radius: 24px; min-height: 48px; padding: 0 16px; font-size: 15px; }}
.search-entry:focus-within {{ box-shadow: inset 0 0 0 2px {PRIMARY}; }}
.search-field {{ background: {SURFACE_CONTAINER_HIGHEST}; color: {ON_SURFACE}; border-radius: 24px; min-height: 48px;
  padding: 0 8px 0 16px; font-size: 15px; caret-color: {PRIMARY}; }}
.search-field:focus-within {{ box-shadow: inset 0 0 0 2px {PRIMARY}; }}
.search-field text selection {{ background: alpha({PRIMARY}, .35); }}
searchbar, searchbar > revealer > box {{ background: transparent; border: none; box-shadow: none; padding: 0; }}

/* Popovers and menus */
popover > contents, popover.menu > contents {{
  background: {SURFACE_CONTAINER_HIGH}; border-radius: 16px; padding: 6px; border: none;
  box-shadow: 0 6px 18px {SHADOW_M}; color: {ON_SURFACE};
}}
popover > arrow {{ background: {SURFACE_CONTAINER_HIGH}; border: none; }}
popover modelbutton {{ border-radius: 10px; min-height: 36px; padding: 0 12px; font-size: 14px; }}
popover modelbutton:hover, popover modelbutton:selected {{ background: {SECONDARY_CONTAINER}; }}
popover separator {{ margin: 4px 6px; }}
popover check, popover radio {{ margin-right: 10px; }}

/* Check and radio */
check, radio {{
  border: 2px solid {ON_SURFACE_VARIANT}; background: transparent; min-width: 14px; min-height: 14px;
  box-shadow: none; -gtk-icon-source: none;
}}
check {{ border-radius: 4px; }}
radio {{ border-radius: 999px; }}
check:checked, radio:checked {{ background: {PRIMARY}; border-color: {PRIMARY}; color: {ON_PRIMARY}; }}
check:checked {{ -gtk-icon-source: -gtk-icontheme("object-select-symbolic"); }}
radio:checked {{ box-shadow: inset 0 0 0 3px {SURFACE_CONTAINER_HIGH}; }}

/* Scrollbars */
scrollbar {{ background: transparent; border: none; }}
scrollbar slider {{ background: {OUTLINE_VARIANT}; border-radius: 999px; min-width: 6px; min-height: 6px; margin: 0; border: none; }}
scrollbar slider:hover {{ background: {OUTLINE}; }}

/* Tooltip and snackbar */
tooltip, tooltip.background {{ background: {INVERSE_SURFACE}; color: {INVERSE_ON_SURFACE}; border-radius: 8px; border: none; box-shadow: none; }}
tooltip label {{ font-family: {FONT}; font-size: 13px; }}
.snackbar {{
  background: {INVERSE_SURFACE}; color: {INVERSE_ON_SURFACE}; border-radius: 14px;
  padding: 12px 16px; margin: 18px; box-shadow: 0 6px 22px {SHADOW_L};
  font-size: 14px; font-weight: 500;
}}
.snackbar button {{ background-color: transparent; color: {INVERSE_PRIMARY}; min-height: 32px; padding: 0 12px; border-radius: 16px; }}
.snackbar button:hover {{ background-color: alpha({INVERSE_PRIMARY}, .12); }}
.selection-bar {{
  background: {SURFACE_CONTAINER_HIGHEST}; border-radius: 28px; padding: 8px 10px 8px 20px; margin: 14px;
  box-shadow: 0 6px 22px {SHADOW_L};
}}
.selection-bar .sel-count {{ font-weight: 600; margin-right: 6px; }}

/* Window controls */
.winctl button {{
  min-width: 32px; min-height: 32px; padding: 0; border-radius: 999px;
  background-color: transparent; color: {ON_SURFACE_VARIANT};
}}
.winctl button:hover {{ background-color: alpha({ON_SURFACE}, .10); }}
.winctl button.close:hover {{ background-color: {ERROR_HOVER}; color: white; }}
.winctl .icon {{ font-size: 18px; min-width: 18px; }}

button.related-hint {{
  background-color: transparent; color: {PRIMARY}; min-height: 0; padding: 2px 6px; margin-left: -6px;
  border-radius: 8px; font-weight: 500;
}}
button.related-hint:hover {{ background-color: alpha({PRIMARY}, .10); }}

textview.textarea, textview.textarea > text {{
  background: {SURFACE_CONTAINER_HIGHEST}; color: {ON_SURFACE}; caret-color: {PRIMARY};
}}
textview.textarea {{ border-radius: 12px; }}
textview.textarea:focus-within {{ box-shadow: inset 0 0 0 2px {PRIMARY}; }}

/* Floating action button (Material 3 extended FAB) */
button.fab {{
  background-color: {PRIMARY_CONTAINER}; color: {ON_PRIMARY_CONTAINER};
  min-height: 56px; padding: 0 22px; border-radius: 18px; font-size: 15px;
  box-shadow: 0 3px 10px {SHADOW_M};
  transition: border-radius 260ms {SPRING}, background-color 200ms {EASE}, box-shadow 200ms {EASE};
}}
button.fab:hover {{ background-color: mix({PRIMARY_CONTAINER}, {ON_PRIMARY_CONTAINER}, .08);
  box-shadow: 0 6px 16px {SHADOW_M}; }}
button.fab:active {{ border-radius: 28px; }}
button.fab .icon {{ font-size: 24px; min-width: 24px; }}
button.fab.tonal {{ background-color: {SECONDARY_CONTAINER}; color: {ON_SECONDARY_CONTAINER}; }}
button.fab.tonal:hover {{ background-color: mix({SECONDARY_CONTAINER}, {ON_SECONDARY_CONTAINER}, .08); }}
.autostart-row {{ padding: 14px 16px; }}
.history-row {{ padding: 14px 16px; }}
.default-glyph {{ font-size: 26px; min-width: 36px; color: {PRIMARY}; }}
button.default-pick {{ min-height: 40px; padding: 0 12px; border-radius: 20px; }}
button.pick-row {{ padding: 6px 10px; border-radius: 12px; }}
.history-row.is-off .app-name {{ color: {ON_SURFACE_VARIANT}; }}
.autostart-row.is-off .icon-tile {{ opacity: .55; }}
.autostart-row.is-off .app-name {{ color: {ON_SURFACE_VARIANT}; }}
.helper-row.is-off .icon-tile {{ opacity: .55; }}
.helper-row.is-off .app-name, .helper-row.is-off .dim {{ color: {ON_SURFACE_VARIANT}; }}
.helper-row.is-off {{ background: transparent; box-shadow: inset 0 0 0 1px {OUTLINE_VARIANT}; }}
list.pick-list {{ background: none; }}
list.pick-list > row {{ padding: 6px 8px; border-radius: 12px; }}
list.pick-list > row:hover {{ background: alpha({ON_SURFACE}, .06); }}

/* Explained options (card menu, Issues page) */
button.option {{
  background-color: transparent; color: {ON_SURFACE}; border-radius: 12px;
  padding: 8px 12px; min-height: 0; font-weight: 400;
}}
button.option:hover {{ background-color: {SECONDARY_CONTAINER}; }}
button.option:active {{ border-radius: 8px; }}
button.option .option-title {{ font-weight: 600; }}
button.option-danger .option-title, button.option-danger .icon {{ color: {ERROR}; }}
popover.options > contents {{ padding: 6px; }}
button.source-item {{ border-radius: 10px; min-height: 36px; padding: 0 12px; }}
button.source-item:hover {{ background: {SECONDARY_CONTAINER}; }}
.spinner-glyph {{ font-size: 32px; animation: spin 1s linear infinite; }}
@keyframes spin {{ to {{ transform: rotate(1turn); }} }}
.issue-row {{ padding: 2px 0; }}
.icon-tile.small-tile {{ padding: 4px; border-radius: 12px; }}

/* Empty state */
.empty-icon {{ color: {OUTLINE}; }}
.swatch {{ min-width: 40px; min-height: 40px; padding: 0; border-radius: 20px; }}
.swatch:checked {{ border-radius: 12px; box-shadow: 0 0 0 3px {SURFACE_CONTAINER}, 0 0 0 5px {ON_SURFACE}; }}
flowboxchild {{ padding: 0; background: none; }}
.swatch.swatch-small {{ min-width: 32px; min-height: 32px; border-radius: 16px; }}
.swatch.swatch-small:checked {{ border-radius: 10px; }}
button.palette-chip {{ min-height: 36px; padding: 0 14px 0 10px; border-radius: 18px; font-size: 13px;
  background-color: transparent; color: {ON_SURFACE}; box-shadow: inset 0 0 0 1px {OUTLINE_VARIANT}; }}
button.palette-chip:hover {{ background-color: alpha({ON_SURFACE}, .06); }}
button.palette-chip:checked {{ background-color: {SECONDARY_CONTAINER}; color: {ON_SECONDARY_CONTAINER};
  box-shadow: inset 0 0 0 2px {PRIMARY}; border-radius: 12px; }}
button.color-dot {{ padding: 2px; min-width: 0; min-height: 0; background: none; border-radius: 50%; box-shadow: none; }}
button.color-dot:hover {{ background: alpha({ON_SURFACE}, .08); }}
.swatch-f4f4f5, .swatch-1b1b1f {{ box-shadow: inset 0 0 0 1px {OUTLINE}; }}
gridview.icon-grid > child {{ padding: 4px; border-radius: 12px; }}
gridview.icon-grid > child:hover {{ background: alpha({ON_SURFACE}, .06); }}
gridview.icon-grid > child:selected {{ background: {SECONDARY_CONTAINER}; }}
.icon-cell {{ padding: 8px; }}
.picker-glyph {{
  font-family: "App Entries Symbols Outlined"; font-size: 28px; min-width: 44px; min-height: 44px;
  color: {ON_SURFACE};
}}
gridview.icon-grid.filled .picker-glyph {{ font-family: "App Entries Symbols Filled"; }}
.light-sample, .dark-sample {{ padding: 8px; border-radius: 12px; }}
.light-sample {{ background: #f4f4f5; }}
.dark-sample {{ background: #1b1b1f; }}
scale trough {{ min-height: 6px; border-radius: 999px; background: {SECONDARY_CONTAINER}; }}
scale highlight {{ border-radius: 999px; background: {PRIMARY}; }}
scale slider {{ min-width: 18px; min-height: 18px; border-radius: 999px; background: {PRIMARY}; margin: -7px; }}
scale value {{ color: {ON_SURFACE_VARIANT}; font-size: 13px; }}
"""

REDUCE_MOTION = "* { transition: none; }"
# Without a compositor, shadows around popups show as black frames. Shadows
# inside the window are fine.
NO_COMPOSITOR = "popover > contents, tooltip { box-shadow: none; }"


def scale_px(css: str, f: float) -> str:
    """Scale every Npx; keep hairlines and 999px pills; fonts scale less."""
    if f == 1.0:
        return css

    def repl(font: bool):
        def inner(m):
            v = float(m.group(1))
            if v <= 2 or v >= 999:
                return m.group(0)
            nv = v * (1 - (1 - f) * 0.6) if font else v * f
            if font:
                nv = max(10, nv)
            return "%dpx" % round(nv)
        return inner

    out = []
    for decl in re.split(r"(;|\{|\})", css):
        is_font = decl.strip().startswith("font-size")
        out.append(re.sub(r"(-?\d+(?:\.\d+)?)px", repl(is_font), decl))
    return "".join(out)


def load_css(provider: Gtk.CssProvider, css: str) -> None:
    if (Gtk.get_major_version(), Gtk.get_minor_version()) >= (4, 12):
        provider.load_from_string(css)
    elif Gtk.get_minor_version() >= 9:
        provider.load_from_data(css, -1)
    else:
        provider.load_from_data(css.encode())


class Style:
    """Owns the CSS providers. Recolours and rescales without touching widgets."""

    def __init__(self, seed: str = theme.DEFAULT_SEED, size: str = "default", dark: bool = True,
                 preset: str = ""):
        """`seed` is the accent (six hex digits), or "" to use the preset's own."""
        self.display = Gdk.Display.get_default()
        self.seed, self.dark, self.preset = seed, dark, preset
        self.palette = theme.palette(seed, dark, preset)
        self._set_gtk_dark(dark)
        self.factor = SIZES.get(size, 0.9)
        self.main = Gtk.CssProvider()
        self.motion = Gtk.CssProvider()
        self.flat = Gtk.CssProvider()
        prio = Gtk.STYLE_PROVIDER_PRIORITY_USER
        Gtk.StyleContext.add_provider_for_display(self.display, self.main, prio + 1)
        Gtk.StyleContext.add_provider_for_display(self.display, self.motion, prio + 2)
        Gtk.StyleContext.add_provider_for_display(self.display, self.flat, prio + 3)
        if not self.display.is_composited():
            load_css(self.flat, NO_COMPOSITOR)
        self._anim = 0
        self.reduced = False
        self._reload()

    def _reload(self, pal=None):
        css = CSS.format(FONT=FONT, ICON=ICON, EASE=EASE, SPRING=SPRING, **(pal or self.palette))
        css += "".join(".swatch-%s { background-color: #%s; }\n" % (s, s)
                       for s, _n in theme.SEEDS + theme.EXTRA_COLORS)
        load_css(self.main, scale_px(css, self.factor))

    def rgb(self, role: str):
        h = self.palette[role].lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def set_size(self, factor: float):
        if factor != self.factor:
            self.factor = factor
            self._reload()

    def set_reduce_motion(self, on: bool):
        load_css(self.motion, REDUCE_MOTION if on else "")
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.set_property("gtk-enable-animations", not on)
        self.reduced = on

    def _set_gtk_dark(self, dark):
        # So the few stock GTK windows (About) match the app.
        from .appearance import set_gtk_dark
        set_gtk_dark(Gtk.Settings.get_default(), dark)

    def recolor(self, seed: str = None, dark: bool = None, animate: bool = True, preset: str = None):
        """Switch accent, palette and/or light/dark, blending over ~300 ms."""
        self.seed = self.seed if seed is None else seed
        self.preset = self.preset if preset is None else preset
        if dark is not None and dark != self.dark:
            self.dark = dark
            self._set_gtk_dark(dark)
        old, new = self.palette, theme.palette(self.seed, self.dark, self.preset)
        if old == new:
            return
        self.palette = new
        if not animate or self.reduced:
            self._reload()
            return
        self._anim += 1
        token, frames, done = self._anim, 8, 0

        def step():
            nonlocal done
            if token != self._anim:
                return False
            done += 1
            self._reload(theme.mix_palette(old, new, done / frames))
            return done < frames

        GLib.timeout_add(36, step)
