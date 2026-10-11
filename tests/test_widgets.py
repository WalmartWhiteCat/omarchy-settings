"""Desktop Notes page: the widget's config file, and opening the app on a page."""

import json
import re

import pytest

from gi.repository import GLib

from osettings import pages_widgets as pw
from osettings import window

from .conftest import REAL_HOME
from .pagekit import needs_display, open_page  # noqa: F401  (open_page is a fixture)


class FakeWin:
    def __init__(self):
        self.toasts, self.selected = [], []
        self.classes = {"notes": pw.NotesPage, "theme": object}

    def toast(self, msg):
        self.toasts.append(msg)

    def select(self, key):
        self.selected.append(key)


class FakeRow:
    def __init__(self):
        self.sensitive = None

    def set_sensitive(self, v):
        self.sensitive = v


def bare_page():
    page = pw.NotesPage.__new__(pw.NotesPage)
    page.win = FakeWin()
    page.cfg = dict(pw.NOTES_DEFAULTS)
    page._pending = None
    page.margin_x, page.margin_y = FakeRow(), FakeRow()
    page.rebuild = lambda delay=0: None
    return page


def test_missing_config_gives_defaults():
    assert pw.read_notes_config() == pw.NOTES_DEFAULTS


def test_config_values_are_clamped_and_junk_dropped():
    pw.NOTES_CONFIG.parent.mkdir(parents=True)
    pw.NOTES_CONFIG.write_text(json.dumps({"opacity": 250, "width": 10, "textScale": "big", "marginX": True,
                                           "marginY": 12.7, "position": "somewhere", "extra": 1}))
    cfg = pw.read_notes_config()
    assert cfg["opacity"] == 100 and cfg["width"] == 200
    assert cfg["textScale"] == 100 and cfg["marginX"] == 32  # wrong types fall back to defaults
    assert cfg["marginY"] == 12 and cfg["position"] == "bottom-right"
    assert "extra" not in cfg


def test_unreadable_config_gives_defaults():
    pw.NOTES_CONFIG.parent.mkdir(parents=True)
    pw.NOTES_CONFIG.write_text("{ not json")
    assert pw.read_notes_config() == pw.NOTES_DEFAULTS
    pw.NOTES_CONFIG.write_text("[1, 2]")
    assert pw.read_notes_config() == pw.NOTES_DEFAULTS


def test_write_round_trips_and_creates_the_folder():
    cfg = dict(pw.NOTES_DEFAULTS, opacity=40, position="top-left")
    pw.write_notes_config(cfg)
    assert pw.read_notes_config() == cfg


def test_position_change_saves_at_once_and_greys_out_unused_distances():
    page = bare_page()
    page.set_position("top")
    assert json.loads(pw.NOTES_CONFIG.read_text())["position"] == "top"
    assert page.margin_x.sensitive is False and page.margin_y.sensitive is True
    page.set_position("center")
    assert page.margin_x.sensitive is False and page.margin_y.sensitive is False
    page.set_position("right")
    assert page.margin_x.sensitive is True and page.margin_y.sensitive is False
    page.set_position("bottom-left")
    assert page.margin_x.sensitive is True and page.margin_y.sensitive is True


def test_slider_changes_close_together_are_one_write():
    page = bare_page()
    page.set("width", 310)
    page.set("width", 320)
    assert not pw.NOTES_CONFIG.exists()
    assert page._pending
    GLib.source_remove(page._pending)
    page.flush()
    assert json.loads(pw.NOTES_CONFIG.read_text())["width"] == 320
    assert page._pending is None


def pump(seconds):
    """Runs GLib's main loop for a while, so timers fire as in the app."""
    import time
    ctx, end = GLib.MainContext.default(), time.monotonic() + seconds
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.005)


def test_slider_held_moving_writes_as_it_goes(monkeypatch):
    # A slider dragged steadily changes every few ms; the widget follows each
    # write, so they must come while it moves, not only once it stops.
    page = bare_page()
    written = []
    monkeypatch.setattr(pw, "write_notes_config", lambda cfg: written.append(cfg["width"]))
    for width in range(300, 400, 10):
        page.set("width", width)
        pump(0.04)
    assert len(written) >= 3, written
    pump(0.3)
    assert written[-1] == 390
    assert page._pending is None


def test_reset_writes_defaults_and_cancels_a_pending_write():
    page = bare_page()
    page.set("opacity", 10)
    done = []
    page.reset(lambda: done.append(True))
    assert page._pending is None
    assert json.loads(pw.NOTES_CONFIG.read_text()) == pw.NOTES_DEFAULTS
    assert done == [True]


def test_reset_leaves_the_notes_alone(sandbox):
    notes = sandbox.home / ".local/state/desktop-notes/notes.json"
    notes.parent.mkdir(parents=True)
    notes.write_text('[{"text": "keep me", "done": false}]')
    bare_page().reset()
    assert "keep me" in notes.read_text()


def test_notes_page_is_in_the_sidebar_and_restore_all():
    keys = [cls.key for _, classes in window.SECTIONS for cls in classes]
    assert "notes" in keys and "notes" in window.RESET_ORDER
    assert set(window.RESET_ORDER) <= set(keys)


def written():
    return json.loads(pw.NOTES_CONFIG.read_text())


def test_title_is_read_trimmed_and_short():
    pw.NOTES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    pw.NOTES_CONFIG.write_text(json.dumps({"title": "  Todo  "}))
    assert pw.read_notes_config()["title"] == "Todo"
    pw.NOTES_CONFIG.write_text(json.dumps({"title": "x" * 100}))
    assert len(pw.read_notes_config()["title"]) == pw.NOTES_TITLE_MAX
    pw.NOTES_CONFIG.write_text(json.dumps({"title": 5}))
    assert pw.read_notes_config()["title"] == "Reminders"


