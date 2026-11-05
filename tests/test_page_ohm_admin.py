"""Qwen3.6-OHM: Model, Prompt & Playbook, Safety & Watcher and the Danger Zone."""
import json

import pytest
from gi.repository import Adw, Gtk

from osettings import pages_ohm as po

from .pagekit import callbacks, needs_display, open_page, spin, widgets  # noqa: F401  (open_page is a fixture)
from .test_page_ohm import VRAM, describe, shown

pytestmark = needs_display

CONFIG = {"vram": dict(VRAM), "game_mode": {"processes": []}, "model": {"path": "/m/Qwen-A.gguf", "alias": "qwen-moe", "context": 131072},
          "llama": {"extra_args": ["-b", "2048", "--mmproj", "/m/mmproj.gguf"], "slots": 4, "slot_similarity": 0.5, "pin_slots": True},
          "prompt": {"swift": True, "playbook": True, "facts": True, "safety": True}, "loop": {"max_tool_calls": 12, "max_tool_calls_thinking": 40, "break_with": "tool_choice", "ask_when_vague": True},
          "verify": {"mode": "shadow", "slot": 3, "min_words": 12, "timeout_s": 12, "max_tokens": 300}, "budget": {"normal": [90, 150, 240], "code": [300, 480, 600], "crash": [300, 600, 900]},
          "protect": {"enabled": True, "screen": True, "extra_paths": ["~/Work/important"]}, "guard": {"mode": "off"},
          "health": {"interval_s": 5, "fail_limit": 3, "crash_limit": 5, "crash_window_s": 600, "failed_retry_s": 600, "backoff_s": [5, 15]}}
RANGES = {"model.context": [4096, 262144], "loop.max_tool_calls": [1, 200], "loop.max_tool_calls_thinking": [1, 500], "verify.min_words": [1, 500], "verify.timeout_s": [1, 120],
          "verify.max_tokens": [50, 2000], "health.interval_s": [0.1, 60], "health.fail_limit": [1, 20], "health.crash_limit": [1, 50], "health.crash_window_s": [5, 3600],
          "health.failed_retry_s": [1, 7200], "llama.slots": [1, 8], "llama.slot_similarity": [0.0, 1.0]}
MODELS = {"models": [{"path": "/m/Qwen-A.gguf", "name": "Qwen-A.gguf", "size_mib": 13000, "current": True, "valid": True},
                     {"path": "/m/Qwen-B.gguf", "name": "Qwen-B.gguf", "size_mib": 17000, "current": False, "valid": True},
                     {"path": "/m/broken.gguf", "name": "broken.gguf", "size_mib": 3, "current": False, "valid": False}], "dir": "/m"}
LESSONS = [{"id": 1, "kind": "repeat", "text": "Do not repeat `ls`.", "status": "new", "count": 3, "last": "2026-11-05 10:00:00"},
           {"id": 2, "kind": "over", "text": "Stop after the first command.", "status": "accepted", "count": 1, "last": "x"}]


@pytest.fixture
def ohm(sandbox, monkeypatch, tmp_path):
    d = describe()
    d["config"] = json.loads(json.dumps(CONFIG))
    d["ranges"] = {**d["ranges"], **RANGES}
    d["enums"] = {"loop.break_with": ["tool_choice", "drop_tools"], "verify.mode": ["off", "shadow", "append"], "guard.mode": ["off", "readonly"]}
    out = sandbox.run_output
    out[("ohm", "config", "--json")] = json.dumps(d)
    out[("ohm", "autostart", "status")] = "starts at login: yes"
    out[("ohm", "models", "--json")] = json.dumps(MODELS)
    out[("ohm", "lessons", "--json")] = json.dumps(LESSONS)
    out[("ohm", "verify", "-n", "3")] = "mode: shadow\n4 checks: ok 4"
    pb = tmp_path / "playbook.md"
    out[("ohm", "playbook", "--json")] = json.dumps({"path": str(pb), "custom": False, "text": "- be brief", "default": "- be brief"})
    po.OHM_STATE.mkdir(parents=True, exist_ok=True)
    return callbacks(monkeypatch, po, __import__("osettings.pages_ohm_admin", fromlist=["x"]))


