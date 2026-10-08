"""System pages: displays, night light, input, fonts, cursor, bar, power and notifications, default apps."""

import copy
import json
import re
import shutil
import time
from pathlib import Path

from gi.repository import Adw, GLib, Gtk, Pango

from .core import (CONFIG_DIR, DEFAULT_FONT, HOME, HYPR_DIR, OMARCHY_PATH, SHELL_JSON, Page, backup, clear_group,
                   combo_row, confirm, group_add, gsetting, hypr_json, icon_button, read_json, reset_group, run,
                   run_async, run_chain, run_ok, scale_row, spawn_detached, spin_row, switch_row, write_atomic)
from .pages_look import apply_pins
from .store import INTERNAL_PANEL, Store

MONITORS_LUA = HYPR_DIR / "monitors.lua"
HYPRSUNSET_CONF = HYPR_DIR / "hyprsunset.conf"


def shell_defaults():
    return read_json(OMARCHY_PATH / "config/omarchy/shell.json",
                     {"idle": {"screensaver": 150, "lock": 300}, "bar": {"position": "top", "transparent": False}})


def read_shell():
    return read_json(SHELL_JSON)


def write_shell(data):
    if data:
        write_atomic(SHELL_JSON, json.dumps(data, indent=2) + "\n")


# ---------------------------------------------------------------- displays


TRANSFORMS = ["Normal", "90°", "180°", "270°", "Flipped", "Flipped 90°", "Flipped 180°", "Flipped 270°"]
SCALE_CANDIDATES = [1, 1.25, 4 / 3, 1.5, 1.6, 5 / 3, 1.75, 2, 2.4, 2.5, 3, 4]


def valid_scales(w, h):
    out = []
    for s in SCALE_CANDIDATES:
        lw, lh = w / s, h / s
        if abs(lw - round(lw)) < 1e-6 and abs(lh - round(lh)) < 1e-6:
            out.append(round(s, 6))
    return out or [1]


TRIAL_MARKER_NAME = "display-trial"  # + a per-trial suffix, so an old watchdog never ends a new trial
MONITOR_RULE_FIELDS = {"output", "mode", "position", "scale", "transform", "disabled"}
TRIAL_SECONDS = 15
# Undoes a display trial even if the app dies first: unless the app removes the marker
# (Keep changes), reloading Hyprland puts the saved settings back.
WATCHDOG = 'sleep "$2"; if [ -e "$1" ]; then rm -f "$1"; hyprctl reload >/dev/null 2>&1; fi'


def monitors_lua_extras(name):
    """Fields other than mode/position/scale/rotation that monitors.lua sets for `name`.

    The app's rule for a screen replaces any earlier rule for it, so these would be lost."""
    try:
        text = MONITORS_LUA.read_text()
    except Exception:
        return []
    text = "\n".join(l for l in text.splitlines() if not l.strip().startswith("--"))
    extras = set()
    for body in re.findall(r"hl\.monitor\(\s*\{(.*?)\}\s*\)", text, re.S):
        if re.search(rf'\boutput\s*=\s*"(desc:)?{re.escape(name)}"', body):
            depth, fields = 0, []
            for tok in re.finditer(r"[{}]|\b(\w+)\s*=", body):  # top-level field names only
                if tok.group(0) == "{":
                    depth += 1
                elif tok.group(0) == "}":
                    depth -= 1
                elif depth == 0:
                    fields.append(tok.group(1))
            extras |= set(fields) - MONITOR_RULE_FIELDS
    return sorted(extras)


def monitor_modes(m):
    """Available modes as 'WxH@R.RR', best first."""
    modes = []
    for mode in m.get("availableModes", []):
        mm = re.match(r"(\d+)x(\d+)@([\d.]+)Hz", mode)
        if mm:
            modes.append(f"{mm.group(1)}x{mm.group(2)}@{float(mm.group(3)):.2f}")
    return sorted(set(modes), key=lambda s: [-float(x) for x in re.split("[x@]", s)])


def mode_size(mode):
    try:
        w, h = (int(v) for v in mode.split("@")[0].split("x"))
        return w, h
    except Exception:
        return 0, 0


def reset_monitor_scale():
    """Put the catch-all scale lines in monitors.lua back to Omarchy's template values.

    Returns False when monitors.lua has been customized beyond those lines (left untouched)."""
    try:
        text = MONITORS_LUA.read_text()
        template = (OMARCHY_PATH / "config/hypr/monitors.lua").read_text()
    except Exception:
        return False
    if "local omarchy_monitor_scale = " not in text:
        return False
    lines = {l.split("=")[0].strip(): l for l in template.splitlines()
             if l.startswith(("local omarchy_monitor_scale =", "local omarchy_gdk_scale ="))}
    out = [lines.get(l.split("=")[0].strip(), l) if l.startswith("local omarchy_") else l
           for l in text.splitlines()]
    new = "\n".join(out) + "\n"
    if new != text:
        backup(MONITORS_LUA)
        MONITORS_LUA.write_text(new)
    return True


