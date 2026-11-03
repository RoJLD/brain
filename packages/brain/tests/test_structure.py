"""brain audit --diff's structure signals (brain.structure, wi-brain-audit-structure: EXT-4, EXT-5), each on a fixture
repo through the scout, with the project's thresholds from projects.yaml."""

import json

import pytest

from brain import cli, projects, structure

from conftest import run_git
from test_audit import FIND, README

STRUCTURE = {"size.cross", "size.grow", "complexity.cross", "complexity.grow", "dep.adr", "shortcut.marker",
             "symptom.cause"}
CORE = "def go():\n    pass\n"
WIDE = "def wide(a, b, c, d, e, f):\n" + "".join(f"    if {x}:\n        return {i}\n"
                                                 for i, x in enumerate("abcdef")) + "    return 9\n"   # complexity 7
LAB = {"README.md": README, "pyproject.toml": '[project]\nname = "lab"\ndependencies = ["pyyaml>=6"]\n\n'
                                              '[project.scripts]\nlab = "lab.cli:main"\n' + FIND,
       "src/lab/__init__.py": "", "src/lab/cli.py": "from lab import core\n\ndef main():\n    core.go()\n",
       "src/lab/core.py": CORE, "src/lab/wide.py": WIDE,
       "tests/test_cli.py": "from lab.cli import main\n", "tests/test_core.py": "from lab.core import go\n",
       "tests/test_wide.py": "from lab.wide import wide\n",
       "notes/decisions.md": "# Decisions\n\n## 2026-10-01 — pyyaml and httpx\n\nWe read YAML with pyyaml.\n"}


def _setup(make_repo, tmp_path, monkeypatch, files=None, audit="{max_lines: 40, complexity: 5}"):
    lab = make_repo("lab", files or LAB)
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"demo: {{root: {lab.as_posix()}, production: [.], audit: {audit}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    run_git(lab, "checkout", "-q", "-b", "feature")
    return lab


def _write(repo, rel, text):
    f = repo / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8", newline="\n")


def _signals(capsys, repo, *args):
    rc = cli.main(["audit", "--diff", *args, "--repo-dir", str(repo), "--json"])
    data = json.loads(capsys.readouterr().out)
    return rc, {(f["check"], f["unit"]): f["tag"] for f in data["findings"] if f["check"] in STRUCTURE}, data


def test_a_file_past_max_lines_is_new_and_a_big_file_that_grows_is_deferred(make_repo, tmp_path, monkeypatch,
                                                                            capsys):
    big = "".join(f"X{i} = {i}\n" for i in range(50))
    lab = _setup(make_repo, tmp_path, monkeypatch, {**LAB, "src/lab/big.py": big,
                                                     "tests/test_big.py": "from lab.big import X1\n"})
    _write(lab, "src/lab/core.py", CORE + "".join(f"Y{i} = {i}\n" for i in range(40)))
    _write(lab, "src/lab/big.py", big + "X50 = 50\n")
    _write(lab, "docs/long.md", "line\n" * 60)   # a doc is not code: never sized
    rc, tags, data = _signals(capsys, lab)
    assert tags == {("size.cross", "src/lab/core.py"): "NEW", ("size.grow", "src/lab/big.py"): "DEFER"}
    assert rc == 1 and data["structure"] == {"max_lines": 40, "complexity": 5}
    assert data["item"] == "wi-debt-lab" and data["deferred"] == 1
    body = tmp_path / "body.md"
    body.write_text("Splits nothing yet.\n\nJustified: src/lab/core.py: a table of constants, read as one block\n",
                    encoding="utf-8")
    rc, tags, data = _signals(capsys, lab, "--pr-body", str(body))
    assert rc == 0 and tags[("size.cross", "src/lab/core.py")] == "justified" and data["justified"] == 1
    assert cli.main(["audit", "--diff", "--repo-dir", str(lab), "--pr-body", str(body)]) == 0
    out = capsys.readouterr().out
    assert "DEFER  P2 size.grow        src/lab/big.py: 50 -> 51 lines, already past 40 -> wi-debt-lab" in out
    assert out.rstrip().endswith("1 deferred, 1 justified; then brain audit --diff again")


