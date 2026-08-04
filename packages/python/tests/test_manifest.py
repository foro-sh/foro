"""Direct unit tests for `_manifest.py` that manifest-cases.json can't
express: `manifest_path` is a `parse_and_validate` argument, not a
`foro.yaml` field, so its rejection cases live here rather than in the shared
table (mirrors foro-sh/platform's manifest.test.ts, which does the same for
its `manifest_path` describe block and the `isValidRepoPath` table).
"""

from __future__ import annotations

import pytest

from foro._manifest import ManifestError, is_valid_repo_path, parse_and_validate


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
