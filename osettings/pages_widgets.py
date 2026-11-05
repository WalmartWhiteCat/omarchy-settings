"""Tools: the Desktop Notes shell plugin's look and place on screen, and Notebook's settings."""

import json
import re

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .core import (HOME, Page, combo_row, hypr_json, read_json, reset_group, rgba_to_hex, scale_row, spawn_detached,
                   spin_row, switch_row, write_atomic)

# The widget (~/.config/omarchy/plugins/sourced.desktop-notes) watches this file and applies changes
# live. It lives outside the plugin folder because saving there reloads the plugin.
NOTES_CONFIG = HOME / ".config/desktop-notes/config.json"
NOTES_PLUGIN = HOME / ".config/omarchy/plugins/sourced.desktop-notes"

NOTES_DEFAULTS = {"opacity": 78, "width": 300, "textScale": 100, "position": "bottom-right",
                  "marginX": 32, "marginY": 32, "title": "Reminders", "alwaysShowBells": False,
                  "rightClickWaitMs": 200, "monitor": "", "outline": False}
# key -> (lowest, highest); the widget clamps to the same ranges for hand-edited files.
NOTES_LIMITS = {"opacity": (0, 100), "width": (200, 800), "textScale": (70, 200),
                "marginX": (0, 1000), "marginY": (0, 1000), "rightClickWaitMs": (150, 600)}
# The card's heading is kept to one short line; empty hides it. The widget's titleMax matches.
NOTES_TITLE_MAX = 60
POSITIONS = [("Top left", "top-left"), ("Top", "top"), ("Top right", "top-right"),
             ("Left", "left"), ("Center", "center"), ("Right", "right"),
             ("Bottom left", "bottom-left"), ("Bottom", "bottom"), ("Bottom right", "bottom-right")]


class DebouncedWrites:
    """Slider and spinner steps are written on a 100 ms timer (`set`, `flush`). When the page goes away with that timer
    pending, the write happens then, at once: left to fire later it would write this page's stale values over whatever
    the file holds by then (seen in the tests, where it clobbered the next test's file)."""

    def hook_unrealize(self):
        if not getattr(self, "_unrealize_hooked", False):
            self._unrealize_hooked = True
            self.connect("unrealize", lambda *_: self.flush_pending())

    def flush_pending(self):
        if getattr(self, "_pending", None):
            GLib.source_remove(self._pending)
            self.flush()


def read_notes_config():
    """The widget's settings with defaults filled in and anything out of range or unknown dropped."""
    data = read_json(NOTES_CONFIG)
    cfg = dict(NOTES_DEFAULTS)
    if not isinstance(data, dict):
        return cfg
    for key, (lo, hi) in NOTES_LIMITS.items():
        v = data.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            cfg[key] = int(min(hi, max(lo, v)))
    if data.get("position") in dict((v, l) for l, v in POSITIONS):
        cfg["position"] = data["position"]
    if isinstance(data.get("title"), str):
        cfg["title"] = data["title"].strip()[:NOTES_TITLE_MAX]
    if isinstance(data.get("monitor"), str):
        cfg["monitor"] = data["monitor"].strip()
    for key in ("alwaysShowBells", "outline"):
        if isinstance(data.get(key), bool):
            cfg[key] = data[key]
    return cfg


def monitor_choices(monitors, chosen):
    """(label, value) for the Monitor drop-down: the main monitor (""), each connected one by its
    output name, and the chosen one if it isn't connected, so opening the page doesn't lose it."""
    choices = [("Main monitor", "")]
    for m in monitors if isinstance(monitors, list) else []:
        if isinstance(m, dict) and m.get("name"):
            choices.append((f"{m['name']} ({m.get('model') or m.get('description') or 'monitor'})", m["name"]))
    if chosen and chosen not in [v for _, v in choices]:
        choices.append((f"{chosen} (not connected)", chosen))
    return choices


def write_notes_config(cfg):
    NOTES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(NOTES_CONFIG, json.dumps(cfg, indent=2) + "\n")


def margin_axes(position):
    """Which distances apply: a centered side has no edge to measure from."""
    horizontal = position.endswith("left") or position.endswith("right")
    vertical = position.startswith("top") or position.startswith("bottom")
    return horizontal, vertical


