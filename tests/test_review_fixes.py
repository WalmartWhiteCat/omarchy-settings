"""Fixes from the UI and robustness review: displays, layouts, bar widgets, toggles."""

import json

import pytest

from osettings import pages_system as ps
from osettings import store as store_mod

from .conftest import REAL_POPEN


class FakeWin:
    def __init__(self, store=None):
        self.toasts = []
        self.store = store

    def toast(self, msg):
        self.toasts.append(msg)

    busy = toast


class FakeButton:
    def __init__(self):
        self.sensitive = None

    def set_sensitive(self, v):
        self.sensitive = v


class FakeDialog:
    def __init__(self, on_yes, on_no):
        self.on_yes, self.on_no, self.closed = on_yes, on_no, False

    def force_close(self):
        self.closed = True

    def set_body(self, _):
        pass


# ------------------------------------------------------------------ keyboard layouts


@pytest.mark.parametrize("layouts, variants, expected", [
    ("us", "", ("us", "", False)),
    ("de,ru", "", ("de,ru", "", False)),
    ("ru", "", ("us,ru", "", True)),
    ("ru,de", "phonetic,nodeadkeys", ("de,ru", "nodeadkeys,phonetic", True)),
    ("ua,ru", "", ("us,ua,ru", "", True)),
    ("gr", "polytonic", ("us,gr", ",polytonic", True)),
])
def test_latin_layout_goes_first(layouts, variants, expected):
    assert ps.latin_first(layouts, variants) == expected


def test_non_latin_list_is_read_from_omarchy(sandbox):
    f = sandbox.omarchy / "default/hypr/input.lua"
    f.parent.mkdir(parents=True)
    f.write_text('local non_latin_layouts =\n  " ru xx "\n')
    assert ps.non_latin_layouts() == {"ru", "xx"}


# ------------------------------------------------------------------ displays


MON = {"name": "DP-1", "description": "Test", "width": 2560, "height": 1440, "refreshRate": 143.99,
       "x": 0, "y": 0, "scale": 1.0, "transform": 0, "disabled": False,
       "availableModes": ["2560x1440@143.99Hz", "1920x1080@60.00Hz", "2560x1440@59.95Hz"]}


def test_monitor_modes_best_first():
    assert ps.monitor_modes(MON) == ["2560x1440@143.99", "2560x1440@59.95", "1920x1080@60.00"]


def test_screen_that_is_off_uses_a_real_mode():
    page = ps.DisplaysPage.__new__(ps.DisplaysPage)
    page.draft = {"DP-1": None}
    off = dict(MON, width=0, height=0, refreshRate=0.0, disabled=True)
    e = ps.DisplaysPage.entry(page, off)
    assert e["mode"] == "2560x1440@143.99" and e["enabled"] is False
    no_modes = dict(off, availableModes=[])
    assert ps.DisplaysPage.entry(page, no_modes)["mode"] == "preferred"
    assert ps.mode_size("preferred") == (0, 0)


def make_display_page(store, monkeypatch, live=(MON,)):
    page = ps.DisplaysPage.__new__(ps.DisplaysPage)
    page.win = FakeWin(store)
    page.live = list(live)
    page.apply_btn = FakeButton()
    page.draft = {m["name"]: None for m in live}
    page.rows = {}
    for m in live:
        page.rows[m["name"]] = {"entry": ps.DisplaysPage.entry(page, m)}
    page.rebuilt = []
    monkeypatch.setattr(page, "rebuild", lambda delay=0: page.rebuilt.append(delay), raising=False)
    dialogs = []

    def fake_confirm(win, heading, body, on_yes, label="", destructive=True, on_no=None):
        d = FakeDialog(on_yes, on_no)
        dialogs.append(d)
        return d

    monkeypatch.setattr(ps, "confirm", fake_confirm)
    monkeypatch.setattr(ps.GLib, "timeout_add", lambda *a: 0)
    return page, dialogs