class DisplaysPage(Page):
    key, title, icon = "displays", "Displays", "video-display-symbolic"

    def build(self):
        store = self.win.store
        self.live = hypr_json("monitors", "all") or []
        self.draft = copy.deepcopy(store.monitors)
        for m in self.live:
            if m["name"] not in self.draft:
                self.draft[m["name"]] = None  # untouched: follows monitors.lua

        intro = Adw.PreferencesGroup(
            description="Change resolution, refresh rate, scale, rotation and arrangement. Nothing changes "
                        "until you press Apply, and you get 15 seconds to keep or undo it.")
        bar = Gtk.Box(spacing=6, halign=Gtk.Align.END, valign=Gtk.Align.CENTER)
        arrange = Gtk.Button(label="Arrange left to right")
        arrange.connect("clicked", lambda *_: self.arrange())
        self.apply_btn = Gtk.Button(label="Apply", sensitive=False)
        self.apply_btn.add_css_class("suggested-action")
        self.apply_btn.connect("clicked", lambda *_: self.apply())
        bar.append(arrange)
        bar.append(self.apply_btn)
        intro.set_header_suffix(bar)
        self.add(intro)

        self.rows = {}
        for m in self.live:
            self.add(self.monitor_group(m))

        g = Adw.PreferencesGroup(title="All displays")
        g.add(combo_row("Variable refresh rate (VRR)", "Adaptive sync to reduce tearing in games and video",
                        ["Off", "On", "Only for fullscreen apps"], store.current("misc:vrr", 0),
                        lambda v: store.set("misc:vrr", v), [0, 1, 2]))
        g.add(switch_row("Wake screens on mouse movement", None, store.current("misc:mouse_move_enables_dpms", True),
                         lambda v: store.set("misc:mouse_move_enables_dpms", v)))
        g.add(switch_row("Wake screens on key press", None, store.current("misc:key_press_enables_dpms", True),
                         lambda v: store.set("misc:key_press_enables_dpms", v)))
        self.add(g)
        self.add(reset_group(self.win, "Restore default display settings?",
                             "Drops the display settings made here so ~/.config/hypr/monitors.lua applies again, "
                             "and puts automatic scaling back.", self.reset))

    def entry(self, m):
        e = self.draft.get(m["name"])
        if e is None:
            # A screen that is off can report a 0x0 mode; use its best real mode instead.
            if m.get("width", 0) > 0 and m.get("height", 0) > 0:
                mode = f"{m['width']}x{m['height']}@{m['refreshRate']:.2f}"
            else:
                mode = (monitor_modes(m) or ["preferred"])[0]
            # Built-in panels are always saved on; Omarchy's lid handling switches them off.
            on = True if INTERNAL_PANEL.match(m["name"]) else not m.get("disabled", False)
            e = {"enabled": on, "mode": mode,
                 "x": m.get("x", 0), "y": m.get("y", 0), "scale": round(m.get("scale") or 1, 6),
                 "transform": m.get("transform", 0)}
        return e

    def monitor_group(self, m):
        name = m["name"]
        e = self.entry(m)
        description = m.get("description", "")
        extras = monitors_lua_extras(name)
        if extras:
            description += (f"\n⚠ monitors.lua also sets {', '.join(extras)} for this screen. Changing it here "
                            "replaces that rule, so those settings would no longer apply.")
        g = Adw.PreferencesGroup(title=f"{name}", description=description)

        def change(key, value):
            # The entry is the draft from the first change on, so later fix-ups (like the
            # scale being corrected for a new resolution) land in what Apply saves.
            self.draft[name] = e
            e[key] = value
            self.apply_btn.set_sensitive(True)
            if key == "mode":
                self.refresh_scales(name)

        if INTERNAL_PANEL.match(name):
            row = Adw.ActionRow(title="Enabled", subtitle="Built-in screen: Omarchy turns it off by itself when "
                                                          "the lid is closed with another screen connected")
            g.add(row)
        else:
            g.add(switch_row("Enabled", None, e["enabled"], lambda v: change("enabled", v)))
        modes = monitor_modes(m)
        current = e["mode"] if e["mode"] in modes else (modes[0] if modes else e["mode"])
        labels = [f"{s.split('@')[0].replace('x', ' × ')}  ·  {float(s.split('@')[1]):g} Hz" for s in modes]
        g.add(combo_row("Resolution and refresh rate", None, labels, current, lambda v: change("mode", v), modes))
        scale = Adw.ComboRow(title="Scale")
        scale.connect("notify::selected", lambda r, _p: getattr(r, "values", None) and
                      change("scale", r.values[r.get_selected()]))
        g.add(scale)
        g.add(combo_row("Rotation", None, TRANSFORMS, e.get("transform", 0), lambda v: change("transform", v),
                        list(range(8))))
        x = spin_row("Position X", None, -20000, 20000, 1, e["x"], lambda v: change("x", int(v)))
        y = spin_row("Position Y", None, -20000, 20000, 1, e["y"], lambda v: change("y", int(v)))
        g.add(x)
        g.add(y)
        self.rows[name] = {"scale": scale, "x": x, "y": y, "entry": e}
        self.refresh_scales(name, initial=True)
        return g

    def refresh_scales(self, name, initial=False):
        r = self.rows[name]
        e = r["entry"]
        w, h = mode_size(e["mode"])
        scales = valid_scales(w, h) if w and h else [1, 1.25, 1.5, 2]
        if e["scale"] not in scales:
            scales = sorted(set(scales + ([e["scale"]] if initial else [])))
        row = r["scale"]
        row.values = None  # silence notify::selected while the model is swapped
        row.set_model(Gtk.StringList.new([f"{s * 100:.0f}%" for s in scales]))
        target = e["scale"] if e["scale"] in scales else 1
        row.set_selected(scales.index(target) if target in scales else 0)
        row.values = scales
        if not initial and e["scale"] not in scales:
            e["scale"] = scales[row.get_selected()]

    def arrange(self):
        x = 0
        for m in self.live:
            r = self.rows[m["name"]]
            e = r["entry"]
            if not e["enabled"]:
                continue
            r["x"].set_value(x)
            r["y"].set_value(0)
            w, h = mode_size(e["mode"])
            if e.get("transform", 0) % 2:
                w = h
            x += round(w / e["scale"])

    def apply(self):
        """Try the new settings live; they are only saved when the user keeps them.

        The trial is applied with `hyprctl eval`, so the saved config never holds an
        unconfirmed setup. A detached watchdog reloads Hyprland (back to the saved settings)
        after the countdown unless Keep removes its marker, so even a crash of the app
        mid-countdown is undone."""
        if not any(self.rows[m["name"]]["entry"]["enabled"] for m in self.live):
            self.win.toast("At least one display has to stay on")
            return
        store = self.win.store
        new = {k: copy.deepcopy(v) for k, v in self.draft.items() if v is not None}
        lines = [Store.monitor_lua(name, mon) for name, mon in new.items()]
        if not lines:
            return
        marker = CONFIG_DIR / f"{TRIAL_MARKER_NAME}-{time.time_ns()}"
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        marker.write_text("Display settings on trial; removed when kept.\n")
        spawn_detached(["sh", "-c", WATCHDOG, "sh", str(marker), str(TRIAL_SECONDS + 3)])
        self.apply_btn.set_sensitive(False)
        state = {"left": TRIAL_SECONDS, "done": False}

        def keep():
            if state["done"]:
                return
            state["done"] = True
            marker.unlink(missing_ok=True)
            store.monitors = new
            store.save_now()
            self.win.toast("Display settings kept")

        def revert(message="Display settings reverted"):
            if state["done"]:
                return
            state["done"] = True
            marker.unlink(missing_ok=True)
            run_async(["hyprctl", "reload"])
            self.win.toast(message)
            self.rebuild(delay=800)

        def tried(code, out, err):
            if code != 0 or not out.strip().startswith("ok"):
                revert(f"Hyprland refused these display settings: {(out or err).strip()[:120]}")
                dialog.force_close()

        run_async(["hyprctl", "eval", "\n".join(lines)], tried)
        dialog = confirm(self.win, "Keep these display settings?",
                         f"Reverting in {TRIAL_SECONDS} seconds…", keep, label="Keep changes", destructive=False,
                         on_no=revert)

        def tick():
            if state["done"]:
                return False
            state["left"] -= 1
            if state["left"] <= 0:
                revert()
                dialog.force_close()
                return False
            dialog.set_body(f"Reverting in {state['left']} seconds…")
            return True

        GLib.timeout_add(1000, tick)

    def reset(self, done=None):
        store = self.win.store
        store.monitors = {}
        reset_monitor_scale()
        store.reset(["misc:vrr", "misc:mouse_move_enables_dpms", "misc:key_press_enables_dpms"])
        store.schedule_save(after=lambda: (self.rebuild(delay=500), done and done()))