class NotesPage(DebouncedWrites, Page):
    key, title, icon = "notes", "Desktop Notes", "accessories-text-editor-symbolic"

    def build(self):
        self.hook_unrealize()
        self.cfg = read_notes_config()
        self._pending = None
        if not NOTES_PLUGIN.is_dir():
            g = Adw.PreferencesGroup(description="The Desktop Notes widget isn't installed "
                                                 f"(expected at {NOTES_PLUGIN}). These settings are saved "
                                                 "and used once it is.")
            self.add(g)

        g = Adw.PreferencesGroup(title="Look", description="Changes show on the desktop right away.")
        title = Adw.EntryRow(title="Title", text=self.cfg["title"], show_apply_button=True,
                             max_length=NOTES_TITLE_MAX,
                             tooltip_text="The heading on the card; leave it empty to hide it")
        title.connect("apply", lambda r: self.set_now("title", r.get_text().strip()))
        g.add(title)
        g.add(scale_row("Background opacity", "Lower lets more of the wallpaper through; text stays solid",
                        *NOTES_LIMITS["opacity"], 1, self.cfg["opacity"], 0, lambda v: self.set("opacity", v)))
        g.add(scale_row("Width", "In pixels", *NOTES_LIMITS["width"], 10, self.cfg["width"], 0,
                        lambda v: self.set("width", v)))
        g.add(scale_row("Text size", "Percent of the shell's normal size", *NOTES_LIMITS["textScale"], 5,
                        self.cfg["textScale"], 0, lambda v: self.set("textScale", v)))
        g.add(switch_row("Always show reminder bells", "Otherwise a note's bell shows when you point at it, "
                         "or while it has a reminder", self.cfg["alwaysShowBells"],
                         lambda on: self.set_now("alwaysShowBells", on)))
        # Only on or off: the outline is as thick as the windows' border (Hyprland's border size,
        # set on the Windows page), in their active border's colour, so there's nothing to pick.
        g.add(switch_row("Outline", "A border as thick as your windows' borders, in their colour",
                         self.cfg["outline"], lambda on: self.set_now("outline", on)))
        self.add(g)

        g = Adw.PreferencesGroup(title="Location")
        monitors = monitor_choices(hypr_json("monitors"), self.cfg["monitor"])
        g.add(combo_row("Monitor", "The main monitor is the one at the top left of the layout. "
                        "If the chosen one isn't connected, the notes go on the main one",
                        [l for l, _ in monitors], self.cfg["monitor"],
                        lambda v: self.set_now("monitor", v), [v for _, v in monitors]))
        g.add(combo_row("Position", "Where on the screen the notes sit", [l for l, _ in POSITIONS],
                        self.cfg["position"], self.set_position, [v for _, v in POSITIONS]))
        self.margin_x = scale_row("Distance from the side", "In pixels", *NOTES_LIMITS["marginX"], 4,
                                  self.cfg["marginX"], 0, lambda v: self.set("marginX", v))
        self.margin_y = scale_row("Distance from the top or bottom", "In pixels", *NOTES_LIMITS["marginY"], 4,
                                  self.cfg["marginY"], 0, lambda v: self.set("marginY", v))
        g.add(self.margin_x)
        g.add(self.margin_y)
        self.update_margins()
        self.add(g)

        g = Adw.PreferencesGroup(title="Clicks", description="Left click ticks a note, right click edits it "
                                 "and a double right click deletes it (the same for a collection's name).")
        g.add(scale_row("Double right-click speed", "How long a right click waits for a second one before "
                        "editing, in milliseconds. Raise it if double right clicks open the editor "
                        "instead of deleting", *NOTES_LIMITS["rightClickWaitMs"], 10,
                        self.cfg["rightClickWaitMs"], 0, lambda v: self.set("rightClickWaitMs", v)))
        self.add(g)

        self.add(reset_group(self.win, "Restore default Desktop Notes settings?",
                             "Titled Reminders, 78% background opacity, 300 px wide, normal text size, bottom "
                             "right of the main monitor, 32 px from the edges, no outline, bells shown on hover, 200 ms for a double right click. "
                             "Your notes are kept.", self.reset))

    def set(self, key, value):
        self.cfg[key] = value
        # Sliders fire on every step: write the latest values at most every 100ms, so the widget
        # follows a slider as it moves without reading the file per pixel. (Restarting the timer on
        # each step, as before 2026-10-11, held every write back until the slider stopped.)
        if not self._pending:
            self._pending = GLib.timeout_add(100, self.flush)

    def flush(self):
        self._pending = None
        try:
            write_notes_config(self.cfg)
        except OSError as e:
            self.win.toast(f"Couldn't save the Desktop Notes settings: {e}")
        return False

    def set_now(self, key, value):
        """Saves a change that isn't a slider step straight away."""
        self.cfg[key] = value
        self.flush()

    def set_position(self, position):
        self.cfg["position"] = position
        self.update_margins()
        self.flush()

    def update_margins(self):
        horizontal, vertical = margin_axes(self.cfg["position"])
        self.margin_x.set_sensitive(horizontal)
        self.margin_y.set_sensitive(vertical)

    def reset(self, done=None):
        if getattr(self, "_pending", None):
            GLib.source_remove(self._pending)
            self._pending = None
        try:
            write_notes_config(dict(NOTES_DEFAULTS))
            self.win.toast("Desktop Notes settings restored")
        except OSError as e:
            self.win.toast(f"Couldn't save the Desktop Notes settings: {e}")
        self.rebuild()
        done and done()



