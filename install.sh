#!/bin/bash
# Install (or with --uninstall, remove) the "Omarchy Settings" app launcher for this checkout.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="${XDG_DATA_HOME:-$HOME/.local/share}/applications/omarchy-settings.desktop"

if [[ ${1:-} == "--uninstall" ]]; then
  rm -f "$LAUNCHER"
  echo "Removed $LAUNCHER"
  exit 0
fi

if ! python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")' 2>/dev/null; then
  echo "GTK 4 / libadwaita for Python not found (needs python-gobject, gtk4, libadwaita)." >&2
  exit 1
fi

mkdir -p "$(dirname "$LAUNCHER")"
cat >"$LAUNCHER" <<EOF
[Desktop Entry]
Type=Application
Name=Omarchy Settings
Comment=Themes, windows, displays, input, keybindings, autostart, bar and more
Exec=python3 "$DIR/omarchy-settings.py"
Icon=preferences-desktop-theme
Categories=Settings;DesktopSettings;
StartupWMClass=org.omarchy.Settings
EOF

if command -v desktop-file-validate >/dev/null; then
  desktop-file-validate "$LAUNCHER"
fi
echo "Installed $LAUNCHER"
