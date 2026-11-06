"""Qwen3.6-OHM, the rest: which model it runs, what it is told, how it is kept safe, and the dangerous controls.

Same rule as pages_ohm.py: these pages are a front end for the `ohm` command and decide nothing about validity.
  ohm models --json | use PATH [--drop-mmproj] | delete PATH --yes     ohm lessons --json | accept N | reject N | clear
  ohm playbook --json | reset      ohm cache clear      ohm config reset --yes      ohm hermes-unregister | uninstall-services
Everything that can't easily be undone is on the Danger Zone page, apart from the ordinary settings, with a loud warning and a confirmation."""

import json
from pathlib import Path

from gi.repository import Adw, GLib, Gtk

from .core import clear_group, combo_row, confirm, group_add, icon_button, run, run_async, run_chain, spin_row, switch_row, write_atomic  # noqa: F401  (run_chain: the tests wrap both runners in each page module)
from .pages_ohm import OhmPage


def typed_confirm(win, heading, body, word, on_yes, label="Do it"):
    """A destructive confirmation that only enables its button once `word` is typed, so it can't be done by a stray double click."""
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("ok", label)
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_response_enabled("ok", False)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")
    entry = Gtk.Entry(placeholder_text=f"Type {word} to confirm", activates_default=False)
    entry.connect("changed", lambda e: dialog.set_response_enabled("ok", e.get_text().strip() == word))
    dialog.set_extra_child(entry)
    # the button is disabled until the word is typed, and the word is checked again here: a confirmation that only trusts its button is one signal away from running
    dialog.connect("response", lambda _d, r: on_yes() if r == "ok" and entry.get_text().strip() == word else None)
    dialog.present(win)
    return dialog


def said(page):
    """A `done` callback for a command: a failure shows the command's own message, then the page shows what is true now."""
    def done(code, out, err):
        text = (err or out).strip().splitlines()
        if code != 0:
            page.win.toast((text[-1] if text else "That didn't work")[:200])
        elif text:
            page.win.toast(text[-1][:200])
        page.rebuild()
    return done


# ---------------------------------------------------------------- Model


