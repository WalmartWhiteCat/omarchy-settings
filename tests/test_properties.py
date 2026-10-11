"""Property tests: rules that must hold for every input, checked by Hypothesis on many generated
ones. Mostly hand-edited settings.json, which must never stop the app from opening or saving, and
the Lua escaping, read back by the real Lua to check it means what was meant.

./test.sh runs a fixed set (the "repeatable" profile in conftest); to look further:
    HYPOTHESIS_PROFILE=explore ./test.sh tests/test_properties.py
A failure prints the smallest input that shows it."""

import json
import math
import re
import shutil
import subprocess

import pytest
from hypothesis import assume, given, strategies as st

from osettings import binds, store as store_mod
from osettings.core import lua_key, lua_str, lua_table, lua_value

from .conftest import REAL_POPEN, luac_error

# --------------------------------------------------------------------------- generators

# Text biased towards what breaks escaping and parsing: quotes, backslashes, newlines, control
# characters, Lua's long brackets and comments, non-ASCII, and Lua/Hyprland words.
TRICKY = ['"', "\\", "\n", "\r", "\t", "\0", "\x7f", "]]", "[[", "--", "'", "%", "$(x)", "é", "日本", "\U0001F600",
          "end", "nil", "function", ":", "+", " ", "SUPER", "code:10", "switch:"]
text = st.one_of(st.text(max_size=12), st.lists(st.sampled_from(TRICKY), max_size=5).map("".join))
names = st.one_of(st.sampled_from(["general", "decoration", "blur", "col", "active_border", "gaps-in", "2fa",
                                   "end", "and", "_x", "x y", "", "plugin", "hyprexpo"]), text)
json_leaf = st.one_of(st.none(), st.booleans(), st.integers(-2**40, 2**40),
                      st.floats(allow_nan=True, allow_infinity=True), text)
json_any = st.recursive(json_leaf, lambda inner: st.lists(inner, max_size=3)
                        | st.dictionaries(names, inner, max_size=3), max_leaves=8)


def or_junk(strategy, p_junk=True):
    """Mostly `strategy`, sometimes any JSON value at all (a hand edit gone wrong)."""
    return st.one_of(strategy, strategy, strategy, json_any) if p_junk else strategy


option = st.one_of(
    st.sampled_from(["general:gaps_in", "general:gaps_out", "general:col:active_border", "decoration:rounding",
                     "decoration:blur:enabled", "input:kb_layout", "plugin:hyprexpo:gesture-distance",
                     "general:col", "gaps", "general", "my-plugin:x", "a::b", ":x", "x:", "", "end:x", "2fa:x"]),
    st.lists(names, min_size=1, max_size=4).map(":".join))
hypr_value = or_junk(st.one_of(st.integers(-100, 100), st.floats(-10, 10), st.booleans(), text,
                               st.fixed_dictionaries({"colors": st.lists(text, max_size=2), "angle": st.integers(0, 360)})))
rule = st.fixed_dictionaries({"class": or_junk(text)}, optional={
    "opacity_active": or_junk(st.floats(0, 1)), "opacity_inactive": or_junk(st.floats(0, 1)),
    "workspace": or_junk(st.one_of(st.integers(1, 10), text, st.sampled_from(["special:steam", "²", "٣", "10"]))),
    "float": json_any, "no_blur": json_any, "enabled": json_any})
monitor = st.fixed_dictionaries({}, optional={
    "enabled": or_junk(st.booleans()), "mode": or_junk(st.sampled_from(["preferred", "2560x1440@144", ""])),
    "x": or_junk(st.integers(-5000, 5000)), "y": or_junk(st.integers(-5000, 5000)),
    "scale": or_junk(st.floats(0.25, 3)), "transform": or_junk(st.integers(0, 7))})
REAL_LINE = 'o.bind("SUPER + RETURN", "Terminal", "uwsm-app -- xdg-terminal-exec")'
rebind = st.fixed_dictionaries({"old": or_junk(text), "new": or_junk(text), "line": or_junk(st.just(REAL_LINE))},
                               optional={"guard": or_junk(st.sampled_from(["o.has_command(\"voxtype\")", None])),
                                         "description": or_junk(text)})
