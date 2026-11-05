"""Windows page, built for real (see pagekit): layout and gaps, custom border colors and
gradients, Omarchy's window transparency setting, animations, and Restore defaults."""

from gi.repository import Adw

from osettings import pages_look as pl

from .pagekit import callbacks, needs_display, open_page  # noqa: F401

pytestmark = needs_display


def test_layout_and_gaps_reach_the_generated_config(open_page):
    p = open_page("windows")
    p.choose("Tiling layout", "Master")
    p.slide("Inner gaps", 12)
    p.slide("Master window size", 0.6)
    p.save()
    hyprland = p.saved()["hyprland"]
    assert hyprland["general:layout"] == "master"
    assert hyprland["general:gaps_in"] == 12 and isinstance(hyprland["general:gaps_in"], int)
    assert hyprland["master:mfact"] == 0.6
    lua = p.lua()
    assert '"master"' in lua and "gaps_in" in lua and "mfact" in lua


def test_controls_show_saved_values(open_page):
    p = open_page("windows", {"hyprland": {"general:layout": "scrolling", "general:gaps_out": 22,
                                           "decoration:blur:enabled": True}})
    assert p.row("Tiling layout").get_selected() == 2
    assert p.row("Outer gaps").scale.get_value() == 22
    assert p.row("Blur").get_active()


def test_custom_border_colors(open_page):
    p = open_page("windows")
    assert not p.row("Focused border").get_sensitive()  # theme colors until switched on
    p.switch("Custom border colors", True)
    values = p.store.values
    assert isinstance(values["general:col:active_border"], str)
    assert "general:col:inactive_border" in values
    assert p.row("Focused border").get_sensitive() and not p.row("Gradient angle").get_sensitive()

    p.switch("Gradient", True)
    grad = values["general:col:active_border"]
    assert len(grad["colors"]) == 2 and grad["angle"] == 45
    assert p.row("Gradient angle").get_sensitive()
    p.slide("Gradient angle", 90)
    assert values["general:col:active_border"]["angle"] == 90

    p.switch("Custom border colors", False)
    assert "general:col:active_border" not in values and "general:col:inactive_border" not in values
    assert not p.row("Focused border").get_sensitive()


TRANSPARENCY = ("omarchy", "hyprland", "window", "transparency")


def shown(combo):
    return combo.get_model().get_string(combo.get_selected())


def test_window_transparency_is_omarchys_own_setting(sandbox, open_page):
    """Omarchy 4.5 keeps opaque / transparent / glassy itself (`omarchy hyprland window transparency`);
    the page shows that and changes it there, and writes nothing of its own."""
    sandbox.run_output[TRANSPARENCY] = "glassy\n"
    p = open_page("windows")
    assert shown(p.row("Window transparency", Adw.ComboRow)) == "Glassy"
    p.choose("Window transparency", "Opaque")
    assert sandbox.run_async[-1] == [*TRANSPARENCY, "opaque"]
    p.choose("Window transparency", "Transparent")
    assert sandbox.run_async[-1] == [*TRANSPARENCY, "transparent"]
    p.choose("Window transparency", "Glassy")
    assert sandbox.run_async[-1] == [*TRANSPARENCY, "glassy"]
    p.save()
    assert "omarchy_opacity" not in p.saved().get("flags", {})
    assert "window transparency off" not in p.lua().lower()


CORNERS = ("omarchy", "hyprland", "corners")


def test_window_corners_are_omarchys_own_setting_and_explain_the_slider(sandbox, open_page):
    """Omarchy 4.5's `corners` toggle files load after the app's file, so sharp/rounded there beats the rounding slider."""
    sandbox.run_output[CORNERS] = "sharp\n"
    p = open_page("windows")
    assert shown(p.row("Window corners", Adw.ComboRow)) == "Sharp"
    assert "Has no effect while Window corners is set to sharp" in p.row("Corner rounding").get_subtitle()
    p.choose("Window corners", "Rounded")
    assert sandbox.run_async[-1] == [*CORNERS, "rounded"]
    p.choose("Window corners", "Follow the theme")
    assert sandbox.run_async[-1] == [*CORNERS, "theme"]


def test_window_corners_default_to_following_the_theme(sandbox, open_page):
    p = open_page("windows")
    assert shown(p.row("Window corners", Adw.ComboRow)) == "Follow the theme"
    assert "Has no effect" not in (p.row("Corner rounding").get_subtitle() or "")


