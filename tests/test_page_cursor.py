"""Cursor page, built for real (see pagekit): theme and size (gsettings + hyprctl setcursor +
the generated config), hiding and warping, and Restore defaults."""

from osettings import pages_system as ps

from .pagekit import callbacks, needs_display, open_page  # noqa: F401

pytestmark = needs_display


def cursor_theme(sandbox, name):
    (sandbox.home / ".icons" / name / "cursors").mkdir(parents=True)


def test_theme_and_size(sandbox, open_page):
    cursor_theme(sandbox, "Test-Cursor")
    p = open_page("cursor")
    assert p.row("Cursor size").get_selected() == 1  # 24 when nothing is set
    p.choose("Cursor theme", "Test-Cursor")
    assert sandbox.run_async[-2:] == [
        ["gsettings", "set", "org.gnome.desktop.interface", "cursor-theme", "Test-Cursor"],
        ["hyprctl", "setcursor", "Test-Cursor", "24"]]
    p.choose("Cursor size", "32")
    assert sandbox.run_async[-2:] == [
        ["gsettings", "set", "org.gnome.desktop.interface", "cursor-size", "32"],
        ["hyprctl", "setcursor", "Test-Cursor", "32"]]
    p.save()
    assert p.saved()["cursor"] == {"theme": "Test-Cursor", "size": 32}
    assert "Test-Cursor" in p.lua()


def test_shows_saved_theme_and_size(sandbox, open_page):
    cursor_theme(sandbox, "Test-Cursor")
    p = open_page("cursor", {"cursor": {"theme": "Test-Cursor", "size": 48}})
    row = p.row("Cursor theme")
    assert row.get_model().get_string(row.get_selected()) == "Test-Cursor"
    assert p.row("Cursor size").get_selected() == 3


def test_hiding_and_warping(open_page):
    p = open_page("cursor")
    p.slide("Hide when idle", 5)
    p.switch("Hide while typing", False)
    p.switch("Move cursor to the focused workspace", False)
    v = p.store.values
    assert v["cursor:inactive_timeout"] == 5.0 and isinstance(v["cursor:inactive_timeout"], float)
    assert v["cursor:hide_on_key_press"] is False
    assert v["cursor:warp_on_change_workspace"] == 0  # Hyprland wants a number here, not a bool
    assert type(v["cursor:warp_on_change_workspace"]) is int
    p.switch("Move cursor to the focused workspace", True)
    assert v["cursor:warp_on_change_workspace"] == 1 and type(v["cursor:warp_on_change_workspace"]) is int


def test_restore_defaults(sandbox, open_page, monkeypatch):
    got = callbacks(monkeypatch, ps)
    cursor_theme(sandbox, "Test-Cursor")
    p = open_page("cursor", {"cursor": {"theme": "Test-Cursor", "size": 48},
                             "hyprland": {"cursor:inactive_timeout": 5.0, "input:repeat_rate": 50}})
    finished = []
    old = p.page
    old.reset(lambda: finished.append(True))
    cmds, done = got["chain"][-1]
    assert cmds == [["gsettings", "reset", "org.gnome.desktop.interface", "cursor-theme"],
                    ["gsettings", "reset", "org.gnome.desktop.interface", "cursor-size"],
                    ["hyprctl", "setcursor", "default", "24"]]
    done([])
    p.save()
    saved = p.saved()
    assert saved["cursor"] == {} and saved["hyprland"] == {"input:repeat_rate": 50}
    assert finished == [True] and "Cursor restored" in p.toasts and p.page is not old


def test_a_size_not_in_the_list_is_shown_as_it_is(sandbox, open_page, monkeypatch):
    """A size of 20 (from gsettings or settings.json) used to show as 16, the first entry."""
    monkeypatch.setattr(ps, "gsetting", lambda key, *a, **k: "20" if key == "cursor-size" else "")
    p = open_page("cursor")
    row = p.row("Cursor size")
    assert row.get_model().get_string(row.get_selected()) == "20"


def test_choosing_a_theme_keeps_the_current_size(sandbox, open_page, monkeypatch):
    """With no size chosen in the app, picking a theme set the live cursor to 24 even when the
    system size (gsettings) was bigger."""
    cursor_theme(sandbox, "Test-Cursor")
    monkeypatch.setattr(ps, "gsetting", lambda key, *a, **k: "48" if key == "cursor-size" else "")
    p = open_page("cursor")
    p.choose("Cursor theme", "Test-Cursor")
    assert sandbox.run_async[-1] == ["hyprctl", "setcursor", "Test-Cursor", "48"]


def test_choosing_a_size_keeps_the_current_theme(sandbox, open_page, monkeypatch):
    monkeypatch.setattr(ps, "gsetting", lambda key, *a, **k: "Bibata" if key == "cursor-theme" else "")
    p = open_page("cursor")
    p.choose("Cursor size", "32")
    assert sandbox.run_async[-1] == ["hyprctl", "setcursor", "Bibata", "32"]
