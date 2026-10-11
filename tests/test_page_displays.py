"""Displays page, built for real (see pagekit): each screen's controls, the scale list following
the resolution, the live trial (hyprctl eval, the watchdog, the 15-second countdown, Keep and
Revert), Hyprland refusing a trial, arranging, and Restore defaults. The trial logic itself also
has stand-in tests in test_review_fixes."""

import pytest
from gi.repository import Adw, GLib

from osettings import pages_system as ps
from osettings import store as store_mod

from .pagekit import callbacks, needs_display, open_page, spin, widgets  # noqa: F401

pytestmark = needs_display

# As `hyprctl monitors all -j` prints them (fields the page reads).
LG = {"name": "DP-1", "description": "LG Electronics LG ULTRAGEAR+", "width": 2560, "height": 1440,
      "refreshRate": 239.97, "x": 0, "y": 0, "scale": 1, "transform": 0, "disabled": False,
      "availableModes": ["2560x1440@239.97Hz", "2560x1440@59.95Hz", "1920x1080@60.00Hz", "1366x768@60.00Hz"]}
ASUS = {"name": "DP-2", "description": "ASUSTek COMPUTER INC ASUS VG277Q1A", "width": 1920, "height": 1080,
        "refreshRate": 165.00301, "x": 2560, "y": 0, "scale": 1, "transform": 0, "disabled": False,
        "availableModes": ["1920x1080@165.00Hz", "1920x1080@60.00Hz"]}


@pytest.fixture
def screens(monkeypatch):
    """screens(*monitors): what hyprctl reports while the page is built."""
    def set_(*monitors):
        monkeypatch.setattr(ps, "hypr_json", lambda *a: [dict(m) for m in monitors] if a == ("monitors", "all") else None)
    return set_


@pytest.fixture
def countdown(monkeypatch):
    """Holds the trial's one-second tick instead of starting a real timer; other timers run."""
    ticks = []
    real = GLib.timeout_add

    def timeout_add(ms, fn, *args):
        if getattr(fn, "__name__", "") == "tick":
            ticks.append(fn)
            return 0
        return real(ms, fn, *args)

    monkeypatch.setattr(ps.GLib, "timeout_add", timeout_add)
    return ticks


def screen(p, name):
    """{row title: row} for one screen's group."""
    group = next(g for g in widgets(p.page) if isinstance(g, Adw.PreferencesGroup) and g.get_title() == name)
    return {r.get_title(): r for r in widgets(group) if isinstance(r, Adw.PreferencesRow)}


def labels(row):
    return [row.get_model().get_string(i) for i in range(row.get_model().get_n_items())]


def picked(row):
    return row.get_model().get_string(row.get_selected())


def pick(row, label):
    row.set_selected(labels(row).index(label))
    spin()


def apply_button(p):
    return next(w for w in widgets(p.page) if getattr(w, "get_label", lambda: None)() == "Apply")


def dialog(p):
    d = p.win.get_visible_dialog()
    assert isinstance(d, Adw.AlertDialog), "no dialog open"
    return d


def answer(p, response):
    d = dialog(p)
    d.emit("response", response)
    d.force_close()
    spin()


def evals(sandbox):
    return [c for c in sandbox.run_async if c[:2] == ["hyprctl", "eval"]]


def markers():
    return list(store_mod.CONFIG_DIR.glob(ps.TRIAL_MARKER_NAME + "-*"))


def test_each_screen_shows_what_it_runs(open_page, screens):
    screens(LG, ASUS)
    p = open_page("displays")
    lg, asus = screen(p, "DP-1"), screen(p, "DP-2")
    assert picked(lg["Resolution and refresh rate"]) == "2560 × 1440  ·  239.97 Hz"
    assert labels(lg["Resolution and refresh rate"])[0] == "2560 × 1440  ·  239.97 Hz"  # best first
    assert picked(asus["Resolution and refresh rate"]) == "1920 × 1080  ·  165 Hz"
    assert picked(lg["Scale"]) == "100%" and picked(lg["Rotation"]) == "Normal"
    assert asus["Position X"].get_value() == 2560 and asus["Position Y"].get_value() == 0
    assert lg["Enabled"].get_active()
    assert not apply_button(p).get_sensitive()  # nothing to apply yet


