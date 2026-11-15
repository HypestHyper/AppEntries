# Changelog

## Unreleased

- When App Entries runs something in your terminal (Help, Update, Remove, installs), the window now waits for Enter afterwards instead of starting your shell, so your shell's startup (fastfetch in its config file, say) no longer prints over what the command said.

## 1.2.11 — 2026-11-15

- **Help in Tools is safe**: a command with a manual page shows **Manual** and opens it. One without shows **Help…**, which opens a terminal explaining it can run the command's --help and waits for you to press Enter, because a program that doesn't understand --help (a script of your own, say) would just run. If it then says it needs administrator rights, the terminal explains that and shows the sudo command for you to run yourself; nothing runs as root.
- A tool in Tools opens with a click anywhere on its row, not just its name or arrow.

## 1.2.10 — 2026-11-15

- **Tools has pages**: click a tool to open its page beside the list (or instead of it in a narrow window), like an app's:
  - what it is, with its package's description; for a file of your own, what kind of file it is (a compiled program, or a Bash, Python… script), its first comment and how it starts;
  - its commands with where each one is, and **Help** to open its manual (or its --help) in your terminal;
  - the same Installation details as apps: package, repository, install date, size, dependencies and what needs it, or the GitHub project;
  - Update, Open folder, Open in text editor (for scripts), Project page and Remove.
- The Tools list has a search box and a group filter, shows each tool's description and size, and each group's total size, with a line on what the group is (like what ~/.local/bin and ~/bin are for).

## 1.2.9 — 2026-11-15

- **Terminal programs from your package manager** in Tools: packages you installed yourself that add a command but have no menu entry (ripgrep, btop, tmux and the like), grouped under the package manager that installed them, with their version, size and commands. **Remove** uninstalls one in your terminal, with the same command and options as Uninstall. Packages pulled in for others, and ones the system, your desktop or App Entries needs, aren't listed. Works with pacman, apt, dnf, zypper, rpm-ostree, xbps, apk, Portage and your Nix profile; on apt, packages Debian counts as part of the base system are left out too. (eopkg doesn't record which packages you installed yourself, so it isn't covered.)
- **Install from GitHub** (New ▾ → From GitHub…, and Tools → Add from GitHub…): paste a project's link and App Entries reads its releases, lets you pick the version (test versions if you want them) and suggests the file that fits this computer, saying why:
  - an **AppImage** goes to ~/Applications and the usual AppImage form opens, filled in from the app itself;
  - an **app archive** is unpacked into its own folder in ~/Applications (refusing any file that would land outside it) and the app folder form opens;
  - a **.deb, .rpm or pacman package** for your system, or a **Flatpak bundle**, installs in your terminal;
  - a project with only source code gets the usual command for its language (pipx, uv, cargo, go install, npm) or a git copy, run in your terminal.
  Downloads are checked against the release's checksum file when it has one, and everything is read from github.com's pages, so it doesn't use up GitHub's API limit. Installed apps are linked to their project, so App updates covers them.
- **Checking for app updates no longer runs into GitHub's limit** of 60 questions an hour: App Entries reads each project's release pages on github.com (where its latest version leads, and its list of files) instead of GitHub's API, remembers answers for an hour, and only asks the API if the pages don't answer.
- **Default apps agree everywhere**: an app's page and the Defaults tab now ask the same question, so a file type nobody chose an app for shows the app your desktop opens it with (ONLYOFFICE for .doc, say) in both, instead of "Make default" on the app's page.
- **Ctrl+Z** while typing in a field undoes the typing there, instead of the last change in History.
- A new icon shows in the app list straight away, even when it replaces the old icon file under the same name.
- Status chips sit in the title bar, beside History and Refresh, so an app's page starts level with the search box.
- **Tools** in the rail opens again: the installed settings didn't list it as a place, so clicking it did nothing.
- A commands launcher's script shows its first 10 lines on its page, with **Show all**, instead of the whole script; and no tooltip repeats it.
- Tooltips use the app's own colours, so they're dark in dark mode instead of a bright box.

## 1.2.8 — 2026-11-15

