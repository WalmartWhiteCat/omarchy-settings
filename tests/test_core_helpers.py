"""core's helpers that the sandbox stubs everywhere else (run, run_ok, run_chain, spawn_detached,
hypr_option, trash_file): the real ones, taken at import, with subprocess / hyprctl / Gio faked
underneath, so nothing real runs. Also write_atomic's clean-up and the color conversions."""

import subprocess
import time
from types import SimpleNamespace

import pytest
from gi.repository import Gdk, GLib

from osettings import core

# The sandbox replaces these in core for every test; these are the real ones.
REAL_RUN = core.run
REAL_RUN_OK = core.run_ok
REAL_RUN_CHAIN = core.run_chain
REAL_SPAWN = core.spawn_detached
REAL_HYPR_OPTION = core.hypr_option
REAL_TRASH = core.trash_file


def fake_subprocess(monkeypatch, answers):
    """core.subprocess.run answers by program name: (returncode, stdout, stderr), or an exception
    to raise. Returns the commands asked for."""
    seen = []

    def run(cmd, **kw):
        seen.append((list(cmd), kw))
        answer = answers[cmd[0]]
        if isinstance(answer, BaseException):
            raise answer
        code, out, err = answer
        return SimpleNamespace(returncode=code, stdout=out, stderr=err)

    monkeypatch.setattr(core.subprocess, "run", run)
    return seen


def wait_for(results):
    end = time.monotonic() + 5
    while not results and time.monotonic() < end:
        GLib.MainContext.default().iteration(False)
        time.sleep(0.01)
    return results


def test_run_returns_trimmed_output_and_nothing_on_failure(monkeypatch):
    seen = fake_subprocess(monkeypatch, {"good": (0, "  out\n", ""), "missing": FileNotFoundError("missing"),
                                         "slow": subprocess.TimeoutExpired("slow", 20)})
    assert REAL_RUN(["good", "x"]) == "out"
    assert REAL_RUN(["missing"]) == ""
    assert REAL_RUN(["slow"]) == ""
    kw = seen[0][1]
    assert kw["capture_output"] and kw["text"] and kw["timeout"] == 20 and kw["stdin"] == subprocess.DEVNULL


def test_run_ok_is_true_only_for_exit_status_0(monkeypatch):
    seen = fake_subprocess(monkeypatch, {"yes": (0, "", ""), "no": (1, "", ""), "two": (2, "", ""),
                                         "missing": FileNotFoundError("missing")})
    assert REAL_RUN_OK(["yes"]) is True
    assert REAL_RUN_OK(["no"]) is False and REAL_RUN_OK(["two"]) is False
    assert REAL_RUN_OK(["missing"]) is False
    assert seen[0][1]["capture_output"] and seen[0][1]["timeout"] == 20


def test_run_chain_runs_every_command_and_names_each_failure(monkeypatch):
    fake_subprocess(monkeypatch, {"ok": (0, "fine", ""), "loud": (1, "out only\n", ""),
                                  "fails": (3, "", "  " + "x" * 150 + "\n"), "missing": FileNotFoundError("no such file")})
    results = []
    REAL_RUN_CHAIN([["ok", "1"], ["loud", "a", "b", "c", "d"], ["fails"], ["missing", "m"]],
                   lambda failures: results.append(failures))
    (failures,) = wait_for(results)
    assert failures == ["loud a b: out only", "fails: " + "x" * 100, "missing m: no such file"]


def test_background_commands_capture_text_and_name_a_hang(monkeypatch):
    seen = fake_subprocess(monkeypatch, {"ok": (0, "", ""), "slow": subprocess.TimeoutExpired("slow", 120)})
    results = []
    REAL_RUN_CHAIN([["ok"], ["slow", "a", "b", "c"]], lambda failures: results.append(failures))
    (failures,) = wait_for(results)
    assert failures == ["slow a b: slow a b didn't finish within 120 seconds"]
    kw = seen[0][1]
    assert kw["capture_output"] and kw["text"] and kw["timeout"] == core.COMMAND_TIMEOUT == 120


def test_run_chain_reports_nothing_when_all_succeed(monkeypatch):
    fake_subprocess(monkeypatch, {"ok": (0, "", "")})
    results = []
    REAL_RUN_CHAIN([["ok"], ["ok"]], lambda failures: results.append(failures))
    assert wait_for(results) == [[]]


def test_spawn_detached_starts_its_own_session_and_says_if_it_could(monkeypatch):
    started = []

    class Popen:
        def __init__(self, cmd, **kw):
            if cmd[0] == "missing":
                raise FileNotFoundError(cmd[0])
            started.append((cmd, kw))

    monkeypatch.setattr(core.subprocess, "Popen", Popen)
    assert REAL_SPAWN(["sh", "-c", "x"]) is True
    assert REAL_SPAWN(["missing"]) is False
    (cmd, kw), = started
    assert kw["start_new_session"] and kw["stdout"] == subprocess.DEVNULL and kw["stdin"] == subprocess.DEVNULL


@pytest.mark.parametrize("answer, expected", [
    ({"option": "general:gaps_in", "int": 5, "set": True}, 5),
    ({"float": 0.75}, 0.75),
    ({"str": "us,fr"}, "us,fr"),
    ({"str": "[[EMPTY]]"}, None),  # hyprctl's word for an unset string
    ({"bool": False}, False),
    ({"css": "5 6 7 8"}, 5),  # gaps: the first (top) side
    ({"css": ""}, None),
    ({"gradient": "ee33ccff ee00ff99 45deg"}, "ee33ccff ee00ff99 45deg"),
    ({"option": "x"}, None),
    ([1, 2], None),
    (None, None),
])
def test_hypr_option_reads_each_kind_of_answer(monkeypatch, answer, expected):
    asked = []
    monkeypatch.setattr(core, "hypr_json", lambda *a: asked.append(a) or answer)
    assert REAL_HYPR_OPTION("general:gaps_in") == expected
    assert asked == [("getoption", "general:gaps_in")]


