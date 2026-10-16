"""Shared paths, helpers and widgets for Omarchy Settings."""

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

HOME = Path.home()
OMARCHY_PATH = Path(os.environ.get("OMARCHY_PATH", "/usr/share/omarchy"))
STATE = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local/state")) / "omarchy"
CONFIG_DIR = HOME / ".config/omarchy-settings"
HYPR_DIR = HOME / ".config/hypr"
SHELL_JSON = HOME / ".config/omarchy/shell.json"
USER_THEMES = HOME / ".config/omarchy/themes"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
# The ones the Live Wallpaper plugin plays (its is_video), for video backgrounds.
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}

# Omarchy's out-of-the-box values, used by the "Restore defaults" buttons.
DEFAULT_THEME = "Tokyo Night"
DEFAULT_FONT = "JetBrainsMono Nerd Font"


# ---------------------------------------------------------------- processes


def run(cmd, timeout=20):
    """Run a command synchronously and return stdout ('' on failure)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout)
        return p.stdout.strip()
    except Exception:
        return ""


def run_ok(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL, timeout=20).returncode == 0
    except Exception:
        return False


# Longest a background command may run. Past it, it counts as failed, so a hung command can't
# leave a page waiting (or "Restore all" stopped part-way) for ever.
COMMAND_TIMEOUT = 120


def _run_bounded(cmd, timeout):
    """(returncode, stdout, stderr); a missing program or a command past `timeout` is a failure."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 1, "", f"{' '.join(cmd[:3])} didn't finish within {timeout} seconds"
    except Exception as e:  # missing binary etc.
        return 1, "", str(e)


def run_async(cmd, done=None, timeout=COMMAND_TIMEOUT):
    """Run a command in a thread; call done(returncode, stdout, stderr) on the main loop."""

    def worker():
        result = _run_bounded(cmd, timeout)
        if done:
            GLib.idle_add(lambda: done(*result) and False)

    threading.Thread(target=worker, daemon=True).start()


def run_chain(cmds, done=None, timeout=COMMAND_TIMEOUT):
    """Run commands one after another in a thread; done(failures) gets the stderr of any that failed."""

    def worker():
        failures = []
        for cmd in cmds:
            code, out, err = _run_bounded(cmd, timeout)
            if code != 0:
                failures.append(f"{' '.join(cmd[:3])}: {(err or out).strip()[:100]}")
        if done:
            GLib.idle_add(lambda: done(failures) and False)

    threading.Thread(target=worker, daemon=True).start()


def spawn_detached(cmd):
    try:
        subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return True
    except Exception:
        return False


def hypr_json(*args):
    try:
        return json.loads(run(["hyprctl", *args, "-j"]))
    except Exception:
        return None


def hypr_option(name):
    data = hypr_json("getoption", name)
    if not isinstance(data, dict):
        return None
    for key in ("int", "float", "str", "bool"):
        if key in data:
            return None if data[key] == "[[EMPTY]]" else data[key]
    if "css" in data:  # gaps: "5 5 5 5"
        try:
            return int(data["css"].split()[0])
        except Exception:
            return None
    if "gradient" in data:  # "ffa9a4e8 0deg" or "ee33ccff ee00ff99 45deg"
        return data["gradient"]
    return None


def gsetting(key, schema="org.gnome.desktop.interface"):
    return run(["gsettings", "get", schema, key]).strip("'")


# ---------------------------------------------------------------- files


def backup(path):
    path = Path(path)
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.bak.{int(time.time())}"))


def trash_file(path):
    """Move a file to the user's Trash. Returns None, or the error message."""
    from gi.repository import Gio
    try:
        Gio.File.new_for_path(str(path)).trash(None)
        return None
    except Exception as e:  # GLib.Error, e.g. no Trash on that filesystem
        return getattr(e, "message", None) or str(e)


# Read once at import: os.umask can only be read by setting it, which isn't thread-safe later.
_UMASK = os.umask(0o022)
os.umask(_UMASK)


def write_atomic(path, text):
    """Replace a file's contents in one step: after a crash or a full disk it holds either the old
    text or the new, never part of it. A symlinked file (e.g. kept in a dotfiles repo) is written
    through the link rather than replaced by a plain file, and an existing file keeps its mode."""
    path = Path(path)
    target = path.resolve() if path.is_symlink() else path
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            mode = stat.S_IMODE(target.stat().st_mode)
        except FileNotFoundError:
            mode = 0o666 & ~_UMASK
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {} if default is None else default


def slugify(name):
    return name.strip().lower().replace(" ", "-")


def theme_dir(slug):
    user = USER_THEMES / slug
    return user if user.is_dir() else OMARCHY_PATH / "themes" / slug