# ---------------------------------------------------------------- night light


OFF_TEMP = 6500  # what Omarchy's nightlight toggle uses for "off"
SUNSET_TEMPLATE = """# Generated by Omarchy Settings: night light schedule.
# Turn the schedule off in the app to go back to Omarchy's default file.
profile {{
    time = {end}
    identity = true
}}

profile {{
    time = {start}
    temperature = {temp}
}}
"""


class NightLightPage(Page):
    key, title, icon = "nightlight", "Night Light", "weather-clear-night-symbolic"

    def build(self):
        store = self.win.store
        nl = store.nightlight
        self._temp_timer = None
        g = Adw.PreferencesGroup(title="Night light", description="Warms the screen to reduce blue light.")
        self.on = switch_row("Night light", "Turn it on now", self.is_on(), self.toggle)
        g.add(self.on)
        self.temp = scale_row("Warmth", "Color temperature in Kelvin: lower is warmer", 2500, 6000, 100,
                              nl.get("temperature", 4000), 0, self.set_temp)
        g.add(self.temp)
        self.add(g)

        g = Adw.PreferencesGroup(title="Schedule",
                                 description="Turns night light on and off at set times every day.")
        g.add(switch_row("Turn on automatically", None, nl.get("schedule"), lambda v: self.set_sched("schedule", v)))
        self.start = Adw.EntryRow(title="Turn on at (HH:MM)", text=nl.get("start", "20:00"), show_apply_button=True)
        self.start.connect("apply", lambda r: self.set_sched("start", r.get_text().strip()))
        self.end = Adw.EntryRow(title="Turn off at (HH:MM)", text=nl.get("end", "07:00"), show_apply_button=True)
        self.end.connect("apply", lambda r: self.set_sched("end", r.get_text().strip()))
        g.add(self.start)
        g.add(self.end)
        self.add(g)
        self.add(reset_group(self.win, "Restore default night light?",
                             "Turns night light off, sets warmth back to 4000 K and removes the schedule.",
                             self.reset))

    @staticmethod
    def is_on():
        try:
            return bool(json.loads(run(["omarchy", "toggle", "nightlight", "--status"])).get("enabled"))
        except Exception:
            return False

    def toggle(self, on):
        """Set the temperature directly. `omarchy toggle nightlight` maps anything other than
        6500 K (including hyprsunset's neutral 6000 K, e.g. after a restart) to 6500 K, so from
        neutral it would turn night light "off" while the switch says on."""
        temp = int(self.win.store.nightlight.get("temperature", 4000))
        target = str(temp if on else OFF_TEMP)
        refresh = ["omarchy-shell", "-q", "nightlight", "refresh"]
        if not run_ok(["pgrep", "-x", "hyprsunset"]):
            if not on:
                return  # nothing is tinting the screen
            # The toggle starts hyprsunset (and waits for it); then set the chosen warmth.
            run_chain([["omarchy", "toggle", "nightlight"], ["hyprctl", "hyprsunset", "temperature", target],
                       refresh])
            return
        run_chain([["hyprctl", "hyprsunset", "temperature", target], refresh])

    def set_temp(self, v):
        self.win.store.nightlight["temperature"] = int(v)
        if self.on.get_active():
            run_async(["hyprctl", "hyprsunset", "temperature", str(int(v))])  # cheap: follow the slider live
        if self._temp_timer:
            GLib.source_remove(self._temp_timer)

        def settle():
            self._temp_timer = None
            if self.on.get_active():
                # The live updates can finish out of order; make sure the final value wins.
                run_async(["hyprctl", "hyprsunset", "temperature", str(int(v))])
            if self.win.store.nightlight.get("schedule"):
                self.write_schedule()
            else:
                self.win.store.schedule_save()
            return False

        self._temp_timer = GLib.timeout_add(500, settle)

    def set_sched(self, key, value):
        if key in ("start", "end") and not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", value):
            self.win.toast("Use 24-hour time like 20:00")
            return
        self.win.store.nightlight[key] = value
        self.write_schedule()

    def write_schedule(self):
        nl = self.win.store.nightlight
        if nl.get("schedule"):
            if not (HYPR_DIR / "hyprsunset.conf.omarchy-settings-original").exists() and HYPRSUNSET_CONF.exists():
                shutil.copy2(HYPRSUNSET_CONF, HYPR_DIR / "hyprsunset.conf.omarchy-settings-original")
            HYPRSUNSET_CONF.write_text(SUNSET_TEMPLATE.format(start=nl.get("start", "20:00"),
                                                              end=nl.get("end", "07:00"),
                                                              temp=int(nl.get("temperature", 4000))))
        else:
            self.restore_conf()
        self.win.store.save_now()  # autostarts hyprsunset when scheduled
        run_async(["omarchy", "restart", "hyprsunset"],
                  lambda c, o, e: self.win.toast("Night light schedule saved" if c == 0 else e.strip()[:120]))

    def restore_conf(self):
        original = HYPR_DIR / "hyprsunset.conf.omarchy-settings-original"
        if original.exists():
            original.replace(HYPRSUNSET_CONF)
        elif HYPRSUNSET_CONF.exists() and HYPRSUNSET_CONF.read_text().startswith("# Generated by Omarchy Settings"):
            shutil.copy2(OMARCHY_PATH / "config/hypr/hyprsunset.conf", HYPRSUNSET_CONF)

    def reset(self, done=None):
        had_schedule = self.win.store.nightlight.get("schedule")
        self.win.store.nightlight = {}
        self.restore_conf()
        self.win.store.save_now()
        cmds = []
        if self.is_on():
            cmds.append(["hyprctl", "hyprsunset", "temperature", str(OFF_TEMP)])
        if had_schedule:
            cmds.append(["omarchy", "restart", "hyprsunset"])

        def finished(_f):
            self.win.toast("Night light restored")
            self.rebuild()
            done and done()

        run_chain(cmds, finished)


