"""pytest glue. Nothing here is needed for `python3 tests/test_core.py`."""
import pytest


@pytest.fixture(autouse=True)
def _loopback_for_core_tests(request):
    """test_core.py starts a real fake relay on 127.0.0.1.

    The Home Assistant pytest plugin blocks every socket unless a test asks for
    `socket_enabled`, so that one module is allowed loopback. test_ha.py stays
    strictly offline: a Home Assistant test that reaches for the network should
    fail, not quietly work.
    """
    is_core = request.module.__name__.rsplit(".", 1)[-1] == "test_core"
    if is_core:
        try:
            request.getfixturevalue("socket_enabled")
        except pytest.FixtureLookupError:
            pass  # plugin not installed, so nothing is blocking sockets anyway
    yield
    if is_core:
        # test_core.py drives its fake relay with asyncio.run(), which ends by
        # leaving the thread with no current event loop. The next async test in
        # the same session (every one in test_ha.py) then fails with "There is no
        # current event loop", so put one back. Only matters when both files run
        # in one `pytest tests/`; run alone, neither file notices.
        import asyncio

        asyncio.set_event_loop(asyncio.new_event_loop())
