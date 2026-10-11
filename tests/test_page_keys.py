"""Keybindings page, built for real (see pagekit): the new-shortcut dialog, and Omarchy's own
shortcuts (their groups, rows, menus, turning off and on, restoring a changed one, search, Restore).
More Keybindings tests use stand-ins: see test_keybinding_fixes, test_review_fixes and test_binds."""

import textwrap

from gi.repository import Adw, Gdk, Gtk

from .pagekit import installed_apps, needs_display, open_page, press_key, spin, widgets  # noqa: F401

pytestmark = needs_display


def new_shortcut_dialog(p):
    """Open the new-shortcut dialog; returns it and its "Open an app" drop-down."""
    p.page.add_custom()
    dialog = p.win.get_visible_dialog()
    return dialog, next(w for w in widgets(dialog) if isinstance(w, Adw.ComboRow) and w.get_title() == "Open an app")


def test_search_apps_in_the_new_shortcut_dialog(open_page, monkeypatch):
    """Typing in "Open an app"'s search field did nothing: it had no expression to match on."""
    installed_apps(monkeypatch, ("firefox.desktop", "Firefox"), ("nautilus.desktop", "Files"), ("kitty.desktop", "Kitty"))
    p = open_page("keys")
    dialog, pick = new_shortcut_dialog(p)
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
    dialog, pick = new_shortcut_dialog(p)
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
    dialog, pick = new_shortcut_dialog(p)
    pick.activate()
    spin()
    assert p._popup_list(pick).child_focus(Gtk.DirectionType.TAB_FORWARD)
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
    dialog, pick = new_shortcut_dialog(p)
    pick.activate()
    spin()
    assert p._popup_list(pick).child_focus(Gtk.DirectionType.TAB_FORWARD)
    spin()
    assert press_key(dialog, Gdk.KEY_F9) is True
    assert dialog.keys == "F9" and dialog.conflict.get_label() == ""
    # Keys the list uses still reach it.
    assert press_key(dialog, Gdk.KEY_Down) is False


# ------------------------------------------------------------------ Omarchy's own shortcuts

PRINT_CMD = ("omarchy", "menu", "keybindings", "--print")


def omarchy_binds(sandbox, printed=()):
    d = sandbox.omarchy / "default/hypr/bindings"
    d.mkdir(parents=True)
    (d / "applications.lua").write_text(textwrap.dedent('''\
        o.bind("SUPER + RETURN", "Terminal", { omarchy = "terminal" })
        o.bind("SUPER + B", "Browser", { omarchy = "browser" })
        '''))
    (d / "tiling.lua").write_text(textwrap.dedent('''\
        o.bind("ALT + TAB", "Next window", "cyclenext")
        o.bind("ALT + TAB", "Bring it to the top", "bringactivetotop")
        for i = 1, 9 do
          o.bind("SUPER + " .. i, "Workspace " .. i, "x")
        end
        '''))
    sandbox.run_output[PRINT_CMD] = "\n".join(printed)


def group_rows(p, title):
    g = next(g for g in widgets(p.page) if isinstance(g, Adw.PreferencesGroup) and g.get_title() == title)
    return {r.get_title(): r for r in widgets(g) if isinstance(r, Adw.ActionRow)}


def keycap_text(row):
    return next(w.get_text() for w in widgets(row) if isinstance(w, Gtk.Label) and w.has_css_class("keycap"))


def menu_items(p, description):
    b = next(d for d in p.page.defaults if d["description"] == description)
    pop = p.page.menu_for(b)
    return {w.get_label(): w for w in widgets(pop) if isinstance(w, Gtk.Button)}


def test_omarchys_shortcuts_are_listed_in_their_groups(sandbox, open_page):
    omarchy_binds(sandbox, ["SUPER + 1 → Workspace 1"])
    p = open_page("keys")
    apps = group_rows(p, "Applications")
    assert list(apps) == ["Terminal", "Browser"] and keycap_text(apps["Terminal"]) == "Super + Enter"
    other = next(g for g in widgets(p.page) if isinstance(g, Adw.PreferencesGroup) and g.get_title() == "Other")
    assert "can be turned off and on, not changed" in other.get_description()
    # Every row has a menu: built from Omarchy's files, or listed under Other.
    rows = list(apps.values()) + list(group_rows(p, "Other").values())
    assert len(rows) == 3 and all(any(isinstance(w, Gtk.MenuButton) for w in widgets(r)) for r in rows)


def test_menu_offers_what_each_shortcut_can_do(sandbox, open_page):
    omarchy_binds(sandbox, ["SUPER + 1 → Workspace 1"])
    p = open_page("keys")
    assert list(menu_items(p, "Terminal")) == ["Change shortcut…", "Turn off"]
    # Bindings on the same key move and turn off together, and say so.
    assert list(menu_items(p, "Next window")) == ["Change shortcut… (also Bring it to the top)",
                                                  "Turn off (also Bring it to the top)"]
    assert list(menu_items(p, "Workspace 1")) == ["Turn off"]  # made in a loop: can't be changed


