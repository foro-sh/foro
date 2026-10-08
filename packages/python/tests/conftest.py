import pytest

from foro import _api


@pytest.fixture(autouse=True)
def no_workspace_between_tests():
    """The workspace header is per-invocation state; one test must not leak it
    into the next."""
    _api.set_workspace(None)
    yield
    _api.set_workspace(None)
