"""binds.parse_default_binds(), normalize() and pretty()."""

import re
import textwrap

import pytest

from osettings import binds

from .conftest import REAL_OMARCHY

PRINT_CMD = ("omarchy", "menu", "keybindings", "--print")


def write_binds(sandbox, **files):
    d = sandbox.omarchy / "default/hypr/bindings"
    d.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (d / f"{name}.lua").write_text(textwrap.dedent(text))


def by_keys(entries):
    return {e["keys"]: e for e in entries}


# ------------------------------------------------------------------ an independent block counter


def _strip(line):
    line = re.sub(r'"(?:\\.|[^"\\])*"' + r"|'(?:\\.|[^'\\])*'", '""', line)
    return line.split("--", 1)[0]


def loop_or_function_lines(text):
    """Line numbers (0-based) that sit inside a for/while/repeat loop or a function body,
    using token-level Lua block matching rather than the app's line heuristics."""
    stack, inside = [], set()
    for i, raw in enumerate(text.splitlines()):
        if any(k in ("loop", "function") for k in stack):
            inside.add(i)
        for tok in re.findall(r"[A-Za-z_]\w*", _strip(raw)):
            if tok == "function":
                stack.append("function")
            elif tok in ("for", "while"):
                stack.append("loop-head")
            elif tok == "do":
                if stack and stack[-1] == "loop-head":
                    stack[-1] = "loop"
                else:
                    stack.append("do")
            elif tok == "repeat":
                stack.append("loop")
            elif tok == "if":
                stack.append("if")
            elif tok in ("end", "until") and stack:
                stack.pop()
    return inside


# ------------------------------------------------------------------ fixture files


FIXTURE = {
    "applications": """\
        -- comment o.bind("SUPER + Z", "commented out", "x")
        o.bind("SUPER + RETURN", "Terminal", { omarchy = "terminal" })
        o.bind( "SUPER + SHIFT + B", "Browser", { omarchy = "browser --private" })
        o.bind("SUPER + SHIFT + A", "ChatGPT", { webapp = "https://chatgpt.com/?q=a&b=c" })
        if o.preinstalled_bindings_enabled() then
          o.bind("SUPER + SHIFT + M", "Music", { tui = "cliamp", focus = true })
        end
        o.bind("SUPER + N", "Editor", "omarchy-launch-editor")
    """,
    "tiling": """\
        o.bind("SUPER + LEFT", "Focus left", hl.dsp.focus({ direction = "l" }))
        for workspace = 1, 10 do
          local key = "code:" .. tostring(workspace + 9)
          o.bind("SUPER + code:10", "Literal in loop", hl.dsp.focus({ workspace = "1" }))
          o.bind("SUPER + " .. key, "Switch to workspace " .. workspace, hl.dsp.focus({ workspace = tostring(workspace) }))
        end
        for i = 1, 3 do o.bind("SUPER + F" .. i, "Inline loop", "x") end
        o.bind("SUPER + TAB", "Next workspace", hl.dsp.focus({ workspace = "e+1" }))
        while false do
          o.bind("SUPER + W", "In while", "x")
        end
    """,
    "utilities": """\
        local function helper(mods, key)
          o.bind("SUPER + H", "In local function", "x")
          return function()
            o.bind("SUPER + I", "In nested function", "x")
          end
        end
        o.bind("SUPER + J", "After function", "x")
        hl.on("layer.opened", function(layer)
          o.bind("SUPER + K", "In callback", "x")
          if layer then
            o.bind("SUPER + L", "In if inside callback", "x")
          end
        end)
        o.bind("SUPER + M", "After callback", "x")
        local handler = function()
          o.bind("SUPER + O", "In assigned function", "x")
        end
        o.bind("SUPER + CTRL + Z", "Zoom in", function()
          o.bind("SUPER + P", "Inside multi-line bind body", "x")
        end)
        o.bind("SUPER + CTRL + ALT + Z", "Reset zoom", function() hl.config({}) end)
        o.bind("SUPER + Q", "After zoom", "x")
        o.bind(
          "SUPER + CTRL + code:10",
          "Multi-line call",
          "x"
        )
        o.bind("SUPER + R", "Uses a local", helper("a", "b"))
        o.bind("SUPER + S", "Uses a variable", some_dispatcher)
        o.bind("SUPER + T", "Concatenation", "omarchy-" .. name)
        o.bind_toggle("SUPER + U", "Toggle", "nightlight")
        hl.bind("SUPER + V", "Raw hl.bind", hl.dsp.exec_cmd("x"))
        hl.bind("SUPER + SHIFT + V", hl.dsp.exec_cmd("no description, not listed"))
        o.bind("SUPER + CTRL + ALT + Y", "Closure with upvalue", function() helper() end)
        o.bind("SUPER + X", nil, "no description")
        o.bind("SUPER + Y", "Parens in string )(", "echo '(' \\"{\\"")
        o.bind("F9", "Release", "voxtype record stop", { release = true })
    """,
}


