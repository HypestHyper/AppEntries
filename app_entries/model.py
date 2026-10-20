"""GObject wrapper so apps can live in a Gio.ListStore."""
from gi.repository import Gio, GObject

from .desktop_entries import App


class AppItem(GObject.Object):
    """One app in the list. Emits `changed` when its App data is replaced."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, app: App):
        super().__init__()
        self.app = app
        self.busy = False
        self.selected = False
        self._search = app.search_text()

    @property
    def search(self) -> str:
        return self._search

    def update(self, app: App) -> bool:
        if app == self.app:
            return False
        self.app = app
        self._search = app.search_text()
        self.emit("changed")
        return True

    def set_selected(self, selected: bool):
        if selected != self.selected:
            self.selected = selected
            self.emit("changed")

    def set_busy(self, busy: bool):
        if busy != self.busy:
            self.busy = busy
            self.emit("changed")


class AppStore:
    """Keeps a Gio.ListStore of AppItems in sync with scan results,
    changing only what differs."""

    def __init__(self):
        self.store = Gio.ListStore(item_type=AppItem)
        self.by_id = {}

    def sync(self, apps) -> bool:
        changed = False
        new_ids = {a.id for a in apps}
        # Remove gone items (from the end, to keep indexes valid).
        for i in range(self.store.get_n_items() - 1, -1, -1):
            item = self.store.get_item(i)
            if item.app.id not in new_ids:
                self.store.remove(i)
                del self.by_id[item.app.id]
                changed = True
        added = []
        updated = []
        for a in apps:
            item = self.by_id.get(a.id)
            if item is None:
                item = AppItem(a)
                self.by_id[a.id] = item
                added.append(item)
            elif item.update(a):
                updated.append(item)
                changed = True
        if updated:
            # Tell the filter and sorter about just these items. Refiltering
            # everything would scroll the grid back to the top.
            pos = {id(self.store.get_item(i)): i for i in range(self.store.get_n_items())}
            for item in updated:
                i = pos[id(item)]
                self.store.items_changed(i, 1, 1)
        if added:
            self.store.splice(self.store.get_n_items(), 0, added)
            changed = True
        return changed

    def items(self):
        return [self.store.get_item(i) for i in range(self.store.get_n_items())]