def test_apply_is_a_live_trial_until_kept(make_store, sandbox, monkeypatch):
    st = make_store()
    page, dialogs = make_display_page(st, monkeypatch)
    page.draft["DP-1"] = dict(page.rows["DP-1"]["entry"], scale=1.25)
    ps.DisplaysPage.apply(page)

    (marker,) = store_mod.CONFIG_DIR.glob(ps.TRIAL_MARKER_NAME + "-*")
    watchdog = sandbox.spawn[-1]
    assert watchdog[:3] == ["sh", "-c", ps.WATCHDOG] and watchdog[4] == str(marker)
    evals = [c for c in sandbox.run_async if c[:2] == ["hyprctl", "eval"]]
    assert evals and "scale = 1.25" in evals[-1][2]
    assert st.monitors == {} and not store_mod.HYPR_LUA.exists()  # nothing saved yet

    dialogs[-1].on_yes()  # Keep changes
    assert not marker.exists()
    assert st.monitors["DP-1"]["scale"] == 1.25
    assert "scale = 1.25" in store_mod.HYPR_LUA.read_text()


def test_revert_reloads_and_saves_nothing(make_store, sandbox, monkeypatch):
    st = make_store()
    page, dialogs = make_display_page(st, monkeypatch)
    page.draft["DP-1"] = dict(page.rows["DP-1"]["entry"], scale=2)
    ps.DisplaysPage.apply(page)
    dialogs[-1].on_no()
    assert ["hyprctl", "reload"] in sandbox.run_async
    assert st.monitors == {} and not store_mod.HYPR_LUA.exists()
    assert not list(store_mod.CONFIG_DIR.glob(ps.TRIAL_MARKER_NAME + "*"))
    dialogs[-1].on_yes()  # a late "keep" after reverting must not save
    assert st.monitors == {}


def test_watchdog_script_only_reloads_while_marker_exists(tmp_path):
    marker = tmp_path / "trial"
    log = tmp_path / "log"
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "hyprctl").write_text(f"#!/bin/sh\necho \"$@\" >> {log}\n")
    (fake / "hyprctl").chmod(0o755)
    env = {"PATH": f"{fake}:/usr/bin:/bin"}  # a fake hyprctl shadows the real one

    def watchdog():
        # The harness blocks real commands; this one only reaches the fake hyprctl above.
        assert REAL_POPEN(["sh", "-c", ps.WATCHDOG, "sh", str(marker), "0"], env=env).wait() == 0

    marker.write_text("x")
    watchdog()
    assert log.read_text().strip() == "reload" and not marker.exists()
    watchdog()
    assert log.read_text().strip() == "reload"  # no marker: no second reload


def test_scale_fix_after_resolution_change_lands_in_draft(monkeypatch):
    page = ps.DisplaysPage.__new__(ps.DisplaysPage)
    page.draft = {"DP-1": None}
    e = ps.DisplaysPage.entry(page, MON)
    e["scale"] = 2.4  # valid for 1920x1080, not for 2560x1440

    class Row:
        values = None

        def set_model(self, m):
            self.n = m.get_n_items()

        def set_selected(self, i):
            self.i = i

        def get_selected(self):
            return self.i

    page.rows = {"DP-1": {"entry": e, "scale": Row()}}
    page.draft["DP-1"] = e  # what change() does on the first edit
    e["mode"] = "2560x1440@143.99"
    ps.DisplaysPage.refresh_scales(page, "DP-1")
    assert page.draft["DP-1"]["scale"] in ps.valid_scales(2560, 1440)


# ------------------------------------------------------------------ bar widgets


