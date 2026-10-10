"""install.sh, run for real with HOME in tmp_path: it only touches the launcher and its own link."""

import os
import subprocess

from .conftest import REAL_POPEN, ROOT

SCRIPT = ROOT / "install.sh"
TARGET = ROOT / "omarchy-settings.py"


def install(home, *args):
    # subprocess.run goes through the guarded Popen, so use the real one directly.
    env = {**os.environ, "HOME": str(home), "XDG_DATA_HOME": str(home / ".local/share")}
    p = REAL_POPEN(["bash", str(SCRIPT), *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate(timeout=60)
    return subprocess.CompletedProcess(p.args, p.returncode, out, err)


def paths(home):
    return home / ".local/share/applications/omarchy-settings.desktop", home / ".local/bin/omarchy-settings"


def test_install_and_uninstall(tmp_path):
    launcher, command = paths(tmp_path)
    r = install(tmp_path)
    assert r.returncode == 0, r.stderr
    assert f'Exec=python3 "{ROOT}/omarchy-settings.py"' in launcher.read_text()
    assert command.is_symlink() and command.samefile(TARGET)
    assert f"Installed {command}" in r.stdout

    r = install(tmp_path, "--uninstall")
    assert r.returncode == 0
    assert not launcher.exists() and not command.is_symlink()
    assert f"Removed {launcher}" in r.stdout and f"Removed {command}" in r.stdout


def test_a_file_there_is_left_alone(tmp_path):
    _, command = paths(tmp_path)
    command.parent.mkdir(parents=True)
    command.write_text("#!/bin/sh\necho mine\n")
    r = install(tmp_path)
    assert command.read_text() == "#!/bin/sh\necho mine\n"
    assert "Left" in r.stderr and f"Installed {command}" not in r.stdout
    r = install(tmp_path, "--uninstall")
    assert command.read_text() == "#!/bin/sh\necho mine\n"
    assert f"Removed {command}" not in r.stdout and "Left" in r.stderr


def test_a_link_elsewhere_is_left_alone(tmp_path):
    _, command = paths(tmp_path)
    other = tmp_path / "other-checkout/omarchy-settings.py"
    other.parent.mkdir()
    other.write_text("")
    command.parent.mkdir(parents=True)
    command.symlink_to(other)
    r = install(tmp_path)
    assert os.readlink(command) == str(other)
    assert "Left" in r.stderr
    r = install(tmp_path, "--uninstall")
    assert os.readlink(command) == str(other)
    assert f"Removed {command}" not in r.stdout


def test_a_broken_link_is_replaced(tmp_path):
    _, command = paths(tmp_path)
    command.parent.mkdir(parents=True)
    command.symlink_to(tmp_path / "moved-away/omarchy-settings.py")
    r = install(tmp_path)
    assert command.samefile(TARGET)
    assert f"Installed {command}" in r.stdout


def test_uninstall_with_nothing_there(tmp_path):
    _, command = paths(tmp_path)
    r = install(tmp_path, "--uninstall")
    assert r.returncode == 0
    assert f"Removed {command}" not in r.stdout and "Left" not in r.stderr
