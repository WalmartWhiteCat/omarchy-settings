"""Store.render_lua(): many settings combinations, every output must pass `luac -p`."""

import itertools
import re

import pytest

from osettings import store as store_mod

from .conftest import luac_error

# A pinned copy of Omarchy's default animations so the tests don't depend on the installed version.
ANIMATIONS = [
    {"leaf": "global", "enabled": True, "speed": 10.0, "bezier": "default"},
    {"leaf": "border", "enabled": True, "speed": 5.39, "bezier": "easeOutQuint"},
    {"leaf": "windowsIn", "enabled": True, "speed": 4.1, "bezier": "easeOutQuint", "style": "popin 87%"},
    {"leaf": "windowsOut", "enabled": True, "speed": 1.49, "bezier": "linear", "style": "popin 87%"},
    {"leaf": "fadeSwitch", "enabled": False},
    {"leaf": "workspaces", "enabled": False},
    {"leaf": "specialWorkspace", "enabled": True, "speed": 3.0, "bezier": "easeOutQuint", "style": "slidevert"},
]

WINDOW_STYLES = [None, "slide", "gnomed", "popin"]
WORKSPACE_STYLES = [None, "off", "slide", "slidevert", "fade", "slidefade 20%"]
FACTORS = [0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 100.0]

NASTY = ['say "hi"', "back\\slash", "naïve café — ünïcødé", "line1\nline2", "tab\tand\rcr",
         "]] --[[ ]=]", "$(touch /tmp/pwned) `x` 'q'", "a\\\"b"]


@pytest.fixture(autouse=True)
def pinned_animations(monkeypatch):
    monkeypatch.setattr(store_mod, "DEFAULT_ANIMATIONS", ANIMATIONS)


def assert_valid(text):
    err = luac_error(text)
    assert err is None, f"{err}\n---\n{text}"


def test_empty_store_renders_header_only(make_store):
    s = make_store()
    out = s.render_lua()
    assert out == store_mod.HEADER
    assert 'hl.define_submap("omarchy_settings_capture"' in out
    assert_valid(out)


def test_plain_values_nest_by_colon(make_store):
    s = make_store()
    s.values = {"general:gaps_in": 5, "general:gaps_out": 10, "decoration:rounding": 8,
                "decoration:blur:enabled": False, "decoration:active_opacity": 0.95,
                "input:kb_options": "compose:caps,grp:alt_shift_toggle", "misc:vfr": True}
    out = s.render_lua()
    assert 'section("settings: general", function()' in out
    assert "      gaps_in = 5," in out
    assert "      blur = {\n        enabled = false,\n      }," in out
    assert '      kb_options = "compose:caps,grp:alt_shift_toggle",' in out
    assert "active_opacity = 0.95," in out
    assert_valid(out)


@pytest.mark.parametrize("active, inactive", [
    ("rgba(33ccffee)", "rgba(595959aa)"),
    ({"colors": ["rgba(33ccffee)", "rgba(00ff99ee)"], "angle": 45}, "rgba(595959aa)"),
    ({"colors": ["rgba(ff0000ff)", "rgba(00ff00ff)"], "angle": 0}, None),
    (None, "rgba(000000ff)"),
])
def test_borders_and_group_mirror(make_store, active, inactive):
    s = make_store()
    if active is not None:
        s.values["general:col:active_border"] = active
    if inactive is not None:
        s.values["general:col:inactive_border"] = inactive
    out = s.render_lua()
    assert_valid(out)
    group = out[out.index('section("settings: group"'):]
    if isinstance(active, dict):
        assert 'colors = { "%s", "%s" }' % tuple(active["colors"]) in out
        assert f"angle = {active['angle']}" in out
        assert "border_active = {" in group
    elif active:
        assert f'border_active = "{active}",' in group
    else:
        assert "border_active" not in group
    if inactive:
        assert f'border_inactive = "{inactive}",' in group
    else:
        assert "border_inactive" not in group


def test_group_mirror_keeps_existing_group_options(make_store):
    s = make_store()
    s.values = {"group:groupbar:enabled": False, "general:col:active_border": "rgba(ffffffff)"}
    out = s.render_lua()
    group = out[out.index('section("settings: group"'):]
    assert "enabled = false" in group and 'border_active = "rgba(ffffffff)"' in group
    assert_valid(out)