# ---------------------------------------------------------------- input


def xkb_layouts():
    out = []
    try:
        text = Path("/usr/share/X11/xkb/rules/evdev.lst").read_text()
        block = text.split("! layout", 1)[1].split("!", 1)[0]
        for line in block.strip().splitlines():
            code, _, desc = line.strip().partition(" ")
            out.append((code, desc.strip()))
    except Exception:
        out = [("us", "English (US)")]
    return out


def non_latin_layouts():
    """Omarchy's list of layouts that can't type Latin letters (read from its input.lua)."""
    try:
        text = (OMARCHY_PATH / "default/hypr/input.lua").read_text()
        m = re.search(r'non_latin_layouts\s*=\s*"([^"]*)"', text)
        if m:
            return set(m.group(1).split())
    except Exception:
        pass
    return set("af am ara bd bg by et ge gr il in iq ir kg kh kz la lk mk mm mn mv np rs ru sy th tj ua".split())


def latin_first(layouts, variants):
    """Hyprland matches shortcuts against the first layout, so a non-Latin first layout
    (e.g. ru) would break Super + letter shortcuts. Like Omarchy's input.lua, put a Latin
    layout first: move an existing one up, or add us. Returns (layouts, variants, changed)."""
    lay = layouts.split(",")
    var = variants.split(",") if variants else []
    var += [""] * (len(lay) - len(var))
    non_latin = non_latin_layouts()
    if not lay or lay[0] not in non_latin:
        return layouts, variants, False
    i = next((i for i, l in enumerate(lay) if l and l not in non_latin), None)
    if i is None:
        lay.insert(0, "us")
        var.insert(0, "")
    else:
        lay.insert(0, lay.pop(i))
        var.insert(0, var.pop(i))
    return ",".join(lay), (",".join(var) if any(var) else ""), True


CAPS_OPTIONS = [
    ("Compose key (Omarchy default)", "compose:caps,shift:both_capslock_cancel"),
    ("Caps Lock", ""),
    ("Escape", "caps:escape"),
    ("Swap with Escape", "caps:swapescape"),
    ("Control", "ctrl:nocaps"),
    ("Backspace", "caps:backspace"),
    ("Disabled", "caps:none"),
]
SWITCH_OPTIONS = [
    ("Left Alt + Right Alt", "grp:alts_toggle"),
    ("Alt + Shift", "grp:alt_shift_toggle"),
    ("Super + Space", "grp:win_space_toggle"),
    ("Ctrl + Shift", "grp:ctrl_shift_toggle"),
    ("Caps Lock", "grp:caps_toggle"),
    ("No shortcut", ""),
]


