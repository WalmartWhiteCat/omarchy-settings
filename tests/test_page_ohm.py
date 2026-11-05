"""Qwen3.6-OHM pages (Tools): what they show from the files and `moe-local config --json`, and the commands they run."""
import json
import time

import pytest
from gi.repository import Adw, Gtk

from osettings import pages_ohm as po

from .pagekit import callbacks, needs_display, open_page, widgets  # noqa: F401  (open_page is a fixture)

pytestmark = needs_display

VRAM = {"yield_low_mib": 1000, "headroom_mib": 2000, "cap_mib": 7500, "min_model_mib": 2700, "wake_margin_mib": 1500, "idle_tick_s": 2.0, "settle_window_s": 10, "settle_band_mib": 300,
        "settle_slope_mib": 150, "settle_timeout_s": 60, "peak_window_s": 30, "grow_room_mib": 1500, "grow_stable_s": 30, "cooldown_s": 90, "tick_s": 1.0, "ram_low_mib": 1500, "ram_ok_mib": 4000,
        "start_timeout_s": 240, "ramp_steps_mib": [2700, 5100, 7500], "ramp_check_s": 30, "ramp_idle_s": 20, "ramp_hold_s": 300}


def describe(games=(), steps=None):
    vram = dict(VRAM, **({"ramp_steps_mib": steps} if steps is not None else {}))
    return {"file": "/x/config.toml", "exists": True, "config": {"vram": vram, "game_mode": {"processes": list(games)}}, "defaults": {"vram": dict(VRAM), "game_mode": {"processes": []}},
            "warnings": [], "ranges": {"vram.cap_mib": [2000, 64000], "vram.yield_low_mib": [300, 8000], "vram.headroom_mib": [500, 8000], "vram.min_model_mib": [1000, 64000],
                                       "vram.wake_margin_mib": [200, 16000], "vram.ramp_check_s": [1, 3600], "vram.ramp_idle_s": [0, 3600], "vram.ramp_hold_s": [0, 86400], "vram.tick_s": [0.05, 10]},
            "enums": {}, "restart_keys": ["model.path"], "no_live_keys": ["ports.router"]}


@pytest.fixture
def ohm(sandbox, monkeypatch):
    """OHM installed: `moe-local config --json` answers, autostart is on, no flags, a fresh state.json."""
    sandbox.run_output[("moe-local", "config", "--json")] = json.dumps(describe())
    sandbox.run_output[("moe-local", "autostart", "status")] = "starts at login: yes (enabled, enabled)"
    po.OHM_STATE.mkdir(parents=True, exist_ok=True)
    write_state()
    return callbacks(monkeypatch, po)


def write_state(**over):
    s = {"state": "RUNNING", "reason": "running", "free": 7000, "used": 9000, "others": 1400, "model": 7600, "total": 16304, "step": 3, "steps": [2700, 5100, 7500], "ts": time.time(), "restart_needed": []}
    s.update(over)
    (po.OHM_STATE / "state.json").write_text(json.dumps(s))


def sub(p, title):
    return p.row(title, Adw.ActionRow).get_subtitle()


# ---------------------------------------------------------------- Control


def test_not_installed_says_so(sandbox, open_page):
    p = open_page("ohm")
    assert any("isn't installed" in (g.get_description() or "") for g in p.rows(Adw.PreferencesGroup)) and not p.has_row("Keep the model off")


def test_status_comes_from_the_state_file(ohm, open_page):
    p = open_page("ohm")
    assert sub(p, "Model") == "Running: running" and sub(p, "Size") == "Step 3 of 3 (7500 MiB)"
    assert "9000 of 16304 MiB" in sub(p, "GPU memory") and "other programs 1400" in sub(p, "GPU memory")
    write_state(state="YIELDED", reason="only 700 MiB VRAM free", step=None)
    p.page.refresh()
    assert sub(p, "Model").startswith("Waiting for room") and sub(p, "Size") == "Not loaded"
    write_state(ts=time.time() - 60)
    p.page.refresh()
    assert "hasn't reported" in sub(p, "Model")
    (po.OHM_STATE / "state.json").unlink()
    p.page.refresh()
    assert sub(p, "Model") == "Not running"


