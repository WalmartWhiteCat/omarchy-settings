# Omarchy Settings: notes for Claude

GTK4/libadwaita Python app that edits the user's **live** Omarchy desktop (Arch + Hyprland 0.55+,
Lua config). README.md covers what it does and every file it writes; OPEN_ITEMS.md lists open work.

## Keeping these notes true

These notes are only useful while they match the code. Whenever a change (a bug fix included)
alters any of the following, update this file, README.md and OPEN_ITEMS.md **in the same
commit**:
- what a page does or how it reaches the desktop (the Pages table), or a page's tests;
- a design decision (add it, or remove one that no longer holds), a safety rule, a known limit;
- a file or path the app reads or writes (also README's "Files it writes" table, and `backup.sh`'s
  list if it's personal data);
- a command it runs, or what an Omarchy command is assumed to print;
- how to run or write tests (test.sh, conftest, pagekit, the sandbox).

Before committing, reread the sections that touch what you changed. `tests/test_docs.py` checks
what it can mechanically (every page, class, module, test file and pagekit helper named here
exists, and every page is in the table), so a rename that forgets these notes fails the suite;
everything else is on you. Fix a wrong statement here as soon as you notice it, even if it's
unrelated to your change. Mark anything you couldn't verify as unverified rather than guessing.

## Working with the user

This is the user's own daily desktop. What they've asked for, across past sessions:
- **Bug reports:** they often run a review in another session and paste its findings. Check each
  claim against the code and Omarchy's scripts first; say which you'd fix, how, and where you
  disagree (they accept pushback when it's explained). Fix once they say go: a test for each fix
  that fails on the old code, the full suite before every commit, one commit per fix, then a plain
  summary that says what wasn't tested live. When they say "in any way you think is best", pick
  the most robust fix rather than the smallest.
- **Honesty about mistakes:** say plainly when something went wrong or a claim was wrong. They're
  fine with rewriting unpushed history to correct a commit.
- **Live checks:** you can't click or see the screen; when a fix needs eyes on the desktop, tell
  them exactly what to do and what they should see. Ask before anything that changes their real
  config, notes, reminders or settings (see "Safety while working"), and back up first.
- **Notes:** keep these notes true (below) as part of every change.
- **Pushing:** commits go to `origin` (GitHub, private) only when the user asks.

## Setting up on a fresh machine

README.md, "Moving to a fresh install", has the steps: sign in (`gh auth login && gh auth
setup-git`; both repos are private), clone github.com/WalmartWhiteCat/omarchy-settings to
`~/Work/omarchy-settings` (the Desktop Notes widget's notes point here), install the widget with
`omarchy plugin add https://github.com/WalmartWhiteCat/omarchy-desktop-notes.git --enable`, `./install.sh`, restore the user's data with
`./backup.sh --restore` (it's never in git), open the app once, then `./test.sh` (it names any
missing package). After an Omarchy update or reinstall, check the assumptions the app makes about
Omarchy's commands and files (the Pages table, "Design decisions") against the new
`/usr/share/omarchy` before trusting them; the tests use stand-ins and won't notice.

## Layout
- `omarchy-settings.py`: entry point. `osettings/__init__.py` pins the GI versions.
- `core.py`: paths, process helpers (`run`, `run_async`, `run_chain`, `spawn_detached`, `trash_file`),
  `write_atomic` (one-step replace that writes through symlinks and keeps the file's mode),
  background commands time out after `COMMAND_TIMEOUT` (120 s; `timeout=` to change it, e.g. 600
  for a theme's git clone) and then count as failed, so nothing waits on a hung command,
  Lua escaping (`lua_str`/`lua_key`/`lua_value`/`lua_table`), shared widgets, `Page` base
  (`build()`, `rebuild()`, `reset(done)`).
- `store.py`: `Store` holds everything the app owns (`settings.json`) and renders
  `~/.config/hypr/omarchy_settings.lua`. Saves are debounced (`schedule_save(after=…)`), checked with
  `luac`, written atomically, then `hyprctl reload` + `configerrors`; a save that leaves the Lua
  unchanged (pins, night light warmth) skips the reload unless `ensure_required` just added the
  require line (it returns "added"). Also `ensure_required`,
  `require_state`, `refresh_rebinds`, `omarchy_opacity_tags`.
- `binds.py`: parses Omarchy's binding files (every `.lua` in `default/hypr/bindings`, known ones
  first: `binding_files()`), reads exact key spellings by running hyprland.lua with
  a stubbed `hl` (as Omarchy's keybinding menu does), key normalisation (`code:N` = produced key).
- `pages_look.py`, `pages_system.py`, `pages_keys.py`, `pages_widgets.py`: pages. `pages_widgets.py`
  writes the Desktop Notes widget's `~/.config/desktop-notes/config.json`; the widget itself is a shell
  plugin in `~/.config/omarchy/plugins/sourced.desktop-notes` (not in this repo) that watches that file
  and clamps to the same ranges (`NOTES_LIMITS`, and `NOTES_TITLE_MAX` for the card's title), so
  change both together (`tests/test_widgets.py` compares them, and the defaults and positions,
  with the installed widget's QML; it skips when the widget isn't installed). Text, switch and drop-down settings (title, always show bells, outline, monitor) are saved at once
  (`set_now`). Outline is only a switch: the widget makes the card's border as thick as Hyprland's
  `general:border_size` (the Windows page's Border width), in the active border's colour, and
  re-reads both on every Hyprland reload (its own notes say how). The Monitor list comes from `hyprctl monitors` (`monitor_choices`). Its sliders write the
  latest values at most every 100ms while they move (a timer that isn't restarted per step), so the
  card follows them live; a debounce restarted per step wrote only once a slider stopped. `window.py`: sidebar, lazy pages,
  Restore all (`RESET_ORDER`), startup checks.

## Pages

Each page is a `Page` subclass with `key, title, icon`; `window.py` `SECTIONS` sets the sidebar
order, and pages are built only when first shown. The file a page lives in doesn't follow the
sidebar section: `pages_system.py` holds Display and Input pages too.

| Sidebar | Page (key) | Class, file | How it reaches the desktop | Page tests |
|---|---|---|---|---|
| Appearance | Theme (`theme`) | `ThemePage`, pages_look | `omarchy theme set/install`; "keep" pins re-applied by the theme-set hook | test_page_theme |
| | Theme Colors (`colors`) | `ColorsPage`, pages_look | edits `colors.toml` (overlay copy for stock themes), then `omarchy theme set` | test_page_colors, test_display_colors |
| | Background (`background`) | `BackgroundPage`, pages_look | `omarchy theme bg`; added files in `~/.config/omarchy/backgrounds/<theme>/`, moved to the Trash one at a time or several at once (`choose_remove`), then switching to another if the current one went | test_page_background, test_review_fixes |
| | Windows (`windows`) | `WindowsPage`, pages_look | `store.values` (Hyprland options as `"section:key"`, plus animations in `store.anim`), rendered into the generated Lua | test_page_windows |
| | App Rules (`rules`) | `RulesPage`, pages_look | `store.rules`, rendered into the Lua | test_page_rules |
| Display | Displays (`displays`) | `DisplaysPage`, pages_system | trial with `hyprctl eval` + watchdog; Keep saves `store.monitors` into the Lua; Restore defaults edits `monitors.lua` | test_page_displays, test_review_fixes |
| | Night Light (`nightlight`) | `NightLightPage`, pages_system | on/off and warmth via `hyprctl hyprsunset temperature`; the schedule is written to `~/.config/hypr/hyprsunset.conf` as hyprsunset profiles (each applies from its `time` until the next: "Turn on at" = `temperature`, "Turn off at" = `identity = true`), then `omarchy restart hyprsunset`; the Lua autostarts hyprsunset while scheduled | test_page_nightlight, test_review_fixes (+ autostart in test_render) |
| | Fonts and Text (`text`) | `TextPage`, pages_system | `omarchy font set`, `omarchy display text`; interface font via gsettings (pinned by the hook) | test_page_text |
| | Cursor (`cursor`) | `CursorPage`, pages_system | `store.cursor` into the Lua, gsettings, `hyprctl setcursor` | test_page_cursor |
| Input | Keyboard and Mouse (`input`) | `InputPage`, pages_system | `store.values` (`input:...` options) into the Lua; `omarchy toggle touchpad` | test_page_input |
| | Keybindings (`keys`) | `KeysPage`, pages_keys | `store.binds` (rebinds, unbinds, custom) into the Lua; parsing in `binds.py` | test_page_keys, test_keybinding_fixes, test_review_fixes, test_binds |
| System | Bar (`bar`) | `BarPage`, pages_system | `omarchy bar ...`, `omarchy plugin enable/disable`; `shell.json` only for removing the menu/media widget | test_page_bar, test_review_fixes |
| | Power and Notifications (`power`) | `PowerPage`, pages_system | `omarchy toggle ...`; idle times written straight to `shell.json` (`idle.screensaver`, `idle.lock`, in seconds; read by Omarchy's idle service, `shell/plugins/services/idle/Service.qml`); Do Not Disturb via `omarchy-shell notifications` | test_page_power, test_review_fixes |
| | Default Apps (`apps`) | `AppsPage`, pages_system | `omarchy default ...` | test_page_apps |
| | Autostart (`autostart`) | `AutostartPage`, pages_keys | `store.autostart` into the Lua | test_page_autostart |
| Widgets | Desktop Notes (`notes`) | `NotesPage`, pages_widgets | `~/.config/desktop-notes/config.json`, read live by the widget | test_widgets |

Other test files: `test_store.py` (loading, saving, the set-aside settings.json), `test_render.py`
(the generated Lua for each store section: values, cursor, monitors, rules, binds, autostart), `test_lua.py` (Lua escaping), `test_properties.py` (property tests: any settings.json, the Lua escaping read back by real Lua, rule regexes, shortcut spellings), `test_files.py` (`write_atomic`), `test_processes.py` (command timeouts), `test_core_helpers.py` (the real `run`, `run_ok`, `run_chain`, `spawn_detached`, `hypr_option`, `trash_file`, which the sandbox stubs elsewhere, with subprocess faked underneath; colors, images, theme previews), `test_window.py` (the
real window and `--page`), `test_install.py` (install.sh). README's "Files it writes" table lists
every file the app touches and how to undo it.

Every page has page-level tests. The `test_page_*.py` files build the real page and cover the
page's controls broadly (see "Kinds of tests"); the older ones in `test_review_fixes.py` use
stand-ins and each covers one past fix. New page tests should use `tests/pagekit.py`.

Pages save in two ways: through the Store (`store.values`, `rules`, `cursor`... saved after a
350ms debounce, so tests call `p.save()`), or by writing a file straight away (`shell.json` on
Power and Bar, `hyprsunset.conf`, `colors.toml`, the pin hook, the notes widget's
`config.json`), which tests read directly.

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
- `Store._clean` drops every entry `render_lua` can't render (nulls, NaN/infinity, wrong types, an
  option that is also another's section, an option outside a section), and `_save` turns any
  render error into a toast: a hand-edited settings.json must never stop the window from opening
  (it once did), nor leave an entry that fails every save. A section name that isn't a Lua name
  (`my-plugin`) is kept and written as a quoted key.
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
./test.sh                          # everything (several hundred tests, a few seconds); exit 0 = all pass
./test.sh -k window                # pytest arguments pass through
./test.sh tests/test_store.py
OSETTINGS_NESTED_HYPRLAND=1 ./test.sh tests/test_nested_hyprland.py   # opt-in, see below
HYPOTHESIS_PROFILE=explore ./test.sh tests/test_properties.py         # property tests, many new inputs
```

Tools (Arch packages):

| Tool | Package | Used for |
|---|---|---|
| `python3` with `gi`, GTK 4, libadwaita | `python-gobject`, `gtk4`, `libadwaita` | the app itself |
| `pytest`, `hypothesis` | `python-pytest`, `python-hypothesis`, or the `.venv` test.sh makes | running the tests (Hypothesis: the property tests) |
| `luac` (Lua 5.5 here) | `lua` | the only real command tests may run: checks the generated Lua |
| `lua` | `lua` | only `test_properties.py`, to read escaped values back (see below) |
| `gtk4-broadwayd` | `gtk4` | invisible display for the real-window tests (they skip without it) |
| `Hyprland`, `hyprctl` | `hyprland` | only the opt-in nested test |

`test.sh` checks these, naming the package when one is missing. The system Python has no pytest
or Hypothesis unless `python-pytest` and `python-hypothesis` are installed; without both, test.sh
makes `.venv/` (git-ignored) once with `--system-site-packages`, since `gi` can't come from pip. `uvx pytest` doesn't work: its Python
can't import `gi`.

How the sandbox works (`tests/conftest.py`):
- Every module-level path (HOME, the config, state and Hypr folders, `OMARCHY_PATH`, themes...)
  points into `tmp_path`, so the autouse `sandbox` fixture fills it: `tmp_path/home` (HOME, with
  only `.config/hypr`) and an empty `tmp_path/omarchy` exist when a test starts. To give a page a
  file to read, write it at the module's path, making its folder first (e.g.
  `ps.SHELL_JSON.parent.mkdir(parents=True)`; `~/.config/omarchy` doesn't exist yet). Don't assume `tmp_path`
  is empty. (`tests/test_install.py` uses `tmp_path` itself as the script's HOME, separate from
  the sandbox's `tmp_path/home`.) `run`, `run_async`, `run_chain`, `spawn_detached`, `trash_file` are
  stubbed and record their commands in the `sandbox` fixture (`sandbox.all_cmds()`;
  `sandbox.run_output[tuple(cmd)]` sets a command's output). Unset, `run` returns "", `run_ok`
  False, `hypr_option` / `hypr_json` None (so `store.current` gives its default) and `gsetting` "";
  `run_async` / `run_chain` never call their done callback (see `callbacks` below). `subprocess.run` / `Popen` are guarded: any real command
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
- Real pages (`tests/test_page_*.py`, using `tests/pagekit.py`). A test file starts with:
  ```python
  from osettings import pages_system as ps       # the page's module, for its paths and helpers
  from .pagekit import callbacks, needs_display, open_page  # noqa: F401  (open_page is a fixture)
  pytestmark = needs_display                     # skip without the invisible display
  ```
  `p = open_page(key, settings=None)` writes settings.json if given, opens the real window on that
  page (nameless SettingsApp, no bus) and returns helpers that use controls by their title:
  `switch(title, on)`, `choose(title, label)` (drop-down), `slide(title, value)`,
  `enter(title, text)` (text field + apply), `number(title, value)` (spinner), `press(title)`
  (button row), `click(tooltip, within=row)` (icon button), `row(title, kind=Adw.PreferencesRow)`,
  `rows(kind)`, `has_row(title)`, `search(row, text)` (type in a searchable drop-down; returns what
  it lists), `pick_found(row, label)` (choose a search result); `save()` runs the pending
  save; `saved()` is settings.json, `lua()` the generated file; `toasts` collects toasts and busy
  messages; `page` is looked up each time because pages rebuild themselves. `callbacks(monkeypatch,
  module)` records each run_async/run_chain's done callback so a test can finish a command as if it
  exited (pass `(code, out, err)` or a failures list). `installed_apps(monkeypatch, (id, name)...)` makes
  the app pickers (Autostart, the shortcut dialog) list those apps instead of the machine's. `press_key(dialog, keyval, state=0)` calls the shortcut dialog's key
  handler as that key's press would (GTK can't fake real presses; the keycode comes from the display's
  keymap, which on Broadway isn't evdev + 8). pagekit answers `hyprctl reload` /
  `configerrors` as a clean reload, so a save's "after" callbacks run. Commands' stub output comes
  from `sandbox.run_output[(cmd...)]`; use the real program's output format (read the script in
  /usr/share/omarchy/bin rather than guess). A GTK grid's selection follows keyboard focus, so
  check what a page shows (labels, marks) rather than which child is selected.
- Pages through stand-ins: `Page.__new__` plus fake win/widgets (`tests/test_review_fixes.py`).
- The real window (`tests/test_window.py`): the real `SettingsApp` with its id cleared
  (`set_application_id(None)`, `NON_UNIQUE`) and no session bus, driving `do_command_line` with a
  fake command line, then checking which pages were built (`win.stack`) and what shows. Never
  register SettingsApp with its real id in a test: it could hand the command line to the user's
  running app. `spin()` runs the GLib main loop a little after each step.
- Property tests (`tests/test_properties.py`, Hypothesis): rules that must hold for every input,
  checked on generated ones. Whatever settings.json holds (shaped like the real thing, with junk
  mixed in), the app opens, renders Lua that `luac` accepts and can write, and saving then loading
  changes nothing more; `lua_str`/`lua_value`/`lua_key`/`lua_table` read back through the real
  `lua` as the same value; a rule's regex matches its class literally; shortcut spellings agree.
  The `lua` read-back runs through `REAL_POPEN` (past the guard) and loads the text in an empty
  environment, so even a broken escape can't reach `os` or `io`. The "repeatable" profile
  (conftest; the default) gives the same examples every run, so ./test.sh's answer doesn't
  change; `HYPOTHESIS_PROFILE=explore` tries thousands of new ones and keeps any failure in
  `.hypothesis/` (git-ignored) to retry first. A failure prints the smallest input that shows it:
  add that input as an example test with the fix. They found three ways a hand edit stopped
  every save (2026-10-11). When `_clean` or `render_lua` learns a new part of settings.json, add
  it to the `settings` strategy.
- The nested Hyprland test (opt-in) opens a small Hyprland window inside the user's session for a
  few seconds and checks `hyprctl configerrors` for a generated file. Ask the user before running
  it.

Habits that caught real bugs:
- See a new test fail on the old code (`git stash -- <file>`, run it, `git stash pop`), or plant
  bugs one at a time in the code it covers and check each is caught (put the file back after).
  Done for all of store.py, core.py, binds.py and pages_widgets.py on 2026-10-11 (every
  comparison, constant, `and`/`or`, `not` and return value changed in turn, in a copy, with the
  suite run against each): what still goes uncaught is styling, docstrings, GLib callback return
  values, thread flags, and equivalent forms.
  A plant that changes nothing (e.g. GTK already clamps the value) can't be caught; one that
  changes behaviour and isn't caught is a gap in the test. Run these through `./test.sh`: it sets
  `PYTHONDONTWRITEBYTECODE=1`, because a cached .pyc is matched only by the source's mtime (whole
  seconds) and size, so a same-length edit within a second would keep running the old code. If
  you call pytest directly, set it yourself (and delete stale `__pycache__` folders).
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
