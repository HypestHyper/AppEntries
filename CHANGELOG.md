# Changelog

## 1.0.7 — 2026-11-13

- Apps you edited, then uninstalled some other way (a terminal, a software centre), no longer linger in menus. Uninstalling removes only the app's own files, so your edited copy stays behind; App Entries now hides it (NoDisplay=true, which every launcher honours) and keeps your edits. When the app is reinstalled, the hide comes off and your edits apply again. Both happen once, show a message with Undo, and are options on the Issues page.
- The card says when that happened, and Issues lists these copies apart as "Uninstalled, your edits remain", with Remove.
- Edited copies of system apps get a TryExec naming their program, so desktops that honour it (GNOME, KDE, Xfce) leave them out of menus straight away. A TryExec the entry came with is kept.
- An Open button on each card starts the app, hidden ones included.
- Default apps can be set per file type: Each type opens a category (Pictures, Videos…) so, say, PNG and TIFF can open in different apps, each with its own Reset.
- By app, at the bottom of Default apps, lists every file type one app says it opens, including ones no category covers (like .xcf or .psd), what opens each now, and Make default, or the app for all of them. File types… in a card's ⋯ menu opens it for that app.
- Sort the list newest first, by when each app appeared on this computer. Apps that appeared since App Entries last looked are marked New until you close it. (Package managers keep build dates on their files, so App Entries notes when it first sees each app instead; the first time, it starts from the file times and marks nothing.)

## 1.0.6 — 2026-11-10

- Screenshots in the README and the app's store listing, in dark mode.
- Under the hood: the code follows Ruff's checks (newer type hints, f-strings), which now run on every change and before every release. Nothing changes in how the app works.

## 1.0.5 — 2026-11-02

- Uninstall reads apk-tools 3's output (Alpine, postmarketOS) correctly, and is tested against dnf5's (Fedora).
- File dialogs switch to GTK's newer FileDialog by themselves once a GTK version drops the old one. Until then the old one stays, as it works on every desktop, including ones without a file-chooser portal like Hyprland.
- The desktop accent is tested against what Noctalia 5 writes for GTK.

## 1.0.4 — 2026-10-26

- Uninstall apps, whatever installed them: Flatpak, Snap, AppImage, Steam, Distrobox, or the system's package manager (pacman, apt, dnf, zypper, rpm-ostree, xbps, apk, eopkg, Portage, Nix). It replaces Remove AppImage.
- Before anything runs, it shows what goes, the packages and apps that need it or go with it, apps that stay but stop working, and whether it's a default app or starts at login, along with the exact command. Package managers are asked first with their own dry run.
- Data folders, unused Flatpak runtimes and advanced options (like removing what depends on it, or skipping dependency checks) are off unless turned on, each with a warning. Packages the system, your desktop or App Entries needs are never offered.
- Commands that need a password go to your own terminal as they are, and the terminal handles the rest.
- Uninstall several apps at once from Select: one command per package manager. History keeps a Reinstall button for uninstalled apps, and `--uninstall` does the same on the command line.
- Helper apps…: shortcuts to Flatseal, Warehouse, Gear Lever, ProtonUp-Qt, Protontricks, BoxBuddy, DistroShelf, GNOME Settings, KDE's app permissions, your software centre and Steam, opened on the app where they allow it. Ones you don't have are behind a + button.
- Launchers can run commands: write them as in a terminal (paru -Syu && flatpak update, pipes, loops, whole scripts) and pick the shell (sh, bash, zsh or fish). Add more sets of commands to open each in its own terminal. They're kept in a small script file, so they work in any launcher.
- A program launcher has one field for the program and what goes after it; the separate Arguments field is gone. Shell syntax like && there is caught, with a button to run it as commands instead. The launcher window is larger.
- When a tab is empty because of the filters (search, source, Hidden or Not in menus), it says how many apps they leave out and offers to lift each one, or all at once.
- The counts on the tabs and at the top are totals, whatever the filters. The Sources menu lists only sources you have apps from.
- Starts about twice as fast, most of all with large icon themes like Papirus: nothing waits for the icon theme before the window appears, app icons fill in as they're found, and pages, windows and network code load when they're first used.
- The list keeps its place when an app is hidden and others move up. Warnings in the Uninstall window are in the error colour.
- Apps exported from Distrobox containers get their own source badge.

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