- **App updates**, on the Updates page: every app and tool from a GitHub project in one list (AppImages, apps installed with pip, pipx or uv, git copies, AUR packages, package files from GitHub, and tools in Tools). **Check all** asks GitHub for each one's latest release; AppImages update right there (with Undo), and the rest run their own update command in your terminal. Turn on **Check once a day** and a status chip says when something is newer; nothing is downloaded or changed until you press Update.
- **System, Flatpak and Snap**: how many updates are waiting (pacman with checkupdates, apt, dnf, zypper, Flatpak, Snap), with the command that installs them run in your terminal, one by one or all together. With paru or yay, AUR packages are included.
- **Tools**, a new place in the rail: command-line tools in your home folder that have no menu entry, grouped by how they were installed (cargo, go install, pipx, uv, npm, or files you put in ~/.local/bin), with their version, size and GitHub project. **Update** and **Remove** run the tool's own command in your terminal; a file you put there yourself goes to the Trash, with Undo. Commands that belong to an app with a menu entry aren't listed again.
- **Waydroid's Android apps**, **JetBrains Toolbox apps** and **Windows programs run with Wine or Bottles** are recognised in Installation: which app looks after them, the Toolbox app's folder, size and version, and the Wine prefix or bottle with its size. Uninstall removes an Android app with Waydroid, hands a Toolbox app to Toolbox, trashes a Wine prefix named like its app, and never deletes a bottle (it can hold other programs).
- **Uninstall** works for more kinds of app, each shown in full first and undone with Undo:
  - **Python apps** installed with pip, pipx or uv: their environment and the commands they added to ~/.local/bin go to the Trash, with their menu entry.
  - **Git copies and app folders** in your home folder: the folder goes to the Trash. Only a folder named like the app is offered, so a script in ~/scripts or a dotfiles copy never takes its whole folder with it.
  - **Games from Heroic, Lutris, Bottles, itch and Minigalaxy**: the launcher opens so you remove the game there, and its menu entry goes once the game's folder is gone, as with Steam.
- **What a Flatpak can reach**, on its page under Installation: files and folders, network, display (X11 or Wayland), sound, devices and the services it talks to, in plain words, with your Flatseal changes applied. The ones that reach a lot are marked, and Flatseal is a click away.
- **New** lasts until you open the app or App Entries starts again, as intended. The Filter menu's Mark as seen button is gone.
- **Games from Heroic, Lutris, Bottles, itch and Minigalaxy** are recognised in Installation, instead of showing the package of the helper their launcher calls (like xdg-utils for `xdg-open heroic://…`). The page says which launcher installed and starts the game and, for Heroic, which store it's from (Epic, GOG or Amazon). Where Heroic or Lutris keep a record, it shows the game's folder and real size, its version and (Lutris) when it was installed.
- Commands that only adjust how an app runs (`env`, `gamemoderun`, `prime-run`, `mangohud` and the like) are looked through to the app itself, and openers (`xdg-open`, `gio open`, `gtk-launch`…) are never taken for the app.

## 1.2.7 — 2026-11-15

- **Launchers made with App Entries** say so in Installation, instead of showing the program they run: a web app shows its site, its browser and how much its own sign-ins take; a commands launcher, the shell that runs your commands; a launcher for a program, the program's own details below.
- **App Entries itself** shows its version, where it's installed and its real size.
- **Sizes**: a program started by a small script or a link is followed to the real program, and an app that lives in its own folder (/opt/app, an app folder in your home) shows the size of the whole folder, not of its start script.
- **Apps installed with pip, pipx or uv, and git copies of projects** are recognised: how they were installed, their version, and the GitHub project they came from (from pip's own record or the copy's git settings). **Update in terminal** runs pipx upgrade, uv tool upgrade, pip install --upgrade or git pull where you can see it.
- **Packages downloaded from GitHub** (a .deb or .rpm installed by hand, or an AUR package) are matched to the GitHub project their package names as home. Check for updates compares versions; Update downloads the new .deb or .rpm for your computer to Downloads and installs it in your terminal. AUR packages say your AUR helper updates them.
- Paths are shown whole, wrapping onto more lines, instead of being shortened in the middle.
- The Flatpak runtime is explained: which one (GNOME Platform 50), its size, what a runtime is, and whether other apps share it.

## 1.2.6 — 2026-11-15

