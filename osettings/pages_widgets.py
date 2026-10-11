"""Desktop widgets: the Desktop Notes shell plugin's look and place on screen."""

import json

from gi.repository import Adw, GLib

from .core import HOME, Page, combo_row, read_json, reset_group, scale_row, switch_row, write_atomic

# The widget (~/.config/omarchy/plugins/sourced.desktop-notes) watches this file and applies changes
# live. It lives outside the plugin folder because saving there reloads the plugin.
NOTES_CONFIG = HOME / ".config/desktop-notes/config.json"
NOTES_PLUGIN = HOME / ".config/omarchy/plugins/sourced.desktop-notes"

NOTES_DEFAULTS = {"opacity": 78, "width": 300, "textScale": 100, "position": "bottom-right",
                  "marginX": 32, "marginY": 32, "title": "Reminders", "alwaysShowBells": False}
# key -> (lowest, highest); the widget clamps to the same ranges for hand-edited files.
NOTES_LIMITS = {"opacity": (0, 100), "width": (200, 800), "textScale": (70, 200),
                "marginX": (0, 1000), "marginY": (0, 1000)}
# The card's heading is kept to one short line; empty hides it. The widget's titleMax matches.
NOTES_TITLE_MAX = 60
POSITIONS = [("Top left", "top-left"), ("Top", "top"), ("Top right", "top-right"),
             ("Left", "left"), ("Center", "center"), ("Right", "right"),
             ("Bottom left", "bottom-left"), ("Bottom", "bottom"), ("Bottom right", "bottom-right")]


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
    if isinstance(data.get("alwaysShowBells"), bool):
        cfg["alwaysShowBells"] = data["alwaysShowBells"]
    return cfg


def write_notes_config(cfg):
    NOTES_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(NOTES_CONFIG, json.dumps(cfg, indent=2) + "\n")


def margin_axes(position):
    """Which distances apply: a centered side has no edge to measure from."""
    horizontal = position.endswith("left") or position.endswith("right")
    vertical = position.startswith("top") or position.startswith("bottom")
    return horizontal, vertical


class NotesPage(Page):
    key, title, icon = "notes", "Desktop Notes", "accessories-text-editor-symbolic"

    def build(self):
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
        self.add(g)

        g = Adw.PreferencesGroup(title="Location")
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

        self.add(reset_group(self.win, "Restore default Desktop Notes settings?",
                             "Titled Reminders, 78% background opacity, 300 px wide, normal text size, bottom "
                             "right, 32 px from the edges, bells shown on hover. Your notes are kept.", self.reset))

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
