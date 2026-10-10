"""CLAUDE.md must keep matching the code. These check what can be checked mechanically: a change
that renames or adds a page, a test file, a helper or a path fails here until the notes follow.
(The rest is on whoever makes the change: see "Keeping these notes true" in CLAUDE.md.)"""

import re

from osettings import window

from . import pagekit
from .conftest import ROOT

NOTES = (ROOT / "CLAUDE.md").read_text()
TABLE = NOTES.split("## Pages", 1)[1].split("\n\n", 2)[2].split("\n\n", 1)[0]


def table_rows():
    rows = [r for r in TABLE.splitlines() if r.startswith("|") and "`" in r]
    out = {}
    for r in rows:
        cells = [c.strip() for c in r.strip("|").split("|")]
        key = re.search(r"\(`(\w+)`\)", cells[1]).group(1)
        out[key] = cells
    return out


def test_every_page_is_in_the_table_and_nothing_else():
    keys = {cls.key: cls for _, classes in window.SECTIONS for cls in classes}
    assert set(table_rows()) == set(keys)


def test_table_names_each_pages_class_file_and_title():
    keys = {cls.key: cls for _, classes in window.SECTIONS for cls in classes}
    for key, cells in table_rows().items():
        cls = keys[key]
        assert cells[1].startswith(cls.title), (key, cells[1])
        klass, module = [c.strip(" `") for c in cells[2].split(",")]
        assert klass == cls.__name__, (key, klass)
        assert cls.__module__ == f"osettings.{module}", (key, module)


def test_sidebar_sections_match():
    sections = [c[0] for c in table_rows().values() if c[0]]
    assert sections == [s for s, _ in window.SECTIONS]


def test_every_test_file_named_exists():
    named = set(re.findall(r"\b(test_\w+)(?:\.py)?\b", NOTES))
    files = {p.stem for p in (ROOT / "tests").glob("test_*.py")}
    missing = {n for n in named if n not in files and not n.endswith("_")}  # test_page_*.py: a pattern
    assert not missing, f"CLAUDE.md names test files that don't exist: {sorted(missing)}"


def test_every_page_test_file_is_in_the_table():
    page_files = {p.stem for p in (ROOT / "tests").glob("test_page_*.py")}
    assert page_files <= set(re.findall(r"\b(test_page_\w+)\b", TABLE))


def test_pagekit_helpers_named_exist():
    documented = re.findall(r"`(\w+)\((?:title|tooltip|key|monkeypatch)", NOTES)
    opened = set(dir(pagekit.Opened)) | set(dir(pagekit))
    assert documented and not set(documented) - opened - {"open_page"}, set(documented) - opened


def test_files_named_in_layout_exist():
    for name in re.findall(r"`((?:osettings/|tests/)?[\w/]+\.(?:py|sh|md))`", NOTES):
        candidates = [ROOT / name, ROOT / "osettings" / name, ROOT / "tests" / name]
        assert any(c.exists() for c in candidates), name