def test_settings_waiting_for_a_restart_are_listed(ohm, open_page):
    p = open_page("ohm")
    assert not p.row("Needs a restart to apply", Adw.ActionRow).get_visible()
    write_state(restart_needed=["model.context", "ports.router"])
    p.page.refresh()
    row = p.row("Needs a restart to apply", Adw.ActionRow)
    assert row.get_visible() and "model.context, ports.router" in row.get_subtitle()
    write_state(config_notice="config.toml cannot be read: keeping the settings in use")
    p.page.refresh()
    assert "cannot be read" in row.get_subtitle()


def test_the_off_switch(ohm, open_page, sandbox):
    p = open_page("ohm")
    assert not p.row("Keep the model off").get_active()
    p.switch("Keep the model off", True)
    assert sandbox.run_async[-1] == ["moe-local", "pause"]
    p.switch("Keep the model off", False)
    assert sandbox.run_async[-1] == ["moe-local", "resume"]


def test_the_switch_follows_the_pause_flag_and_a_timed_pause_shows_its_end(ohm, open_page, sandbox):
    (po.OHM_STATE / "pause").write_text("")
    p = open_page("ohm")
    assert p.row("Keep the model off").get_active() and not p.row("Switched off for a set time", Adw.ActionRow).get_visible()
    n = len(sandbox.run_async)
    (po.OHM_STATE / "pause").write_text(str(int(time.time()) + 3600))
    p.page.refresh()
    timed = p.row("Switched off for a set time", Adw.ActionRow)
    assert not p.row("Keep the model off").get_active() and timed.get_visible() and "Until " in timed.get_subtitle() and "(in 6" in timed.get_subtitle()      # 60 or 59 minutes
    assert len(sandbox.run_async) == n      # showing a state sent no command
    next(w for w in widgets(timed) if isinstance(w, Gtk.Button)).emit("clicked")
    assert sandbox.run_async[-1] == ["moe-local", "resume"]
    (po.OHM_STATE / "pause").unlink()
    p.page.refresh()
    assert not timed.get_visible()


def test_switching_off_for_a_set_time(ohm, open_page, sandbox):
    p = open_page("ohm")
    p.press("Switch off for that long")
    assert sandbox.run_async[-1] == ["moe-local", "pause", "--for", "30m"]
    p.choose("Switch it off for", "2 hours")
    p.press("Switch off for that long")
    assert sandbox.run_async[-1] == ["moe-local", "pause", "--for", "2h"]
    p.enter("Or type a length (30m, 2h, 1h30m)", "45m")
    assert sandbox.run_async[-1] == ["moe-local", "pause", "--for", "45m"]
    n = len(sandbox.run_async)
    p.enter("Or type a length (30m, 2h, 1h30m)", "   ")
    assert len(sandbox.run_async) == n      # nothing typed, nothing run


def test_a_refused_command_says_why(ohm, open_page, sandbox):
    p = open_page("ohm")
    p.switch("Keep the model off", True)
    ohm["async"][-1][1](2, "", "--for takes a length between 1 minute and 7 days\n")
    assert p.toasts[-1] == "--for takes a length between 1 minute and 7 days"


def test_the_lock(ohm, open_page, sandbox):
    p = open_page("ohm")
    assert not p.row("Lock at a step").get_active() and p.row("Lock at a step").get_sensitive()
    steps = p.row("Step", Adw.ComboRow)
    assert [steps.get_model().get_string(i) for i in range(3)] == ["Step 1: 2700 MiB", "Step 2: 5100 MiB", "Step 3: 7500 MiB"]
    p.choose("Step", "Step 2: 5100 MiB")
    assert sandbox.run_async == [] or sandbox.run_async[-1] != ["moe-local", "lock", "2"]      # choosing a step does not lock by itself
    p.switch("Lock at a step", True)
    assert sandbox.run_async[-1] == ["moe-local", "lock", "2"]
    p.choose("Step", "Step 3: 7500 MiB")
    assert sandbox.run_async[-1] == ["moe-local", "lock", "3"]
    p.switch("Lock at a step", False)
    assert sandbox.run_async[-1] == ["moe-local", "lock", "off"]


def test_the_lock_flag_is_shown(ohm, open_page):
    (po.OHM_STATE / "lock-step").write_text("2")
    p = open_page("ohm")
    assert p.row("Lock at a step").get_active() and shown(p.row("Step", Adw.ComboRow)) == "Step 2: 5100 MiB"
    (po.OHM_STATE / "lock-step").unlink()
    p.page.refresh()
    assert not p.row("Lock at a step").get_active()