custom = st.fixed_dictionaries({"keys": or_junk(text), "command": or_junk(text)},
                               optional={"description": or_junk(text), "launch": json_any, "enabled": json_any})
autostart = st.fixed_dictionaries({"command": or_junk(text)}, optional={"launch": json_any, "enabled": json_any})
settings = st.fixed_dictionaries({}, optional={
    "hyprland": or_junk(st.dictionaries(option, hypr_value, max_size=5)),
    "cursor": or_junk(st.fixed_dictionaries({}, optional={"theme": or_junk(text), "size": or_junk(st.integers(0, 96))})),
    "monitors": or_junk(st.dictionaries(st.one_of(st.sampled_from(["DP-1", "eDP-1", "HDMI-A-1"]), text), monitor, max_size=3)),
    "rules": or_junk(st.lists(rule, max_size=3)),
    "binds": or_junk(st.fixed_dictionaries({}, optional={
        "disabled": or_junk(st.lists(or_junk(text), max_size=3)),
        "disabled_info": or_junk(st.dictionaries(text, or_junk(text), max_size=2)),
        "rebinds": or_junk(st.lists(rebind, max_size=2)), "custom": or_junk(st.lists(custom, max_size=2))})),
    "autostart": or_junk(st.lists(autostart, max_size=3)),
    "animations": or_junk(st.fixed_dictionaries({}, optional={
        "factor": or_junk(st.floats(0.1, 4)), "windows": or_junk(st.sampled_from(["popin", "gnomed", "slide"])),
        "workspaces": or_junk(st.sampled_from(["off", "slidefade 20%", "slide"]))})),
    "nightlight": or_junk(st.fixed_dictionaries({}, optional={"schedule": json_any})),
    "flags": or_junk(st.fixed_dictionaries({}, optional={"omarchy_opacity": json_any})),
})


def write_settings(data):
    store_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    store_mod.SETTINGS_FILE.write_text(data if isinstance(data, str) else json.dumps(data))


def load_store():
    return store_mod.Store(lambda msg: None)


# --------------------------------------------------------------------------- settings.json


@given(st.one_of(settings, json_any, text))
def test_any_settings_json_opens_renders_and_parses(sandbox, data):
    """Whatever settings.json holds, the app opens, and what it would save is valid Lua it can
    write: a bad entry is dropped on load, not left to fail every save."""
    for leftover in store_mod.CONFIG_DIR.glob("settings.json.broken-*"):
        leftover.unlink()
    write_settings(data)
    s = load_store()
    json.loads(json.dumps(s.to_json()))  # what it saves back reads again
    lua = s.render_lua()
    lua.encode("utf-8")  # writable
    assert luac_error(lua) is None, lua


@given(settings)
def test_cleaned_settings_are_kept_as_they_are(sandbox, data):
    """Loading what the app saved drops nothing more and renders the same Lua: cleaning once is
    enough, so a saved file never shrinks or warns on the next start."""
    write_settings(data)
    first = load_store()
    saved = json.dumps(first.to_json(), indent=2)
    write_settings(saved)
    second = load_store()
    assert second.load_warning is None, second.load_warning
    assert second.to_json() == first.to_json()
    assert second.render_lua() == first.render_lua()


@given(st.dictionaries(st.lists(st.sampled_from(["general", "col", "active_border", "blur", "x"]),
                                min_size=2, max_size=4).map(":".join),
                       st.integers(0, 9), max_size=6))
def test_options_render_into_one_table_each(sandbox, values):
    """Every option kept ends up in the Lua exactly once; one that is also another's section is
    dropped, never rendered as both a value and a table."""
    write_settings({"hyprland": values})
    s = load_store()
    for opt in s.values:
        assert not any(o.startswith(opt + ":") for o in s.values if o != opt)
    assert set(s.values) == {o for o in values if not any(p.startswith(o + ":") for p in values)}
    assert luac_error(s.render_lua()) is None


# --------------------------------------------------------------------------- Lua escaping

