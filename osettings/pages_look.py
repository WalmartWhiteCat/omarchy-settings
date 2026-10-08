"""Appearance pages: theme, theme colors, background, window look, per-app window rules."""

import os
import re
import shutil
import tomllib
from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .core import (DEFAULT_THEME, HOME, OMARCHY_PATH, STATE, USER_THEMES, Page, clear_group, combo_row,
                   confirm, current_theme_slug, group_add, gsetting, hypr_json, icon_button, images_in,
                   load_texture_async, reset_group, rgba_from_hypr, rgba_to_hex, rgba_to_hypr, run, run_async,
                   run_chain, scale_row, slugify, switch_row, theme_dir, theme_preview)
from .store import DEFAULT_ANIMATIONS

PIN_HOOK = HOME / ".config/omarchy/hooks/theme-set.d/50-omarchy-settings-pins"
PIN_HOOK_SCRIPT = """#!/bin/bash
# Installed by Omarchy Settings: re-apply the appearance you pinned in the app
# (light/dark, icons, interface font) after Omarchy switches themes.
f="$HOME/.config/omarchy-settings/settings.json"
[[ -f $f ]] || exit 0
get() { jq -r ".pins.$1 // empty" "$f" 2>/dev/null; }
cs=$(get color_scheme)
if [[ $cs == prefer-light ]]; then
  gsettings set org.gnome.desktop.interface color-scheme prefer-light
  gsettings set org.gnome.desktop.interface gtk-theme Adwaita
elif [[ $cs == prefer-dark ]]; then
  gsettings set org.gnome.desktop.interface color-scheme prefer-dark
  gsettings set org.gnome.desktop.interface gtk-theme Adwaita-dark
fi
it=$(get icon_theme); [[ -n $it ]] && gsettings set org.gnome.desktop.interface icon-theme "$it"
fn=$(get font_name); [[ -n $fn ]] && gsettings set org.gnome.desktop.interface font-name "$fn"
exit 0
"""


def flowbox():
    return Gtk.FlowBox(selection_mode=Gtk.SelectionMode.SINGLE, homogeneous=True, max_children_per_line=4,
                       min_children_per_line=2, row_spacing=12, column_spacing=12)


def thumb():
    pic = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, can_shrink=True)
    pic.set_size_request(200, 112)
    pic.add_css_class("card")
    pic.set_overflow(Gtk.Overflow.HIDDEN)
    return pic


def apply_pins(store):
    """Apply pinned appearance now and make sure the theme-set hook re-applies it later."""
    pins = store.pins
    cmds = []
    cs = pins.get("color_scheme")
    if cs:
        cmds.append(["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", cs])
        cmds.append(["gsettings", "set", "org.gnome.desktop.interface", "gtk-theme",
                     "Adwaita" if cs == "prefer-light" else "Adwaita-dark"])
    if pins.get("icon_theme"):
        cmds.append(["gsettings", "set", "org.gnome.desktop.interface", "icon-theme", pins["icon_theme"]])
    if pins.get("font_name"):
        cmds.append(["gsettings", "set", "org.gnome.desktop.interface", "font-name", pins["font_name"]])
    if any(pins.values()):
        PIN_HOOK.parent.mkdir(parents=True, exist_ok=True)
        PIN_HOOK.write_text(PIN_HOOK_SCRIPT)
        PIN_HOOK.chmod(0o755)
    elif PIN_HOOK.exists():
        PIN_HOOK.unlink()
    store.save_now()
    run_chain(cmds)


# ---------------------------------------------------------------- theme


