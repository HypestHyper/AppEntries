# Planned for the next version

Not started. Nothing here is built until it's agreed.

## Edited apps left behind after uninstalling outside App Entries

Editing a system app saves a full copy of its entry in
`~/.local/share/applications`. When the package is removed some other way
(a terminal, a software centre), the copy stays: the app can still show in
menus, and it appears in Issues.

Agreed direction (must work with any desktop and launcher):

- **Hiding:** `TryExec` isn't enough on its own. GNOME, KDE and Xfce honour
  it, but Noctalia 5 (C++, src/system/desktop_entry.cpp) and Quickshell
  (older Noctalia, other Quickshell shells) only read `NoDisplay`, `Hidden`
  and OnlyShowIn/NotShowIn, and other launchers vary. So the copy itself gets
  `NoDisplay=true`, which every launcher honours, like the Hide switch does.
- **Options in the Issues tab** (decided), each explained there:
  - **Hide edited apps when they're uninstalled**, on by default. Package
    managers remove their own entry from the system folders and never touch
    the user's copy, so App Entries hides it: `NoDisplay=true`, marked with
    an `X-AppEntries-` key as hidden for this reason, recorded in History
    with Undo, and a snackbar says so.
  - **Bring the edits back when the app is reinstalled**, on by default.
    Without it, the hidden copy would keep the reinstalled app out of menus.
    When the app's own entry reappears, the hide App Entries added (only
    that, recognised by its mark) is removed, so the edits apply again.
- **A note on the card:** "GIMP was uninstalled. Your edits are kept, hidden
  from menus; remove them in Issues." With the option off, the note has a
  Hide button instead.
- **TryExec as well:** edited copies get `TryExec=` with their program when
  saved, so desktops that honour it hide them even before App Entries runs.
- **Issues:** these listed apart from other leftovers as "uninstalled, your
  edits remain", with what the copy changed and one button to remove them,
  with Undo.

Still open: nothing. Waiting for the go-ahead.
