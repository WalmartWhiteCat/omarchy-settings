"""Night Light page, built for real (see pagekit): the on/off switch (from neutral, with hyprsunset
running or not), the warmth slider following live and settling, the schedule written as
hyprsunset profiles (and the original file put back), and Restore defaults. Older stand-in tests
are in test_review_fixes."""

import time

from gi.repository import GLib

from osettings import pages_system as ps

from .pagekit import callbacks, needs_display, open_page, spin  # noqa: F401

pytestmark = needs_display

STATUS = ("omarchy", "toggle", "nightlight", "--status")
REFRESH = ["omarchy-shell", "-q", "nightlight", "refresh"]
ORIGINAL = "# Omarchy's hyprsunset.conf\nprofile {\n    time = 7:00\n    identity = true\n}\n"


def hyprsunset_running(monkeypatch, running=True):
    monkeypatch.setattr(ps, "run_ok", lambda cmd: running and cmd == ["pgrep", "-x", "hyprsunset"])


def settle(seconds=0.7):
    """Run the main loop past the warmth slider's 500ms settle timer."""
    end = time.monotonic() + seconds
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)


def test_opens_with_omarchys_defaults(open_page):
    p = open_page("nightlight")
    assert not p.row("Night light").get_active()
    assert p.row("Warmth").scale.get_value() == 4000
    assert not p.row("Turn on automatically").get_active()
    assert p.row("Turn on at (HH:MM)").get_text() == "20:00"
    assert p.row("Turn off at (HH:MM)").get_text() == "07:00"


def test_the_switch_shows_whether_it_is_on(sandbox, open_page):
    sandbox.run_output[STATUS] = '{"enabled":true,"temperature":4000}'
    assert open_page("nightlight").row("Night light").get_active()


def test_turning_on_starts_hyprsunset_then_sets_the_warmth(sandbox, open_page, monkeypatch):
    hyprsunset_running(monkeypatch, False)
    p = open_page("nightlight", {"nightlight": {"temperature": 3500}})
    p.switch("Night light", True)
    assert sandbox.run_chain[-1] == [["omarchy", "toggle", "nightlight"],
                                     ["hyprctl", "hyprsunset", "temperature", "3500"], REFRESH]


def test_turning_on_and_off_while_hyprsunset_runs_sets_the_temperature(sandbox, open_page, monkeypatch):
    # Not `omarchy toggle nightlight`: from hyprsunset's neutral 6000 K it would turn it "off".
    hyprsunset_running(monkeypatch)
    p = open_page("nightlight")
    p.switch("Night light", True)
    assert sandbox.run_chain[-1] == [["hyprctl", "hyprsunset", "temperature", "4000"], REFRESH]
    p.switch("Night light", False)
    assert sandbox.run_chain[-1] == [["hyprctl", "hyprsunset", "temperature", str(ps.OFF_TEMP)], REFRESH]


def test_turning_off_with_nothing_running_does_nothing(sandbox, open_page, monkeypatch):
    hyprsunset_running(monkeypatch, False)
    sandbox.run_output[STATUS] = '{"enabled":true,"temperature":4000}'
    p = open_page("nightlight")
    p.switch("Night light", False)
    assert sandbox.run_chain == []


def test_warmth_follows_the_slider_and_the_last_value_wins(sandbox, open_page, monkeypatch):
    hyprsunset_running(monkeypatch)
    sandbox.run_output[STATUS] = '{"enabled":true,"temperature":4000}'
    p = open_page("nightlight")
    p.slide("Warmth", 3000)
    p.slide("Warmth", 3300)
    live = [c for c in sandbox.run_async if c[:3] == ["hyprctl", "hyprsunset", "temperature"]]
    assert live == [["hyprctl", "hyprsunset", "temperature", "3000"], ["hyprctl", "hyprsunset", "temperature", "3300"]]
    settle()
    live = [c for c in sandbox.run_async if c[:3] == ["hyprctl", "hyprsunset", "temperature"]]
    assert live[-1] == ["hyprctl", "hyprsunset", "temperature", "3300"] and len(live) == 3  # once more, settled
    assert p.store._pending  # settling schedules the save
    p.save()
    assert p.saved()["nightlight"]["temperature"] == 3300


