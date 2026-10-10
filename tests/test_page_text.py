"""Fonts and Text page, built for real (see pagekit): the monospace font, the interface font
(kept across themes), the text size (applied once the spinner settles), and Restore defaults."""

import os
import time

from gi.repository import GLib, Gtk, Pango

from osettings import pages_look as pl
from osettings import pages_system as ps
from osettings.core import DEFAULT_FONT

from .pagekit import callbacks, needs_display, open_page, widgets  # noqa: F401

pytestmark = needs_display


def fonts(sandbox, names, current, size=12):
    sandbox.run_output[("omarchy", "font", "list")] = "\n".join(names) + "\n\n"
    sandbox.run_output[("omarchy", "font", "current")] = current
    # What `omarchy display text size` prints (omarchy-display-text-size).
    sandbox.run_output[("omarchy", "display", "text", "size")] = (
        f"text size: {size} px\ngtk text-scaling-factor: 1.0\nterminal font: 9 pt\n")


def wait_until(check, seconds=3):
    ctx, end = GLib.MainContext.default(), time.monotonic() + seconds
    while not check() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return check()


def test_monospace_font(sandbox, open_page, monkeypatch):
    got = callbacks(monkeypatch, ps)
    fonts(sandbox, ["Hack Nerd Font", "JetBrainsMono Nerd Font"], "JetBrainsMono Nerd Font")
    p = open_page("text")
    row = p.row("Monospace font")
    assert row.get_model().get_n_items() == 2 and row.get_selected() == 1
    p.choose("Monospace font", "Hack Nerd Font")
    cmd, done = got["async"][-1]
    assert cmd == ["omarchy", "font", "set", "Hack Nerd Font"]
    done(0, "", "")
    assert "Font set to Hack Nerd Font" in p.toasts
    done(1, "", "font not installed\n")
    assert "font not installed" in p.toasts


def test_text_size_shows_and_applies_once_settled(sandbox, open_page):
    fonts(sandbox, ["A"], "A", 14)
    p = open_page("text")
    assert p.row("Text size").get_value() == 14
    p.number("Text size", 15)
    p.number("Text size", 16)
    assert wait_until(lambda: any(c[:4] == ["omarchy", "display", "text", "size"] for c in sandbox.run_async))
    sizes = [c for c in sandbox.run_async if c[:4] == ["omarchy", "display", "text", "size"]]
    assert sizes == [["omarchy", "display", "text", "size", "16"]]  # only the settled value


def test_text_size_out_of_range_is_clamped(sandbox, open_page):
    fonts(sandbox, ["A"], "A", 30)
    assert open_page("text").row("Text size").get_value() == 20


def test_interface_font_is_kept_across_themes(sandbox, open_page):
    fonts(sandbox, ["A"], "A")
    p = open_page("text")
    [btn] = [w for w in widgets(p.page) if isinstance(w, Gtk.FontDialogButton)]
    btn.set_font_desc(Pango.FontDescription.from_string("Inter 12"))
    p.save()
    assert p.saved()["pins"]["font_name"] == "Inter 12"
    assert os.access(pl.PIN_HOOK, os.X_OK)
    assert ["gsettings", "set", "org.gnome.desktop.interface", "font-name", "Inter 12"] in sandbox.run_chain[-1]


def test_restore_defaults(sandbox, open_page, monkeypatch):
    got = callbacks(monkeypatch, ps)
    fonts(sandbox, ["A"], "A")
    p = open_page("text", {"pins": {"font_name": "Inter 12"}})
    finished = []
    old = p.page
    old.reset(lambda: finished.append(True))
    assert p.saved()["pins"]["font_name"] is None
    assert not pl.PIN_HOOK.exists()
    cmds, done = got["chain"][-1]
    assert cmds == [["omarchy", "font", "set", DEFAULT_FONT], ["omarchy", "display", "text", "size", "reset"],
                    ["gsettings", "reset", "org.gnome.desktop.interface", "font-name"]]
    done([])
    assert "Fonts restored" in p.toasts and finished == [True] and p.page is not old


def test_restore_defaults_reports_a_failure(sandbox, open_page, monkeypatch):
    got = callbacks(monkeypatch, ps)
    fonts(sandbox, ["A"], "A")
    p = open_page("text")
    p.page.reset()
    got["chain"][-1][1](["omarchy font set: not found"])
    assert "Some resets failed: omarchy font set: not found" in p.toasts