def test_removing_a_multi_purpose_widget_only_takes_it_off_the_bar(sandbox):
    ps.SHELL_JSON.parent.mkdir(parents=True, exist_ok=True)
    ps.SHELL_JSON.write_text(json.dumps({"bar": {"layout": {
        "left": [{"id": "omarchy.menu"}, {"id": "omarchy.workspaces"}], "center": ["omarchy.menu"], "right": []}}}))
    page = ps.BarPage.__new__(ps.BarPage)
    page.win = FakeWin()
    page.catalog = {"omarchy.menu": {"kinds": ["menu", "bar-widget"]},
                    "omarchy.clock": {"kinds": ["bar-widget"]}}
    page.populate_widgets = lambda: None
    ps.BarPage.remove(page, "omarchy.menu")
    layout = json.loads(ps.SHELL_JSON.read_text())["bar"]["layout"]
    assert layout == {"left": [{"id": "omarchy.workspaces"}], "center": [], "right": []}
    assert not any("disable" in c for c in sandbox.all_cmds())

    ps.BarPage.remove(page, "omarchy.clock")  # a plain widget still goes through Omarchy
    assert ["omarchy", "plugin", "disable", "omarchy.clock"] in sandbox.run_chain[-1]


# ------------------------------------------------------------------ switches set, not flip


def test_flag_switch_only_toggles_when_state_differs(sandbox, monkeypatch):
    page = ps.PowerPage.__new__(ps.PowerPage)
    captured = {}
    monkeypatch.setattr(ps, "switch_row", lambda t, s, active, cb: captured.setdefault("cb", cb))
    flag_off = {"v": False}
    monkeypatch.setattr(ps, "run_ok", lambda cmd: flag_off["v"])
    ps.PowerPage.flag_row(page, "Screensaver", None, "screensaver-off", ["omarchy", "toggle", "screensaver"])
    captured["cb"](True)  # already on (flag not set): nothing to do
    assert sandbox.run_async == []
    captured["cb"](False)
    assert sandbox.run_async == [["omarchy", "toggle", "screensaver"]]


# ------------------------------------------------------------------ keybinding conflicts


from osettings import pages_keys as pk  # noqa: E402
from osettings import pages_look as pl  # noqa: E402

CLOSE = {"keys": "SUPER + W", "description": "Close window", "line": 'o.bind("SUPER + W", "Close window", "x")',
         "rebindable": True, "group": "tiling"}
TERM = {"keys": "SUPER + RETURN", "description": "Terminal", "line": 'o.bind("SUPER + RETURN", "Terminal", "t")',
        "rebindable": True, "group": "applications"}


def keys_page(make_store):
    page = pk.KeysPage.__new__(pk.KeysPage)
    page.win = FakeWin(make_store())
    page.defaults = [dict(CLOSE), dict(TERM)]
    page.saved = lambda msg: page.win.toasts.append(msg)
    return page


def test_moving_a_default_onto_anothers_key_turns_that_one_off(make_store):
    page = keys_page(make_store)
    close, term = page.defaults
    clash = pk.KeysPage.take_over(page, "SUPER + W", ignore=term)
    page.win.store.binds["rebinds"].append({"old": term["keys"], "new": "SUPER + W", "line": term["line"],
                                            "description": "Terminal"})
    assert clash["ref"] is close
    assert page.win.store.binds["disabled"] == ["SUPER + W"]
    # The page now says who really owns the key.
    assert pk.KeysPage.who_uses(page, "SUPER + W")["ref"] is term
    assert any("turned off" in t for t in page.win.toasts)


def test_custom_shortcut_on_a_default_key_turns_the_default_off(make_store):
    page = keys_page(make_store)
    pk.KeysPage.take_over(page, "SUPER + RETURN")
    assert "SUPER + RETURN" in page.win.store.binds["disabled"]


def test_turning_on_or_restoring_refuses_a_taken_key(make_store):
    page = keys_page(make_store)
    close, term = page.defaults
    binds = page.win.store.binds
    binds["disabled"].append("SUPER + W")
    binds["custom"].append({"keys": "SUPER + W", "command": "foo", "description": "Mine", "enabled": True})
    pk.KeysPage.set_disabled(page, close, False)
    assert binds["disabled"] == ["SUPER + W"]  # still off
    assert any("Mine" in t for t in page.win.toasts)

    binds["custom"][0]["enabled"] = False
    pk.KeysPage.set_disabled(page, close, False)
    assert binds["disabled"] == []

    binds["rebinds"].append({"old": "SUPER + RETURN", "new": "SUPER + F1", "line": TERM["line"],
                             "description": "Terminal"})
    binds["custom"].append({"keys": "SUPER + RETURN", "command": "bar", "description": "Other", "enabled": True})
    pk.KeysPage.restore_default(page, term)
    assert len(binds["rebinds"]) == 1  # refused: the original key is taken