def page(open_page, sandbox, key):
    """Open a page and forget the commands the window itself ran on the way (a hyprctl reload), so a test can say "nothing ran"."""
    p = open_page(key)
    sandbox.run_async.clear()
    sandbox.run_chain.clear()
    return p


def dialog(p):
    d = p.win.get_visible_dialog()
    assert isinstance(d, Adw.AlertDialog), "no dialog open"
    return d


def answer(p, response="ok", typed=None):
    d = dialog(p)
    if typed is not None:
        next(w for w in widgets(d) if isinstance(w, Gtk.Entry)).set_text(typed)
    d.emit("response", response)
    d.force_close()
    spin()


def sets(sandbox, path=None):
    return [c for batch in sandbox.run_chain for c in batch if c[:3] == ["ohm", "config", "set"] and (path is None or c[3] == path)]


# ---------------------------------------------------------------- Model


def test_the_model_page_lists_the_files(ohm, sandbox, open_page):
    p = page(open_page, sandbox, "ohm-model")
    assert "Qwen-A.gguf" in p.row("Model in use", Adw.ActionRow).get_subtitle() and "called qwen-moe" in p.row("Model in use", Adw.ActionRow).get_subtitle()
    assert "13000 MiB" in p.row("Qwen-A.gguf", Adw.ActionRow).get_subtitle() and "in use" in p.row("Qwen-A.gguf", Adw.ActionRow).get_subtitle()
    assert "not a valid model file" in p.row("broken.gguf", Adw.ActionRow).get_subtitle()
    use = lambda name: [w for w in widgets(p.row(name, Adw.ActionRow)) if isinstance(w, Gtk.Button)]
    assert use("Qwen-B.gguf") and not use("Qwen-A.gguf") and not use("broken.gguf")      # a button only for a usable, other model


def test_switching_asks_first_and_warns_about_the_projector(ohm, open_page, sandbox):
    p = page(open_page, sandbox, "ohm-model")
    next(w for w in widgets(p.row("Qwen-B.gguf", Adw.ActionRow)) if isinstance(w, Gtk.Button)).emit("clicked")
    assert "image input is turned off" in dialog(p).get_body() and sandbox.run_async == []
    answer(p, "cancel")
    assert sandbox.run_async == []
    next(w for w in widgets(p.row("Qwen-B.gguf", Adw.ActionRow)) if isinstance(w, Gtk.Button)).emit("clicked")
    answer(p, "ok")
    assert sandbox.run_async[-1] == ["ohm", "models", "use", "/m/Qwen-B.gguf", "--drop-mmproj"]


def test_without_a_projector_nothing_is_dropped(sandbox, ohm, open_page):
    d = json.loads(sandbox.run_output[("ohm", "config", "--json")])
    d["config"]["llama"]["extra_args"] = ["-b", "2048"]
    sandbox.run_output[("ohm", "config", "--json")] = json.dumps(d)
    p = page(open_page, sandbox, "ohm-model")
    next(w for w in widgets(p.row("Qwen-B.gguf", Adw.ActionRow)) if isinstance(w, Gtk.Button)).emit("clicked")
    assert "vision projector" not in dialog(p).get_body()
    answer(p, "ok")
    assert sandbox.run_async[-1] == ["ohm", "models", "use", "/m/Qwen-B.gguf"]


def test_a_refused_switch_says_why(ohm, open_page, sandbox):
    p = page(open_page, sandbox, "ohm-model")
    next(w for w in widgets(p.row("Qwen-B.gguf", Adw.ActionRow)) if isinstance(w, Gtk.Button)).emit("clicked")
    answer(p, "ok")
    ohm["async"][-1][1](1, "", "x is not a model file\n")
    assert p.toasts[-1] == "x is not a model file"