def theme_preview(slug):
    for d in (USER_THEMES / slug, OMARCHY_PATH / "themes" / slug):
        if (d / "preview.png").exists():
            return d / "preview.png"
    for d in (USER_THEMES / slug, OMARCHY_PATH / "themes" / slug):
        imgs = images_in(d / "backgrounds")
        if imgs:
            return imgs[0]
    return None


def current_theme_slug():
    try:
        return (STATE / "current/theme.name").read_text().strip()
    except Exception:
        return ""


def natural_key(name):
    """Sort key that orders numbers by value, so 2.png comes before 10.png, and ignores case."""
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", name)], name


def images_in(*dirs, videos=False):
    """Each folder's images (and videos, if asked), in natural order, folder by folder."""
    exts = IMAGE_EXTS | VIDEO_EXTS if videos else IMAGE_EXTS
    out = []
    for d in dirs:
        if d.is_dir():
            out += sorted((p for p in d.iterdir() if p.suffix.lower() in exts and p.is_file()),
                          key=lambda p: natural_key(p.name))
    return out


def load_texture_async(path, width, height, callback):
    """Decode a scaled thumbnail off the main thread."""

    def worker():
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), width, height, True)
            fmt = Gdk.MemoryFormat.R8G8B8A8 if pb.get_has_alpha() else Gdk.MemoryFormat.R8G8B8
            tex = Gdk.MemoryTexture.new(pb.get_width(), pb.get_height(), fmt,
                                        GLib.Bytes.new(pb.get_pixels()), pb.get_rowstride())
        except Exception:
            tex = None
        GLib.idle_add(lambda: callback(tex) and False)

    threading.Thread(target=worker, daemon=True).start()


# ---------------------------------------------------------------- colors


def rgba_from_hypr(value, fallback="#888888"):
    """'ffa9a4e8 0deg' / 'rgba(33ccffee)' / '#A9A4E8' -> Gdk.RGBA of the first color."""
    c = Gdk.RGBA()
    s = str(value or "").strip()
    if (s.startswith("rgba(") or s.startswith("rgb(")) and ")" in s:
        hexs = s[s.index("(") + 1:s.index(")")]
        if len(hexs) in (6, 8) and all(ch in "0123456789abcdefABCDEF" for ch in hexs):
            a = int(hexs[6:8], 16) / 255 if len(hexs) == 8 else 1
            c.parse("#" + hexs[:6])
            c.alpha = a
            return c
    first = s.split()[0] if s else ""
    if len(first) == 8 and all(ch in "0123456789abcdefABCDEF" for ch in first):  # AARRGGBB
        c.parse("#" + first[2:])
        c.alpha = int(first[:2], 16) / 255
        return c
    if not c.parse(s):
        c.parse(fallback)
    return c


def rgba_to_hypr(c):
    return "rgba(%02x%02x%02x%02x)" % (round(c.red * 255), round(c.green * 255),
                                       round(c.blue * 255), round(c.alpha * 255))


def rgba_to_hex(c):
    return "#%02X%02X%02X" % (round(c.red * 255), round(c.green * 255), round(c.blue * 255))


# ---------------------------------------------------------------- lua


def lua_str(s):
    out = ['"']
    for ch in str(s):
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ord(ch) < 32 or ord(ch) == 127:
            out.append("\\%03d" % ord(ch))
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


LUA_KEYWORDS = {"and", "break", "do", "else", "elseif", "end", "false", "for", "function", "goto", "if",
                "in", "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while"}


def lua_key(k):
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) and k not in LUA_KEYWORDS:
        return k
    return f"[{lua_str(k)}]"


def lua_value(v, indent=0):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".") if v != int(v) else f"{v:.1f}"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "{ " + ", ".join(lua_value(x) for x in v) + " }"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{lua_key(k)} = {lua_value(x)}" for k, x in v.items()) + " }"
    return lua_str(v)


def lua_table(d, indent=1):
    """Render a nested dict as multi-line Lua table fields."""
    lines = []
    pad = "  " * indent
    for k, v in d.items():
        if isinstance(v, dict) and not v.get("__value__"):
            lines.append(f"{pad}{lua_key(k)} = {{")
            lines += lua_table(v, indent + 1)
            lines.append(f"{pad}}},")
        else:
            lines.append(f"{pad}{lua_key(k)} = {lua_value(v)},")
    return lines


def lua_syntax_error(text):
    """Return luac's complaint about `text`, or None when it parses (or luac is missing)."""
    if not shutil.which("luac"):
        return None
    try:
        p = subprocess.run(["luac", "-p", "-"], input=text, capture_output=True, text=True, timeout=10)
        return None if p.returncode == 0 else p.stderr.strip()
    except Exception:
        return None


