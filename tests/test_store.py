"""Store reset(), settings.json round trip, legacy migration, save, ensure_required()."""

import json

import pytest

from osettings import store as store_mod

from .conftest import luac_error
from .test_render import kitchen_sink


# ------------------------------------------------------------------ reset


VALUES = {"general:gaps_in": 5, "general:gaps_out": 10, "general:col:active_border": "rgba(ffffffff)",
          "decoration:rounding": 8, "decoration:blur:enabled": False, "animations:enabled": False,
          "input:kb_layout": "us"}


@pytest.fixture
def s(make_store):
    st = make_store()
    st.values = dict(VALUES)
    return st


def test_reset_all(s):
    s.reset()
    assert s.values == {}
    assert s._pending  # a save was scheduled, not run


def test_reset_keys(s):
    s.reset(keys=["general:gaps_in", "decoration:rounding", "not:there"])
    assert set(s.values) == set(VALUES) - {"general:gaps_in", "decoration:rounding"}


def test_reset_keys_positional(s):
    s.reset(["animations:enabled"])
    assert "animations:enabled" not in s.values and len(s.values) == len(VALUES) - 1


def test_reset_prefix(s):
    s.reset(prefix="general:")
    assert set(s.values) == {"decoration:rounding", "decoration:blur:enabled", "animations:enabled",
                             "input:kb_layout"}


def test_reset_prefix_is_not_substring(s):
    s.reset(prefix="blur")
    assert s.values == VALUES


def test_reset_keys_and_prefix(s):
    s.reset(keys=["input:kb_layout"], prefix="decoration:")
    assert set(s.values) == {"general:gaps_in", "general:gaps_out", "general:col:active_border",
                             "animations:enabled"}


def test_reset_empty_keys_drops_nothing(s):
    s.reset(keys=[])
    assert s.values == VALUES


def test_reset_leaves_other_state(s):
    s.anim = {"factor": 2.0}
    s.binds["disabled"] = ["SUPER + W"]
    s.reset()
    assert s.anim == {"factor": 2.0} and s.binds["disabled"] == ["SUPER + W"]


def test_set_and_current(s):
    s.set("general:gaps_in", 7)
    assert s.current("general:gaps_in") == 7
    assert s.current("misc:unknown", 42) == 42  # hypr_option is stubbed to None


# ------------------------------------------------------------------ persistence


def test_fresh_store_defaults(make_store):
    st = make_store()
    assert st.values == {} and st.rules == [] and st.autostart == []
    assert st.binds == {"disabled": [], "rebinds": [], "custom": []}


def test_round_trip(make_store):
    data = kitchen_sink()
    st = make_store(data)
    assert st.to_json() == data
    st.save_now()
    saved = json.loads(store_mod.SETTINGS_FILE.read_text())
    assert saved == data
    again = make_store()
    assert again.to_json() == data
    assert again.render_lua() == st.render_lua()


def test_round_trip_fills_missing_bind_lists(make_store):
    st = make_store({"binds": {"disabled": ["SUPER + W"]}})
    assert st.binds == {"disabled": ["SUPER + W"], "rebinds": [], "custom": []}


def test_legacy_hyprland_json_is_migrated(make_store):
    store_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    store_mod.LEGACY_FILE.write_text(json.dumps({"hyprland": {"general:gaps_in": 9},
                                                 "cursor": {"size": 30}}))
    st = make_store()
    assert st.values == {"general:gaps_in": 9} and st.cursor == {"size": 30}
    st.save_now()
    assert json.loads(store_mod.SETTINGS_FILE.read_text())["hyprland"] == {"general:gaps_in": 9}
    # From now on settings.json wins over the legacy file.
    store_mod.LEGACY_FILE.write_text(json.dumps({"hyprland": {"general:gaps_in": 1}}))
    assert make_store().values == {"general:gaps_in": 9}


def test_settings_json_preferred_over_legacy(make_store):
    store_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    store_mod.LEGACY_FILE.write_text(json.dumps({"hyprland": {"a:b": 1}}))
    store_mod.SETTINGS_FILE.write_text(json.dumps({"hyprland": {"a:b": 2}}))
    assert make_store().values == {"a:b": 2}


def test_corrupt_settings_is_set_aside_not_lost(make_store):
    # A damaged settings.json must not be silently overwritten, nor stale legacy data revived.
    store_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    store_mod.SETTINGS_FILE.write_text("{not json")
    store_mod.LEGACY_FILE.write_text(json.dumps({"hyprland": {"a:b": 3}}))
    st = make_store()
    assert st.values == {}
    assert "couldn't be read" in st.load_warning
    broken = list(store_mod.CONFIG_DIR.glob("settings.json.broken-*"))
    assert len(broken) == 1 and broken[0].read_text() == "{not json"
    assert not store_mod.SETTINGS_FILE.exists()