- **Installation** section at the bottom of each app's page: its package, version and where it came from (your distribution's repositories, the AUR, a PPA or other repository, a hand-installed package file, Flathub, a Snap channel), when it was installed, whether it was installed directly or pulled in by another package, who installed it (where apt records that), whether it's for all users or just you, and its size. **Dependencies** opens to show what it needs, what needs it, and optional extras with whether they're installed. For a Flatpak, its runtime and how many other apps share it; for a Snap, its publisher and base.
- For an AppImage or a program no package owns: the file, its date, the web address your browser downloaded it from, and the GitHub project an AppImage says its updates come from.
- **Apps from GitHub**: an AppImage's page shows the GitHub project it comes from, found from its own update information or the address it was downloaded from; any other AppImage can be linked to a project by name. **Check for updates** reads the project's latest release (only when you press it; nothing about you is sent) and shows what's new. **Update** downloads the AppImage for your computer's processor next to the one you have, checks it, points the launcher at it and moves the old file to the Trash. Undo puts the old file and launcher back and moves the download to the Trash.
- **Use a newer file…** now works for every AppImage, not just launchers made with App Entries.
- The page doesn't wait for any of this: it opens at once, the section fills in from the background, and the dependency lists are only read when opened. Answers are remembered until something is installed or removed. Only reads; nothing is changed.

## 1.2.5 — 2026-11-15

- Going from Launchers to another tab no longer flashes the Apps list on the way out.
- Window buttons press evenly into a rounded square, instead of collapsing towards one corner.
- Window buttons follow your desktop's button layout as it changes: which buttons, and on which side. With no buttons in the layout, none are shown. Maximise turns into Restore while the window is maximised.

## 1.2.4 — 2026-11-14

