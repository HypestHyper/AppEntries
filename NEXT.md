# Planned for the next version

Not started. Nothing here is built until it's agreed.

## Edited apps left behind after uninstalling outside App Entries

Editing a system app saves a full copy of its entry in
`~/.local/share/applications`. When the package is removed some other way
(a terminal, a software centre), the copy stays: the app can still show in
menus, and it appears in Issues.

Agreed direction:

- **Hidden once the app is gone:** edited copies get `TryExec=` with the
  program they run, written when the edit is saved. Desktops hide an entry
  whose TryExec program is missing, so the copy leaves the menus by itself
  when the app is uninstalled, without App Entries changing anything then
  ("the app never does anything by itself" holds). Copies made before this
  get it the next time they're saved, or from an Issues button. To check:
  which launchers honour TryExec (GNOME, KDE and Xfce do; check rofi,
  fuzzel, wofi, walker and the like).
- **A note on the card:** "GIMP was uninstalled. Your edits are kept;
  remove them in Issues." The card shows as hidden.
- **Issues:** these listed apart from other leftovers as "uninstalled, your
  edits remain", with what the copy changed and one button to remove them,
  with Undo.

Still open:

- If the user's launcher ignores TryExec, whether to offer hiding the copy
  for real (a button in the card's note), since doing it automatically
  would break "the app never does anything by itself".
- Keep the edits somewhere (History or an export) so reinstalling the app
  can bring them back.
