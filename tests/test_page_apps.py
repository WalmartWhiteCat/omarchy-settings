"""Default Apps page, built for real (see pagekit): only installed apps are offered, the current
default is picked (even one the page doesn't know), and choosing runs `omarchy default`."""

import shutil
import types

from gi.repository import Adw

from osettings import pages_system as ps

from .pagekit import callbacks, needs_display, open_page  # noqa: F401

pytestmark = needs_display


def installed(monkeypatch, binaries=(), desktops=()):
    monkeypatch.setattr(ps, "shutil", types.SimpleNamespace(
        which=lambda b: f"/usr/bin/{b}" if b in binaries else None, copy2=shutil.copy2))
    monkeypatch.setattr(ps, "desktop_exists", lambda d: d in desktops)


def defaults(sandbox, terminal="", browser="", editor=""):
    for kind, value in (("terminal", terminal), ("browser", browser), ("editor", editor)):
        sandbox.run_output[("omarchy", "default", kind)] = value


def labels(row):
    m = row.get_model()
    return [m.get_string(i) for i in range(m.get_n_items())]


def chosen(row):
    return row.get_model().get_string(row.get_selected())


def test_only_installed_apps_are_offered(sandbox, open_page, monkeypatch):
    installed(monkeypatch, binaries={"kitty", "alacritty", "nvim", "hx"},
              desktops={"firefox.desktop", "chromium.desktop"})
    defaults(sandbox, terminal="kitty", browser="firefox", editor="nvim")
    p = open_page("apps")
    assert labels(p.row("Terminal")) == ["Alacritty", "Kitty"]
    assert labels(p.row("Web browser")) == ["Chromium", "Firefox"]
    assert labels(p.row("Editor")) == ["Helix", "Neovim"]  # Helix found as `hx`
    assert (chosen(p.row("Terminal")), chosen(p.row("Web browser")), chosen(p.row("Editor"))) == \
        ("Kitty", "Firefox", "Neovim")


def test_choosing_runs_omarchy_default(sandbox, open_page, monkeypatch):
    got = callbacks(monkeypatch, ps)
    installed(monkeypatch, binaries={"kitty", "alacritty", "code", "nvim"},
              desktops={"firefox.desktop", "zen.desktop"})
    defaults(sandbox, terminal="kitty", browser="firefox", editor="nvim")
    p = open_page("apps")
    p.choose("Web browser", "Zen")
    p.choose("Editor", "VS Code")
    p.choose("Terminal", "Alacritty")
    assert [c for c, _ in got["async"]] == [["omarchy", "default", "browser", "zen"],
                                            ["omarchy", "default", "editor", "code"],
                                            ["omarchy", "default", "terminal", "alacritty"]]
    cmd, done = got["async"][-1]
    done(0, "", "")
    assert "Default terminal set" in p.toasts
    done(1, "", "alacritty: not found\n")
    assert "alacritty: not found" in p.toasts


def test_an_unknown_current_default_is_kept(sandbox, open_page, monkeypatch):
    installed(monkeypatch, binaries={"kitty"})
    defaults(sandbox, terminal="wezterm")
    p = open_page("apps")
    assert labels(p.row("Terminal")) == ["Kitty", "wezterm"] and chosen(p.row("Terminal")) == "wezterm"


def test_zed_is_recognised(sandbox, open_page, monkeypatch):
    installed(monkeypatch, binaries={"zeditor"})
    defaults(sandbox, editor="zeditor")  # Omarchy prints Zed's binary name
    p = open_page("apps")
    assert labels(p.row("Editor")) == ["Zed"] and chosen(p.row("Editor")) == "Zed"


def test_nothing_installed(sandbox, open_page, monkeypatch):
    installed(monkeypatch)
    defaults(sandbox)
    p = open_page("apps")
    row = p.row("Terminal", Adw.ActionRow)
    assert not isinstance(row, Adw.ComboRow)
    assert row.get_subtitle() == "None of the supported apps are installed"


def test_restore_all_leaves_default_apps_alone(sandbox, open_page, monkeypatch):
    installed(monkeypatch, binaries={"kitty"})
    defaults(sandbox, terminal="kitty")
    p = open_page("apps")
    before = list(sandbox.all_cmds())
    finished = []
    p.page.reset(lambda: finished.append(True))
    assert finished == [True] and sandbox.all_cmds() == before
