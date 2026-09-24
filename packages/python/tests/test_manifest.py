"""`_manifest.py` cases the shared table cannot express: `manifest_path`
and resolved runtime versions."""

from __future__ import annotations

import pytest

from foro._manifest import (
    ManifestError,
    egress_entry_error,
    is_valid_repo_path,
    parse_and_validate,
    resolve_runtime_version,
)


def test_rejects_manifest_path_with_traversal(tmp_path):
    with pytest.raises(ManifestError) as exc_info:
        parse_and_validate(tmp_path, "../outside")
    assert exc_info.value.reason == "invalid_build_path"


def test_rejects_manifest_path_with_shell_metachar(tmp_path):
    with pytest.raises(ManifestError) as exc_info:
        parse_and_validate(tmp_path, "x && whoami")
    assert exc_info.value.reason == "invalid_build_path"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (".", True),
        ("services/api", True),
        ("src/server.py", True),
        ("/etc", False),
        ("../escape", False),
        ("a/../../b", False),
        ("x && whoami", False),
        ("a b", False),
        ("x\ny", False),
        ("foo.py\n", False),
        ("", False),
    ],
)
def test_is_valid_repo_path(path, expected):
    assert is_valid_repo_path(path) is expected


@pytest.mark.parametrize(
    ("spec", "runtime", "expected"),
    [
        ("^22 || ^24", "node", "24"),
        ("^20 || ^22", "node", "22"),
        ("22 || 24", "node", "24"),
        (">=22", "node", "24"),
        ("^22.0.0", "node", "22"),
        (">=3.11,!=3.13", "python", "3.12"),
        (">=3.10,!=3.12", "python", "3.13"),
        (">=3.11,<3.13", "python", "3.12"),
        ("==3.11.*", "python", "3.11"),
        ("~=3.11", "python", "3.13"),
        ("", "python", "3.12"),
        ("whatever a spec can say", "python", "3.12"),
    ],
)
def test_resolve_runtime_version(spec, runtime, expected):
    assert resolve_runtime_version(spec, runtime) == expected


@pytest.mark.parametrize(
    ("spec", "runtime"),
    [("^20", "node"), ("<22", "node"), (">=3.11,!=3.11,!=3.12,!=3.13", "python")],
)
def test_resolve_runtime_version_rejects_a_range_with_no_supported_version(spec, runtime):
    with pytest.raises(ManifestError) as exc_info:
        resolve_runtime_version(spec, runtime)
    assert exc_info.value.reason == "invalid_runtime_version"


def _write_pyproject(tmp_path, contents):
    (tmp_path / "pyproject.toml").write_text(contents)
    (tmp_path / "server.py").write_text("")


def test_egress_is_none_when_absent(tmp_path):
    _write_pyproject(tmp_path, '[project]\nname = "my-server"\n')
    assert parse_and_validate(tmp_path, ".").egress is None


def test_egress_is_empty_list_when_declared_empty(tmp_path):
    _write_pyproject(
        tmp_path,
        '[project]\nname = "my-server"\n\n[tool.foro]\nentrypoint = "server.py"\negress = []\n',
    )
    assert parse_and_validate(tmp_path, ".").egress == []


def test_egress_preserves_order_and_contents(tmp_path):
    _write_pyproject(
        tmp_path,
        '[project]\nname = "my-server"\n\n[tool.foro]\nentrypoint = "server.py"\n'
        'egress = ["b.example.com:443", "a.example.com:443", "10.0.0.0/8:5432"]\n',
    )
    assert parse_and_validate(tmp_path, ".").egress == [
        "b.example.com:443",
        "a.example.com:443",
        "10.0.0.0/8:5432",
    ]


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ("10.1.2.3/8:443", True),
        ("10.0.0.0/8:443", True),
        ("192.168.0.0/16:443", True),
        ("172.0.0.0/8:443", False),
        ("172.16.5.5/12:443", False),
        ("example.com:443\n", False),
    ],
)
def test_egress_entry_error(entry, expected):
    assert (egress_entry_error(entry) is None) is expected


def test_egress_entry_error_hostname_length_boundary():
    ok = ("aaaa." * 50) + "aaa"
    too_long = ok + "a"
    assert len(ok) == 253
    assert len(too_long) == 254
    assert egress_entry_error(f"{ok}:443") is None
    assert egress_entry_error(f"{too_long}:443") is not None
