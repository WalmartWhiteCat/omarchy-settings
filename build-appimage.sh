#!/bin/bash
# Builds dist/Omarchy_Settings-x86_64.AppImage: one file the user can run or put in ~/Applications.
# README, "AppImage", says what it contains and what it leaves to the system.
#
#   ./build-appimage.sh             build it (downloads the AppImage runtime once, checks its hash)
#   ./build-appimage.sh --stage DIR only lay out the AppDir in DIR (the tests use this)
#
# Needs mksquashfs (pacman: squashfs-tools) and, the first time, curl.
set -euo pipefail
cd "$(dirname "$0")"

# The runtime is the small program at the front of every AppImage that mounts the rest.
# Pinned to a release and its hash, so a changed download can't slip into the build.
RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64"
RUNTIME_SHA256="2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d"
CACHE=.appimage-cache
OUT=dist/Omarchy_Settings-x86_64.AppImage

stage() {
  local dir=$1 share=$1/usr/share/omarchy-settings
  rm -rf "$dir"
  mkdir -p "$share/osettings"
  install -m755 omarchy-settings.py "$share/"
  # Source only: no tests, no cached bytecode (the image is read-only).
  find osettings -maxdepth 1 -name '*.py' -exec install -m644 {} "$share/osettings/" \;
  install -m755 packaging/appimage/AppRun "$dir/AppRun"
  install -m644 packaging/appimage/omarchy-settings.desktop packaging/appimage/omarchy-settings.svg "$dir/"
  ln -s omarchy-settings.svg "$dir/.DirIcon"
}

if [[ ${1:-} == "--stage" ]]; then
  [[ -n ${2:-} ]] || { echo "Usage: $0 --stage DIR" >&2; exit 2; }
  stage "$2"
  exit 0
fi

command -v mksquashfs >/dev/null || { echo "Missing mksquashfs (pacman: squashfs-tools)." >&2; exit 2; }

runtime=$CACHE/runtime-x86_64
if ! { [[ -f $runtime ]] && echo "$RUNTIME_SHA256  $runtime" | sha256sum -c --status; }; then
  command -v curl >/dev/null || { echo "Missing curl, to fetch the AppImage runtime." >&2; exit 2; }
  mkdir -p "$CACHE"
  curl -fL --silent --show-error -o "$runtime.part" "$RUNTIME_URL"
  if ! echo "$RUNTIME_SHA256  $runtime.part" | sha256sum -c --status; then
    rm -f "$runtime.part"
    echo "The downloaded runtime doesn't match its pinned hash; not using it." >&2
    exit 1
  fi
  mv "$runtime.part" "$runtime"
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
stage "$work/AppDir"
mksquashfs "$work/AppDir" "$work/app.squashfs" -root-owned -noappend -comp zstd -no-progress >/dev/null

mkdir -p dist
cat "$runtime" "$work/app.squashfs" >"$OUT"
chmod +x "$OUT"
echo "Built $OUT ($(du -h "$OUT" | cut -f1))"
