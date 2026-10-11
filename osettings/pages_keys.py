"""Keybindings and autostart pages."""

import re

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .binds import (bare_ok, canonical, group_title, key_count, keys_from_event, normalize, parse_default_binds,
                    pretty, siblings)
from .core import (HYPR_DIR, OMARCHY_PATH, Page, clear_group, group_add, icon_button, keycap, reset_group, run,
                   run_async, spawn_detached)
from .store import CAPTURE_SUBMAP, require_state


def app_choices():
    apps = [a for a in Gio.AppInfo.get_all() if a.should_show() and a.get_id()]
    apps.sort(key=lambda a: a.get_display_name().lower())
    return apps


def enter_capture():
    run_async(["hyprctl", "dispatch", f'hl.dsp.submap("{CAPTURE_SUBMAP}")'])


def leave_capture(wait=False):
    """Leave the recording submap. `wait` blocks until done, for when the app is about to quit."""
    cmd = ["hyprctl", "dispatch", 'hl.dsp.submap("reset")']
    run(cmd) if wait else run_async(cmd)


def typed_keys(text):
    """A typed combination spelled the way recorded ones are: 'super shift r' -> 'SUPER + SHIFT + R'.
    Text without exactly one key comes back as typed, for set_keys to refuse (canonical would drop
    the extra keys)."""
    if key_count(text) != 1:
        return text.strip()
    keys = canonical(text)
    mods, _, key = keys.rpartition(" + ")
    if len(key) == 1:
        keys = f"{mods} + {key.upper()}" if mods else key.upper()
    return keys


# Keys that move focus or confirm in a dialog; without a modifier they are never recorded.
NAVIGATION = {"Tab", "ISO_Left_Tab", "space", "Return", "KP_Enter", "Escape", "Up", "Down", "Left", "Right"}
CTRL_MODS = Gdk.ModifierType.SUPER_MASK | Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK


class ShortcutDialog(Adw.Dialog):
    """Records a key combination. With `custom=True` it also asks what the shortcut runs."""

    def __init__(self, page, title, on_done, keys="", custom=None, ignore=None):
        super().__init__(title=title, content_width=520)
        self.page, self.on_done, self.keys, self.ignore = page, on_done, keys, ignore
        self.custom = custom
        tv = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.save = Gtk.Button(label="Save", sensitive=bool(keys))
        self.save.add_css_class("suggested-action")
        self.save.connect("clicked", lambda *_: self.finish())
        header.pack_end(self.save)
        tv.add_top_bar(header)

        page_ = Adw.PreferencesPage()
        # The pause needs the submap from the app's generated file; without it Hyprland
        # refuses the switch, so don't claim shortcuts are paused.
        self.pausing = require_state() == "loaded"
        g = Adw.PreferencesGroup(description=(
            "Press the new key combination. Your other shortcuts are paused while this window is open "
            "(Super + Escape resumes them)." if self.pausing else
            "Press the new key combination. Your other shortcuts are NOT paused, because the app's Hyprland "
            "config isn't loaded, so combinations Omarchy already uses will also do their usual thing."))
        self.shown = Gtk.Label(label=pretty(keys) if keys else "Waiting for keys…", margin_top=18, margin_bottom=6)
        self.shown.add_css_class("title-1")
        g.add(self.shown)
        self.conflict = Gtk.Label(label="", wrap=True, margin_bottom=6)
        self.conflict.add_css_class("warning")
        g.add(self.conflict)
        self.typed = Adw.EntryRow(title="Or type it (e.g. SUPER + SHIFT + R)", text=keys, show_apply_button=True)
        self.typed.connect("apply", lambda r: self.apply_typed())
        self._typed_seen = keys  # the field's text when last used, so Save can tell a fresh edit
        g.add(self.typed)
        page_.add(g)

        if custom is not None:
            g2 = Adw.PreferencesGroup(title="What it does")
            self.desc = Adw.EntryRow(title="Name", text=custom.get("description", ""))
            g2.add(self.desc)
            self.apps = app_choices()
            pick = Adw.ComboRow(title="Open an app", subtitle="Or type a command below",
                                model=Gtk.StringList.new(["—"] + [a.get_display_name() for a in self.apps]),
                                enable_search=True)
            pick.connect("notify::selected", self.on_app)
            g2.add(pick)
            self.command = Adw.EntryRow(title="Command", text=custom.get("command", ""))
            g2.add(self.command)
            self.launch = Adw.SwitchRow(title="Start as an app", subtitle="Runs it through uwsm-app like Omarchy's "
                                        "own app shortcuts; turn off for quick scripts",
                                        active=custom.get("launch", True))
            g2.add(self.launch)
            page_.add(g2)

        tv.set_content(page_)
        self.set_child(tv)
        keys_ctl = Gtk.EventControllerKey(propagation_phase=Gtk.PropagationPhase.CAPTURE)
        keys_ctl.connect("key-pressed", self.on_key)
        self.add_controller(keys_ctl)
        self.connect("closed", lambda *_: (self._cancel_timeout(), self.pausing and leave_capture()))
        self._timeout = None
        if self.pausing:
            self._timeout = GLib.timeout_add_seconds(60, self._timed_out)
            enter_capture()

    def _timed_out(self):
        # Safety limit: give the user their shortcuts back, and say so.
        self._timeout = None
        self.pausing = False
        leave_capture()
        self.conflict.set_label("Your shortcuts are active again after 60 seconds. Close and reopen this window "
                                "to record without them firing.")
        return False

    def _cancel_timeout(self):
        # A stale timer must not end the recording of a dialog opened after this one.
        if self._timeout:
            GLib.source_remove(self._timeout)
            self._timeout = None

    def on_app(self, row, _p):
        i = row.get_selected()
        if i > 0:
            app = self.apps[i - 1]
            self.command.set_text(app.get_id())
            self.launch.set_active(True)
            if not self.desc.get_text():
                self.desc.set_text(app.get_display_name())

    def on_key(self, _ctl, keyval, keycode, state):
        focus = self.get_root().get_focus() if self.get_root() else None
        held = state & CTRL_MODS
        if isinstance(focus, Gtk.Text) and not held:
            return False  # typing or moving the cursor in a text field (arrows, Home, F-keys too)
        if not held and Gdk.keyval_name(keyval) in NAVIGATION:
            return False  # moving focus between buttons
        keys = keys_from_event(keycode, state)
        if not keys:
            return False
        self.set_keys(keys)
        return True

    def apply_typed(self):
        """Use the typed combination. False when it was refused (the reason is shown)."""
        self._typed_seen = self.typed.get_text().strip()
        return self.set_keys(typed_keys(self._typed_seen))

    def set_keys(self, keys):
        """Take `keys` as the new shortcut. False when refused (the reason is shown)."""
        if not keys:
            return False
        if key_count(keys) != 1:
            self.conflict.set_label(f"“{keys}” needs exactly one key besides Super, Shift, Ctrl and Alt, "
                                    "e.g. SUPER + SHIFT + R.")
            return False
        if not bare_ok(keys):
            self.conflict.set_label(f"{pretty(keys)} on its own would stop that key working in every app. "
                                    "Hold Super, Ctrl or Alt with it.")
            return False
        # Reuse the exact spelling of a binding we would replace (including code:N keys),
        # so unbinding it matches.
        clash = self.page.who_uses(keys, ignore=self.ignore)
        if clash:
            keys = clash["keys"]
            self.conflict.set_label(f"Already used by “{clash['description'] or clash['keys']}”. "
                                    "Saving moves the key to this shortcut.")
        else:
            self.conflict.set_label("")
        self.keys = keys
        self.shown.set_label(pretty(keys))
        self.save.set_sensitive(True)
        return True

    def finish(self):
        # Text typed since the field was last used wins over a recorded key, as it's the latest input.
        typed = self.typed.get_text().strip()
        if typed and typed != self._typed_seen and not self.apply_typed():
            return
        if not self.keys:
            return
        result = {"keys": self.keys}
        if self.custom is not None:
            cmd = self.command.get_text().strip()
            if not cmd:
                self.page.win.toast("Choose an app or type a command")
                return
            result.update(command=cmd, description=self.desc.get_text().strip() or cmd,
                          launch=self.launch.get_active(), enabled=True)
        self._cancel_timeout()
        self.close()
        self.on_done(result)


