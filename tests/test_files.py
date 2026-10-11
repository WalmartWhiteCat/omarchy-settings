"""core.write_atomic(): whole-file replacement that is safe for the user's own config files."""

import os
import stat

import pytest

from osettings import core


@pytest.fixture
def d(tmp_path):
    """An empty folder of its own (the sandbox puts home/ and omarchy/ in tmp_path)."""
    folder = tmp_path / "w"
    folder.mkdir()
    return folder


def test_replaces_the_contents(d):
    f = d / "a.json"
    f.write_text("old")
    core.write_atomic(f, "new")
    assert f.read_text() == "new"
    assert sorted(p.name for p in d.iterdir()) == ["a.json"]  # no temp file left behind


def test_writes_through_a_symlink(d):
    """A dotfiles-managed file (a symlink into a repo) must stay a link; replacing the link with a
    plain file would quietly cut it off from the repo."""
    (d / "repo").mkdir()
    real = d / "repo/shell.json"
    real.write_text("old")
    link = d / "shell.json"
    link.symlink_to(real)
    core.write_atomic(link, "new")
    assert link.is_symlink() and real.read_text() == "new"


def test_keeps_the_files_mode(d):
    f = d / "hook"
    f.write_text("old")
    f.chmod(0o750)
    core.write_atomic(f, "new")
    assert stat.S_IMODE(f.stat().st_mode) == 0o750


def test_a_new_file_gets_the_usual_mode(d):
    f = d / "new.lua"
    core.write_atomic(f, "x")
    umask = os.umask(0)
    os.umask(umask)
    assert stat.S_IMODE(f.stat().st_mode) == 0o666 & ~umask


def test_a_failed_write_leaves_the_old_file_and_no_temp(d, monkeypatch):
    f = d / "a.json"
    f.write_text("old")

    def boom(*a):
        raise OSError("disk full")

    monkeypatch.setattr(core.os, "replace", boom)
    with pytest.raises(OSError):
        core.write_atomic(f, "new")
    assert f.read_text() == "old"
    assert sorted(p.name for p in d.iterdir()) == ["a.json"]
