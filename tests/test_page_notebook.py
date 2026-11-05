"""Notebook page: its settings file (which Notebook follows live and never writes), the start-up choices, and parity with Notebook's own code."""

import importlib
import json
import sys

import pytest
from gi.repository import Adw

from osettings import pages_widgets as pw

from .conftest import REAL_HOME
from .pagekit import needs_display, open_page  # noqa: F401  (open_page is a fixture)

pytestmark = needs_display


def seed(**data):
    pw.NOTEBOOK_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    pw.NOTEBOOK_CONFIG.write_text(json.dumps(data))


def cfg():
    return json.loads(pw.NOTEBOOK_CONFIG.read_text())


def shown(row):
    return row.get_model().get_string(row.get_selected())


def test_defaults_are_shown_and_nothing_is_written(sandbox, open_page):
    p = open_page("notebook")
    assert p.row("Side margins", Adw.SpinRow).get_value() == 140 and p.row("Dim amount", Adw.SpinRow).get_value() == 15
    assert shown(p.row("View", Adw.ComboRow)) == "Same as last time" and shown(p.row("Sort notes", Adw.ComboRow)) == "Leave it as it is"
    assert p.row("Blinking cursor").get_active() and p.row("Reopen the last notes").get_active()
    assert not p.row("Open at a set text size").get_active() and not p.row("Text size", Adw.SpinRow).get_sensitive()
    assert not pw.NOTEBOOK_CONFIG.exists()


def test_changes_are_written_and_only_what_differs(sandbox, open_page):
    seed(vault="/mnt/Writing", mine=1, margin=600)
    p = open_page("notebook")
    assert p.row("Side margins", Adw.SpinRow).get_value() == 600
    p.number("Line spacing", 6)
    p.page.flush()
    p.choose("View", "Advanced")
    p.choose("Window", "Windowed")
    p.switch("Blinking cursor", False)
    p.choose("Sort notes", "By name")
    assert cfg() == {"vault": "/mnt/Writing", "mine": 1, "margin": 600, "line_spacing": 6, "start_view": "advanced",
                     "start_window": "windowed", "cursor_blink": False, "sort": "name"}      # the folder and a hand-added key stay
    p.choose("View", "Same as last time")
    p.number("Side margins", 140)
    p.page.flush()
    assert "start_view" not in cfg() and "margin" not in cfg()      # back to the default: left out


def test_every_start_up_choice_reaches_the_file(sandbox, open_page):
    p = open_page("notebook")
    for title, label, key, value in (("View", "Simple", "start_view", "simple"), ("Window", "Fullscreen", "start_window", "fullscreen"),
                                     ("Sidebar", "Hidden", "start_sidebar", "hidden"), ("Note", "Reading", "start_reading", "reading"),
                                     ("First-line indent", "On", "start_indent", "on"), ("Sort notes", "Last edited first", "sort", "modified")):
        p.choose(title, label)
        assert cfg()[key] == value, title
    p.switch("Reopen the last notes", False)
    assert cfg()["reopen_tabs"] is False


def test_the_text_size_switch(sandbox, open_page):
    p = open_page("notebook")
    p.switch("Open at a set text size", True)
    assert cfg()["start_text_size"] == 100 and p.row("Text size", Adw.SpinRow).get_sensitive()      # 100% until it is changed
    p.number("Text size", 150)
    p.page.flush()
    assert cfg()["start_text_size"] == 150
    p.switch("Open at a set text size", False)
    assert "start_text_size" not in cfg() and not p.row("Text size", Adw.SpinRow).get_sensitive()


def test_the_cursor_colour_and_font(sandbox, open_page):
    from gi.repository import Gdk

    p = open_page("notebook")
    rgba = Gdk.RGBA()
    rgba.parse("#ff8800")
    p.page.caret.set_rgba(rgba)
    assert cfg()["caret"] == "#ff8800"
    p.page.set_font("Serif")
    assert cfg()["font"] == "Serif" and p.row("Font", Adw.ActionRow).get_subtitle() == "Serif"
    p.page.set_font("")
    assert "font" not in cfg()


@pytest.mark.parametrize("key, bad", [("margin", 5), ("margin", "90"), ("margin", True), ("caret", "white"), ("dim", "yes"), ("start_view", "wide"),
                                      ("start_text_size", 49), ("start_text_size", 501), ("start_text_size", False), ("sort", "newest"), ("reopen_tabs", 1)])
def test_a_bad_value_in_the_file_shows_the_default(sandbox, key, bad):
    seed(**{key: bad})
    assert pw.read_notebook_config()[key] == pw.NB_DEFAULTS[key]


