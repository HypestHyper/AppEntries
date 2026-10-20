<p align="center">
  <img alt="App Entries" src="data/icons/hicolor/scalable/apps/io.github.HypestHyper.AppEntries.svg" width="128">
</p>

<h1 align="center">App Entries</h1>

<p align="center">
  A GTK 4 app for Linux that hides, shows and edits app launcher entries. It can also make launchers and web apps, manage autostart entries, choose default apps and remove AppImages. It only changes files in your home folder.
</p>

<p align="center">
  <img alt="Version 1.0.2" src="https://img.shields.io/badge/version-1.0.2-1f9e80">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-blue">
  <img alt="Linux" src="https://img.shields.io/badge/platform-Linux-informational">
  <img alt="Python 3.9+" src="https://img.shields.io/badge/python-3.9%2B-3776AB">
  <img alt="GTK 4" src="https://img.shields.io/badge/GTK-4-4A86CF">
  <img alt="Material 3 Expressive" src="https://img.shields.io/badge/style-Material%203%20Expressive-8f7ae0">
</p>

<p align="center">
  <a href="#installation">Install</a> ·
  <a href="#features">Features</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#keyboard-shortcuts">Shortcuts</a> ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

---

> **AI disclosure:** This project was written almost entirely by an AI assistant, with direction and testing by the author. It has been tested on Arch Linux with Hyprland, but not yet on every desktop, so review the code before relying on it.

## Features

**Apps**
- Every installed app in one searchable grid: system packages, Flatpak, Snap, AppImage, Steam and your own launchers. Filter by source; badges show where each app comes from and why it's hidden.
- Hide or show an app with one switch. Hidden apps still open links and files, and stay in "Open With".
- **Select several** to hide, show, restore or restyle many apps at once.
- **Edit** any entry (name, icon, command, environment, folders, desktops, quick actions) with a live view of the file. Editing a system app saves your own copy; *Restore original* puts it back.
- **Issues** finds leftover files, missing programs and duplicates, and explains each with a button to fix it.
- **Remove AppImage…** removes the AppImage (to the Trash) and every entry, icon and file type set up for it, after listing each file. Its settings folders are offered separately.

**Launchers**
- **New launcher** for any script or command, with terminal options and a live preview.
- **New web app**: a site in its own window with no address bar or tabs, using a Chromium-based browser. It shares your browser's sign-ins, or keeps its own, with an optional dark mode and a window name for docks and window rules.
- **Styled icons** from 4,000 Material Symbols or your own SVGs: tile shape, colour, shading, size and border, with a built-in colour picker. Paste SVG code, download from a link, or use a site's icon.

**More**
- **Autostart**: turn login programs on and off, or add your own.
- **Default apps**: choose which app opens links, email, folders, text, PDFs, pictures, videos, music and archives. Uses the standard `mimeapps.list`, and also updates Xfce's and KDE's own browser settings.
- **History** of every change, each with Undo, kept between sessions.
- **Export / Import** your changes to set up another computer.
- **Updates** from GitHub releases, installed with one button.
- A **command line** for scripts, and full keyboard and screen reader support.
- Light and dark themes, six accent colours and a responsive layout.

Nothing happens by itself: every option is explained, nothing is written until you press a button, and every change can be undone. System files are never changed.

## Installation

```sh
git clone https://github.com/HypestHyper/AppEntries.git
cd AppEntries
./install.sh                  # installs to ~/.local
```

Needs Python 3.9+, GTK 4.6+ and PyGObject. The installer shows the command for your distribution and asks before installing anything missing (`--yes` to skip the question). Use `sudo ./install.sh --system` for `/usr/local`, or `--prefix DIR`.

Updates come from the **Updates** tab. To remove it, run `./uninstall.sh` (same options). Add `--restore-apps` to show the apps you hid and turn login programs back on, and `--purge` to delete settings.

## How it works

Launchers read `.desktop` files from `~/.local/share/applications` before the system folders, so a file there with the same name wins. Hiding an app writes a copy of its entry there with `NoDisplay=true`, marked with a checksum so App Entries can tell if you edit it. Showing it again deletes the copy, or removes just that line from a file of your own. Autostart works the same way in `~/.config/autostart`. Default apps are written to `~/.config/mimeapps.list`, the standard file desktops and apps read to decide what opens links and files.

This follows the [Desktop Entry Specification](https://specifications.freedesktop.org/desktop-entry-spec/latest/), so it works with GNOME, KDE Plasma, Xfce, Cinnamon, rofi, wofi, fuzzel and other launchers that read `.desktop` files.

## Command line

```sh
app-entries --list --hidden          # ID, state and name
app-entries --hide steam discord     # by ID or name
app-entries --unhide steam
app-entries --export ~/apps.json     # and --import, which lists the changes first
app-entries --refresh-launchers
```

Add `--yes` to skip questions in scripts. See `app-entries --help`.

## Keyboard shortcuts

| Keys | Action |
| --- | --- |
| `Ctrl+F`, or start typing | Search |
| `Alt+1` … `Alt+9` | Switch tabs |
| `Ctrl+N` / `Ctrl+Shift+N` | New launcher / New web app |
| `Enter` on a card | Hide or show it |
| `Ctrl+Z` | Undo the last change |
| `Ctrl+H` | History |
| `Ctrl+R` | Refresh |
| `Ctrl+,` | Settings |

## Files

| What | Where |
| --- | --- |
| Hidden and edited apps, launchers you make | `~/.local/share/applications/` |
| Login programs you changed | `~/.config/autostart/` |
| Default apps | `~/.config/mimeapps.list` |
| Your icons, web apps' own sign-ins | `~/.local/share/app-entries/` |
| History of changes | `~/.local/state/app-entries/history.json` |

## Development

```sh
python3 -m app_entries        # run from the source folder
python3 -m pytest tests       # tests use temporary folders, never your real ones
```

## License

MIT, see [LICENSE](LICENSE). Third-party assets are listed in [THIRD_PARTY.md](THIRD_PARTY.md).
