"""Keybinding fixes from the xhigh review: keycode keys, shared keys, "Other" rows,
recorder input, the recording pause, and turned-off keys after Omarchy updates."""

import textwrap

import pytest

from osettings import binds, pages_keys as pk, store as store_mod

from .conftest import luac_error
from .test_review_fixes import FakeWin


def write(sandbox, **files):
    d = sandbox.omarchy / "default/hypr/bindings"
    d.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (d / f"{name}.lua").write_text(textwrap.dedent(text))


PRINTED = "\n".join([
    "SUPER + 1                           → Switch to workspace 1",
    "SUPER SHIFT + 1                     → Move window to workspace 1",
    "SUPER CTRL ALT + J                  → From bindings.lua",
    "SUPER ALT + N                       → My custom one",
])
LIVE = [
    {"description": "Switch to workspace 1", "modmask": 64, "key": "", "keycode": 10},
    {"description": "Move window to workspace 1", "modmask": 65, "key": "", "keycode": 10},
    {"description": "From bindings.lua", "modmask": 76, "key": "J", "keycode": 0},
    {"description": "Move window", "modmask": 64, "key": "mouse:272", "keycode": 0, "mouse": True},
]


@pytest.fixture
def printed(sandbox, monkeypatch):
    sandbox.run_output[("omarchy", "menu", "keybindings", "--print")] = PRINTED
    monkeypatch.setattr(binds, "hypr_json", lambda *a: LIVE)


# ------------------------------------------------------------------ keys and spellings


def test_keycode_keys_clash_with_the_key_they_produce():
    assert binds.normalize("SUPER + code:10") == binds.normalize("SUPER + 1")
    assert binds.normalize("SUPER + code:20") == binds.normalize("SUPER + minus")
    assert binds.normalize("SUPER + code:10") != binds.normalize("SUPER + 2")


def test_switch_keys_are_whole():
    a, b = "switch:on:Lid Switch", "switch:off:Lid Switch"
    assert binds.normalize(a) != binds.normalize(b)


def test_canonical_spelling():
    assert binds.canonical("SUPER CTRL ALT + J") == "SUPER + CTRL + ALT + J"
    assert binds.canonical("SUPER + SHIFT + code:10") == "SUPER + SHIFT + code:10"


def test_other_rows_get_the_spelling_hyprland_uses(sandbox, printed):
    write(sandbox, tiling='o.bind("SUPER + W", "Close window", "x")\n')
    out = {b["description"]: b for b in binds.parse_default_binds(owned={binds.normalize("SUPER + ALT + N")})}
    assert out["Switch to workspace 1"]["keys"] == "SUPER + code:10"
    assert out["Move window to workspace 1"]["keys"] == "SUPER + SHIFT + code:10"
    assert out["From bindings.lua"]["keys"] == "SUPER + CTRL + ALT + J"
    assert "My custom one" not in out  # the app's own shortcut isn't listed as Omarchy's


def test_turned_off_other_rows_stay_listed(sandbox, printed):
    sandbox.run_output[("omarchy", "menu", "keybindings", "--print")] = ""  # unbound, so not printed
    out = binds.parse_default_binds(disabled_info={"SUPER + code:10": "Switch to workspace 1"})
    assert [(b["keys"], b["group"]) for b in out] == [("SUPER + code:10", "other")]


def test_switch_and_mouse_binds_are_not_rebindable(sandbox):
    write(sandbox, utilities='''\
        o.bind("switch:on:Lid Switch", "Lid closed", "omarchy-lid close")
        o.bind("SUPER + mouse:272", "Move window", hl.dsp.window.drag(), { mouse = true })
    ''')
    assert not any(b["rebindable"] for b in binds.parse_default_binds())


def test_lines_in_if_blocks_keep_their_condition(sandbox):
    write(sandbox, voxtype='''\
        if o.cmd_present("voxtype") then
          o.bind("F9", "Start dictation", "voxtype record start")
          o.bind("F9", "Stop dictation", "voxtype record stop", { release = true })
        end
        if weird_local then
          o.bind("F8", "Odd", "x")
        end
    ''')
    out = {b["description"]: b for b in binds.parse_default_binds()}
    assert out["Start dictation"]["guard"] == '(o.cmd_present("voxtype"))'
    assert out["Start dictation"]["rebindable"] is True
    assert out["Odd"]["rebindable"] is False  # unknown names in the condition: never lifted out


