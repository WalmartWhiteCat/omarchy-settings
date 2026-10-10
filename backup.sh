#!/bin/bash
# Saves (or restores) your personal Omarchy Settings and Desktop Notes data. None of it is in git:
# it's your settings, your notes and the files the app wrote. Keep the archive somewhere safe (not
# in the repo).
#
#   ./backup.sh [ARCHIVE]           save to ARCHIVE (default ~/omarchy-personal-<date>.tar.gz)
#   ./backup.sh --list              show what would be saved
#   ./backup.sh --restore ARCHIVE   put the files back; a file that's already there is kept
#                                   as <name>.~1~ (then ~2~...) rather than overwritten
#
# After a restore, open Omarchy Settings once: it regenerates its Hyprland config from
# settings.json and re-adds its line to hyprland.lua. See README, "Moving to a fresh install".
set -euo pipefail

# Relative to HOME. Missing ones are skipped.
PATHS=(
  .config/omarchy-settings                                    # the app's settings.json
  .config/hypr/hyprsunset.conf                                # night light schedule
  .config/hypr/hyprsunset.conf.omarchy-settings-original
  .config/omarchy/shell.json                                  # idle times, bar layout, enabled plugins
  .config/omarchy/themes                                      # edited theme colors, installed themes
  .config/omarchy/backgrounds                                 # backgrounds you added
  .config/omarchy/hooks/theme-set.d/50-omarchy-settings-pins  # keeps app style, icons and font
  .config/desktop-notes                                       # the notes widget's look and position
  .local/state/desktop-notes                                  # your notes
)

cd "$HOME"
existing=()
for p in "${PATHS[@]}"; do
  [[ -e $p ]] && existing+=("$p")
done

case ${1:-} in
--list)
  printf '%s\n' "${existing[@]}"
  ;;
--restore)
  archive=${2:?usage: ./backup.sh --restore ARCHIVE}
  archive=$(realpath "$archive")
  tar -xzf "$archive" -C "$HOME" --backup=numbered
  echo "Restored into $HOME from $archive"
  echo "shell.json is Omarchy's whole shell config: if this Omarchy is newer, compare it with"
  echo "~/.config/omarchy/shell.json.~1~ (the one it replaced, if any) before keeping it."
  ;;
-*)
  echo "usage: ./backup.sh [ARCHIVE] | --list | --restore ARCHIVE" >&2
  exit 2
  ;;
*)
  archive=${1:-$HOME/omarchy-personal-$(date +%Y-%m-%d).tar.gz}
  if ((${#existing[@]} == 0)); then
    echo "Nothing to save." >&2
    exit 1
  fi
  tar -czf "$archive" "${existing[@]}"
  echo "Saved ${#existing[@]} items to $archive:"
  printf '  ~/%s\n' "${existing[@]}"
  ;;
esac
