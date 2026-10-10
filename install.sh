#!/bin/bash
# Install (or with --uninstall, remove) the "Omarchy Settings" app launcher for this checkout.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="${XDG_DATA_HOME:-$HOME/.local/share}/applications/omarchy-settings.desktop"
# The Desktop Notes widget's settings button runs `omarchy-settings --page notes`.
COMMAND="$HOME/.local/bin/omarchy-settings"
TARGET="$DIR/omarchy-settings.py"

# The command is ours when it links to this checkout, or is a broken link (a
# moved checkout). Anything else there (a file, a wrapper, another checkout)
# is left alone.
ours() { [[ -L $COMMAND ]] && { [[ ! -e $COMMAND ]] || [[ $COMMAND -ef $TARGET ]]; }; }
taken() { [[ -e $COMMAND || -L $COMMAND ]] && ! ours; }

if [[ ${1:-} == "--uninstall" ]]; then
  rm -f "$LAUNCHER"
  echo "Removed $LAUNCHER"
  if ours; then
    rm -f "$COMMAND"
    echo "Removed $COMMAND"
  elif taken; then
    echo "Left $COMMAND alone: it isn't a link to this checkout." >&2
  fi
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

if taken; then
  echo "Left $COMMAND alone: it isn't a link to this checkout." >&2
else
  mkdir -p "$(dirname "$COMMAND")"
  # The link runs the file directly, so it must be executable (a copy may have lost the bit).
  [[ -x $TARGET ]] || chmod +x "$TARGET"
  ln -sfn "$TARGET" "$COMMAND"
  echo "Installed $COMMAND"
fi
