"""Run manifest-cases.json against `_manifest.parse_and_validate`."""

from __future__ import annotations

import json
from importlib import resources

import pytest

from foro._manifest import ManifestError, parse_and_validate

CASES = json.loads(resources.files("foro").joinpath("manifest-cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_manifest_case(case, tmp_path):
    for name, contents in case["files"].items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    expect = case["expect"]

    if expect["ok"]:
        parse_and_validate(tmp_path, ".")
    else:
        with pytest.raises(ManifestError) as exc_info:
            parse_and_validate(tmp_path, ".")
        assert exc_info.value.reason == expect["reason"]