class InputPage(Page):
    key, title, icon = "input", "Keyboard and Mouse", "input-keyboard-symbolic"

    def build(self):
        s = self.win.store

        def setter(opt):
            return lambda v: s.set(opt, v)

        g = Adw.PreferencesGroup(title="Keyboard layout")
        self.layouts = xkb_layouts()
        codes = {c for c, _ in self.layouts}
        layout = Adw.EntryRow(title="Layouts (comma separated, e.g. us,de)", show_apply_button=True,
                              text=s.current("input:kb_layout", "us"))
        layout.connect("apply", lambda r: self.set_layout(r, codes))
        g.add(layout)
        variant = Adw.EntryRow(title="Variants (e.g. ,nodeadkeys — leave blank for none)", show_apply_button=True,
                               text=s.current("input:kb_variant", "") or "")
        variant.connect("apply", lambda r: s.set("input:kb_variant", r.get_text().strip()))
        g.add(variant)
        browse = Adw.ExpanderRow(title="Layout codes", subtitle="Browse available layout codes")
        lst = Gtk.Label(label="\n".join(f"{c:<8} {d}" for c, d in self.layouts), xalign=0, selectable=True,
                        margin_start=12, margin_end=12, margin_top=6, margin_bottom=6)
        lst.add_css_class("monospace")
        lst.set_ellipsize(Pango.EllipsizeMode.NONE)
        browse.add_row(lst)
        g.add(browse)

        opts = (s.current("input:kb_options", "") or "").split(",")
        self.caps = next((v for _l, v in CAPS_OPTIONS if v and set(v.split(",")) <= set(opts)), "")
        self.switch = next((v for _l, v in SWITCH_OPTIONS if v and v in opts), "")
        self.extra = [o for o in opts if o and o not in self.caps.split(",") and o != self.switch]
        g.add(combo_row("Caps Lock key acts as", None, [l for l, _ in CAPS_OPTIONS], self.caps,
                        lambda v: self.set_opts(caps=v), [v for _, v in CAPS_OPTIONS]))
        g.add(combo_row("Switch layouts with", "Only matters with more than one layout",
                        [l for l, _ in SWITCH_OPTIONS], self.switch, lambda v: self.set_opts(switch=v),
                        [v for _, v in SWITCH_OPTIONS]))
        self.add(g)

        g = Adw.PreferencesGroup(title="Typing")
        g.add(scale_row("Key repeat rate", "Characters per second while holding a key", 10, 80, 1,
                        s.current("input:repeat_rate", 40), 0, setter("input:repeat_rate")))
        g.add(scale_row("Key repeat delay", "Milliseconds before repeating starts", 150, 800, 10,
                        s.current("input:repeat_delay", 250), 0, setter("input:repeat_delay")))
        g.add(switch_row("Num Lock on at startup", None, s.current("input:numlock_by_default", True),
                         setter("input:numlock_by_default")))
        self.add(g)

        g = Adw.PreferencesGroup(title="Mouse")
        g.add(scale_row("Pointer speed", "0 is default", -1.0, 1.0, 0.05, s.current("input:sensitivity", 0.0), 2,
                        setter("input:sensitivity")))
        g.add(combo_row("Acceleration", None, ["Default", "Adaptive", "Flat (no acceleration)"],
                        s.current("input:accel_profile", "") or "", setter("input:accel_profile"),
                        ["", "adaptive", "flat"]))
        g.add(switch_row("Natural scrolling", "Content moves with your fingers", s.current("input:natural_scroll", False),
                         setter("input:natural_scroll")))
        g.add(scale_row("Scroll speed", None, 0.1, 3.0, 0.05, s.current("input:scroll_factor", 1.0), 2,
                        setter("input:scroll_factor")))
        g.add(switch_row("Left-handed", "Swap left and right buttons", s.current("input:left_handed", False),
                         setter("input:left_handed")))
        g.add(combo_row("Focus follows mouse", None,
                        ["Off (click to focus)", "Always", "Only on click, but scroll the hovered window",
                         "Keyboard stays, mouse focus separate"],
                        s.current("input:follow_mouse", 1), setter("input:follow_mouse"), [0, 1, 2, 3]))
        self.add(g)

        mice = (hypr_json("devices") or {}).get("mice", [])
        if not any("touchpad" in m.get("name", "").lower() for m in mice):
            self.add_reset()
            return
        g = Adw.PreferencesGroup(title="Touchpad")
        g.add(switch_row("Touchpad enabled", None, True,
                         lambda v: run_async(["omarchy", "toggle", "touchpad", "on" if v else "off"])))
        g.add(switch_row("Natural scrolling", None, s.current("input:touchpad:natural_scroll", False),
                         setter("input:touchpad:natural_scroll")))
        g.add(switch_row("Tap to click", None, s.current("input:touchpad:tap_to_click", True),
                         setter("input:touchpad:tap_to_click")))
        g.add(switch_row("Two-finger click for right-click", "Instead of clicking the lower-right corner",
                         s.current("input:touchpad:clickfinger_behavior", True),
                         setter("input:touchpad:clickfinger_behavior")))
        g.add(switch_row("Disable while typing", None, s.current("input:touchpad:disable_while_typing", True),
                         setter("input:touchpad:disable_while_typing")))
        g.add(combo_row("Drag with fingers", None, ["Off", "Three fingers", "Four fingers"],
                        s.current("input:touchpad:drag_3fg", 0), setter("input:touchpad:drag_3fg"), [0, 1, 2]))
        g.add(scale_row("Scroll speed", None, 0.1, 2.0, 0.05, s.current("input:touchpad:scroll_factor", 0.4), 2,
                        setter("input:touchpad:scroll_factor")))
        self.add(g)
        self.add_reset()

    def add_reset(self):
        self.add(reset_group(self.win, "Restore default keyboard and mouse settings?",
                             "Layouts, Caps Lock, key repeat, pointer, scrolling and touchpad settings made here "
                             "are removed. Your own ~/.config/hypr/input.lua still applies.", self.reset))

    def set_layout(self, row, codes):
        text = row.get_text().replace(" ", "")
        bad = [c for c in text.split(",") if c and c not in codes]
        if bad or not text:
            self.win.toast(f"Unknown layout: {', '.join(bad) or '(empty)'}")
            return
        store = self.win.store
        variants = store.current("input:kb_variant", "") or ""
        text, variants, moved = latin_first(text, variants)
        if moved:
            row.set_text(text)
            store.values["input:kb_variant"] = variants
            self.win.toast(f"Shortcuts need a Latin layout first, so layouts are now {text}")
        store.set("input:kb_layout", text)
        if "," in text and not self.switch:
            self.set_opts(switch="grp:alts_toggle")
            self.win.toast("Switch layouts with Left Alt + Right Alt")

    def set_opts(self, caps=None, switch=None):
        if caps is not None:
            self.caps = caps
        if switch is not None:
            self.switch = switch
        opts = [o for o in self.caps.split(",") if o] + ([self.switch] if self.switch else []) + self.extra
        self.win.store.set("input:kb_options", ",".join(opts))

    def reset(self, done=None):
        self.win.store.reset(prefix="input:")
        self.win.store.schedule_save(after=lambda: (self.rebuild(), done and done()))


# ---------------------------------------------------------------- fonts and text


class TextPage(Page):
    key, title, icon = "text", "Fonts and Text", "preferences-desktop-font-symbolic"

    def build(self):
        g = Adw.PreferencesGroup(title="Fonts")
        fonts = [f for f in run(["omarchy", "font", "list"]).splitlines() if f.strip()]
        self.fonts = fonts
        g.add(combo_row("Monospace font", "Used by terminals, the bar and editors", fonts,
                        run(["omarchy", "font", "current"]), self.on_font))

        row = Adw.ActionRow(title="Interface font", subtitle="Used by GTK apps (kept across theme changes)")
        btn = Gtk.FontDialogButton(dialog=Gtk.FontDialog(), valign=Gtk.Align.CENTER, use_font=True)
        btn.set_font_desc(Pango.FontDescription.from_string(gsetting("font-name") or "Sans 11"))
        btn.connect("notify::font-desc", lambda b, _p: self.set_ui_font(b.get_font_desc().to_string()))
        row.add_suffix(btn)
        g.add(row)

        size = 12
        for line in run(["omarchy", "display", "text", "size"]).splitlines():
            if line.startswith("text size:"):
                try:
                    size = int(line.split(":")[1].split()[0])
                except Exception:
                    pass
        self._size_timer = None
        # omarchy display text size accepts 9–20 px
        self.size = spin_row("Text size", "Scales text in the shell, GTK apps and terminals (default 12)",
                             9, 20, 1, min(20, max(9, size)), self.on_size)
        g.add(self.size)
        self.add(g)
        self.add(reset_group(self.win, "Restore default fonts?",
                             f"Font goes back to {DEFAULT_FONT}, text size to 12px and the interface font to "
                             "the system default.", self.reset))

    def on_font(self, name):
        self.win.busy(f"Setting font {name}…")
        run_async(["omarchy", "font", "set", name],
                  lambda c, o, e: self.win.toast(f"Font set to {name}" if c == 0 else e.strip()[:120]))

    def set_ui_font(self, desc):
        self.win.store.pins["font_name"] = desc
        apply_pins(self.win.store)

    def on_size(self, _v):
        if self._size_timer:
            GLib.source_remove(self._size_timer)

        def apply():
            self._size_timer = None
            v = str(int(self.size.get_value()))
            run_async(["omarchy", "display", "text", "size", v],
                      lambda c, o, e: self.win.toast(f"Text size {v}px" if c == 0 else e.strip()[:120]))
            return False

        self._size_timer = GLib.timeout_add(600, apply)

    def reset(self, done=None):
        self.win.store.pins["font_name"] = None
        apply_pins(self.win.store)
        cmds = [["omarchy", "font", "set", DEFAULT_FONT], ["omarchy", "display", "text", "size", "reset"],
                ["gsettings", "reset", "org.gnome.desktop.interface", "font-name"]]
        self.win.busy("Restoring fonts…")

        def finished(failures):
            self.win.toast(f"Some resets failed: {failures[0]}" if failures else "Fonts restored")
            self.rebuild()
            done and done()

        run_chain(cmds, finished)


