"""Display helpers (valid_scales, reset_monitor_scale) and ColorsPage.save's TOML rewrite."""

import tomllib

import pytest

from osettings import pages_look, pages_system

from .conftest import REAL_OMARCHY, luac_error

# ------------------------------------------------------------------ valid_scales


@pytest.mark.parametrize("w, h, expected", [
    (1920, 1080, [1, 1.25, 1.333333, 1.5, 1.6, 1.666667, 2, 2.4, 2.5, 3, 4]),
    (2560, 1440, [1, 1.25, 1.333333, 1.6, 1.666667, 2, 2.5, 4]),   # 2560/1.5 isn't whole
    (3840, 2160, [1, 1.25, 1.333333, 1.5, 1.6, 1.666667, 2, 2.4, 2.5, 3, 4]),
    (2880, 1800, [1, 1.25, 1.333333, 1.5, 1.6, 1.666667, 2, 2.4, 2.5, 3, 4]),
    (1366, 768, [1, 2]),
    (1001, 1001, [1, 1.75]),
    (1367, 769, [1]),
])
def test_valid_scales(w, h, expected):
    assert pages_system.valid_scales(w, h) == expected


@pytest.mark.parametrize("w, h", [(1920, 1080), (2560, 1440), (3840, 2160), (2880, 1800), (3456, 2234),
                                  (2256, 1504), (5120, 2880)])
def test_valid_scales_give_whole_logical_sizes(w, h):
    scales = pages_system.valid_scales(w, h)
    assert scales[0] == 1 and scales == sorted(scales)
    for s in scales:
        assert abs(w / s - round(w / s)) < 1e-3 and abs(h / s - round(h / s)) < 1e-3, s


# ------------------------------------------------------------------ reset_monitor_scale


TEMPLATE = """-- See https://wiki.hypr.land/Configuring/Monitors/
-- List current monitors and resolutions possible: hyprctl monitors

local omarchy_gdk_scale = 2
local omarchy_monitor_scale = "auto"

hl.env("GDK_SCALE", tostring(omarchy_gdk_scale))
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = omarchy_monitor_scale })
"""


@pytest.fixture
def template(sandbox):
    p = sandbox.omarchy / "config/hypr/monitors.lua"
    p.parent.mkdir(parents=True)
    p.write_text(TEMPLATE)
    return p


def monitor_backups():
    return sorted(pages_system.MONITORS_LUA.parent.glob("monitors.lua.bak.*"))


def test_reset_monitor_scale_restores_template_lines(template):
    custom = TEMPLATE.replace("omarchy_gdk_scale = 2", "omarchy_gdk_scale = 1") \
                     .replace('omarchy_monitor_scale = "auto"', "omarchy_monitor_scale = 1.5")
    custom += '\nhl.monitor({ output = "DP-1", mode = "preferred", position = "auto", scale = 1 })\n'
    pages_system.MONITORS_LUA.write_text(custom)
    assert pages_system.reset_monitor_scale() is True
    text = pages_system.MONITORS_LUA.read_text()
    assert "local omarchy_gdk_scale = 2\n" in text
    assert 'local omarchy_monitor_scale = "auto"\n' in text
    assert 'output = "DP-1"' in text  # the user's own lines survive
    assert [b.read_text() for b in monitor_backups()] == [custom]
    assert template.read_text() == TEMPLATE
    assert luac_error(text) is None


def test_reset_monitor_scale_noop_when_already_default(template):
    pages_system.MONITORS_LUA.write_text(TEMPLATE)
    assert pages_system.reset_monitor_scale() is True
    assert pages_system.MONITORS_LUA.read_text() == TEMPLATE
    assert monitor_backups() == []


def test_reset_monitor_scale_leaves_customized_file(template):
    custom = 'hl.monitor({ output = "DP-1", mode = "2560x1440@144", position = "0x0", scale = 1.25 })\n'
    pages_system.MONITORS_LUA.write_text(custom)
    assert pages_system.reset_monitor_scale() is False
    assert pages_system.MONITORS_LUA.read_text() == custom
    assert monitor_backups() == []


def test_reset_monitor_scale_missing_files(sandbox):
    assert pages_system.reset_monitor_scale() is False
    pages_system.MONITORS_LUA.write_text(TEMPLATE)
    assert pages_system.reset_monitor_scale() is False  # no template to restore from
    assert pages_system.MONITORS_LUA.read_text() == TEMPLATE


