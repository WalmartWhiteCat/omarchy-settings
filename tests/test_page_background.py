"""Background page, built for real (see pagekit): the theme's wallpapers and the user's own, which
one is current, setting one, adding images (copies, name clashes, files that can't be copied),
moving one or several to the Trash (and not leaving the desktop on a deleted file), and Restore
defaults.
Older stand-in tests are in test_review_fixes."""

import os

from gi.repository import Adw, Gio, Gtk

from osettings import pages_look as pl

from .pagekit import callbacks, needs_display, open_page, spin, widgets  # noqa: F401

pytestmark = needs_display

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
                    "0000000d49444154789c6360000002000005000155a7fd1d0000000049454e44ae426082")


def theme(slug="tokyo-night", stock=("1-stock.png", "2-stock.jpg"), mine=(), current=None):
    """A current theme with stock wallpapers and the user's own; `current` (a name) is the
    background link's target."""
    state = pl.STATE / "current"
    (state / "theme/backgrounds").mkdir(parents=True, exist_ok=True)
    (state / "theme.name").write_text(slug + "\n")
    for name in stock:
        (state / "theme/backgrounds" / name).write_bytes(PNG)
    user = pl.HOME / ".config/omarchy/backgrounds" / slug
    user.mkdir(parents=True, exist_ok=True)
    for name in mine:
        (user / name).write_bytes(PNG)
    if current:
        target = user / current if current in mine else state / "theme/backgrounds" / current
        (state / "background").symlink_to(target)
    return user


def tiles(p):
    return [c for c in widgets(p.page) if isinstance(c, Gtk.FlowBoxChild)]


def names(p):
    return [c.path.name for c in tiles(p)]


def tile(p, name):
    return next(c for c in tiles(p) if c.path.name == name)


def flow(p):
    return next(w for w in widgets(p.page) if isinstance(w, Gtk.FlowBox))


def bg_sets(sandbox):
    return [c[4] for c in sandbox.run_async if c[:4] == ["omarchy", "theme", "bg", "set"]]


def answer(p, response):
    d = p.win.get_visible_dialog()
    assert isinstance(d, Adw.AlertDialog), "no dialog open"
    d.emit("response", response)
    d.force_close()
    spin()


class FilesChosen:
    """Stands in for the file chooser's answer to on_files."""

    def __init__(self, *files, cancelled=False):
        self.files, self.cancelled = files, cancelled

    def open_multiple_finish(self, _result):
        if self.cancelled:
            raise pl.GLib.Error("dismissed")
        store = Gio.ListStore.new(Gio.File)
        for f in self.files:
            store.append(f)
        return store


def test_lists_mine_then_the_themes_and_marks_the_current_one(open_page):
    theme(mine=("holiday.png",), current="2-stock.jpg")
    p = open_page("background")
    assert names(p) == ["holiday.png", "1-stock.png", "2-stock.jpg"]
    assert [c.path.name for c in flow(p).get_selected_children()] == ["2-stock.jpg"]
    assert "(tokyo-night)" in p.page.group.get_description()
    # Only images the user added can be moved to the Trash: the theme's come back with it.
    trash = {c.path.name: any(isinstance(w, Gtk.Button) and w.get_tooltip_text() == "Move to Trash"
                              for w in widgets(c)) for c in tiles(p)}
    assert trash == {"holiday.png": True, "1-stock.png": False, "2-stock.jpg": False}


def test_choosing_one_sets_it(sandbox, open_page, monkeypatch):
    theme()
    got = callbacks(monkeypatch, pl)
    p = open_page("background")
    flow(p).emit("child-activated", tile(p, "1-stock.png"))
    spin()
    assert bg_sets(sandbox) == [str(pl.STATE / "current/theme/backgrounds/1-stock.png")]
    got["async"][-1][1](0, "", "")
    assert p.toasts[-1] == "Background updated"
    got["async"][-1][1](1, "", "no such theme\n")
    assert p.toasts[-1] == "no such theme"


