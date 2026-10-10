"""Theme page, built for real (see pagekit): the theme grid, keeping app style and icons across
themes, installing a theme, and Restore defaults."""

import os

from osettings import pages_look as pl
from osettings.core import DEFAULT_THEME

from .pagekit import Gtk, callbacks, needs_display, open_page, widgets  # noqa: F401

pytestmark = needs_display


def themes(sandbox, names, current):
    sandbox.run_output[("omarchy", "theme", "list")] = "\n".join(names)
    sandbox.run_output[("omarchy", "theme", "current")] = current


def grid(p):
    flow = p.page.flow
    out, i = [], 0
    while (child := flow.get_child_at_index(i)) is not None:
        out.append(child)
        i += 1
    return out


def marked(p):
    """The themes shown as current: bold with a ✓. (Which child the grid has selected follows
    keyboard focus, so that isn't checked.)"""
    labels = [w for c in grid(p) for w in widgets(c) if isinstance(w, Gtk.Label)]
    return [lbl.get_text().removesuffix("  ✓") for lbl in labels if lbl.get_text().endswith("✓")]


def test_lists_omarchy_themes_and_marks_the_current_one(sandbox, open_page):
    themes(sandbox, ["Nord", "Tokyo Night", "Gruvbox"], "Tokyo Night")
    p = open_page("theme")
    assert [c.theme_name for c in grid(p)] == ["Nord", "Tokyo Night", "Gruvbox"]
    assert marked(p) == ["Tokyo Night"]


def test_choosing_a_theme_applies_it_once(sandbox, open_page, monkeypatch):
    got = callbacks(monkeypatch, pl)
    themes(sandbox, ["Nord", "Gruvbox"], "Gruvbox")
    p = open_page("theme")
    nord = grid(p)[0]
    p.page.flow.emit("child-activated", nord)
    p.page.flow.emit("child-activated", nord)  # a second click while it's still applying
    sets = [c for c, _ in got["async"] if c[:3] == ["omarchy", "theme", "set"]]
    assert sets == [["omarchy", "theme", "set", "Nord"]]
    assert "Still applying the last theme…" in p.toasts

    done = next(d for c, d in got["async"] if c == ["omarchy", "theme", "set", "Nord"])
    themes(sandbox, ["Nord", "Gruvbox"], "Nord")
    done(0, "", "")
    assert "Theme set to Nord" in p.toasts
    assert marked(p) == ["Nord"]


def test_a_failed_theme_says_why(sandbox, open_page, monkeypatch):
    got = callbacks(monkeypatch, pl)
    themes(sandbox, ["Nord"], "")
    p = open_page("theme")
    p.page.flow.emit("child-activated", grid(p)[0])
    got["async"][-1][1](1, "", "theme folder missing\n")
    assert "Theme failed: theme folder missing" in p.toasts
    assert not p.page.applying  # another theme can be chosen


def test_keeping_light_style_across_themes(sandbox, open_page):
    p = open_page("theme")
    p.choose("App style", "Light")
    assert p.saved()["pins"]["color_scheme"] == "prefer-light"
    assert os.access(pl.PIN_HOOK, os.X_OK)
    assert sandbox.run_chain[-1] == [
        ["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", "prefer-light"],
        ["gsettings", "set", "org.gnome.desktop.interface", "gtk-theme", "Adwaita"]]

    p.choose("App style", "Follow theme")
    assert p.saved()["pins"]["color_scheme"] is None
    assert not pl.PIN_HOOK.exists()  # nothing kept any more
    assert "Will follow the theme from the next theme change" in p.toasts


def test_install_a_theme_from_a_url(sandbox, open_page):
    p = open_page("theme")
    p.enter("Git repository URL", "   ")
    assert not [c for c in sandbox.run_async if c[:3] == ["omarchy", "theme", "install"]]
    p.enter("Git repository URL", " https://github.com/someone/omarchy-x-theme ")
    assert sandbox.run_async[-1] == ["omarchy", "theme", "install", "https://github.com/someone/omarchy-x-theme"]


def test_restore_defaults_keeps_the_interface_font(sandbox, open_page, monkeypatch):
    got = callbacks(monkeypatch, pl)
    p = open_page("theme", {"pins": {"color_scheme": "prefer-dark", "icon_theme": "Papirus",
                                     "font_name": "Inter 11"}})
    finished = []
    p.page.reset(lambda: finished.append(True))
    assert p.saved()["pins"] == {"color_scheme": None, "icon_theme": None, "font_name": "Inter 11"}
    assert pl.PIN_HOOK.exists()  # still needed for the font
    cmd, done = got["async"][-1]
    assert cmd == ["omarchy", "theme", "set", DEFAULT_THEME]
    done(0, "", "")
    assert finished == [True]
