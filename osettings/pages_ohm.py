"""Qwen3.6-OHM (the local model that runs beside the desktop): its controls and its memory settings.

These pages are a front end for the `ohm` command; the project decides what is valid:
  ohm config --json          every setting, its default, range and choices
  ohm config set PATH JSON   one change, checked, written with the file's comments kept
  ohm pause [--for 30m] / resume, lock N|off, autostart on|off|status
The running controller and router pick a changed config.toml up within a couple of seconds, so most changes act at once. What
the running model server was started with (the model file, llama options) waits for its next start and is listed on the Control page.
State is read from the files the controller writes (state.json, and the pause and lock-step flags)."""

import json
import os
import time

from gi.repository import Adw, GLib, Gtk

from .core import HOME, Page, clear_group, combo_row, group_add, icon_button, read_json, reset_group, run, run_async, run_chain, spin_row, switch_row
from .pages_widgets import DebouncedWrites

OHM_STATE = HOME / ".local/state/moe-local"
OHM_BIN = HOME / ".local/bin/ohm"
PAUSE_PRESETS = [("15 minutes", "15m"), ("30 minutes", "30m"), ("1 hour", "1h"), ("2 hours", "2h"), ("4 hours", "4h"), ("8 hours", "8h")]
STATE_WORDS = {"RUNNING": "Running", "STARTING": "Loading", "YIELDED": "Waiting for room", "PAUSED": "Off", "GAME": "Off (a game is running)",
               "FAILED": "Failed, will try again", "NO_GPU": "GPU unreadable"}
APPLY_NOTE = "Applies within a couple of seconds."


def ohm_describe():
    """`ohm config --json` as a dict, or None when the command is missing or answers with something else."""
    try:
        d = json.loads(run(["ohm", "config", "--json"]))
    except ValueError:
        return None
    return d if isinstance(d, dict) and "config" in d and "ranges" in d else None


def ohm_flags():
    """(paused, ends, lock): the pause flag (ends = epoch seconds of a timed pause, else None) and the locked step (1-based or None)."""
    paused, ends, lock = False, None, None
    try:
        text = (OHM_STATE / "pause").read_text().strip()
        paused = True
        try:
            ends = float(text) if text else None
        except ValueError:
            ends = None
    except FileNotFoundError:
        pass
    except OSError:
        paused = True
    try:
        n = int((OHM_STATE / "lock-step").read_text().strip())
        lock = n if n >= 1 else None
    except (OSError, ValueError):
        pass
    return paused, ends, lock


# Tools that run inside an app's scope but are never what you start or stop on purpose: shells, coreutils, helpers.
NOT_PROGRAMS = {"bash", "sh", "dash", "zsh", "fish", "python", "python3", "sleep", "cut", "head", "tail", "sort", "grep", "awk", "sed",
                "cat", "less", "tmux", "ssh", "socat", "inotifywait", "gdbus", "systemctl", "journalctl", "chrome_crashpad", "udiskie"}
NOT_PROGRAM_PREFIXES = ("omarchy-", "xdg-", "gvfs", "dbus", "at-spi", "p11-kit", "gnome-keyring", "systemd", "(sd-")


def launched_as_app(cgroup_text):
    """Was this started as an application (by the launcher, Steam or a terminal) rather than as a background service or part of the session?
    systemd puts apps in `app-*.scope` units and daemons (pipewire, bluetooth agents, portals) in `*.service`. Unknown (no cgroup info) counts as yes."""
    unit = cgroup_text.strip().splitlines()[-1].rsplit("/", 1)[-1].removesuffix(" (deleted)") if cgroup_text.strip() else ""
    return not unit or (unit.startswith("app-") and (unit.endswith(".scope") or ".service" in unit))


def is_program(name, cgroup_text):
    """True for something a person might start or stop on purpose: not a system daemon, shell or helper."""
    low = name.lower()
    return bool(name) and low not in NOT_PROGRAMS and not low.startswith(NOT_PROGRAM_PREFIXES) and not low.endswith("-daemon") and launched_as_app(cgroup_text)