def test_the_context_size(ohm, open_page, sandbox):
    p = page(open_page, sandbox, "ohm-model")
    p.number("Context size", 65536)
    p.page.flush_pending()
    assert sets(sandbox, "model.context")[-1] == ["ohm", "config", "set", "model.context", "65536"]


# ---------------------------------------------------------------- Prompt and playbook


def test_prompt_switches_and_limits(ohm, open_page, sandbox):
    p = page(open_page, sandbox, "ohm-prompt")
    p.switch("Facts about this setup", False)
    assert sets(sandbox, "prompt.facts")[-1][4] == "false"
    p.number("Most tool calls in one turn", 8)
    p.page.flush_pending()
    assert sets(sandbox, "loop.max_tool_calls")[-1][4] == "8"
    p.choose("When the limit is reached", "Take the tools away")
    assert sets(sandbox, "loop.break_with")[-1][4] == '"drop_tools"'
    p.switch("Ask when the request is vague", False)
    assert sets(sandbox, "loop.ask_when_vague")[-1][4] == "false"


def test_the_time_limits_are_sent_as_the_whole_list(ohm, open_page, sandbox):
    p = page(open_page, sandbox, "ohm-prompt")
    p.number("Coding: firmer warning", 500)
    p.page.flush_pending()
    assert sets(sandbox, "budget.code")[-1] == ["ohm", "config", "set", "budget.code", "[300, 500, 600]"]


def test_the_second_opinion(ohm, open_page, sandbox):
    p = page(open_page, sandbox, "ohm-prompt")
    assert shown(p.row("Mode", Adw.ComboRow)) == "Log only"
    p.choose("Mode", "Append a note to the answer")
    assert sets(sandbox, "verify.mode")[-1][4] == '"append"'
    assert p.has_row("What it has found lately")


def test_lessons_are_accepted_or_rejected_by_you(ohm, open_page, sandbox):
    p = page(open_page, sandbox, "ohm-prompt")
    row = p.row("Do not repeat `ls`.", Adw.ActionRow)
    assert not p.has_row("Stop after the first command.")      # accepted ones aren't suggestions any more
    add, no = [w for w in widgets(row) if isinstance(w, Gtk.Button)]
    add.emit("clicked")
    assert sandbox.run_async[-1] == ["ohm", "lessons", "accept", "1"]
    no.emit("clicked")
    assert sandbox.run_async[-1] == ["ohm", "lessons", "reject", "1"]


def test_no_lessons_says_so(sandbox, ohm, open_page):
    sandbox.run_output[("ohm", "lessons", "--json")] = "[]"
    assert open_page("ohm-prompt").has_row("No suggestions waiting")


def test_saving_the_playbook_makes_your_own_copy(ohm, sandbox, open_page, tmp_path):
    p = page(open_page, sandbox, "ohm-prompt")
    p.page.buffer.set_text("- be brief\n- never guess dates\n")
    p.press("Save as my playbook")
    assert (tmp_path / "playbook.md").read_text() == "- be brief\n- never guess dates\n" and any("Playbook saved" in t for t in p.toasts)


def test_going_back_to_the_built_in_playbook_asks(sandbox, ohm, open_page):
    pb = json.loads(sandbox.run_output[("ohm", "playbook", "--json")])
    sandbox.run_output[("ohm", "playbook", "--json")] = json.dumps({**pb, "custom": True, "text": "- mine"})
    p = page(open_page, sandbox, "ohm-prompt")
    assert not p.has_row("Save as my playbook") is False
    p.press("Go back to the built-in playbook")
    assert "deleted" in dialog(p).get_body()
    answer(p, "cancel")
    assert sandbox.run_async == []
    p.press("Go back to the built-in playbook")
    answer(p, "ok")
    assert sandbox.run_async[-1] == ["ohm", "playbook", "reset"]


