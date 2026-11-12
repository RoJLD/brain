"""Each format as a released engine wrote it (wi-brain-format-fixture-freeze; spec-brain-data-compat N8, COMPAT-1):
tests/fixtures/formats/<format>/v<N>/<tag>.<ext>, frozen by installer/freeze_store.py from the brain that tag's engine
wrote through its own commands (the old-store fixture's), and never edited. This checkout reads each one strict
(BRAIN_STRICT=1, as CI): N reads what N-1 wrote with no note and no error. The hand-written older/newer pair beside
them (test_formats_compat) stays the tolerant reader's test."""

import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from brain import init, neutral, projects, schema

FORMATS = Path(__file__).parent / "fixtures" / "formats"
TAG = re.compile(r"^v\d+\.\d+\.\d+$")
FROZEN = sorted(p for p in FORMATS.glob("*/v*/*") if p.is_file() and TAG.match(p.stem))
JSON_LINES = ("ar", "event")          # one record per line
RECORDS = ("ddr", "sr")               # one record per file


def ids(p: Path) -> str:
    return f"{p.parent.parent.name}/{p.parent.name}/{p.name}"


def test_formats_are_frozen_from_released_engines():
    """At least the formats a brain init and its first commands write, from more than one tag."""
    assert {p.parent.parent.name for p in FROZEN} >= {"ar", "config", "ddr", "event", "packs", "projects", "sr",
                                                       "template"}
    assert len({p.stem for p in FROZEN}) >= 2
    assert not [p for p in FROZEN if p.parent.parent.name == "status"]   # a machine's inventory: never frozen


@pytest.mark.parametrize("path", FROZEN, ids=ids)
def test_this_engine_reads_it_strict(path, tmp_path, monkeypatch):
    fmt, v = path.parent.parent.name, int(path.parent.name[1:])
    text = path.read_text(encoding="utf-8")
    if fmt in JSON_LINES:
        for line in text.splitlines():
            record = json.loads(line)
            assert schema.check(fmt, record) == ([], []), line
    elif fmt in RECORDS:
        assert schema.check(fmt, yaml.safe_load(text)) == ([], [])
    elif fmt == "config":   # its schema (brain.config's check also asks its folders to exist: the brain's, not the format)
        assert schema.check("config", json.loads(text)) == ([], [])
    elif fmt == "projects":
        root = tmp_path / "brain"
        root.mkdir()
        shutil.copyfile(path, root / "projects.yaml")
        monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
        assert projects.check(root) == []
    elif fmt == "packs":
        monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "none.json"))
        (tmp_path / neutral.FOLDER).mkdir(parents=True)
        shutil.copyfile(path, tmp_path / neutral.FOLDER / neutral.PACKS)
        assert neutral.check(neutral.load(tmp_path), nodes=[]) == []
    elif fmt == "template":
        folder = tmp_path / "template"
        shutil.copytree(init.TEMPLATES / init.DEFAULT_TEMPLATE, folder)
        shutil.copyfile(path, folder / init.MANIFEST)
        assert init.load_template(str(folder)).name == "generic"
    else:
        pytest.fail(f"{fmt}: no reader in this test for a frozen file: add its read here")
    assert v == 1   # every format is at v1 so far: a v2 frozen here comes with its migration (formats.md)
