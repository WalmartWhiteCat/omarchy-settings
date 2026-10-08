"""Opt-in: load a generated file in a nested Hyprland and check `hyprctl configerrors`.

Run with  OSETTINGS_NESTED_HYPRLAND=1 pytest tests/test_nested_hyprland.py
It opens a small Hyprland window inside the current session for a few seconds. The nested
instance gets its own HOME/XDG_CONFIG_HOME under tmp_path, no D-Bus session, and every
hyprctl call names its signature explicitly; the parent session's signature is never used."""

import json
import os
import shutil
import signal
import time
from pathlib import Path

import pytest

from osettings import store as store_mod

from .conftest import REAL_OMARCHY, REAL_POPEN, REAL_RUN
from .test_render import REBIND_LINE

pytestmark = pytest.mark.integration

PARENT_SIG = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))


def skip_reason():
    if os.environ.get("OSETTINGS_NESTED_HYPRLAND") != "1":
        return "set OSETTINGS_NESTED_HYPRLAND=1 to start a nested Hyprland"
    if not os.environ.get("WAYLAND_DISPLAY"):
        return "no Wayland session to nest in"
    if not (shutil.which("Hyprland") and shutil.which("hyprctl")):
        return "Hyprland/hyprctl not installed"
    if not (REAL_OMARCHY / "default/hypr/bootstrap.lua").exists():
        return "Omarchy not installed"
    return None


TEST_MAIN = """\
dofile({omarchy} .. "/default/hypr/bootstrap.lua")

-- Record instead of running anything: autostart, and the error notifications from section().
local log = assert(io.open({log}, "w"))
hl.exec_cmd = function(cmd)
  log:write(tostring(cmd), "\\n")
  log:flush()
end

require("default.hypr.helpers")
require("default.hypr.looknfeel")   -- curves the animations refer to
hl.config({{ xwayland = {{ enabled = false }} }})
require("hypr.omarchy_settings")
"""


def settings():
    return {
        "hyprland": {
            "general:gaps_in": 7, "general:gaps_out": 13, "general:border_size": 3,
            "general:col:active_border": {"colors": ["rgba(33ccffee)", "rgba(00ff99ee)"], "angle": 45},
            "general:col:inactive_border": "rgba(595959aa)",
            "decoration:rounding": 6, "decoration:blur:enabled": False,
            "decoration:shadow:color": "rgba(1a1a1aee)", "decoration:inactive_opacity": 0.9,
            "input:kb_options": "compose:caps", "input:sensitivity": -0.25,
        },
        "cursor": {"theme": "Adwaita", "size": 24},
        "monitors": {"DP-98": {"enabled": False},
                     "DP-99": {"mode": "1920x1080@60", "x": 0, "y": 0, "scale": 1.25, "transform": 1}},
        "rules": [{"class": "org.gnome.Calculator", "float": True},
                  {"class": "steam_app_[0-9]+ (game)", "workspace": 5, "no_blur": True,
                   "opacity_active": 1.0, "opacity_inactive": 0.85}],
        "binds": {"disabled": [],
                  "rebinds": [{"old": "SUPER + RETURN", "new": "SUPER + ALT + F12", "line": REBIND_LINE}],
                  "custom": [{"keys": "SUPER + ALT + F11", "command": 'echo "héllo\\\\wörld"',
                              "description": 'Say "hi"', "launch": False}]},
        "autostart": [{"command": "true", "launch": False}],
        "animations": {"factor": 1.5, "windows": "slide", "workspaces": "slidefade 20%"},
    }


def hyprctl(sig, *args):
    assert sig and sig != PARENT_SIG
    env = {**os.environ, "HYPRLAND_INSTANCE_SIGNATURE": sig}
    p = REAL_RUN(["hyprctl", "--instance", sig, *args], capture_output=True, text=True, env=env, timeout=10)
    return p.stdout


def find_instance(pid, before, deadline):
    while time.time() < deadline:
        for d in (RUNTIME / "hypr").glob("*"):
            if d.name in before or d.name == PARENT_SIG:
                continue
            lock = d / "hyprland.lock"
            try:
                if lock.read_text().split()[0] == str(pid) and (d / ".socket.sock").exists():
                    return d.name
            except (OSError, IndexError):
                pass
        time.sleep(0.2)
    return None


@pytest.mark.skipif(skip_reason() is not None, reason=skip_reason() or "")
def test_generated_config_loads_without_errors(tmp_path, make_store, monkeypatch):
    home = tmp_path / "nested-home"
    hypr = home / ".config/hypr"
    hypr.mkdir(parents=True)
    log = tmp_path / "exec.log"

    monkeypatch.setattr(store_mod, "HYPR_LUA", hypr / "omarchy_settings.lua")
    st = make_store(settings())
    store_mod.HYPR_LUA.write_text(st.render_lua())
    (hypr / "hyprland.lua").write_text(TEST_MAIN.format(omarchy=json.dumps(str(REAL_OMARCHY)),
                                                        log=json.dumps(str(log))))

    env = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
           "XDG_STATE_HOME": str(home / ".local/state"), "XDG_DATA_HOME": str(home / ".local/share"),
           "XDG_CACHE_HOME": str(home / ".cache"), "XDG_RUNTIME_DIR": str(RUNTIME),
           "WAYLAND_DISPLAY": os.environ["WAYLAND_DISPLAY"], "PATH": os.environ.get("PATH", "/usr/bin"),
           "OMARCHY_PATH": str(REAL_OMARCHY), "DBUS_SESSION_BUS_ADDRESS": "disabled:",
           "XDG_SESSION_TYPE": "wayland"}
    before = {d.name for d in (RUNTIME / "hypr").glob("*")}
    proc = REAL_POPEN(["Hyprland"], env=env, stdin=open(os.devnull), stdout=open(tmp_path / "hypr.out", "w"),
                      stderr=open(tmp_path / "hypr.err", "w"), start_new_session=True)
    sig = None
    try:
        sig = find_instance(proc.pid, before, time.time() + 30)
        if sig is None:
            if proc.poll() is not None:
                pytest.skip(f"nested Hyprland exited ({proc.returncode}): "
                            f"{(tmp_path / 'hypr.err').read_text()[-500:]}")
            pytest.skip("nested Hyprland did not open its socket in time")
        assert sig != PARENT_SIG
        time.sleep(1.0)  # let the config finish loading

        errors = [e for e in json.loads(hyprctl(sig, "configerrors", "-j") or "[]") if e.strip()]
        assert errors == [], errors

        # Our file really was loaded into the nested instance.
        gaps = json.loads(hyprctl(sig, "getoption", "general:gaps_in", "-j"))
        assert "7" in json.dumps(gaps)

        # No section() failed (each failure would have tried to send a notification).
        logged = log.read_text() if log.exists() else ""
        assert "omarchy-notification-send" not in logged, logged
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(10)
            except Exception:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(5)
        # A killed instance leaves its runtime dir behind; remove ours (never the parent's).
        if sig and sig != PARENT_SIG and proc.poll() is not None:
            shutil.rmtree(RUNTIME / "hypr" / sig, ignore_errors=True)