def test_a_shortcut_sharing_its_key_with_one_that_cant_move_cant_be_changed(sandbox, open_page):
    d = sandbox.omarchy / "default/hypr/bindings"
    d.mkdir(parents=True)
    (d / "tiling.lua").write_text('o.bind("SUPER + J", "Toggle split", "togglesplit")\n'
                                  'o.bind("SUPER + J", "Run a script", function() os.execute("x") end)\n')
    p = open_page("keys")
    assert list(menu_items(p, "Toggle split")) == ["Turn off (also Run a script)"]


def test_turning_one_off_and_on_again(sandbox, open_page):
    omarchy_binds(sandbox)
    p = open_page("keys")
    menu_items(p, "Next window")["Turn off (also Bring it to the top)"].emit("clicked")
    spin()
    assert p.store.binds["disabled"] == ["ALT + TAB"]
    assert p.store.binds["disabled_info"] == {"ALT + TAB": "Next window / Bring it to the top"}
    row = group_rows(p, "Windows and workspaces")["Next window"]
    assert row.get_subtitle() == "Turned off"
    assert list(menu_items(p, "Next window")) == ["Turn on (also Bring it to the top)"]
    p.save()
    assert 'hl.unbind("ALT + TAB")' in p.lua()
    menu_items(p, "Next window")["Turn on (also Bring it to the top)"].emit("clicked")
    spin()
    p.save()
    assert p.store.binds["disabled"] == [] and p.store.binds["disabled_info"] == {}
    assert 'hl.unbind("ALT + TAB")' not in p.lua()
    assert p.toasts[-1] == "“Next window” turned on"


def test_a_changed_shortcut_shows_both_keys_and_can_be_restored(sandbox, open_page):
    omarchy_binds(sandbox)
    line = 'o.bind("SUPER + RETURN", "Terminal", { omarchy = "terminal" })'
    p = open_page("keys", {"binds": {"rebinds": [{"old": "SUPER + RETURN", "new": "SUPER + T", "line": line,
                                                  "description": "Terminal"}]}})
    row = group_rows(p, "Applications")["Terminal"]
    assert row.get_subtitle() == "Changed from Super + Enter" and keycap_text(row) == "Super + T"
    assert list(menu_items(p, "Terminal")) == ["Change shortcut…", "Restore Omarchy's shortcut", "Turn off"]
    menu_items(p, "Terminal")["Restore Omarchy's shortcut"].emit("clicked")
    spin()
    assert p.store.binds["rebinds"] == []
    assert keycap_text(group_rows(p, "Applications")["Terminal"]) == "Super + Enter"


def test_turning_on_refuses_a_key_now_used_by_another_shortcut(sandbox, open_page):
    omarchy_binds(sandbox)
    p = open_page("keys", {"binds": {"disabled": ["SUPER + B"], "disabled_info": {"SUPER + B": "Browser"},
                                     "custom": [{"keys": "SUPER + B", "command": "btop", "description": "Top"}]}})
    menu_items(p, "Browser")["Turn on"].emit("clicked")
    spin()
    assert p.toasts[-1] == "Super + B is used by “Top”. Change or turn that off first."
    assert p.store.binds["disabled"] == ["SUPER + B"]


def test_search_filters_every_row(sandbox, open_page):
    omarchy_binds(sandbox)
    p = open_page("keys", {"binds": {"custom": [{"keys": "SUPER + ALT + N", "command": "notify-send hi",
                                                 "description": "Say hi"}]}})
    p.page.search.set_text("super enter")
    p.page.filter()
    shown = [r.get_title() for r in p.page.rows if r.get_visible()]
    assert shown == ["Terminal"]
    p.page.search.set_text("say")
    p.page.filter()
    assert [r.get_title() for r in p.page.rows if r.get_visible()] == ["Say hi"]
    p.page.search.set_text("")
    p.page.filter()
    assert all(r.get_visible() for r in p.page.rows)


def test_restore_keybindings(sandbox, open_page):
    omarchy_binds(sandbox)
    p = open_page("keys", {"binds": {"disabled": ["SUPER + B"], "disabled_info": {"SUPER + B": "Browser"},
                                     "custom": [{"keys": "SUPER + ALT + N", "command": "x"}]}})
    p.press("Restore defaults")
    d = p.win.get_visible_dialog()
    d.emit("response", "ok")
    d.force_close()
    spin()
    p.save()
    assert p.saved()["binds"] == {"disabled": [], "rebinds": [], "custom": [], "disabled_info": {}}
    assert p.toasts[-1] == "Keybindings restored"
    assert group_rows(p, "Applications")["Browser"].get_subtitle() in ("", None)