# ------------------------------------------------------------------ shared keys


SHARED = '''\
    if o.cmd_present("voxtype") then
      o.bind("F9", "Start dictation", "voxtype record start")
      o.bind("F9", "Stop dictation", "voxtype record stop", { release = true })
    end
    o.bind("SUPER + W", "Close window", "x")
'''


def keys_page(sandbox, make_store):
    write(sandbox, voxtype=SHARED)
    page = pk.KeysPage.__new__(pk.KeysPage)
    page.win = FakeWin(make_store())
    page.defaults = binds.parse_default_binds()
    page.saved = lambda msg: page.win.toasts.append(msg)
    return page


def test_shared_key_moves_together_and_keeps_its_condition(sandbox, make_store, monkeypatch):
    page = keys_page(sandbox, make_store)
    start = next(b for b in page.defaults if b["description"] == "Start dictation")
    dialogs = []
    monkeypatch.setattr(pk, "ShortcutDialog", lambda page_, title, done, **kw: dialogs.append((done, kw)) or
                        type("D", (), {"present": lambda self, w: None})())
    pk.KeysPage.change_default(page, start)
    done, kw = dialogs[-1]
    assert len(kw["ignore"]) == 2
    done({"keys": "F10"})
    rebinds = page.win.store.binds["rebinds"]
    assert sorted(r["description"] for r in rebinds) == ["Start dictation", "Stop dictation"]
    lua = page.win.store.render_lua()
    assert luac_error(lua) is None
    section = lua.split('section("shortcut F10"', 1)[1].split("end)\n", 1)[0]
    assert section.count('hl.unbind("F10")') == 1 and section.count('hl.unbind("F9")') == 1
    assert 'if (o.cmd_present("voxtype")) then o.bind("F10", "Start dictation"' in section
    assert 'o.bind("F10", "Stop dictation", "voxtype record stop", { release = true })' in section


def test_turning_off_a_shared_key_records_both(sandbox, make_store):
    page = keys_page(sandbox, make_store)
    stop = next(b for b in page.defaults if b["description"] == "Stop dictation")
    pk.KeysPage.set_disabled(page, stop, True)
    binds_ = page.win.store.binds
    assert binds_["disabled"] == ["F9"]
    assert binds_["disabled_info"]["F9"] == "Start dictation / Stop dictation"
    pk.KeysPage.set_disabled(page, stop, False)
    assert binds_["disabled"] == [] and binds_["disabled_info"] == {}


def test_turned_off_key_reused_by_omarchy_is_dropped(make_store):
    st = make_store()
    st.binds["disabled"] = ["SUPER + W", "F9"]
    st.binds["disabled_info"] = {"SUPER + W": "Close window", "F9": "Start dictation / Stop dictation"}
    defaults = [
        {"keys": "SUPER + W", "description": "Something new", "line": "x", "rebindable": True},
        {"keys": "F9", "description": "Start dictation", "line": "x", "rebindable": True},
        {"keys": "F9", "description": "Stop dictation", "line": "y", "rebindable": True},
    ]
    changed, dropped = st.refresh_rebinds(defaults)
    assert changed and dropped == ["Close window (off)"]
    assert st.binds["disabled"] == ["F9"]


# ------------------------------------------------------------------ recorder


class Label:
    def __init__(self):
        self.text = ""

    def set_label(self, t):
        self.text = t


class Button:
    sensitive = None

    def set_sensitive(self, v):
        self.sensitive = v


def recorder(page):
    d = pk.ShortcutDialog.__new__(pk.ShortcutDialog)
    d.page, d.ignore, d.keys = page, None, ""
    d.conflict, d.shown, d.save = Label(), Label(), Button()
    return d


@pytest.mark.parametrize("keys, ok", [
    ("Left", False), ("Home", False), ("SHIFT + A", False), ("space", False),
    ("F5", True), ("XF86AudioPlay", True), ("Print", True), ("SUPER + Left", True), ("CTRL + ALT + T", True),
])
def test_recorder_refuses_bare_keys(sandbox, make_store, keys, ok):
    page = keys_page(sandbox, make_store)
    d = recorder(page)
    pk.ShortcutDialog.set_keys(d, keys)
    assert (d.keys == keys) is ok
    if not ok:
        assert "Hold Super, Ctrl or Alt" in d.conflict.text