def test_the_notes_folder_is_kept_and_shown(sandbox, open_page):
    seed(vault="/mnt/Writing", margin=300)
    p = open_page("notebook")
    assert p.row("Notes folder", Adw.ActionRow).get_subtitle() == "/mnt/Writing"
    p.page.set_folder("/mnt/Other")
    assert cfg() == {"vault": "/mnt/Other", "margin": 300} and p.row("Notes folder", Adw.ActionRow).get_subtitle() == "/mnt/Other"


def test_the_folder_defaults_to_the_notes_folder(sandbox, open_page):
    assert open_page("notebook").row("Notes folder", Adw.ActionRow).get_subtitle() == "~/Notes"


def test_restore_keeps_the_folder_and_other_keys(sandbox, open_page):
    seed(vault="/mnt/Writing", mine=1, margin=300, sort="name", start_view="advanced", dim=False)
    p = open_page("notebook")
    p.page.reset()
    assert cfg() == {"vault": "/mnt/Writing", "mine": 1}
    assert p.row("Side margins", Adw.SpinRow).get_value() == 140 and "Notebook settings restored" in p.toasts


def test_an_unwritable_file_says_so(sandbox, open_page, monkeypatch):
    p = open_page("notebook")

    def boom(path, text):
        raise OSError("read-only file system")

    monkeypatch.setattr(pw, "write_atomic", boom)
    p.switch("Panel shadows", False)
    assert any("Couldn't save the Notebook settings" in t for t in p.toasts)


def test_the_page_is_under_tools(sandbox, open_page):
    from osettings import window

    sections = dict((name, [c.key for c in classes]) for name, classes in window.SECTIONS)
    assert sections["Tools"] == ["notes", "notebook", "ohm", "ohm-memory", "ohm-model", "ohm-prompt", "ohm-safety", "ohm-danger"] and "Widgets" not in sections


def test_defaults_limits_and_choices_match_notebooks_own():
    """What Notebook accepts is decided in notebook/settings.py; this page must offer exactly that (skipped without Notebook)."""
    folder = REAL_HOME / "Work/omarchy-notebook"
    if not (folder / "notebook/settings.py").exists():
        pytest.skip("Notebook isn't installed")
    sys.path.insert(0, str(folder))
    saved = {k: v for k, v in sys.modules.items() if k == "notebook" or k.startswith("notebook.")}
    for k in saved:
        del sys.modules[k]
    try:
        ns = importlib.import_module("notebook.settings")
        assert pw.NB_DEFAULTS == ns.DEFAULTS
        assert pw.NB_LIMITS == ns.LIMITS
        assert {k: tuple(v for _, v in pairs) for k, pairs in pw.NB_CHOICES.items()} == ns.CHOICES
        assert pw.NB_TEXT_SIZE == (50, 500)
        for key, good in (("start_text_size", 0), ("start_text_size", 50), ("start_text_size", 500)):
            assert ns.valid(key, good) and pw.nb_valid(key, good)
        for key, bad in (("start_text_size", 49), ("start_text_size", 501), ("margin", 801), ("caret", "#fff"), ("dim", 1)):
            assert not ns.valid(key, bad) and not pw.nb_valid(key, bad)
    finally:
        for k in [k for k in sys.modules if k == "notebook" or k.startswith("notebook.")]:
            del sys.modules[k]
        sys.modules.update(saved)
        sys.path.remove(str(folder))


def test_a_pending_slider_write_happens_when_the_page_goes_away_not_later(sandbox, open_page):
    """The 100 ms timer must not fire after the page is gone and write its stale values over the file."""
    p = open_page("notebook")
    p.page.set("margin", 300)          # pending, not yet written
    assert not pw.NOTEBOOK_CONFIG.exists()
    p.page.flush_pending()             # what tearing the page down does
    assert cfg() == {"margin": 300} and p.page._pending is None
    seed(margin=500)                   # the file moved on; a timer that fires later must not undo it
    p.page.flush_pending()
    assert cfg() == {"margin": 500}


def test_a_page_writes_only_what_it_changed(sandbox, open_page):
    """Another edit to the file (by hand, or by a stale page) must survive this page's next change."""
    seed(margin=300, vault="/mnt/Writing")
    p = open_page("notebook")
    seed(margin=500, vault="/mnt/Writing", line_spacing=9)      # edited elsewhere after the page was built
    p.choose("Sort notes", "By name")
    assert cfg() == {"margin": 500, "vault": "/mnt/Writing", "line_spacing": 9, "sort": "name"}
    p.page.set("title_gap", 30)
    p.page.flush_pending()
    assert cfg() == {"margin": 500, "vault": "/mnt/Writing", "line_spacing": 9, "sort": "name", "title_gap": 30}


def test_open_notebook_runs_it(sandbox, open_page):
    open_page("notebook").press("Open Notebook")
    assert sandbox.spawn[-1] == ["omarchy-notebook"]
