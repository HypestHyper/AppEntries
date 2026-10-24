# Changelog

## Unreleased

- When a tab is empty because of the filters (search, source, Hidden or Not in menus), it says how many apps they leave out and offers to lift each one, or all at once. While searching, it counts only apps that match the search.
- The counts on the tabs and at the top are totals: the search, the source and the Hidden and Not in menus switches don't change them.
- Starts about twice as fast, most of all with large icon themes like Papirus: nothing waits for the icon theme before the window appears, and pages, windows and network code load when they're first used.
- Uninstall apps, whatever installed them: Flatpak, Snap, AppImage, Steam, Distrobox, or the system's package manager (pacman, apt, dnf, zypper, rpm-ostree, xbps, apk, eopkg, Portage, Nix). It replaces Remove AppImage.
- Before anything runs, it shows what goes, the packages and apps that need it or go with it, apps that stay but stop working, and whether it's a default app or starts at login, along with the exact command. Package managers are asked first with their own dry run.
- Data folders, unused Flatpak runtimes and advanced options (like removing what depends on it, or skipping dependency checks) are off unless turned on, each with a warning.
- Commands that need a password open in your terminal, so the package manager asks there. Packages the system, your desktop or App Entries needs are never offered.
- Uninstall several apps at once from Select: one command per package manager.
- History keeps a Reinstall button for uninstalled apps; `--uninstall` on the command line.
- Apps exported from Distrobox containers get their own source badge.
- Helper apps…: shortcuts to Flatseal, Warehouse, Gear Lever, ProtonUp-Qt, Protontricks, BoxBuddy, DistroShelf, GNOME Settings, KDE's app permissions, your software centre and Steam, opened on the app where they allow it.
- Commands that need a password go to your terminal as they are; the terminal handles the rest.

## 1.0.3 — 2026-10-21

- Accent from your desktop: follows GNOME's and KDE's accent setting, or the colours theme tools like Noctalia, matugen and wallust write to ~/.config/gtk-4.0/gtk.css, and changes live with them.
- Palettes: Catppuccin, Gruvbox, Nord, Rosé Pine, Tokyo Night, Everforest and Solarized, in light and dark.
- Any accent colour, with a colour picker.
- Settings are kept on systems without a D-Bus session.
- Autostart says exactly how to run login programs on window managers, including systems without systemd.

## 1.0.2 — 2026-10-20

- Default apps tab: choose which app opens links, email, folders, text, PDFs, pictures, videos, music and archives.
- Web apps: dark mode, and a window name for docks and window rules.
- Bordered icon tiles no longer show a thin line of the tile's colour around the outside. Redraw existing icons with Select → Style icons.
- Lists that show two apps with the same name now say which is which.

## 1.0.1 — 2026-10-20

- History of every change, each with Undo, kept between sessions (Ctrl+H; Ctrl+Z undoes the last one).
- Web apps can be deleted from their card.
- Paste SVG lists where to find icons.

## 1.0.0 — 2026-10-20

First release.

- Every installed app in one searchable grid: system packages, Flatpak, Snap, AppImage, Steam and your own launchers, filterable by source.
- Hide or show apps with one switch, or several at once. Hidden apps still open links and files. Everything can be undone, and system files are never changed.
- Edit any app's entry, with a live view of the file; Restore original puts the system version back.
- Issues tab: leftover files, missing programs and duplicates, each explained with a fix.
- New launchers for scripts and commands, and web apps: a site in its own window, sharing your browser's sign-ins.
- Styled icons from 4,000 Material Symbols or your own SVGs, with tile, shading, border and a built-in colour picker.
- Autostart tab: turn login programs on and off, add apps and commands.
- Remove AppImage: the file and everything set up for it, with a full list first.
- Export and import your changes, and a command line for scripts.
- Updates tab: checks GitHub releases and updates with one button.
