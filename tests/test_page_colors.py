"""Theme Colors page, built for real (see pagekit): the palette in its groups (and "Other" for keys
it doesn't know), the Mode drop-down, picking a color, Apply writing a personal copy for a stock
theme, and Restore. The colors.toml rewriting itself is tested in test_display_colors."""

import tomllib

from gi.repository import Adw, Gtk

from osettings import pages_look as pl

from .pagekit import callbacks, needs_display, open_page, spin, widgets  # noqa: F401

pytestmark = needs_display

COLORS = """\
# Nord, as a stock theme ships it
mode = "dark"
accent = "#88C0D0"
background = "#2E3440"
black = "#3B4252"
bright_red = "#BF616A"
sparkle = "#123456"
count = 3

[extra]
accent = "#000000"
"""


def stock_theme(slug="nord", text=COLORS):
    d = pl.OMARCHY_PATH / "themes" / slug
    d.mkdir(parents=True)
    (d / "colors.toml").write_text(text)
    (pl.STATE / "current").mkdir(parents=True, exist_ok=True)
    (pl.STATE / "current/theme.name").write_text(slug + "\n")
    return d


def groups(p):
    return {g.get_title(): [r.get_title() for r in widgets(g) if isinstance(r, Adw.ActionRow)
                            and not isinstance(r, Adw.ComboRow)]
            for g in widgets(p.page) if isinstance(g, Adw.PreferencesGroup) and g.get_title()}


def color_button(p, title):
    row = p.row(title, Adw.ActionRow)
    return row, next(w for w in widgets(row) if isinstance(w, Gtk.ColorDialogButton))


def pick(p, title, hex_):
    from gi.repository import Gdk
    row, btn = color_button(p, title)
    c = Gdk.RGBA()
    c.parse(hex_)
    btn.set_rgba(c)
    spin()
    return row


def apply_button(p):
    return next(w for w in widgets(p.page) if isinstance(w, Gtk.Button) and w.get_label() == "Apply")


def test_the_palette_is_shown_in_its_groups(open_page):
    stock_theme()
    p = open_page("colors")
    assert groups(p) == {"Colors of Nord": [], "Interface": ["Accent", "Background"], "Terminal palette": ["Black"],
                         "Terminal bright palette": ["Bright red"], "Other": ["Sparkle"]}  # not `count`: no color
    assert p.row("Accent", Adw.ActionRow).get_subtitle() == "#88C0D0"
    _row, btn = color_button(p, "Accent")
    assert pl.rgba_to_hex(btn.get_rgba()) == "#88C0D0"
    assert p.row("Mode", Adw.ComboRow).get_selected() == 0  # Dark
    assert not apply_button(p).get_sensitive()


def test_picking_a_color_then_apply_saves_a_personal_copy(sandbox, open_page, monkeypatch):
    stock = stock_theme()
    got = callbacks(monkeypatch, pl)
    p = open_page("colors")
    row = pick(p, "Accent", "#ff0000")
    assert row.get_subtitle() == "#FF0000"
    assert apply_button(p).get_sensitive()
    p.choose("Mode", "Light")
    apply_button(p).emit("clicked")
    spin()
    copy = pl.USER_THEMES / "nord" / "colors.toml"
    data = tomllib.loads(copy.read_text())
    assert data["accent"] == "#FF0000" and data["mode"] == "light" and data["extra"] == {"accent": "#000000"}
    assert copy.read_text().startswith("# Nord, as a stock theme ships it")  # comments kept
    assert (pl.USER_THEMES / "nord" / pl.OVERLAY_MARK).exists()
    assert (stock / "colors.toml").read_text() == COLORS  # the stock theme is never changed
    assert ["omarchy", "theme", "set", "nord"] in sandbox.run_async
    assert p.toasts[-1] == "Applying theme…"
    changed = []
    p.win.theme_changed = lambda: changed.append(True)  # pages showing the theme refresh
    next(done for cmd, done in got["async"] if cmd[:3] == ["omarchy", "theme", "set"])(0, "", "")
    assert p.toasts[-1] == "Colors applied" and changed == [True]


def test_a_failed_theme_set_says_so(open_page, monkeypatch):
    stock_theme()
    got = callbacks(monkeypatch, pl)
    p = open_page("colors")
    pick(p, "Black", "#000000")
    apply_button(p).emit("clicked")
    spin()
    got["async"][-1][1](1, "", "theme not found\n")
    assert p.toasts[-1] == "Theme failed: theme not found"


def test_picking_the_same_color_back_needs_no_apply(open_page):
    stock_theme()
    p = open_page("colors")
    pick(p, "Accent", "#ff0000")
    pick(p, "Accent", "#88c0d0")
    assert not apply_button(p).get_sensitive()


def test_restore_removes_the_copy(sandbox, open_page, monkeypatch):
    stock_theme()
    callbacks(monkeypatch, pl)
    p = open_page("colors")
    pick(p, "Accent", "#ff0000")
    apply_button(p).emit("clicked")
    spin()
    p.press("Restore defaults")
    d = p.win.get_visible_dialog()
    d.emit("response", "ok")
    d.force_close()
    spin()
    assert not (pl.USER_THEMES / "nord").exists()
    assert sandbox.run_async.count(["omarchy", "theme", "set", "nord"]) == 2


def test_restore_when_nothing_was_edited(sandbox, open_page):
    stock_theme()
    p = open_page("colors")
    p.press("Restore defaults")
    d = p.win.get_visible_dialog()
    d.emit("response", "ok")
    d.force_close()
    spin()
    assert p.toasts[-1] == "These colors have not been edited"
    assert ["omarchy", "theme", "set", "nord"] not in sandbox.run_async


def test_a_theme_without_colors_says_so(open_page):
    stock_theme(text="")
    p = open_page("colors")
    assert p.has_row("This theme has no colors.toml to edit")
    assert not p.has_row("Mode")


def test_a_theme_without_a_mode_has_no_mode_choice(open_page):
    stock_theme(text='accent = "#88C0D0"\n')
    p = open_page("colors")
    assert not p.has_row("Mode") and p.has_row("Accent")