def test_reset_monitor_scale_against_installed_template_copy(sandbox, monkeypatch):
    """Use a copy of the installed Omarchy template; neither it nor ~/.config is written."""
    real = REAL_OMARCHY / "config/hypr/monitors.lua"
    if not real.exists():
        pytest.skip("Omarchy not installed")
    text = real.read_text()
    if "local omarchy_monitor_scale = " not in text:
        pytest.skip("installed template has no scale lines")
    copy = sandbox.omarchy / "config/hypr/monitors.lua"
    copy.parent.mkdir(parents=True)
    copy.write_text(text)
    edited = "\n".join("local omarchy_monitor_scale = 3" if l.startswith("local omarchy_monitor_scale =") else l
                       for l in text.splitlines()) + "\n"
    pages_system.MONITORS_LUA.write_text(edited)
    assert pages_system.reset_monitor_scale() is True
    assert pages_system.MONITORS_LUA.read_text().splitlines() == text.splitlines()


# ------------------------------------------------------------------ theme colors


COLORS_TOML = """# Tokyo Night, with comments that must survive
mode = "dark"

accent = "#7aa2f7"   # inline comment
selection = "#292e42"
  background = "#1a1b26"
foreground="#a9b1d6"
dark_foreground = "#565f89"
bright_foreground = "#c0caf5" # keep me
"""


class FakeWin:
    def __init__(self):
        self.toasts = []

    def toast(self, msg):
        self.toasts.append(msg)


class Colors:
    """ColorsPage without the widgets: only the attributes save()/reset() use."""

    target = pages_look.ColorsPage.target
    save = pages_look.ColorsPage.save
    reset = pages_look.ColorsPage.reset

    def __init__(self, slug, source):
        self.slug, self.source = slug, source
        self.colors = tomllib.loads(source.read_text())
        self.edited = dict(self.colors)
        self.win = FakeWin()
        self.applied = []

    def apply_theme(self, message, done=None):
        self.applied.append(message)
        done and done()


@pytest.fixture
def stock_theme(sandbox):
    d = sandbox.omarchy / "themes/tokyo-night"
    d.mkdir(parents=True)
    (d / "colors.toml").write_text(COLORS_TOML)
    return d / "colors.toml"


def test_save_rewrites_values_keeps_comments(stock_theme):
    page = Colors("tokyo-night", stock_theme)
    page.edited.update(accent="#FF0000", background="#000000", foreground="#FFFFFF", mode="light")
    page.save()
    target = pages_look.USER_THEMES / "tokyo-night/colors.toml"
    text = target.read_text()
    assert text == COLORS_TOML.replace('accent = "#7aa2f7"', 'accent = "#FF0000"') \
                              .replace('background = "#1a1b26"', 'background = "#000000"') \
                              .replace('foreground="#a9b1d6"', 'foreground="#FFFFFF"') \
                              .replace('mode = "dark"', 'mode = "light"')
    parsed = tomllib.loads(text)
    assert parsed["accent"] == "#FF0000" and parsed["mode"] == "light"
    assert parsed["dark_foreground"] == "#565f89"  # `foreground` must not match `dark_foreground`
    assert stock_theme.read_text() == COLORS_TOML  # stock theme untouched
    assert (target.parent / pages_look.OVERLAY_MARK).exists()
    assert page.applied == ["Colors applied"]


def test_save_appends_missing_key(stock_theme):
    page = Colors("tokyo-night", stock_theme)
    page.edited["orange"] = "#EB927B"
    page.save()
    parsed = tomllib.loads((pages_look.USER_THEMES / "tokyo-night/colors.toml").read_text())
    assert parsed["orange"] == "#EB927B" and parsed["accent"] == "#7aa2f7"


def test_save_unchanged_is_identical(stock_theme):
    page = Colors("tokyo-night", stock_theme)
    page.save()
    assert (pages_look.USER_THEMES / "tokyo-night/colors.toml").read_text() == COLORS_TOML


