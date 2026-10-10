#!/bin/bash
# Runs the whole test suite (see CLAUDE.md, "Tests"). Exits non-zero if a test fails or a tool is
# missing. Extra arguments go to pytest, e.g. ./test.sh -k window, ./test.sh tests/test_store.py
#
# pytest comes from the system (python-pytest) when installed; otherwise a .venv in this folder is
# made once, with --system-site-packages so it sees the system's GTK bindings (gi), which pip
# can't install. The opt-in nested Hyprland test still needs OSETTINGS_NESTED_HYPRLAND=1.
set -uo pipefail
cd "$(dirname "$0")"

missing=()
python3 -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1")' 2>/dev/null \
  || missing+=("GTK 4 / libadwaita for Python (pacman: python-gobject gtk4 libadwaita)")
command -v luac >/dev/null || missing+=("luac (pacman: lua)")
if ((${#missing[@]})); then
  printf 'Missing: %s\n' "${missing[@]}" >&2
  exit 2
fi
command -v gtk4-broadwayd >/dev/null \
  || echo "Note: gtk4-broadwayd (part of gtk4) not found, so the real-window tests will skip." >&2

if python3 -c 'import pytest' 2>/dev/null; then
  py=python3
else
  py=.venv/bin/python
  if ! "$py" -c 'import pytest, gi' 2>/dev/null; then
    echo "Setting up .venv with pytest (once; or install python-pytest instead)..." >&2
    rm -rf .venv
    python3 -m venv --system-site-packages .venv && .venv/bin/pip install -q pytest || {
      echo "Couldn't set up .venv. Install pytest instead: sudo pacman -S python-pytest" >&2
      exit 2
    }
  fi
fi
exec "$py" -m pytest -q "$@"
