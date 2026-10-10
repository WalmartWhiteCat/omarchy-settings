# Omarchy Settings: notes for Claude

GTK4/libadwaita Python app that edits the user's **live** Omarchy desktop (Arch + Hyprland 0.55+,
Lua config). README.md covers what it does and every file it writes; OPEN_ITEMS.md lists open work.

## Layout
- `omarchy-settings.py`: entry point. `osettings/__init__.py` pins the GI versions.
- `core.py`: paths, process helpers (`run`, `run_async`, `run_chain`, `spawn_detached`, `trash_file`),
  Lua escaping (`lua_str`/`lua_key`/`lua_value`/`lua_table`), shared widgets, `Page` base
  (`build()`, `rebuild()`, `reset(done)`).
- `store.py`: `Store` holds everything the app owns (`settings.json`) and renders
  `~/.config/hypr/omarchy_settings.lua`. Saves are debounced (`schedule_save(after=…)`), checked with
  `luac`, written atomically, then `hyprctl reload` + `configerrors`. Also `ensure_required`,
  `require_state`, `refresh_rebinds`, `omarchy_opacity_tags`.
- `binds.py`: parses Omarchy's binding files, reads exact key spellings by running hyprland.lua with
  a stubbed `hl` (as Omarchy's keybinding menu does), key normalisation (`code:N` = produced key).
- `pages_look.py`, `pages_system.py`, `pages_keys.py`, `pages_widgets.py`: pages. `pages_widgets.py`
  writes the Desktop Notes widget's `~/.config/desktop-notes/config.json`; the widget itself is a shell
  plugin in `~/.config/omarchy/plugins/sourced.desktop-notes` (not in this repo) that watches that file
  and clamps to the same ranges (`NOTES_LIMITS`), so change both together. `window.py`: sidebar, lazy pages,
  Restore all (`RESET_ORDER`), startup checks.

## Pages

Each page is a `Page` subclass with `key, title, icon`; `window.py` `SECTIONS` sets the sidebar
order, and pages are built only when first shown. The file a page lives in doesn't follow the
sidebar section: `pages_system.py` holds Display and Input pages too.

| Sidebar | Page (key) | Class, file | How it reaches the desktop | Page tests |
|---|---|---|---|---|
| Appearance | Theme (`theme`) | `ThemePage`, pages_look | `omarchy theme set/install`; "keep" pins re-applied by the theme-set hook | none |
| | Theme Colors (`colors`) | `ColorsPage`, pages_look | edits `colors.toml` (overlay copy for stock themes), then `omarchy theme set` | test_display_colors |
| | Background (`background`) | `BackgroundPage`, pages_look | `omarchy theme bg`; added files in `~/.config/omarchy/backgrounds/<theme>/` | test_review_fixes |
| | Windows (`windows`) | `WindowsPage`, pages_look | `store.values` (Hyprland options as `"section:key"`, plus animations in `store.anim`), rendered into the generated Lua | none (Lua: test_render) |
| | App Rules (`rules`) | `RulesPage`, pages_look | `store.rules`, rendered into the Lua | none (Lua: test_render) |
| Display | Displays (`displays`) | `DisplaysPage`, pages_system | trial with `hyprctl eval` + watchdog; Keep saves `store.monitors` into the Lua; Restore defaults edits `monitors.lua` | test_review_fixes |
| | Night Light (`nightlight`) | `NightLightPage`, pages_system | on/off and warmth via `hyprctl hyprsunset temperature`; the schedule is written to `~/.config/hypr/hyprsunset.conf` as hyprsunset profiles (each applies from its `time` until the next: "Turn on at" = `temperature`, "Turn off at" = `identity = true`), then `omarchy restart hyprsunset`; the Lua autostarts hyprsunset while scheduled | test_review_fixes (+ autostart in test_render) |
| | Fonts and Text (`text`) | `TextPage`, pages_system | `omarchy font set`, `omarchy display text`; interface font via gsettings (pinned by the hook) | none |
| | Cursor (`cursor`) | `CursorPage`, pages_system | `store.cursor` into the Lua, gsettings, `hyprctl setcursor` | none (Lua: test_render) |
| Input | Keyboard and Mouse (`input`) | `InputPage`, pages_system | `store.values` (`input:...` options) into the Lua; `omarchy toggle touchpad` | none (Lua: test_render) |
| | Keybindings (`keys`) | `KeysPage`, pages_keys | `store.binds` (rebinds, unbinds, custom) into the Lua; parsing in `binds.py` | test_keybinding_fixes, test_review_fixes, test_binds |
| System | Bar (`bar`) | `BarPage`, pages_system | `omarchy bar ...`, `omarchy plugin enable/disable`; `shell.json` only for removing the menu/media widget | test_review_fixes |
| | Power and Notifications (`power`) | `PowerPage`, pages_system | `omarchy toggle ...`; idle times in `shell.json`; Do Not Disturb via `omarchy-shell notifications` | test_review_fixes |
| | Default Apps (`apps`) | `AppsPage`, pages_system | `omarchy default ...` | none |
| | Autostart (`autostart`) | `AutostartPage`, pages_keys | `store.autostart` into the Lua | none (Lua: test_render) |
| Widgets | Desktop Notes (`notes`) | `NotesPage`, pages_widgets | `~/.config/desktop-notes/config.json`, read live by the widget | test_widgets |

Other test files: `test_store.py` (loading, saving, the set-aside settings.json), `test_render.py`
(the generated Lua for each store section: values, cursor, monitors, rules, binds, autostart), `test_lua.py` (Lua escaping), `test_window.py` (the
real window and `--page`), `test_install.py` (install.sh). README's "Files it writes" table lists
every file the app touches and how to undo it.

Pages marked "none" have no tests of the page itself: a bug in how they read a widget or call a
command won't be caught. When fixing one, add the first test for it in `test_review_fixes.py`
style (a `Page.__new__` stand-in with a fake win; see `night_page` / `FakeWin` there).

## Design decisions: don't "fix" these
- Each part of the generated Lua runs in its own `section()` pcall, so one bad entry can't break
  the rest of Hyprland's config.
- Use the `omarchy` CLI wherever a command exists; never edit `/usr/share/omarchy`. Read it freely to
  check assumptions (the Omarchy skill has details).
- Rebinding refuses lines inside loops/functions, lid-switch and mouse binds; a moved line keeps its
  `if` condition. Bindings sharing a key move and turn off together (Hyprland unbinds keys whole).
- Unbinds reuse the exact source spelling (Hyprland's unbind is case-sensitive and `SUPER + 1` does
  not remove a `SUPER + code:10` bind; verified live).
- A commented-out `require("hypr.omarchy_settings")` means the user switched the app off: never
  re-add it, only warn. Missing entirely: add it after `hypr.looknfeel`.
- Built-in laptop panels (eDP/LVDS/DSI) are never saved as off; Omarchy's lid logic owns that.
- Displays: trials are live (`hyprctl eval`), saved only on Keep; a detached watchdog with a
  per-trial marker reloads Hyprland if the app dies.
- Stock themes are never edited; color edits go to `~/.config/omarchy/themes`.
- An unreadable settings.json is set aside, never replaced by the legacy file or silently wiped.
- `omarchy toggle …` commands flip state: check the current state and only call them when it
  differs. `omarchy toggle bar off` *shows* the bar (it removes the bar-off flag).

## Safety while working
- Never change the live desktop to test something unless the user agrees: no `hyprctl
  reload/eval/dispatch/keyword/setcursor`, no state-changing `omarchy` commands, no `gsettings
  set/reset`, no writes to `~/.config` or `~/.local/state`. Read-only `hyprctl … -j`, `omarchy …
  --help`, `luac -p` are fine. If a brief live check is agreed, use values identical to the current
  state and restore afterwards.
- Tests never touch the live desktop (see "Tests"); keep it that way.

## Tests

Run from this folder:

```bash
./test.sh                          # everything; exit status 0 only if all pass (~530 tests, ~1s)
./test.sh -k window                # pytest arguments pass through
./test.sh tests/test_store.py
OSETTINGS_NESTED_HYPRLAND=1 ./test.sh tests/test_nested_hyprland.py   # opt-in, see below
```

Tools (Arch packages):

| Tool | Package | Used for |
|---|---|---|
| `python3` with `gi`, GTK 4, libadwaita | `python-gobject`, `gtk4`, `libadwaita` | the app itself |
| `pytest` | `python-pytest`, or the `.venv` test.sh makes | running the tests |
| `luac` (Lua 5.5 here) | `lua` | the only real command tests may run: checks the generated Lua |
| `gtk4-broadwayd` | `gtk4` | invisible display for the real-window tests (they skip without it) |
| `Hyprland`, `hyprctl` | `hyprland` | only the opt-in nested test |

`test.sh` checks these, naming the package when one is missing. The system Python has no pytest
unless `python-pytest` is installed; then test.sh makes `.venv/` (git-ignored) once with
`--system-site-packages`, since `gi` can't come from pip. `uvx pytest` doesn't work: its Python
can't import `gi`.

How the sandbox works (`tests/conftest.py`):
- Every module-level path (HOME, the config, state and Hypr folders, `OMARCHY_PATH`, themes...)
  points into `tmp_path`, so the autouse `sandbox` fixture fills it: `tmp_path/home` (HOME, with
  `.config/hypr`) and `tmp_path/omarchy` already exist when a test starts. Don't assume `tmp_path`
  is empty. (`tests/test_install.py` uses `tmp_path` itself as the script's HOME, separate from
  the sandbox's `tmp_path/home`.) `run`, `run_async`, `run_chain`, `spawn_detached`, `trash_file` are
  stubbed and record their commands in the `sandbox` fixture (`sandbox.all_cmds()`;
  `sandbox.run_output` sets stub output). `subprocess.run` / `Popen` are guarded: any real command
  but `luac` fails the test. Stub any new helper that touches the system.
- Before GTK loads, conftest starts `gtk4-broadwayd` on a free display (`:90`-`:99`, bound to
  127.0.0.1) and sets `GDK_BACKEND=broadway`, so nothing can draw on the desktop. Display `:N`
  listens on `$XDG_RUNTIME_DIR/broadway<N+1>.socket`. A socket nothing listens on (left by a killed
  run) is removed and reused; broadwayd exits with the test run (`PR_SET_PDEATHSIG`) and its socket
  is removed at exit. `HEADLESS` says whether it started; `tests/test_window.py` skips without it.
- `DBUS_SESSION_BUS_ADDRESS` points at nowhere, so tests can't reach the user's services, and a
  GApplication registers locally.
- conftest is imported twice (as `conftest` and `tests.conftest`); module-level setup must cope
  (the display start checks `OSETTINGS_TEST_BROADWAY`). `REAL_RUN` goes through the guarded
  `Popen`, so a test that must run something real (`tests/test_install.py` runs install.sh with
  HOME in tmp_path) uses `REAL_POPEN`.

Kinds of tests:
- Pages through stand-ins: `Page.__new__` plus fake win/widgets (`tests/test_review_fixes.py`).
- The real window (`tests/test_window.py`): the real `SettingsApp` with its id cleared
  (`set_application_id(None)`, `NON_UNIQUE`) and no session bus, driving `do_command_line` with a
  fake command line, then checking which pages were built (`win.stack`) and what shows. Never
  register SettingsApp with its real id in a test: it could hand the command line to the user's
  running app. `spin()` runs the GLib main loop a little after each step.
- The nested Hyprland test (opt-in) opens a small Hyprland window inside the user's session for a
  few seconds and checks `hyprctl configerrors` for a generated file. Ask the user before running
  it.

Habits that caught real bugs:
- See a new test fail on the old code (`git stash -- <file>`, run it, `git stash pop`).
- Commit only when the test run's exit status is 0, never on grepped or tailed output (a
  pipeline's status is its last command's).

Working in a copy (`cp -a`) is fine for experiments; delete its `tests/__pycache__` and
`.pytest_cache` first (they report the original's paths), and let `./test.sh` make the copy its
own `.venv` (a copied one has the original's paths baked in).

## Debugging on the live desktop

- Only one instance runs (`org.omarchy.Settings`): starting it again hands the command line to the
  running one. To try new code, close the open window first.
- Start it from a terminal (`python3 omarchy-settings.py`, or `omarchy-settings --page notes`) to
  see tracebacks: PyGObject prints exceptions in GTK callbacks and carries on, so the window may
  just look stuck.
- Its files: `~/.config/omarchy-settings/settings.json` (an unreadable one is moved to
  `settings.json.broken-<time>` and the app starts fresh with a toast), and the generated
  `~/.config/hypr/omarchy_settings.lua` (checked with `luac -p` before writing; after
  `hyprctl reload` the app reads `hyprctl configerrors` and shows the first error as a toast).
  Both are read-only for debugging: don't edit them while the app runs.
- `hyprctl configerrors` and `luac -p ~/.config/hypr/omarchy_settings.lua` are safe read-only
  checks. `configerrors` reports the whole config as of the last reload, so it's stale if the
  file changed since; `luac` (Lua 5.5 here) only checks syntax, and Hyprland's own Lua may differ.
  The only full check without touching the live session is the opt-in nested Hyprland test. Whether `hyprland.lua` still requires the file: look for
  `require("hypr.omarchy_settings")` (commented out = the user switched the app off).
- The Desktop Notes widget's own notes (tests, data files, log) are in its folder:
  `~/.config/omarchy/plugins/sourced.desktop-notes/CLAUDE.md`.

## Conventions
- One commit per fix, message explaining the bug and the fix, ending with the Co-Authored-By line
  from the session's attribution instructions. `./test.sh` must exit 0 before every commit.
- When several fixes touch one file, stage them separately and check each staged tree imports;
  don't use `git apply --unidiff-zero` (it misplaced code once).
- Match the existing style: plain sentences in UI text, comments explain why, not what.
