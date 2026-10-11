"""App Rules page, built for real (see pagekit): adding a rule for an open app or a typed class,
each rule's settings, removing rules, and removing all."""

from gi.repository import Adw

from osettings import pages_look as pl

from .pagekit import needs_display, open_page  # noqa: F401

pytestmark = needs_display


def open_apps(monkeypatch, *classes):
    clients = [{"class": c} for c in classes] + [{"class": ""}]
    monkeypatch.setattr(pl, "hypr_json", lambda *a: clients if a == ("clients",) else None)


def rule_row(p, cls):
    return p.row(cls, Adw.ExpanderRow)


def test_add_a_rule_for_a_typed_class(open_page):
    p = open_page("rules")
    assert p.has_row("No rules yet")
    p.enter("Or type an app class (e.g. firefox)", "  firefox ")
    assert p.store.rules == [{"class": "firefox", "enabled": True}]
    assert rule_row(p, "firefox").get_subtitle() == "No changes yet"
    assert not p.has_row("No rules yet")
    p.save()
    assert p.saved()["rules"] == [{"class": "firefox", "enabled": True}]


def test_a_class_gets_only_one_rule(open_page):
    p = open_page("rules", {"rules": [{"class": "firefox", "enabled": True}]})
    p.enter("Or type an app class (e.g. firefox)", "firefox")
    assert len(p.store.rules) == 1
    assert "firefox already has a rule" in p.toasts


def test_add_a_rule_for_an_open_app(open_page, monkeypatch):
    open_apps(monkeypatch, "kitty", "firefox", "kitty", "Spotify")
    p = open_page("rules", {"rules": [{"class": "firefox", "enabled": True}]})
    pick = p.row("Add a rule for an open app", Adw.ComboRow)
    model = pick.get_model()
    assert [model.get_string(i) for i in range(model.get_n_items())] == ["Spotify", "kitty"]  # firefox has one
    pick.set_selected(1)
    p.click("Add rule")
    assert [r["class"] for r in p.store.rules] == ["firefox", "kitty"]


def test_no_open_apps_to_pick(open_page):
    p = open_page("rules")
    pick = p.row("Add a rule for an open app", Adw.ComboRow)
    assert not pick.get_sensitive()
    p.click("Add rule")
    assert p.store.rules == []


def test_rule_settings(open_page):
    p = open_page("rules", {"rules": [{"class": "mpv", "enabled": True}]})
    rule = p.store.rules[0]
    row = rule_row(p, "mpv")
    p.switch("Always float", True)
    p.switch("Turn off blur", True)
    p.number("Open on workspace", 3)
    assert rule == {"class": "mpv", "enabled": True, "float": True, "no_blur": True, "workspace": 3}
    assert row.get_subtitle() == "floats, no blur, workspace 3"

    p.switch("Custom transparency", True)
    assert rule["opacity_active"] == 0.9 and rule["opacity_inactive"] == 0.85
    p.slide("Focused opacity", 0.75)
    assert rule["opacity_active"] == 0.75
    assert row.get_subtitle().startswith("opacity 0.75/0.85")

    p.switch("Custom transparency", False)
    p.slide("Focused opacity", 0.5)  # ignored while off
    p.switch("Always float", False)
    p.number("Open on workspace", 0)
    assert rule == {"class": "mpv", "enabled": True, "no_blur": True}

    row.set_enable_expansion(False)
    assert rule["enabled"] is False
    p.save()
    assert p.saved()["rules"] == [{"class": "mpv", "enabled": False, "no_blur": True}]


def test_remove_a_rule(open_page):
    p = open_page("rules", {"rules": [{"class": "mpv", "enabled": True}, {"class": "kitty", "enabled": True}]})
    rule_row(p, "mpv")
    [mpv] = [r for r in p.rows(Adw.ButtonRow) if r.get_title() == "Remove rule"
             and r.get_ancestor(Adw.ExpanderRow).get_title() == "mpv"]
    mpv.emit("activated")
    assert [r["class"] for r in p.store.rules] == ["kitty"]
    assert not p.has_row("mpv")


def test_remove_all_rules(open_page):
    p = open_page("rules", {"rules": [{"class": "mpv", "enabled": True}]})
    finished = []
    p.page.reset(lambda: finished.append(True))
    p.save()
    assert p.saved()["rules"] == [] and finished == [True]
    assert p.has_row("No rules yet")


def test_a_damaged_rule_in_settings_still_opens_the_app(open_page):
    """A hand-edited null used to stop the window from opening: the startup save raised."""
    p = open_page("rules", settings={"rules": [
        {"class": "foot", "opacity_active": None, "opacity_inactive": 0.5},
        {"class": "kitty", "float": True}]})
    assert p.has_row("kitty") and not p.has_row("foot")
    assert any("Ignored 1 unreadable entry" in t for t in p.toasts)


def test_a_named_workspace_shows_and_is_kept(open_page):
    """The generated Lua supports a named workspace (e.g. "special:steam", set by hand), but the page
    assumed a number and failed to build."""
    p = open_page("rules", {"rules": [{"class": "steam", "enabled": True, "workspace": "special:steam"}]})
    row = rule_row(p, "steam")
    assert row.get_subtitle() == "workspace special:steam"
    ws = p.row("Open on workspace", Adw.SpinRow)
    assert ws.get_value() == 0 and "special:steam" in ws.get_subtitle()
    p.switch("Always float", True)
    assert p.store.rules[0]["workspace"] == "special:steam"  # untouched until a number is chosen
    p.number("Open on workspace", 4)
    assert p.store.rules[0]["workspace"] == 4