def test_added_images_are_copied_into_the_themes_folder_and_the_last_is_set(sandbox, open_page, tmp_path):
    user = theme(mine=("beach.png",))
    picked = tmp_path / "picked"
    picked.mkdir()
    for name in ("beach.png", "city.png"):
        (picked / name).write_bytes(PNG)
    p = open_page("background")
    p.page.on_files(FilesChosen(Gio.File.new_for_path(str(picked / "beach.png")),
                                Gio.File.new_for_path(str(picked / "city.png"))), None)
    spin()
    assert sorted(f.name for f in user.iterdir()) == ["beach-2.png", "beach.png", "city.png"]  # no overwrite
    assert (picked / "beach.png").exists()  # copied, not moved
    assert bg_sets(sandbox) == [str(user / "city.png")]
    assert names(p)[:3] == ["beach-2.png", "beach.png", "city.png"]


def test_files_that_cant_be_added_are_named_and_the_rest_still_are(sandbox, open_page, tmp_path):
    user = theme()
    (tmp_path / "ok.png").write_bytes(PNG)
    p = open_page("background")
    p.page.on_files(FilesChosen(Gio.File.new_for_uri("https://example.com/remote.png"),
                                Gio.File.new_for_path(str(tmp_path / "gone.png")),
                                Gio.File.new_for_path(str(tmp_path / "ok.png"))), None)
    spin()
    assert p.toasts[-1] == "2 files couldn't be added: remote.png, gone.png"
    assert [f.name for f in user.iterdir()] == ["ok.png"]  # nothing half-copied
    assert bg_sets(sandbox) == [str(user / "ok.png")]


def test_cancelling_the_file_chooser_changes_nothing(sandbox, open_page):
    user = theme()
    p = open_page("background")
    p.page.on_files(FilesChosen(cancelled=True), None)
    spin()
    assert list(user.iterdir()) == [] and bg_sets(sandbox) == [] and p.toasts == []


def test_moving_one_to_the_trash(sandbox, open_page):
    user = theme(mine=("a.png", "b.png"), current="1-stock.png")
    p = open_page("background")
    p.click("Move to Trash", within=tile(p, "b.png"))
    answer(p, "ok")
    assert sandbox.trash == [str(user / "b.png")]
    assert p.toasts[-1] == "Moved b.png to the Trash"
    assert "b.png" not in names(p)
    assert bg_sets(sandbox) == []  # it wasn't the current one


def test_cancelling_the_trash_keeps_it(sandbox, open_page):
    theme(mine=("a.png",))
    p = open_page("background")
    p.click("Move to Trash", within=tile(p, "a.png"))
    answer(p, "cancel")
    assert sandbox.trash == [] and "a.png" in names(p)


def test_trashing_the_current_one_switches_to_another(sandbox, open_page):
    user = theme(mine=("a.png", "b.png"), current="a.png")
    p = open_page("background")
    p.click("Move to Trash", within=tile(p, "a.png"))
    answer(p, "ok")
    assert sandbox.trash == [str(user / "a.png")]
    assert bg_sets(sandbox) == [str(user / "b.png")]
    assert p.toasts[-1] == "Moved to the Trash; switched to b.png"


def test_trashing_the_only_one_says_so(sandbox, open_page):
    theme(stock=(), mine=("a.png",), current="a.png")
    p = open_page("background")
    p.click("Move to Trash", within=tile(p, "a.png"))
    answer(p, "ok")
    assert bg_sets(sandbox) == []
    assert p.toasts[-1] == "Moved to the Trash. This theme has no other backgrounds."


def test_a_failed_trash_keeps_the_file_and_says_why(sandbox, open_page, monkeypatch):
    user = theme(mine=("a.png",))
    monkeypatch.setattr(pl, "trash_file", lambda path: "permission denied")
    p = open_page("background")
    p.click("Move to Trash", within=tile(p, "a.png"))
    answer(p, "ok")
    assert (user / "a.png").exists()
    assert p.toasts[-1] == "Couldn't move a.png to the Trash: permission denied"


def bulk(p):
    """Open the "Move several" dialog; returns it and its rows by file name ("Select all" first)."""
    p.click("Move several to the Trash…")
    d = p.win.get_visible_dialog()
    assert isinstance(d, Adw.AlertDialog), "no dialog open"
    rows = {r.get_title(): r for r in widgets(d.get_extra_child()) if isinstance(r, Adw.ActionRow)}
    return d, rows