def test_scales_offered_are_the_ones_that_fit_the_resolution(open_page, screens):
    screens(LG)
    p = open_page("displays")
    lg = screen(p, "DP-1")
    assert labels(lg["Scale"]) == ["100%", "125%", "133%", "160%", "167%", "200%", "250%", "400%"]
    pick(lg["Scale"], "200%")
    pick(lg["Resolution and refresh rate"], "1920 × 1080  ·  60 Hz")
    lg = screen(p, "DP-1")
    assert labels(lg["Scale"]) == ["100%", "125%", "133%", "150%", "160%", "167%", "200%", "240%", "250%", "300%",
                                   "400%"]
    assert picked(lg["Scale"]) == "200%"
    pick(lg["Resolution and refresh rate"], "2560 × 1440  ·  59.95 Hz")
    pick(screen(p, "DP-1")["Scale"], "125%")
    pick(screen(p, "DP-1")["Resolution and refresh rate"], "1366 × 768  ·  60 Hz")
    # 125% doesn't divide 1366 × 768 evenly: the scale falls back to 100%, and that is what applies.
    assert labels(screen(p, "DP-1")["Scale"]) == ["100%", "200%"]
    assert picked(screen(p, "DP-1")["Scale"]) == "100%"
    assert p.page.draft["DP-1"]["scale"] == 1


def test_apply_tries_it_live_and_keep_saves_it(sandbox, open_page, screens, countdown, monkeypatch):
    screens(LG, ASUS)
    got = callbacks(monkeypatch, ps)
    p = open_page("displays")
    before = p.lua()
    pick(screen(p, "DP-1")["Resolution and refresh rate"], "2560 × 1440  ·  59.95 Hz")
    assert apply_button(p).get_sensitive()
    apply_button(p).emit("clicked")
    spin()

    (marker,) = markers()
    assert sandbox.spawn[-1] == ["sh", "-c", ps.WATCHDOG, "sh", str(marker), str(ps.TRIAL_SECONDS + 3)]
    (cmd,) = evals(sandbox)
    assert 'mode = "2560x1440@59.95"' in cmd[2] and 'output = "DP-1"' in cmd[2]
    assert "DP-2" not in cmd[2]  # an untouched screen keeps following monitors.lua
    assert p.lua() == before and p.store.monitors == {}  # nothing saved on trial
    assert dialog(p).get_body() == "Reverting in 15 seconds…"
    countdown[-1]()
    assert dialog(p).get_body() == "Reverting in 14 seconds…"

    next(done for c, done in got["async"] if c[:2] == ["hyprctl", "eval"])(0, "ok", "")
    answer(p, "ok")
    assert not markers()
    assert p.toasts[-1] == "Display settings kept"
    assert p.saved()["monitors"]["DP-1"]["mode"] == "2560x1440@59.95"
    assert 'mode = "2560x1440@59.95"' in p.lua()
    assert countdown[-1]() is False  # the countdown stops once kept


def test_the_countdown_running_out_reverts(sandbox, open_page, screens, countdown):
    screens(LG)
    p = open_page("displays")
    before = p.lua()
    pick(screen(p, "DP-1")["Rotation"], "90°")
    apply_button(p).emit("clicked")
    spin()
    tick = countdown[-1]
    for _ in range(ps.TRIAL_SECONDS - 1):
        assert tick() is True
    assert tick() is False
    spin()
    assert ["hyprctl", "reload"] in sandbox.run_async
    assert p.toasts[-1] == "Display settings reverted"
    assert not markers() and p.store.monitors == {} and p.lua() == before
    assert p.win.get_visible_dialog() is None


def test_revert_puts_the_saved_settings_back(sandbox, open_page, screens, countdown):
    screens(LG)
    saved = {"monitors": {"DP-1": {"enabled": True, "mode": "2560x1440@239.97", "x": 0, "y": 0, "scale": 1.25,
                                   "transform": 0}}}
    p = open_page("displays", saved)
    assert picked(screen(p, "DP-1")["Scale"]) == "125%"
    pick(screen(p, "DP-1")["Scale"], "200%")
    apply_button(p).emit("clicked")
    spin()
    answer(p, "cancel")
    assert ["hyprctl", "reload"] in sandbox.run_async  # the saved config comes back
    assert p.store.monitors == saved["monitors"]
    assert not markers()


def test_hyprland_refusing_a_trial_reverts_it(sandbox, open_page, screens, countdown, monkeypatch):
    screens(LG)
    got = callbacks(monkeypatch, ps)
    p = open_page("displays")
    pick(screen(p, "DP-1")["Rotation"], "180°")
    apply_button(p).emit("clicked")
    spin()
    next(done for c, done in got["async"] if c[:2] == ["hyprctl", "eval"])(1, "", "invalid mode")
    spin()
    assert p.toasts[-1] == "Hyprland refused these display settings: invalid mode"
    assert ["hyprctl", "reload"] in sandbox.run_async
    assert not markers() and p.store.monitors == {}
    assert p.win.get_visible_dialog() is None