def test_warmth_while_off_is_only_remembered(sandbox, open_page):
    p = open_page("nightlight")
    p.slide("Warmth", 5000)
    settle()
    assert not [c for c in sandbox.run_async if c[:2] == ["hyprctl", "hyprsunset"]]
    p.save()
    assert p.saved()["nightlight"]["temperature"] == 5000


def test_a_schedule_is_written_as_hyprsunset_profiles(sandbox, open_page, monkeypatch):
    ps.HYPRSUNSET_CONF.write_text(ORIGINAL)
    got = callbacks(monkeypatch, ps)
    p = open_page("nightlight", {"nightlight": {"temperature": 3800}})
    p.enter("Turn on at (HH:MM)", "21:30")
    p.enter("Turn off at (HH:MM)", "06:15")
    p.switch("Turn on automatically", True)
    conf = ps.HYPRSUNSET_CONF.read_text()
    # Each profile applies from its time until the next: off at 06:15, on (3800 K) at 21:30.
    assert ps.SUNSET_TEMPLATE.format(start="21:30", end="06:15", temp=3800) == conf
    assert (ps.HYPR_DIR / "hyprsunset.conf.omarchy-settings-original").read_text() == ORIGINAL
    assert p.saved()["nightlight"] == {"temperature": 3800, "start": "21:30", "end": "06:15", "schedule": True}
    assert 'o.launch_on_start("hyprsunset")' in p.lua()
    restart = [done for cmd, done in got["async"] if cmd == ["omarchy", "restart", "hyprsunset"]]
    assert restart
    restart[-1](0, "", "")
    assert p.toasts[-1] == "Night light schedule saved"
    restart[-1](1, "", "hyprsunset failed to start\n")
    assert p.toasts[-1] == "hyprsunset failed to start"

    p.switch("Turn on automatically", False)
    assert ps.HYPRSUNSET_CONF.read_text() == ORIGINAL  # Omarchy's file is back
    assert not (ps.HYPR_DIR / "hyprsunset.conf.omarchy-settings-original").exists()
    assert "hyprsunset" not in p.lua()


def test_a_time_that_isnt_hh_mm_is_refused(open_page):
    p = open_page("nightlight")
    for bad in ("25:00", "9:00", "21.30", "noon"):
        p.enter("Turn on at (HH:MM)", bad)
        assert p.toasts[-1] == "Use 24-hour time like 20:00"
    assert not ps.HYPRSUNSET_CONF.exists()
    assert "start" not in p.store.nightlight


def test_changing_warmth_rewrites_the_schedule(open_page):
    p = open_page("nightlight", {"nightlight": {"schedule": True, "start": "20:00", "end": "07:00"}})
    p.slide("Warmth", 2800)
    settle()
    assert "temperature = 2800" in ps.HYPRSUNSET_CONF.read_text()


def test_restore_defaults(sandbox, open_page, monkeypatch):
    ps.HYPRSUNSET_CONF.write_text("# Generated by Omarchy Settings: night light schedule.\n")
    (sandbox.omarchy / "config/hypr").mkdir(parents=True)
    (sandbox.omarchy / "config/hypr/hyprsunset.conf").write_text(ORIGINAL)
    sandbox.run_output[STATUS] = '{"enabled":true,"temperature":3000}'
    got = callbacks(monkeypatch, ps)
    p = open_page("nightlight", {"nightlight": {"schedule": True, "temperature": 3000}})
    p.press("Restore defaults")
    d = p.win.get_visible_dialog()
    d.emit("response", "ok")
    d.force_close()
    spin()
    assert p.saved()["nightlight"] == {}
    assert ps.HYPRSUNSET_CONF.read_text() == ORIGINAL  # Omarchy's template, as there was no backup
    cmds, done = got["chain"][-1]
    assert cmds == [["hyprctl", "hyprsunset", "temperature", str(ps.OFF_TEMP)], ["omarchy", "restart", "hyprsunset"]]
    done(True)
    assert p.toasts[-1] == "Night light restored"
