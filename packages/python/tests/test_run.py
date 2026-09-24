import os

import pytest

from foro import run


class _FakeServer:

    def __init__(self):
        self.run_kwargs = None

    def run(self, **kwargs):
        self.run_kwargs = kwargs


class FakeStandaloneFastMCP(_FakeServer):
    pass


class FakeMCPServerFastMCP(_FakeServer):
    pass


class FakeLowLevelServer(_FakeServer):
    pass


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


class FakeBannerServer(_FakeServer):

    def run(self, show_banner=None, **kwargs):
        self.run_kwargs = {**kwargs, "show_banner": show_banner}


def test_run_suppresses_the_fastmcp_banner_when_supported(monkeypatch):
    monkeypatch.delenv("PROJECT_SLUG", raising=False)
    server = FakeBannerServer()

    run(server)

    assert server.run_kwargs["show_banner"] is False


@pytest.mark.parametrize("server_cls", FLAVORS)
def test_run_omits_show_banner_for_servers_that_do_not_take_it(server_cls, monkeypatch):
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
    monkeypatch.setenv("PROJECT_SLUG", "swift-harbor-a3f2")

    run(FakeBannerServer())

    assert capsys.readouterr().out == ""


def test_run_does_not_override_an_explicit_banner_preference(monkeypatch):
    monkeypatch.setenv("FASTMCP_SHOW_SERVER_BANNER", "true")

    run(FakeBannerServer())

    assert os.environ["FASTMCP_SHOW_SERVER_BANNER"] == "true"


def test_an_explicit_port_is_not_mistaken_for_no_port(monkeypatch):
    """`port or ...` treated 0 as missing and used $PORT."""
    monkeypatch.setenv("PORT", "9001")

    with pytest.raises(ValueError, match="between 1 and 65535"):
        run(FakeStandaloneFastMCP(), port=0)


@pytest.mark.parametrize("bad", [-1, 65536])
def test_a_port_outside_the_valid_range_is_refused(bad, monkeypatch):
    monkeypatch.delenv("PORT", raising=False)

    with pytest.raises(ValueError, match="between 1 and 65535"):
        run(FakeStandaloneFastMCP(), port=bad)


def test_a_non_numeric_port_names_the_variable(monkeypatch):
    """Must name PORT, not raise int()'s ValueError."""
    monkeypatch.setenv("PORT", "eight thousand")

    with pytest.raises(ValueError, match="PORT is not a number"):
        run(FakeStandaloneFastMCP())
