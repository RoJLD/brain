"""The brain package's licence (wi-brain-engine-license): the Business Source License 1.1 from 0.2.2, its NOTICE kept
with every copy, both named in the package's metadata; research-graph, the repo's other package, stays MIT."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = pytest.importorskip("tomli")

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[1]
PARAMETERS = ("Licensor:", "Licensed Work:", "Additional Use Grant:", "Change Date:", "Change License:")


def project(folder):
    return tomllib.loads((folder / "pyproject.toml").read_text(encoding="utf-8"))


def test_pyproject_names_busl_and_its_license_files():
    data = project(PACKAGE)
    assert data["project"]["license"] == "BUSL-1.1"
    assert data["project"]["license-files"] == ["LICENSE", "NOTICE"]
    assert all((PACKAGE / name).is_file() for name in data["project"]["license-files"])
    # an SPDX expression in license and license-files are PEP 639, which setuptools reads from 77
    assert "setuptools>=77" in data["build-system"]["requires"]


def test_license_is_bsl_with_its_parameters():
    text = (PACKAGE / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("Business Source License 1.1\n")
    head = text.split("\nTerms\n", 1)[0]
    assert all(p in head for p in PARAMETERS)
    assert "from version 0.2.2 (every version after 0.2.1)" in head
    assert "hosted or managed service" in head and "NOTICE" in head
    assert "Change License:       Apache License, Version 2.0" in head
    assert text.rstrip().endswith("4. Not to modify this License in any other way.")   # the standard text, whole


def test_notice_gives_the_credit():
    text = (PACKAGE / "NOTICE").read_text(encoding="utf-8")
    assert "Business Source License 1.1" in text and "https://github.com/RoJLD/brain" in text
    assert "credit" in text


def test_research_graph_stays_mit():
    assert project(REPO)["project"]["license"] == {"text": "MIT"}
    assert (REPO / "LICENSE").read_text(encoding="utf-8").startswith("MIT License\n")


def test_built_metadata_names_busl_and_ships_license_and_notice(tmp_path):
    """The wheel's metadata, as setuptools writes it from a copy of the package's build inputs."""
    setuptools = pytest.importorskip("setuptools")
    if int(setuptools.__version__.split(".")[0]) < 77:
        pytest.skip(f"setuptools {setuptools.__version__} predates PEP 639")
    for name in ("pyproject.toml", "README.md", "LICENSE", "NOTICE"):
        shutil.copy(PACKAGE / name, tmp_path / name)
    (tmp_path / "src" / "brain").mkdir(parents=True)
    shutil.copy(PACKAGE / "src" / "brain" / "__init__.py", tmp_path / "src" / "brain" / "__init__.py")
    script = "import setuptools.build_meta as b; print(b.prepare_metadata_for_build_wheel('out'))"
    (tmp_path / "out").mkdir()
    r = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stderr
    info = tmp_path / "out" / r.stdout.strip().splitlines()[-1]
    headers = (info / "METADATA").read_text(encoding="utf-8").split("\n\n", 1)[0].splitlines()
    assert "License-Expression: BUSL-1.1" in headers
    assert {"License-File: LICENSE", "License-File: NOTICE"} <= set(headers)
    assert (info / "licenses" / "LICENSE").read_bytes() == (PACKAGE / "LICENSE").read_bytes()
    assert (info / "licenses" / "NOTICE").read_bytes() == (PACKAGE / "NOTICE").read_bytes()