@pytest.fixture
def parsed(sandbox):
    write_binds(sandbox, **FIXTURE)
    return by_keys(binds.parse_default_binds())


@pytest.mark.parametrize("keys", [
    "SUPER + code:10", "SUPER + F", "SUPER + W", "SUPER + H", "SUPER + I", "SUPER + K", "SUPER + L",
    "SUPER + O", "SUPER + P",
])
def test_nothing_in_loops_or_functions_is_rebindable(parsed, keys):
    if keys == "SUPER + F":  # `"SUPER + F" .. i` isn't a plain literal key; must not appear rebindable at all
        assert not any(e["rebindable"] for k, e in parsed.items() if k.startswith("SUPER + F"))
        return
    assert keys in parsed
    assert parsed[keys]["rebindable"] is False


@pytest.mark.parametrize("keys", [
    "SUPER + RETURN", "SUPER + SHIFT + B", "SUPER + SHIFT + A", "SUPER + SHIFT + M", "SUPER + N",
    "SUPER + LEFT", "SUPER + TAB", "SUPER + J", "SUPER + M", "SUPER + Q", "SUPER + U", "SUPER + V",
    "SUPER + X", "SUPER + Y", "F9",
])
def test_single_line_literal_binds_are_rebindable(parsed, keys):
    assert parsed[keys]["rebindable"] is True, parsed[keys]["line"]


@pytest.mark.parametrize("keys", ["SUPER + CTRL + Z", "SUPER + R", "SUPER + S", "SUPER + T",
                                  "SUPER + CTRL + ALT + Y"])
def test_binds_with_code_are_not_rebindable(parsed, keys):
    assert parsed[keys]["rebindable"] is False


def test_self_contained_one_line_closure_is_rebindable(parsed):
    # Only hl.* inside, so the line still works when lifted into the generated file.
    assert parsed["SUPER + CTRL + ALT + Z"]["rebindable"] is True


def test_hl_bind_without_description_is_not_listed(parsed):
    assert "SUPER + SHIFT + V" not in parsed


def test_multi_line_call_is_not_listed_from_files(parsed):
    assert "SUPER + CTRL + code:10" not in parsed


def test_comment_is_ignored(parsed):
    assert "SUPER + Z" not in parsed


def test_entry_fields(parsed):
    e = parsed["SUPER + RETURN"]
    assert e == {"keys": "SUPER + RETURN", "description": "Terminal", "group": "applications", "rebindable": True,
                 "line": 'o.bind("SUPER + RETURN", "Terminal", { omarchy = "terminal" })', "guard": None}
    assert parsed["SUPER + X"]["description"] == ""
    assert parsed["SUPER + V"]["group"] == "utilities"


def test_missing_files_are_skipped(sandbox):
    write_binds(sandbox, media='o.bind("XF86AudioMute", "Mute", "pamixer -t")\n')
    out = binds.parse_default_binds()
    assert [e["keys"] for e in out] == ["XF86AudioMute"]


def test_printed_list_adds_only_unseen_bindings(sandbox):
    write_binds(sandbox, tiling='o.bind("SUPER + TAB", "Next workspace", "x")\n')
    sandbox.run_output[PRINT_CMD] = "\n".join([
        "SUPER + TAB → Next workspace (dupe)",
        "super tab → Same keys, other spelling",
        "SUPER + 1 → Switch to workspace 1",
        "SUPER + 1 → Duplicate in printed list",
        "a header line without an arrow",
        "SUPER + SHIFT + 1  →  Move to → workspace 1 ",
    ])
    out = binds.parse_default_binds()
    assert [(e["keys"], e["description"], e["group"], e["rebindable"], e["line"]) for e in out] == [
        ("SUPER + TAB", "Next workspace", "tiling", True, 'o.bind("SUPER + TAB", "Next workspace", "x")'),
        ("SUPER + 1", "Switch to workspace 1", "other", False, None),
        ("SUPER + SHIFT + 1", "Move to → workspace 1", "other", False, None),
    ]
    assert sandbox.run == [list(PRINT_CMD)]