def test_recorder_adopts_keycode_spelling(sandbox, make_store):
    page = keys_page(sandbox, make_store)
    page.defaults.append({"keys": "SUPER + code:10", "description": "Switch to workspace 1", "line": None,
                          "guard": None, "rebindable": False, "group": "other"})
    d = recorder(page)
    pk.ShortcutDialog.set_keys(d, "SUPER + 1")
    assert d.keys == "SUPER + code:10" and "workspace 1" in d.conflict.text


def test_require_state(sandbox):
    assert store_mod.require_state() == "missing"
    store_mod.HYPR_MAIN.write_text(f"-- {store_mod.REQUIRE_LINE}\n")
    assert store_mod.require_state() == "disabled"
    store_mod.HYPR_MAIN.write_text(f"{store_mod.REQUIRE_LINE}\n")
    assert store_mod.require_state() == "missing"  # required but never generated
    store_mod.HYPR_LUA.write_text("-- generated\n")
    assert store_mod.require_state() == "loaded"


@pytest.mark.parametrize("typed", ["SUPER", "CTRL + ", "SUPER + SHIFT", "SUPER + A B", "+"])
def test_recorder_refuses_a_shortcut_without_exactly_one_key(sandbox, make_store, typed):
    """Typed text with no key (or two) was saved as a binding Hyprland rejects at every reload."""
    page = keys_page(sandbox, make_store)
    d = recorder(page)
    pk.ShortcutDialog.set_keys(d, pk.typed_keys(typed))
    assert d.keys == "" and "one key" in d.conflict.text


@pytest.mark.parametrize("typed, keys", [
    ("super shift r", "SUPER + SHIFT + R"), ("SUPER+code:10", "SUPER + code:10"),
    ("ctrl + alt + Delete", "CTRL + ALT + Delete"), ("SUPER + Return", "SUPER + Return"),
])
def test_typed_shortcuts_are_spelled_like_recorded_ones(sandbox, make_store, typed, keys):
    page = keys_page(sandbox, make_store)
    d = recorder(page)
    pk.ShortcutDialog.set_keys(d, pk.typed_keys(typed))
    assert d.keys == keys


class Entry:
    def __init__(self, text=""):
        self.text = text

    def get_text(self):
        return self.text


def finishing(page, typed, keys="", start=""):
    d = recorder(page)
    d.keys, d.custom, d._timeout = keys, None, None
    d.typed, d._typed_seen = Entry(typed), start
    d.done, d.closed = [], False
    d.on_done = d.done.append
    d.close = lambda: setattr(d, "closed", True)
    return d


def test_save_uses_text_typed_after_a_recorded_key(sandbox, make_store):
    """Typing a combination (without pressing its apply button) after a key had been recorded used
    to be ignored: Save kept the recorded key."""
    d = finishing(keys_page(sandbox, make_store), typed="SUPER + Y", keys="SUPER + T")
    pk.ShortcutDialog.finish(d)
    assert d.done == [{"keys": "SUPER + Y"}] and d.closed


def test_save_keeps_the_recorded_key_when_the_text_is_unchanged(sandbox, make_store):
    d = finishing(keys_page(sandbox, make_store), typed="SUPER + T", keys="SUPER + G", start="SUPER + T")
    pk.ShortcutDialog.finish(d)
    assert d.done == [{"keys": "SUPER + G"}]


def test_save_stays_open_when_the_typed_text_is_refused(sandbox, make_store):
    d = finishing(keys_page(sandbox, make_store), typed="SUPER", keys="SUPER + T")
    pk.ShortcutDialog.finish(d)
    assert d.done == [] and not d.closed and "one key" in d.conflict.text


def test_turning_on_a_shortcut_redraws_the_shortcut_it_turned_off(sandbox, make_store):
    """take_over turns off whatever else is on the key; without a redraw the page still showed that
    shortcut as on."""
    page = keys_page(sandbox, make_store)
    page.rebuilt = []
    page.rebuild = lambda delay=0: page.rebuilt.append(1)
    c = {"keys": "F9", "command": "foot", "description": "Terminal", "launch": True, "enabled": False}
    page.win.store.binds["custom"].append(c)
    pk.KeysPage.toggle_custom(page, c, True)
    assert c["enabled"] and "F9" in page.win.store.binds["disabled"]
    assert page.rebuilt == [1]
    pk.KeysPage.toggle_custom(page, c, False)  # nothing else changes: no redraw needed
    assert page.rebuilt == [1]