# ---------------------------------------------------------------- cursor


class CursorPage(Page):
    key, title, icon = "cursor", "Cursor", "input-mouse-symbolic"

    def build(self):
        store = self.win.store
        g = Adw.PreferencesGroup(title="Cursor", description="Apps opened after a change pick it up fully.")
        themes = sorted({p.parent.name for base in (Path("/usr/share/icons"), HOME / ".local/share/icons",
                                                     HOME / ".icons") if base.is_dir()
                         for p in base.glob("*/cursors")})
        cur_theme = store.cursor.get("theme") or gsetting("cursor-theme")
        g.add(combo_row("Cursor theme", None, themes, cur_theme, lambda v: self.set_cursor(theme=v)))
        sizes = [16, 24, 32, 48, 64]
        try:
            cur_size = int(store.cursor.get("size") or gsetting("cursor-size") or 24)
        except ValueError:
            cur_size = 24
        g.add(combo_row("Cursor size", None, [str(s) for s in sizes], cur_size, lambda v: self.set_cursor(size=v),
                        sizes))
        g.add(scale_row("Hide when idle", "Seconds without movement (0 = never)", 0, 30, 1,
                        store.current("cursor:inactive_timeout", 0), 0,
                        lambda v: store.set("cursor:inactive_timeout", float(v))))
        g.add(switch_row("Hide while typing", None, store.current("cursor:hide_on_key_press", True),
                         lambda v: store.set("cursor:hide_on_key_press", v)))
        g.add(switch_row("Move cursor to the focused workspace", "When switching workspaces",
                         store.current("cursor:warp_on_change_workspace", 1),
                         lambda v: store.set("cursor:warp_on_change_workspace", 1 if v else 0)))
        self.add(g)
        self.add(reset_group(self.win, "Restore the default cursor?",
                             "Cursor theme, size and hiding go back to the system defaults.", self.reset))

    def set_cursor(self, theme=None, size=None):
        store = self.win.store
        if theme:
            store.cursor["theme"] = theme
            run_async(["gsettings", "set", "org.gnome.desktop.interface", "cursor-theme", theme])
        if size:
            store.cursor["size"] = size
            run_async(["gsettings", "set", "org.gnome.desktop.interface", "cursor-size", str(size)])
        run_async(["hyprctl", "setcursor", store.cursor.get("theme") or "default", str(store.cursor.get("size") or 24)])
        store.schedule_save()

    def reset(self, done=None):
        store = self.win.store
        store.cursor = {}
        store.reset(prefix="cursor:")
        cmds = [["gsettings", "reset", "org.gnome.desktop.interface", "cursor-theme"],
                ["gsettings", "reset", "org.gnome.desktop.interface", "cursor-size"],
                ["hyprctl", "setcursor", "default", "24"]]

        def finished(_f):
            store.schedule_save(after=lambda: (self.rebuild(), self.win.toast("Cursor restored"), done and done()))

        run_chain(cmds, finished)


# ---------------------------------------------------------------- bar


SECTIONS = ["left", "center", "right"]