def test_settings_that_are_not_an_object_are_set_aside(make_store):
    store_mod.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    store_mod.SETTINGS_FILE.write_text("[1, 2]")
    st = make_store()
    assert st.values == {} and st.load_warning
    assert list(store_mod.CONFIG_DIR.glob("settings.json.broken-*"))


def test_wrong_types_are_ignored_not_fatal(make_store):
    st = make_store({"hyprland": [], "binds": {"disabled": "x", "custom": None}, "rules": {},
                     "monitors": {"DP-1": {"enabled": True}}})
    assert st.values == {} and st.rules == [] and st.monitors == {"DP-1": {"enabled": True}}
    assert st.binds == {"disabled": [], "rebinds": [], "custom": []}
    assert "hyprland" in st.load_warning
    assert luac_error(st.render_lua()) is None


def test_invalid_lua_saves_nothing_and_releases_waiters(make_store, monkeypatch):
    st = make_store({"hyprland": {"general:gaps_in": 4}})
    st.save_now()
    good_json, good_lua = store_mod.SETTINGS_FILE.read_text(), store_mod.HYPR_LUA.read_text()
    monkeypatch.setattr(store_mod, "lua_syntax_error", lambda text: "boom")
    st.values["general:gaps_in"] = 9
    ran = []
    st.schedule_save(after=lambda: ran.append(1))
    st.save_now()
    assert ran == [1]  # a "Restore all" chain waiting on this save keeps going
    assert store_mod.SETTINGS_FILE.read_text() == good_json
    assert store_mod.HYPR_LUA.read_text() == good_lua
    assert any(r and "invalid" in r for r in st.results)


def test_refresh_rebinds_updates_and_drops():
    st = store_mod.Store(lambda e: None)
    st.binds["rebinds"] = [
        {"old": "SUPER + A", "new": "SUPER + F1", "line": 'o.bind("SUPER + A", "Apps", "old-cmd")',
         "description": "Apps"},
        {"old": "SUPER + B", "new": "SUPER + F2", "line": 'o.bind("SUPER + B", "Gone", "x")',
         "description": "Gone"},
        {"old": "SUPER + C", "new": "SUPER + F3", "line": 'o.bind("SUPER + C", "Same", "y")',
         "description": "Same"},
    ]
    defaults = [
        {"keys": "SUPER + A", "description": "Apps", "line": 'o.bind("SUPER + A", "Apps", "new-cmd")',
         "rebindable": True},
        {"keys": "SUPER + B", "description": "Something else now", "line": 'o.bind("SUPER + B", "S", "z")',
         "rebindable": True},
        {"keys": "SUPER + C", "description": "Same", "line": 'o.bind("SUPER + C", "Same", "y")',
         "rebindable": True},
    ]
    changed, dropped = st.refresh_rebinds(defaults)
    assert changed and dropped == ["Gone"]
    assert [r["old"] for r in st.binds["rebinds"]] == ["SUPER + A", "SUPER + C"]
    assert "new-cmd" in st.binds["rebinds"][0]["line"]
    assert st.refresh_rebinds(defaults) == (False, [])


def test_save_writes_lua_requires_and_reloads(make_store, sandbox):
    store_mod.HYPR_MAIN.write_text('require("hypr.looknfeel")\n')
    st = make_store()
    st.values = {"general:gaps_in": 4}
    st.save_now()
    lua = store_mod.HYPR_LUA.read_text()
    assert lua == st.render_lua() and luac_error(lua) is None
    assert store_mod.REQUIRE_LINE in store_mod.HYPR_MAIN.read_text()
    assert sandbox.run_async == [["hyprctl", "reload"]]  # recorded by the stub, never executed
    assert st.results == []


def test_save_refuses_invalid_lua(make_store, sandbox, monkeypatch):
    monkeypatch.setattr(store_mod, "lua_syntax_error", lambda text: "boom")
    store_mod.HYPR_LUA.write_text("-- previous good file\n")
    st = make_store()
    st.save_now()
    assert store_mod.HYPR_LUA.read_text() == "-- previous good file\n"
    assert st.results == ["Not saved, generated config is invalid: boom"]
    assert sandbox.run_async == []


