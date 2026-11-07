#!/bin/bash
# Install (or with --uninstall, remove) the "Omarchy Settings" app launcher for this checkout.   ./install.sh [--yes] [--uninstall]

set -euo pipefail

UNINSTALL=0
ASSUME_YES=0
for arg in "$@"; do
  case $arg in
    --uninstall) UNINSTALL=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    -h|--help)
      echo "Usage: ./install.sh [--yes] [--uninstall]"
      echo "  --yes        install any missing system packages without asking"
      echo "  --uninstall  remove the launcher and command this script made"
      exit 0 ;;
    *) echo "Unknown option: $arg (try --help)" >&2; exit 2 ;;
  esac
done

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

if (( UNINSTALL )); then
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


# ---- system packages ------------------------------------------------------------------------
# Omarchy is Arch, so a missing library is one pacman command away: say what is missing and offer
# to install it (--yes: don't ask). Without a terminal and without --yes it only prints the command.
py_ok() { python3 -c "$1" >/dev/null 2>&1; }
scan() {
  missing=(); optional=()
  if ! command -v python3 >/dev/null; then missing+=(python); return; fi
  if ! py_ok 'import gi'; then missing+=(python-gobject); return; fi
  py_ok 'import gi; gi.require_version("Gtk", "4.0")' || missing+=(gtk4)
  py_ok 'import gi; gi.require_version("Adw", "1")' || missing+=(libadwaita)
}
pacman_install() {
  command -v pacman >/dev/null || { echo "Please install with your package manager: $*" >&2; return 1; }
  if (( ! ASSUME_YES )); then
    if [[ -t 0 && -t 1 ]]; then
      read -r -p "Install $* now (sudo pacman -S --needed)? [Y/n] " answer
      [[ ${answer:-y} =~ ^[Yy] ]] || return 1
    else
      echo "Run: sudo pacman -S --needed $*   (or run ./install.sh --yes)" >&2
      return 1
    fi
  fi
  sudo pacman -S --needed "$@"
}

scan
if ((${#missing[@]})); then
  echo "Missing: ${missing[*]}"
  pacman_install "${missing[@]}" || { echo "Not installed: ${missing[*]}. Nothing was changed." >&2; exit 1; }
  scan
  if ((${#missing[@]})); then echo "Still missing after installing: ${missing[*]}. Nothing was changed." >&2; exit 1; fi
fi
if ((${#optional[@]})); then
  echo "Optional: ${optional[*]} (nothing optional)"
  pacman_install "${optional[@]}" || echo "Skipped: nothing optional." >&2
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
