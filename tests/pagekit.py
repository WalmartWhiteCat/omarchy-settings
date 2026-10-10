"""Opening one real settings page on the tests' invisible display (see conftest) and using its
controls the way a person would: switches, drop-downs, sliders, text fields and buttons, found by
their titles. Everything runs inside the sandbox, so the commands a page runs are recorded in
`sandbox` (run, run_async, run_chain…) and its files land in tmp_path.

The app is the real SettingsApp with its name taken away and no session bus, so it can never
reach the user's running Omarchy Settings."""

import json

import pytest
from gi.repository import Adw, Gio, GLib, Gtk

from osettings import store as store_mod
from osettings import window

from .conftest import HEADLESS

needs_display = pytest.mark.skipif(not HEADLESS, reason="no invisible Broadway display (gtk4-broadwayd)")


def spin(n=30):
    ctx = GLib.MainContext.default()
    for _ in range(n):
        ctx.iteration(False)


def widgets(root):
    """Every widget under root, depth first."""
    child = root.get_first_child()
    while child is not None:
        yield child
        yield from widgets(child)
        child = child.get_next_sibling()


class Opened:
    """A window opened on one page, with helpers to find and use its controls."""

    def __init__(self, app, key, toasts):
        self.app = app
        self.key = key
        self.toasts = toasts
        self.win = window.SettingsWindow(app, page=key)
        self.win.present()
        spin()

    @property
    def page(self):
        # A page can rebuild itself (replace_page), so always look it up.
        return self.win.stack.get_child_by_name(self.key)

    @property
    def store(self):
        return self.win.store

    def rows(self, kind=Adw.PreferencesRow):
        return [w for w in widgets(self.page) if isinstance(w, kind)]

    def row(self, title, kind=Adw.PreferencesRow):
        found = [w for w in self.rows(kind) if w.get_title() == title]
        assert found, f"no row titled {title!r} on the {self.key} page: " \
                      f"{sorted({r.get_title() for r in self.rows(kind)})}"
        assert len(found) == 1, f"{len(found)} rows titled {title!r}"
        return found[0]

    def has_row(self, title):
        return any(r.get_title() == title for r in self.rows())

    def switch(self, title, on):
        row = self.row(title, Adw.SwitchRow)
        row.set_active(on)
        spin()
        return row

    def choose(self, title, label):
        """Pick `label` in the drop-down titled `title`."""
        row = self.row(title, Adw.ComboRow)
        labels = [row.get_model().get_string(i) for i in range(row.get_model().get_n_items())]
        assert label in labels, f"{label!r} isn't in {title!r}: {labels}"
        row.set_selected(labels.index(label))
        spin()
        return row

    def slide(self, title, value):
        row = self.row(title, Adw.ActionRow)
        row.scale.set_value(value)
        spin()
        return row

    def enter(self, title, text):
        """Type into the text field titled `title` and press its apply button."""
        row = self.row(title, Adw.EntryRow)
        row.set_text(text)
        row.emit("apply")
        spin()
        return row

    def click(self, tooltip, within=None):
        """Click the icon button with this tooltip (inside `within`, a row, if given)."""
        found = [w for w in widgets(within or self.page)
                 if isinstance(w, Gtk.Button) and w.get_tooltip_text() == tooltip]
        assert len(found) == 1, f"{len(found)} buttons with tooltip {tooltip!r}"
        found[0].emit("clicked")
        spin()

    def number(self, title, value):
        row = self.row(title, Adw.SpinRow)
        row.set_value(value)
        spin()
        return row

    def press(self, title):
        row = self.row(title, Adw.ButtonRow)
        row.emit("activated")
        spin()

    def save(self):
        """Run the pending save now (with its "after" callbacks), as its timer would."""
        self.store.save_now()
        spin()

    def saved(self):
        return json.loads(store_mod.SETTINGS_FILE.read_text())

    def lua(self):
        return store_mod.HYPR_LUA.read_text()


@pytest.fixture
def open_page(sandbox, monkeypatch):
    """open_page(key, settings=None) -> Opened. settings, if given, is written as settings.json first."""
    toasts = []
    monkeypatch.setattr(window.SettingsWindow, "toast", lambda self, text: toasts.append(text))
    # A save finishes (and runs its "after" callbacks) once hyprctl reload and configerrors
    # answer; answer them as a clean reload would. They're still recorded in sandbox.run_async.
    recorded = store_mod.run_async

    def run_async(cmd, done=None):
        recorded(cmd, done)
        if done and cmd[:2] in (["hyprctl", "reload"], ["hyprctl", "configerrors"]):
            done(0, "no errors" if cmd[1] == "configerrors" else "ok", "")

    monkeypatch.setattr(store_mod, "run_async", run_async)
    monkeypatch.setattr(window.SettingsWindow, "busy", lambda self, text: toasts.append(text))
    apps = []

    def open_(key, settings=None):
        if settings is not None:
            store_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            store_mod.SETTINGS_FILE.write_text(json.dumps(settings))
        app = window.SettingsApp()
        app.set_application_id(None)
        app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
        assert app.register(None) and app.get_dbus_connection() is None
        apps.append(app)
        return Opened(app, key, toasts)

    yield open_
    for app in apps:
        for win in app.get_windows():
            if win.store._pending:
                GLib.source_remove(win.store._pending)
                win.store._pending = None
            win.destroy()
    spin()


def last_async(sandbox, prefix):
    """The last run_async command starting with `prefix`, or None."""
    matches = [c for c in sandbox.run_async if c[:len(prefix)] == list(prefix)]
    return matches[-1] if matches else None


def callbacks(monkeypatch, *modules):
    """Make run_async / run_chain in these modules also record their done callbacks, so a test
    can finish a command as if it had exited. Returns {"async": [(cmd, done)], "chain": [...]}"""
    got = {"async": [], "chain": []}
    for mod in modules:
        old_async, old_chain = mod.run_async, mod.run_chain

        def run_async(cmd, done=None, _old=old_async):
            _old(cmd, done)
            got["async"].append((list(cmd), done))

        def run_chain(cmds, done=None, _old=old_chain):
            _old(cmds, done)
            got["chain"].append(([list(c) for c in cmds], done))

        monkeypatch.setattr(mod, "run_async", run_async)
        monkeypatch.setattr(mod, "run_chain", run_chain)
    return got


__all__ = ["needs_display", "open_page", "spin", "widgets", "last_async", "callbacks", "Gtk"]
