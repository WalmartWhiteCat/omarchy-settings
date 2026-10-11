"""Power and Notifications page, built for real (see pagekit): Do not disturb, Keep awake, the
screensaver and suspend switches (Omarchy's toggles flip, so they only run when the state differs),
the idle times it writes to ~/.config/omarchy/shell.json, and Restore defaults."""

import json

from osettings import pages_system as ps

from .pagekit import callbacks, needs_display, open_page, spin  # noqa: F401

pytestmark = needs_display


def test_idle_times_go_to_their_own_keys(sandbox, open_page):
    # Omarchy's idle service reads idle.screensaver as the screensaver timeout and idle.lock as
    # the lock timeout (shell/plugins/services/idle/Service.qml); the rows once had them swapped.
    ps.SHELL_JSON.parent.mkdir(parents=True, exist_ok=True)
    ps.SHELL_JSON.write_text(json.dumps({"idle": {"screensaver": 150, "lock": 300}}))
    p = open_page("power")
    assert p.row("Start screensaver after").get_value() == 2.5
    assert p.row("Lock screen after").get_value() == 5
    p.number("Lock screen after", 10)
    assert json.loads(ps.SHELL_JSON.read_text())["idle"] == {"screensaver": 150, "lock": 600}
    p.number("Start screensaver after", 3)
    assert json.loads(ps.SHELL_JSON.read_text())["idle"] == {"screensaver": 180, "lock": 600}


def flags(monkeypatch, *on):
    """Which Omarchy toggle flags exist (`omarchy toggle enabled <flag>` succeeds)."""
    monkeypatch.setattr(ps, "run_ok", lambda cmd: cmd[:3] == ["omarchy", "toggle", "enabled"] and cmd[3] in on)


def shell_json(data):
    ps.SHELL_JSON.parent.mkdir(parents=True, exist_ok=True)
    ps.SHELL_JSON.write_text(json.dumps(data))


def omarchy_defaults(sandbox, idle):
    (sandbox.omarchy / "config/omarchy").mkdir(parents=True)
    (sandbox.omarchy / "config/omarchy/shell.json").write_text(json.dumps({"idle": idle}))


def test_do_not_disturb(sandbox, open_page):
    sandbox.run_output[("omarchy-shell", "notifications", "isDnd")] = "on"
    p = open_page("power")
    assert p.row("Do not disturb").get_active()
    p.switch("Do not disturb", False)
    assert sandbox.run_async[-1] == ["omarchy-shell", "notifications", "setDnd", "off"]
    p.switch("Do not disturb", True)
    assert sandbox.run_async[-1] == ["omarchy-shell", "notifications", "setDnd", "on"]


def test_keep_awake(sandbox, open_page):
    # omarchy-toggle-idle's status: "enabled" is true while staying awake.
    sandbox.run_output[("omarchy", "toggle", "idle", "status")] = '{"enabled":true,"class":"enabled"}'
    p = open_page("power")
    assert p.row("Keep awake").get_active()
    p.switch("Keep awake", False)
    assert sandbox.run_async[-1] == ["omarchy", "toggle", "idle", "allow-idle"]
    p.switch("Keep awake", True)
    assert sandbox.run_async[-1] == ["omarchy", "toggle", "idle", "stay-awake"]


def test_unreadable_idle_status_means_idle_allowed(sandbox, open_page):
    sandbox.run_output[("omarchy", "toggle", "idle", "status")] = "not json"
    assert not open_page("power").row("Keep awake").get_active()


def test_flag_switches_only_toggle_when_the_state_differs(sandbox, open_page, monkeypatch):
    # The flags say what's off: screensaver-off present means no screensaver.
    flags(monkeypatch, "screensaver-off")
    p = open_page("power")
    assert not p.row("Screensaver").get_active() and p.row("Suspend in system menu").get_active()
    p.switch("Screensaver", True)
    assert sandbox.run_async[-1] == ["omarchy", "toggle", "screensaver"]
    sandbox.run_async.clear()
    p.switch("Suspend in system menu", True)  # already on: nothing to flip
    p.switch("Suspend in system menu", False)
    assert sandbox.run_async == [["omarchy", "toggle", "suspend"]]


def test_idle_times_fall_back_to_omarchys_and_never_go_below_half_a_minute(sandbox, open_page):
    omarchy_defaults(sandbox, {"screensaver": 150, "lock": 300})
    shell_json({"idle": {"lock": 0}, "bar": {"position": "top"}})
    p = open_page("power")
    assert p.row("Start screensaver after").get_value() == 2.5  # not in the user's file: Omarchy's
    assert p.row("Lock screen after").get_value() == 0.5  # 0 is "right away" to Omarchy
    p.number("Start screensaver after", 0.5)
    data = json.loads(ps.SHELL_JSON.read_text())
    assert data == {"idle": {"lock": 0, "screensaver": 30}, "bar": {"position": "top"}}  # the rest kept


def test_idle_time_without_a_shell_json_isnt_saved(sandbox, open_page):
    p = open_page("power")
    p.number("Lock screen after", 10)
    assert not ps.SHELL_JSON.exists()
    assert p.toasts[-1] == "Couldn't read ~/.config/omarchy/shell.json, so the idle time wasn't saved"


def test_restore_defaults(sandbox, open_page, monkeypatch):
    omarchy_defaults(sandbox, {"screensaver": 150, "lock": 300})
    shell_json({"idle": {"screensaver": 900, "lock": 1200}})
    flags(monkeypatch, "suspend-off")
    got = callbacks(monkeypatch, ps)
    p = open_page("power")
    p.press("Restore defaults")
    d = p.win.get_visible_dialog()
    d.emit("response", "ok")
    d.force_close()
    spin()
    assert json.loads(ps.SHELL_JSON.read_text())["idle"] == {"screensaver": 150, "lock": 300}
    cmds, done = got["chain"][-1]
    assert cmds == [["omarchy-shell", "notifications", "setDnd", "off"], ["omarchy", "toggle", "idle", "allow-idle"],
                    ["omarchy", "toggle", "suspend"]]  # the screensaver is already allowed
    done([])
    assert p.toasts[-1] == "Power and notifications restored"
    done(["omarchy toggle suspend: no permission"])
    assert p.toasts[-1] == "Reset failed: omarchy toggle suspend: no permission"