def test_trash_file_says_why_it_couldnt(tmp_path):
    # A file that doesn't exist, so the real Trash is never touched.
    message = REAL_TRASH(tmp_path / "not-there.png")
    assert isinstance(message, str) and message


def test_write_atomic_leaves_nothing_behind_when_it_fails(tmp_path, monkeypatch):
    folder = tmp_path / "atomic"  # tmp_path also holds the sandbox's folders
    folder.mkdir()
    target = folder / "settings.json"
    target.write_text("old")

    def fail(*a):
        raise OSError("disk full")

    monkeypatch.setattr(core.os, "replace", fail)
    with pytest.raises(OSError):
        core.write_atomic(target, "new")
    assert target.read_text() == "old"
    assert [p.name for p in folder.iterdir()] == ["settings.json"]  # no temp file left


def rgba(r, g, b, a=1.0):
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r, g, b, a
    return c


@pytest.mark.parametrize("value, expected", [
    ("rgba(33ccffee)", "rgba(33ccffee)"),
    ("rgb(33ccff)", "rgba(33ccffff)"),
    ("RGBA(33CCFFEE)", "rgba(888888ff)"),  # not Hyprland's spelling: the fallback
    ("ee33ccff ee00ff99 45deg", "rgba(33ccffee)"),  # AARRGGBB, the first of a gradient
    ("80a9a4e8", "rgba(a9a4e880)"),
    ("#A9A4E8", "rgba(a9a4e8ff)"),
    ("rgba(33ccffe)", "rgba(888888ff)"),
    ("rgba(zzzzzzzz)", "rgba(888888ff)"),
    ("", "rgba(888888ff)"),
    (None, "rgba(888888ff)"),
])
def test_colors_from_hyprland(value, expected):
    assert core.rgba_to_hypr(core.rgba_from_hypr(value)) == expected


def test_colors_to_hyprland_and_hex():
    c = rgba(1, 0.5, 0, 0.25)
    assert core.rgba_to_hypr(c) == "rgba(ff800040)"
    assert core.rgba_to_hex(c) == "#FF8000"
    assert core.rgba_to_hypr(core.rgba_from_hypr("x", fallback="#123456")) == "rgba(123456ff)"


def test_lua_syntax_error_is_luacs_message_or_none():
    """The real check (the store tests replace it to fake a failure)."""
    assert core.lua_syntax_error("x = 1\n") is None
    err = core.lua_syntax_error("x = = 1\n")
    assert err and err.startswith("luac:") and err == err.strip()


def test_images_are_only_image_files(tmp_path):
    d = tmp_path / "bgs"
    (d / "folder.png").mkdir(parents=True)
    for name in ("b.JPG", "a.png", "notes.txt", "c.webp", "noext"):
        (d / name).write_text("x")
    assert [p.name for p in core.images_in(d, tmp_path / "missing")] == ["a.png", "b.JPG", "c.webp"]


def test_theme_preview_prefers_a_preview_then_a_background(monkeypatch, tmp_path):
    user, stock = tmp_path / "user", tmp_path / "stock"
    monkeypatch.setattr(core, "USER_THEMES", user)
    monkeypatch.setattr(core, "OMARCHY_PATH", stock)
    assert core.theme_preview("nord") is None
    (stock / "themes/nord/backgrounds").mkdir(parents=True)
    (stock / "themes/nord/backgrounds/2.png").write_text("x")
    (stock / "themes/nord/backgrounds/1.png").write_text("x")
    assert core.theme_preview("nord") == stock / "themes/nord/backgrounds/1.png"
    (stock / "themes/nord/preview.png").write_text("x")
    assert core.theme_preview("nord") == stock / "themes/nord/preview.png"
    (user / "nord").mkdir(parents=True)
    (user / "nord/preview.png").write_text("x")
    assert core.theme_preview("nord") == user / "nord/preview.png"
    assert core.theme_dir("nord") == user / "nord" and core.theme_dir("other") == stock / "themes/other"


def test_slugs_and_padded_colors():
    assert core.slugify("  Tokyo Night ") == "tokyo-night"
    assert core.rgba_to_hypr(core.rgba_from_hypr("  rgba(33ccffee)  ")) == "rgba(33ccffee)"


def test_row_helpers_keep_their_subtitles():
    switch = core.switch_row("Title", "Sub", None, lambda v: None)
    assert switch.get_subtitle() == "Sub" and switch.get_active() is False
    assert core.combo_row("Title", "Sub", ["a", "b"], "b", lambda v: None, ["a", "b"]).get_subtitle() == "Sub"
    assert core.search_combo("Title", ["a"], "Sub").get_subtitle() == "Sub"
    assert core.scale_row("Title", "Sub", 0, 10, 1, 5, 0, lambda v: None).get_subtitle() == "Sub"
    assert core.switch_row("Title", None, True, lambda v: None).get_subtitle() == ""


def test_no_current_theme_is_an_empty_name():
    assert core.current_theme_slug() == ""  # callers build paths from it
    (core.STATE / "current").mkdir(parents=True)
    (core.STATE / "current/theme.name").write_text("nord\n")
    assert core.current_theme_slug() == "nord"