def test_option_names_with_dashes_and_digits(make_store):
    s = make_store()
    s.values = {"plugin:hyprexpo:gesture-distance": 300, "plugin:my-plugin:some-flag": True,
                "general:snap:window-gap": 10, "device:at-translated-set-2-keyboard:kb_layout": "us",
                "misc:3d": 1}
    out = s.render_lua()
    assert '["gesture-distance"] = 300,' in out
    assert '["my-plugin"] = {' in out
    assert '["at-translated-set-2-keyboard"] = {' in out
    assert '["3d"] = 1,' in out
    assert_valid(out)


@pytest.mark.parametrize("windows, workspaces, factor",
                         list(itertools.product(WINDOW_STYLES, WORKSPACE_STYLES, FACTORS)))
def test_every_animation_combination(make_store, windows, workspaces, factor):
    s = make_store()
    s.anim = {"factor": factor}
    if windows:
        s.anim["windows"] = windows
    if workspaces:
        s.anim["workspaces"] = workspaces
    out = s.render_lua()
    assert_valid(out)
    lines = s.render_animations()
    if factor == 1.0 and not windows and not workspaces:
        assert lines == [] and 'section("animations"' not in out
        return
    assert len(lines) == len(ANIMATIONS)
    by_leaf = {re.search(r'leaf = "(\w+)"', l).group(1): l for l in lines}
    win_style = {None: "popin 87%", "popin": "popin 87%"}.get(windows, windows)
    for leaf in ("windowsIn", "windowsOut"):
        assert f'style = "{win_style}"' in by_leaf[leaf]
    ws = by_leaf["workspaces"]
    if workspaces in (None, "off"):
        assert "enabled = false" in ws and "speed" not in ws
    else:
        assert f'style = "{workspaces}"' in ws and "enabled = true" in ws
    for a in ANIMATIONS:
        if "speed" in a and a["leaf"] != "workspaces":
            want = a["speed"] if factor == 1.0 else round(max(0.1, a["speed"] / factor), 2)
            got = float(re.search(r"speed = ([\d.]+)", by_leaf[a["leaf"]]).group(1))
            assert got == pytest.approx(want), a["leaf"]
    assert "speed" not in by_leaf["fadeSwitch"]


def test_animation_speed_never_below_floor(make_store):
    s = make_store()
    s.anim = {"factor": 1000.0}
    for line in s.render_animations():
        m = re.search(r"speed = ([\d.]+)", line)
        if m:
            assert float(m.group(1)) >= 0.1


def test_animation_factor_falsy_means_default(make_store):
    s = make_store()
    s.anim = {"factor": 0}
    assert s.render_animations() == []


def test_render_does_not_mutate_default_animations(make_store):
    before = [dict(a) for a in ANIMATIONS]
    s = make_store()
    s.anim = {"factor": 2.0, "windows": "slide", "workspaces": "fade"}
    s.render_lua()
    assert ANIMATIONS == before


def test_real_omarchy_animations_render(make_store, monkeypatch):
    """Same check against whatever looknfeel.lua is installed (read only)."""
    from .conftest import REAL_OMARCHY
    monkeypatch.setattr(store_mod, "OMARCHY_PATH", REAL_OMARCHY)
    real = store_mod._parse_animations()
    if not real:
        pytest.skip("no Omarchy looknfeel.lua installed")
    monkeypatch.setattr(store_mod, "DEFAULT_ANIMATIONS", real)
    s = make_store()
    s.anim = {"factor": 1.5, "windows": "slide", "workspaces": "slidefade 20%"}
    out = s.render_lua()
    assert len(s.render_animations()) == len(real)
    assert_valid(out)


def test_parse_animations_from_fixture(sandbox, monkeypatch):
    f = sandbox.omarchy / "default/hypr/looknfeel.lua"
    f.parent.mkdir(parents=True)
    f.write_text('hl.curve("quick", { type = "bezier", points = { { 0.15, 0 }, { 0.1, 1 } } })\n'
                 'hl.animation({ leaf = "global", enabled = true, speed = 10, bezier = "default" })\n'
                 '  hl.animation({ leaf = "windowsIn", enabled = true, speed = 4.1, style = "popin 87%" })  \n'
                 'hl.animation({ leaf = "fadeSwitch", enabled = false })\n'
                 '-- hl.animation({ leaf = "commented", enabled = true })\n'
                 'hl.animation({ enabled = true })\n')
    assert store_mod._parse_animations() == [
        {"leaf": "global", "enabled": True, "speed": 10.0, "bezier": "default"},
        {"leaf": "windowsIn", "enabled": True, "speed": 4.1, "style": "popin 87%"},
        {"leaf": "fadeSwitch", "enabled": False},
    ]


