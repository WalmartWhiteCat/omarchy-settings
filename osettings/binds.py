"""Reading Omarchy's default keybindings and normalising key combinations."""

import re

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk  # noqa: E402

from .core import OMARCHY_PATH, run

BIND_FILES = ["applications", "clipboard", "media", "tiling", "utilities", "voxtype"]
FILE_TITLES = {"applications": "Applications", "clipboard": "Clipboard", "media": "Media keys",
               "tiling": "Windows and workspaces", "utilities": "Menus and utilities",
               "voxtype": "Dictation", "other": "Other"}

MOD_ALIASES = {"SUPER": "SUPER", "WIN": "SUPER", "MOD4": "SUPER", "LOGO": "SUPER",
               "SHIFT": "SHIFT", "CTRL": "CTRL", "CONTROL": "CTRL", "ALT": "ALT", "MOD1": "ALT"}
MOD_ORDER = ["SUPER", "SHIFT", "CTRL", "ALT"]
LUA_WORDS = {"true", "false", "nil", "and", "or", "not", "o", "hl", "tostring", "function", "end"}
CALL_RE = re.compile(r'^(o\.bind|o\.bind_toggle|hl\.bind)\(\s*"([^"]+)"\s*,\s*(?:"([^"]*)"|nil)')


def normalize(keys):
    """'SUPER SHIFT + Return' / 'SUPER + SHIFT + RETURN' -> ('ALT'.., 'return') comparable tuple."""
    parts = [p for p in re.split(r"[+\s]+", keys.strip()) if p]
    mods, key = set(), ""
    for p in parts:
        up = p.upper()
        if up in MOD_ALIASES:
            mods.add(MOD_ALIASES[up])
        else:
            key = p.lower()
    return tuple(m for m in MOD_ORDER if m in mods), key


def pretty(keys):
    mods, key = normalize(keys)
    names = {"return": "Enter", "space": "Space", "escape": "Esc", "backspace": "Backspace",
             "comma": ",", "period": ".", "slash": "/", "tab": "Tab", "print": "PrtSc",
             "left": "←", "right": "→", "up": "↑", "down": "↓", "home": "Home"}
    m = re.match(r"code:(\d+)$", key)
    if m and 10 <= int(m.group(1)) <= 19:
        k = str((int(m.group(1)) - 9) % 10)
    else:
        k = names.get(key, key.upper() if len(key) == 1 else key[:1].upper() + key[1:])
    return " + ".join([{"SUPER": "Super", "SHIFT": "Shift", "CTRL": "Ctrl", "ALT": "Alt"}[x] for x in mods] + [k])


def _strip_strings(s):
    return re.sub(r'"(?:\\.|[^"\\])*"', '""', s)


def _rebindable(line):
    """A single-line call whose action only uses literals and the o./hl. helpers."""
    body = _strip_strings(line)
    if body.count("(") != body.count(")") or body.count("{") != body.count("}"):
        return False
    for ident in re.findall(r"(?<![\w.])([A-Za-z_]\w*)", body):
        if ident in LUA_WORDS:
            continue
        # table keys like `omarchy = ` / `direction =` are fine
        if re.search(rf"(?<![\w.]){ident}\s*=(?!=)", body):
            continue
        return False
    return True


def parse_default_binds():
    """List of {keys, description, line, rebindable, group} from Omarchy's binding files."""
    out = []
    seen = set()
    for name in BIND_FILES:
        try:
            text = (OMARCHY_PATH / f"default/hypr/bindings/{name}.lua").read_text()
        except Exception:
            continue
        stack = []  # block kinds currently open
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("--"):
                continue
            m = CALL_RE.match(line)
            if m:
                keys, desc = m.group(2), m.group(3)
                safe = "for" not in stack and "function" not in stack and _rebindable(line)
                out.append({"keys": keys, "description": desc or "", "line": line,
                            "rebindable": safe, "group": name})
                seen.add(normalize(keys))
            # crude block tracking so we never lift a line out of a loop or function;
            # strings are blanked first so a description like "function(s)" can't open a block
            code = _strip_strings(line)
            opens = re.match(r"^(for|while|if|local function|function)\b", code) or \
                re.search(r"=\s*function\b", code) or re.search(r"\bfunction\s*\(", code)
            if opens:
                kind = "if" if code.startswith("if") else ("for" if code.startswith(("for", "while")) else "function")
                if not re.search(r"\bend\)?\s*$", code):
                    stack.append(kind)
            elif re.match(r"^end\b", code) and stack:
                stack.pop()
    # Bindings built in loops/functions only show up in Omarchy's printed list.
    for row in run(["omarchy", "menu", "keybindings", "--print"]).splitlines():
        if "→" not in row:
            continue
        keys, desc = [x.strip() for x in row.split("→", 1)]
        if normalize(keys) in seen:
            continue
        seen.add(normalize(keys))
        out.append({"keys": keys, "description": desc, "line": None, "rebindable": False, "group": "other"})
    return out


def keys_from_event(keycode, state):
    """Hyprland key string for a key press, or None for a lone modifier."""
    display = Gdk.Display.get_default()
    ok, _keys, keyvals = display.map_keycode(keycode)
    if not ok or not keyvals:
        return None
    keyval = keyvals[0]
    name = Gdk.keyval_name(keyval)
    if not name or name.startswith(("Shift", "Control", "Alt", "Super", "Meta", "Hyper", "ISO_Level")):
        return None
    if len(name) == 1:
        name = name.upper()
    mods = []
    if state & Gdk.ModifierType.SUPER_MASK:
        mods.append("SUPER")
    if state & Gdk.ModifierType.SHIFT_MASK:
        mods.append("SHIFT")
    if state & Gdk.ModifierType.CONTROL_MASK:
        mods.append("CTRL")
    if state & Gdk.ModifierType.ALT_MASK:
        mods.append("ALT")
    return " + ".join(mods + [name])