class OhmModelPage(OhmPage):
    key, title, icon = "ohm-model", "OHM Model", "applications-science-symbolic"

    def build(self):
        if not self.load():
            return
        try:
            data = json.loads(run(["ohm", "models", "--json"]))
        except ValueError:
            data = {}
        models = data.get("models") or []
        self.models_dir = data.get("dir", "its models folder")
        cur = next((m for m in models if m["current"]), None)
        llama = self.cfg["llama"]
        self.has_projector = "--mmproj" in llama["extra_args"] or any(str(a).startswith("--mmproj=") for a in llama["extra_args"])

        g = Adw.PreferencesGroup(title="The model in use", description="Switching reloads it, which takes about half a minute.")
        g.add(Adw.ActionRow(title="Model in use", subtitle=f"{cur['name'] if cur else Path(self.cfg['model']['path']).name} · " + (f"{cur['size_mib']} MiB" if cur else "file not found") + f" · called {self.cfg['model']['alias']} in Hermes"))
        self.num(g, "model.context", "Context size", "Tokens it can hold at once; applies the next time the model loads", 4096)
        self.add(g)

        self.sampling_group()

        self.list = Adw.PreferencesGroup(title="Available models", description=f"Put a model's .gguf file in {self.models_dir} and it shows up here.")
        self.add(self.list)
        for m in models:
            row = Adw.ActionRow(title=m["name"], subtitle=f"{m['size_mib']} MiB" + ("  ·  in use" if m["current"] else "") + ("" if m["valid"] else "  ·  not a valid model file"))
            if not m["current"] and m["valid"]:
                b = Gtk.Button(label="Use", valign=Gtk.Align.CENTER)
                b.connect("clicked", lambda _b, m=m: self.confirm_use(m))
                row.add_suffix(b)
            group_add(self.list, row)
        if not models:
            group_add(self.list, Adw.ActionRow(title="No models found"))
        rescan = Adw.ButtonRow(title="Look again", start_icon_name="view-refresh-symbolic")
        rescan.connect("activated", lambda _r: self.rebuild())
        group_add(self.list, rescan)

    SAMPLING_SETS = (("chat", "Everyday replies", "Thinking off: nearly every request from Hermes"), ("code", "Thinking about code or a crash", "Precise, technical work"),
                     ("think", "Other thinking", "For example a message that starts with /think"))
    SAMPLING_FIELDS = (("temperature", "Temperature", "Higher is more random", 0.05, 2), ("top_p", "Top-p", "Only the most likely words that add up to this share are considered", 0.05, 2),
                       ("top_k", "Top-k", "Only this many most likely words are considered (0 = no limit)", 1, 0), ("min_p", "Min-p", "Drop words less likely than this share of the best one", 0.01, 2),
                       ("presence_penalty", "Presence penalty", "Positive: avoids repeating itself; negative: repeats more", 0.1, 1))

    def sampling_group(self):
        """Sampling: the router fills in these values when the client sends none (Hermes sends none). Off = llama-server's own defaults. Hidden for an older ohm without it."""
        if "sampling" not in self.cfg:
            return
        g = Adw.PreferencesGroup(title="Sampling", description="How the model picks its words. Hermes sends no sampling settings, so without this the model runs on llama-server's own defaults "
                                 "(temperature 1.0, top-p 0.95, no repeat penalty). Switched on, the router fills in the values below for anything the client leaves out. The starting values are "
                                 "Qwen's recommendations for this model. Applies to the next message.")
        g.add(switch_row("Use these sampling values", "Off: llama-server's own defaults", self.cfg["sampling"]["enabled"], lambda on: self.set_now("sampling.enabled", on)))
        for prefix, title, sub in self.SAMPLING_SETS:
            ex = Adw.ExpanderRow(title=title, subtitle=sub)
            for key, label, hint, step, digits in self.SAMPLING_FIELDS:
                path = f"sampling.{prefix}_{key}"
                lo, hi = self.limits(path, (0, 100))
                ex.add_row(spin_row(label, hint, lo, hi, step, self.cfg["sampling"][f"{prefix}_{key}"],
                                    lambda v, p=path, dg=digits: self.set(p, round(v, 3) if dg else int(v)), digits))
            g.add(ex)
        self.add(g)

    def confirm_use(self, m):
        body = f"{m['name']} replaces the model in use. It loads in about half a minute, and Hermes is unavailable meanwhile."
        if self.has_projector:
            body += ("\n\nThe current setup loads a vision projector made for the current model. Another model can't use it, so image input is turned off with this switch.")
        confirm(self.win, "Switch the model?", body, lambda: run_async(["ohm", "models", "use", m["path"], *(["--drop-mmproj"] if self.has_projector else [])], said(self)),
                label="Switch", destructive=False)


# ---------------------------------------------------------------- Prompt and playbook

BUDGETS = [("normal", "Everyday questions"), ("code", "Coding"), ("crash", "Crash reports")]


