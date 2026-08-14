"""Runs the shared manifest-cases.json table against _manifest.parse_and_validate.

This table is published in both SDK packages specifically so
foro-sh/platform's manifest.test.ts can run the same cases against its own
parseAndValidate - the two sides can never silently drift apart on what's
valid (see foro-sh/foro#5). The platform imports it from
`@foro-sh/foro/manifest-cases`, which the TypeScript package generates from
this same JSON at build time (packages/typescript/scripts).
"""

from __future__ import annotations

import json
from importlib import resources

import pytest

from foro._manifest import ManifestError, parse_and_validate

CASES = json.loads(resources.files("foro").joinpath("manifest-cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_manifest_case(case, tmp_path):
    # Entry-file inference reads the directory, so a case declares whatever
    # has to be on disk - the config file plus, where it matters, the file the
    # config points at.
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