# Reads a Lua expression with the real interpreter and prints it back in a form Python can
# compare: strings as hex bytes, integers and floats apart, tables as sorted [key, value] pairs.
# It loads in an empty environment, so even a broken escape can't run anything (no os, no io).
READ_BACK = r"""
local src = io.read("a")
local f, err = load("return " .. src, "=value", "t", {})
if not f then io.stderr:write(err) os.exit(2) end
local ok, v = pcall(f)
if not ok then io.stderr:write(tostring(v)) os.exit(3) end
local function ser(x)
  local t = type(x)
  if t == "string" then return '{"s":"' .. x:gsub(".", function(c) return ("%02x"):format(c:byte()) end) .. '"}' end
  if t == "boolean" then return tostring(x) end
  if t == "number" then
    if math.type(x) == "integer" then return '{"i":"' .. tostring(x) .. '"}' end
    return '{"f":"' .. ("%.17g"):format(x) .. '"}'
  end
  if t == "table" then
    local pairs_ = {}
    for k, val in pairs(x) do pairs_[#pairs_ + 1] = {ser(k), ser(val)} end
    table.sort(pairs_, function(a, b) return a[1] < b[1] end)
    local out = {}
    for _, p in ipairs(pairs_) do out[#out + 1] = "[" .. p[1] .. "," .. p[2] .. "]" end
    return '{"t":[' .. table.concat(out, ",") .. "]}"
  end
  return '{"other":"' .. t .. '"}'
end
io.write(ser(v))
"""

needs_lua = pytest.mark.skipif(not shutil.which("lua"), reason="lua not installed")


def lua_reads(expr):
    """What the real Lua makes of `expr`. Runs the interpreter directly (REAL_POPEN, past the
    sandbox's guard): with an empty environment, nothing it reads can reach the system."""
    with REAL_POPEN(["lua", "-e", READ_BACK], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, text=True) as p:
        out, err = p.communicate(expr, timeout=10)
    assert p.returncode == 0, f"Lua couldn't read {expr!r}: {err}"
    return json.loads(out)


