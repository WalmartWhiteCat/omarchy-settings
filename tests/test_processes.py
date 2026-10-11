"""core.run_async / run_chain: a command that hangs must still finish, so nothing waits on it forever."""

import subprocess
import time

from gi.repository import GLib

from osettings import core

# The sandbox stubs core.run_async / run_chain; these are the real ones, taken at import.
REAL_RUN_ASYNC = core.run_async
REAL_RUN_CHAIN = core.run_chain


def wait_for(results):
    end = time.monotonic() + 5
    while not results and time.monotonic() < end:
        GLib.MainContext.default().iteration(False)
        time.sleep(0.01)
    return results


def hangs(monkeypatch):
    """subprocess.run that times out, as a command still running at its deadline would."""
    seen = []

    def run(cmd, **kw):
        seen.append(kw.get("timeout"))
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    monkeypatch.setattr(core.subprocess, "run", run)
    return seen


def test_run_async_reports_a_command_that_hangs(monkeypatch):
    seen = hangs(monkeypatch)
    results = []
    REAL_RUN_ASYNC(["omarchy", "theme", "set", "x"], lambda *r: results.append(r))
    code, out, err = wait_for(results)[0]
    assert seen == [core.COMMAND_TIMEOUT] and code != 0 and "didn't finish" in err


def test_run_async_timeout_can_be_longer(monkeypatch):
    seen = hangs(monkeypatch)
    results = []
    REAL_RUN_ASYNC(["omarchy", "theme", "install", "url"], lambda *r: results.append(r), timeout=600)
    wait_for(results)
    assert seen == [600]


def test_run_chain_reports_a_command_that_hangs_and_goes_on(monkeypatch):
    seen = hangs(monkeypatch)
    results = []
    REAL_RUN_CHAIN([["omarchy", "a"], ["omarchy", "b"]], lambda f: results.append(f))
    failures = wait_for(results)[0]
    assert seen == [core.COMMAND_TIMEOUT] * 2
    assert len(failures) == 2 and all("didn't finish" in f for f in failures)