def test_installed_omarchy_bindings_never_lift_code_out_of_blocks(sandbox, monkeypatch):
    """Against the real binding files (read only): a rebindable bind must never come from inside a
    loop or a function, and every single-line literal bind at top level / in an `if` should be rebindable."""
    if not (REAL_OMARCHY / "default/hypr/bindings").is_dir():
        pytest.skip("Omarchy not installed")
    monkeypatch.setattr(binds, "OMARCHY_PATH", REAL_OMARCHY)
    out = binds.parse_default_binds()
    assert out
    checked = 0
    for name, f in binds.binding_files():
        lines = f.read_text().splitlines()
        inside = loop_or_function_lines(f.read_text())
        entries = [e for e in out if e["group"] == name]
        for e in entries:
            idx = [i for i, l in enumerate(lines) if l.strip() == e["line"]]
            assert idx, e
            if any(i in inside for i in idx):
                assert e["rebindable"] is False, f"{name}.lua: {e['line']}"
                checked += 1
            elif re.fullmatch(r'o\.bind\(\s*"[^"]+"\s*,\s*"[^"]*"\s*,\s*("[^"]*"|\{[^{}()]*\})\s*'
                              r'(,\s*\{[^{}()]*\})?\)', e["line"]):
                assert e["rebindable"] is True, f"{name}.lua: {e['line']}"
                checked += 1
    assert checked


def test_block_counter_sanity():
    text = "for i=1,2 do\n  a()\nend\nb()\nlocal f = function()\n  c()\nend\nif x then\n  d()\nend\n"
    assert loop_or_function_lines(text) == {1, 2, 5, 6}


# ------------------------------------------------------------------ normalize / pretty


@pytest.mark.parametrize("a, b", [
    ("SUPER + SHIFT + Return", "SUPER SHIFT RETURN"),
    ("super+shift+return", "SHIFT + SUPER + RETURN"),
    ("WIN + Q", "SUPER + q"),
    ("MOD4 + Q", "LOGO + Q"),
    ("CONTROL + ALT + T", "ALT + CTRL + T"),
    ("MOD1 + F4", "ALT + F4"),
    ("  SUPER  +  Q  ", "SUPER + Q"),
    ("SUPER + SUPER + Q", "SUPER + Q"),
])
def test_normalize_equivalent(a, b):
    assert binds.normalize(a) == binds.normalize(b)


@pytest.mark.parametrize("keys, expected", [
    ("SUPER + SHIFT + Return", (("SUPER", "SHIFT"), "return")),
    ("ALT + CTRL + SHIFT + SUPER + x", (("SUPER", "SHIFT", "CTRL", "ALT"), "x")),
    ("F9", ((), "f9")),
    ("SUPER + code:10", (("SUPER",), "1")),  # keycodes compare as the key they produce
    ("SUPER + code:200", (("SUPER",), "code:200")),  # unknown keycode stays as written
    ("XF86AudioRaiseVolume", ((), "xf86audioraisevolume")),
    ("SUPER", (("SUPER",), "")),
    ("", ((), "")),
])
def test_normalize(keys, expected):
    assert binds.normalize(keys) == expected


def test_normalize_distinguishes_different_keys():
    assert binds.normalize("SUPER + Q") != binds.normalize("SUPER + SHIFT + Q")
    assert binds.normalize("SUPER + Q") != binds.normalize("SUPER + W")


@pytest.mark.parametrize("keys, expected", [
    ("SUPER + RETURN", "Super + Enter"),
    ("SUPER + SHIFT + space", "Super + Shift + Space"),
    ("ALT + CTRL + Delete", "Ctrl + Alt + Delete"),
    ("SUPER + q", "Super + Q"),
    ("SUPER + COMMA", "Super + ,"),
    ("SUPER + PERIOD", "Super + ."),
    ("SUPER + SHIFT + SLASH", "Super + Shift + /"),
    ("SUPER + LEFT", "Super + ←"),
    ("SUPER + ESCAPE", "Super + Esc"),
    ("PRINT", "PrtSc"),
    ("SUPER + code:10", "Super + 1"),
    ("SUPER + code:18", "Super + 9"),
    ("SUPER + code:19", "Super + 0"),
    ("SUPER + code:20", "Super + -"),
    ("SUPER + code:9", "Super + Code:9"),
    ("XF86AudioMute", "Xf86audiomute"),
    ("F9", "F9"),
])
def test_pretty(keys, expected):
    assert binds.pretty(keys) == expected


def test_keyword_inside_a_string_does_not_open_a_block(sandbox):
    # The block tracker must look at code, not at descriptions or commands.
    write_binds(sandbox, media="""\
        o.bind("SUPER + A", "Show function(s) help", "omarchy-help")
        o.bind("SUPER + B", "After", "x")
    """)
    out = by_keys(binds.parse_default_binds())
    assert out["SUPER + A"]["rebindable"] is True
    assert out["SUPER + B"]["rebindable"] is True


