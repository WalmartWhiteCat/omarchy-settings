#!/usr/bin/env python3
"""Omarchy Settings — a GTK4/libadwaita control panel for the look and feel of an
Omarchy (Hyprland) desktop.

Everything goes through the stock `omarchy` CLI where a command exists. Hyprland
changes are written to ~/.config/hypr/omarchy_settings.lua, which is required
from ~/.config/hypr/hyprland.lua after looknfeel.lua.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from osettings.window import SettingsApp  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(SettingsApp().run(None))