class ThemePage(Page):
    key, title, icon = "theme", "Theme", "applications-graphics-symbolic"

    def build(self):
        group = Adw.PreferencesGroup(
            title="Theme", description="Applies colors to Hyprland, the bar, terminals, editors and GTK apps.")
        self.flow = flowbox()
        self.flow.connect("child-activated", self.on_activate)
        group.add(self.flow)
        self.add(group)

        g = Adw.PreferencesGroup(title="Keep across themes",
                                 description="Normally each theme picks these. Choose a value to keep it "
                                             "whatever theme you switch to.")
        store = self.win.store
        g.add(combo_row("App style", "Light or dark GTK and libadwaita apps",
                        ["Follow theme", "Dark", "Light"], store.pins.get("color_scheme"),
                        lambda v: self.pin("color_scheme", v), [None, "prefer-dark", "prefer-light"]))
        icons = sorted({p.parent.name for base in (Path("/usr/share/icons"), HOME / ".local/share/icons",
                                                    HOME / ".icons") if base.is_dir()
                        for p in base.glob("*/index.theme")
                        if not (p.parent / "cursors").is_dir() or (p.parent / "scalable").is_dir()
                        or any(p.parent.glob("*x*"))} - {"default", "hicolor"})
        g.add(combo_row("Icon theme", f"Currently {gsetting('icon-theme')}", ["Follow theme"] + icons,
                        store.pins.get("icon_theme"), lambda v: self.pin("icon_theme", v), [None] + icons))
        self.add(g)

        install = Adw.PreferencesGroup(title="Install theme",
                                       description="Clone a theme from a git repository (see omarchy.org/themes).")
        self.url = Adw.EntryRow(title="Git repository URL", show_apply_button=True)
        self.url.connect("apply", self.on_install)
        install.add(self.url)
        self.add(install)
        self.add(reset_group(self.win, "Restore the default theme?",
                             f"Switches back to {DEFAULT_THEME}, Omarchy's default theme, and stops keeping "
                             "app style and icons fixed. Installed themes are kept.", self.reset))
        self.populate()

    def pin(self, key, value):
        self.win.store.pins[key] = value
        apply_pins(self.win.store)
        if value is None:
            self.win.toast("Will follow the theme from the next theme change")

    def populate(self):
        while (c := self.flow.get_first_child()):
            self.flow.remove(c)
        current = run(["omarchy", "theme", "current"])
        for name in run(["omarchy", "theme", "list"]).splitlines():
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            pic = thumb()
            box.append(pic)
            label = Gtk.Label(label=name, ellipsize=3)
            if name == current:
                label.set_markup(f"<b>{GLib.markup_escape_text(name)}</b>  ✓")
            box.append(label)
            child = Gtk.FlowBoxChild(child=box)
            child.theme_name = name
            self.flow.append(child)
            if name == current:
                self.flow.select_child(child)
            preview = theme_preview(slugify(name))
            if preview:
                load_texture_async(preview, 400, 225, lambda t, p=pic: t and p.set_paintable(t))

    def on_activate(self, _flow, child):
        if getattr(self, "applying", False):
            self.win.toast("Still applying the last theme…")
            return
        self.applying = True
        name = child.theme_name
        self.win.busy(f"Applying {name}…")
        run_async(["omarchy", "theme", "set", name], lambda c, o, e: self.applied(name, c, e))

    def applied(self, name, code, err):
        self.applying = False
        self.win.toast(f"Theme set to {name}" if code == 0 else f"Theme failed: {err.strip()[:120]}")
        self.populate()
        self.win.theme_changed()

    def on_install(self, row):
        url = row.get_text().strip()
        if not url:
            return
        self.win.busy("Installing theme…")

        def done(code, out, err):
            self.win.toast("Theme installed" if code == 0 else f"Install failed: {(err or out).strip()[:120]}")
            row.set_text("")
            self.populate()
            self.win.theme_changed()

        run_async(["omarchy", "theme", "install", url], done)

    def reset(self, done=None):
        self.win.store.pins = {k: None for k in ("color_scheme", "icon_theme")} | {
            "font_name": self.win.store.pins.get("font_name")}
        apply_pins(self.win.store)
        self.win.busy(f"Applying {DEFAULT_THEME}…")

        def finished(code, _o, err):
            self.applied(DEFAULT_THEME, code, err)
            self.rebuild()
            done and done()

        run_async(["omarchy", "theme", "set", DEFAULT_THEME], finished)


# ---------------------------------------------------------------- theme colors