def running_programs():
    """Names of the programs this user has started, the way the controller matches games (the first 15 characters of the process name).
    Background services and session plumbing (pipewire, bt-agent, portals, dbus...) are left out; a name can still be typed in by hand."""
    names = set()
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                if os.stat(f"/proc/{d}").st_uid != os.getuid():
                    continue
                name = open(f"/proc/{d}/comm").read().strip()
                try:
                    cg = open(f"/proc/{d}/cgroup").read()
                except OSError:
                    cg = ""
                if is_program(name, cg):
                    names.add(name)
            except OSError:
                pass
    return sorted(names, key=str.casefold)


def clock(epoch):
    return time.strftime("%H:%M", time.localtime(epoch))


def minutes_left(epoch):
    return max(0, round((epoch - time.time()) / 60))


class OhmPage(DebouncedWrites, Page):
    """Base: fetches the settings, writes changes through `ohm config set` (batched on a short timer), refreshes what it shows."""

    @classmethod
    def available(cls):
        return OHM_BIN.exists()      # the launcher its installer makes; any other program called "ohm" on the PATH must not make this page appear

    def load(self):
        self.hook_unrealize()
        self._pending = None
        self.pend = {}
        self.resort = False
        self.syncing = False
        self.timer = None
        self.d = ohm_describe()
        if self.d is None:
            self.add(Adw.PreferencesGroup(description="Qwen3.6-OHM is installed but `ohm` isn't answering. Try `ohm doctor` in a terminal. "
                                          "Nothing here can be changed until it answers."))
            return False
        self.cfg = self.d["config"]
        if not getattr(self, "_stop_hooked", False):
            self._stop_hooked = True
            self.connect("unrealize", lambda *_: self.stop_timer())
        return True

    def stop_timer(self):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None

    def every(self, seconds, fn):
        self.stop_timer()
        self.timer = GLib.timeout_add_seconds(seconds, lambda: fn() or True)

    def limits(self, path, fallback=(0, 100000)):
        lo, hi = self.d["ranges"].get(path, fallback)
        return lo, hi

    def num(self, group, path, title, subtitle, step, digits=0):
        sec, _, key = path.partition(".")
        lo, hi = self.limits(path)
        value = self.cfg[sec][key]
        group.add(spin_row(title, subtitle, lo, hi, step, value, lambda v, p=path, dg=digits: self.set(p, round(v, 3) if dg else int(v)), digits))

    # ---- writing: a short timer batches a burst of changes into one run
    def set(self, path, value):
        sec, _, key = path.partition(".")
        self.cfg[sec][key] = value
        self.pend[path] = value
        if not self._pending:
            self._pending = GLib.timeout_add(500, self.flush)

    def set_now(self, path, value):
        if self._pending:
            GLib.source_remove(self._pending)
            self._pending = None
        sec, _, key = path.partition(".")
        self.cfg[sec][key] = value
        self.pend[path] = value
        self.flush()

    def flush(self):
        self._pending = None
        items, self.pend = list(self.pend.items()), {}
        if items:
            run_chain([["ohm", "config", "set", p, json.dumps(v)] for p, v in items], self.after_set)
        return False

    def after_set(self, failures):
        """A refusal says why (the project's own message); the page then shows what the file really holds."""
        if failures:
            self.win.toast(str(failures[0])[:200])
            self.rebuild()
        elif self.resort:
            self.resort = False
            self.rebuild()


