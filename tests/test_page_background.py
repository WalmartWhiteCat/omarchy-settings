"""Background page, built for real (see pagekit): the theme's wallpapers and the user's own, which
one is current, setting one, adding images (copies, name clashes, files that can't be copied),
moving one or several to the Trash (and not leaving the desktop on a deleted file), Restore
defaults, and the automatic change timer.
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


# Automatic change

SWITCH, HOW_OFTEN = "Change the background automatically", "How often"
IS_ACTIVE = ("systemctl", "--user", "is-active", pl.CYCLE_TIMER_NAME)
HERMES_TIMER = """[Unit]
Description=Wallpaper cycling timer (10 min)

[Timer]
OnCalendar=*-*-* *:00/10
Accuracy=1us

[Install]
WantedBy=timers.target
"""
HERMES_SERVICE = """[Unit]
Description=Cycle Omarchy wallpaper (10 min)

[Service]
Type=oneshot
ExecStart=/somewhere/else/omarchy theme bg next
"""


def units(sandbox, timer=HERMES_TIMER, service=HERMES_SERVICE, active=True):
    pl.CYCLE_TIMER.parent.mkdir(parents=True, exist_ok=True)
    if timer is not None:
        pl.CYCLE_TIMER.write_text(timer)
    if service is not None:
        pl.CYCLE_SERVICE.write_text(service)
    sandbox.run_output[IS_ACTIVE] = "active" if active else "inactive"


def selected(p, title=HOW_OFTEN):
    row = p.row(title, Adw.ComboRow)
    return row.get_model().get_string(row.get_selected())


def test_cycle_shows_the_timer_hermes_set_up(open_page, sandbox):
    theme()
    units(sandbox)
    p = open_page("background")
    assert p.row(SWITCH, Adw.SwitchRow).get_active()
    assert selected(p) == "Every 10 minutes"


def test_cycle_shows_off_when_the_timer_is_stopped_or_missing(open_page, sandbox):
    theme()
    p = open_page("background")
    assert not p.row(SWITCH, Adw.SwitchRow).get_active()
    assert selected(p) == "Every 10 minutes"
    assert not pl.CYCLE_TIMER.exists()  # only looking writes nothing


def test_cycle_off_stops_and_disables_the_timer(open_page, sandbox):
    theme()
    units(sandbox)
    p = open_page("background")
    p.switch(SWITCH, False)
    assert sandbox.run_chain[-1] == [["systemctl", "--user", "disable", "--now", pl.CYCLE_TIMER_NAME]]
    assert pl.CYCLE_TIMER.read_text() == HERMES_TIMER


def test_cycle_on_keeps_an_existing_timer(open_page, sandbox):
    theme()
    units(sandbox, timer=HERMES_TIMER.replace("*-*-* *:00/10", "Mon 09:00"), active=False)
    p = open_page("background")
    p.switch(SWITCH, True)
    assert sandbox.run_chain[-1] == [["systemctl", "--user", "daemon-reload"],
                                     ["systemctl", "--user", "enable", "--now", pl.CYCLE_TIMER_NAME]]
    assert "OnCalendar=Mon 09:00" in pl.CYCLE_TIMER.read_text()


def test_cycle_on_creates_missing_units_with_the_chosen_interval(open_page, sandbox, monkeypatch):
    theme()
    got = callbacks(monkeypatch, pl)
    p = open_page("background")
    p.choose(HOW_OFTEN, "Every 30 minutes")
    got["chain"][-1][1]([])
    p.switch(SWITCH, True)
    assert "OnCalendar=*:00/30\n" in pl.CYCLE_TIMER.read_text()
    assert f"ExecStart={pl.OMARCHY_PATH}/bin/omarchy theme bg next" in pl.CYCLE_SERVICE.read_text()
    assert sandbox.run_chain[-1][-1] == ["systemctl", "--user", "enable", "--now", pl.CYCLE_TIMER_NAME]


def test_cycle_switch_goes_back_when_systemctl_fails(open_page, sandbox, monkeypatch):
    theme()
    units(sandbox)
    got = callbacks(monkeypatch, pl)
    p = open_page("background")
    p.switch(SWITCH, False)
    group = p.page.cycle_group
    assert not group.get_sensitive()  # no second change until this one finishes
    calls = len(sandbox.run_chain)
    got["chain"][-1][1](["systemctl --user disable: no bus"])
    spin()
    assert p.row(SWITCH, Adw.SwitchRow).get_active()
    assert group.get_sensitive()
    assert any("no bus" in t for t in p.toasts)
    assert len(sandbox.run_chain) == calls  # putting it back runs nothing


def test_cycle_switch_can_go_back_on_after_going_off(open_page, sandbox, monkeypatch):
    theme()
    units(sandbox)
    got = callbacks(monkeypatch, pl)
    p = open_page("background")
    p.switch(SWITCH, False)
    got["chain"][-1][1]([])
    p.switch(SWITCH, True)
    assert sandbox.run_chain[-1][-1] == ["systemctl", "--user", "enable", "--now", pl.CYCLE_TIMER_NAME]


def test_cycle_interval_rewrites_the_timer_and_keeps_the_service_command(open_page, sandbox):
    theme()
    units(sandbox)
    p = open_page("background")
    p.choose(HOW_OFTEN, "Every 2 hours")
    timer = pl.CYCLE_TIMER.read_text()
    assert "OnCalendar=00/2:00\n" in timer
    assert "10 min" not in timer and "Accuracy=" not in timer and "AccuracySec=1s" in timer
    assert "WantedBy=timers.target" in timer
    service = pl.CYCLE_SERVICE.read_text()
    assert "ExecStart=/somewhere/else/omarchy theme bg next" in service and "10 min" not in service
    assert sandbox.run_chain[-1] == [["systemctl", "--user", "daemon-reload"],
                                     ["systemctl", "--user", "try-restart", pl.CYCLE_TIMER_NAME]]


def test_cycle_interval_write_failure_goes_back(open_page, sandbox, monkeypatch):
    theme()
    units(sandbox)
    p = open_page("background")

    def fail(*_):
        raise OSError("disk full")

    monkeypatch.setattr(pl, "write_atomic", fail)
    p.choose(HOW_OFTEN, "Every hour")
    assert selected(p) == "Every 10 minutes"
    assert any("disk full" in t for t in p.toasts)
    assert sandbox.run_chain == []


def test_cycle_custom_schedule_is_shown_and_kept_until_changed(open_page, sandbox):
    theme()
    units(sandbox, timer=HERMES_TIMER.replace("*-*-* *:00/10", "Mon 09:00"))
    p = open_page("background")
    assert selected(p) == "Custom (Mon 09:00)"
    p.choose(HOW_OFTEN, "Every day")
    assert "OnCalendar=00:00\n" in pl.CYCLE_TIMER.read_text()
    p.choose(HOW_OFTEN, "Custom (Mon 09:00)")
    assert "OnCalendar=Mon 09:00\n" in pl.CYCLE_TIMER.read_text()


def test_cycle_timer_without_a_single_schedule_is_custom_and_cant_be_chosen_back(open_page, sandbox):
    theme()
    units(sandbox, timer=HERMES_TIMER.replace("OnCalendar=*-*-* *:00/10", "OnUnitActiveSec=7min"))
    p = open_page("background")
    assert selected(p) == "Custom"
    p.switch(SWITCH, False)
    p.choose(HOW_OFTEN, "Every hour")
    p.choose(HOW_OFTEN, "Custom")
    assert selected(p) == "Every hour"
    assert "OnCalendar=*:00\n" in pl.CYCLE_TIMER.read_text()


def test_videos_are_listed_marked_and_set_like_images(sandbox, open_page, monkeypatch):
    """Omarchy 4.5 plays a video as the background; they were invisible here."""
    user = theme(mine=("holiday.png",), current="2-stock.jpg")
    (user / "waves.mp4").write_bytes(b"v")
    (pl.STATE / "current/theme/backgrounds/loop.webm").write_bytes(b"v")
    asked = []
    monkeypatch.setattr(pl, "load_texture_async", lambda path, w, h, cb: asked.append(path.name))
    p = open_page("background")
    assert names(p) == ["holiday.png", "waves.mp4", "1-stock.png", "2-stock.jpg", "loop.webm"]
    assert "waves.mp4" in asked and "loop.webm" in asked  # thumbnails are asked for like any other
    badges = {c.path.name: any(isinstance(w, Gtk.Image) and w.get_icon_name() == "media-playback-start-symbolic"
                               for w in widgets(c)) for c in tiles(p)}
    assert badges == {"holiday.png": False, "waves.mp4": True, "1-stock.png": False, "2-stock.jpg": False,
                      "loop.webm": True}
    flow(p).emit("child-activated", tile(p, "waves.mp4"))
    spin()
    assert bg_sets(sandbox) == [str(user / "waves.mp4")]
    # A video the user added can be moved to the Trash like an image.
    assert any(isinstance(w, Gtk.Button) and w.get_tooltip_text() == "Move to Trash" for w in widgets(tile(p, "waves.mp4")))


def test_added_videos_are_copied_and_set(sandbox, open_page, tmp_path):
    user = theme()
    (tmp_path / "waves.mp4").write_bytes(b"v")
    p = open_page("background")
    p.page.on_files(FilesChosen(Gio.File.new_for_path(str(tmp_path / "waves.mp4"))), None)
    spin()
    assert [f.name for f in user.iterdir()] == ["waves.mp4"]
    assert bg_sets(sandbox) == [str(user / "waves.mp4")]


def test_the_file_chooser_offers_videos_too(sandbox, open_page, monkeypatch):
    theme()
    opened = []
    monkeypatch.setattr(pl.Gtk.FileDialog, "open_multiple", lambda self, *a: opened.append(self))
    open_page("background").page.on_add()
    f = opened[0].get_filters().get_item(0)
    assert f.get_name() == "Images and videos"
    assert "image/*" in str(f.to_gvariant()) and "video/*" in str(f.to_gvariant())