class BarPage(Page):
    key, title, icon = "bar", "Bar", "view-app-grid-symbolic"
    POSITIONS = ["top", "bottom", "left", "right"]

    def build(self):
        shell = read_shell()
        bar = shell.get("bar", {})

        g = Adw.PreferencesGroup(title="Bar")
        g.add(combo_row("Position", None, [p.title() for p in self.POSITIONS], bar.get("position", "top"),
                        lambda v: self.cmd(["omarchy", "bar", "position", v]), self.POSITIONS))
        g.add(switch_row("Transparent", None, bar.get("transparent", False),
                         lambda v: self.cmd(["omarchy", "bar", "transparent", "true" if v else "false"])))
        vis = Adw.ButtonRow(title="Show / hide bar")
        vis.connect("activated", lambda _r: self.cmd(["omarchy", "toggle", "bar"]))
        g.add(vis)
        self.add(g)

        clock = self.find_widget(shell, "omarchy.clock") or {}
        g = Adw.PreferencesGroup(title="Clock",
                                 description="Qt date format: HH:mm is 24-hour, h:mm AP is 12-hour, dddd is the "
                                             "weekday, d MMM the date.")
        for key, title in (("format", "Format"), ("formatAlt", "Format when clicked")):
            e = Adw.EntryRow(title=title, text=clock.get(key, ""), show_apply_button=True)
            e.connect("apply", lambda r, k=key: self.cmd(["omarchy", "bar", "set", "omarchy.clock", k,
                                                           r.get_text()]))
            g.add(e)
        presets = Adw.ActionRow(title="Presets")
        box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        for label, fmt in (("Weekday 24h", "dddd HH:mm"), ("24h", "HH:mm"), ("12h", "h:mm AP"),
                           ("Date + time", "d MMM HH:mm")):
            b = Gtk.Button(label=label)
            b.connect("clicked", lambda _b, f=fmt: (self.cmd(["omarchy", "bar", "set", "omarchy.clock", "format", f]),
                                                     self.rebuild(delay=600)))
            box.append(b)
        presets.add_suffix(box)
        g.add(presets)
        self.add(g)

        self.widgets = {}
        for sec in SECTIONS:
            wg = Adw.PreferencesGroup(title=f"{sec.title()} widgets")
            self.widgets[sec] = wg
            self.add(wg)
        add = Adw.PreferencesGroup(title="Add a widget")
        self.add_row = Adw.ComboRow(title="Widget")
        self.add_section = Adw.ComboRow(title="Section", model=Gtk.StringList.new([s.title() for s in SECTIONS]))
        btn = Adw.ButtonRow(title="Add to bar", start_icon_name="list-add-symbolic")
        btn.connect("activated", lambda _r: self.add_widget())
        add.add(self.add_row)
        add.add(self.add_section)
        add.add(btn)
        self.add(add)
        self.populate_widgets()

        self.add(reset_group(self.win, "Restore default bar settings?",
                             "Position, transparency, visibility and clock format go back to Omarchy's defaults. "
                             "Your widget layout is kept.", self.reset))
        self.add(reset_group(self.win, "Restore default bar widgets?",
                             "Widgets you added, removed or moved go back to Omarchy's default layout.",
                             lambda: run_chain([["omarchy", "bar", "defaults"]], self.after_widgets),
                             label="Restore default bar widgets"))

    @staticmethod
    def entry_id(e):
        return e.get("id") if isinstance(e, dict) else str(e)

    def find_widget(self, shell, wid):
        for sec in SECTIONS:
            for e in shell.get("bar", {}).get("layout", {}).get(sec, []):
                if self.entry_id(e) == wid and isinstance(e, dict):
                    return e
        return None

    def populate_widgets(self):
        layout = read_shell().get("bar", {}).get("layout", {})
        try:
            catalog = {p["id"]: p for p in json.loads(run(["omarchy", "plugin", "list", "--json"]))
                       if "bar-widget" in p.get("kinds", [])}
        except Exception:
            catalog = {}
        self.catalog = catalog
        on_bar = set()
        for sec in SECTIONS:
            g = self.widgets[sec]
            clear_group(g)
            items = [self.entry_id(e) for e in layout.get(sec, [])]
            if not items:
                group_add(g, Adw.ActionRow(title="Empty"))
            for idx, wid in enumerate(items):
                on_bar.add(wid)
                row = Adw.ActionRow(title=catalog.get(wid, {}).get("name", wid), subtitle=wid)
                box = Gtk.Box(spacing=2, valign=Gtk.Align.CENTER)
                up = icon_button("go-up-symbolic", "Move up",
                                 lambda w=wid, s=sec, i=idx: self.move(w, s, i - 1))
                up.set_sensitive(idx > 0)
                down = icon_button("go-down-symbolic", "Move down",
                                   lambda w=wid, s=sec, i=idx: self.move(w, s, i + 1))
                down.set_sensitive(idx < len(items) - 1)
                box.append(up)
                box.append(down)
                menu = Gtk.MenuButton(icon_name="view-more-symbolic", tooltip_text="Move to section")
                menu.add_css_class("flat")
                pop = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=4, margin_bottom=4)
                for target in SECTIONS:
                    if target == sec:
                        continue
                    b = Gtk.Button(label=f"Move to {target}")
                    b.add_css_class("flat")
                    b.connect("clicked", lambda _b, w=wid, t=target: self.move(w, t, None))
                    pop.append(b)
                popover = Gtk.Popover(child=pop)
                menu.set_popover(popover)
                box.append(menu)
                if catalog.get(wid, {}).get("canDisable", True):
                    box.append(icon_button("list-remove-symbolic", "Remove from bar", lambda w=wid: self.remove(w)))
                row.add_suffix(box)
                group_add(g, row)
        self.available = sorted((p["id"] for p in catalog.values() if p["id"] not in on_bar),
                                key=lambda i: catalog[i].get("name", i))
        self.add_row.set_model(Gtk.StringList.new([catalog[i].get("name", i) for i in self.available]
                                                  or ["Every widget is on the bar"]))
        self.add_row.set_sensitive(bool(self.available))

    def widget_cmd(self, argv):
        run_chain([argv], lambda f: (self.win.toast(f[0]) if f else None, self.populate_widgets()))

    def move(self, wid, section, index):
        argv = ["omarchy", "bar", "move", wid, "--section", section]
        if index is not None:
            argv += ["--index", str(index)]
        self.widget_cmd(argv)

    def remove(self, wid):
        kinds = self.catalog.get(wid, {}).get("kinds", ["bar-widget"])
        if set(kinds) - {"bar-widget"}:
            # This plugin does more than draw a widget (e.g. omarchy.menu is also the Omarchy
            # menu itself), so disabling it would break more than the bar: only take it off the bar.
            data = read_shell()
            layout = data.get("bar", {}).get("layout", {})
            for sec in SECTIONS:
                if isinstance(layout.get(sec), list):
                    layout[sec] = [e for e in layout[sec] if self.entry_id(e) != wid]
            write_shell(data)
            self.populate_widgets()
            return
        self.widget_cmd(["omarchy", "plugin", "disable", wid])

    def add_widget(self):
        if not self.available:
            return
        wid = self.available[self.add_row.get_selected()]
        sec = SECTIONS[self.add_section.get_selected()]
        run_chain([["omarchy", "plugin", "enable", wid], ["omarchy", "bar", "put", wid, "--section", sec]],
                  lambda f: (self.win.toast(f[0]) if f else self.win.toast("Widget added"), self.populate_widgets()))

    def cmd(self, argv):
        run_async(argv, lambda c, o, e: self.win.toast((o if c == 0 else e).strip()[:120] or "Done"))

    def after_widgets(self, failures):
        self.win.toast(f"Reset failed: {failures[0]}" if failures else "Bar widgets restored")
        self.populate_widgets()

    def reset(self, done=None):
        d = shell_defaults().get("bar", {})
        clock = self.find_widget(shell_defaults(), "omarchy.clock") or {}
        cmds = [["omarchy", "bar", "position", d.get("position", "top")],
                ["omarchy", "bar", "transparent", "true" if d.get("transparent") else "false"],
                # `omarchy toggle bar` drives a bar-off flag: "off" removes it, which shows the bar.
                ["omarchy", "toggle", "bar", "off"]]
        for k in ("format", "formatAlt"):
            if k in clock:
                cmds.append(["omarchy", "bar", "set", "omarchy.clock", k, clock[k]])

        def finished(failures):
            self.win.toast(f"Reset failed: {failures[0]}" if failures else "Bar restored")
            self.rebuild()
            done and done()

        run_chain(cmds, finished)


# ---------------------------------------------------------------- power and notifications