class OhmControlPage(OhmPage):
    key, title, icon = "ohm", "OHM Control", "computer-symbolic"

    def build(self):
        if not self.load():
            return
        paused, ends, lock = ohm_flags()
        g = Adw.PreferencesGroup(title="Qwen3.6-OHM", description="The local model that runs beside your desktop and unloads for games.")
        self.state_row = Adw.ActionRow(title="Model")
        self.size_row = Adw.ActionRow(title="Size")
        self.vram_row = Adw.ActionRow(title="GPU memory")
        self.note_row = Adw.ActionRow(title="Needs a restart to apply", visible=False)
        for r in (self.state_row, self.size_row, self.vram_row, self.note_row):
            g.add(r)
        self.add(g)

        g = Adw.PreferencesGroup(title="Off switch", description="The model unloads at once and gives the GPU back; it loads again by itself when it is on and there is room.")
        self.off = switch_row("Keep the model off", "Until you turn this off. It stays off after a restart or a reboot.", paused and ends is None, self.on_off)
        g.add(self.off)
        self.preset = combo_row("Switch it off for", None, [l for l, _ in PAUSE_PRESETS], "30m", lambda v: None, [v for _, v in PAUSE_PRESETS])
        g.add(self.preset)
        go = Adw.ButtonRow(title="Switch off for that long", start_icon_name="media-playback-pause-symbolic")
        go.connect("activated", lambda _r: self.pause_for(PAUSE_PRESETS[self.preset.get_selected()][1]))
        g.add(go)
        custom = Adw.EntryRow(title="Or type a length (30m, 2h, 1h30m)", show_apply_button=True)
        custom.connect("apply", lambda r: self.pause_for(r.get_text().strip()))
        g.add(custom)
        self.timed = Adw.ActionRow(title="Switched off for a set time", visible=False)
        back = Gtk.Button(label="Switch on now", valign=Gtk.Align.CENTER)
        back.connect("clicked", lambda _b: self.resume())
        self.timed.add_suffix(back)
        g.add(self.timed)
        self.add(g)

        g = Adw.PreferencesGroup(title="Keep it at one size", description="The model normally moves between its steps by itself. A lock holds it at one: it waits for room "
                                 "for exactly that size, and still unloads at once when something needs the memory.")
        steps = self.d["steps"] if "steps" in self.d else self.cfg["vram"]["ramp_steps_mib"]      # the sizes in use (an older ohm only has the list)
        self.lock = switch_row("Lock at a step", None if steps else "Needs steps (see OHM Memory & Steps)", lock is not None, self.on_lock)
        self.lock.set_sensitive(bool(steps))
        g.add(self.lock)
        labels = [f"Step {i + 1}: {size} MiB" for i, size in enumerate(steps)] or ["No steps"]
        self.lock_step = combo_row("Step", None, labels, labels[min((lock or 1) - 1, len(labels) - 1)], self.on_lock_step, labels)
        self.lock_step.set_sensitive(bool(steps))
        g.add(self.lock_step)
        self.add(g)

        g = Adw.PreferencesGroup(title="Start at login")
        self.login = switch_row("Start with the computer", "The model and its watcher start when you log in. Turning this off doesn't stop what is running now.",
                                self.autostart_on(), self.on_login)
        g.add(self.login)
        self.add(g)

        self.games = Adw.PreferencesGroup(title="Games", description="While any of these programs runs, the model is unloaded, and it comes back when they have all closed. "
                                          "They are matched by process name (the first 15 characters).")
        self.add(self.games)
        self.fill_games()
        self.add(self.games_add_group())

        self.refresh()
        self.every(2, self.refresh)

    # ---- what is shown, from the files the controller writes
    def refresh(self):
        s = read_json(OHM_STATE / "state.json")
        s = s if isinstance(s, dict) else {}
        paused, ends, lock = ohm_flags()
        stale = time.time() - float(s.get("ts") or 0) > 10
        state = STATE_WORDS.get(s.get("state"), s.get("state") or "Not running")
        self.state_row.set_subtitle(f"{state}: {s.get('reason')}" if s.get("reason") and s.get("state") else state)
        if stale and s:
            self.state_row.set_subtitle(self.state_row.get_subtitle() + "  (the controller hasn't reported for a while)")
        steps = s.get("steps") or []
        self.size_row.set_subtitle(f"Step {s['step']} of {len(steps)} ({steps[s['step'] - 1]} MiB)" if s.get("step") and s.get("state") in ("RUNNING", "STARTING") and steps else "Not loaded")
        self.vram_row.set_subtitle(f"{s['used']} of {s['total']} MiB in use: other programs {s['others']}, the model {s['model']}" if "used" in s and "total" in s else "")
        wait = [*s.get("restart_needed", [])]
        self.note_row.set_visible(bool(wait or s.get("config_notice")))
        self.note_row.set_subtitle(s.get("config_notice") or ", ".join(wait) + ": the next time the model loads (switch it off and on to do it now)")
        self.syncing = True
        try:
            self.off.set_active(paused and ends is None)
            self.timed.set_visible(paused and ends is not None)
            if paused and ends is not None:
                self.timed.set_subtitle(f"Until {clock(ends)} (in {minutes_left(ends)} min); it loads again by itself")
            self.lock.set_active(lock is not None)
            if lock is not None and self.lock_step.get_model().get_n_items() >= lock:
                self.lock_step.set_selected(lock - 1)
        finally:
            self.syncing = False

    def autostart_on(self):
        return "starts at login: yes" in run(["ohm", "autostart", "status"])

    # ---- the switches
    def on_off(self, on):
        if self.syncing:
            return
        run_async(["ohm", "pause"] if on else ["ohm", "resume"], self.said)

    def pause_for(self, length):
        if length:
            run_async(["ohm", "pause", "--for", length], self.said)

    def resume(self):
        run_async(["ohm", "resume"], self.said)

    def said(self, code, out, err):
        if code != 0:
            self.win.toast((err or out).strip().splitlines()[-1][:200] if (err or out).strip() else "That didn't work")
        self.refresh()

    def on_lock(self, on):
        if self.syncing:
            return
        run_async(["ohm", "lock", str(self.lock_step.get_selected() + 1)] if on else ["ohm", "lock", "off"], self.said)

    def on_lock_step(self, _label):
        if not self.syncing and self.lock.get_active():
            run_async(["ohm", "lock", str(self.lock_step.get_selected() + 1)], self.said)

    def on_login(self, on):
        if not self.syncing:
            run_async(["ohm", "autostart", "on" if on else "off"], self.said)

    # ---- the game list
    def fill_games(self):
        clear_group(self.games)
        names = self.cfg["game_mode"]["processes"]
        if not names:
            group_add(self.games, Adw.ActionRow(title="No games on the list", subtitle="The model only unloads when it needs the memory."))
        for n in names:
            row = Adw.ActionRow(title=n)
            row.add_suffix(icon_button("user-trash-symbolic", "Take it off the list", lambda n=n: self.set_games([x for x in self.cfg["game_mode"]["processes"] if x != n])))
            group_add(self.games, row)

    def games_add_group(self):
        g = Adw.PreferencesGroup()
        e = Adw.EntryRow(title="Add a program (its process name)", show_apply_button=True)
        e.connect("apply", lambda r: (self.add_game(r.get_text()), r.set_text("")))
        g.add(e)
        pick = Adw.ButtonRow(title="Pick from the running programs…", start_icon_name="view-list-symbolic")
        pick.connect("activated", lambda _r: self.pick_game())
        g.add(pick)
        return g

    def set_games(self, names):
        self.set_now("game_mode.processes", names)
        self.fill_games()

    def add_game(self, name):
        name = name.strip()
        if name and name not in self.cfg["game_mode"]["processes"]:
            self.set_games([*self.cfg["game_mode"]["processes"], name])

    def pick_game(self):
        dialog = Adw.AlertDialog(heading="Pick a program", body="Start the game first, then pick it here. Background services are not listed; to watch one of those, type its name in the box instead.")
        dialog.add_response("cancel", "Close")
        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")
        search = Gtk.SearchEntry(placeholder_text="Filter")
        rows = []
        for n in running_programs():
            row = Adw.ActionRow(title=n, activatable=True)
            row.connect("activated", lambda _r, n=n: (self.add_game(n), dialog.force_close()))
            listbox.append(row)
            rows.append((n, row))
        search.connect("search-changed", lambda e: [r.set_visible(e.get_text().lower() in n.lower()) for n, r in rows])
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(search)
        box.append(Gtk.ScrolledWindow(child=listbox, propagate_natural_height=True, max_content_height=320, hscrollbar_policy=Gtk.PolicyType.NEVER))
        dialog.set_extra_child(box)
        dialog.present(self.win)
        return dialog