def test_save_twice_on_overlay_then_reset_removes_it(stock_theme):
    page = Colors("tokyo-night", stock_theme)
    page.edited["accent"] = "#111111"
    page.save()
    overlay = pages_look.USER_THEMES / "tokyo-night"
    # Second edit starts from the overlay copy, like the page does after a rebuild.
    page2 = Colors("tokyo-night", overlay / "colors.toml")
    page2.edited["accent"] = "#222222"
    page2.save()
    assert tomllib.loads((overlay / "colors.toml").read_text())["accent"] == "#222222"
    assert not (overlay / ("colors.toml" + pages_look.ORIGINAL_SUFFIX)).exists()
    page2.reset()
    assert not overlay.exists()
    assert stock_theme.read_text() == COLORS_TOML


def test_save_on_user_theme_keeps_original_and_reset_restores(sandbox):
    d = pages_look.USER_THEMES / "mine"
    d.mkdir(parents=True)
    (d / "colors.toml").write_text(COLORS_TOML)
    page = Colors("mine", d / "colors.toml")
    page.edited["accent"] = "#ABCDEF"
    page.save()
    original = d / ("colors.toml" + pages_look.ORIGINAL_SUFFIX)
    assert original.read_text() == COLORS_TOML
    assert not (d / pages_look.OVERLAY_MARK).exists()
    page.reset()
    assert (d / "colors.toml").read_text() == COLORS_TOML and not original.exists()


def test_reset_when_never_edited(sandbox):
    d = pages_look.USER_THEMES / "mine"
    d.mkdir(parents=True)
    (d / "colors.toml").write_text(COLORS_TOML)
    page = Colors("mine", d / "colors.toml")
    page.reset()
    assert page.win.toasts == ["These colors have not been edited"] and page.applied == []


def test_save_single_quoted_value(sandbox):
    # TOML literal strings are valid too; editing one must not leave a duplicate key behind.
    d = sandbox.omarchy / "themes/quoted"
    d.mkdir(parents=True)
    (d / "colors.toml").write_text("accent = '#7aa2f7'\nbackground = \"#1a1b26\"\n")
    page = Colors("quoted", d / "colors.toml")
    page.edited["accent"] = "#FF0000"
    page.save()
    parsed = tomllib.loads((pages_look.USER_THEMES / "quoted/colors.toml").read_text())
    assert parsed["accent"] == "#FF0000"


def test_save_against_installed_themes_produces_valid_toml(sandbox):
    """Every installed stock theme's colors.toml survives an edit of every color (copies only)."""
    themes = sorted((REAL_OMARCHY / "themes").glob("*/colors.toml")) if (REAL_OMARCHY / "themes").is_dir() else []
    if not themes:
        pytest.skip("no Omarchy themes installed")
    for src in themes:
        d = sandbox.omarchy / "themes" / src.parent.name
        d.mkdir(parents=True)
        (d / "colors.toml").write_text(src.read_text())
        page = Colors(src.parent.name, d / "colors.toml")
        for k, v in page.colors.items():
            if isinstance(v, str) and v.startswith("#"):
                page.edited[k] = "#123456"
        page.save()
        parsed = tomllib.loads((pages_look.USER_THEMES / src.parent.name / "colors.toml").read_text())
        for k, v in page.edited.items():
            assert parsed[k] == v, (src, k)


def test_save_leaves_tables_alone(sandbox):
    d = sandbox.omarchy / "themes/tabled"
    d.mkdir(parents=True)
    (d / "colors.toml").write_text('accent = "#111111"\n\n[extra]\naccent = "#222222"\n')
    page = Colors("tabled", d / "colors.toml")
    page.edited.update(accent="#FF0000", cyan="#00FFFF")
    page.save()
    parsed = tomllib.loads((pages_look.USER_THEMES / "tabled/colors.toml").read_text())
    assert parsed["accent"] == "#FF0000"
    assert parsed["cyan"] == "#00FFFF"
    assert parsed["extra"] == {"accent": "#222222"}


def test_save_refuses_when_result_would_be_invalid(sandbox, monkeypatch):
    d = sandbox.omarchy / "themes/broken"
    d.mkdir(parents=True)
    (d / "colors.toml").write_text('accent = "#111111"\n')
    page = Colors("broken", d / "colors.toml")
    page.edited["accent"] = "#FF0000"
    monkeypatch.setattr(pages_look, "rewrite_colors", lambda text, changes: text + "accent = \"#FF0000\"\n")
    page.save()
    assert not (pages_look.USER_THEMES / "broken").exists()
    assert page.applied == []
    assert any("not saved" in t for t in page.win.toasts)