class KeysPage(Page):
    key, title, icon = "keys", "Keybindings", "preferences-desktop-keyboard-shortcuts-symbolic"

    def build(self):
        binds = self.win.store.binds
        owned = {normalize(c["keys"]) for c in binds["custom"]} | {normalize(r["new"]) for r in binds["rebinds"]}
        self.defaults = parse_default_binds(owned=owned, disabled_info=binds["disabled_info"])
        top = Adw.PreferencesGroup()
        box = Gtk.Box(spacing=8)
        self.search = Gtk.SearchEntry(placeholder_text="Search shortcuts", hexpand=True)
        self.search.connect("search-changed", lambda *_: self.filter())
        add = Gtk.Button(label="Add shortcut")
        add.add_css_class("suggested-action")
        add.connect("clicked", lambda *_: self.add_custom())
        box.append(self.search)
        box.append(add)
        top.add(box)
        self.add(top)

        self.custom_group = Adw.PreferencesGroup(title="Your shortcuts")
        self.add(self.custom_group)
        self.rows = []
        self.populate_custom()

        groups = {}
        for b in self.defaults:
            g = groups.get(b["group"])
            if not g:
                g = groups[b["group"]] = Adw.PreferencesGroup(title=group_title(b["group"]))
                if b["group"] == "other":
                    g.set_description("Made by Omarchy in loops or scripts, or by your own "
                                      "~/.config/hypr/bindings.lua. These can be turned off and on, not changed.")
            row = self.default_row(b)
            g.add(row)
            self.rows.append(row)
        for g in groups.values():
            self.add(g)
        self.add(reset_group(self.win, "Restore Omarchy's keybindings?",
                             "Removes every shortcut you added, changed or turned off here.", self.reset))

    # ------------------------------------------------------------ lookups

    def effective(self, ignore=None):
        """All active bindings: [{keys, description, kind, ref}]."""
        binds = self.win.store.binds
        disabled = set(binds["disabled"])
        moved = {rb["old"]: rb for rb in binds["rebinds"]}
        out = []
        for b in self.defaults:
            if b["keys"] in disabled:
                continue
            keys = moved[b["keys"]]["new"] if b["keys"] in moved else b["keys"]
            out.append({"keys": keys, "description": b["description"], "kind": "default", "ref": b})
        for c in binds["custom"]:
            if c.get("enabled", True):
                out.append({"keys": c["keys"], "description": c.get("description", ""), "kind": "custom", "ref": c})
        skip = ignore if isinstance(ignore, list) else [ignore]
        return [e for e in out if not any(e["ref"] is s for s in skip)]

    def who_uses(self, keys, ignore=None):
        n = normalize(keys)
        return next((e for e in self.effective(ignore) if normalize(e["keys"]) == n), None)

    # ------------------------------------------------------------ rows

    def default_row(self, b):
        binds = self.win.store.binds
        rb = next((r for r in binds["rebinds"] if r["old"] == b["keys"]), None)
        off = b["keys"] in binds["disabled"]
        row = Adw.ActionRow(title=GLib.markup_escape_text(b["description"] or b["keys"]))
        if off:
            row.set_subtitle("Turned off")
            row.add_css_class("dim-label")
        elif rb:
            row.set_subtitle(f"Changed from {pretty(b['keys'])}")
        row.add_suffix(keycap(pretty(rb["new"] if rb else b["keys"])))
        row.search_text = f"{b['description']} {b['keys']} {pretty(b['keys'])} {rb['new'] if rb else ''}".lower()
        if b["line"] or b["group"] == "other":
            menu = Gtk.MenuButton(icon_name="view-more-symbolic", valign=Gtk.Align.CENTER)
            menu.add_css_class("flat")
            menu.set_create_popup_func(lambda m, b=b: m.set_popover(self.menu_for(b)))
            row.add_suffix(menu)
        return row

    def menu_for(self, b):
        binds = self.win.store.binds
        rb = next((r for r in binds["rebinds"] if r["old"] == b["keys"]), None)
        off = b["keys"] in binds["disabled"]
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=4, margin_bottom=4)
        pop = Gtk.Popover(child=box)

        def item(label, fn):
            btn = Gtk.Button(label=label)
            btn.add_css_class("flat")
            btn.connect("clicked", lambda *_: (pop.popdown(), fn()))
            box.append(btn)

        group = siblings(self.defaults, b)
        others = [g["description"] for g in group if g is not b]
        also = f" (also {', '.join(others)})" if others else ""
        if all(g["rebindable"] for g in group) and b["line"] and not off:
            item(f"Change shortcut…{also}", lambda: self.change_default(b))
        if rb:
            item(f"Restore Omarchy's shortcut{also}", lambda: self.restore_default(b))
        if off:
            item(f"Turn on{also}", lambda: self.set_disabled(b, False))
        else:
            item(f"Turn off{also}", lambda: self.set_disabled(b, True))
        return pop

    def populate_custom(self):
        clear_group(self.custom_group)
        custom = self.win.store.binds["custom"]
        if not custom:
            group_add(self.custom_group, Adw.ActionRow(title="No shortcuts of your own yet",
                                                       subtitle="Use Add shortcut to make one"))
        for c in custom:
            row = Adw.ActionRow(title=GLib.markup_escape_text(c.get("description") or c["command"]),
                                subtitle=GLib.markup_escape_text(c["command"]))
            row.search_text = f"{c.get('description', '')} {c['command']} {c['keys']} {pretty(c['keys'])}".lower()
            row.add_suffix(keycap(pretty(c["keys"])))
            sw = Gtk.Switch(active=c.get("enabled", True), valign=Gtk.Align.CENTER)
            sw.connect("notify::active", lambda s, _p, c=c: self.toggle_custom(c, s.get_active()))
            row.add_suffix(sw)
            row.add_suffix(icon_button("document-edit-symbolic", "Edit", lambda c=c: self.edit_custom(c)))
            row.add_suffix(icon_button("user-trash-symbolic", "Delete", lambda c=c: self.delete_custom(c)))
            group_add(self.custom_group, row)
            self.rows.append(row)

    def filter(self):
        q = self.search.get_text().strip().lower()
        for row in self.rows:
            if row.get_parent() is not None:
                row.set_visible(not q or all(w in getattr(row, "search_text", "") for w in q.split()))

    # ------------------------------------------------------------ actions

    def saved(self, message):
        self.win.store.schedule_save(after=lambda: self.win.toast(message))
        self.rebuild()

    def take_over(self, keys, ignore=None):
        """Turn off whatever shortcut uses `keys` now, so the page shows what Hyprland will do.

        The Lua side unbinds the key either way; without this a displaced Omarchy shortcut
        would still look active, and later clash checks would point at the wrong one."""
        clash = self.who_uses(keys, ignore)
        if not clash:
            return None
        if clash["kind"] == "custom":
            clash["ref"]["enabled"] = False
        else:
            self.turn_off_key(clash["ref"])
        self.win.toast(f"“{clash['description'] or clash['keys']}” was turned off: its key is used now")
        return clash

    def turn_off_key(self, b):
        """Turn off `b` and every Omarchy binding sharing its key (Hyprland unbinds keys whole)."""
        binds = self.win.store.binds
        group = siblings(self.defaults, b)
        binds["rebinds"] = [r for r in binds["rebinds"] if r["old"] != b["keys"]]
        if b["keys"] not in binds["disabled"]:
            binds["disabled"].append(b["keys"])
        binds["disabled_info"][b["keys"]] = " / ".join(g["description"] for g in group)

    def key_taken(self, b):
        """Refuse to bring `b` back on its original key while another shortcut uses it."""
        clash = self.who_uses(b["keys"], ignore=siblings(self.defaults, b))
        if clash:
            self.win.toast(f"{pretty(b['keys'])} is used by “{clash['description'] or clash['keys']}”. "
                           "Change or turn that off first.")
        return clash

    def change_default(self, b):
        group = siblings(self.defaults, b)

        def done(res):
            binds = self.win.store.binds
            binds["rebinds"] = [r for r in binds["rebinds"] if r["old"] != b["keys"]]
            if normalize(res["keys"]) != normalize(b["keys"]):
                self.take_over(res["keys"], group)
                for g in group:  # bindings sharing the key move together
                    binds["rebinds"].append({"old": g["keys"], "new": res["keys"], "line": g["line"],
                                             "guard": g.get("guard"), "description": g["description"]})
            self.saved(f"“{b['description']}” is now {pretty(res['keys'])}")

        ShortcutDialog(self, f"Change “{b['description']}”", done, ignore=group).present(self.win)

    def restore_default(self, b):
        if self.key_taken(b):
            return
        binds = self.win.store.binds
        binds["rebinds"] = [r for r in binds["rebinds"] if r["old"] != b["keys"]]
        self.saved(f"“{b['description']}” is back on {pretty(b['keys'])}")

    def set_disabled(self, b, off):
        if not off and self.key_taken(b):
            return
        binds = self.win.store.binds
        if off:
            self.turn_off_key(b)
        else:
            binds["disabled"] = [k for k in binds["disabled"] if k != b["keys"]]
            binds["disabled_info"].pop(b["keys"], None)
        self.saved(f"“{b['description']}” turned {'off' if off else 'on'}")

    def add_custom(self):
        def done(res):
            self.take_over(res["keys"])
            self.win.store.binds["custom"].append(res)
            self.saved(f"Added {pretty(res['keys'])}")

        ShortcutDialog(self, "New shortcut", done, custom={}).present(self.win)

    def edit_custom(self, c):
        def done(res):
            self.take_over(res["keys"], c)
            c.update(res)
            self.saved("Shortcut updated")

        ShortcutDialog(self, "Edit shortcut", done, keys=c["keys"], custom=c, ignore=c).present(self.win)

    def toggle_custom(self, c, on):
        took = self.take_over(c["keys"], c) if on else None
        c["enabled"] = on
        self.win.store.schedule_save()
        if took:
            # The shortcut that lost its key now shows as off. Rebuilt from the main loop, not from
            # inside the switch's own signal, which the rebuild would remove.
            self.rebuild(delay=1)

    def delete_custom(self, c):
        self.win.store.binds["custom"].remove(c)
        self.saved("Shortcut deleted")

    def reset(self, done=None):
        self.win.store.binds = {"disabled": [], "rebinds": [], "custom": [], "disabled_info": {}}
        self.win.store.schedule_save(after=lambda: (self.win.toast("Keybindings restored"), done and done()))
        self.rebuild()


