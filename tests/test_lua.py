"""lua_str / lua_key / lua_value / lua_table escaping."""

import pytest

from osettings.core import lua_key, lua_str, lua_table, lua_value

from .conftest import luac_error


def lua_eval(expr):
    """Assert `expr` is a valid Lua expression (as the right-hand side of an assignment)."""
    err = luac_error(f"local x = {expr}\n")
    assert err is None, f"{expr!r}: {err}"


@pytest.mark.parametrize("s, expected", [
    ("", '""'),
    ("plain", '"plain"'),
    ('say "hi"', r'"say \"hi\""'),
    ("back\\slash", r'"back\\slash"'),
    ("line\nbreak", r'"line\nbreak"'),
    ("tab\there", r'"tab\009here"'),
    ("cr\r", r'"cr\013"'),
    ("nul\0", r'"nul\000"'),
    ("del\x7f", r'"del\127"'),
    ("café ñ 日本", '"café ñ 日本"'),
    ("trailing\\", r'"trailing\\"'),
    ("\\\"", r'"\\\""'),
])
def test_lua_str_exact(s, expected):
    assert lua_str(s) == expected
    lua_eval(lua_str(s))


def test_lua_str_control_char_before_digit_stays_three_digits():
    # "\0015" must be read by Lua as \001 followed by "5", so the escape is always 3 digits wide.
    assert lua_str("\x015") == r'"\0015"'
    lua_eval(lua_str("\x015"))


@pytest.mark.parametrize("s", [
    "]]", "[[", "--[[", "]=]", "'single'", "%s %d", "$(rm -rf ~)", "a\\nb", "\\x41", "\\u{41}",
    "".join(chr(i) for i in range(0, 128)),
])
def test_lua_str_always_parses(s):
    lua_eval(lua_str(s))


def test_lua_str_coerces_non_strings():
    assert lua_str(5) == '"5"'
    assert lua_str(None) == '"None"'


@pytest.mark.parametrize("k, expected", [
    ("gaps_in", "gaps_in"),
    ("col", "col"),
    ("border-size", '["border-size"]'),
    ("2fa", '["2fa"]'),
    ("with space", '["with space"]'),
    ("quo\"te", r'["quo\"te"]'),
])
def test_lua_key(k, expected):
    assert lua_key(k) == expected
    lua_eval("{ " + lua_key(k) + " = 1 }")


@pytest.mark.parametrize("v, expected", [
    (True, "true"),
    (False, "false"),
    (0, "0"),
    (-3, "-3"),
    (1.0, "1.0"),
    (2.0, "2.0"),
    (0.5, "0.5"),
    (1.25, "1.25"),
    (4 / 3, "1.3333"),
    (0.00001, "0"),
    (-0.75, "-0.75"),
    ("str", '"str"'),
    ([1, "a", True], '{ 1, "a", true }'),
    ((0.5, 2), "{ 0.5, 2 }"),
    ([], "{  }"),
    ({}, "{  }"),
    ({"a": 1, "b-c": "x"}, '{ a = 1, ["b-c"] = "x" }'),
    ({"colors": ["rgba(33ccffee)", "rgba(00ff99ee)"], "angle": 45},
     '{ colors = { "rgba(33ccffee)", "rgba(00ff99ee)" }, angle = 45 }'),
])
def test_lua_value(v, expected):
    assert lua_value(v) == expected
    lua_eval(lua_value(v))


def test_lua_value_bool_is_not_rendered_as_int():
    # bool is a subclass of int; the bool branch must win.
    assert lua_value(True) == "true"
    assert lua_value([False]) == "{ false }"


def test_lua_value_nested():
    v = {"match": {"class": "^(a\\.b)$"}, "opacity": "0.90 0.80", "float": True}
    out = lua_value(v)
    assert out == r'{ match = { class = "^(a\\.b)$" }, opacity = "0.90 0.80", float = true }'
    lua_eval(out)


def test_lua_table_nested_and_flat():
    lines = lua_table({"gaps_in": 5, "col": {"active_border": "rgba(ffffffff)"},
                       "snap": {"enabled": True, "window-gap": 10}}, indent=1)
    assert lines == [
        "  gaps_in = 5,",
        "  col = {",
        '    active_border = "rgba(ffffffff)",',
        "  },",
        "  snap = {",
        "    enabled = true,",
        '    ["window-gap"] = 10,',
        "  },",
    ]
    assert luac_error("local t = {\n" + "\n".join(lines) + "\n}\n") is None


def test_lua_table_value_marker_renders_inline():
    lines = lua_table({"x": {"__value__": True, "a": 1}})
    assert lines == ['  x = { __value__ = true, a = 1 },']


@pytest.mark.parametrize("k", ["end", "nil", "function", "café"])
def test_lua_key_never_emits_invalid_identifier(k):
    # Python identifiers are a superset of Lua's: keywords and non-ASCII letters are not valid Lua names.
    lua_eval("{ " + lua_key(k) + " = 1 }")


# Lua 5.4/5.5's reserved words, listed here rather than taken from core, so a word missing
# from core's own list fails.
RESERVED = ["and", "break", "do", "else", "elseif", "end", "false", "for", "function", "goto", "if", "in",
            "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while"]


@pytest.mark.parametrize("word", RESERVED)
def test_lua_key_quotes_every_reserved_word(word):
    assert lua_key(word) == f'["{word}"]'
    lua_eval("{ " + lua_key(word) + " = 1 }")
