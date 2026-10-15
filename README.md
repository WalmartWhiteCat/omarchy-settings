# Omarchy Settings

A GTK4/libadwaita settings app for [Omarchy](https://omarchy.org/) (Arch Linux + Hyprland). It changes
your desktop's look and feel from one window instead of hand-editing config files.

| Section | Pages |
|---|---|
| Appearance | Theme, Theme Colors, Background, Windows, App Rules |
| Display | Displays, Night Light, Fonts and Text, Cursor |
| Input | Keyboard and Mouse, Keybindings |
| System | Bar, Power and Notifications, Default Apps, Autostart |
| Widgets | Desktop Notes (look and position of the `sourced.desktop-notes` shell widget) |

Every page has a **Restore defaults** button, and the menu (☰) has **Restore all defaults…**.

## Requirements

An Omarchy install with Hyprland's Lua config (Hyprland 0.55+). Everything else the app uses
(Python 3, PyGObject, GTK 4, libadwaita, `lua`/`luac`, `jq`) comes with Omarchy.

## Install and run

```bash
./install.sh            # adds "Omarchy Settings" to the app launcher and an omarchy-settings command
./install.sh --uninstall
python3 omarchy-settings.py   # or run it directly
omarchy-settings --page notes # open on a page (install.sh links the command into ~/.local/bin)
```

## Moving to a fresh install

Your settings and notes aren't in git. Before reinstalling, save them, and keep the archive
somewhere that survives (not in the repo):

```bash
./backup.sh --list          # what it saves: the app's settings, night light schedule, shell.json,
                            # themes and backgrounds you added, the notes widget's look and notes
./backup.sh                 # writes ~/omarchy-personal-<date>.tar.gz
```

On the fresh install:

```bash
# 0. Both repos are private: sign in so git can clone them
gh auth login && gh auth setup-git

# 1. The app, where its notes expect it (the Desktop Notes widget's notes point here)
git clone https://github.com/WalmartWhiteCat/omarchy-settings.git ~/Work/omarchy-settings
cd ~/Work/omarchy-settings && ./install.sh

# 2. The Desktop Notes widget: Omarchy clones it into ~/.config/omarchy/plugins/sourced.desktop-notes
#    and enables it (later, `omarchy plugin update` pulls new commits)
omarchy plugin add https://github.com/WalmartWhiteCat/omarchy-desktop-notes.git --enable

# 3. Your data (files already there are kept as <name>.~1~)
./backup.sh --restore ~/omarchy-personal-<date>.tar.gz

# 4. Open Omarchy Settings once: it regenerates its Hyprland config from settings.json, adds its
#    line to hyprland.lua and reloads. Then `omarchy restart shell` for the widget.
```

Things that live outside files come back only when set again: the cursor theme and size, light or
dark app style, icon theme and interface font (GNOME settings), the monospace font and text size,
Do Not Disturb, Keep awake, and your default apps. Pick them again in the app. If the new Omarchy
is newer, compare `~/.config/omarchy/shell.json` with the `shell.json.~1~` it replaced before
keeping it, and run `./test.sh` in both repos (it names any package to install).

## How it changes your system

Wherever Omarchy has a command for something (`omarchy theme set`, `omarchy font set`,
`omarchy bar …`, `omarchy toggle …`, `omarchy default …`), the app runs that command, so it behaves
like Omarchy's own menus. Everything else goes into files it owns, or small, backed-up edits.

### Files it writes

| File | What and why | How to undo |
|---|---|---|
| `~/.config/omarchy-settings/settings.json` | Everything the app manages | Delete it (the app starts fresh) |
| `~/.config/hypr/omarchy_settings.lua` | Generated Hyprland config: window look, input, monitors, rules, shortcuts, autostart, cursor | Delete it, or restore defaults in the app |
| `~/.config/hypr/hyprland.lua` | One added line, `require("hypr.omarchy_settings")`, after `hypr.looknfeel` (backup: `hyprland.lua.bak.<time>`) | Comment the line out to switch all of the app's Hyprland changes off; the app respects that and never re-adds it |
| `~/.config/hypr/monitors.lua` | Only Displays → Restore defaults: puts Omarchy's automatic-scale lines back (backup: `monitors.lua.bak.<time>`) | Use the backup |
| `~/.config/hypr/hyprsunset.conf` | Night-light schedule (original kept as `hyprsunset.conf.omarchy-settings-original`) | Turn the schedule off |
| `~/.config/omarchy/shell.json` | Idle times; removing the Omarchy menu or media widget from the bar (other bar changes go through `omarchy bar`) | Restore defaults on the page |
| `~/.config/omarchy/themes/<theme>/colors.toml` | Edited theme colors. Stock themes get a separate copy (marked with `.omarchy-settings-overlay`); your own themes are edited in place (original kept as `colors.toml.omarchy-settings-original`) | Theme Colors → Restore defaults |
| `~/.config/omarchy/hooks/theme-set.d/50-omarchy-settings-pins` | Re-applies app style, icons and interface font you chose to keep after each theme change | Set them back to "Follow theme" |
| `~/.config/omarchy/backgrounds/<theme>/` | Backgrounds you add; removing one (or several at once) moves it to the Trash | — |
| `~/.config/desktop-notes/config.json` | Desktop Notes widget's title, background opacity, width, text size, outline, bells, click speed, monitor and position; the widget applies changes live. Notes themselves stay in `~/.local/state/desktop-notes/notes.json` | Widgets → Desktop Notes → Restore defaults |
| GNOME settings (`gsettings`) | Cursor theme and size, light/dark style, icon theme, interface font | Restore defaults on the page |

The generated Lua runs each part separately, so one bad entry can't break the rest of your Hyprland
config; a failing part shows a notification. Before writing, the app checks the file with `luac`.

### Safety features

- **Displays:** Apply tries the change live without saving it. Unless you press Keep within 15 seconds,
  it's undone, even if the app is closed or crashes (a separate watchdog reloads Hyprland).
- **Keybindings:** while you record a shortcut, your other shortcuts are paused so they don't fire.
  Super + Escape gets you out if anything goes wrong.
- **Damaged settings:** an unreadable `settings.json` is set aside as `settings.json.broken-<time>`,
  never silently overwritten. Single entries it can't use (a missing number, NaN, a wrong type) are
  skipped with a message, so the app still opens.

## Uninstall completely

1. `./install.sh --uninstall`
2. Remove the `require("hypr.omarchy_settings")` line from `~/.config/hypr/hyprland.lua`, delete
   `~/.config/hypr/omarchy_settings.lua`, then run `hyprctl reload`.
3. Optional: delete `~/.config/omarchy-settings/` and the hook script above, and restore
   `hyprsunset.conf` / theme colors from the saved originals if you used those pages.

## Development

```bash
./test.sh                  # several hundred tests, a few seconds
HYPOTHESIS_PROFILE=explore ./test.sh tests/test_properties.py   # property tests on many new inputs
# Opt-in: loads the generated config in a nested Hyprland (opens a compositor window in your session)
OSETTINGS_NESTED_HYPRLAND=1 ./test.sh tests/test_nested_hyprland.py
```

`test.sh` needs `python-gobject`, `gtk4`, `libadwaita` and `lua` (for `luac` and `lua`), and uses
`python-pytest` and `python-hypothesis` if both are installed, otherwise it sets up a `.venv` with
them once.

The tests run in a sandbox: every path points into a temporary folder, any real command other
than `luac` makes a test fail (the property tests also run `lua`, in an empty environment that
can't reach anything), GTK draws on an invisible display, and there's no session bus.
They never touch your live desktop. Details are in [CLAUDE.md](CLAUDE.md).

Code layout: `omarchy-settings.py` starts the app; `osettings/` holds `core.py` (helpers, Lua
escaping, widgets), `store.py` (settings and the Lua generator), `binds.py` (reading Omarchy's
keybindings), `pages_look.py`, `pages_system.py`, `pages_keys.py`, `pages_widgets.py` (the pages)
and `window.py`.

Open items and things not yet tested on a real desktop are in [OPEN_ITEMS.md](OPEN_ITEMS.md).
