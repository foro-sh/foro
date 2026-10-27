from __future__ import annotations

import socket

import pytest


@pytest.fixture
def free_port() -> int:
    """A port nothing is listening on, so dev tests don't collide with whatever
    else the machine runs on the default 8000."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