# ---------------------------------------------------------------- autostart


def lua_calls(path, pattern):
    try:
        text = path.read_text()
    except Exception:
        return []
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("--"):
            continue
        m = re.search(pattern, s)
        if m:
            out.append(m.group(1))
    return out


class AutostartPage(Page):
    key, title, icon = "autostart", "Autostart", "system-run-symbolic"

    def build(self):
        g = Adw.PreferencesGroup(title="Start at login",
                                 description="Apps and commands to run when you log in. Changes apply from the "
                                             "next login; use ▶ to start one now.")
        self.apps = app_choices()
        self.pick = Adw.ComboRow(title="Add an app", model=Gtk.StringList.new([a.get_display_name() for a in self.apps]),
                                 enable_search=True)
        self.pick.add_suffix(icon_button("list-add-symbolic", "Add", self.add_app))
        g.add(self.pick)
        self.cmd = Adw.EntryRow(title="Or add a command", show_apply_button=True)
        self.cmd.connect("apply", lambda r: self.add_item(r.get_text().strip(), False))
        g.add(self.cmd)
        self.add(g)

        self.list = Adw.PreferencesGroup(title="Your startup items")
        self.add(self.list)
        self.populate()

        user = lua_calls(HYPR_DIR / "autostart.lua", r'o\.(?:launch|exec)_on_start\(\s*"([^"]+)"')
        if user:
            g = Adw.PreferencesGroup(title="From ~/.config/hypr/autostart.lua",
                                     description="Edit that file to change these.")
            for c in user:
                g.add(Adw.ActionRow(title=GLib.markup_escape_text(c)))
            self.add(g)
        omarchy = lua_calls(OMARCHY_PATH / "default/hypr/autostart.lua", r'hl\.exec_cmd\((?:o\.launch\()?"([^"]+)"')
        if omarchy:
            g = Adw.PreferencesGroup(title="Started by Omarchy", description="Part of the desktop itself.")
            for c in omarchy:
                row = Adw.ActionRow(title=GLib.markup_escape_text(c))
                row.add_css_class("dim-label")
                g.add(row)
            self.add(g)
        self.add(reset_group(self.win, "Remove your startup items?",
                             "Everything added on this page stops starting at login. Apps already running keep "
                             "running.", self.reset, label="Remove all startup items"))

    def populate(self):
        clear_group(self.list)
        items = self.win.store.autostart
        if not items:
            group_add(self.list, Adw.ActionRow(title="Nothing added yet"))
        names = {a.get_id(): a.get_display_name() for a in self.apps}
        for a in items:
            title = names.get(a["command"], a["command"])
            row = Adw.ActionRow(title=GLib.markup_escape_text(title),
                                subtitle=GLib.markup_escape_text(a["command"] if title != a["command"] else
                                                                 ("App" if a.get("launch", True) else "Command")))
            row.add_suffix(icon_button("media-playback-start-symbolic", "Start now", lambda a=a: self.start(a)))
            sw = Gtk.Switch(active=a.get("enabled", True), valign=Gtk.Align.CENTER)
            sw.connect("notify::active", lambda s, _p, a=a: (a.update(enabled=s.get_active()),
                                                              self.win.store.schedule_save()))
            row.add_suffix(sw)
            row.add_suffix(icon_button("user-trash-symbolic", "Remove", lambda a=a: self.remove(a)))
            group_add(self.list, row)

    def add_app(self):
        if self.apps:
            self.add_item(self.apps[self.pick.get_selected()].get_id(), True)

    def add_item(self, command, launch):
        if not command:
            return
        if any(a["command"] == command for a in self.win.store.autostart):
            self.win.toast("Already in the list")
            return
        self.win.store.autostart.append({"command": command, "launch": launch, "enabled": True})
        self.win.store.schedule_save(after=lambda: self.win.toast("Will start at next login"))
        self.cmd.set_text("")
        self.populate()

    def start(self, a):
        cmd = ["uwsm-app", "--", a["command"]] if a.get("launch", True) else ["sh", "-c", a["command"]]
        self.win.toast("Started" if spawn_detached(cmd) else "Could not start it")

    def remove(self, a):
        self.win.store.autostart.remove(a)
        self.win.store.schedule_save()
        self.populate()

    def reset(self, done=None):
        self.win.store.autostart = []
        self.win.store.schedule_save(after=lambda: done and done())
        self.populate()