# ---------------------------------------------------------------- widgets


def scale_row(title, subtitle, lo, hi, step, value, digits, on_change):
    row = Adw.ActionRow(title=title, subtitle=subtitle or "")
    adj = Gtk.Adjustment(lower=lo, upper=hi, step_increment=step, page_increment=step * 5,
                         value=lo if value is None else value)
    scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj, digits=digits,
                      draw_value=True, value_pos=Gtk.PositionType.LEFT, hexpand=True)
    scale.set_size_request(260, -1)
    scale.set_valign(Gtk.Align.CENTER)
    scale.connect("value-changed",
                  lambda s: on_change(round(s.get_value(), digits) if digits else int(s.get_value())))
    row.add_suffix(scale)
    row.scale = scale
    return row


def switch_row(title, subtitle, active, on_change):
    row = Adw.SwitchRow(title=title, subtitle=subtitle or "", active=bool(active))
    row.connect("notify::active", lambda r, _p: on_change(r.get_active()))
    return row


def combo_row(title, subtitle, labels, selected, on_change, values=None):
    """Combo over `labels`; on_change gets the matching entry of `values` (default: labels)."""
    values = values if values is not None else labels
    row = Adw.ComboRow(title=title, subtitle=subtitle or "", model=Gtk.StringList.new(labels))
    if selected in values:
        row.set_selected(values.index(selected))
    row.connect("notify::selected", lambda r, _p: on_change(values[r.get_selected()]))
    return row


def search_combo(title, labels, subtitle=""):
    """A drop-down over `labels` with a search field. The expression tells it what to match typed
    text against; without one (as before) the search field filtered nothing. It matches anywhere in
    a label: libadwaita's default only matches the start, so "code" missed "Visual Studio Code"."""
    return Adw.ComboRow(title=title, subtitle=subtitle or "", model=Gtk.StringList.new(labels),
                        enable_search=True, search_match_mode=Gtk.StringFilterMatchMode.SUBSTRING,
                        expression=Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"))


def spin_row(title, subtitle, lo, hi, step, value, on_change, digits=0):
    row = Adw.SpinRow.new_with_range(lo, hi, step)
    row.set_title(title)
    if subtitle:
        row.set_subtitle(subtitle)
    row.set_digits(digits)
    row.set_value(value or 0)
    row.connect("notify::value", lambda r, _p: on_change(r.get_value()))
    return row


def icon_button(icon, tooltip, on_click, css="flat"):
    b = Gtk.Button(icon_name=icon, tooltip_text=tooltip, valign=Gtk.Align.CENTER)
    if css:
        b.add_css_class(css)
    b.connect("clicked", lambda *_: on_click())
    return b


def keycap(text):
    label = Gtk.Label(label=text, valign=Gtk.Align.CENTER)
    label.add_css_class("keycap")
    return label


def confirm(win, heading, body, on_yes, label="Restore defaults", destructive=True, on_no=None):
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("ok", label)
    dialog.set_response_appearance(
        "ok", Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")

    def respond(_d, r):
        if r == "ok":
            on_yes()
        elif on_no:
            on_no()

    dialog.connect("response", respond)
    dialog.present(win)
    return dialog


def reset_group(win, title, body, on_yes, description=None, label="Restore defaults"):
    """A page-footer group holding a confirmed "Restore defaults" button."""
    group = Adw.PreferencesGroup(description=description or "")
    row = Adw.ButtonRow(title=label, start_icon_name="edit-undo-symbolic")
    row.add_css_class("destructive-action")
    row.connect("activated", lambda _r: confirm(win, title, body, on_yes))
    group.add(row)
    return group


def clear_group(group):
    """Remove every row added to an Adw.PreferencesGroup."""
    for row in list(getattr(group, "_rows", [])):
        group.remove(row)
    group._rows = []


def group_add(group, row):
    group.add(row)
    rows = getattr(group, "_rows", None)
    if rows is None:
        rows = group._rows = []
    rows.append(row)
    return row


class Page(Adw.PreferencesPage):
    """Base page: knows its window and can rebuild itself from scratch."""

    key = ""
    title = ""
    icon = ""

    def __init__(self, win):
        super().__init__(title=self.title, icon_name=self.icon)
        self.win = win
        self.build()

    def build(self):
        pass

    def rebuild(self, delay=0):
        def go():
            self.win.replace_page(self.key, type(self)(self.win))
            return False

        if delay:
            GLib.timeout_add(delay, go)
        else:
            go()

    def reset(self, done=None):
        done and done()
