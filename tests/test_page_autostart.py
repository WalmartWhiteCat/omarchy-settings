"""Autostart page, built for real (see pagekit): adding apps and commands, turning items off,
starting one now, removing, the read-only lists from autostart.lua files, and removing all."""

from gi.repository import Adw, Gtk

from osettings import pages_keys as pk

from .pagekit import needs_display, open_page, widgets  # noqa: F401

pytestmark = needs_display


class App:
    def __init__(self, app_id, name):
        self.app_id, self.name = app_id, name

    def get_id(self):
        return self.app_id

    def get_display_name(self):
        return self.name


def apps(monkeypatch, *pairs):
    monkeypatch.setattr(pk, "app_choices", lambda: [App(i, n) for i, n in pairs])


def item_row(p, title):
    return p.row(title, Adw.ActionRow)


def test_add_an_app(open_page, monkeypatch):
    apps(monkeypatch, ("btop.desktop", "btop"), ("signal.desktop", "Signal"))
    p = open_page("autostart")
    assert p.has_row("Nothing added yet")
    p.row("Add an app", Adw.ComboRow).set_selected(1)
    p.click("Add")
    p.save()
    assert p.saved()["autostart"] == [{"command": "signal.desktop", "launch": True, "enabled": True}]
    assert item_row(p, "Signal").get_subtitle() == "signal.desktop"
    assert "Will start at next login" in p.toasts


def test_add_a_command(open_page, monkeypatch):
    apps(monkeypatch)
    p = open_page("autostart")
    row = p.enter("Or add a command", "  syncthing --no-browser ")
    assert p.store.autostart == [{"command": "syncthing --no-browser", "launch": False, "enabled": True}]
    assert row.get_text() == ""
    assert item_row(p, "syncthing --no-browser").get_subtitle() == "Command"
    p.enter("Or add a command", "   ")
    assert len(p.store.autostart) == 1


def test_an_item_is_added_once(open_page, monkeypatch):
    apps(monkeypatch)
    p = open_page("autostart", {"autostart": [{"command": "syncthing", "launch": False, "enabled": True}]})
    p.enter("Or add a command", "syncthing")
    assert len(p.store.autostart) == 1 and "Already in the list" in p.toasts


def test_turn_off_start_now_and_remove(open_page, monkeypatch, sandbox):
    apps(monkeypatch, ("btop.desktop", "btop"))
    p = open_page("autostart", {"autostart": [{"command": "btop.desktop", "launch": True, "enabled": True},
                                              {"command": "syncthing", "launch": False, "enabled": True}]})
    btop, sync = item_row(p, "btop"), item_row(p, "syncthing")
    [switch] = [w for w in widgets(sync) if isinstance(w, Gtk.Switch)]
    switch.set_active(False)
    assert p.store.autostart[1]["enabled"] is False

    p.click("Start now", within=btop)
    p.click("Start now", within=sync)
    assert sandbox.spawn[-2:] == [["uwsm-app", "--", "btop.desktop"], ["sh", "-c", "syncthing"]]
    assert p.toasts[-1] == "Started"

    p.click("Remove", within=item_row(p, "btop"))
    p.save()
    assert p.saved()["autostart"] == [{"command": "syncthing", "launch": False, "enabled": False}]
    assert not p.has_row("btop")


def test_shows_what_autostart_lua_files_start(open_page, monkeypatch, sandbox):
    apps(monkeypatch)
    (pk.HYPR_DIR / "autostart.lua").write_text(
        'o.launch_on_start("nextcloud")\n-- o.exec_on_start("old-thing")\no.exec_on_start("swayosd-server")\n')
    omarchy = pk.OMARCHY_PATH / "default/hypr/autostart.lua"
    omarchy.parent.mkdir(parents=True)
    omarchy.write_text('hl.exec_cmd(o.launch("mako"))\nhl.exec_cmd("walker --gapplication-service")\n')
    p = open_page("autostart")
    for title in ("nextcloud", "swayosd-server", "mako", "walker --gapplication-service"):
        assert p.has_row(title), title
    assert not p.has_row("old-thing")  # commented out


def test_remove_all(open_page, monkeypatch):
    apps(monkeypatch)
    p = open_page("autostart", {"autostart": [{"command": "syncthing", "launch": False, "enabled": True}]})
    finished = []
    p.page.reset(lambda: finished.append(True))
    p.save()
    assert p.saved()["autostart"] == [] and finished == [True]
    assert p.has_row("Nothing added yet")


def test_search_the_app_list(open_page, monkeypatch):
    """Typing in the drop-down's search field did nothing: it had no expression to match on."""
    apps(monkeypatch, ("firefox.desktop", "Firefox"), ("nautilus.desktop", "Files"), ("kitty.desktop", "Kitty"))
    p = open_page("autostart")
    pick = p.row("Add an app", Adw.ComboRow)
    assert p.search(pick, "fi") == ["Firefox", "Files"]
    assert p.search(pick, "kit") == ["Kitty"]
    p.pick_found(pick, "Kitty")
    p.click("Add")
    p.save()
    assert p.saved()["autostart"] == [{"command": "kitty.desktop", "launch": True, "enabled": True}]


def test_search_matches_anywhere_in_a_name(open_page, monkeypatch):
    """The search only matched the start of a name (libadwaita's default), so "code" didn't find
    Visual Studio Code."""
    apps(monkeypatch, ("code.desktop", "Visual Studio Code"), ("firefox.desktop", "Firefox"),
         ("writer.desktop", "LibreOffice Writer"))
    p = open_page("autostart")
    pick = p.row("Add an app", Adw.ComboRow)
    assert p.search(pick, "code") == ["Visual Studio Code"]
    assert p.search(pick, "FOX") == ["Firefox"]