def test_complexity_past_the_threshold_new_growth_past_it_deferred_a_moved_function_neither(make_repo, tmp_path,
                                                                                           monkeypatch, capsys):
    lab = _setup(make_repo, tmp_path, monkeypatch)
    _write(lab, "src/lab/core.py", "def go(a, b, c):\n" + "".join(f"    if {x}:\n        return 1\n"
                                                              for x in "abc") + "    return a and b and c\n")
    _write(lab, "src/lab/wide.py", WIDE.replace("    return 9\n", "    return 9 if a else 8\n"))
    rc, tags, _ = _signals(capsys, lab)
    assert rc == 1 and tags == {("complexity.cross", "src/lab/core.py::go"): "NEW",
                                ("complexity.grow", "src/lab/wide.py::wide"): "DEFER"}
    run_git(lab, "checkout", "-q", "--", ".")
    _write(lab, "src/lab/wide.py", "")
    _write(lab, "src/lab/cli.py", "from lab import core\n\ndef main():\n    core.go()\n\n\n" + WIDE)
    rc, tags, _ = _signals(capsys, lab)
    assert tags == {}   # moved to cli.py with its complexity: nothing new


def test_a_new_dependency_needs_a_decision_log_line(make_repo, tmp_path, monkeypatch, capsys):
    lab = _setup(make_repo, tmp_path, monkeypatch)
    _write(lab, "pyproject.toml", LAB["pyproject.toml"].replace('["pyyaml>=6"]', '["pyyaml>=6", "Requests>=2", '
                                                                                '"httpx"]'))
    rc, tags, data = _signals(capsys, lab)
    assert rc == 1 and tags == {("dep.adr", "requests"): "NEW"}   # httpx: the project's log names it
    assert "a new dependency in pyproject.toml" in next(f["why"] for f in data["findings"] if f["check"] == "dep.adr")
    _write(lab, "notes/decisions.md", LAB["notes/decisions.md"] + "\n## 2026-10-02 — requests for the API\n")
    rc, tags, _ = _signals(capsys, lab)
    assert rc == 0 and tags == {}   # the change's own ADR names it


def test_a_shortcut_marker_needs_its_ceiling_trigger_and_debt_item(make_repo, tmp_path, monkeypatch, capsys):
    lab = _setup(make_repo, tmp_path, monkeypatch)
    _write(lab, "src/lab/core.py", "def go():\n    # shortcut: the whole file in memory\n    pass\n")
    _write(lab, "src/lab/cli.py", "from lab import core\n\n# shortcut: one pass over the rows; ceiling: 10k rows;\n"
                                  "# trigger: a file past it; wi-lab-stream\ndef main():\n    core.go()\n")
    _write(lab, "tests/test_core.py", 'from lab.core import go\n\nNOTE = "# shortcut: a string, not a marker"\n')
    rc, tags, data = _signals(capsys, lab)
    assert rc == 1 and tags == {("shortcut.marker", "src/lab/core.py"): "NEW"}
    why = next(f["why"] for f in data["findings"] if f["check"] == "shortcut.marker")
    assert why == "a shortcut: marker without a ceiling, a trigger, a debt item"


@pytest.mark.parametrize("rel,before,after,kind", [
    ("src/lab/core.py", CORE, "def go():\n    import os  # noqa: F401\n", "a noqa"),
    ("src/lab/core.py", CORE, "def go() -> int:\n    return 'x'  # type: ignore[return-value]\n", "a type: ignore"),
    ("tests/test_core.py", "from lab.core import go\n",
     "import pytest\nfrom lab.core import go\n\n"
     "@pytest.mark.skip(reason='flaky')\ndef test_go():\n    go()\n",
     "a skipped test"),
    ("src/lab/core.py", CORE, "def go():\n    try:\n        pass\n    except Exception:\n        pass\n",
     "an except that swallows everything"),
    ("src/lab/core.py", CORE, "import time\n\ndef go():\n    time.sleep(1)\n", "a sleep"),
    ("src/lab/core.py", CORE, "def go():\n    for attempt in range(3):\n        pass\n", "a retry"),
    ("src/lab/core.py", "TIMEOUT_S = 10\n\ndef go():\n    pass\n", "TIMEOUT_S = 30\n\ndef go():\n    pass\n",
     "a longer timeout"),
    ("scripts/run.sh", "curl --max-time 5 x\n", "sleep 5\ncurl --max-time 5 x\n", "a sleep"),
])
def test_each_symptom_fix_needs_a_root_cause_line(make_repo, tmp_path, monkeypatch, capsys, rel, before, after,
                                                  kind):
    lab = _setup(make_repo, tmp_path, monkeypatch, {**LAB, rel: before})
    _write(lab, rel, after)
    rc, tags, data = _signals(capsys, lab)
    assert tags[("symptom.cause", rel)] == "NEW" and rc == 1
    assert next(f["why"] for f in data["findings"] if f["check"] == "symptom.cause") == f"{kind} added"
    run_git(lab, "add", "-A")
    run_git(lab, "commit", "-q", "-m", "Fix the flaky run\n\nRoot cause: the server answers after its warm-up.")
    rc, tags, _ = _signals(capsys, lab)
    assert tags[("symptom.cause", rel)] == "justified"


