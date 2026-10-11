"""Reading Omarchy's default keybindings and normalising key combinations."""

import os
import re
import shutil
import subprocess

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk  # noqa: E402

from .core import OMARCHY_PATH, hypr_json, run

# Omarchy's binding files in their usual order; any others in the folder are read too.
BIND_FILES = ["applications", "clipboard", "media", "tiling", "utilities", "voxtype"]
FILE_TITLES = {"applications": "Applications", "clipboard": "Clipboard", "media": "Media keys",
               "tiling": "Windows and workspaces", "utilities": "Menus and utilities",
               "voxtype": "Dictation", "other": "Other"}
MODMASK = [(64, "SUPER"), (1, "SHIFT"), (4, "CTRL"), (8, "ALT")]
# Keys without a modifier that are fine as shortcuts on their own.
BARE_OK = re.compile(r"^(F\d{1,2}|XF86\w+|Print|Pause|Scroll_Lock|Menu|Insert)$", re.I)
_code_names = {}


def keycode_name(code):
    """Keysym name (lowercase) of an xkb keycode on the current keymap, e.g. 10 -> '1'."""
    if code not in _code_names:
        name = None
        try:
            display = Gdk.Display.get_default()
            ok, _keys, keyvals = display.map_keycode(code) if display else (False, None, None)
            if ok and keyvals:
                name = (Gdk.keyval_name(keyvals[0]) or "").lower() or None
        except Exception:
            name = None
        _code_names[code] = name
    return _code_names[code]

MOD_ALIASES = {"SUPER": "SUPER", "WIN": "SUPER", "MOD4": "SUPER", "LOGO": "SUPER",
               "SHIFT": "SHIFT", "CTRL": "CTRL", "CONTROL": "CTRL", "ALT": "ALT", "MOD1": "ALT"}
MOD_ORDER = ["SUPER", "SHIFT", "CTRL", "ALT"]
LUA_WORDS = {"true", "false", "nil", "and", "or", "not", "o", "hl", "tostring", "function", "end"}
CALL_RE = re.compile(r'^(o\.bind|o\.bind_toggle|hl\.bind)\(\s*"([^"]+)"\s*,\s*(?:"([^"]*)"|nil)')


def binding_files():
    """Omarchy's binding files as (group, path): the known ones in their usual order, then any
    others (a file Omarchy added or renamed), so none of its shortcuts go missing."""
    folder = OMARCHY_PATH / "default/hypr/bindings"
    try:
        found = {p.stem: p for p in folder.glob("*.lua") if p.is_file()}
    except OSError:
        return []
    order = [n for n in BIND_FILES if n in found] + sorted(n for n in found if n not in BIND_FILES)
    return [(n, found[n]) for n in order]


def group_title(group):
    return FILE_TITLES.get(group) or re.sub(r"[-_]+", " ", group).strip().capitalize()


def normalize(keys):
    """'SUPER SHIFT + Return' / 'SUPER + SHIFT + RETURN' -> ('ALT'.., 'return') comparable tuple.

    `code:N` keys compare equal to the key they produce on the current keymap, so
    SUPER + code:10 and SUPER + 1 clash; switch bindings compare as a whole."""
    keys = keys.strip()
    if keys.lower().startswith("switch:"):
        return (), keys.lower()
    parts = [p for p in re.split(r"[+\s]+", keys) if p]
    mods, key = set(), ""
    for p in parts:
        up = p.upper()
        if up in MOD_ALIASES:
            mods.add(MOD_ALIASES[up])
        else:
            key = p.lower()
    m = re.fullmatch(r"code:(\d+)", key)
    if m:
        key = keycode_name(int(m.group(1))) or key
    return tuple(m for m in MOD_ORDER if m in mods), key


def canonical(keys):
    """Display spelling 'SUPER CTRL ALT + J' -> bind spelling 'SUPER + CTRL + ALT + J'."""
    if keys.strip().lower().startswith("switch:"):
        return keys.strip()
    parts = [p for p in re.split(r"[+\s]+", keys.strip()) if p]
    mods = [MOD_ALIASES[p.upper()] for p in parts if p.upper() in MOD_ALIASES]
    rest = [p for p in parts if p.upper() not in MOD_ALIASES]
    return " + ".join([m for m in MOD_ORDER if m in mods] + rest[-1:])


def key_count(keys):
    """How many non-modifier keys a combination names (a shortcut needs exactly one)."""
    if keys.strip().lower().startswith("switch:"):
        return 1
    return sum(1 for p in re.split(r"[+\s]+", keys.strip()) if p and p.upper() not in MOD_ALIASES)


def has_modifier(keys):
    return bool(normalize(keys)[0])


def bare_ok(keys):
    """A shortcut needs Super, Ctrl or Alt, unless it's an F-key, media key or similar."""
    mods, key = normalize(keys)
    if set(mods) - {"SHIFT"}:
        return True
    name = re.split(r"[+\s]+", keys.strip())[-1]
    return bool(BARE_OK.match(name))


def pretty(keys):
    mods, key = normalize(keys)
    names = {"return": "Enter", "space": "Space", "escape": "Esc", "backspace": "Backspace",
             "comma": ",", "period": ".", "slash": "/", "tab": "Tab", "print": "PrtSc",
             "left": "←", "right": "→", "up": "↑", "down": "↓", "home": "Home"}
    m = re.match(r"code:(\d+)$", key)
    if m and 10 <= int(m.group(1)) <= 19:
        k = str((int(m.group(1)) - 9) % 10)
    elif key.startswith("switch:"):
        k = key.split(":")[-1].title()
    else:
        names.update({"minus": "-", "equal": "=", "bracketleft": "[", "bracketright": "]"})
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


