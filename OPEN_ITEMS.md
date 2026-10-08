# Open items

## Not yet tried on a real desktop
Covered by tests with stand-ins, but never clicked through live:

- **Displays:** Apply → Keep, Apply → Revert, and letting the 15-second countdown run out (the
  watchdog reload). Also a docked laptop with the lid shut.
- **Keybindings:** a custom shortcut on Super + 1 really replacing the workspace switch; moving F9
  dictation (start and stop together); turning an "Other" shortcut off and on again.
- **Night light:** turning it on from hyprsunset's neutral state (after a restart or the schedule's end).
- **Windows:** the "Omarchy's subtle transparency" switch making windows fully opaque.
- **Background:** moving a background to the Trash (the confirmation and the real Trash).
- **Bar:** removing the Omarchy menu widget from the layout (assumes the bar shows only what's in
  its layout; if Omarchy re-adds enabled widgets, it would come back, harmlessly).
- **Keyboard:** a non-Latin layout keeping shortcuts working.
- **Restore all defaults** end to end.
- **Desktop Notes:** the page's sliders and position moving the widget live, and the widget's settings
  button opening this page (both when the app is closed and when it's already open). The widget's new
  QML loaded without errors and sits where it did before.

The opt-in nested-Hyprland test (`OSETTINGS_NESTED_HYPRLAND=1 python3 -m pytest
tests/test_nested_hyprland.py`) could settle some of these safely, for example whether a later
`hl.monitor` rule replaces or merges with an earlier one for the same output.

## Design concerns (from the 2026-10-08 review)
- **Color edits are full copies** of `colors.toml`, so later Omarchy updates to an edited stock
  theme's colors never arrive. Storing only the changed keys and re-applying them would fix it.
- **Editing a git-installed theme's colors in place** makes `omarchy theme update` (git pull) fail
  for that theme when upstream changes the file. Saving edits as a separate copy would avoid it.
- **Displays vs Super + /:** per-monitor scales saved by the app override Omarchy's Super + /
  scaling at every reload, and Displays → Restore defaults rewrites the `monitors.lua` lines that
  Super + / also edits.
- **monitors.lua extras:** the app's rule for a screen only carries mode, position, scale and
  rotation. It warns when monitors.lua sets more (bit depth, HDR…), but doesn't carry those over.

## Before sharing it
- Choose a license.
- Screenshots for the README.
