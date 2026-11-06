"""The AppImage's pieces: what build-appimage.sh lays out, and AppRun's own behaviour. The image
itself is not built here (that needs a download); the layout is the part that can go wrong with
a new module, and AppRun is plain shell run for real with HOME in tmp_path."""

import os
import re
import subprocess
import sys

from .conftest import REAL_POPEN, ROOT

BUILD = ROOT / "build-appimage.sh"
PACKAGING = ROOT / "packaging/appimage"


def sh(args, home, **env):
    # subprocess.run goes through the guarded Popen, so use the real one directly.
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent", **env}
    p = REAL_POPEN(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate(timeout=60)
    return subprocess.CompletedProcess(p.args, p.returncode, out, err)


def stage(tmp_path):
    appdir = tmp_path / "AppDir"
    r = sh(["bash", str(BUILD), "--stage", str(appdir)], tmp_path / "home")
    assert r.returncode == 0, r.stderr
    return appdir


def test_stage_holds_every_module_and_no_tests(tmp_path):
    appdir = stage(tmp_path)
    share = appdir / "usr/share/omarchy-settings"
    modules = sorted(p.name for p in (ROOT / "osettings").glob("*.py"))
    assert sorted(p.name for p in (share / "osettings").iterdir()) == modules
    assert (share / "omarchy-settings.py").read_bytes() == (ROOT / "omarchy-settings.py").read_bytes()
    for name in modules:
        assert (share / "osettings" / name).read_bytes() == (ROOT / "osettings" / name).read_bytes()
    assert not (share / "tests").exists() and not list(share.rglob("__pycache__"))


def test_stage_has_what_an_appimage_needs(tmp_path):
    appdir = stage(tmp_path)
    assert os.access(appdir / "AppRun", os.X_OK)
    desktop = (appdir / "omarchy-settings.desktop").read_text()
    assert "Exec=AppRun" in desktop and "Icon=omarchy-settings" in desktop
    assert "StartupWMClass=org.omarchy.Settings" in desktop  # the app's id, so the window matches the launcher
    assert (appdir / "omarchy-settings.svg").is_file()
    assert (appdir / ".DirIcon").resolve() == (appdir / "omarchy-settings.svg").resolve()


def test_staged_copy_imports_on_its_own(tmp_path):
    """Run from the stage, so a module the layout forgot fails here."""
    share = stage(tmp_path) / "usr/share/omarchy-settings"
    code = f"import sys; sys.path.insert(0, {str(share)!r}); import osettings.window as w; print(w.__file__)"
    r = sh([sys.executable, "-B", "-I", "-c", code], tmp_path / "home")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().startswith(str(share))


def test_runtime_is_pinned_to_a_release_and_a_hash():
    text = BUILD.read_text()
    url = re.search(r'RUNTIME_URL="([^"]+)"', text).group(1)
    assert "/releases/download/" in url and "/continuous/" not in url  # a moving tag can't be pinned
    assert re.fullmatch(r"[0-9a-f]{64}", re.search(r'RUNTIME_SHA256="([^"]+)"', text).group(1))


def test_app_run_adds_and_removes_the_launcher(tmp_path):
    appdir = stage(tmp_path)
    home = tmp_path / "home"
    image = tmp_path / "My Apps" / "Omarchy_Settings-x86_64.AppImage"
    launcher = home / ".local/share/applications/omarchy-settings.desktop"
    icon = home / ".local/share/icons/hicolor/scalable/apps/omarchy-settings.svg"

    r = sh([str(appdir / "AppRun"), "--install-launcher"], home, APPIMAGE=str(image))
    assert r.returncode == 0, r.stderr
    assert f'Exec="{image}"' in launcher.read_text()  # quoted: the path has a space
    assert icon.is_file()

    r = sh([str(appdir / "AppRun"), "--remove-launcher"], home)
    assert r.returncode == 0
    assert not launcher.exists() and not icon.exists()


def test_app_run_wont_add_a_launcher_outside_an_appimage(tmp_path):
    appdir = stage(tmp_path)
    home = tmp_path / "other-home"  # the sandbox's own home already has a .local/bin
    home.mkdir()
    r = sh([str(appdir / "AppRun"), "--install-launcher"], home)
    assert r.returncode == 1 and "AppImage" in r.stderr
    assert not list(home.rglob("*"))


def test_app_run_says_what_to_install_when_gtk_is_missing(tmp_path):
    appdir = stage(tmp_path)
    r = sh([str(appdir / "AppRun")], tmp_path / "home", OMARCHY_SETTINGS_PYTHON="/bin/false")
    assert r.returncode == 1
    assert "python-gobject gtk4 libadwaita" in r.stderr