- Motion follows Material 3 Expressive throughout. Things that move or change shape (button presses, the rail's indicator, switches, panels) overshoot slightly and settle; colours and fades never bounce. Small parts move fast, panels a little slower.
- The rail's indicator grows out from the middle of the place you pick.
- Hiding an app: its icon turns round, steps back and dims, along with its name.
- An app's page rises into place beside the list. In a narrow window it comes in from the side, and the list comes back from the other side when you go back.
- The save bar, selection bar and confirmations slide up and fade in. New status chips pop in; the ones already there stay still.
- Switch handles grow when turned on and when pressed.
- Reduce motion in Settings now works alongside your desktop's own setting: if your desktop has animations off, turning Reduce motion off no longer turns them back on.
- After resizing the window, everything takes its new size at once. Before, some parts (like Back to Apps) kept their old size until the pointer passed over them, then jumped.

## 1.2.3 — 2026-11-14

- The pencil on an app's icon sits in the middle of its circle.
- Open works for launchers that run in a terminal (commands launchers among them): App Entries starts them in your terminal itself, instead of relying on GLib, which only knows a few terminals and failed with "Unable to find terminal required for application".
- In a narrow window, an app's page has a clear **Back to Apps** (or Launchers) button, and clicking Apps or Launchers in the rail goes back to the list too.
- A commands launcher's page shows your commands under Runs, not the script that runs them.

## 1.2.2 — 2026-11-14

- The big icon at the top of an app's page has a pencil and opens the icon picker when clicked, for any app or launcher. The new icon shows at once, ready to save.

## 1.2.1 — 2026-11-14

- New apps stay marked New until you open their page, instead of until you close App Entries, so you don't miss them. Filter has Mark all as seen.
- Styled icons have a **Symbol colour**: Auto (white or dark, whichever stands out on the tile, as before), White, Black, any colour you pick, or, for your own multi-colour SVGs, Original. It replaces the Recolour switch, and icons you made before look the same.
- The main colour is called Tile colour when there's a tile, and **Swap with the tile** flips the tile and symbol colours. Style icons for several apps at once carries the symbol colour too.

## 1.2.0 — 2026-11-14

- New ▾ in Launchers adds what you downloaded, each filled in for you in the launcher form:
  - **AppImage**: its name, description, icon, categories, file types and window class are read from inside it with unsquashfs, without running it. (Without unsquashfs, it asks before using the AppImage's own extractor.) It can move to ~/Applications and is made executable.
  - **App folder** from a tar.gz or zip: the program and icon are found inside, or taken from an entry that came with it.
  - **Windows program**: run with Wine or Proton (umu), with its own icon when icoutils is installed.
  - **Java app**, a **.desktop file** that came with an app (paths next to it are fixed so it keeps working), and **Distrobox** apps, added with distrobox-export.
- Launchers lists AppImages, app folders and Windows programs in ~/Applications, ~/AppImages, ~/Games and ~/Downloads that have no launcher yet, each with Add. It only looks.
- An AppImage's page has Use a newer file…, which points the launcher at a newer download and moves the old one to the Trash (Undo brings it back), and Show the app's file. Deleting a launcher for an app folder in ~/Applications can take the folder to the Trash too.
- Launchers keep their window class and file types when edited.

## 1.1.2 — 2026-11-14

- No more dot on the Filter button. When the list is narrowed to a source, customised or new apps, the button is tinted and each filter shows under it as a chip that lifts it. Leaving out apps that aren't in menus is a preference, so it isn't marked.

## 1.1.1 — 2026-11-14

- Status chips at the top right say what needs your attention, wherever you are: issues found, an update (or a restart to finish one), unsaved edits to an app, a slow scan, or apps that couldn't be read. Each one takes you there. With nothing to say there are none, and the header's apps count is gone (the counts are on Shown and Hidden).
- Search, Shown/Hidden/All, Filter, Sort and Select sit at the top of the app list instead of across the window, so the app page starts at the top. Filter, Sort and Select are compact buttons; a dot on Filter means a filter is on, and pointing at it says which.
- The update notification has an Update button, which installs it and shows the progress in Updates, and a What's new button. It goes away after your notification server's usual time, as before, and is taken down once the update is installed.

## 1.1.0 — 2026-11-14

- A new layout. A slim rail on the left goes to Apps, Launchers, Issues, Autostart and Defaults, with Updates and Settings at the bottom.
- Apps are a compact list. **Shown**, **Hidden** or **All** picks which, Shown by default, so hidden apps stay out of the way; source, customised, new and apps not in menus are in one Filter menu. An eye on each row hides or shows it (always there on hidden apps, on the others when you point at them); Space does the same, and right-click or the Menu key opens its options.
- Each app has a page beside the list: how it looks in your launcher, the Hidden switch, Open, its name, icon and command, the file types it opens, starting at login, helper apps, the changes made to it with Undo, and Uninstall. In narrow windows the page takes the list's place, with a way back.
- Editing is on the page: a Save / Discard bar appears once something changes, the launcher preview follows as you type, and unsaved edits are kept (marked with a dot) while you look at other apps. Closing with unsaved edits asks first.
- New launchers and web apps, and editing them, open in the page; History slides in at the side. The Edit, launcher, web app and History windows are gone.
- The window works from about 470 px wide, for tiling desktops: search gets its own line, the list never gets wider than 600 px, and the page sits beside it when there's room.

## 1.0.8 — 2026-11-13

- Text in the app can be selected with the mouse and copied with Ctrl+C or the right-click menu: descriptions, paths, commands, explanations. It stays out of the Tab order, so keyboard use is unchanged.
- Default apps shows what really opens a type when you haven't chosen anything (your desktop's pick, explained when you hover), instead of "Not chosen", which read as if the app shown wasn't chosen.
- More room between the icon or text and the edge of the app pickers and the Sources and Sort menus.

## 1.0.7 — 2026-11-13

- Apps you edited, then uninstalled some other way (a terminal, a software centre), no longer linger in menus. Uninstalling removes only the app's own files, so your edited copy stays behind; App Entries now hides it (NoDisplay=true, which every launcher honours) and keeps your edits. When the app is reinstalled, the hide comes off and your edits apply again. Both happen once, show a message with Undo, and are options on the Issues page.
- The card says when that happened, and Issues lists these copies apart as "Uninstalled, your edits remain", with Remove.
- Edited copies of system apps get a TryExec naming their program, so desktops that honour it (GNOME, KDE, Xfce) leave them out of menus straight away. A TryExec the entry came with is kept.
- An Open button on each card starts the app, hidden ones included.
- Default apps can be set per file type: Each type opens a category (Pictures, Videos…) so, say, PNG and TIFF can open in different apps, each with its own Reset.
- By app, at the bottom of Default apps, lists every file type one app says it opens, including ones no category covers (like .xcf or .psd), what opens each now, and Make default, or the app for all of them. File types… in a card's ⋯ menu opens it for that app.
- Sort the list newest first, by when each app appeared on this computer. Apps that appeared since App Entries last looked are marked New. (Package managers keep build dates on their files, so App Entries notes when it first sees each app instead; the first time, it starts from the file times and marks nothing.)

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
