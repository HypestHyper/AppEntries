# Planned for the next version

Not started. Nothing here is built until it's agreed.

## Edited apps left behind after uninstalling outside App Entries

Editing a system app saves a full copy of its entry in
`~/.local/share/applications`. When the package is removed some other way
(a terminal, a software centre), the copy stays: the app can still show in
menus, and it appears in Issues.

Ideas to agree on first:

- **Prevent it:** give edited copies `TryExec=` with the program they run.
  Desktops hide entries whose TryExec program is missing, so the copy
  disappears from menus by itself when the app is uninstalled. Existing
  copies would get it the next time they're saved, or through an Issues fix.
- **Say it happened:** after a scan finds copies whose app is gone, show a
  snackbar ("GIMP was uninstalled. Your edits for it are still there.")
  with a button to remove them, and Undo. Nothing is removed by itself.
- **Clearer in Issues:** list these as "uninstalled, your edits remain",
  apart from other leftovers, with what the copy changed (name, icon,
  command) and one button to remove them, with Undo.
- Keep the edits somewhere (History or an export) so reinstalling the app
  can bring them back.