class OhmPromptPage(OhmPage):
    key, title, icon = "ohm-prompt", "OHM Prompt & Playbook", "document-edit-symbolic"

    def build(self):
        if not self.load():
            return
        d = self.d["enums"]
        g = Adw.PreferencesGroup(title="What it is told", description="Lines added to Hermes's own instructions before the model reads them. Applies from the next message.")
        self.flag(g, "prompt.swift", "Reasoning line", "Asks it to think carefully and check its work")
        self.flag(g, "prompt.playbook", "The playbook", "Short efficient ways to do common things (edited below)")
        self.flag(g, "prompt.facts", "Facts about this setup", "Which model it is, where it runs, how big its context is")
        self.add(g)

        g = Adw.PreferencesGroup(title="Keeping it on track", description="Limits that stop it going round in circles. " + "Applies from the next message.")
        self.num(g, "loop.max_tool_calls", "Most tool calls in one turn", "After this many it must answer with what it has", 1)
        self.num(g, "loop.max_tool_calls_thinking", "…when it is thinking hard", "The same, for questions it thinks about at length", 1)
        self.flag(g, "loop.ask_when_vague", "Ask when the request is vague", "A first message like \"fix it\" gets one short question instead of a search")
        g.add(combo_row("When the limit is reached", "How it is made to stop", ["Tell it to answer without tools", "Take the tools away"], self.cfg["loop"]["break_with"],
                        lambda v: self.set_now("loop.break_with", v), list(d.get("loop.break_with", ["tool_choice", "drop_tools"]))))
        self.add(g)

        g = Adw.PreferencesGroup(title="Time limits", description="Seconds for one question: a first warning, a firmer one, then it must answer.")
        ex = Adw.ExpanderRow(title="Show the time limits")
        for tier, label in BUDGETS:
            for i, word in enumerate(("warning", "firmer warning", "must answer")):
                ex.add_row(spin_row(f"{label}: {word}", "Seconds", 10, 7200, 10, self.cfg["budget"][tier][i], lambda v, tier=tier, i=i: self.set_budget(tier, i, int(v))))
        g.add(ex)
        self.add(g)

        g = Adw.PreferencesGroup(title="Second opinion", description="After an answer that used tools, the same model checks it against what the tools returned. "
                                 "Off does nothing. Log only just records what it finds. Append adds a note to the answer when it finds a real problem.")
        modes = ["off", "shadow", "append"]
        g.add(combo_row("Mode", "Log only is the safe choice", ["Off", "Log only", "Append a note to the answer"], self.cfg["verify"]["mode"], lambda v: self.set_now("verify.mode", v), modes))
        self.num(g, "verify.min_words", "Only check answers longer than", "Words", 1)
        self.num(g, "verify.timeout_s", "Give the check this long", "Seconds, in Append mode", 1)
        self.num(g, "verify.max_tokens", "Longest reply the check may write", "Tokens", 50)
        self.add(g)
        if "gate" in self.cfg["verify"]:          # an older ohm has no sentence gate: nothing to show
            g = Adw.PreferencesGroup(title="Sentence marks", description="While an answer that used web pages is written, a sentence that names things none of the pages contain gets a short "
                                     "note after it. Nothing is rewritten and no extra time is spent. It needs the second opinion's mode above to be anything but Off.")
            g.add(combo_row("Mark unsupported sentences", "Off is the default", ["Off", "Mark them in the answer"], self.cfg["verify"]["gate"], lambda v: self.set_now("verify.gate", v),
                            list(d.get("verify.gate", ["off", "mark"]))))
            self.num(g, "verify.gate_min_missing", "Names or numbers a sentence needs to lack", "Higher marks less, 2 is the tested setting", 1)
            if "gate_lone_figures" in self.cfg["verify"]:
                self.flag(g, "verify.gate_lone_figures", "Also mark one invented figure", "A single number (a decimal, or four digits that is not a year) no page contains")
            self.add(g)
        self.verdicts = Adw.ExpanderRow(title="What it has found lately")
        out = run(["ohm", "verify", "-n", "3"])
        label = Gtk.Label(label=out or "Nothing yet.", xalign=0, wrap=True, selectable=True, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        label.add_css_class("monospace")
        self.verdicts.add_row(label)
        g = Adw.PreferencesGroup()
        g.add(self.verdicts)
        self.add(g)

        self.lessons_group = Adw.PreferencesGroup(title="Suggested lessons", description="Lines the router suggests adding to the playbook when the model loops, over-explores or "
                                                  "tries to touch Hermes's own files. Nothing is added until you accept it.")
        self.add(self.lessons_group)
        self.fill_lessons()

        self.add(self.playbook_group())

    # ---- small helpers
    def flag(self, group, path, title, sub):
        sec, _, key = path.partition(".")
        group.add(switch_row(title, sub, self.cfg[sec][key], lambda on, p=path: self.set_now(p, on)))

    def set_budget(self, tier, i, value):
        vals = list(self.cfg["budget"][tier])
        vals[i] = value
        self.set(f"budget.{tier}", vals)

    # ---- lessons
    def fill_lessons(self):
        clear_group(self.lessons_group)
        try:
            items = json.loads(run(["ohm", "lessons", "--json"]))
        except ValueError:
            items = []
        new = [x for x in items if x.get("status") == "new"]
        if not new:
            group_add(self.lessons_group, Adw.ActionRow(title="No suggestions waiting", subtitle=f"{len(items)} seen so far" if items else "The model hasn't needed one yet"))
        for x in new:
            row = Adw.ActionRow(title=x["text"], subtitle=f"seen {x.get('count', 1)} time(s), last {x.get('last', '')}", title_lines=0)
            row.add_suffix(icon_button("object-select-symbolic", "Add to the playbook", lambda i=x["id"]: run_async(["ohm", "lessons", "accept", str(i)], said(self)), css="suggested-action"))
            row.add_suffix(icon_button("window-close-symbolic", "Not that one", lambda i=x["id"]: run_async(["ohm", "lessons", "reject", str(i)], said(self))))
            group_add(self.lessons_group, row)

    # ---- the playbook
    def playbook_group(self):
        try:
            self.pb = json.loads(run(["ohm", "playbook", "--json"]))
        except ValueError:
            self.pb = {"path": "", "custom": False, "text": "", "default": ""}
        g = Adw.PreferencesGroup(title="The playbook", description=("This is your own playbook." if self.pb["custom"] else "This is the built-in playbook. Saving here makes your own copy, "
                                 "which replaces it.") + " The model reads it with every message, so keep it short and concrete.")
        self.buffer = Gtk.TextBuffer(text=self.pb["text"])
        view = Gtk.TextView(buffer=self.buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8, left_margin=10, right_margin=10, monospace=True)
        scroll = Gtk.ScrolledWindow(child=view, min_content_height=280, hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.add_css_class("card")
        g.add(scroll)
        save = Adw.ButtonRow(title="Save as my playbook", start_icon_name="document-save-symbolic")
        save.connect("activated", lambda _r: self.save_playbook())
        g.add(save)
        if self.pb["custom"]:
            back = Adw.ButtonRow(title="Go back to the built-in playbook", start_icon_name="edit-undo-symbolic")
            back.connect("activated", lambda _r: confirm(self.win, "Use the built-in playbook?", "Your own playbook is deleted. The lines you accepted from lessons go with it.",
                                                         lambda: run_async(["ohm", "playbook", "reset"], said(self)), label="Use the built-in one"))
            g.add(back)
        return g

    def save_playbook(self):
        text = self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), False).strip()
        if not self.pb.get("path"):
            self.win.toast("Couldn't find where the playbook is kept")
            return
        try:
            Path(self.pb["path"]).parent.mkdir(parents=True, exist_ok=True)
            write_atomic(Path(self.pb["path"]), text + "\n")
        except OSError as e:
            self.win.toast(f"Couldn't save the playbook: {e}")
            return
        self.win.toast("Playbook saved: the model uses it from the next message")
        self.rebuild()