def test_no_symptom_from_text_that_only_looks_like_one(make_repo, tmp_path, monkeypatch, capsys):
    lab = _setup(make_repo, tmp_path, monkeypatch)
    _write(lab, "src/lab/core.py", 'HELP = "add # noqa or time.sleep(1)"\n\ndef go():\n    pass\n')
    _write(lab, "docs/guide.md", "Never add `# type: ignore` or a sleep 5 to make it pass.\n")
    _write(lab, "src/lab/cli.py", "from lab import core\n\ndef main():\n    try:\n        core.go()\n"
                                  "    except ValueError:\n        pass\n    except Exception as exc:\n"
                                  "        print(exc)\n        raise\n")
    _write(lab, "tests/test_core.py", "import shutil\nimport sys\n\nimport pytest\nfrom lab.core import go\n\n"
                                      "@pytest.mark.skipif(sys.platform == 'win32', reason='no fork')\n"
                                      "def test_go():\n    if not shutil.which('git'):\n"
                                      "        pytest.skip('git not available')\n    go()\n")
    rc, tags, _ = _signals(capsys, lab)
    assert tags == {}   # a string, a doc, a narrow except, a broad one that re-raises, guards


def test_complexity_counts_the_decision_points():
    text = ("def f(a, b):\n    if a and b or a:\n        return [x for x in a if x]\n    while b:\n        b -= 1\n"
            "    try:\n        pass\n    except ValueError:\n        pass\n    return 1 if a else 2\n\n"
            "class K:\n    def m(self):\n        def inner():\n            if self:\n                pass\n"
            "        return inner\n")
    assert structure.complexities(text) == {"f": 9, "K.m": 1, "K.m.inner": 2}
    assert structure.complexities("def broken(:\n") == {}


def test_manifests_and_thresholds():
    assert structure.dependencies("requirements-dev.txt", "# x\nRequests[socks]>=2\n-e .\npy_yaml==6\n") == {
        "requests", "py-yaml"}
    assert structure.dependencies("web/package.json", '{"dependencies": {"React": "18"}, "devDependencies": '
                                                      '{"vite": "5"}}') == {"react", "vite"}
    assert structure.dependencies("pyproject.toml", '[tool.poetry.dependencies]\npython = "^3.10"\nrich = "*"\n'
                                                    '[tool.poetry.group.dev.dependencies]\npytest = "*"\n'
                                                    '[dependency-groups]\nlint = ["ruff"]\n') == {
        "rich", "pytest", "ruff"}
    assert structure.dependencies("setup.cfg", "install_requires = x") == set()
    assert structure.thresholds(None) == {"max_lines": 1000, "complexity": 15}
    assert structure.thresholds({"spec": "s", "complexity": 20}) == {"max_lines": 1000, "complexity": 20}


def test_the_registry_checks_the_thresholds(tmp_path):
    root = tmp_path / "p"
    root.mkdir()
    p = projects.Project("p", root, audit={"max_lines": 0})
    with pytest.raises(projects.RepoError, match="audit max_lines is a whole number"):
        projects.repos_of(p)
    p = projects.Project("p", root, audit={"complexity": 12, "spec": "s"})
    assert projects.repos_of(p)[0].path == root
