"""Direct unit tests for `_node_project.detect_dependency_manager`, ported
from foro-sh/platform's apps/api/src/services/node-project.ts. Otherwise the
module is only exercised indirectly through `run_check()`, and only ever hits
the pnpm branch, since `tests/fixtures/node-minimal/` ships a pnpm-lock.yaml.
"""

from __future__ import annotations

import pytest

from foro._node_project import NodeDependencyManagerError, detect_dependency_manager


# --- lockfile detection ---------------------------------------------------


def test_detects_npm_from_package_lock(tmp_path):
    (tmp_path / "package-lock.json").write_text("{}")

    assert detect_dependency_manager(tmp_path) == "npm"


def test_detects_pnpm_from_pnpm_lock(tmp_path):
    (tmp_path / "pnpm-lock.yaml").write_text("")

    assert detect_dependency_manager(tmp_path) == "pnpm"


def test_detects_yarn_from_yarn_lock(tmp_path):
    (tmp_path / "yarn.lock").write_text("")

    assert detect_dependency_manager(tmp_path) == "yarn"


def test_bare_package_json_falls_back_to_npm(tmp_path):
    (tmp_path / "package.json").write_text("{}")

    assert detect_dependency_manager(tmp_path) == "npm"


def test_raises_when_nothing_recognisable_present(tmp_path):
    with pytest.raises(NodeDependencyManagerError, match="No recognised Node project"):
        detect_dependency_manager(tmp_path)
