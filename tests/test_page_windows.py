"""Windows page, built for real (see pagekit): layout and gaps, custom border colors and
gradients, Omarchy's transparency switch, animations, and Restore defaults."""

from .pagekit import needs_display, open_page  # noqa: F401

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


def test_omarchys_transparency_switch(open_page):
    p = open_page("windows")
    assert p.row("Omarchy's subtle transparency").get_active()
    p.switch("Omarchy's subtle transparency", False)
    p.save()
    assert p.saved()["flags"]["omarchy_opacity"] is False
    p.switch("Omarchy's subtle transparency", True)
    p.save()
    assert "omarchy_opacity" not in p.saved()["flags"]


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