# ---------------------------------------------------------------- Notebook

# Notebook (~/Work/omarchy-notebook) has no settings dialog: it follows this file live (a file monitor), and never writes
# it. Only values that differ from the default are written, other keys (the notes folder, anything added by hand) are kept.
# The defaults, limits and choices must match notebook/settings.py (tests/test_widgets.py compares them; it skips when
# Notebook isn't there). "last" is "as it was left", Notebook's behaviour before these settings existed.
NOTEBOOK_CONFIG = HOME / ".config/omarchy-notebook/config.json"
NOTEBOOK_BIN = HOME / ".local/bin/omarchy-notebook"
NB_DEFAULTS = {"font": "", "margin": 140, "line_spacing": 0, "title_gap": 6, "caret": "#ffffff", "cursor_blink": True,
               "dim": True, "dim_amount": 15, "shadows": True, "start_view": "last", "start_window": "last",
               "start_sidebar": "last", "start_reading": "last", "start_indent": "last", "start_text_size": 0,
               "reopen_tabs": True, "sort": "last"}
NB_LIMITS = {"margin": (12, 800), "line_spacing": (0, 60), "title_gap": (0, 300), "dim_amount": (5, 90)}
NB_TEXT_SIZE = (50, 500)
SAME = ("Same as last time", "last")
NB_CHOICES = {"start_view": (SAME, ("Simple", "simple"), ("Advanced", "advanced")),
              "start_window": (SAME, ("Fullscreen", "fullscreen"), ("Windowed", "windowed")),
              "start_sidebar": (SAME, ("Shown", "shown"), ("Hidden", "hidden")),
              "start_reading": (SAME, ("Editing", "editing"), ("Reading", "reading")),
              "start_indent": (SAME, ("On", "on"), ("Off", "off")),
              "sort": (("Leave it as it is", "last"), ("Your order", "manual"), ("By name", "name"), ("Last edited first", "modified"))}
NB_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def nb_valid(key, value):
    """The same test Notebook applies to a value read from the file."""
    default = NB_DEFAULTS[key]
    if key in NB_CHOICES:
        return value in [v for _, v in NB_CHOICES[key]]
    if key == "start_text_size":
        return isinstance(value, int) and not isinstance(value, bool) and (value == 0 or NB_TEXT_SIZE[0] <= value <= NB_TEXT_SIZE[1])
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        lo, hi = NB_LIMITS[key]
        return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi
    if key == "caret":
        return isinstance(value, str) and NB_HEX.fullmatch(value) is not None
    return isinstance(value, str) and len(value) < 200


def read_notebook_config():
    """Notebook's settings with defaults filled in and any bad value replaced by its default."""
    data = read_json(NOTEBOOK_CONFIG)
    data = data if isinstance(data, dict) else {}
    return {k: data[k] if k in data and nb_valid(k, data[k]) else d for k, d in NB_DEFAULTS.items()}


