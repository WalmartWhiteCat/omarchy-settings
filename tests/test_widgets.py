"""Desktop Notes page: the widget's config file, and opening the app on a page."""

import json

from gi.repository import GLib

from osettings import pages_widgets as pw
from osettings import window


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