def test_unique_path(tmp_path):
    a = tmp_path / "wall.png"
    assert pl.unique_path(a) == a
    a.write_text("1")
    assert pl.unique_path(a) == tmp_path / "wall-2.png"
    (tmp_path / "wall-2.png").write_text("2")
    assert pl.unique_path(a) == tmp_path / "wall-3.png"


# ------------------------------------------------------------------ built-in laptop panels


def test_docked_laptop_panel_is_never_saved_off(make_store, sandbox, monkeypatch):
    panel = dict(MON, name="eDP-1", disabled=True, width=0, height=0, refreshRate=0.0)
    st = make_store()
    page, dialogs = make_display_page(st, monkeypatch, live=(panel, dict(MON, name="DP-2")))
    e = page.rows["eDP-1"]["entry"]
    assert e["enabled"] is True
    page.draft["eDP-1"] = dict(e, scale=1.25)
    ps.DisplaysPage.apply(page)
    dialogs[-1].on_yes()
    lua = store_mod.HYPR_LUA.read_text()
    assert "disabled = true" not in lua and 'output = "eDP-1"' in lua


def test_generator_never_writes_a_panel_off():
    assert "disabled" not in store_mod.Store.monitor_lua("eDP-1", {"enabled": False, "mode": "1920x1080@60.00"})
    assert "disabled = true" in store_mod.Store.monitor_lua("DP-1", {"enabled": False})


# ------------------------------------------------------------------ bar and idle


def test_bar_reset_shows_the_bar(sandbox):
    page = ps.BarPage.__new__(ps.BarPage)
    page.win = FakeWin()
    ps.BarPage.reset(page)
    cmds = sandbox.run_chain[-1]
    assert ["omarchy", "toggle", "bar", "off"] in cmds  # removes the bar-off flag
    assert ["omarchy", "toggle", "bar", "on"] not in cmds


def test_keep_awake_reads_omarchy_status_the_right_way_round(sandbox, monkeypatch):
    rows = {}
    monkeypatch.setattr(ps, "switch_row", lambda t, s, active, cb: rows.setdefault(t, active))
    monkeypatch.setattr(ps, "spin_row", lambda *a, **k: None)
    monkeypatch.setattr(ps.PowerPage, "flag_row", lambda *a: None)
    monkeypatch.setattr(ps.Adw, "PreferencesGroup", lambda **k: type("G", (), {"add": lambda s, r: None})())
    page = ps.PowerPage.__new__(ps.PowerPage)
    page.win, page.add = FakeWin(), lambda g: None
    monkeypatch.setattr(ps, "reset_group", lambda *a, **k: None)
    for status, expected in (('{"enabled":true,"class":"enabled"}', True), ('{"enabled":false}', False)):
        rows.clear()
        sandbox.run_output[("omarchy", "toggle", "idle", "status")] = status
        ps.PowerPage.build(page)
        assert rows["Keep awake"] is expected


def test_idle_times_never_saved_as_zero(sandbox):
    ps.SHELL_JSON.parent.mkdir(parents=True, exist_ok=True)
    ps.SHELL_JSON.write_text('{"idle": {"lock": 300}}')
    page = ps.PowerPage.__new__(ps.PowerPage)
    page.win = FakeWin()
    ps.PowerPage.set_idle(page, "lock", 0)
    assert json.loads(ps.SHELL_JSON.read_text())["idle"]["lock"] == 30


def test_idle_change_without_shell_json_says_so(sandbox):
    page = ps.PowerPage.__new__(ps.PowerPage)
    page.win = FakeWin()
    ps.PowerPage.set_idle(page, "lock", 600)
    assert not ps.SHELL_JSON.exists() and "wasn't saved" in page.win.toasts[-1]


