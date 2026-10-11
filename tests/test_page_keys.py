"""Keybindings page, built for real (see pagekit). Most Keybindings tests use stand-ins: see
test_keybinding_fixes, test_review_fixes and test_binds."""

from gi.repository import Adw, Gdk, Gtk

from .pagekit import installed_apps, needs_display, open_page, press_key, spin, widgets  # noqa: F401

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


def test_typing_in_the_app_search_is_not_recorded_as_a_shortcut(open_page, monkeypatch):
    """The dialog records every key it sees first (a capture-phase controller) unless a text field
    has the focus. Opening "Open an app" must put the focus in its search field, so letters typed
    there reach it instead of becoming the shortcut. (GTK can't fake real key presses, so this
    calls the dialog's key handler as a key press would.)"""
    installed_apps(monkeypatch, ("firefox.desktop", "Firefox"))
    p = open_page("keys")
    p.page.add_custom()
    dialog = p.win.get_visible_dialog()
    pick = next(w for w in widgets(dialog) if isinstance(w, Adw.ComboRow) and w.get_title() == "Open an app")
    pick.activate()
    spin()
    focus = dialog.get_root().get_focus()
    assert isinstance(focus, Gtk.Text) and focus.get_ancestor(Gtk.Popover) and focus.is_ancestor(pick)
    assert press_key(dialog, Gdk.KEY_f) is False
    assert dialog.shown.get_label() == "Waiting for keys…" and dialog.conflict.get_label() == ""
    # Held Ctrl still records a shortcut, even from the search field.
    assert press_key(dialog, Gdk.KEY_f, Gdk.ModifierType.CONTROL_MASK) is True
    assert dialog.keys == "CTRL + F"


def test_keys_in_the_app_list_are_not_recorded_as_a_shortcut(open_page, monkeypatch):
    """With the focus moved from the search field into the drop-down's list (arrow keys, or a
    click on a result), the focus is no longer a text field, so a typed letter became the shortcut
    ("R on its own would stop that key working…") instead of going to the list."""
    installed_apps(monkeypatch, ("firefox.desktop", "Firefox"), ("nautilus.desktop", "Files"))
    p = open_page("keys")
    p.page.add_custom()
    dialog = p.win.get_visible_dialog()
    pick = next(w for w in widgets(dialog) if isinstance(w, Adw.ComboRow) and w.get_title() == "Open an app")
    pick.activate()
    spin()
    listview = next(w for w in widgets(pick) if isinstance(w, Gtk.ListView) and w.get_ancestor(Gtk.Popover))
    assert listview.child_focus(Gtk.DirectionType.TAB_FORWARD)
    spin()
    focus = dialog.get_root().get_focus()
    assert not isinstance(focus, Gtk.Text) and focus.get_ancestor(Gtk.Popover)
    assert press_key(dialog, Gdk.KEY_r) is False
    assert dialog.shown.get_label() == "Waiting for keys…" and dialog.conflict.get_label() == ""
    assert press_key(dialog, Gdk.KEY_r, Gdk.ModifierType.CONTROL_MASK) is True
    assert dialog.keys == "CTRL + R"


def test_f_keys_are_recorded_from_the_app_list(open_page, monkeypatch):
    """Letting the result list have plain keys must not swallow keys that work as a shortcut on
    their own: the list does nothing with F9, so it was lost and the dialog kept waiting."""
    installed_apps(monkeypatch, ("firefox.desktop", "Firefox"))
    p = open_page("keys")
    p.page.add_custom()
    dialog = p.win.get_visible_dialog()
    pick = next(w for w in widgets(dialog) if isinstance(w, Adw.ComboRow) and w.get_title() == "Open an app")
    pick.activate()
    spin()
    assert p._popup_list(pick).child_focus(Gtk.DirectionType.TAB_FORWARD)
    spin()
    assert press_key(dialog, Gdk.KEY_F9) is True
    assert dialog.keys == "F9" and dialog.conflict.get_label() == ""
    # Keys the list uses still reach it.
    assert press_key(dialog, Gdk.KEY_Down) is False