def write_notebook_config(cfg, vault=None, only=None):
    """Merges cfg into the file: defaults are left out, other keys kept; `vault`, when given, is the notes folder. `only` limits it to those keys, so a page
    writes just what it changed and can't undo an edit made elsewhere meanwhile (a stale page, or the file edited by hand)."""
    data = read_json(NOTEBOOK_CONFIG)
    data = data if isinstance(data, dict) else {}
    for key, default in NB_DEFAULTS.items() if only is None else {k: NB_DEFAULTS[k] for k in only if k in NB_DEFAULTS}.items():
        if cfg.get(key, default) == default or not nb_valid(key, cfg.get(key)):
            data.pop(key, None)
        else:
            data[key] = cfg[key]
    if vault is not None:
        data["vault"] = str(vault)
    NOTEBOOK_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(NOTEBOOK_CONFIG, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def notebook_folder():
    """The notes folder as the file names it (Notebook's own default is ~/Notes)."""
    v = read_json(NOTEBOOK_CONFIG)
    v = v.get("vault") if isinstance(v, dict) else None
    return (v.strip() if isinstance(v, str) and v.strip() else "~/Notes")


class NotebookPage(DebouncedWrites, Page):
    key, title, icon = "notebook", "Notebook", "document-edit-symbolic"

    def build(self):
        self.hook_unrealize()
        self.cfg = read_notebook_config()
        self._pending = None
        self._dirty = set()
        if not NOTEBOOK_BIN.exists():
            self.add(Adw.PreferencesGroup(description="Notebook isn't installed (expected at "
                                          f"{NOTEBOOK_BIN}). These settings are saved and used once it is."))

        g = Adw.PreferencesGroup(title="Writing", description="An open Notebook follows these as you change them.")
        self.font_row = Adw.ActionRow(title="Font", subtitle=self.cfg["font"] or "The design's own")
        self.font_default = Gtk.Button(label="Default", valign=Gtk.Align.CENTER, css_classes=["flat"],
                                       tooltip_text="Back to the design's own font", visible=bool(self.cfg["font"]))
        self.font_default.connect("clicked", lambda _b: self.set_font(""))
        choose = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
        choose.connect("clicked", lambda _b: self.choose_font())
        self.font_row.add_suffix(self.font_default)
        self.font_row.add_suffix(choose)
        g.add(self.font_row)
        g.add(spin_row("Side margins", "Space between the text and the text field's edges, each side, in pixels; "
                       "not used in the advanced view", *NB_LIMITS["margin"], 10, self.cfg["margin"],
                       lambda v: self.set("margin", v)))
        g.add(spin_row("Line spacing", "Extra space between lines, in pixels", *NB_LIMITS["line_spacing"], 1,
                       self.cfg["line_spacing"], lambda v: self.set("line_spacing", v)))
        g.add(spin_row("Space under the title", "Between the title and the text, in pixels", *NB_LIMITS["title_gap"], 2,
                       self.cfg["title_gap"], lambda v: self.set("title_gap", v)))
        caret = Adw.ActionRow(title="Cursor colour")
        self.caret = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
        rgba = Gdk.RGBA()
        rgba.parse(self.cfg["caret"])
        self.caret.set_rgba(rgba)
        self.caret.connect("notify::rgba", lambda b, _p: self.set_now("caret", rgba_to_hex(b.get_rgba()).lower()))
        caret.add_suffix(self.caret)
        g.add(caret)
        g.add(switch_row("Blinking cursor", None, self.cfg["cursor_blink"], lambda on: self.set_now("cursor_blink", on)))
        self.add(g)

        g = Adw.PreferencesGroup(title="Layout")
        g.add(switch_row("Dim other panels", "Darken the panels the pointer isn't over", self.cfg["dim"],
                         lambda on: self.set_now("dim", on)))
        g.add(spin_row("Dim amount", "Percent", *NB_LIMITS["dim_amount"], 5, self.cfg["dim_amount"],
                       lambda v: self.set("dim_amount", v)))
        g.add(switch_row("Panel shadows", "On the panel under the pointer", self.cfg["shadows"],
                         lambda on: self.set_now("shadows", on)))
        self.add(g)

        g = Adw.PreferencesGroup(title="Notes")
        self.folder_row = Adw.ActionRow(title="Notes folder", subtitle=notebook_folder(), subtitle_selectable=True,
                                        tooltip_text="An open Notebook reopens on the new folder")
        pick = Gtk.Button(label="Choose…", valign=Gtk.Align.CENTER)
        pick.connect("clicked", lambda _b: self.choose_folder())
        self.folder_row.add_suffix(pick)
        g.add(self.folder_row)
        g.add(self.choice("Sort notes", "Applies at once; \"Leave it as it is\" keeps what Notebook last used", "sort"))
        self.add(g)

        g = Adw.PreferencesGroup(title="When Notebook opens",
                                 description="Each choice is \"Same as last time\" until you pick one. The shortcuts "
                                             "inside Notebook still work whatever you choose here.")
        g.add(self.choice("View", "Simple, or with toolbars, search and the outline panel", "start_view"))
        g.add(self.choice("Window", None, "start_window"))
        g.add(self.choice("Sidebar", "The list of notes", "start_sidebar"))
        g.add(self.choice("Note", "Editing, or the reading view", "start_reading"))
        g.add(self.choice("First-line indent", "Every paragraph indented, as in a book; the files don't change", "start_indent"))
        self.size_switch = switch_row("Open at a set text size", None, self.cfg["start_text_size"] > 0, self.set_size_switch)
        g.add(self.size_switch)
        self.size_row = spin_row("Text size", "Percent of normal", *NB_TEXT_SIZE, 10, self.cfg["start_text_size"] or 100,
                                 lambda v: self.cfg["start_text_size"] and self.set("start_text_size", v))
        self.size_row.set_sensitive(self.cfg["start_text_size"] > 0)
        g.add(self.size_row)
        g.add(switch_row("Reopen the last notes", "Open the last note and its tabs again", self.cfg["reopen_tabs"],
                         lambda on: self.set_now("reopen_tabs", on)))
        self.add(g)

        g = Adw.PreferencesGroup()
        open_row = Adw.ButtonRow(title="Open Notebook", start_icon_name="document-edit-symbolic")
        open_row.connect("activated", lambda _r: spawn_detached(["omarchy-notebook"]))
        g.add(open_row)
        self.add(g)

        self.add(reset_group(self.win, "Restore default Notebook settings?",
                             "Font, margins, spacing, cursor, dimming, shadows, sort and how it opens go back to Notebook's "
                             "own defaults. Your notes and the notes folder are kept.", self.reset))

    def choice(self, title, subtitle, key):
        pairs = NB_CHOICES[key]
        return combo_row(title, subtitle, [l for l, _ in pairs], self.cfg[key], lambda v: self.set_now(key, v), [v for _, v in pairs])

    def set(self, key, value):
        """A slider or spinner step: written at most every 100 ms, so an open Notebook follows without a write per step.
        The spinner hands over floats (6.0); Notebook only accepts whole numbers for these, and would drop a 6.0."""
        self.cfg[key] = int(value) if isinstance(value, float) and value == int(value) else value
        self._dirty.add(key)
        if not self._pending:
            self._pending = GLib.timeout_add(100, self.flush)

    def set_now(self, key, value):
        self.cfg[key] = value
        self._dirty.add(key)
        self.flush()

    def flush(self):
        self._pending = None
        keys, self._dirty = self._dirty, set()
        try:
            write_notebook_config(self.cfg, only=keys)
        except OSError as e:
            self.win.toast(f"Couldn't save the Notebook settings: {e}")
        return False

    def set_font(self, family):
        self.font_row.set_subtitle(family or "The design's own")
        self.font_default.set_visible(bool(family))
        self.set_now("font", family)

    def choose_font(self):
        dialog = Gtk.FontDialog(title="Font")

        def done(d, result):
            try:
                family = d.choose_family_finish(result)
            except GLib.Error:      # cancelled
                return
            if family is not None:
                self.set_font(family.get_name())

        dialog.choose_family(self.win, None, None, done)

    def set_size_switch(self, on):
        self.size_row.set_sensitive(on)
        self.set_now("start_text_size", int(self.size_row.get_value()) if on else 0)

    def choose_folder(self):
        dialog = Gtk.FileDialog(title="Notes folder")

        def done(d, result):
            try:
                folder = d.select_folder_finish(result)
            except GLib.Error:      # cancelled
                return
            if folder is not None and folder.get_path():
                self.set_folder(folder.get_path())

        dialog.select_folder(self.win, None, done)

    def set_folder(self, path):
        try:
            write_notebook_config(self.cfg, vault=path, only=set())
        except OSError as e:
            self.win.toast(f"Couldn't save the Notebook settings: {e}")
            return
        self.folder_row.set_subtitle(str(path))

    def reset(self, done=None):
        if getattr(self, "_pending", None):
            GLib.source_remove(self._pending)
            self._pending = None
        try:
            write_notebook_config(dict(NB_DEFAULTS))
            self.win.toast("Notebook settings restored")
        except OSError as e:
            self.win.toast(f"Couldn't save the Notebook settings: {e}")
        self.rebuild()
        done and done()