def test_sync_file_only_writes_when_stale(make_store, sandbox):
    st = make_store()
    st.sync_file()
    assert store_mod.HYPR_LUA.read_text() == st.render_lua()
    assert len(sandbox.run_async) == 1
    st.sync_file()
    assert len(sandbox.run_async) == 1
    store_mod.HYPR_LUA.write_text("-- old version\n")
    st.sync_file()
    assert store_mod.HYPR_LUA.read_text() == st.render_lua()


# ------------------------------------------------------------------ ensure_required


def backups():
    return sorted(store_mod.HYPR_DIR.glob("hyprland.lua.bak.*"))


def test_ensure_required_inserts_after_looknfeel_once():
    original = ('dofile("bootstrap.lua")\nrequire("default.hypr.omarchy")\nrequire("hypr.monitors")\n'
                'require("hypr.looknfeel")\nrequire("hypr.autostart")\n')
    store_mod.HYPR_MAIN.write_text(original)
    store_mod.ensure_required()
    text = store_mod.HYPR_MAIN.read_text()
    lines = text.splitlines()
    assert lines.count(store_mod.REQUIRE_LINE) == 1
    assert lines.index(store_mod.REQUIRE_LINE) == lines.index('require("hypr.looknfeel")') + 1
    assert lines[-1] == 'require("hypr.autostart")'
    assert [b.read_text() for b in backups()] == [original]
    assert luac_error(text) is None

    store_mod.ensure_required()
    store_mod.ensure_required()
    assert store_mod.HYPR_MAIN.read_text() == text
    assert len(backups()) == 1


def test_ensure_required_only_first_looknfeel():
    store_mod.HYPR_MAIN.write_text('require("hypr.looknfeel")\n-- require("hypr.looknfeel")\n')
    store_mod.ensure_required()
    assert store_mod.HYPR_MAIN.read_text().count(store_mod.REQUIRE_LINE) == 1


def test_ensure_required_appends_without_anchor():
    store_mod.HYPR_MAIN.write_text('require("default.hypr.omarchy")')
    store_mod.ensure_required()
    assert store_mod.HYPR_MAIN.read_text() == f'require("default.hypr.omarchy")\n{store_mod.REQUIRE_LINE}\n'
    assert len(backups()) == 1


def test_ensure_required_leaves_existing_line_alone():
    text = f'require("hypr.looknfeel")\n{store_mod.REQUIRE_LINE}\n'
    store_mod.HYPR_MAIN.write_text(text)
    store_mod.ensure_required()
    assert store_mod.HYPR_MAIN.read_text() == text
    assert backups() == []


def test_ensure_required_without_main_file():
    store_mod.ensure_required()
    assert not store_mod.HYPR_MAIN.exists()
    assert backups() == []


def test_ensure_required_respects_commented_out_require():
    # Commenting the line out is how a user switches the app's Hyprland changes off: never re-add it.
    text = f'require("hypr.looknfeel")\n-- {store_mod.REQUIRE_LINE}\n'
    store_mod.HYPR_MAIN.write_text(text)
    assert store_mod.ensure_required() == "disabled"
    assert store_mod.HYPR_MAIN.read_text() == text
    assert backups() == []


def test_ensure_required_reports_loaded():
    store_mod.HYPR_MAIN.write_text(f'  {store_mod.REQUIRE_LINE}\n')
    assert store_mod.ensure_required() == "loaded"
    store_mod.HYPR_MAIN.write_text('require("hypr.looknfeel")\n')
    assert store_mod.ensure_required() == "loaded"


def test_ensure_required_skips_commented_out_anchor():
    store_mod.HYPR_MAIN.write_text('-- require("hypr.looknfeel")\nrequire("hypr.looknfeel")\nrequire("hypr.autostart")\n')
    store_mod.ensure_required()
    lines = store_mod.HYPR_MAIN.read_text().splitlines()
    assert lines == ['-- require("hypr.looknfeel")', 'require("hypr.looknfeel")', store_mod.REQUIRE_LINE,
                     'require("hypr.autostart")']


def test_save_warns_once_when_require_is_commented_out(make_store, monkeypatch):
    results = []
    st = make_store()
    monkeypatch.setattr(st, "on_result", results.append)
    store_mod.HYPR_MAIN.write_text(f'-- {store_mod.REQUIRE_LINE}\n')
    st.save_now()
    st.save_now()
    warnings = [r for r in results if r and "commented out" in r]
    assert len(warnings) == 1
    assert store_mod.HYPR_MAIN.read_text() == f'-- {store_mod.REQUIRE_LINE}\n'
