"""Direct unit tests for `_manifest.py` that manifest-cases.json can't
express: `manifest_path` is a `parse_and_validate` argument, not a config
field, so its rejection cases live here rather than in the shared table
(mirrors foro-sh/platform's manifest.test.ts, which does the same for its
`manifest_path` describe block and the `isValidRepoPath` table). The shared
table carries only ok/reason, so which version a range resolves *to* lives
here too.
"""

from __future__ import annotations

import pytest

from foro._manifest import (
    ManifestError,
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
        # `||` is a union of ranges. Reading it as one more clause to
        # intersect makes `^22 || ^24` - the idiomatic way to declare both
        # majors foro supports - resolve to nothing at all.
        ("^22 || ^24", "node", "24"),
        ("^20 || ^22", "node", "22"),
        ("22 || 24", "node", "24"),
        (">=22", "node", "24"),
        ("^22.0.0", "node", "22"),
        # `!=` excludes; without it in the operator table the version reads as
        # a bare `==` pin on the one version the project ruled out.
        (">=3.11,!=3.13", "python", "3.12"),
        (">=3.10,!=3.12", "python", "3.13"),
        (">=3.11,<3.13", "python", "3.12"),
        ("==3.11.*", "python", "3.11"),
        ("~=3.11", "python", "3.13"),
        # Unreadable or absent: the default, never a guess.
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
