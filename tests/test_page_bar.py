"""Bar page, built for real (see pagekit). Older Bar tests (stand-ins) are in test_review_fixes."""

import json

from gi.repository import Adw, Gtk

from osettings import pages_system as ps

from .pagekit import needs_display, open_page  # noqa: F401

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
