"""brain gate: the pre-push checks in one call. Each step passes, fails (its own reason and next command) or is
skipped (it does not apply, or --skip); the gate exits 0 only when no step failed, whichever step it is (every path
through the door refused alike), writes each step's log and verdict.json, and says three lines. git runs for real on
a local repository with a local bare origin; the steps' brain commands go through a faked runner."""

import json
import re
import shutil
from pathlib import Path

import pytest
from brain import cli, gate, review, ship, verdict
from conftest import NO_LOCKS, git_init, run_git

STAMPED = {"findings": 2, "fixed": 2, "contested": 0}
_TEMPLATE: dict[str, tuple[Path, str]] = {}


@pytest.fixture(scope="module")
def _template(tmp_path_factory):
    """A clone of a local bare origin, on a branch with one commit past origin/main: made once per module, copied by
    each test (git costs seconds a call on a loaded Windows machine)."""
    root = tmp_path_factory.mktemp("gate-template")
    origin = git_init(root / "origin.git", bare=True)
    work = git_init(root / "work")
    (work / "a.py").write_text("A = 1\n", encoding="utf-8")
    run_git(work, "add", "-A")
    run_git(work, "commit", "-q", "-m", "init")
    run_git(work, "remote", "add", "origin", str(origin))
    run_git(work, "push", "-q", "origin", "main")
    run_git(work, "fetch", "-q", "origin")
    run_git(work, "switch", "-q", "-c", "feat")
    (work / "a.py").write_text("A = 2\n", encoding="utf-8")
    run_git(work, "commit", "-q", "-am", "change")
    return work, run_git(work, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(_template, tmp_path, monkeypatch):
    """The template's copy; the runs' logs under the test's own temporary folder."""
    monkeypatch.setattr(verdict.tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()
    work = Path(shutil.copytree(_template[0], tmp_path / "work", ignore=NO_LOCKS))
    _TEMPLATE[str(work)] = (work, _template[1])
    return work


def head(repo: Path) -> str:
    return _TEMPLATE[str(repo)][1] if str(repo) in _TEMPLATE else run_git(repo, "rev-parse", "HEAD").strip()


class Fake:
    """The runner: every brain step green unless a rule (a pattern on the command line) answers otherwise."""

    def __init__(self, rules=None):
        self.rules = dict(rules or {})
        self.calls: list[str] = []
        self.exes: set[str] = set()   # the interpreters that ran the brain steps

    def __call__(self, cmd, cwd=None, timeout=0, env=None):
        line = " ".join(str(c) for c in cmd[1:])
        self.calls.append(line)
        self.exes.add(str(cmd[0]))
        for pattern, answer in self.rules.items():
            if re.search(pattern, line):
                return answer(cmd, cwd) if callable(answer) else answer
        if "merge-check" in line:
            return ship.Result(0, json.dumps({"base": "origin/main", "base_sha": "c" * 40, "behind": False,
                                              "lost": [], "lost_ids": []}))
        if "audit --diff" in line:
            return ship.Result(0, "== scout\nscout: 0 to fix in this PR (0 NEW, 0 LEFT), 0 deferred\n")
        if " test --changed" in line:
            return ship.Result(0, "brain test: tests/test_a.py\n3 passed in 0.5s\n")
        return ship.Result(0, "", "")


def make(repo, fake=None, public=(False, ""), stamp_valid=False, **kw):
    return gate.Gate(repo, runner=fake or Fake(), is_public=lambda top: public,
                     stamp_valid=lambda slug, sha: stamp_valid, **kw)


def stamp(repo, **counts):
    c = {**STAMPED, **counts}
    review.stamp(head(repo), c["findings"], c["fixed"], c["contested"])


def by_name(report) -> dict:
    return {s.name: s for s in report.steps}


def test_every_step_green_passes_with_three_lines_and_the_logs(repo):
    stamp(repo)
    g = make(repo)
    r = g.run()
    assert r.ok and [s.name for s in r.steps] == list(gate.STEPS)
    steps = by_name(r)
    assert steps["views"].ok is None and steps["views"].detail == "no graph store"
    assert steps["public"].ok is None and steps["public"].detail == "not a public repo"
    assert all(steps[n].ok for n in ("clean", "merge-check", "review", "audit", "tests"))
    lines = r.lines()
    assert len(lines) == 3
    assert lines[0].startswith("gate: PASSED 5/5 (clean, merge-check, review, audit, tests); skipped: views (no "
                               "graph store), public (not a public repo); logs: ")
    assert lines[1] == "failed: none" and lines[2].startswith("next: git push")
    logs = sorted(p.name for p in g.folder.iterdir())
    assert logs == ["1-clean.log", "2-merge-check.log", "3-review.log", "4-audit.log", "5-tests.log", "verdict.json"]
    assert json.loads((g.folder / "verdict.json").read_text(encoding="utf-8"))["ok"] is True
    assert "exit: 0" in (g.folder / "4-audit.log").read_text(encoding="utf-8")
    assert g.folder.parent == verdict.scratch_root("gate")


def _dirty(repo, fake):
    (repo / "a.py").write_text("A = 3\n", encoding="utf-8")


def _untracked(repo, fake):
    (repo / "new_module.py").write_text("B = 1\n", encoding="utf-8")


def _behind(repo, fake):
    fake.rules["merge-check"] = ship.Result(1, json.dumps({"base": "origin/main", "base_sha": "c" * 40,
                                                           "behind": True, "lost": [], "lost_ids": []}))


def _lost(repo, fake):
    fake.rules["merge-check"] = ship.Result(1, json.dumps({"base": "origin/main", "base_sha": "c" * 40,
                                                           "behind": False, "lost": [{"path": "CHANGELOG.md"}],
                                                           "lost_ids": []}))


def _garbage(repo, fake):
    fake.rules["merge-check"] = ship.Result(2, "", "brain merge-check: not a git repo")


def _no_stamp(repo, fake):
    review.stamp_file(head(repo)).unlink()


def _open(repo, fake):
    stamp(repo, findings=3, fixed=1)


def _audit(repo, fake):
    fake.rules["audit --diff"] = ship.Result(1, "NEW P1 feature.links x.py\nscout: 1 to fix in this PR (1 NEW, 0 "
                                                "LEFT), 0 deferred\n")


def _tests(repo, fake):
    fake.rules[" test --changed"] = ship.Result(1, "FAILED tests/test_a.py::test_one - assert 1 == 2\n"
                                                   "1 failed, 2 passed in 0.4s\n")


FAILURES = {
    "clean": (_dirty, "file(s) changed or untracked", "git add -A"),
    "clean-untracked": (_untracked, "new_module.py", "git add -A"),
    "merge-check": (_behind, "behind origin/main", "git merge origin/main"),
    "merge-check-lost": (_lost, "1 line(s), node change(s) or id(s) of origin/main lost", "brain merge-check"),
    "merge-check-garbage": (_garbage, "not a git repo", "brain merge-check"),
    "review": (_no_stamp, "no review stamp for HEAD", "brain review stamp"),
    "review-open": (_open, "2 finding(s) left open", "brain review stamp HEAD"),
    "audit": (_audit, "scout: 1 to fix in this PR (1 NEW, 0 LEFT)", "brain audit --diff origin/main"),
    "tests": (_tests, "1 failed, 2 passed: tests/test_a.py::test_one", "python -m pytest tests/test_a.py::test_one"),
}


@pytest.mark.parametrize("case", sorted(FAILURES))
def test_any_step_that_fails_fails_the_gate_with_its_reason_and_next_command(repo, case):
    """The door's every path: whichever step fails, the gate fails, the others still run, the verdict names it."""
    stamp(repo)
    fake = Fake()
    setup, why, nxt = FAILURES[case]
    setup(repo, fake)
    r = make(repo, fake).run()
    name = "merge-check" if case.startswith("merge-check") else case.split("-")[0]
    failed = [s for s in r.steps if s.ok is False]
    assert not r.ok and [s.name for s in failed] == [name]
    assert len(r.steps) == len(gate.STEPS)   # the others ran
    lines = r.lines()
    assert lines[0].startswith("gate: FAILED 4/5") and why in lines[1] and lines[1].startswith(f"failed: {name}: ")
    assert lines[2].startswith("next: ") and nxt in lines[2]
    assert Path(failed[0].log).is_file()


def test_views_regenerated_and_checked_in_a_graph_repo_and_a_rewritten_view_fails(repo):
    (repo / gate.GRAPH).parent.mkdir(parents=True)
    (repo / gate.GRAPH).write_text("v: 1\n", encoding="utf-8")
    (repo / "notes" / "kanban.md").write_text("old\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "store")
    _TEMPLATE.pop(str(repo))   # a new HEAD
    stamp(repo)
    fake = Fake()
    r = make(repo, fake).run()
    assert by_name(r)["views"].ok and any("refresh --offline" in c and str(repo) in c for c in fake.calls)

    def rewrite(cmd, cwd):
        (repo / "notes" / "kanban.md").write_text("new\n", encoding="utf-8")
        return ship.Result(0)
    r = make(repo, Fake({"refresh": rewrite})).run()
    v = by_name(r)["views"]
    assert not r.ok and v.ok is False and "refresh rewrote 1 file(s) (notes/kanban.md)" in v.detail
    run_git(repo, "checkout", "--", "notes/kanban.md")
    r = make(repo, Fake({"refresh": ship.Result(1, "", "check: 1 project(s) failed")})).run()
    assert by_name(r)["views"].detail == "brain refresh: check: 1 project(s) failed"


def test_public_repo_runs_the_public_check_unless_the_head_is_stamped(repo):
    stamp(repo)
    fake = Fake()
    r = make(repo, fake, public=(True, "o/r"), stamp_valid=True).run()
    assert by_name(r)["public"].ok and not any("--public" in c for c in fake.calls)
    r = make(repo, fake, public=(True, "o/r")).run()
    assert by_name(r)["public"].ok and any("check --public --history" in c for c in fake.calls)
    r = make(repo, Fake({"--public": ship.Result(1, "private term: x.py:3\n1 finding(s)\n")}),
             public=(True, "o/r")).run()
    p = by_name(r)["public"]
    assert not r.ok and p.ok is False and p.detail == "brain check --public: 1 finding(s)"


def test_skip_and_fail_fast(repo):
    fake = Fake()
    r = make(repo, fake, skip=("tests", "audit")).run()   # no stamp: review fails
    steps = by_name(r)
    assert steps["tests"].ok is None and steps["tests"].detail == "--skip" and not any("test --changed" in c
                                                                                       for c in fake.calls)
    assert "tests (--skip)" in r.lines()[0] and not r.ok
    r = make(repo, Fake(), fail_fast=True).run()
    assert [s.name for s in r.steps] == ["clean", "merge-check", "review"]
    with pytest.raises(gate.GateError, match="--skip nope: not a step"):
        make(repo, skip=("nope",))


def test_a_check_skipped_on_purpose_is_no_pass(repo):
    """--skip never turns the gate green: nothing failed, yet INCOMPLETE and not ok (exit 1)."""
    stamp(repo)
    r = make(repo, skip=("tests",)).run()
    lines = r.lines()
    assert not r.ok and r.skipped_on_purpose == ["tests"] and not [s for s in r.steps if s.ok is False]
    assert lines[0].startswith("gate: INCOMPLETE 4/4") and lines[1] == "failed: none"
    assert lines[2] == "next: brain gate without --skip (tests) before the push"
    assert make(repo).run().ok   # the steps that do not apply (views, public) are no skip on purpose


def test_the_brain_steps_run_with_this_engine_and_the_tests_with_python(repo):
    import sys
    stamp(repo)
    fake = Fake()
    make(repo, fake, python="other-python").run()
    assert fake.exes == {sys.executable}
    assert [c for c in fake.calls if " test --changed" in c][0].endswith("--python other-python")


def test_a_base_that_is_no_commit_cannot_start(repo, capsys):
    with pytest.raises(gate.GateError, match="--base origin/nope: not a commit of this checkout"):
        make(repo, base="origin/nope")
    assert cli.main(["gate", "--repo-dir", str(repo), "--base", "origin/nope"]) == 2
    assert "not a commit" in capsys.readouterr().err


def test_a_widened_selection_that_ran_nothing_says_so(repo):
    stamp(repo)
    nothing = ship.Result(0, "", "brain test: no test module to run\nbrain test: shadow mode: the whole suite is the "
                                 "answer; the CI runs it before the merge\n")
    t = by_name(make(repo, Fake({" test --changed": nothing})).run())["tests"]
    assert t.ok and t.detail == "no test module selected; widened: the CI runs the whole suite"


def test_a_step_that_raises_fails_alone(repo, monkeypatch):
    stamp(repo)
    monkeypatch.setattr(gate.Gate, "audit", lambda self: (_ for _ in ()).throw(OSError("disk gone")))
    r = make(repo).run()
    a = by_name(r)["audit"]
    assert not r.ok and a.ok is False and a.detail == "could not run: disk gone" and by_name(r)["tests"].ok
    assert "--skip" not in a.next and a.next.startswith("run the audit step's command by hand")


def test_the_command_exit_codes_and_outputs(repo, monkeypatch, capsys):
    stamp(repo)
    monkeypatch.setattr(gate, "_default_runner", lambda: Fake())
    monkeypatch.setattr(gate, "_is_public", lambda top: (False, ""))
    assert cli.main(["gate", "--repo-dir", str(repo)]) == 0
    out = capsys.readouterr()
    assert len(out.out.strip().splitlines()) == 3 and "brain gate: clean: ok" in out.err
    assert cli.main(["gate", "--repo-dir", str(repo), "--json", "--logs", str(repo.parent / "logs")]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] and data["head"] == head(repo) and data["logs"] == (repo.parent / "logs").as_posix()
    _untracked(repo, None)
    assert cli.main(["gate", "--repo-dir", str(repo), "--skip", "tests"]) == 1
    assert capsys.readouterr().out.splitlines()[1].startswith("failed: clean: ")
    assert cli.main(["gate", "--repo-dir", str(repo.parent)]) == 2   # not a git repo
    assert "brain gate:" in capsys.readouterr().err


def test_verdict_reads_pytest_and_keeps_the_newest_runs(tmp_path):
    s = verdict.pytest_summary("x\nFAILED t/a.py::b - boom\nERROR t/c.py::d\nFAILED t/a.py::b\n"
                               "== 1 failed, 4 passed, 1 error in 2.0s ==\n== 2 passed in 1s ==\n")
    assert s.failed == ["t/a.py::b", "t/c.py::d"] and s.counts == {"failed": 1, "passed": 6, "error": 1}
    assert not verdict.pytest_summary("nothing here").found
    for _ in range(verdict.KEEP + 3):
        verdict.run_folder("gate", "x", root=tmp_path)
    assert len(list(tmp_path.iterdir())) == verdict.KEEP
    assert verdict.last_line("", "a\n\nlast one\n") == "last one" and len(verdict.last_line("x" * 500)) == \
        verdict.DETAIL