# ---------------------------------------------------------------- Safety and watcher


def test_the_safety_page_says_what_is_on(ohm, open_page, sandbox):
    p = page(open_page, sandbox, "ohm-safety")
    assert "blocks deleting your home folder" in p.row("Safety screen", Adw.ActionRow).get_subtitle()
    d = json.loads(sandbox.run_output[("ohm", "config", "--json")])
    d["config"]["protect"]["screen"] = False
    sandbox.run_output[("ohm", "config", "--json")] = json.dumps(d)
    assert p.page is not None and "OFF" in page(open_page, sandbox, "ohm-safety").row("Safety screen", Adw.ActionRow).get_subtitle()


def test_read_only_mode_and_protected_folders(ohm, open_page, sandbox):
    p = page(open_page, sandbox, "ohm-safety")
    p.choose("Read-only mode", "Read-only")
    assert sets(sandbox, "guard.mode")[-1][4] == '"readonly"'
    assert p.has_row("~/Work/important")
    p.enter("Protect another folder or file", "~/Work/more")
    assert sets(sandbox, "protect.extra_paths")[-1][4] == '["~/Work/important", "~/Work/more"]'
    p.enter("Protect another folder or file", "~/Work/more")      # twice: once
    p.enter("Protect another folder or file", "  ")
    assert len(sets(sandbox, "protect.extra_paths")) == 1
    gone = p.row("~/Work/important", Adw.ActionRow)
    next(w for w in widgets(gone) if isinstance(w, Gtk.Button)).emit("clicked")
    assert sets(sandbox, "protect.extra_paths")[-1][4] == '["~/Work/more"]'


def test_the_watcher_and_the_server_settings(ohm, open_page, sandbox):
    p = page(open_page, sandbox, "ohm-safety")
    p.number("Check the model every", 10)
    p.number("Conversations kept ready", 2)
    p.page.flush_pending()
    batch = sandbox.run_chain[-1]
    assert ["ohm", "config", "set", "health.interval_s", "10"] in batch and ["ohm", "config", "set", "llama.slots", "2"] in batch
    p.switch("Give each chat its own slot", False)
    assert sets(sandbox, "llama.pin_slots")[-1][4] == "false"


# ---------------------------------------------------------------- Danger zone


def test_the_danger_zone_is_loud_and_apart(ohm, sandbox, open_page):
    p = page(open_page, sandbox, "ohm-danger")
    banners = p.rows(Adw.Banner)
    assert banners and "DANGER ZONE" in banners[0].get_title() and banners[0].get_revealed()
    for title in ("Safety screen is on", "All protection of Hermes's own files is on", "The safety rules in its instructions is on"):
        assert p.row(title).get_active()
    # none of the dangerous controls are on the ordinary pages
    for key in ("ohm", "ohm-memory", "ohm-model", "ohm-prompt", "ohm-safety"):
        assert not page(open_page, sandbox, key).has_row("Delete this file") and not page(open_page, sandbox, key).has_row("Remove its background services")


def test_a_protection_stays_on_until_the_typed_word_is_right(ohm, open_page, sandbox):
    p = page(open_page, sandbox, "ohm-danger")
    p.page.guards["protect.screen"].set_active(False)
    assert p.page.guards["protect.screen"].get_active() and sets(sandbox) == []      # asked first: it didn't turn off by itself
    d = dialog(p)
    assert "TURN OFF" in d.get_heading() or "SAFETY" in d.get_heading()
    entry = next(w for w in widgets(d) if isinstance(w, Gtk.Entry))
    entry.set_text("turn off")      # the wrong case
    assert not d.get_response_enabled("ok")
    entry.set_text("TURN OFF")
    assert d.get_response_enabled("ok")
    answer(p, "cancel")
    assert p.page.guards["protect.screen"].get_active() and sets(sandbox) == []
    p.page.guards["protect.screen"].set_active(False)
    answer(p, "ok", typed="TURN OFF")
    assert not p.page.guards["protect.screen"].get_active() and sets(sandbox, "protect.screen")[-1][4] == "false"