class PowerPage(Page):
    key, title, icon = "power", "Power and Notifications", "preferences-system-notifications-symbolic"

    def build(self):
        g = Adw.PreferencesGroup(title="Notifications")
        g.add(switch_row("Do not disturb", "Silence notification popups",
                         run(["omarchy-shell", "notifications", "isDnd"]) == "on",
                         lambda v: run_async(["omarchy-shell", "notifications", "setDnd", "on" if v else "off"])))
        self.add(g)

        # Missing values mean Omarchy's defaults, not 0.
        idle = {**shell_defaults().get("idle", {}), **read_shell().get("idle", {})}
        g = Adw.PreferencesGroup(title="Idle", description="Times in minutes. To stop idle locking and the "
                                                           "screensaver altogether, use Keep awake.")
        try:
            # "enabled" is true when stay-awake is on (see omarchy-toggle-idle's print_status).
            awake = bool(json.loads(run(["omarchy", "toggle", "idle", "status"])).get("enabled", False))
        except Exception:
            awake = False
        g.add(switch_row("Keep awake", "Never start the screensaver or lock on idle", awake,
                         lambda v: run_async(["omarchy", "toggle", "idle", "stay-awake" if v else "allow-idle"])))
        # Omarchy treats 0 as "right away", not "never", so the minimum is half a minute.
        for key, title in (("screensaver", "Start screensaver after"), ("lock", "Lock screen after")):
            g.add(spin_row(title, None, 0.5, 240, 0.5, max(30, int(idle.get(key) or 0)) / 60,
                           lambda v, k=key: self.set_idle(k, int(round(v * 60))), digits=1))
        g.add(self.flag_row("Screensaver", "Allow the screensaver to run", "screensaver-off",
                            ["omarchy", "toggle", "screensaver"]))
        g.add(self.flag_row("Suspend in system menu", None, "suspend-off", ["omarchy", "toggle", "suspend"]))
        self.add(g)
        self.add(reset_group(self.win, "Restore default power and notification settings?",
                             "Do not disturb off, idle allowed, screensaver and suspend available, and default "
                             "screensaver and lock timeouts.", self.reset))

    def flag_row(self, title, subtitle, flag, toggle_cmd):
        off = run_ok(["omarchy", "toggle", "enabled", flag])

        def set_on(on):
            # The omarchy command flips the flag, so only run it when the state differs.
            if run_ok(["omarchy", "toggle", "enabled", flag]) == on:
                run_async(toggle_cmd)

        return switch_row(title, subtitle, not off, set_on)

    def set_idle(self, key, seconds):
        data = read_shell()
        if not data:
            self.win.toast("Couldn't read ~/.config/omarchy/shell.json, so the idle time wasn't saved")
            return
        data.setdefault("idle", {})[key] = max(30, seconds)
        write_shell(data)

    def reset(self, done=None):
        idle = shell_defaults().get("idle", {})
        for key in ("screensaver", "lock"):
            if key in idle:
                self.set_idle(key, idle[key])
        cmds = [["omarchy-shell", "notifications", "setDnd", "off"], ["omarchy", "toggle", "idle", "allow-idle"]]
        for flag, cmd in (("screensaver-off", ["omarchy", "toggle", "screensaver"]),
                          ("suspend-off", ["omarchy", "toggle", "suspend"])):
            if run_ok(["omarchy", "toggle", "enabled", flag]):
                cmds.append(cmd)

        def finished(failures):
            self.win.toast(f"Reset failed: {failures[0]}" if failures else "Power and notifications restored")
            self.rebuild()
            done and done()

        run_chain(cmds, finished)


# ---------------------------------------------------------------- default apps


TERMINALS = [("Alacritty", "alacritty", "alacritty"), ("Foot", "foot", "foot"),
             ("Ghostty", "ghostty", "ghostty"), ("Kitty", "kitty", "kitty")]
BROWSERS = [("Chromium", "chromium", "chromium.desktop"), ("Chrome", "chrome", "google-chrome.desktop"),
            ("Brave", "brave", "brave-browser.desktop"), ("Brave Origin", "brave-origin", "brave-origin.desktop"),
            ("Edge", "edge", "microsoft-edge.desktop"), ("Firefox", "firefox", "firefox.desktop"),
            ("Zen", "zen", "zen.desktop")]
EDITORS = [("VS Code", "code", "code"), ("Cursor", "cursor", "cursor"), ("Zed", "zed", "zeditor"),
           ("Sublime Text", "sublime_text", "subl"), ("Helix", "helix", "helix"), ("Vim", "vim", "vim"),
           ("Emacs", "emacs", "emacs"), ("Neovim", "nvim", "nvim")]


def desktop_exists(desktop_id):
    dirs = [HOME / ".local/share/applications", Path("/usr/share/applications"),
            Path("/var/lib/flatpak/exports/share/applications")]
    return any((d / desktop_id).exists() for d in dirs)


class AppsPage(Page):
    key, title, icon = "apps", "Default Apps", "applications-system-symbolic"

    def build(self):
        g = Adw.PreferencesGroup(title="Default apps",
                                 description="Used by Omarchy's shortcuts (Super + Enter, Super + Shift + B, …) and "
                                             "when opening links and files. Only installed apps are listed.")
        for title, kind, options, installed in (
                ("Terminal", "terminal", TERMINALS, lambda b: shutil.which(b)),
                ("Web browser", "browser", BROWSERS, desktop_exists),
                ("Editor", "editor", EDITORS, lambda b: shutil.which(b) or (b == "helix" and shutil.which("hx")))):
            avail = [(label, val) for label, val, probe in options if installed(probe)]
            current = run(["omarchy", "default", kind])
            if current and current not in [v for _, v in avail]:
                avail.append((current, current))
            if not avail:
                g.add(Adw.ActionRow(title=title, subtitle="None of the supported apps are installed"))
                continue
            g.add(combo_row(title, None, [l for l, _ in avail], current,
                            lambda v, k=kind: run_async(["omarchy", "default", k, v],
                                                        lambda c, o, e: self.win.toast(
                                                            f"Default {k} set" if c == 0 else e.strip()[:120])),
                            [v for _, v in avail]))
        self.add(g)
        g = Adw.PreferencesGroup(description="Install another terminal from the Omarchy menu: Install › Terminal. "
                                             "Default apps have no factory setting, so Restore all leaves them alone.")
        self.add(g)
