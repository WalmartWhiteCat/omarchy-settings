"""Pages for tools that aren't installed are left out of the sidebar (a page that does nothing only confuses), and so is a section with nothing left."""

import pytest

from osettings import pages_ohm as po
from osettings import pages_widgets as pw

from .pagekit import needs_display, open_page  # noqa: F401  (open_page is a fixture)

pytestmark = needs_display
TOOLS = {"notes", "notebook", "ohm", "ohm-memory"}


def remove(*which):
    for w in which:
        if w == "notes":
            pw.NOTES_PLUGIN.rmdir()
        elif w == "notebook":
            pw.NOTEBOOK_BIN.unlink()
        else:
            po.OHM_BIN.unlink()


def shown(p):
    return {row.key for row in iter_rows(p.win.sidebar)}


def iter_rows(listbox):
    row = listbox.get_first_child()
    while row:
        if hasattr(row, "key"):      # the list's own placeholder label has none
            yield row
        row = row.get_next_sibling()


def test_everything_installed_shows_every_tools_page(sandbox, open_page):
    p = open_page("theme")
    assert TOOLS <= shown(p) and [n for n, _ in p.win.sections][-1] == "Tools"


@pytest.mark.parametrize("gone, hidden", [(("notes",), {"notes"}), (("notebook",), {"notebook"}), (("ohm",), {"ohm", "ohm-memory"}),
                                          (("notes", "notebook", "ohm"), TOOLS)])
def test_a_tool_that_isnt_installed_has_no_page(sandbox, open_page, gone, hidden):
    remove(*gone)
    p = open_page("theme")
    assert not (hidden & shown(p)) and (TOOLS - hidden) <= shown(p)
    assert not (hidden & set(p.win.classes))


def test_the_section_goes_when_nothing_in_it_is_installed(sandbox, open_page):
    remove("notes", "notebook", "ohm")
    p = open_page("theme")
    assert "Tools" not in [n for n, _ in p.win.sections] and len(p.win.sections) == 4


def test_another_program_called_ohm_on_the_path_does_not_count(sandbox, open_page, monkeypatch):
    """`ohm` is a short generic name: only the launcher Qwen3.6-OHM's installer makes shows the pages."""
    po.OHM_BIN.unlink()
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ohm" if name == "ohm" else None)
    assert not po.OhmControlPage.available() and not po.OhmMemoryPage.available()
    po.OHM_BIN.write_text("")
    assert po.OhmControlPage.available()


def test_asking_for_a_hidden_page_opens_the_first_one(sandbox, open_page):
    remove("notebook")                      # `omarchy-settings --page notebook`, but Notebook isn't installed
    p = open_page("notebook")
    assert p.win.content.get_title() == "Theme"


def test_the_always_there_pages_stay(sandbox, open_page):
    remove("notes", "notebook", "ohm")
    p = open_page("theme")
    assert {"theme", "background", "windows", "bar", "keys"} <= shown(p)