# Runs the user's hyprland.lua with Hyprland's API stubbed out and prints every described
# bind's key exactly as written in the source, the same way Omarchy's keybinding menu does.
# Hyprland itself reports code:N binds without their key, so this is the only place the
# real spelling (e.g. SUPER + code:10) can be read from.
SOURCE_SCAN = r"""
local noop
noop = setmetatable({}, { __index = function() return noop end, __call = function() return noop end })
local function proxy() return noop end
-- Dispatchers must come back as plain tables: Omarchy's helpers inspect their fields.
local function dsp()
  return setmetatable({}, { __index = function() return dsp() end, __call = function() return {} end })
end
hl = setmetatable({
  dsp = dsp(),
  bind = function(keys, _dispatcher, opts)
    if type(opts) == "table" and opts.description and opts.description ~= "" then
      print(tostring(keys) .. "\t" .. opts.description)
    end
    return noop
  end,
  get_config = function() return nil end,
}, { __index = proxy })
local config = os.getenv("HOME") .. "/.config/hypr/hyprland.lua"
local file = io.open(config, "r")
if file then file:close(); pcall(dofile, config) end
"""


def source_bind_spellings():
    """description -> [keys as written in the config source]."""
    out = {}
    if not shutil.which("lua"):
        return out
    try:
        p = subprocess.run(["lua", "-"], input=SOURCE_SCAN, capture_output=True, text=True, timeout=10,
                           env=dict(os.environ))
    except Exception:
        return out
    for line in p.stdout.splitlines():
        keys, _, desc = line.partition("\t")
        if keys and desc:
            out.setdefault(desc, []).append(keys)
    return out


def live_bind_spellings():
    """description -> [bind spelling] from Hyprland's live binds, using code:N where the bind
    was made by keycode (Omarchy's workspace and resize keys), so unbinding it matches."""
    out = {}
    for b in hypr_json("binds") or []:
        if not isinstance(b, dict) or b.get("mouse") or not b.get("description"):
            continue
        key = f"code:{b['keycode']}" if b.get("keycode") else b.get("key", "")
        if not key:
            continue
        mods = [name for bit, name in MODMASK if b.get("modmask", 0) & bit]
        out.setdefault(b["description"], []).append(" + ".join(mods + [key]))
    return out


def parse_default_binds(owned=(), disabled_info=None):
    """List of {keys, description, line, guard, rebindable, group} for Omarchy's bindings.

    `owned` are normalized keys the app binds itself (custom shortcuts, moved ones): rows from
    Omarchy's printed list with those keys are the app's own and are left out.
    `disabled_info` maps keys the app turned off to their description, so "Other" bindings
    that are currently unbound (and so missing from the printed list) can still be listed."""
    out = []
    seen = set()
    for name, path in binding_files():
        try:
            text = path.read_text()
        except Exception:
            continue
        stack = []  # (kind, condition) of blocks currently open
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("--"):
                continue
            m = CALL_RE.match(line)
            if m:
                keys, desc = m.group(2), m.group(3)
                guards = [c for k, c in stack if k == "if"]
                safe = (all(k == "if" for k, _ in stack) and _rebindable(line)
                        and all(_rebindable(g) for g in guards)
                        and not keys.lower().startswith("switch:") and "mouse:" not in keys.lower())
                out.append({"keys": keys, "description": desc or "", "line": line,
                            "guard": " and ".join(f"({g})" for g in guards) or None,
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
                    cond = None
                    if kind == "if":
                        mc = re.match(r"^if\s+(.*?)\s+then\s*$", line)
                        cond = mc.group(1) if mc else "false"  # unknown shape: never lifted out
                    stack.append((kind, cond))
            elif re.match(r"^end\b", code) and stack:
                stack.pop()
    # Bindings built in loops/functions only show up in Omarchy's printed list.
    owned = set(owned)
    spellings = {}
    for source in (source_bind_spellings(), live_bind_spellings()):
        for desc, keys in source.items():
            spellings.setdefault(desc, []).extend(keys)
    for row in run(["omarchy", "menu", "keybindings", "--print"]).splitlines():
        if "→" not in row:
            continue
        shown, desc = [x.strip() for x in row.split("→", 1)]
        n = normalize(shown)
        if n in seen or n in owned:
            continue
        keys = next((s for s in spellings.get(desc, []) if normalize(s) == n), canonical(shown))
        seen.add(n)
        out.append({"keys": keys, "description": desc, "line": None, "guard": None, "rebindable": False,
                    "group": "other"})
    for keys, desc in (disabled_info or {}).items():
        if normalize(keys) not in seen:
            seen.add(normalize(keys))
            out.append({"keys": keys, "description": desc, "line": None, "guard": None, "rebindable": False,
                        "group": "other"})
    return out


def siblings(defaults, b):
    """Omarchy bindings on the same key as `b` (e.g. ALT + TAB's two actions), `b` included.
    Hyprland can only unbind a key as a whole, so they move and turn off together."""
    if not b.get("line"):
        return [b]
    return [d for d in defaults if d.get("line") and d["keys"] == b["keys"]]


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
