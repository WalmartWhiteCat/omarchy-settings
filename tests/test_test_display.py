"""The tests' own invisible display: stale sockets are reused, live ones left alone."""

import socket

from . import conftest


def test_free_socket(tmp_path):
    missing = tmp_path / "broadway91.socket"
    assert conftest._free_socket(missing)

    stale = tmp_path / "broadway92.socket"
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(stale))
    s.close()  # the file stays, with nothing listening: a killed run's leftover
    assert stale.exists()
    assert conftest._free_socket(stale)
    assert not stale.exists()

    live = tmp_path / "broadway93.socket"
    with socket.socket(socket.AF_UNIX) as listening:
        listening.bind(str(live))
        listening.listen()
        assert not conftest._free_socket(live)
        assert live.exists()


def test_window_tests_need_the_invisible_display():
    from . import test_window
    mark = test_window.pytestmark
    assert mark.name == "skipif" and mark.args == (not conftest.HEADLESS,)
