"""Bar page, built for real (see pagekit). Older Bar tests (stand-ins) are in test_review_fixes."""

import json

import pytest
from gi.repository import Adw, Gtk

from osettings import pages_system as ps

from .pagekit import callbacks, needs_display, open_page, spin, widgets  # noqa: F401

pytestmark = needs_display


def labels(widget):
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        if isinstance(w, Gtk.Label):
            out.append(w.get_text())
        child = w.get_first_child()
        while child:
            stack.append(child)
            child = child.get_next_sibling()
    return out


def test_widget_names_are_shown_as_written(sandbox, open_page):
    """Rows use Pango markup: a name or id with & or < used to show as a blank or broken row."""
    ps.SHELL_JSON.parent.mkdir(parents=True)
    ps.SHELL_JSON.write_text(json.dumps({"bar": {"layout": {"left": ["me.tips&tricks"], "center": [],
                                                            "right": []}}}))
    sandbox.run_output[("omarchy", "plugin", "list", "--json")] = json.dumps([
        {"id": "me.tips&tricks", "name": "Tips & <Tricks>", "kinds": ["bar-widget"]}])
    p = open_page("bar")
    row = next(r for r in p.rows(Adw.ActionRow) if "Tricks" in r.get_title())
    shown = labels(row)
    assert "Tips & <Tricks>" in shown and "me.tips&tricks" in shown


CATALOG = [
    {"id": "omarchy.clock", "name": "Clock", "kinds": ["bar-widget"]},
    {"id": "omarchy.menu", "name": "Omarchy menu", "kinds": ["bar-widget", "launcher"]},
    {"id": "omarchy.tray", "name": "Tray", "kinds": ["bar-widget"]},
    {"id": "omarchy.audio", "name": "Audio", "kinds": ["bar-widget"], "canDisable": False},
    {"id": "me.weather", "name": "Weather", "kinds": ["bar-widget"]},
    {"id": "me.service", "name": "Not a widget", "kinds": ["service"]},
]
LAYOUT = {"left": ["omarchy.menu", {"id": "omarchy.clock", "format": "HH:mm", "formatAlt": "dddd"}],
          "center": [], "right": ["omarchy.tray", "omarchy.audio"]}


@pytest.fixture
def bar(sandbox, monkeypatch):
    """A bar laid out as LAYOUT, Omarchy's plugin catalog, and Omarchy's default shell.json."""
    ps.SHELL_JSON.parent.mkdir(parents=True)
    ps.SHELL_JSON.write_text(json.dumps({"bar": {"position": "bottom", "transparent": True, "layout": LAYOUT}}))
    sandbox.run_output[("omarchy", "plugin", "list", "--json")] = json.dumps(CATALOG)
    (sandbox.omarchy / "config/omarchy").mkdir(parents=True)
    (sandbox.omarchy / "config/omarchy/shell.json").write_text(json.dumps({"bar": {
        "position": "top", "transparent": False,
        "layout": {"left": [{"id": "omarchy.clock", "format": "dddd HH:mm", "formatAlt": "d MMMM"}]}}}))
    return callbacks(monkeypatch, ps)


def section_rows(p, section):
    group = next(g for g in widgets(p.page) if isinstance(g, Adw.PreferencesGroup)
                 and g.get_title() == f"{section.title()} widgets")
    return [r for r in widgets(group) if isinstance(r, Adw.ActionRow)]


def button(row, tooltip):
    return next(w for w in widgets(row) if isinstance(w, Gtk.Button) and w.get_tooltip_text() == tooltip)


def test_bar_settings(sandbox, open_page, bar):
    p = open_page("bar")
    assert p.row("Position", Adw.ComboRow).get_selected() == 1 and p.row("Transparent").get_active()
    p.choose("Position", "Left")
    assert sandbox.run_async[-1] == ["omarchy", "bar", "position", "left"]
    p.switch("Transparent", False)
    assert sandbox.run_async[-1] == ["omarchy", "bar", "transparent", "false"]
    p.press("Show / hide bar")
    assert sandbox.run_async[-1] == ["omarchy", "toggle", "bar"]
    bar["async"][-1][1](0, "Bar hidden\n", "")
    assert p.toasts[-1] == "Bar hidden"
    bar["async"][-1][1](1, "", "")
    assert p.toasts[-1] == "Done"


def test_clock_format(sandbox, open_page, bar):
    p = open_page("bar")
    assert p.row("Format", Adw.EntryRow).get_text() == "HH:mm"
    assert p.row("Format when clicked", Adw.EntryRow).get_text() == "dddd"
    p.enter("Format", "h:mm AP")
    assert sandbox.run_async[-1] == ["omarchy", "bar", "set", "omarchy.clock", "format", "h:mm AP"]
    next(w for w in widgets(p.page) if isinstance(w, Gtk.Button) and w.get_label() == "Date + time").emit("clicked")
    spin()
    assert sandbox.run_async[-1] == ["omarchy", "bar", "set", "omarchy.clock", "format", "d MMM HH:mm"]


