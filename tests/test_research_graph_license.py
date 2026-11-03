"""research-graph's licence in its metadata (wi-brain-rg-license-spdx): MIT as an SPDX expression and the LICENSE file
in license-files (PEP 639), the forms setuptools reads from 77; the `license = { text = ... }` table it deprecates
stops building from 2027-02-18."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = pytest.importorskip("tomli")

REPO = Path(__file__).resolve().parents[1]


def _project():
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))


def test_pyproject_names_mit_and_its_license_file():
    data = _project()
    assert data["project"]["license"] == "MIT"
    assert data["project"]["license-files"] == ["LICENSE"]
    assert (REPO / "LICENSE").read_text(encoding="utf-8").startswith("MIT License\n")
    # an SPDX expression in license and license-files are PEP 639, which setuptools reads from 77
    assert "setuptools>=77" in data["build-system"]["requires"]


def test_built_metadata_names_mit_and_ships_license(tmp_path):
    """The wheel's metadata, as setuptools writes it from a copy of the package's build inputs."""
    setuptools = pytest.importorskip("setuptools")
    if int(setuptools.__version__.split(".")[0]) < 77:
        pytest.skip(f"setuptools {setuptools.__version__} predates PEP 639")
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy(REPO / name, tmp_path / name)
    (tmp_path / "src" / "research_graph").mkdir(parents=True)
    shutil.copy(REPO / "src" / "research_graph" / "__init__.py", tmp_path / "src" / "research_graph" / "__init__.py")
    script = "import setuptools.build_meta as b; print(b.prepare_metadata_for_build_wheel('out'))"
    (tmp_path / "out").mkdir()
    r = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    info = tmp_path / "out" / r.stdout.strip().splitlines()[-1]
    headers = (info / "METADATA").read_text(encoding="utf-8").split("\n\n", 1)[0].splitlines()
    assert "License-Expression: MIT" in headers
    assert "License-File: LICENSE" in headers
    assert not any(h.startswith("License: ") for h in headers)  # the deprecated free-text field is gone
    assert (info / "licenses" / "LICENSE").read_bytes() == (REPO / "LICENSE").read_bytes()
