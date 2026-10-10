"""Power and Notifications page, built for real (see pagekit): the idle times it writes to
~/.config/omarchy/shell.json."""

import json

from osettings import pages_system as ps

from .pagekit import needs_display, open_page  # noqa: F401

pytestmark = needs_display


def test_idle_times_go_to_their_own_keys(sandbox, open_page):
    # Omarchy's idle service reads idle.screensaver as the screensaver timeout and idle.lock as
    # the lock timeout (shell/plugins/services/idle/Service.qml); the rows once had them swapped.
    ps.SHELL_JSON.parent.mkdir(parents=True, exist_ok=True)
    ps.SHELL_JSON.write_text(json.dumps({"idle": {"screensaver": 150, "lock": 300}}))
    p = open_page("power")
    assert p.row("Start screensaver after").get_value() == 2.5
    assert p.row("Lock screen after").get_value() == 5
    p.number("Lock screen after", 10)
    assert json.loads(ps.SHELL_JSON.read_text())["idle"] == {"screensaver": 150, "lock": 600}
    p.number("Start screensaver after", 3)
    assert json.loads(ps.SHELL_JSON.read_text())["idle"] == {"screensaver": 180, "lock": 600}