# ------------------------------------------------------------------ cursor


@pytest.mark.parametrize("cursor", [{}, {"theme": "Bibata-Modern-Ice"}, {"size": 32}, {"size": "24"},
                                    {"theme": 'we"ird\\theme', "size": 48.0}])
def test_cursor(make_store, cursor):
    s = make_store()
    s.cursor = cursor
    out = s.render_lua()
    assert_valid(out)
    if cursor.get("theme"):
        assert f'hl.env("XCURSOR_THEME", {store_mod.lua_str(cursor["theme"])})' in out
    if cursor.get("size"):
        assert f'hl.env("XCURSOR_SIZE", "{int(float(cursor["size"]))}")' in out
    if not cursor:
        assert 'section("cursor"' not in out


# ------------------------------------------------------------------ monitors


@pytest.mark.parametrize("name, m, expected", [
    ("eDP-1", {"enabled": False}, 'hl.monitor({ output = "eDP-1", disabled = true })'),
    ("eDP-1", {}, 'hl.monitor({ output = "eDP-1", mode = "preferred", position = "auto", scale = 1 })'),
    ("DP-1", {"mode": "2560x1440@144", "x": 0, "y": 0, "scale": 1.25},
     'hl.monitor({ output = "DP-1", mode = "2560x1440@144", position = "0x0", scale = 1.25 })'),
    ("DP-2", {"mode": "1920x1080@60", "x": -1920, "y": 120.0, "scale": 1, "transform": 1},
     'hl.monitor({ output = "DP-2", mode = "1920x1080@60", position = "-1920x120", scale = 1, transform = 1 })'),
    ("HDMI-A-1", {"mode": "3840x2160@60", "x": 2560, "y": 0, "scale": 2.0, "transform": 3},
     'hl.monitor({ output = "HDMI-A-1", mode = "3840x2160@60", position = "2560x0", scale = 2.0, transform = 3 })'),
    ("DP-3", {"x": 0, "y": 0, "transform": 0},
     'hl.monitor({ output = "DP-3", mode = "preferred", position = "0x0", scale = 1 })'),
    ("desc:Dell Inc. U2720Q \"x\"", {"enabled": True},
     r'hl.monitor({ output = "desc:Dell Inc. U2720Q \"x\"", mode = "preferred", position = "auto", scale = 1 })'),
])
def test_monitor_lua(name, m, expected):
    assert store_mod.Store.monitor_lua(name, m) == expected
    assert luac_error(expected) is None


def test_monitors_section(make_store):
    s = make_store()
    s.monitors = {"eDP-1": {"enabled": False},
                  "DP-1": {"mode": "2560x1440@144", "x": 0, "y": 0, "scale": 1.333333, "transform": 1}}
    out = s.render_lua()
    assert 'section("monitor eDP-1", function()' in out
    assert 'section("monitor DP-1", function()' in out
    assert "transform = 1" in out
    assert_valid(out)


# ------------------------------------------------------------------ window rules


@pytest.mark.parametrize("cls", ["firefox", "org.gnome.Nautilus", "com.mitchellh.ghostty", "Code - OSS",
                                 "a.b*c+d?e(f)g[h]i{j}k|l^m$n\\o", 'quote"class', "steam_app_[0-9]+",
                                 "Ünïcødé"])
def test_rule_class_is_escaped_regex(cls):
    line = store_mod.Store.rule_lua({"class": cls, "float": True})
    assert luac_error(line) is None
    m = re.search(r'class = ("(?:\\.|[^"\\])*")', line)
    # Undo Lua string escaping, then the regex must match the literal class and nothing longer.
    lua_literal = m.group(1)[1:-1]
    regex = re.sub(r'\\(["\\])', r"\1", lua_literal)
    assert re.fullmatch(regex, cls)
    assert not re.fullmatch(regex, cls + "x")
    assert not re.fullmatch(regex, "x" + cls)