def test_turning_off_every_screen_is_refused(sandbox, open_page, screens):
    screens(LG, ASUS)
    p = open_page("displays")
    screen(p, "DP-1")["Enabled"].set_active(False)
    screen(p, "DP-2")["Enabled"].set_active(False)
    spin()
    apply_button(p).emit("clicked")
    spin()
    assert p.toasts[-1] == "At least one display has to stay on"
    assert not evals(sandbox) and not markers() and not sandbox.spawn


def test_one_screen_off_is_tried_as_disabled(sandbox, open_page, screens, countdown):
    screens(LG, ASUS)
    p = open_page("displays")
    screen(p, "DP-2")["Enabled"].set_active(False)
    spin()
    apply_button(p).emit("clicked")
    spin()
    (cmd,) = evals(sandbox)
    assert 'hl.monitor({ output = "DP-2", disabled = true })' in cmd[2]


def test_arrange_puts_lit_screens_side_by_side(open_page, screens):
    rotated = dict(ASUS, transform=1, x=9000, y=300)
    screens(dict(LG, x=1920, y=50), rotated)
    p = open_page("displays")
    pick(screen(p, "DP-1")["Scale"], "125%")
    next(w for w in widgets(p.page) if getattr(w, "get_label", lambda: None)() == "Arrange left to right").emit("clicked")
    spin()
    lg, asus = screen(p, "DP-1"), screen(p, "DP-2")
    assert (lg["Position X"].get_value(), lg["Position Y"].get_value()) == (0, 0)
    # 2560 wide at 125% takes 2048 logical pixels; the next screen starts there.
    assert (asus["Position X"].get_value(), asus["Position Y"].get_value()) == (2048, 0)
    assert p.page.draft["DP-2"]["x"] == 2048 and apply_button(p).get_sensitive()


def test_monitors_lua_extras_are_warned_about(sandbox, open_page, screens):
    ps.MONITORS_LUA.write_text('hl.monitor({ output = "DP-1", mode = "preferred", bitdepth = 10, cm = "hdr" })\n')
    screens(LG, ASUS)
    p = open_page("displays")
    groups = {g.get_title(): g.get_description() for g in widgets(p.page) if isinstance(g, Adw.PreferencesGroup)}
    assert "monitors.lua also sets bitdepth, cm for this screen" in groups["DP-1"]
    assert "monitors.lua" not in groups["DP-2"]


def test_all_displays_options_are_saved(open_page, screens):
    screens(LG)
    p = open_page("displays")
    p.choose("Variable refresh rate (VRR)", "Only for fullscreen apps")
    p.switch("Wake screens on key press", False)
    p.save()
    assert p.saved()["hyprland"] == {"misc:vrr": 2, "misc:key_press_enables_dpms": False}
    assert "vrr = 2," in p.lua() and "key_press_enables_dpms = false," in p.lua()


def test_restore_defaults(sandbox, open_page, screens):
    template = "local omarchy_monitor_scale = 1\nlocal omarchy_gdk_scale = 1\n"
    (sandbox.omarchy / "config/hypr").mkdir(parents=True)
    (sandbox.omarchy / "config/hypr/monitors.lua").write_text(template)
    ps.MONITORS_LUA.write_text("local omarchy_monitor_scale = 2\nlocal omarchy_gdk_scale = 2\n"
                               'hl.monitor({ output = "", mode = "preferred", position = "auto", scale = omarchy_monitor_scale })\n')
    screens(LG)
    p = open_page("displays", {"monitors": {"DP-1": {"enabled": True, "mode": "1920x1080@60.00", "x": 0, "y": 0,
                                                     "scale": 2, "transform": 0}},
                               "hyprland": {"misc:vrr": 1, "general:gaps_in": 3}})
    p.press("Restore defaults")
    answer(p, "ok")
    p.save()
    assert p.saved()["monitors"] == {}
    assert p.saved()["hyprland"] == {"general:gaps_in": 3}  # only the display options go
    text = ps.MONITORS_LUA.read_text()
    assert text.startswith(template) and 'output = ""' in text  # scale lines back, the rest kept
    assert list(ps.MONITORS_LUA.parent.glob("monitors.lua.bak*"))  # backed up first

