"""Keyboard and Mouse page, built for real (see pagekit): layouts (Latin first), Caps Lock and
layout-switch options, typing and mouse settings, the touchpad group, and Restore defaults."""

from gi.repository import Adw

from osettings import pages_system as ps

from .pagekit import needs_display, open_page  # noqa: F401

pytestmark = needs_display

LAYOUTS = [("us", "English (US)"), ("de", "German"), ("fr", "French"), ("ru", "Russian")]


def setup(monkeypatch, touchpad=False):
    monkeypatch.setattr(ps, "xkb_layouts", lambda: LAYOUTS)
    mice = [{"name": "logitech-mouse"}] + ([{"name": "elan-touchpad"}] if touchpad else [])
    monkeypatch.setattr(ps, "hypr_json", lambda *a: {"mice": mice} if a == ("devices",) else None)


LAYOUT_ROW = "Layouts (comma separated, e.g. us,de)"


def test_one_layout(open_page, monkeypatch):
    setup(monkeypatch)
    p = open_page("input")
    p.enter(LAYOUT_ROW, "de")
    assert p.store.values["input:kb_layout"] == "de"
    assert "input:kb_options" not in p.store.values  # one layout needs no switch shortcut


def test_second_layout_gets_a_switch_shortcut(open_page, monkeypatch):
    setup(monkeypatch)
    p = open_page("input")
    p.enter(LAYOUT_ROW, "us, de")
    assert p.store.values["input:kb_layout"] == "us,de"
    assert p.store.values["input:kb_options"] == "grp:alts_toggle"
    assert "Switch layouts with Left Alt + Right Alt" in p.toasts


def test_unknown_layout_is_refused(open_page, monkeypatch):
    setup(monkeypatch)
    p = open_page("input")
    p.enter(LAYOUT_ROW, "us,xx")
    p.enter(LAYOUT_ROW, "")
    assert "input:kb_layout" not in p.store.values
    assert p.toasts[-2:] == ["Unknown layout: xx", "Unknown layout: (empty)"]


def test_a_latin_layout_goes_first(open_page, monkeypatch):
    setup(monkeypatch)
    p = open_page("input", {"hyprland": {"input:kb_variant": "phonetic"}})
    row = p.enter(LAYOUT_ROW, "ru")
    assert p.store.values["input:kb_layout"] == "us,ru"
    assert p.store.values["input:kb_variant"] == ",phonetic"
    assert row.get_text() == "us,ru"
    assert any("Latin layout first" in t for t in p.toasts)


def test_caps_lock_and_switch_options_keep_others(open_page, monkeypatch):
    setup(monkeypatch)
    p = open_page("input", {"hyprland": {"input:kb_options": "caps:escape,grp:alt_shift_toggle,compose:ralt"}})
    assert p.row("Caps Lock key acts as").get_selected() == 2  # Escape
    assert p.row("Switch layouts with").get_selected() == 1  # Alt + Shift
    p.choose("Caps Lock key acts as", "Control")
    assert p.store.values["input:kb_options"] == "ctrl:nocaps,grp:alt_shift_toggle,compose:ralt"
    p.choose("Switch layouts with", "No shortcut")
    assert p.store.values["input:kb_options"] == "ctrl:nocaps,compose:ralt"
    p.choose("Caps Lock key acts as", "Compose key (Omarchy default)")
    assert p.store.values["input:kb_options"] == "compose:caps,shift:both_capslock_cancel,compose:ralt"


def test_typing_and_mouse(open_page, monkeypatch):
    setup(monkeypatch)
    p = open_page("input")
    p.slide("Key repeat rate", 55)
    p.slide("Pointer speed", -0.5)
    p.switch("Left-handed", True)
    p.choose("Acceleration", "Flat (no acceleration)")
    p.choose("Focus follows mouse", "Off (click to focus)")
    v = p.store.values
    assert (v["input:repeat_rate"], v["input:sensitivity"], v["input:left_handed"]) == (55, -0.5, True)
    assert v["input:accel_profile"] == "flat" and v["input:follow_mouse"] == 0
    p.save()
    assert "repeat_rate" in p.lua() and "accel_profile" in p.lua()


def test_touchpad_group_only_with_a_touchpad(open_page, monkeypatch):
    setup(monkeypatch)
    assert not open_page("input").has_row("Tap to click")


def test_touchpad(open_page, monkeypatch, sandbox):
    setup(monkeypatch, touchpad=True)
    p = open_page("input")
    assert p.row("Touchpad enabled", Adw.SwitchRow).get_active()
    p.switch("Tap to click", False)
    p.choose("Drag with fingers", "Three fingers")
    assert p.store.values["input:touchpad:tap_to_click"] is False
    assert p.store.values["input:touchpad:drag_3fg"] == 1
    p.switch("Touchpad enabled", False)
    assert sandbox.run_async[-1] == ["omarchy", "toggle", "touchpad", "off"]


def test_touchpad_shows_omarchys_off_state(open_page, monkeypatch, sandbox):
    setup(monkeypatch, touchpad=True)
    flag = ps.STATE / "toggles/hypr/touchpad-disabled-name"
    flag.parent.mkdir(parents=True)
    flag.write_text("elan-touchpad")
    assert not open_page("input").row("Touchpad enabled", Adw.SwitchRow).get_active()


def test_restore_defaults(open_page, monkeypatch, sandbox):
    setup(monkeypatch, touchpad=True)
    flag = ps.STATE / "toggles/hypr/touchpad-disabled-name"
    flag.parent.mkdir(parents=True)
    flag.write_text("elan-touchpad")
    p = open_page("input", {"hyprland": {"input:kb_layout": "de", "input:touchpad:tap_to_click": False,
                                         "general:gaps_in": 3}})
    finished = []
    p.page.reset(lambda: finished.append(True))
    assert ["omarchy", "toggle", "touchpad", "on"] in sandbox.run_async
    p.save()
    assert p.saved()["hyprland"] == {"general:gaps_in": 3} and finished == [True]