@needs_display
def test_title_field_saves_it(open_page):
    p = open_page("notes")
    p.enter("Title", "  Todo ")
    assert written()["title"] == "Todo"
    p.enter("Title", "")
    assert written()["title"] == ""


def test_always_show_bells_is_read_only_as_a_switch():
    pw.NOTES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    pw.NOTES_CONFIG.write_text(json.dumps({"alwaysShowBells": True}))
    assert pw.read_notes_config()["alwaysShowBells"] is True
    pw.NOTES_CONFIG.write_text(json.dumps({"alwaysShowBells": "yes"}))
    assert pw.read_notes_config()["alwaysShowBells"] is False


@needs_display
def test_always_show_bells_switch_saves_it(open_page):
    p = open_page("notes")
    p.switch("Always show reminder bells", True)
    assert written()["alwaysShowBells"] is True
    p.switch("Always show reminder bells", False)
    assert written()["alwaysShowBells"] is False


def test_double_right_click_speed_is_kept_in_range():
    pw.NOTES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    pw.NOTES_CONFIG.write_text(json.dumps({"rightClickWaitMs": 5000}))
    assert pw.read_notes_config()["rightClickWaitMs"] == 600
    pw.NOTES_CONFIG.write_text(json.dumps({}))
    assert pw.read_notes_config()["rightClickWaitMs"] == 200


@needs_display
def test_double_right_click_speed_slider_saves_it(open_page):
    p = open_page("notes")
    p.slide("Double right-click speed", 450)
    pump(0.3)
    assert written()["rightClickWaitMs"] == 450


MONITORS = [{"name": "DP-1", "model": "LG ULTRAGEAR+", "x": 0, "y": 0},
            {"name": "DP-2", "model": "ASUS VG277Q1A", "x": 2560, "y": 0}]


def test_monitor_choices_list_connected_monitors_and_a_missing_choice():
    assert pw.monitor_choices(MONITORS, "") == [
        ("Main monitor", ""), ("DP-1 (LG ULTRAGEAR+)", "DP-1"), ("DP-2 (ASUS VG277Q1A)", "DP-2")]
    # Chosen but unplugged: still listed, so the choice isn't lost.
    assert pw.monitor_choices(MONITORS[:1], "DP-2")[-1] == ("DP-2 (not connected)", "DP-2")
    assert pw.monitor_choices(None, "") == [("Main monitor", "")]
    assert len(pw.monitor_choices(MONITORS, "DP-1")) == 3  # chosen and connected: listed once


@needs_display
def test_monitor_drop_down_saves_it(open_page, monkeypatch):
    monkeypatch.setattr(pw, "hypr_json", lambda *a: MONITORS if a == ("monitors",) else None)
    p = open_page("notes")
    p.choose("Monitor", "DP-2 (ASUS VG277Q1A)")
    assert written()["monitor"] == "DP-2"
    p.choose("Monitor", "Main monitor")
    assert written()["monitor"] == ""


def _qml_object(qml, name):
    """A `readonly property var name: (...)` / `property int name: n` from DesktopNotes.qml, as Python."""
    m = re.search(rf"property \w+ {name}: (\(\{{.*?\}}\)|\[.*?\]|\d+)\s*$", qml, re.S | re.M)
    assert m, f"{name} not found in DesktopNotes.qml"
    text = m.group(1).strip("()")
    return json.loads(re.sub(r"(\w+):", r'"\1":', text))


WIDGET_QML = REAL_HOME / ".config/omarchy/plugins/sourced.desktop-notes/DesktopNotes.qml"


@pytest.mark.skipif(not WIDGET_QML.exists(), reason="the Desktop Notes widget isn't installed")
def test_defaults_and_limits_match_the_widget():
    """The widget clamps hand-edited values to the same ranges and falls back to the same defaults;
    the two are kept in step by hand (CLAUDE.md), so check them. Reads the installed widget only."""
    qml = WIDGET_QML.read_text()
    assert _qml_object(qml, "defaults") == pw.NOTES_DEFAULTS
    assert {k: tuple(v) for k, v in _qml_object(qml, "limits").items()} == pw.NOTES_LIMITS
    assert _qml_object(qml, "titleMax") == pw.NOTES_TITLE_MAX
    assert _qml_object(qml, "positions") == [v for _, v in pw.POSITIONS]


def test_monitor_is_read_trimmed():
    pw.NOTES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    pw.NOTES_CONFIG.write_text(json.dumps({"monitor": "  DP-2 \n"}))
    assert pw.read_notes_config()["monitor"] == "DP-2"


def test_monitor_choices_skip_entries_without_a_name():
    assert pw.monitor_choices([{"model": "x"}, "DP-3", {"name": "", "model": "y"}], "") == [("Main monitor", "")]
    assert pw.monitor_choices([{"name": "DP-1"}], "") == [("Main monitor", ""), ("DP-1 (monitor)", "DP-1")]
    assert pw.monitor_choices([{"name": "DP-1", "description": "LG"}], "")[-1] == ("DP-1 (LG)", "DP-1")


@needs_display
def test_page_says_when_the_widget_isnt_installed(open_page):
    from gi.repository import Adw
    from .pagekit import widgets

    def notices(p):
        return [g.get_description() for g in widgets(p.page)
                if isinstance(g, Adw.PreferencesGroup) and "isn't installed" in (g.get_description() or "")]

    assert notices(open_page("notes"))  # the sandbox has no plugin folder
    pw.NOTES_PLUGIN.mkdir(parents=True)
    assert not notices(open_page("notes"))
