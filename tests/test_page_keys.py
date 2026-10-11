"""Keybindings page, built for real (see pagekit). Most Keybindings tests use stand-ins: see
test_keybinding_fixes, test_review_fixes and test_binds."""

from gi.repository import Adw

from .pagekit import installed_apps, needs_display, open_page, widgets  # noqa: F401

pytestmark = needs_display


def test_search_apps_in_the_new_shortcut_dialog(open_page, monkeypatch):
    """Typing in "Open an app"'s search field did nothing: it had no expression to match on."""
    installed_apps(monkeypatch, ("firefox.desktop", "Firefox"), ("nautilus.desktop", "Files"), ("kitty.desktop", "Kitty"))
    p = open_page("keys")
    p.page.add_custom()
    dialog = p.win.get_visible_dialog()
    pick = next(w for w in widgets(dialog) if isinstance(w, Adw.ComboRow) and w.get_title() == "Open an app")
    assert p.search(pick, "fi") == ["Firefox", "Files"]
    p.pick_found(pick, "Files")
    assert dialog.command.get_text() == "nautilus.desktop" and dialog.desc.get_text() == "Files"