COLOR_GROUPS = [
    ("Interface", ["accent", "selection", "muted", "background", "dark_background", "darker_background",
                   "lighter_background", "foreground", "dark_foreground", "light_foreground",
                   "bright_foreground"]),
    ("Terminal palette", ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white", "orange",
                          "brown"]),
    ("Terminal bright palette", ["bright_black", "bright_red", "bright_green", "bright_yellow", "bright_blue",
                                 "bright_magenta", "bright_cyan", "bright_white"]),
]
OVERLAY_MARK = ".omarchy-settings-overlay"
TABLE_HEADER = re.compile(r"^[ \t]*\[", re.M)


def rewrite_colors(text, changes):
    """Set top-level `key = "value"` pairs in colors.toml text, keeping comments and order.

    Only the part before the first [table] header is touched; keys that aren't there yet
    are added at the end of that part, so they never land inside a table."""
    header = TABLE_HEADER.search(text)
    top, rest = (text[:header.start()], text[header.start():]) if header else (text, "")
    for k, v in changes.items():
        top, n = re.subn(rf'(?m)^([ \t]*{re.escape(k)}[ \t]*=[ \t]*)(?:"[^"\n]*"|\'[^\'\n]*\')',
                         lambda m: f'{m.group(1)}"{v}"', top, count=1)
        if not n:
            top = top.rstrip("\n") + f'\n{k} = "{v}"\n' + ("\n" if rest else "")
    return top + rest
ORIGINAL_SUFFIX = ".omarchy-settings-original"


class ColorsPage(Page):
    key, title, icon = "colors", "Theme Colors", "color-select-symbolic"

    def build(self):
        self.slug = current_theme_slug()
        self.source = theme_dir(self.slug) / "colors.toml"
        try:
            self.colors = tomllib.loads(self.source.read_text())
        except Exception:
            self.colors = {}
        self.edited = dict(self.colors)

        head = Adw.PreferencesGroup(
            title=f"Colors of {self.slug.replace('-', ' ').title()}",
            description="Edit the current theme's palette, then apply. Stock themes are never changed: your "
                        "colors are saved as a personal copy in ~/.config/omarchy/themes.")
        apply = Gtk.Button(label="Apply", valign=Gtk.Align.CENTER, sensitive=False)
        apply.add_css_class("suggested-action")
        apply.connect("clicked", lambda *_: self.save())
        self.apply_btn = apply
        head.set_header_suffix(apply)
        if not self.colors:
            head.add(Adw.ActionRow(title="This theme has no colors.toml to edit"))
            self.add(head)
            return
        if "mode" in self.colors:
            head.add(combo_row("Mode", "Whether the theme is treated as light or dark", ["Dark", "Light"],
                               self.colors.get("mode"), lambda v: self.edit("mode", v), ["dark", "light"]))
        self.add(head)

        used = {"mode"}
        for title, keys in COLOR_GROUPS + [("Other", [k for k in self.colors if k not in
                                                      {x for _, ks in COLOR_GROUPS for x in ks} | {"mode"}])]:
            keys = [k for k in keys if isinstance(self.colors.get(k), str) and k not in used]
            if not keys:
                continue
            g = Adw.PreferencesGroup(title=title)
            for k in keys:
                used.add(k)
                row = Adw.ActionRow(title=k.replace("_", " ").capitalize(), subtitle=self.colors[k])
                btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), valign=Gtk.Align.CENTER)
                btn.set_rgba(rgba_from_hypr(self.colors[k]))
                btn.connect("notify::rgba", lambda b, _p, k=k, r=row: self.edit(k, rgba_to_hex(b.get_rgba()), r))
                row.add_suffix(btn)
                g.add(row)
            self.add(g)
        self.add(reset_group(self.win, "Restore this theme's original colors?",
                             "Removes your edited palette for this theme and re-applies it.", self.reset))

    def edit(self, key, value, row=None):
        self.edited[key] = value
        if row:
            row.set_subtitle(value)
        self.apply_btn.set_sensitive(self.edited != self.colors)

    def target(self):
        return USER_THEMES / self.slug / "colors.toml"

    def save(self):
        changes = {k: v for k, v in self.edited.items() if self.colors.get(k) != v}
        text = rewrite_colors(self.source.read_text(), changes)
        try:
            parsed = tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            parsed, err = None, str(e)
        if parsed is None or any(parsed.get(k) != v for k, v in changes.items()):
            self.win.toast("Colors not saved: the theme's colors.toml couldn't be updated safely"
                           + (f" ({err})" if parsed is None else ""))
            return
        target = self.target()
        stock = not (USER_THEMES / self.slug).is_dir()
        target.parent.mkdir(parents=True, exist_ok=True)
        if stock:
            (target.parent / OVERLAY_MARK).write_text("Created by Omarchy Settings to hold edited colors.\n")
        original = target.with_name("colors.toml" + ORIGINAL_SUFFIX)
        if target.exists() and not original.exists() and not (target.parent / OVERLAY_MARK).exists():
            shutil.copy2(target, original)
        target.write_text(text)
        self.apply_theme("Colors applied")

    def apply_theme(self, message, done=None):
        self.win.busy("Applying theme…")

        def finished(code, _o, err):
            self.win.toast(message if code == 0 else f"Theme failed: {err.strip()[:120]}")
            self.win.theme_changed()
            done and done()

        run_async(["omarchy", "theme", "set", self.slug], finished)

    def reset(self, done=None):
        target = self.target()
        d = target.parent
        original = target.with_name("colors.toml" + ORIGINAL_SUFFIX)
        if (d / OVERLAY_MARK).exists():
            target.unlink(missing_ok=True)
            (d / OVERLAY_MARK).unlink(missing_ok=True)
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        elif original.exists():
            original.replace(target)
        else:
            self.win.toast("These colors have not been edited")
            return done and done()
        self.apply_theme("Original colors restored", done)