def test_corner_shape_is_circle_or_squircle_through_hyprlands_rounding_power(sandbox, open_page):
    p = open_page("windows")
    assert shown(p.row("Corner shape", Adw.ComboRow)) == "Circle"
    p.choose("Corner shape", "Squircle"); p.save()
    assert p.saved()["hyprland"]["decoration:rounding_power"] == 4.0 and "rounding_power = 4" in p.lua()
    p.choose("Corner shape", "Circle"); p.save()
    assert p.saved()["hyprland"]["decoration:rounding_power"] == 2.0


def test_corner_shape_shows_a_saved_squircle_and_names_a_value_set_elsewhere(sandbox, open_page):
    assert shown(open_page("windows", {"hyprland": {"decoration:rounding_power": 4.0}}).row("Corner shape", Adw.ComboRow)) == "Squircle"
    odd = open_page("windows", {"hyprland": {"decoration:rounding_power": 3.0}})
    assert shown(odd.row("Corner shape", Adw.ComboRow)) == "Circle" and "now 3" in odd.row("Corner shape").get_subtitle()


def test_corner_shape_says_when_omarchys_window_corners_overrides_it(sandbox, open_page):
    sandbox.run_output[CORNERS] = "rounded\n"
    assert "Has no effect while Window corners is set to rounded" in open_page("windows").row("Corner shape").get_subtitle()


def test_animations_switch_says_when_omarchys_toggle_overrides_it(sandbox, open_page):
    from osettings import pages_look as pl
    assert "overrides" not in (open_page("windows").row("Animations").get_subtitle() or "")
    pl.NO_ANIMATIONS_FLAG.parent.mkdir(parents=True, exist_ok=True); pl.NO_ANIMATIONS_FLAG.write_text("")
    assert "overrides" in open_page("windows").row("Animations").get_subtitle()


def test_window_transparency_defaults_to_transparent(sandbox, open_page):
    assert shown(open_page("windows").row("Window transparency", Adw.ComboRow)) == "Transparent"


def test_the_old_switch_is_offered_as_omarchys_opaque(sandbox, open_page, monkeypatch):
    """Before 4.5 the page's own switch turned Omarchy's transparency off with a rule on a tag
    (default-opacity) that no longer exists, so it quietly did nothing. The choice stays visible
    until the user moves it to Omarchy's setting; nothing on the desktop changes unasked."""
    got = callbacks(monkeypatch, pl)
    p = open_page("windows", {"flags": {"omarchy_opacity": False}})
    assert sandbox.all_cmds().count([*TRANSPARENCY, "opaque"]) == 0
    p.press("Switch to Omarchy's Opaque setting")
    cmd, done = got["async"][-1]
    assert cmd == [*TRANSPARENCY, "opaque"]
    done(0, "", "")
    p.save()
    assert "omarchy_opacity" not in p.saved()["flags"]
    assert not p.has_row("Switch to Omarchy's Opaque setting")


def test_a_failed_switch_keeps_the_old_choice(sandbox, open_page, monkeypatch):
    got = callbacks(monkeypatch, pl)
    p = open_page("windows", {"flags": {"omarchy_opacity": False}})
    p.press("Switch to Omarchy's Opaque setting")
    got["async"][-1][1](1, "", "boom")
    p.save()
    assert p.saved()["flags"]["omarchy_opacity"] is False


def test_no_notice_without_the_old_choice(sandbox, open_page):
    assert not open_page("windows").has_row("Switch to Omarchy's Opaque setting")


def test_animations(open_page):
    p = open_page("windows")
    p.choose("Workspace switching", "Instant")
    p.choose("Window open and close", "Slide")
    p.slide("Animation speed", 1.5)
    p.save()
    assert p.saved()["animations"] == {"workspaces": "off", "windows": "slide", "factor": 1.5}
    p.choose("Workspace switching", "Default")
    p.save()
    assert "workspaces" not in p.saved()["animations"]


def test_restore_defaults_only_touches_window_settings(open_page):
    p = open_page("windows", {"hyprland": {"general:gaps_in": 20, "decoration:rounding": 8,
                                           "master:mfact": 0.7, "scrolling:column_width": 0.6,
                                           "dwindle:preserve_split": True,
                                           "animations:enabled": False, "input:repeat_rate": 55},
                              "animations": {"factor": 2.0}, "flags": {"omarchy_opacity": False}})
    old = p.page
    finished = []
    old.reset(lambda: finished.append(True))
    p.save()
    saved = p.saved()
    assert saved["hyprland"] == {"input:repeat_rate": 55}
    assert saved["animations"] == {} and "omarchy_opacity" not in saved["flags"]
    assert finished == [True] and "Window settings restored" in p.toasts
    assert p.page is not old  # rebuilt, so its controls show the defaults
    assert p.row("Outer gaps").scale.get_value() == 10