def test_widgets_are_listed_by_section_and_move(sandbox, open_page, bar):
    p = open_page("bar")
    assert [r.get_title() for r in section_rows(p, "left")] == ["Omarchy menu", "Clock"]
    assert [r.get_title() for r in section_rows(p, "center")] == ["Empty"]
    menu, clock = section_rows(p, "left")
    assert not button(menu, "Move up").get_sensitive() and button(menu, "Move down").get_sensitive()
    assert button(clock, "Move up").get_sensitive() and not button(clock, "Move down").get_sensitive()
    button(clock, "Move up").emit("clicked")
    spin()
    assert bar["chain"][-1][0] == [["omarchy", "bar", "move", "omarchy.clock", "--section", "left", "--index", "0"]]
    menu_button = next(w for w in widgets(clock) if isinstance(w, Gtk.MenuButton))
    assert menu_button.get_tooltip_text() == "Move to section"
    assert [w.get_label() for w in widgets(menu_button.get_popover()) if isinstance(w, Gtk.Button)] == [
        "Move to center", "Move to right"]  # not its own section
    to_center = next(w for w in widgets(menu_button.get_popover())
                     if isinstance(w, Gtk.Button) and w.get_label() == "Move to center")
    to_center.emit("clicked")
    spin()
    assert bar["chain"][-1][0] == [["omarchy", "bar", "move", "omarchy.clock", "--section", "center"]]
    bar["chain"][-1][1](["omarchy bar move: no such section"])
    assert p.toasts[-1] == "omarchy bar move: no such section"
    # A widget Omarchy says can't be disabled has no remove button.
    audio = section_rows(p, "right")[1]
    assert not any(isinstance(w, Gtk.Button) and w.get_tooltip_text() == "Remove from bar" for w in widgets(audio))


def test_removing_a_widget_disables_its_plugin(sandbox, open_page, bar):
    p = open_page("bar")
    button(section_rows(p, "right")[0], "Remove from bar").emit("clicked")
    spin()
    assert bar["chain"][-1][0] == [["omarchy", "plugin", "disable", "omarchy.tray"]]


def test_removing_a_widget_that_is_more_than_a_widget_only_takes_it_off_the_bar(sandbox, open_page, bar):
    # omarchy.menu is also the Omarchy menu: disabling the plugin would break that.
    p = open_page("bar")
    button(section_rows(p, "left")[0], "Remove from bar").emit("clicked")
    spin()
    assert not [c for c in bar["chain"] if c[0][0][:3] == ["omarchy", "plugin", "disable"]]
    layout = json.loads(ps.SHELL_JSON.read_text())["bar"]["layout"]
    assert layout["left"] == [LAYOUT["left"][1]] and layout["right"] == LAYOUT["right"]
    assert [r.get_title() for r in section_rows(p, "left")] == ["Clock"]


def test_adding_a_widget(sandbox, open_page, bar):
    p = open_page("bar")
    widget = p.row("Widget", Adw.ComboRow)
    assert [widget.get_model().get_string(i) for i in range(widget.get_model().get_n_items())] == ["Weather"]
    p.choose("Section", "Center")
    p.press("Add to bar")
    cmds, done = bar["chain"][-1]
    assert cmds == [["omarchy", "plugin", "enable", "me.weather"], ["omarchy", "bar", "put", "me.weather", "--section", "center"]]
    done([])
    assert p.toasts[-1] == "Widget added"


def test_nothing_to_add_when_every_widget_is_on_the_bar(sandbox, open_page, bar):
    sandbox.run_output[("omarchy", "plugin", "list", "--json")] = json.dumps(CATALOG[:4])
    p = open_page("bar")
    widget = p.row("Widget", Adw.ComboRow)
    assert widget.get_model().get_string(0) == "Every widget is on the bar" and not widget.get_sensitive()
    p.page.add_widget()
    assert bar["chain"] == []


def answer(p, title):
    p.press(title)
    d = p.win.get_visible_dialog()
    d.emit("response", "ok")
    d.force_close()
    spin()


def test_restore_bar_settings_keeps_the_widgets(sandbox, open_page, bar):
    p = open_page("bar")
    answer(p, "Restore defaults")
    cmds, done = bar["chain"][-1]
    assert cmds == [["omarchy", "bar", "position", "top"], ["omarchy", "bar", "transparent", "false"],
                    ["omarchy", "toggle", "bar", "off"],  # "off" removes the bar-off flag: the bar shows
                    ["omarchy", "bar", "set", "omarchy.clock", "format", "dddd HH:mm"],
                    ["omarchy", "bar", "set", "omarchy.clock", "formatAlt", "d MMMM"]]
    done([])
    assert p.toasts[-1] == "Bar restored"


def test_restore_default_bar_widgets(sandbox, open_page, bar):
    p = open_page("bar")
    answer(p, "Restore default bar widgets")
    cmds, done = bar["chain"][-1]
    assert cmds == [["omarchy", "bar", "defaults"]]
    done(["omarchy bar defaults: failed"])
    assert p.toasts[-1] == "Reset failed: omarchy bar defaults: failed"
    done([])
    assert p.toasts[-1] == "Bar widgets restored"