# ---------------------------------------------------------------- Safety and watcher


class OhmSafetyPage(OhmPage):
    key, title, icon = "ohm-safety", "OHM Safety & Watcher", "security-high-symbolic"

    def build(self):
        if not self.load():
            return
        p = self.cfg["protect"]
        g = Adw.PreferencesGroup(title="What the model may do", description="The safety screen and its protected folders are always on unless you turn them off in the Danger Zone.")
        g.add(Adw.ActionRow(title="Safety screen", subtitle="On: it blocks deleting your home folder, formatting disks, shutting down, running as root, reading keys and passwords, and editing "
                            "Hermes's settings or its own files" if p["enabled"] and p["screen"] else "OFF: the model can run anything Hermes allows. Turn it back on in the Danger Zone."))
        g.add(combo_row("Read-only mode", "In read-only mode the model can look around but not change anything; most of what Hermes does is then refused",
                        ["Off", "Read-only"], self.cfg["guard"]["mode"], lambda v: self.set_now("guard.mode", v), ["off", "readonly"]))
        self.add(g)

        self.paths = Adw.PreferencesGroup(title="Extra protected folders", description="The model can never write in these, on top of Hermes's settings, your keys and its own files.")
        self.add(self.paths)
        self.fill_paths()
        g = Adw.PreferencesGroup()
        e = Adw.EntryRow(title="Protect another folder or file", show_apply_button=True)
        e.connect("apply", lambda r: (self.add_path(r.get_text()), r.set_text("")))
        g.add(e)
        pick = Adw.ButtonRow(title="Choose a folder…", start_icon_name="folder-open-symbolic")
        pick.connect("activated", lambda _r: self.choose_path())
        g.add(pick)
        self.add(g)

        g = Adw.PreferencesGroup(title="The watcher", description="How it checks that the model is healthy, and when it gives up. Applies within seconds.")
        self.num(g, "health.interval_s", "Check the model every", "Seconds", 1)
        self.num(g, "health.fail_limit", "Restart it after this many failed checks", None, 1)
        self.num(g, "health.crash_limit", "Stop trying after this many crashes", "Within the time below; it then rests before trying again", 1)
        self.num(g, "health.crash_window_s", "…within", "Seconds", 30)
        self.num(g, "health.failed_retry_s", "Rest before trying again", "Seconds", 30)
        self.add(g)

        g = Adw.PreferencesGroup(title="The model server", description="Applies the next time the model loads (switch it off and on on the Control page to do it now).")
        self.num(g, "llama.slots", "Conversations kept ready", "Each one holds a chat's memory so a reply doesn't start from scratch", 1)
        self.num(g, "llama.slot_similarity", "How alike a chat must be to share a slot", "0 to 1", 0.05, 2)
        g.add(switch_row("Give each chat its own slot", "Stops a long research chat from throwing another chat's memory away", self.cfg["llama"]["pin_slots"],
                         lambda on: self.set_now("llama.pin_slots", on)))
        self.add(g)

    def fill_paths(self):
        clear_group(self.paths)
        items = self.cfg["protect"]["extra_paths"]
        if not items:
            group_add(self.paths, Adw.ActionRow(title="None added"))
        for path in items:
            row = Adw.ActionRow(title=path)
            row.add_suffix(icon_button("user-trash-symbolic", "Stop protecting it", lambda p=path: self.set_paths([x for x in self.cfg["protect"]["extra_paths"] if x != p])))
            group_add(self.paths, row)

    def set_paths(self, items):
        self.set_now("protect.extra_paths", items)
        self.fill_paths()

    def add_path(self, text):
        text = text.strip()
        if text and text not in self.cfg["protect"]["extra_paths"]:
            self.set_paths([*self.cfg["protect"]["extra_paths"], text])

    def choose_path(self):
        dialog = Gtk.FileDialog(title="Protect a folder")

        def done(d, result):
            try:
                folder = d.select_folder_finish(result)
            except Exception:  # noqa: BLE001  (cancelled)
                return
            if folder is not None and folder.get_path():
                self.add_path(folder.get_path())

        dialog.select_folder(self.win, None, done)