def tick(row):
    next(w for w in widgets(row) if isinstance(w, Gtk.CheckButton)).set_active(True)


def test_several_only_lists_mine_and_needs_one_ticked(sandbox, open_page):
    theme(mine=("a.png", "b.png"))
    p = open_page("background")
    d, rows = bulk(p)
    assert list(rows) == ["Select all", "a.png", "b.png"]  # never the theme's own
    assert not d.get_response_enabled("ok")
    tick(rows["b.png"])
    assert d.get_response_enabled("ok") and d.get_response_label("ok") == "Move 1 to Trash"
    answer(p, "cancel")
    assert sandbox.trash == []


def test_several_move_together(sandbox, open_page):
    user = theme(mine=("a.png", "b.png", "c.png"), current="1-stock.png")
    p = open_page("background")
    _d, rows = bulk(p)
    tick(rows["a.png"])
    tick(rows["c.png"])
    answer(p, "ok")
    assert sandbox.trash == [str(user / "a.png"), str(user / "c.png")]
    assert p.toasts[-1] == "Moved 2 backgrounds to the Trash"
    assert bg_sets(sandbox) == []


def test_select_all_ticks_every_one(sandbox, open_page):
    user = theme(mine=("a.png", "b.png"))
    p = open_page("background")
    d, rows = bulk(p)
    tick(rows["Select all"])
    assert d.get_response_label("ok") == "Move 2 to Trash"
    answer(p, "ok")
    assert sandbox.trash == [str(user / "a.png"), str(user / "b.png")]


def test_several_including_the_current_one_switch_to_what_is_left(sandbox, open_page):
    user = theme(mine=("a.png", "b.png", "c.png"), current="b.png")
    p = open_page("background")
    _d, rows = bulk(p)
    tick(rows["a.png"])
    tick(rows["b.png"])
    answer(p, "ok")
    assert bg_sets(sandbox) == [str(user / "c.png")]
    assert p.toasts[-1] == "Moved 2 backgrounds to the Trash; switched to c.png"


def test_several_that_fail_are_named_and_the_rest_still_go(sandbox, open_page, monkeypatch):
    user = theme(mine=("a.png", "b.png", "c.png"), current="c.png")
    real = pl.trash_file
    monkeypatch.setattr(pl, "trash_file", lambda path: "permission denied" if path.name != "c.png" else real(path))
    p = open_page("background")
    _d, rows = bulk(p)
    tick(rows["Select all"])
    answer(p, "ok")
    assert (user / "a.png").exists() and (user / "b.png").exists()
    assert "Couldn't move a.png, b.png to the Trash: permission denied" in p.toasts
    assert bg_sets(sandbox) == [str(user / "a.png")]  # the current one went, so don't point at it
    assert p.toasts[-1] == "Moved to the Trash; switched to a.png"


def test_the_several_button_shows_only_with_backgrounds_of_my_own(open_page):
    theme()
    p = open_page("background")
    assert not p.page.bulk.get_visible()
    theme(stock=(), mine=("a.png",))
    p.page.populate()
    assert p.page.bulk.get_visible()


def test_restore_defaults_sets_the_first_stock_wallpaper(sandbox, open_page, monkeypatch):
    theme(mine=("mine.png",), current="mine.png")
    got = callbacks(monkeypatch, pl)
    p = open_page("background")
    p.press("Restore defaults")
    answer(p, "ok")
    assert bg_sets(sandbox) == [str(pl.STATE / "current/theme/backgrounds/1-stock.png")]
    got["async"][-1][1](0, "", "")
    assert p.toasts[-1] == "Background restored"
    assert os.path.exists(pl.HOME / ".config/omarchy/backgrounds/tokyo-night/mine.png")  # kept


def test_restore_defaults_without_stock_wallpapers(sandbox, open_page):
    theme(stock=())
    p = open_page("background")
    p.press("Restore defaults")
    answer(p, "ok")
    assert bg_sets(sandbox) == []
    assert p.toasts[-1] == "This theme has no stock backgrounds"
