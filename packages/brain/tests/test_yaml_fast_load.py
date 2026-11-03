"""wi-brain-yaml-fast-load: every YAML read of the engine goes through one helper (research_graph.yamlio: libyaml and
a per-process memo), and the git answers a command asks again and again are kept."""

import re
import subprocess
from pathlib import Path

import brain
from brain import graph, paths

SRC = Path(brain.__file__).resolve().parent


def test_no_module_parses_yaml_on_its_own():
    """The pure-Python loader is never called directly (cli.py's two DDR file reads are left to the shared file's
    owner): graph.load_yaml, load_yaml_file and load_yaml_all are the only ways in."""
    bad = []
    for f in sorted(SRC.glob("*.py")):
        if f.name == "cli.py":
            continue
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\bsafe_load(_all)?\(|yaml\.load\(|CSafeLoader", line):
                bad.append(f"{f.name}:{i}: {line.strip()}")
    assert not bad, bad


def test_a_store_file_is_a_fresh_copy_each_time(tmp_path):
    f = tmp_path / "work.yaml"
    f.write_text("- {id: wi-a, status: todo}\n", encoding="utf-8")
    one = graph.load_yaml_list(f)
    one[0]["status"] = "changed"
    assert graph.load_yaml_list(f) == [{"id": "wi-a", "status": "todo"}]
    assert graph.load_yaml_all("a: 1\n---\nb: 2\n") == [{"a": 1}, {"b": 2}]


def test_the_main_checkout_is_asked_once(git_repo, tmp_path, monkeypatch):
    calls = []
    real = subprocess.run

    def spy(cmd, *a, **kw):
        calls.append(cmd)
        return real(cmd, *a, **kw)

    monkeypatch.setattr(paths.subprocess, "run", spy)
    sub = git_repo / "notes"
    assert paths.main_checkout(sub) == paths.main_checkout(sub) == git_repo.resolve()
    assert len(calls) == 1
    plain = tmp_path / "not-yet-a-repo"
    plain.mkdir()
    assert paths.main_checkout(plain) is None
    subprocess.run(["git", "init", "-q", str(plain)], check=True)
    assert paths.main_checkout(plain) == plain.resolve()   # None was not kept