# ---------------------------------------------------------------- background


class BackgroundPage(Page):
    key, title, icon = "background", "Background", "preferences-desktop-wallpaper-symbolic"

    def build(self):
        self.group = Adw.PreferencesGroup(title="Background")
        self.group.set_header_suffix(icon_button("list-add-symbolic", "Add images…", self.on_add))
        self.flow = flowbox()
        self.flow.connect("child-activated", self.on_activate)
        self.group.add(self.flow)
        self.add(self.group)
        self.add(reset_group(self.win, "Restore the default background?",
                             "Sets the current theme's first stock wallpaper. Images you added are kept.",
                             self.reset))
        self.populate()

    def user_dir(self):
        return HOME / ".config/omarchy/backgrounds" / current_theme_slug()

    def populate(self):
        while (c := self.flow.get_first_child()):
            self.flow.remove(c)
        self.group.set_description(f"Wallpapers for the current theme ({current_theme_slug()}). "
                                   "Use + to add your own.")
        link = STATE / "current/background"
        current = os.path.realpath(link) if link.exists() else ""
        for img in images_in(self.user_dir(), STATE / "current/theme/backgrounds"):
            pic = thumb()
            child = Gtk.FlowBoxChild(child=pic, tooltip_text=img.name)
            child.path = img
            self.flow.append(child)
            if os.path.realpath(img) == current:
                self.flow.select_child(child)
            load_texture_async(img, 400, 225, lambda t, p=pic: t and p.set_paintable(t))

    def on_activate(self, _flow, child):
        run_async(["omarchy", "theme", "bg", "set", str(child.path)],
                  lambda c, o, e: self.win.toast("Background updated" if c == 0 else e.strip()[:120]))

    def on_add(self):
        dialog = Gtk.FileDialog(title="Add backgrounds")
        f = Gtk.FileFilter(name="Images")
        f.add_mime_type("image/*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(f)
        dialog.set_filters(filters)
        dialog.open_multiple(self.win, None, self.on_files)

    def on_files(self, dialog, result):
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            return
        dest = self.user_dir()
        dest.mkdir(parents=True, exist_ok=True)
        last = None
        for i in range(files.get_n_items()):
            src = Path(files.get_item(i).get_path())
            last = dest / src.name
            shutil.copy2(src, last)
        self.populate()
        if last:
            run_async(["omarchy", "theme", "bg", "set", str(last)], lambda *_: self.populate())

    def reset(self, done=None):
        stock = images_in(STATE / "current/theme/backgrounds")
        if not stock:
            self.win.toast("This theme has no stock backgrounds")
            return done and done()

        def finished(code, _o, err):
            self.win.toast("Background restored" if code == 0 else err.strip()[:120])
            self.populate()
            done and done()

        run_async(["omarchy", "theme", "bg", "set", str(stock[0])], finished)


# ---------------------------------------------------------------- windows


WINDOW_PREFIXES = ("general:", "decoration:", "dwindle:", "master:", "scrolling:")


class WindowsPage(Page):
    key, title, icon = "windows", "Windows", "preferences-desktop-display-symbolic"
    LAYOUTS = ["dwindle", "master", "scrolling"]

    def build(self):
        h = self.win.store

        def cur(opt, default):
            return h.current(opt, default)

        def setter(opt, conv=None):
            return lambda v: h.set(opt, conv(v) if conv else v)

        g = Adw.PreferencesGroup(title="Layout and spacing")
        g.add(combo_row("Tiling layout", "Dwindle splits windows, master keeps one large window, "
                                         "scrolling is a niri-like side-scrolling strip",
                        ["Dwindle", "Master", "Scrolling"], cur("general:layout", "dwindle"),
                        setter("general:layout"), self.LAYOUTS))
        g.add(scale_row("Master window size", "Share of the screen in the master layout", 0.2, 0.9, 0.01,
                        cur("master:mfact", 0.55), 2, setter("master:mfact")))
        g.add(scale_row("Scrolling column width", "Share of the screen per column in the scrolling layout",
                        0.2, 1.0, 0.01, cur("scrolling:column_width", 0.49), 2, setter("scrolling:column_width")))
        g.add(scale_row("Inner gaps", "Space between windows", 0, 40, 1, cur("general:gaps_in", 5), 0,
                        setter("general:gaps_in")))
        g.add(scale_row("Outer gaps", "Space to screen edges", 0, 60, 1, cur("general:gaps_out", 10), 0,
                        setter("general:gaps_out")))
        g.add(switch_row("Resize by dragging borders", None, cur("general:resize_on_border", False),
                         setter("general:resize_on_border")))
        self.add(g)

        g = Adw.PreferencesGroup(title="Borders and corners",
                                 description="Border colors normally come from the theme.")
        g.add(scale_row("Border width", None, 0, 10, 1, cur("general:border_size", 2), 0,
                        setter("general:border_size")))
        g.add(scale_row("Corner rounding", None, 0, 30, 1, cur("decoration:rounding", 0), 0,
                        setter("decoration:rounding")))
        self.border_rows(g)
        self.add(g)

        g = Adw.PreferencesGroup(title="Transparency and dimming")
        g.add(scale_row("Focused window opacity", None, 0.3, 1.0, 0.01, cur("decoration:active_opacity", 1.0), 2,
                        setter("decoration:active_opacity")))
        g.add(scale_row("Unfocused window opacity", None, 0.3, 1.0, 0.01,
                        cur("decoration:inactive_opacity", 1.0), 2, setter("decoration:inactive_opacity")))
        g.add(scale_row("Fullscreen window opacity", None, 0.3, 1.0, 0.01,
                        cur("decoration:fullscreen_opacity", 1.0), 2, setter("decoration:fullscreen_opacity")))
        g.add(switch_row("Dim unfocused windows", None, cur("decoration:dim_inactive", False),
                         setter("decoration:dim_inactive")))
        g.add(scale_row("Dim strength", None, 0.0, 1.0, 0.01, cur("decoration:dim_strength", 0.5), 2,
                        setter("decoration:dim_strength")))
        self.add(g)

        g = Adw.PreferencesGroup(title="Blur", description="Blur shows behind transparent windows.")
        g.add(switch_row("Blur", None, cur("decoration:blur:enabled", False), setter("decoration:blur:enabled")))
        g.add(scale_row("Blur size", None, 1, 20, 1, cur("decoration:blur:size", 8), 0,
                        setter("decoration:blur:size")))
        g.add(scale_row("Blur passes", "More passes look smoother but cost more GPU", 1, 6, 1,
                        cur("decoration:blur:passes", 1), 0, setter("decoration:blur:passes")))
        g.add(scale_row("Vibrancy", "Color saturation of the blur", 0.0, 1.0, 0.01,
                        cur("decoration:blur:vibrancy", 0.17), 2, setter("decoration:blur:vibrancy")))
        g.add(scale_row("Brightness", None, 0.0, 2.0, 0.01, cur("decoration:blur:brightness", 1.0), 2,
                        setter("decoration:blur:brightness")))
        g.add(scale_row("Contrast", None, 0.0, 2.0, 0.01, cur("decoration:blur:contrast", 0.89), 2,
                        setter("decoration:blur:contrast")))
        g.add(scale_row("Noise", None, 0.0, 0.2, 0.001, cur("decoration:blur:noise", 0.0117), 3,
                        setter("decoration:blur:noise")))
        g.add(switch_row("Blur menus and popups", None, cur("decoration:blur:popups", False),
                         setter("decoration:blur:popups")))
        g.add(switch_row("X-ray", "Floating windows blur only the wallpaper, not windows behind them",
                         cur("decoration:blur:xray", False), setter("decoration:blur:xray")))
        self.add(g)

        g = Adw.PreferencesGroup(title="Shadows")
        g.add(switch_row("Shadows", None, cur("decoration:shadow:enabled", False),
                         setter("decoration:shadow:enabled")))
        g.add(scale_row("Shadow range", None, 1, 50, 1, cur("decoration:shadow:range", 4), 0,
                        setter("decoration:shadow:range")))
        g.add(scale_row("Shadow sharpness", "1 is soft, 4 is sharp", 1, 4, 1,
                        cur("decoration:shadow:render_power", 3), 0, setter("decoration:shadow:render_power")))
        row = Adw.ActionRow(title="Shadow color")
        btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=True), valign=Gtk.Align.CENTER)
        btn.set_rgba(rgba_from_hypr(cur("decoration:shadow:color", "ee1a1a1a")))
        btn.connect("notify::rgba", lambda b, _p: h.set("decoration:shadow:color", rgba_to_hypr(b.get_rgba())))
        row.add_suffix(btn)
        g.add(row)
        self.add(g)

        self.animation_group()

        self.add(reset_group(self.win, "Restore default window settings?",
                             "Layout, gaps, borders, colors, rounding, opacity, dimming, blur, shadows and "
                             "animations go back to Omarchy's defaults. Your own ~/.config/hypr/looknfeel.lua "
                             "still applies.", self.reset))

    def border_rows(self, g):
        h = self.win.store
        active = h.values.get("general:col:active_border")
        inactive = h.values.get("general:col:inactive_border")
        live_active = h.current("general:col:active_border", "ff33ccff")

        self.custom_border = switch_row("Custom border colors", "Off uses the theme's colors",
                                        active is not None, self.toggle_border)
        g.add(self.custom_border)

        def color_row(title, color, alpha=True):
            row = Adw.ActionRow(title=title)
            btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=alpha), valign=Gtk.Align.CENTER)
            btn.set_rgba(rgba_from_hypr(color))
            btn.connect("notify::rgba", lambda *_: self.save_border())
            row.add_suffix(btn)
            row.btn = btn
            g.add(row)
            return row

        colors = active.get("colors") if isinstance(active, dict) else [active] if active else []
        live = str(live_active).split()
        first = colors[0] if colors else (live[0] if live else "ff33ccff")
        second = colors[1] if len(colors) > 1 else first
        self.c1 = color_row("Focused border", first)
        self.gradient = switch_row("Gradient", "Blend the focused border into a second color",
                                   len(colors) > 1, lambda _v: self.save_border())
        g.add(self.gradient)
        self.c2 = color_row("Gradient second color", second)
        angle = active.get("angle", 45) if isinstance(active, dict) else 45
        self.angle = scale_row("Gradient angle", None, 0, 360, 15, angle, 0, lambda _v: self.save_border())
        g.add(self.angle)
        self.c3 = color_row("Unfocused border", inactive or h.current("general:col:inactive_border", "aa595959"))
        self.sync_border_sensitivity()

    def sync_border_sensitivity(self):
        on = self.custom_border.get_active()
        grad = self.gradient.get_active()
        for w in (self.c1, self.gradient, self.c3):
            w.set_sensitive(on)
        for w in (self.c2, self.angle):
            w.set_sensitive(on and grad)

    def toggle_border(self, on):
        if on:
            self.save_border()
        else:
            self.win.store.reset(["general:col:active_border", "general:col:inactive_border"])
        self.sync_border_sensitivity()

    def save_border(self):
        self.sync_border_sensitivity()
        if not self.custom_border.get_active():
            return
        h = self.win.store
        c1 = rgba_to_hypr(self.c1.btn.get_rgba())
        if self.gradient.get_active():
            h.values["general:col:active_border"] = {"colors": [c1, rgba_to_hypr(self.c2.btn.get_rgba())],
                                                     "angle": int(self.angle.scale.get_value())}
        else:
            h.values["general:col:active_border"] = c1
        h.values["general:col:inactive_border"] = rgba_to_hypr(self.c3.btn.get_rgba())
        h.schedule_save()

    def animation_group(self):
        h = self.win.store
        g = Adw.PreferencesGroup(title="Animations")
        g.add(switch_row("Animations", None, h.current("animations:enabled", True),
                         lambda v: h.set("animations:enabled", v)))

        def set_anim(key, value):
            if value is None:
                h.anim.pop(key, None)
            else:
                h.anim[key] = value
            h.schedule_save()

        g.add(scale_row("Animation speed", "1 is Omarchy's normal speed; higher is faster", 0.25, 3.0, 0.05,
                        float(h.anim.get("factor", 1.0)), 2, lambda v: set_anim("factor", v)))
        g.add(combo_row("Window open and close", None, ["Default (pop in)", "Slide", "Shrink (gnomed)"],
                        h.anim.get("windows"), lambda v: set_anim("windows", v), [None, "slide", "gnomed"]))
        default_ws = next((a for a in DEFAULT_ANIMATIONS if a["leaf"] == "workspaces"), {})
        g.add(combo_row("Workspace switching",
                        "Omarchy's default is " + ("instant" if not default_ws.get("enabled", True) else "animated"),
                        ["Default", "Instant", "Slide", "Slide vertically", "Fade", "Slide and fade"],
                        h.anim.get("workspaces"), lambda v: set_anim("workspaces", v),
                        [None, "off", "slide", "slidevert", "fade", "slidefade 20%"]))
        self.add(g)

    def reset(self, done=None):
        h = self.win.store
        h.reset(prefix=WINDOW_PREFIXES)
        h.reset(["animations:enabled"])
        h.anim = {}

        def rebuilt():
            self.rebuild()
            self.win.toast("Window settings restored")
            done and done()

        h.schedule_save(after=rebuilt)