# ------------------------------------------------------------------ night light


def night_page(make_store, monkeypatch, running=True):
    page = ps.NightLightPage.__new__(ps.NightLightPage)
    page.win = FakeWin(make_store())
    monkeypatch.setattr(ps, "run_ok", lambda cmd: running if cmd[0] == "pgrep" else False)
    return page


def test_night_light_on_sets_the_warmth_directly(sandbox, make_store, monkeypatch):
    page = night_page(make_store, monkeypatch)
    page.win.store.nightlight["temperature"] = 3500
    ps.NightLightPage.toggle(page, True)
    cmds = sandbox.run_chain[-1]
    assert cmds[0] == ["hyprctl", "hyprsunset", "temperature", "3500"]
    assert ["omarchy", "toggle", "nightlight"] not in cmds  # it would go to 6500 K from neutral


def test_night_light_off_and_not_running(sandbox, make_store, monkeypatch):
    page = night_page(make_store, monkeypatch)
    ps.NightLightPage.toggle(page, False)
    assert sandbox.run_chain[-1][0] == ["hyprctl", "hyprsunset", "temperature", "6500"]
    page = night_page(make_store, monkeypatch, running=False)
    sandbox.run_chain.clear()
    ps.NightLightPage.toggle(page, False)
    assert sandbox.run_chain == []
    ps.NightLightPage.toggle(page, True)
    assert sandbox.run_chain[-1][0] == ["omarchy", "toggle", "nightlight"]  # starts hyprsunset
    assert sandbox.run_chain[-1][1] == ["hyprctl", "hyprsunset", "temperature", "4000"]


def test_night_light_schedule_warms_at_start_and_clears_at_end(sandbox, make_store, monkeypatch):
    # "Turn on at" must be the warm profile and "Turn off at" the neutral one in hyprsunset.conf.
    page = night_page(make_store, monkeypatch)
    page.win.store.nightlight.update(schedule=True, start="20:00", end="07:00", temperature=3800)
    ps.NightLightPage.write_schedule(page)
    profiles = ps.HYPRSUNSET_CONF.read_text().split("profile {")[1:]
    by_time = {p.split("time = ")[1].split()[0]: p for p in profiles}
    assert "temperature = 3800" in by_time["20:00"]
    assert "identity = true" in by_time["07:00"]

def test_each_trial_has_its_own_marker(make_store, sandbox, monkeypatch):
    st = make_store()
    page, dialogs = make_display_page(st, monkeypatch)
    page.draft["DP-1"] = dict(page.rows["DP-1"]["entry"], scale=1.25)
    ps.DisplaysPage.apply(page)
    first = sandbox.spawn[-1][4]
    dialogs[-1].on_yes()
    page.draft["DP-1"] = dict(page.rows["DP-1"]["entry"], scale=2)
    ps.DisplaysPage.apply(page)
    second = sandbox.spawn[-1][4]
    assert first != second
    # the first trial's watchdog looks for its own marker, which Keep already removed
    assert not ps.Path(first).exists() and ps.Path(second).exists()


def test_monitors_lua_extras(sandbox):
    ps.MONITORS_LUA.write_text('''
hl.monitor({ output = "DP-1", mode = "2560x1440@144", position = "0x0", scale = 1, bitdepth = 10,
             reserved_area = { top = 10, bottom = 0 }, cm = "hdr" })
-- hl.monitor({ output = "DP-1", vrr = 1 })
hl.monitor({ output = "DP-2", mode = "preferred", position = "auto", scale = 1 })
''')
    assert ps.monitors_lua_extras("DP-1") == ["bitdepth", "cm", "reserved_area"]
    assert ps.monitors_lua_extras("DP-2") == []
    assert ps.monitors_lua_extras("HDMI-A-1") == []