def test_binding_files_omarchy_adds_or_renames_are_read(sandbox):
    """The file list used to be fixed, so a renamed file's shortcuts looked gone (and changes to
    them were dropped at startup). Known files keep their order and titles; others follow."""
    write_binds(sandbox,
                tiling='o.bind("SUPER + J", "Toggle split", "x")\n',
                windows='o.bind("SUPER + W", "Close window", "y")\n',
                **{"screen-capture": 'o.bind("SUPER + P", "Screenshot", "z")\n'})
    out = binds.parse_default_binds()
    assert [e["group"] for e in out] == ["tiling", "screen-capture", "windows"]
    w = by_keys(out)["SUPER + W"]
    assert w["line"] == 'o.bind("SUPER + W", "Close window", "y")' and w["rebindable"]
    assert binds.group_title("tiling") == "Windows and workspaces"
    assert binds.group_title("screen-capture") == "Screen capture"
    assert binds.group_title("other") == "Other"


# ------------------------------------------------------------------ gaps a mutation pass found


def test_a_table_key_doesnt_excuse_code_after_it(sandbox):
    write_binds(sandbox, utilities='o.bind("SUPER + Z", "Zap", { omarchy = "terminal", run = os.getenv("X") })\n'
                                   'o.bind("SUPER + Y", "Yes", { omarchy = "terminal", direction = "l" })\n')
    out = by_keys(binds.parse_default_binds())
    assert not out["SUPER + Z"]["rebindable"]
    assert out["SUPER + Y"]["rebindable"]


def test_nested_ifs_make_one_guard(sandbox):
    write_binds(sandbox, utilities="""\
        -- if commented_out then
        if o.has_command("voxtype") then
          if o.has_command("wtype") then
            o.bind("F9", "Dictation", "voxtype")
          end
        end
        o.bind("SUPER + D", "Plain", "x")
        """)
    out = by_keys(binds.parse_default_binds())
    assert out["F9"]["guard"] == '(o.has_command("voxtype")) and (o.has_command("wtype"))'
    assert out["F9"]["rebindable"]
    assert out["SUPER + D"]["guard"] is None  # the commented-out `if` opened nothing


def test_an_unreadable_binding_file_doesnt_hide_the_others(sandbox):
    write_binds(sandbox, applications='o.bind("SUPER + A", "A", "a")\n', zzz='o.bind("SUPER + B", "B", "b")\n')
    bad = sandbox.omarchy / "default/hypr/bindings/applications.lua"
    bad.chmod(0)
    try:
        assert [e["keys"] for e in binds.parse_default_binds()] == ["SUPER + B"]
    finally:
        bad.chmod(0o644)


def test_turned_off_keys_missing_from_the_lists_are_listed_but_not_movable(sandbox):
    out = binds.parse_default_binds(disabled_info={"SUPER + W": "Close window"})
    assert out == [{"keys": "SUPER + W", "description": "Close window", "line": None, "guard": None,
                    "rebindable": False, "group": "other"}]


def test_live_binds_give_the_spelling_hyprland_unbinds_by(monkeypatch):
    monkeypatch.setattr(binds, "hypr_json", lambda *a: [
        {"modmask": 64, "key": "", "keycode": 10, "description": "Workspace 1"},
        {"modmask": 65, "key": "Return", "keycode": 0, "description": "Terminal"},
        {"modmask": 0, "key": "F9", "keycode": 0, "description": "Dictation"},
        {"modmask": 64, "key": "mouse:272", "mouse": True, "description": "Move"},
        {"modmask": 64, "key": "Q", "keycode": 0, "description": ""},
        {"modmask": 64, "key": "", "keycode": 0, "description": "Nothing"},
        "not a bind"])
    assert binds.live_bind_spellings() == {"Workspace 1": ["SUPER + code:10"], "Terminal": ["SUPER + SHIFT + Return"],
                                           "Dictation": ["F9"]}


def test_pretty_reads_keycodes_without_a_keymap(monkeypatch):
    monkeypatch.setattr(binds, "keycode_name", lambda code: None)
    assert binds.pretty("SUPER + code:10") == "Super + 1"
    assert binds.pretty("SUPER + code:19") == "Super + 0"
    assert binds.pretty("SUPER + code:20") == "Super + Code:20"
    assert binds.pretty("SUPER + code:9") == "Super + Code:9"


def test_switches_and_odd_spellings():
    assert binds.pretty("switch:on:Lid Switch") == "Lid Switch"
    assert binds.key_count("switch:on:Lid Switch") == 1
    assert binds.key_count("SUPER + J + K") == 2
    assert binds.canonical("SUPER J K") == "SUPER + K"  # one key: the last
    assert binds.canonical("  switch:on:Lid  ") == "switch:on:Lid"
    assert binds.has_modifier("SHIFT + J") and not binds.has_modifier("J")
    assert not binds.bare_ok("SHIFT + J") and binds.bare_ok("SHIFT + F12") and binds.bare_ok("CTRL + J")