class OhmMemoryPage(OhmPage):
    key, title, icon = "ohm-memory", "OHM Memory & Steps", "drive-harddisk-symbolic"

    def build(self):
        if not self.load():
            return
        v = self.cfg["vram"]
        g = Adw.PreferencesGroup(title="Memory limits", description="All in MiB of the GPU's memory. " + APPLY_NOTE)
        self.num(g, "vram.cap_mib", "Most memory the model may use", "Even with more free, it never takes more than this", 100)
        self.num(g, "vram.headroom_mib", "Keep this much free", "Room left for a game or app to start, beyond what is in use now", 100)
        self.num(g, "vram.yield_low_mib", "Unload below this much free", "The model unloads at once when free memory falls under this; it must stay below the amount above", 50)
        self.num(g, "vram.wake_margin_mib", "Spare room needed to restart", "How much must be free, beyond the smallest size, before it loads again; above the amount just above", 100)
        self.num(g, "vram.min_model_mib", "Smallest size it will load at", "With little room it loads this small (most of the model in RAM)", 100)
        self.add(g)

        self.steps_group = Adw.PreferencesGroup(title="Steps", description="The model loads at the smallest step and grows one step at a time while the computer is idle and there is room, "
                                                "and drops a step each time memory runs short. Moving between steps reloads the model (about 25 seconds). Sizes above the memory limit are cut to it.")
        self.add(self.steps_group)
        self.fill_steps()

        g = Adw.PreferencesGroup(title="Moving between steps", description=APPLY_NOTE)
        self.num(g, "vram.ramp_check_s", "Look for room every", "Seconds", 1)
        self.num(g, "vram.ramp_idle_s", "Grow only after this long idle", "Seconds with no request", 5)
        self.num(g, "vram.ramp_hold_s", "Wait after an unload before growing", "Seconds", 30)
        self.add(g)

        g = Adw.PreferencesGroup(title="Advanced timings", description="How it judges that the memory has settled and how fast it watches. The defaults were tuned on this machine; "
                                 "the limits keep every value safe, but odd ones can make it unload too easily or react slowly.")
        ex = Adw.ExpanderRow(title="Show the advanced timings")
        for path, title, sub, step, digits in (("vram.tick_s", "Check while running every", "Seconds", 0.1, 2), ("vram.idle_tick_s", "Check while unloaded every", "Seconds", 0.1, 2),
                                               ("vram.settle_window_s", "Memory must stay steady for", "Seconds, before it counts as settled", 1, 0),
                                               ("vram.settle_band_mib", "Steady means within", "MiB", 50, 0), ("vram.settle_slope_mib", "…and not rising faster than", "MiB", 10, 0),
                                               ("vram.settle_timeout_s", "Stop waiting for steady after", "Seconds", 5, 0), ("vram.peak_window_s", "Look back over", "Seconds, for other programs' peak use", 5, 0),
                                               ("vram.grow_room_mib", "Room needed to grow", "MiB", 100, 0), ("vram.grow_stable_s", "Steady before growing for", "Seconds", 5, 0),
                                               ("vram.cooldown_s", "Pause after a start", "Seconds before the next size change", 5, 0), ("vram.ram_low_mib", "Unload when RAM is below", "MiB of free RAM", 100, 0),
                                               ("vram.ram_ok_mib", "Load again when RAM is above", "MiB of free RAM", 100, 0), ("vram.start_timeout_s", "Give a start this long", "Seconds", 10, 0)):
            sec, _, key = path.partition(".")
            if key in v:
                lo, hi = self.limits(path)
                ex.add_row(spin_row(title, sub, lo, hi, step, v[key], lambda val, p=path, dg=digits: self.set(p, round(val, 3) if dg else int(val)), digits))
        g.add(ex)
        self.add(g)

        self.add(reset_group(self.win, "Restore the memory settings?", "Memory limits, steps and timings go back to the project's defaults. The rest of the settings are kept.", self.reset))

    STEP_MODES = [("Pick each size", "list"), ("Spread evenly between a minimum and the maximum", "even")]

    def fill_steps(self):
        clear_group(self.steps_group)
        v = self.cfg["vram"]
        even = v.get("ramp_mode") == "even"
        if "ramp_mode" in v:       # an older Qwen3.6-OHM has only the list
            group_add(self.steps_group, combo_row("How the steps are set", None, [l for l, _ in self.STEP_MODES], v["ramp_mode"], self.on_step_mode, [m for _, m in self.STEP_MODES]))
        if even:
            lo, hi = self.limits("vram.ramp_min_mib")
            group_add(self.steps_group, spin_row("Minimum", "MiB. The steps sit between this and the maximum (“Most memory the model may use”, above); neither end is a step",
                                                 lo, hi, 100, v["ramp_min_mib"], lambda val: self.set("vram.ramp_min_mib", int(val))))
            lo, hi = self.limits("vram.ramp_count")
            group_add(self.steps_group, spin_row("Number of steps between", "Placed at equal distances from each other", lo, hi, 1, v["ramp_count"],
                                                 lambda val: self.set("vram.ramp_count", int(val))))
            self.steps_preview = Adw.ActionRow(title="The steps will be")
            group_add(self.steps_group, self.steps_preview)
            self.show_steps_preview()
            return
        steps = list(v["ramp_steps_mib"])
        use = switch_row("Use steps", "Off: one size from the free memory, and one regrowth (the older way)", bool(steps), self.on_use_steps)
        group_add(self.steps_group, use)
        for i, size in enumerate(steps):
            row = spin_row(f"Step {i + 1}", "MiB" + ("  (the smallest)" if i == 0 else ""), 1000, 64000, 100, size, lambda v, i=i: self.step_changed(i, int(v)))
            row.add_suffix(icon_button("user-trash-symbolic", "Remove this step", lambda i=i: self.remove_step(i)))
            group_add(self.steps_group, row)
        if steps:
            add = Adw.ButtonRow(title="Add a step", start_icon_name="list-add-symbolic")
            add.connect("activated", lambda _r: self.add_step())
            group_add(self.steps_group, add)

    def show_steps_preview(self):
        """The sizes the project works out (`ohm config --json` "steps"): this page never does the arithmetic itself, so it can't disagree with the controller."""
        steps = self.d.get("steps") or []
        row = getattr(self, "steps_preview", None)
        if row is not None:
            row.set_subtitle(" · ".join(str(x) for x in steps) + " MiB" if steps else "None: the minimum must be below the maximum")

    def on_step_mode(self, mode):
        if self.syncing or mode == self.cfg["vram"].get("ramp_mode"):
            return
        self.set_now("vram.ramp_mode", mode)
        self.fill_steps()

    def after_set(self, failures):
        super().after_set(failures)
        if not failures and self.cfg["vram"].get("ramp_mode") == "even":
            fresh = ohm_describe()          # the sizes are worked out by the project; ask it again after every change
            if fresh is not None:
                self.d = fresh
                self.show_steps_preview()

    def on_use_steps(self, on):
        if self.syncing:
            return
        self.set_now("vram.ramp_steps_mib", list(self.d["defaults"]["vram"]["ramp_steps_mib"]) if on else [])
        self.fill_steps()

    def step_changed(self, i, size):
        steps = list(self.cfg["vram"]["ramp_steps_mib"])
        steps[i] = size
        ordered = sorted(set(steps))
        self.resort = ordered != steps        # typed out of order: sent sorted, and the page shows the sorted list afterwards
        self.set("vram.ramp_steps_mib", ordered if len(ordered) == len(steps) else steps)

    def add_step(self):
        steps = list(self.cfg["vram"]["ramp_steps_mib"])
        self.set_now("vram.ramp_steps_mib", [*steps, min(64000, (steps[-1] if steps else 2700) + 1000)])
        self.fill_steps()

    def remove_step(self, i):
        steps = list(self.cfg["vram"]["ramp_steps_mib"])
        if len(steps) > 1:
            del steps[i]
            self.set_now("vram.ramp_steps_mib", steps)
            self.fill_steps()

    def reset(self, done=None):
        run_chain([["ohm", "config", "unset", f"vram.{k}"] for k in self.d["defaults"]["vram"]], lambda f: (self.win.toast(f[0][:160] if f else "Memory settings restored"), self.rebuild(), done and done()))