def shown(combo):
    return combo.get_model().get_string(combo.get_selected())


def test_without_steps_there_is_nothing_to_lock(sandbox, open_page):
    sandbox.run_output[("moe-local", "config", "--json")] = json.dumps(describe(steps=[]))
    sandbox.run_output[("moe-local", "autostart", "status")] = "starts at login: no"
    p = open_page("ohm")
    assert not p.row("Lock at a step").get_sensitive() and not p.row("Step", Adw.ComboRow).get_sensitive()


def test_start_at_login(ohm, open_page, sandbox):
    p = open_page("ohm")
    assert p.row("Start with the computer").get_active()
    p.switch("Start with the computer", False)
    assert sandbox.run_async[-1] == ["moe-local", "autostart", "off"]
    p.switch("Start with the computer", True)
    assert sandbox.run_async[-1] == ["moe-local", "autostart", "on"]


def games_written(sandbox):
    return [c for c in sandbox.run_chain if c and c[0][:4] == ["moe-local", "config", "set", "game_mode.processes"]]


def test_the_game_list(ohm, open_page, sandbox, monkeypatch):
    p = open_page("ohm")
    assert p.has_row("No games on the list")
    p.enter("Add a program (its process name)", "Client-Win64-Sh")
    assert games_written(sandbox)[-1] == [["moe-local", "config", "set", "game_mode.processes", '["Client-Win64-Sh"]']]
    assert p.has_row("Client-Win64-Sh") and not p.has_row("No games on the list")
    p.enter("Add a program (its process name)", "Client-Win64-Sh")      # twice: once
    p.enter("Add a program (its process name)", "  ")
    assert len(games_written(sandbox)) == 1
    p.enter("Add a program (its process name)", "osu!")
    assert games_written(sandbox)[-1] == [["moe-local", "config", "set", "game_mode.processes", '["Client-Win64-Sh", "osu!"]']]
    gone = p.row("osu!", Adw.ActionRow)
    next(w for w in widgets(gone) if isinstance(w, Gtk.Button)).emit("clicked")
    assert games_written(sandbox)[-1] == [["moe-local", "config", "set", "game_mode.processes", '["Client-Win64-Sh"]']] and not p.has_row("osu!")


def test_picking_a_running_program(ohm, open_page, sandbox, monkeypatch):
    monkeypatch.setattr(po, "running_programs", lambda: ["Hyprland", "Proton", "steam"])
    p = open_page("ohm")
    p.press("Pick from the running programs…")
    dialog = p.win.get_visible_dialog()
    rows = [w for w in widgets(dialog) if isinstance(w, Adw.ActionRow)]
    assert [r.get_title() for r in rows] == ["Hyprland", "Proton", "steam"]
    next(r for r in rows if r.get_title() == "Proton").emit("activated")
    assert games_written(sandbox)[-1] == [["moe-local", "config", "set", "game_mode.processes", '["Proton"]']]


def test_running_programs_are_this_users_process_names():
    names = po.running_programs()
    assert names and names == sorted(names, key=str.casefold) and all(n == n.strip() and n for n in names)


# ---------------------------------------------------------------- Memory


def test_memory_values_and_limits_come_from_the_project(ohm, open_page):
    p = open_page("ohm-memory")
    cap = p.row("Most memory the model may use", Adw.SpinRow)
    assert cap.get_value() == 7500 and (cap.get_adjustment().get_lower(), cap.get_adjustment().get_upper()) == (2000, 64000)
    assert p.row("Unload below this much free", Adw.SpinRow).get_value() == 1000 and p.row("Look for room every", Adw.SpinRow).get_value() == 30


def test_a_change_is_written_after_a_moment_as_one_command_each(ohm, open_page, sandbox):
    p = open_page("ohm-memory")
    p.number("Most memory the model may use", 7000)
    p.number("Keep this much free", 2500)
    assert [c for c in sandbox.run_chain] == []      # batched on a short timer
    p.page.flush_pending()
    assert sandbox.run_chain[-1] == [["moe-local", "config", "set", "vram.cap_mib", "7000"], ["moe-local", "config", "set", "vram.headroom_mib", "2500"]]


