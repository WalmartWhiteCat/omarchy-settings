"""The real main window, built on the tests' invisible display (see conftest), and `--page`.

The app is the real SettingsApp with its name taken away and no session bus (see conftest), so
it can never reach the user's running Omarchy Settings and hand it a command line."""

import pytest
from gi.repository import Gio, GLib

from osettings import window

from .conftest import HEADLESS

# Never on the live desktop: without the invisible display, these don't run.
pytestmark = pytest.mark.skipif(not HEADLESS, reason="no invisible Broadway display (gtk4-broadwayd)")


class FakeOptions:
    def __init__(self, page):
        self.page = page

    def lookup_value(self, name, _type):
        return GLib.Variant("s", self.page) if name == "page" and self.page is not None else None


class FakeCommandLine:
    def __init__(self, page):
        self.options = FakeOptions(page)

    def get_options_dict(self):
        return self.options


def spin(n=30):
    ctx = GLib.MainContext.default()
    for _ in range(n):
        ctx.iteration(False)


@pytest.fixture
def app():
    app = window.SettingsApp()
    app.set_application_id(None)
    app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
    assert app.register(None) and app.get_dbus_connection() is None
    yield app
    for win in app.get_windows():
        win.destroy()
    spin()


@pytest.fixture
def toasts(monkeypatch):
    shown = []
    monkeypatch.setattr(window.SettingsWindow, "toast", lambda self, text: shown.append(text))
    return shown


def command_line(app, page):
    assert app.do_command_line(FakeCommandLine(page)) == 0
    spin()
    return app.props.active_window


def built(win):
    return [win.stack.get_page(child).get_name() for child in win.stack]


def showing(win):
    return win.stack.get_visible_child_name(), win.sidebar.get_selected_row().key


def test_opens_on_the_first_page(app):
    win = command_line(app, None)
    assert showing(win) == ("theme", "theme")
    assert built(win) == ["theme"]


def test_page_option_opens_straight_on_that_page(app):
    win = command_line(app, "notes")
    assert showing(win) == ("notes", "notes")
    assert built(win) == ["notes"]  # the Theme page was never built
    assert win.content.get_title() == win.stack.get_visible_child().get_title()


def test_page_option_switches_an_open_window(app):
    first = command_line(app, None)
    win = command_line(app, "notes")
    assert win is first and len(app.get_windows()) == 1
    assert showing(win) == ("notes", "notes")


def test_no_page_option_leaves_an_open_window_where_it_is(app, toasts):
    command_line(app, "keys")
    win = command_line(app, None)
    assert showing(win) == ("keys", "keys") and toasts == []


def test_unknown_page_says_so(app, toasts):
    win = command_line(app, "nope")
    assert showing(win) == ("theme", "theme")
    assert "nope" in toasts[0]
    command_line(app, "notes")
    command_line(app, "nope")
    assert showing(win) == ("notes", "notes") and len(toasts) == 2


def test_page_option_waits_for_an_open_dialog(app, toasts):
    win = command_line(app, "keys")
    win.confirm_reset_all()
    spin()
    dialog = win.get_visible_dialog()
    assert dialog is not None
    command_line(app, "notes")
    assert showing(win) == ("keys", "keys")
    assert win.get_visible_dialog() is dialog
    assert "dialog" in toasts[0]

    dialog.force_close()
    spin()
    command_line(app, "notes")
    assert showing(win) == ("notes", "notes") and len(toasts) == 1


def test_a_damaged_settings_file_keeps_the_last_good_lua(app, toasts):
    """After a damaged settings.json is set aside, the app starts fresh but leaves the generated
    Lua alone until something is changed: replacing it at startup would wipe the user's settings
    from Hyprland on the next reload."""
    from osettings import store as store_mod
    store_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    store_mod.SETTINGS_FILE.write_text("{not json")
    store_mod.HYPR_LUA.write_text("-- the last good settings\n")
    command_line(app, None)
    assert store_mod.HYPR_LUA.read_text() == "-- the last good settings\n"


def test_a_missing_lua_file_is_written_at_startup(app, toasts):
    from osettings import store as store_mod
    store_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    store_mod.SETTINGS_FILE.write_text('{"hyprland": {"general:gaps_in": 7}}')
    command_line(app, None)
    assert "gaps_in = 7," in store_mod.HYPR_LUA.read_text()