def test_turning_a_protection_back_on_needs_no_questions(sandbox, ohm, open_page):
    d = json.loads(sandbox.run_output[("ohm", "config", "--json")])
    d["config"]["prompt"]["safety"] = False
    sandbox.run_output[("ohm", "config", "--json")] = json.dumps(d)
    p = page(open_page, sandbox, "ohm-danger")
    assert not p.row("The safety rules in its instructions is on").get_active()
    p.switch("The safety rules in its instructions is on", True)
    assert sets(sandbox, "prompt.safety")[-1][4] == "true" and not isinstance(p.win.get_visible_dialog(), Adw.AlertDialog)


@pytest.mark.parametrize("title, cmd", [("Delete the saved conversations", ["ohm", "cache", "clear"]), ("Clear the lesson list", ["ohm", "lessons", "clear"])])
def test_deleting_things_asks_and_then_runs(ohm, open_page, sandbox, title, cmd):
    p = page(open_page, sandbox, "ohm-danger")
    next(w for w in widgets(p.row(title, Adw.ActionRow)) if isinstance(w, Gtk.Button)).emit("clicked")
    answer(p, "cancel")
    assert sandbox.run_async == []
    next(w for w in widgets(p.row(title, Adw.ActionRow)) if isinstance(w, Gtk.Button)).emit("clicked")
    answer(p, "ok")
    assert sandbox.run_async[-1] == cmd


def test_deleting_a_model_file_lists_only_the_others_and_needs_the_word(ohm, open_page, sandbox):
    p = page(open_page, sandbox, "ohm-danger")
    combo = p.row("File", Adw.ComboRow)
    assert [combo.get_model().get_string(i) for i in range(combo.get_model().get_n_items())] == ["Qwen-B.gguf (17000 MiB)", "broken.gguf (3 MiB)"]      # never the one in use
    p.choose("File", "Qwen-B.gguf (17000 MiB)")
    p.press("Delete this file")
    d = dialog(p)
    next(w for w in widgets(d) if isinstance(w, Gtk.Entry)).set_text("yes")
    assert not d.get_response_enabled("ok")
    answer(p, "cancel")
    assert sandbox.run_async == []
    p.press("Delete this file")
    answer(p, "ok", typed="DELETE")
    assert sandbox.run_async[-1] == ["ohm", "models", "delete", "/m/Qwen-B.gguf", "--yes"]


@pytest.mark.parametrize("title, word, cmd", [("Put every Qwen3.6-OHM setting back to its default", "RESET", ["ohm", "config", "reset", "--yes"]),
                                              ("Remove it from Hermes", "REMOVE", ["ohm", "hermes-unregister"]),
                                              ("Remove its background services", "UNINSTALL", ["ohm", "uninstall-services"])])
def test_the_big_ones_need_a_typed_word(ohm, open_page, sandbox, title, word, cmd):
    p = page(open_page, sandbox, "ohm-danger")
    p.press(title)
    d = dialog(p)
    assert not d.get_response_enabled("ok")
    answer(p, "ok", typed="nope")
    assert sandbox.run_async == []      # the wrong word: the button was never enabled, and answering did nothing
    p.press(title)
    answer(p, "ok", typed=word)
    assert sandbox.run_async[-1] == cmd


def test_a_failing_command_says_why(ohm, open_page, sandbox):
    p = page(open_page, sandbox, "ohm-danger")
    p.press("Remove its background services")
    answer(p, "ok", typed="UNINSTALL")
    ohm["async"][-1][1](1, "", "could not stop the service\n")
    assert p.toasts[-1] == "could not stop the service"