@pytest.mark.parametrize("rule, expected", [
    ({"class": "x"}, None),
    ({"class": "x", "float": False, "no_blur": False}, None),
    ({"class": "x", "float": True}, 'hl.window_rule({ match = { class = "^(x)$" }, float = true })'),
    ({"class": "x", "opacity_active": 0.9},
     'hl.window_rule({ match = { class = "^(x)$" }, opacity = "0.90 0.90" })'),
    ({"class": "x", "opacity_active": 1, "opacity_inactive": 0.75},
     'hl.window_rule({ match = { class = "^(x)$" }, opacity = "1.00 0.75" })'),
    ({"class": "x", "opacity_inactive": 0.5},
     'hl.window_rule({ match = { class = "^(x)$" }, opacity = "1.00 0.50" })'),
    ({"class": "x", "no_blur": True, "workspace": 3.0},
     'hl.window_rule({ match = { class = "^(x)$" }, no_blur = true, workspace = "3" })'),
])
def test_rule_lua(rule, expected):
    assert store_mod.Store.rule_lua(rule) == expected


def test_rules_section_skips_disabled_and_classless(make_store):
    s = make_store()
    s.rules = [{"class": "on.app", "float": True},
               {"class": "off.app", "float": True, "enabled": False},
               {"class": "", "float": True},
               {"class": "noop.app"},
               {"class": "re[gex](.*)", "workspace": 2, "opacity_active": 0.8}]
    out = s.render_lua()
    assert 'section("window rule on.app"' in out
    assert "off.app" not in out
    assert "noop.app" not in out
    assert out.count("hl.window_rule(") == 2
    assert_valid(out)


# ------------------------------------------------------------------ binds


REBIND_LINE = 'o.bind("SUPER + RETURN", "Terminal", { omarchy = "terminal" })'


def test_disabled_binds(make_store):
    s = make_store()
    s.binds["disabled"] = ["SUPER + W", 'SUPER + "odd"']
    out = s.render_lua()
    assert 'hl.unbind("SUPER + W")' in out
    assert r'hl.unbind("SUPER + \"odd\"")' in out
    assert_valid(out)


def test_rebind_replaces_only_the_key(make_store):
    s = make_store()
    s.binds["rebinds"] = [{"old": "SUPER + RETURN", "new": "SUPER + T", "line": "  " + REBIND_LINE + "  "}]
    out = s.render_lua()
    body = out[out.index('section("shortcut SUPER + T"'):]
    assert body.splitlines()[1:4] == [
        '  hl.unbind("SUPER + RETURN")',
        '  hl.unbind("SUPER + T")',
        '  o.bind("SUPER + T", "Terminal", { omarchy = "terminal" })',
    ]
    assert_valid(out)


def test_rebind_only_first_occurrence(make_store):
    s = make_store()
    line = 'o.bind("SUPER + K", "Says SUPER + K", "notify-send \\"SUPER + K\\"")'
    s.binds["rebinds"] = [{"old": "SUPER + K", "new": "SUPER + J", "line": line}]
    out = s.render_lua()
    assert 'o.bind("SUPER + J", "Says SUPER + K", "notify-send \\"SUPER + K\\"")' in out
    assert_valid(out)


@pytest.mark.parametrize("command", NASTY)
@pytest.mark.parametrize("launch", [False, True])
def test_custom_shortcut_escaping(make_store, command, launch):
    s = make_store()
    s.binds["custom"] = [{"keys": "SUPER + ALT + Q", "command": command, "launch": launch,
                          "description": command[::-1]}]
    out = s.render_lua()
    assert_valid(out)
    q = store_mod.lua_str(command)
    action = f"{{ launch = {q} }}" if launch else q
    assert f'o.bind("SUPER + ALT + Q", {store_mod.lua_str(command[::-1])}, {action})' in out
    assert 'hl.unbind("SUPER + ALT + Q")' in out


@pytest.mark.parametrize("keys", ['SUPER + "', "SUPER + \\", "SUPER + é", "SUPER +\nX"])
def test_custom_shortcut_keys_escaped(make_store, keys):
    s = make_store()
    s.binds["custom"] = [{"keys": keys, "command": "true"}]
    assert_valid(s.render_lua())


def test_custom_shortcut_defaults_and_skips(make_store):
    s = make_store()
    s.binds["custom"] = [{"keys": "SUPER + A", "command": "foo"},
                         {"keys": "SUPER + B", "command": "bar", "enabled": False},
                         {"keys": "", "command": "baz"},
                         {"keys": "SUPER + C", "command": ""},
                         {"keys": "SUPER + D", "command": "qux", "description": ""}]
    out = s.render_lua()
    assert 'o.bind("SUPER + A", "foo", "foo")' in out
    assert 'o.bind("SUPER + D", "qux", "qux")' in out
    assert "bar" not in out and "baz" not in out and "SUPER + C" not in out
    assert_valid(out)


# ------------------------------------------------------------------ autostart / night light


