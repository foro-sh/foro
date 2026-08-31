import os

import pytest

from foro import run


class _FakeServer:
    """Records .run() kwargs instead of actually serving anything."""

    def __init__(self):
        self.run_kwargs = None

    def run(self, **kwargs):
        self.run_kwargs = kwargs


class FakeStandaloneFastMCP(_FakeServer):
    """Stands in for fastmcp.FastMCP."""


class FakeMCPServerFastMCP(_FakeServer):
    """Stands in for mcp.server.fastmcp.FastMCP."""


class FakeLowLevelServer(_FakeServer):
    """Stands in for mcp.server.lowlevel.Server."""


FLAVORS = [FakeStandaloneFastMCP, FakeMCPServerFastMCP, FakeLowLevelServer]


@pytest.mark.parametrize("server_cls", FLAVORS)
def test_run_defaults_to_port_8000_without_port_env(server_cls, monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    server = server_cls()

    run(server)

    assert server.run_kwargs == {
        "transport": "http",
        "host": "0.0.0.0",
        "port": 8000,
    }


@pytest.mark.parametrize("server_cls", FLAVORS)
def test_run_reads_port_from_port_env(server_cls, monkeypatch):
    monkeypatch.setenv("PORT", "9001")
    server = server_cls()

    run(server)

    assert server.run_kwargs == {
        "transport": "http",
        "host": "0.0.0.0",
        "port": 9001,
    }


def test_run_explicit_port_overrides_env(monkeypatch):
    monkeypatch.setenv("PORT", "9001")
    server = FakeStandaloneFastMCP()

    run(server, port=1234)

    assert server.run_kwargs["port"] == 1234


# --- startup banner -------------------------------------------------------


class FakeBannerServer(_FakeServer):
    """Stands in for a real fastmcp.FastMCP, whose run() takes show_banner."""

    def run(self, show_banner=None, **kwargs):
        self.run_kwargs = {**kwargs, "show_banner": show_banner}


def test_run_suppresses_the_fastmcp_banner_when_supported(monkeypatch):
    monkeypatch.delenv("PROJECT_SLUG", raising=False)
    server = FakeBannerServer()

    run(server)

    assert server.run_kwargs["show_banner"] is False


@pytest.mark.parametrize("server_cls", FLAVORS)
def test_run_omits_show_banner_for_servers_that_do_not_take_it(server_cls, monkeypatch):
    # A **kwargs catch-all doesn't count as support: forwarding show_banner
    # into a transport that's never heard of it is worse than one extra banner.
    monkeypatch.delenv("PROJECT_SLUG", raising=False)
    server = server_cls()

    run(server)

    assert "show_banner" not in server.run_kwargs


def test_run_prints_the_foro_banner(monkeypatch, capsys):
    monkeypatch.delenv("PROJECT_SLUG", raising=False)

    run(FakeBannerServer(), port=1234)

    out = capsys.readouterr().out
    assert "██████╗" in out
    assert "port 1234" in out


def test_run_leaves_the_banner_to_the_wrapper_inside_a_container(monkeypatch, capsys):
    # PROJECT_SLUG only exists in a platform-created container, where the
    # wrapper script already printed this art before exec'ing the server.
    monkeypatch.setenv("PROJECT_SLUG", "swift-harbor-a3f2")

    run(FakeBannerServer())

    assert capsys.readouterr().out == ""


def test_run_does_not_override_an_explicit_banner_preference(monkeypatch):
    monkeypatch.setenv("FASTMCP_SHOW_SERVER_BANNER", "true")

    run(FakeBannerServer())

    assert os.environ["FASTMCP_SHOW_SERVER_BANNER"] == "true"


def test_an_explicit_port_is_not_mistaken_for_no_port(monkeypatch):
    """`port or ...` read an explicit 0 as "not given" and fell through to
    $PORT, so the caller's argument vanished without a word."""
    monkeypatch.setenv("PORT", "9001")

    with pytest.raises(ValueError, match="between 1 and 65535"):
        run(FakeStandaloneFastMCP(), port=0)


@pytest.mark.parametrize("bad", [-1, 65536])
def test_a_port_outside_the_valid_range_is_refused(bad, monkeypatch):
    monkeypatch.delenv("PORT", raising=False)

    with pytest.raises(ValueError, match="between 1 and 65535"):
        run(FakeStandaloneFastMCP(), port=bad)


def test_a_non_numeric_port_names_the_variable(monkeypatch):
    """It used to surface as `invalid literal for int() with base 10`."""
    monkeypatch.setenv("PORT", "eight thousand")

    with pytest.raises(ValueError, match="PORT is not a number"):
        run(FakeStandaloneFastMCP())
