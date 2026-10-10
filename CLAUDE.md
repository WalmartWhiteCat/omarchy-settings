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
- Tests (`python3 -m pytest`) are sandboxed by `tests/conftest.py`: all paths go to tmp_path, real
  commands other than `luac` fail the test, the Trash and keymap are stubbed. Keep it that way:
  stub any new helper that touches the system.
- GTK pages are tested through stand-ins (`Page.__new__` plus fake win/widgets), see
  `tests/test_review_fixes.py`. The real window can be built too (`tests/test_window.py`):
  conftest runs GTK on an invisible Broadway display and points the session bus at nowhere, so
  nothing draws on the desktop or reaches the user's services. Never register SettingsApp with
  its real id in a test.
- The system Python has no pytest: use a venv made with `--system-site-packages` (so it sees
  `gi`) and `pip install pytest` in it. `uvx pytest` can't import `gi`.
- Commit only when the test run's exit status is 0, never on its grepped or tailed output.

## Conventions
- One commit per fix, message explaining the bug and the fix, ending with the Co-Authored-By line
  from the session's attribution instructions. Run the **full** test suite before every commit.
- When several fixes touch one file, stage them separately and check each staged tree imports;
  don't use `git apply --unidiff-zero` (it misplaced code once).
- Match the existing style: plain sentences in UI text, comments explain why, not what.