def test_a_refusal_is_shown_and_the_page_shows_what_the_file_holds(ohm, open_page, sandbox):
    p = open_page("ohm-memory")
    p.number("Unload below this much free", 2500)
    p.page.flush_pending()
    ohm["chain"][-1][1](["yield_low_mib must be below headroom_mib"])
    assert p.toasts[-1] == "yield_low_mib must be below headroom_mib"
    assert p.row("Unload below this much free", Adw.SpinRow).get_value() == 1000      # rebuilt from `config --json`


def test_steps_are_listed_added_and_removed(ohm, open_page, sandbox):
    p = open_page("ohm-memory")
    assert [p.row(f"Step {i}", Adw.SpinRow).get_value() for i in (1, 2, 3)] == [2700, 5100, 7500]
    p.press("Add a step")
    assert sandbox.run_chain[-1] == [["moe-local", "config", "set", "vram.ramp_steps_mib", "[2700, 5100, 7500, 8500]"]]
    assert p.has_row("Step 4")
    remove = next(w for w in widgets(p.row("Step 2", Adw.SpinRow)) if isinstance(w, Gtk.Button) and w.get_tooltip_text() == "Remove this step")
    remove.emit("clicked")
    assert sandbox.run_chain[-1] == [["moe-local", "config", "set", "vram.ramp_steps_mib", "[2700, 7500, 8500]"]]


def test_the_last_step_cannot_be_removed(sandbox, open_page):
    sandbox.run_output[("moe-local", "config", "--json")] = json.dumps(describe(steps=[4000]))
    sandbox.run_output[("moe-local", "autostart", "status")] = "x"
    p = open_page("ohm-memory")
    next(w for w in widgets(p.row("Step 1", Adw.SpinRow)) if isinstance(w, Gtk.Button) and w.get_tooltip_text() == "Remove this step").emit("clicked")
    assert sandbox.run_chain == []


def test_a_step_typed_out_of_order_is_sent_sorted(ohm, open_page, sandbox):
    p = open_page("ohm-memory")
    p.number("Step 1", 6000)
    p.page.flush_pending()
    assert sandbox.run_chain[-1] == [["moe-local", "config", "set", "vram.ramp_steps_mib", "[5100, 6000, 7500]"]]
    assert p.page.resort is True


def test_steps_can_be_turned_off_and_on(ohm, open_page, sandbox):
    p = open_page("ohm-memory")
    p.switch("Use steps", False)
    assert sandbox.run_chain[-1] == [["moe-local", "config", "set", "vram.ramp_steps_mib", "[]"]] and not p.has_row("Step 1")
    p.switch("Use steps", True)
    assert sandbox.run_chain[-1] == [["moe-local", "config", "set", "vram.ramp_steps_mib", "[2700, 5100, 7500]"]] and p.has_row("Step 3")


def test_restore_unsets_every_memory_setting(ohm, open_page, sandbox):
    p = open_page("ohm-memory")
    p.page.reset()
    cmds = sandbox.run_chain[-1]
    assert cmds[0][:3] == ["moe-local", "config", "unset"] and {c[3] for c in cmds} == {f"vram.{k}" for k in VRAM}


def test_advanced_timings_are_there_and_use_the_projects_limits(ohm, open_page):
    p = open_page("ohm-memory")
    tick = p.row("Check while running every", Adw.SpinRow)
    assert tick.get_value() == 1.0 and tick.get_adjustment().get_lower() == 0.05 and tick.get_digits() == 2


def test_the_real_command_answers_in_the_shape_these_pages_read():
    """Against the installed `moe-local` (skipped without it, or with an older one)."""
    import shutil
    import subprocess

    from .conftest import REAL_POPEN

    if not shutil.which("moe-local"):
        pytest.skip("moe-local isn't installed")
    out = REAL_POPEN(["moe-local", "config", "--json"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).communicate(timeout=30)[0]
    try:
        d = json.loads(out)
    except ValueError:
        pytest.skip("this moe-local has no config --json yet")
    assert {"config", "defaults", "ranges", "restart_keys"} <= set(d) and "ramp_steps_mib" in d["config"]["vram"] and "processes" in d["config"]["game_mode"]
    assert set(d["config"]["vram"]) <= set(d["defaults"]["vram"]) and "vram.cap_mib" in d["ranges"]