@pytest.mark.parametrize("command", NASTY + ["waybar", "uwsm app -- foo --bar=1"])
def test_autostart_escaping(make_store, command):
    s = make_store()
    s.autostart = [{"command": command, "launch": True}, {"command": command, "launch": False}]
    out = s.render_lua()
    q = store_mod.lua_str(command)
    assert f"o.launch_on_start({q})" in out
    assert f"o.exec_on_start({q})" in out
    assert_valid(out)


def test_autostart_skips_disabled_and_empty_and_defaults_to_launch(make_store):
    s = make_store()
    s.autostart = [{"command": "a"}, {"command": "b", "enabled": False}, {"command": ""}, {}]
    out = s.render_lua()
    auto = out[out.index('section("autostart"'):]
    assert 'o.launch_on_start("a")' in auto
    assert '"b"' not in auto
    assert auto.count("_on_start(") == 1


@pytest.mark.parametrize("nightlight, expect", [
    ({}, False),
    ({"schedule": False, "temperature": 3500}, False),
    ({"schedule": True, "start": "20:00", "end": "07:00", "temperature": 4000}, True),
])
def test_nightlight_schedule(make_store, nightlight, expect):
    s = make_store()
    s.nightlight = nightlight
    out = s.render_lua()
    assert ('o.launch_on_start("hyprsunset")' in out) == expect
    assert_valid(out)


# ------------------------------------------------------------------ everything at once


def kitchen_sink():
    return {
        "hyprland": {
            "general:gaps_in": 3, "general:gaps_out": 6, "general:border_size": 2, "general:layout": "master",
            "general:col:active_border": {"colors": ["rgba(33ccffee)", "rgba(00ff99ee)"], "angle": 45},
            "general:col:inactive_border": "rgba(595959aa)",
            "decoration:rounding": 10, "decoration:blur:enabled": True, "decoration:blur:size": 4,
            "decoration:shadow:color": "rgba(1a1a1aee)", "decoration:inactive_opacity": 0.9,
            "animations:enabled": True, "input:kb_layout": "us,fr", "input:kb_options": "compose:caps",
            "input:touchpad:natural_scroll": True, "input:sensitivity": -0.25,
            "plugin:hyprexpo:gesture-distance": 300,
        },
        "cursor": {"theme": "Bibata", "size": 28},
        "monitors": {"eDP-1": {"enabled": False},
                     "DP-1": {"mode": "2560x1440@144", "x": 0, "y": 0, "scale": 1.25, "transform": 0},
                     "DP-2": {"mode": "1920x1080@60", "x": 2048, "y": 0, "scale": 1, "transform": 3}},
        "rules": [{"class": "org.gnome.Calculator", "float": True},
                  {"class": "steam_app_[0-9]+ (game)", "workspace": 5, "no_blur": True,
                   "opacity_active": 1.0, "opacity_inactive": 0.85}],
        "binds": {"disabled": ["SUPER + W"],
                  "rebinds": [{"old": "SUPER + RETURN", "new": "SUPER + T", "line": REBIND_LINE}],
                  "custom": [{"keys": "SUPER + ALT + N", "command": 'notify-send "héllo\\nwörld"',
                              "description": "Say \"hi\"\nnow", "launch": False},
                             {"keys": "SUPER + ALT + B", "command": "btop", "launch": True}]},
        "autostart": [{"command": "nm-applet --indicator", "launch": True},
                      {"command": "echo 'started' >> /tmp/x", "launch": False}],
        "animations": {"factor": 1.5, "windows": "gnomed", "workspaces": "slidefade 20%"},
        "pins": {"color_scheme": "prefer-dark"},
        "nightlight": {"schedule": True, "start": "21:00", "end": "06:30", "temperature": 3800},
    }


def test_kitchen_sink(make_store):
    s = make_store(kitchen_sink())
    out = s.render_lua()
    assert_valid(out)
    order = ['section("capture submap"', 'section("settings: general"', 'section("animations"',
             'section("cursor"', 'section("monitor eDP-1"', 'section("window rule ', 'section("unbind SUPER + W"',
             'section("shortcut SUPER + T"', 'section("shortcut SUPER + ALT + N"', 'section("autostart"']
    positions = [out.index(o) for o in order]
    assert positions == sorted(positions)
    # every generated statement sits inside a section() so one failure can't take the rest down
    for line in out[len(store_mod.HEADER):].splitlines():
        assert not line or line.startswith(("section(", "  ")) or line == "end)", line