# ---------------------------------------------------------------- per-app rules


class RulesPage(Page):
    key, title, icon = "rules", "App Rules", "view-list-symbolic"

    def build(self):
        g = Adw.PreferencesGroup(
            title="Per-app rules",
            description="Give one app its own transparency, make it always float, turn blur off for it, or "
                        "always open it on a given workspace.")
        classes = sorted({c.get("class") for c in (hypr_json("clients") or []) if c.get("class")})
        self.classes = classes
        existing = {r["class"] for r in self.win.store.rules}
        avail = [c for c in classes if c not in existing]
        self.pick = Adw.ComboRow(title="Add a rule for an open app",
                                 model=Gtk.StringList.new(avail or ["No other apps open"]))
        self.pick.set_sensitive(bool(avail))
        self.pick.add_suffix(icon_button("list-add-symbolic", "Add rule",
                                         lambda: avail and self.add_rule(avail[self.pick.get_selected()])))
        g.add(self.pick)
        entry = Adw.EntryRow(title="Or type an app class (e.g. firefox)", show_apply_button=True)
        entry.connect("apply", lambda r: r.get_text().strip() and self.add_rule(r.get_text().strip()))
        g.add(entry)
        self.add(g)

        self.list = Adw.PreferencesGroup(title="Your rules")
        self.add(self.list)
        self.populate()
        self.add(reset_group(self.win, "Remove all app rules?",
                             "Every per-app rule made here is deleted.", self.reset, label="Remove all rules"))

    def populate(self):
        clear_group(self.list)
        rules = self.win.store.rules
        if not rules:
            group_add(self.list, Adw.ActionRow(title="No rules yet", subtitle="Add one above"))
        for r in rules:
            group_add(self.list, self.rule_row(r))

    def summary(self, r):
        bits = []
        if r.get("opacity_active") is not None:
            bits.append(f"opacity {r['opacity_active']:.2f}/{r.get('opacity_inactive', r['opacity_active']):.2f}")
        if r.get("float"):
            bits.append("floats")
        if r.get("no_blur"):
            bits.append("no blur")
        if r.get("workspace"):
            bits.append(f"workspace {int(r['workspace'])}")
        return ", ".join(bits) or "No changes yet"

    def rule_row(self, r):
        store = self.win.store
        exp = Adw.ExpanderRow(title=GLib.markup_escape_text(r["class"]), subtitle=self.summary(r),
                              show_enable_switch=True, enable_expansion=r.get("enabled", True))

        def changed(key, value):
            if value is None:
                r.pop(key, None)
            else:
                r[key] = value
            exp.set_subtitle(self.summary(r))
            store.schedule_save()

        exp.connect("notify::enable-expansion", lambda e, _p: changed("enabled", e.get_enable_expansion()))
        custom = r.get("opacity_active") is not None
        op = switch_row("Custom transparency", None, custom,
                        lambda v: (changed("opacity_active", a.scale.get_value() if v else None),
                                   changed("opacity_inactive", i.scale.get_value() if v else None)))
        exp.add_row(op)
        a = scale_row("Focused opacity", None, 0.2, 1.0, 0.01, r.get("opacity_active", 0.9), 2,
                      lambda v: op.get_active() and changed("opacity_active", v))
        i = scale_row("Unfocused opacity", None, 0.2, 1.0, 0.01, r.get("opacity_inactive", 0.85), 2,
                      lambda v: op.get_active() and changed("opacity_inactive", v))
        exp.add_row(a)
        exp.add_row(i)
        exp.add_row(switch_row("Always float", None, r.get("float"), lambda v: changed("float", v or None)))
        exp.add_row(switch_row("Turn off blur", None, r.get("no_blur"), lambda v: changed("no_blur", v or None)))
        ws = Adw.SpinRow.new_with_range(0, 10, 1)
        ws.set_title("Open on workspace")
        ws.set_subtitle("0 = wherever it is launched")
        ws.set_value(r.get("workspace") or 0)
        ws.connect("notify::value", lambda s, _p: changed("workspace", int(s.get_value()) or None))
        exp.add_row(ws)
        remove = Adw.ButtonRow(title="Remove rule", start_icon_name="user-trash-symbolic")
        remove.add_css_class("destructive-action")
        remove.connect("activated", lambda _r: self.remove_rule(r))
        exp.add_row(remove)
        return exp

    def add_rule(self, cls):
        if any(r["class"] == cls for r in self.win.store.rules):
            self.win.toast(f"{cls} already has a rule")
            return
        self.win.store.rules.append({"class": cls, "enabled": True})
        self.win.store.schedule_save()
        self.rebuild()

    def remove_rule(self, r):
        self.win.store.rules.remove(r)
        self.win.store.schedule_save()
        self.rebuild()

    def reset(self, done=None):
        self.win.store.rules = []
        self.win.store.schedule_save(after=lambda: done and done())
        self.rebuild()
