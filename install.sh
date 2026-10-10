#!/bin/bash
# Install (or with --uninstall, remove) the "Omarchy Settings" app launcher for this checkout.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LAUNCHER="${XDG_DATA_HOME:-$HOME/.local/share}/applications/omarchy-settings.desktop"
# The Desktop Notes widget's settings button runs `omarchy-settings --page notes`.
COMMAND="$HOME/.local/bin/omarchy-settings"
TARGET="$DIR/omarchy-settings.py"

# The command is ours when it links to this checkout. Install also replaces a
# broken link (a moved checkout, or one on a drive that isn't mounted: it runs
# nothing either way); uninstall leaves that alone. Anything else there (a
# file, a wrapper, another checkout) is never touched. The launcher is ours
# when it runs this checkout.
ours() { [[ -L $COMMAND && $COMMAND -ef $TARGET ]]; }
replaceable() { ours || [[ -L $COMMAND && ! -e $COMMAND ]] || [[ ! -e $COMMAND && ! -L $COMMAND ]]; }
our_launcher() { [[ -f $LAUNCHER ]] && grep -qxF "Exec=python3 \"$TARGET\"" "$LAUNCHER"; }

if [[ ${1:-} == "--uninstall" ]]; then
  if our_launcher; then
    rm -f "$LAUNCHER"
    echo "Removed $LAUNCHER"
  elif [[ -e $LAUNCHER ]]; then
    echo "Left $LAUNCHER alone: it doesn't run this checkout." >&2
  fi
  if ours; then
    rm -f "$COMMAND"
    echo "Removed $COMMAND"
  elif [[ -e $COMMAND || -L $COMMAND ]]; then
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

if ! replaceable; then
  echo "Left $COMMAND alone: it isn't a link to this checkout, so the notes widget's settings" \
    "button will still open whatever it runs." >&2
else
  mkdir -p "$(dirname "$COMMAND")"
  # The link runs the file directly, so it must be executable (a copy may have lost the bit).
  [[ -x $TARGET ]] || chmod +x "$TARGET"
  ln -sfn "$TARGET" "$COMMAND"
  echo "Installed $COMMAND"
fi