def test_touchpad_state_comes_from_omarchy_flag(sandbox):
    assert ps.touchpad_disabled() is False
    f = ps.STATE / "toggles/hypr/touchpad-disabled-name"
    f.parent.mkdir(parents=True)
    f.write_text("some-touchpad\n")
    assert ps.touchpad_disabled() is True


# ------------------------------------------------------------------ removing backgrounds


def bg_page(sandbox, monkeypatch):
    state = pl.STATE
    (state / "current/theme/backgrounds").mkdir(parents=True)
    (state / "current/theme.name").write_text("tokyo-night\n")
    stock = state / "current/theme/backgrounds/1-stock.png"
    stock.write_bytes(b"png")
    mine = pl.HOME / ".config/omarchy/backgrounds/tokyo-night"
    mine.mkdir(parents=True)
    for n in ("a.png", "b.png"):
        (mine / n).write_bytes(b"png")
    page = pl.BackgroundPage.__new__(pl.BackgroundPage)
    page.win = FakeWin()
    page.populate = lambda: None
    return page, mine, stock


def test_remove_moves_a_user_background_to_the_trash(sandbox, monkeypatch):
    page, mine, stock = bg_page(sandbox, monkeypatch)
    pl.BackgroundPage.remove(page, mine / "a.png")
    assert sandbox.trash == [str(mine / "a.png")]
    assert not (mine / "a.png").exists() and stock.exists()
    assert not any(c[:4] == ["omarchy", "theme", "bg", "set"] for c in sandbox.run_async)


def test_removing_the_current_background_switches_to_another(sandbox, monkeypatch):
    page, mine, stock = bg_page(sandbox, monkeypatch)
    (pl.STATE / "current/background").symlink_to(mine / "a.png")
    pl.BackgroundPage.remove(page, mine / "a.png")
    assert ["omarchy", "theme", "bg", "set", str(mine / "b.png")] in sandbox.run_async
    assert "switched to b.png" in page.win.toasts[-1]


def test_trash_failure_keeps_the_file(sandbox, monkeypatch):
    page, mine, stock = bg_page(sandbox, monkeypatch)
    monkeypatch.setattr(pl, "trash_file", lambda p: "no Trash on this filesystem")
    pl.BackgroundPage.remove(page, mine / "a.png")
    assert (mine / "a.png").exists()
    assert "Couldn't move" in page.win.toasts[-1]


LID_SHUT = dict(MON, name="eDP-1", width=2880, height=1800, refreshRate=120.0, x=0, y=0, disabled=True,
                availableModes=["2880x1800@120.00Hz"])
EXTERNAL = dict(MON, name="DP-1", x=0)


def test_a_shut_laptop_panel_does_not_count_as_a_screen_left_on(make_store, sandbox, monkeypatch):
    """Built-in panels are always saved on, but with the lid shut they show nothing: turning off every
    external screen then must be refused, not tried (black screens until the revert)."""
    page, dialogs = make_display_page(make_store(), monkeypatch, live=(LID_SHUT, EXTERNAL))
    page.rows["DP-1"]["entry"]["enabled"] = False
    page.draft["DP-1"] = page.rows["DP-1"]["entry"]
    ps.DisplaysPage.apply(page)
    assert "At least one display has to stay on" in page.win.toasts
    assert not dialogs and not [c for c in sandbox.run_async if c[:2] == ["hyprctl", "eval"]]


class Spin:
    def __init__(self):
        self.value = None

    def set_value(self, v):
        self.value = v


def test_arrange_leaves_no_gap_for_a_shut_laptop_panel(make_store, monkeypatch):
    second = dict(MON, name="HDMI-A-1", width=1920, height=1080, x=5000)
    page, _ = make_display_page(make_store(), monkeypatch, live=(LID_SHUT, EXTERNAL, second))
    for r in page.rows.values():
        r["x"], r["y"] = Spin(), Spin()
    ps.DisplaysPage.arrange(page)
    assert page.rows["DP-1"]["x"].value == 0 and page.rows["HDMI-A-1"]["x"].value == 2560
    assert page.rows["eDP-1"]["x"].value is None