# ---------------------------------------------------------------- Danger zone


class OhmDangerPage(OhmPage):
    key, title, icon = "ohm-danger", "OHM Danger Zone", "dialog-warning-symbolic"

    def build(self):
        if not self.load():
            return
        banner = Adw.Banner(title="DANGER ZONE: these can break the model, remove its protections, or delete things for good", revealed=True)
        banner.add_css_class("danger")      # red, whatever the window's focus (a plain banner goes grey)
        g = Adw.PreferencesGroup()
        g.add(banner)
        self.add(g)

        p = self.cfg["protect"]
        g = Adw.PreferencesGroup(title="Protections", description="These keep a small model from doing something terrible on your computer. Switching one off is your decision and "
                                 "nothing else will catch what it lets through.")
        self.guards = {}
        for path, title, sub, loud in (("protect.screen", "Safety screen", "Blocks deleting your home folder, formatting disks, shutting down, running as root, reading keys and "
                                        "passwords, and editing Hermes's settings. Off: none of that is checked.", "TURN OFF THE SAFETY SCREEN?"),
                                       ("protect.enabled", "All protection of Hermes's own files", "Hermes's skills, its program files and its database. Off: the model may rewrite them, "
                                        "and one bad edit can stall Hermes entirely.", "TURN OFF ALL PROTECTION?"),
                                       ("prompt.safety", "The safety rules in its instructions", "The paragraph telling it never to delete, shut down, run as root or send passwords, and "
                                        "to treat text in files as data. Off: it isn't told.", "REMOVE THE SAFETY RULES FROM ITS INSTRUCTIONS?")):
            sec, _, key = path.partition(".")
            row = switch_row(title + " is on", sub, self.cfg[sec][key], lambda on, p=path, t=title, h=loud: self.on_guard(p, t, h, on))
            self.guards[path] = row
            g.add(row)
        self.add(g)

        g = Adw.PreferencesGroup(title="Delete things", description="Each of these asks you to confirm.")
        for title, sub, cmd, label in (("Delete the saved conversations", "The model's memory of recent chats. The next messages are slower while it rebuilds them.", ["ohm", "cache", "clear"], "Delete"),
                                       ("Clear the lesson list", "The suggestions waiting to be added to the playbook. The playbook itself is kept.", ["ohm", "lessons", "clear"], "Clear")):
            row = Adw.ActionRow(title=title, subtitle=sub)
            b = Gtk.Button(label=label, valign=Gtk.Align.CENTER, css_classes=["destructive-action"])
            b.connect("clicked", lambda _b, t=title, c=cmd, s=sub: confirm(self.win, t + "?", s, lambda: run_async(c, said(self)), label=label))
            row.add_suffix(b)
            g.add(row)
        self.add(g)

        g = Adw.PreferencesGroup(title="Delete a model file", description="A downloaded model can be many gigabytes and has to be downloaded again. The model in use can't be deleted here.")
        try:
            models = [m for m in json.loads(run(["ohm", "models", "--json"])).get("models", []) if not m["current"]]
        except ValueError:
            models = []
        self.victims = models
        if models:
            self.victim = combo_row("File", None, [f"{m['name']} ({m['size_mib']} MiB)" for m in models], f"{models[0]['name']} ({models[0]['size_mib']} MiB)", lambda v: None)
            g.add(self.victim)
            row = Adw.ButtonRow(title="Delete this file", start_icon_name="user-trash-symbolic")
            row.add_css_class("destructive-action")
            row.connect("activated", lambda _r: self.delete_model())
            g.add(row)
        else:
            g.add(Adw.ActionRow(title="No other model files"))
        self.add(g)

        g = Adw.PreferencesGroup(title="Start over", description="These change a lot at once.")
        reset = Adw.ButtonRow(title="Put every Qwen3.6-OHM setting back to its default", start_icon_name="edit-undo-symbolic")
        reset.add_css_class("destructive-action")
        reset.connect("activated", lambda _r: typed_confirm(self.win, "Reset every setting?",
                      "Memory limits, steps, games, protections, the model server's options (including the vision projector and which llama-server build is used) all go back to the "
                      "built-in defaults, and some defaults may not suit this computer. The old file is kept next to it as config.toml.bak.", "RESET", lambda: run_async(["ohm", "config", "reset", "--yes"], said(self)),
                      label="Reset everything"))
        g.add(reset)
        self.add(g)

        g = Adw.PreferencesGroup(title="Take it apart", description="After these the model is no longer started, or no longer known to Hermes. Your model files and settings stay.")
        for title, sub, cmd, word in (("Remove it from Hermes", "Hermes forgets this model and goes back to the one it used before. Put it back with `ohm hermes-register`.", ["ohm", "hermes-unregister"], "REMOVE"),
                                      ("Remove its background services", "It stops now and no longer starts at login. Put them back with `ohm install-services`.", ["ohm", "uninstall-services"], "UNINSTALL")):
            row = Adw.ButtonRow(title=title, start_icon_name="edit-delete-symbolic")
            row.add_css_class("destructive-action")
            row.connect("activated", lambda _r, t=title, s=sub, c=cmd, w=word: typed_confirm(self.win, t + "?", s, w, lambda: run_async(c, said(self)), label=t))
            g.add(row)
        self.add(g)

    def on_guard(self, path, title, loud, on):
        if self.syncing:
            return
        if on:
            self.set_now(path, True)
            return
        self.quiet_set(self.guards[path], True)      # the switch stays on until it is confirmed
        typed_confirm(self.win, loud, f"{title}: off. Nothing else will catch what it lets through.", "TURN OFF", lambda: self.guard_off(path), label="Turn it off")

    def quiet_set(self, row, value):
        """Set a switch without its handler acting. A change made inside the switch's own handler is announced after that handler returns, so the
        flag is cleared on the next idle, not at once (cleared at once, the second announcement ran the handler and sent a stray command)."""
        self.syncing = True
        row.set_active(value)
        GLib.idle_add(self.done_syncing)

    def done_syncing(self):
        self.syncing = False
        return False

    def guard_off(self, path):
        self.quiet_set(self.guards[path], False)
        self.set_now(path, False)

    def delete_model(self):
        m = self.victims[self.victim.get_selected()]
        typed_confirm(self.win, f"Delete {m['name']}?", f"{m['size_mib']} MiB are deleted for good. It has to be downloaded again to use it.", "DELETE",
                      lambda: run_async(["ohm", "models", "delete", m["path"], "--yes"], said(self)), label="Delete it for good")
