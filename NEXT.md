# Planned for the next version

Not started. Nothing here is built until it's agreed.

## Edited apps left behind after uninstalling outside App Entries

Editing a system app saves a full copy of its entry in
`~/.local/share/applications`. When the package is removed some other way
(a terminal, a software centre), the copy stays: the app can still show in
menus, and it appears in Issues.

Agreed direction (must work with any desktop and launcher):

- **Hiding:** `TryExec` isn't enough on its own. GNOME, KDE and Xfce honour
  it, but Quickshell (Noctalia and other Quickshell shells) only reads
  `NoDisplay` and `Hidden`, and other launchers vary. So the copy itself gets
  `NoDisplay=true`, which every launcher honours, like the Hide switch does.
- **A setting, so it isn't done by itself:** "Hide edited apps when they're
  uninstalled", in Settings, explained. When on, a scan that finds a copy
  whose app is gone hides it, records it in History with Undo, and says so
  in a snackbar. Default to decide.
- **A note on the card:** "GIMP was uninstalled. Your edits are kept, hidden
  from menus; remove them in Issues." With the setting off, the note has a
  Hide button instead.
- **TryExec as well:** edited copies get `TryExec=` with their program when
  saved, so desktops that honour it hide them even before App Entries runs.
- **Issues:** these listed apart from other leftovers as "uninstalled, your
  edits remain", with what the copy changed and one button to remove them,
  with Undo.

Still open:

- The setting's default (on, or off with the card's Hide button).
- Keep the edits somewhere (History or an export) so reinstalling the app
  can bring them back.