def as_lua(v):
    """What lua_value(v) should read back as, in lua_reads' form (None isn't rendered here)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return {"i": str(v)}
    if isinstance(v, float):
        return {"f": None}  # compared separately: lua_value keeps 4 decimals
    if isinstance(v, (list, tuple)):
        v = {i + 1: x for i, x in enumerate(v)}
    if isinstance(v, dict):
        return {"t": sorted([[as_lua(k), as_lua(x)] for k, x in v.items()], key=lambda kv: json.dumps(kv[0]))}
    return {"s": str(v).encode("utf-8").hex()}


def same(got, want, path="value"):
    if isinstance(want, dict) and "f" in want:
        # A float may come out whole (1e-05 is "0"): Hyprland takes either, as Omarchy's own
        # `sensitivity = 0` shows.
        assert "f" in got or "i" in got, f"{path}: {got} isn't a number"
        return
    if isinstance(want, dict) and "t" in want:
        assert "t" in got, f"{path}: {got} isn't a table"
        gk = {json.dumps(k, sort_keys=True): v for k, v in got["t"]}
        wk = {json.dumps(k, sort_keys=True): v for k, v in want["t"]}
        assert gk.keys() == wk.keys(), f"{path}: keys {sorted(gk)} != {sorted(wk)}"
        for k in wk:
            same(gk[k], wk[k], f"{path}[{k}]")
        return
    assert got == want, f"{path}: {got} != {want}"


# Lua strings are bytes: a lone surrogate (which JSON allows as "\ud800") has no UTF-8 form.
lua_text = st.text(st.characters(exclude_categories=("Cs",)), max_size=20) | st.lists(st.sampled_from(TRICKY), max_size=6).map("".join)


@needs_lua
@given(lua_text)
def test_lua_str_reads_back_as_the_same_text(sandbox, s):
    assert lua_reads(lua_str(s)) == {"s": s.encode("utf-8").hex()}


@needs_lua
@given(st.recursive(st.one_of(st.booleans(), st.integers(-2**53, 2**53), lua_text,
                              st.floats(allow_nan=False, allow_infinity=False, min_value=-1e15, max_value=1e15)),
                    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(lua_text, inner, max_size=3),
                    max_leaves=10))
def test_lua_value_reads_back_as_the_same_value(sandbox, v):
    got = lua_reads(lua_value(v))
    same(got, as_lua(v))


@needs_lua
@given(st.floats(allow_nan=False, allow_infinity=False, min_value=-1e15, max_value=1e15))
def test_lua_value_keeps_floats_to_four_places(sandbox, x):
    got = lua_reads(lua_value(x))
    read = float(got.get("f", got.get("i")))
    assert math.isclose(read, x, abs_tol=5.01e-5, rel_tol=1e-12), (x, lua_value(x), got)


@needs_lua
@given(st.dictionaries(lua_text, st.recursive(st.one_of(st.integers(-9, 9), lua_text, st.booleans()),
                                              lambda inner: st.dictionaries(lua_text, inner, min_size=1, max_size=3),
                                              max_leaves=6), max_size=4))
def test_lua_table_reads_back_as_the_same_table(sandbox, d):
    got = lua_reads("{\n" + "\n".join(lua_table(d)) + "\n}")
    same(got, as_lua(d))


@needs_lua
@given(lua_text)
def test_lua_key_names_the_same_key(sandbox, k):
    got = lua_reads(f"{{ {lua_key(k)} = 1 }}")
    assert got == {"t": [[{"s": k.encode("utf-8").hex()}, {"i": "1"}]]}


# --------------------------------------------------------------------------- window rules


@given(text)
def test_a_rule_matches_its_class_exactly(sandbox, cls):
    """The class is matched literally: special characters in it are escaped, and the match is
    whole (Python's re stands in for Hyprland's regex engine here)."""
    assume(cls)
    line = store_mod.Store.rule_lua({"class": cls, "float": True})
    regex = re.search(r'class = ("(?:[^"\\]|\\.)*")', line).group(1)
    pattern = lua_reads(regex)["s"] if shutil.which("lua") else None
    if pattern is None:
        return
    pattern = bytes.fromhex(pattern).decode("utf-8")
    assert re.fullmatch(pattern, cls, re.S), (cls, pattern)
    assert not re.fullmatch(pattern, cls + "x", re.S)
    assert not re.fullmatch(pattern, "x" + cls, re.S)


# --------------------------------------------------------------------------- shortcuts

keys = st.one_of(text, st.lists(st.sampled_from(["SUPER", "super", "WIN", "SHIFT", "CTRL", "Control", "ALT", "MOD4",
                                                  "J", "Return", "code:10", "F9", "XF86AudioMute", "+", " ", "  +  "]),
                                max_size=5).map(" ".join))


@given(keys)
def test_shortcut_spellings_agree(sandbox, k):
    """However a shortcut is written, its bind spelling means the same keys, writing it again
    changes nothing, and showing it never fails."""
    c = binds.canonical(k)
    assert binds.canonical(c) == c
    if binds.key_count(k) <= 1:
        assert binds.normalize(c) == binds.normalize(k), (k, c)
    binds.pretty(k)
    binds.bare_ok(k)


# --------------------------------------------------------------------------- colors

hex_digits = st.text("0123456789abcdefABCDEF", min_size=2, max_size=2)


@given(st.lists(hex_digits, min_size=4, max_size=4).map("".join))
def test_hyprland_colors_survive_a_round_trip(sandbox, rrggbbaa):
    """A color read from Hyprland and written back is the same color, in either spelling it uses
    (rgba(RRGGBBAA), or AARRGGBB at the start of a gradient)."""
    from osettings.core import rgba_from_hypr, rgba_to_hypr
    want = f"rgba({rrggbbaa.lower()})"
    assert rgba_to_hypr(rgba_from_hypr(f"rgba({rrggbbaa})")) == want
    aarrggbb = rrggbbaa[6:] + rrggbbaa[:6]
    assert rgba_to_hypr(rgba_from_hypr(f"{aarrggbb} 45deg")) == want
