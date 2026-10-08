"""Test harness: every path the app knows about points into tmp_path, and no subprocess
other than `luac` may run. Nothing here may touch the live desktop."""

import json
import os
import pwd
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from gi.repository import GLib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from osettings import binds, core, pages_keys, pages_look, pages_system, store  # noqa: E402

# Kept for the opt-in integration test, which needs to start a nested Hyprland.
REAL_RUN = subprocess.run
REAL_POPEN = subprocess.Popen
REAL_OMARCHY = core.OMARCHY_PATH

ALLOWED = {"luac"}
US_KEYCODES = {**{9 + i: str(i % 10) for i in range(1, 11)}, 20: "minus", 21: "equal", 24: "q", 36: "return"}
MODULES = (core, store, binds, pages_look, pages_system, pages_keys)


def _argv0(args):
    cmd = args[0] if args else None
    if isinstance(cmd, (str, bytes)):
        cmd = cmd.split()[0] if isinstance(cmd, str) else cmd
    else:
        cmd = list(cmd)[0]
    return os.path.basename(str(cmd))


def _guarded(real):
    def wrapper(*args, **kwargs):
        name = _argv0(args or [kwargs.get("args")])
        if name not in ALLOWED:
            raise AssertionError(f"test tried to run a real command: {args!r}")
        return real(*args, **kwargs)

    return wrapper


class Calls:
    """Records the stubbed run / run_async / run_chain calls."""

    def __init__(self):
        self.run, self.run_async, self.run_chain, self.spawn, self.trash = [], [], [], [], []
        self.run_output = {}  # tuple(cmd) -> stdout for the stubbed run()

    def all_cmds(self):
        return self.run + self.run_async + [c for chain in self.run_chain for c in chain] + self.spawn


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch, request):
    """Point every module-level path at tmp_path and stub process helpers."""
    home = tmp_path / "home"
    (home / ".config/hypr").mkdir(parents=True)
    omarchy = tmp_path / "omarchy"
    omarchy.mkdir()

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local/state"))
    monkeypatch.delenv("HYPRLAND_INSTANCE_SIGNATURE", raising=False)

    paths = {
        "HOME": home,
        "OMARCHY_PATH": omarchy,
        "STATE": home / ".local/state/omarchy",
        "CONFIG_DIR": home / ".config/omarchy-settings",
        "HYPR_DIR": home / ".config/hypr",
        "SHELL_JSON": home / ".config/omarchy/shell.json",
        "USER_THEMES": home / ".config/omarchy/themes",
        "SETTINGS_FILE": home / ".config/omarchy-settings/settings.json",
        "LEGACY_FILE": home / ".config/omarchy-settings/hyprland.json",
        "HYPR_LUA": home / ".config/hypr/omarchy_settings.lua",
        "HYPR_MAIN": home / ".config/hypr/hyprland.lua",
        "MONITORS_LUA": home / ".config/hypr/monitors.lua",
        "HYPRSUNSET_CONF": home / ".config/hypr/hyprsunset.conf",
        "PIN_HOOK": home / ".config/omarchy/hooks/theme-set.d/50-omarchy-settings-pins",
    }
    for mod in MODULES:
        for name, value in paths.items():
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, value)

    calls = Calls()

    def fake_run(cmd, timeout=20):
        calls.run.append(list(cmd))
        return calls.run_output.get(tuple(cmd), "")

    def fake_run_ok(cmd):
        calls.run.append(list(cmd))
        return False

    def fake_run_async(cmd, done=None):
        calls.run_async.append(list(cmd))

    def fake_run_chain(cmds, done=None):
        calls.run_chain.append([list(c) for c in cmds])

    def fake_spawn(cmd):
        calls.spawn.append(list(cmd))
        return True

    stubs = {"run": fake_run, "run_ok": fake_run_ok, "run_async": fake_run_async,
             "run_chain": fake_run_chain, "spawn_detached": fake_spawn,
             "hypr_option": lambda name: None, "hypr_json": lambda *a: None, "gsetting": lambda *a, **k: "",
             # a fixed US keymap, so tests don't depend on the machine's keyboard layout
             "keycode_name": lambda code: US_KEYCODES.get(code),
             "source_bind_spellings": lambda: {},
             # never the real Trash: record and remove instead
             "trash_file": lambda path: (calls.trash.append(str(path)), os.remove(path)) and None}
    for mod in MODULES:
        for name, fn in stubs.items():
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, fn)

    if "integration" not in request.keywords:
        monkeypatch.setattr(subprocess, "run", _guarded(REAL_RUN))
        monkeypatch.setattr(subprocess, "Popen", _guarded(REAL_POPEN))

    calls.home = home
    calls.omarchy = omarchy
    yield calls


REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
WATCHED = [REAL_HOME / ".config/hypr", REAL_HOME / ".config/omarchy-settings", REAL_HOME / ".config/omarchy"]


def _snapshot():
    out = {}
    for d in WATCHED:
        if d.is_dir():
            for p in d.iterdir():
                try:
                    out[p] = p.stat().st_mtime_ns
                except OSError:
                    pass
    return out


@pytest.fixture(autouse=True, scope="session")
def live_config_untouched():
    """Fail the run if anything in the real ~/.config/hypr etc. changed while tests ran."""
    before = _snapshot()
    yield
    after = _snapshot()
    changed = sorted(str(p) for p in set(before) | set(after) if before.get(p) != after.get(p))
    assert not changed, f"live config changed during tests: {changed}"


@pytest.fixture
def make_store(sandbox):
    """Build a Store from a settings dict without touching GLib timers."""
    results = []

    def make(data=None):
        if data is not None:
            store.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            store.SETTINGS_FILE.write_text(json.dumps(data))
        s = store.Store(results.append)
        s.results = results
        made.append(s)
        return s

    made = []
    yield make
    for s in made:  # drop debounced saves so no GLib timer outlives the test
        if s._pending:
            GLib.source_remove(s._pending)
            s._pending = None


def luac_error(text):
    """None when `text` parses as Lua, else luac's message. Fails the test if luac is missing."""
    if not shutil.which("luac"):
        pytest.skip("luac not installed")
    p = subprocess.run(["luac", "-p", "-"], input=text, capture_output=True, text=True, timeout=10)
    return None if p.returncode == 0 else p.stderr.strip()
