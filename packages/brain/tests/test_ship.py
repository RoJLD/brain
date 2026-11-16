"""brain ship: a local merge queue. The queue file (idempotent, per repo, any title kept and
escaped), the merger's lock (one winner, a stale lock broken, released on an exception, never on a network share),
the merger (the merge gate's every block refuses, the catch-up, the checks, the batch's full suite and its
bisection), and every external system down, slow or answering garbage. gh, git and pytest are faked through the
runner; the one test that runs git for real uses a local bare origin, never a real remote."""

import json
import os
import re
import shlex
from pathlib import Path

import pytest
from brain import cli, filelock, mergeready, review, ship
from conftest import git_init, run_git

HEAD = "a" * 40
ROOT = Path(__file__).resolve().parents[1]   # packages/brain


def _sha(n: int) -> str:
    return f"{n:040x}"


class Fake:
    """The runner: records each call and answers by the first rule whose pattern the command line matches."""

    def __init__(self, tmp: Path, rules=None):
        self.calls: list[list[str]] = []
        self.tmp = tmp
        self.rules = list(rules or [])
        self.at: dict[str, str] = {}   # scratch worktree -> the commit it was added at

    def __call__(self, cmd, cwd=None, timeout=0, env=None):
        cmd = [str(c) for c in cmd]
        self.calls.append(cmd)
        line = " ".join(Path(cmd[0]).stem if i == 0 else c for i, c in enumerate(cmd))
        if "worktree add" in line:
            scratch, commit = cmd[-2], cmd[-1]
            Path(scratch).mkdir(parents=True, exist_ok=True)
            self.at[str(Path(scratch))] = commit
        if "worktree remove" in line:
            import shutil
            shutil.rmtree(cmd[-1], ignore_errors=True)
        for pattern, answer in self.rules:
            if re.search(pattern, line):
                return answer(cmd, cwd) if callable(answer) else answer
        return ship.Result(0, "", "")

    def ran(self, pattern: str) -> list[str]:
        return [" ".join(c) for c in self.calls if re.search(pattern, " ".join(c))]


def _gate(blocks=(), head=HEAD, base="main", raises=None):
    """A gate that reads the PR through the merger's view (gh through the runner), then answers ``blocks``."""
    def gate(top, pr, slug, remote, view):
        view(pr, slug, top)
        if raises:
            raise raises
        g = mergeready.Gate(int(pr), slug, head, base)
        for c in ("open", "fresh", "merge-check", "ci", "review", "public", "body", "pins"):
            g.add(c, c not in blocks, f"{c} detail")
        return g
    return gate


def _pr_json(pr=7, branch="feat", title="Adds a line"):
    return ship.Result(0, json.dumps({"number": pr, "state": "OPEN", "headRefName": branch, "title": title,
                                      "url": f"https://github.com/acme/lab/pull/{pr}"}))


def _queue(tmp_path, *prs, repo="acme/lab"):
    d = tmp_path / repo.replace("/", "-")
    d.mkdir(exist_ok=True)
    for pr in prs:
        ship.enqueue(repo, pr, str(d), "origin", f"PR {pr}", f"feat-{pr}")
    return d


def _suite(top, python):
    return [(top, ["pytest-suite", str(top)])]


def _merger(fake, gate=None, batch=5, suite=_suite):
    return ship.Merger(fake, gate or _gate(), suite, batch, say=lambda line: None)


def _base_after(n_holder: list):
    """rev-parse of origin/main: a new tip after each merge (the merges move main)."""
    def answer(cmd, cwd):
        return ship.Result(0, _sha(n_holder[0]) + "\n")
    return answer


# --- the queue file ---------------------------------------------------------------------------------------------


def test_queuing_twice_keeps_one_entry_and_says_its_place_per_repo(tmp_path):
    d = _queue(tmp_path, 3, 4)
    e, added, place = ship.enqueue("acme/lab", 4, str(d), title="again")
    assert not added and place == (2, 2) and e["title"] == "again"
    ship.enqueue("acme/web", 4, str(d))   # the same number in another repo: its own entry, its own count
    assert [(r["repo"], r["pr"]) for r in ship.entries()] == [("acme/lab", 3), ("acme/lab", 4), ("acme/web", 4)]
    assert ship.place(ship.entries(), "acme/web", 4) == (1, 1)
    ship.update("acme/lab", 3, status="failed", reason="tests")
    e, added, place = ship.enqueue("ACME/lab", 3, str(d))   # a failed PR goes back to queued, at its old place
    assert added and e["status"] == "queued" and e["reason"] == "" and len(ship.entries("acme/lab")) == 2


def test_a_title_with_newlines_quotes_percent_and_dollar_round_trips_and_the_table_escapes_it(tmp_path):
    title = 'Fix "x" | 100% of $HOME\nsecond line `code` <b>'
    ship.enqueue("acme/lab", 9, str(tmp_path), title=title)
    raw = ship.queue_path().read_text(encoding="utf-8")
    assert json.loads(raw)["entries"][0]["title"] == title and "\n" not in json.dumps(title)
    rows = ship.table(ship.entries())
    assert len(rows) == 3   # one line per entry: the newline did not break the table
    row = rows[2]
    assert "\\|" in row and "\\`code\\`" in row and "&lt;b&gt;" in row and "100% of $HOME second line" in row
    assert row.count(" | ") == 6   # its own pipe escaped: the columns hold


def test_an_unreadable_queue_reads_empty_and_the_next_write_sets_it_aside(tmp_path):
    ship.queue_path().parent.mkdir(parents=True)
    ship.queue_path().write_text("{not json", encoding="utf-8")
    assert ship.entries() == []
    ship.enqueue("acme/lab", 1, str(tmp_path))
    assert [e["pr"] for e in ship.entries()] == [1]
    assert any(".unreadable-" in p.name for p in ship.queue_path().parent.iterdir())


def _locate_rules(tmp_path, remote_url="https://github.com/acme/lab.git"):
    git_dir = tmp_path / "lab" / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    return [(r"git-common-dir", ship.Result(0, str(git_dir) + "\n")),
            (r"remote get-url", ship.Result(0, remote_url + "\n"))]


def test_queue_pr_reads_the_title_and_queues_the_main_checkout(tmp_path):
    fake = Fake(tmp_path, [*_locate_rules(tmp_path), (r"^gh pr view", _pr_json(12, "feat-x", "Adds 50% more $"))])
    e, added, place, warnings = ship.queue_pr("12", tmp_path / "lab" / "wt", runner=fake)
    assert added and place == (1, 1) and not warnings
    assert (e["repo"], e["pr"], e["branch"], e["title"]) == ("acme/lab", 12, "feat-x", "Adds 50% more $")
    assert Path(e["dir"]) == tmp_path / "lab"   # the main checkout, not the session's worktree


@pytest.mark.parametrize("answer", [ship.Result(127, "", "gh: not found"), ship.Result(124, "", "gh: no answer in 120 s"),
                                    ship.Result(0, "<html>rate limited</html>"), ship.Result(0, "[1, 2]")],
                         ids=["down", "slow", "garbage", "not-an-object"])
def test_gh_down_slow_or_garbage_still_queues_the_pr_with_a_warning(tmp_path, answer):
    fake = Fake(tmp_path, [*_locate_rules(tmp_path), (r"^gh pr view", answer)])
    e, added, _, warnings = ship.queue_pr("https://github.com/acme/lab/pull/5", tmp_path, runner=fake)
    assert added and e["repo"] == "acme/lab" and e["pr"] == 5 and e["title"] == ""
    assert len(warnings) == 1 and "gh pr view 5" in warnings[0]


def test_a_closed_pr_a_bad_number_and_an_unknown_repo_are_refused(tmp_path):
    closed = ship.Result(0, json.dumps({"number": 5, "state": "MERGED", "title": "t", "headRefName": "f"}))
    fake = Fake(tmp_path, [*_locate_rules(tmp_path), (r"^gh pr view", closed)])
    with pytest.raises(ship.ShipError, match="merged"):
        ship.queue_pr("5", tmp_path, runner=fake)
    with pytest.raises(ship.ShipError, match="not a PR"):
        ship.queue_pr("five", tmp_path, runner=fake)
    fake = Fake(tmp_path, [*_locate_rules(tmp_path, "https://gitlab.example/x.git"),
                           (r"^gh pr view", ship.Result(1, "", "no"))])
    with pytest.raises(ship.ShipError, match="--slug"):
        ship.queue_pr("5", tmp_path, runner=fake)
    fake = Fake(tmp_path, [(r"git-common-dir", ship.Result(128, "", "fatal: not a git repository"))])
    with pytest.raises(ship.ShipError, match="not in a git checkout"):
        ship.queue_pr("5", tmp_path, runner=fake)
    assert ship.entries() == []


# --- the merger -------------------------------------------------------------------------------------------------


def _ok_rules(tip=None, pr_view=None):
    tip = tip if tip is not None else [1]
    return [(r"^gh pr view", pr_view or _pr_json()),
            (r"rev-parse --verify origin/main", _base_after(tip)),
            (r"rev-parse --verify HEAD", ship.Result(0, "b" * 40 + "\n"))]


def test_an_up_to_date_pr_is_checked_and_merged_at_the_head_the_gate_saw(tmp_path):
    _queue(tmp_path, 7)
    fake = Fake(tmp_path, _ok_rules())
    rep = _merger(fake).run()
    assert rep.ok and [d["status"] for d in rep.done] == ["merged"]
    assert fake.ran("merge-base --is-ancestor origin/main HEAD") and not fake.ran(r"\bpush\b")
    assert fake.ran(f"pr merge 7 --repo acme/lab --merge --match-head-commit {HEAD}")
    assert fake.ran(r"-m brain test --changed origin/main --repo-dir") and not fake.ran("merge-check")
    assert rep.suites and rep.suites[0]["prs"] == [7] and rep.suites[0]["result"] == "pass"   # the partial batch
    e = ship.entries()[0]
    assert e["status"] == "merged" and e["head"] == HEAD and e["merged"] == _sha(1)
    assert not any(Path(p).exists() for p in fake.at)   # the scratch worktrees removed


def test_a_pr_behind_main_is_caught_up_checked_pushed_and_merged_at_the_new_head(tmp_path):
    _queue(tmp_path, 7)
    fake = Fake(tmp_path, [(r"merge-base --is-ancestor", ship.Result(1)), *_ok_rules()])
    rep = _merger(fake).run()
    assert rep.ok, rep.done
    order = [c for c in (" ".join(x) for x in fake.calls)
             if re.search(r"merge --no-ff|commit --no-edit|merge-check|test --changed|push|pr merge", c)]
    assert [re.search(r"merge --no-ff|commit|merge-check|test --changed|push|pr merge", c).group(0)
            for c in order] == ["merge --no-ff", "commit", "merge-check", "test --changed", "push", "pr merge"]
    assert fake.ran("push origin HEAD:refs/heads/feat$") and fake.ran(f"--match-head-commit {'b' * 40}")


def test_a_graph_store_gets_its_views_regenerated_once_after_the_catch_up(tmp_path):
    _queue(tmp_path, 7)

    def add(cmd, cwd):
        Path(cmd[-2], "notes", "graph").mkdir(parents=True)
        Path(cmd[-2], "notes", "graph", "schema.yaml").write_text("x: 1\n", encoding="utf-8")
        return ship.Result(0)
    fake = Fake(tmp_path, [(r"worktree add", add), (r"merge-base --is-ancestor", ship.Result(1)), *_ok_rules()])
    assert _merger(fake).run().ok
    assert len(fake.ran(r"-m brain --root .* refresh --offline")) == 1 and not fake.ran(r"-m brain --root .* check$")
    fake = Fake(tmp_path, [(r"worktree add", add), *_ok_rules()])
    ship.enqueue("acme/lab", 8, str(tmp_path / "acme-lab"))
    assert _merger(fake).run().ok
    assert fake.ran(r"-m brain --root .* check$") and not fake.ran("refresh")


GATE_CHECKS = ["open", "merge-check", "ci", "review", "public", "body", "pins"]


@pytest.mark.parametrize("check", GATE_CHECKS)
def test_every_block_of_the_merge_gate_refuses_the_pr(tmp_path, check):
    _queue(tmp_path, 7)
    fake = Fake(tmp_path, _ok_rules())
    rep = _merger(fake, _gate(blocks=(check,))).run()
    assert [d["status"] for d in rep.done] == ["refused"] and f"{check}: {check} detail" in rep.done[0]["reason"]
    assert not fake.ran("worktree add") and not fake.ran("pr merge") and not rep.ok
    assert ship.entries()[0]["status"] == "refused"


def test_fresh_alone_is_the_mergers_own_job_and_a_gate_with_no_check_refuses(tmp_path):
    _queue(tmp_path, 7)
    fake = Fake(tmp_path, [(r"merge-base --is-ancestor", ship.Result(1)), *_ok_rules()])
    assert _merger(fake, _gate(blocks=("fresh",))).run().ok

    def empty(top, pr, slug, remote, view):
        return mergeready.Gate(int(pr), slug, HEAD, "main")
    ship.enqueue("acme/lab", 8, str(tmp_path / "acme-lab"))
    rep = _merger(Fake(tmp_path, _ok_rules()), empty).run()
    assert rep.done[0]["status"] == "refused" and "no check" in rep.done[0]["reason"]


@pytest.mark.parametrize("answer,why", [(ship.Result(127, "", "gh: not found"), "not found"),
                                        (ship.Result(124, "", "gh: no answer in 120 s"), "no answer"),
                                        (ship.Result(0, "Bad gateway <html>"), "not JSON")],
                         ids=["down", "slow", "garbage"])
def test_gh_down_slow_or_garbage_at_the_gate_fails_that_pr_and_the_next_goes_on(tmp_path, answer, why):
    _queue(tmp_path, 7, 8)
    fake = Fake(tmp_path, [(r"pr view 7 ", answer), *_ok_rules()])
    rep = _merger(fake).run()
    assert [(d["pr"], d["status"]) for d in rep.done] == [(7, "failed"), (8, "merged")]
    assert why in rep.done[0]["reason"] and "merge gate could not run" in rep.done[0]["reason"]
    assert not fake.ran("pr merge 7 ")


@pytest.mark.parametrize("pattern,answer,why", [
    (r"worktree add", ship.Result(127, "", "git: not found"), "git worktree add: git: not found"),
    (r"merge-base --is-ancestor", ship.Result(128, "", "fatal: bad object"), "git merge-base"),
    (r"test --changed", ship.Result(124, "", "python: no answer in 1800 s"), "targeted tests"),
    (r"test --changed", ship.Result(1, "3 failed"), "3 failed"),
    (r"pr merge", ship.Result(1, "", "head branch was modified"), "gh pr merge: head branch was modified"),
    (r"pr merge", ship.Result(124, "", "gh: no answer in 120 s"), "gh pr merge: gh: no answer"),
], ids=["git-down", "git-garbage", "tests-slow", "tests-red", "gh-merge-refused", "gh-merge-slow"])
def test_a_step_that_fails_marks_the_pr_failed_with_its_reason(tmp_path, pattern, answer, why):
    _queue(tmp_path, 7, 8)
    first = [True]

    def once(cmd, cwd):   # only the first PR's step fails
        if first[0]:
            first[0] = False
            return answer
        return ship.Result(0, "b" * 40)
    fake = Fake(tmp_path, [(pattern, once), *_ok_rules()])
    rep = _merger(fake).run()
    assert [(d["pr"], d["status"]) for d in rep.done] == [(7, "failed"), (8, "merged")], rep.done
    assert why in rep.done[0]["reason"] and not rep.ok
    assert ship.entries()[0]["reason"] == rep.done[0]["reason"]


def test_a_conflict_the_driver_leaves_aborts_the_merge_and_fails_the_pr(tmp_path):
    _queue(tmp_path, 7)
    fake = Fake(tmp_path, [(r"merge-base --is-ancestor", ship.Result(1)),
                           (r"merge --no-ff", ship.Result(1, "CONFLICT (content)")),
                           (r"diff --name-only --diff-filter=U", ship.Result(0, "README.md\nCHANGELOG.md\n")),
                           *_ok_rules()])
    rep = _merger(fake).run()
    assert rep.done[0]["status"] == "failed" and "README.md, CHANGELOG.md" in rep.done[0]["reason"]
    assert fake.ran("merge --abort") and not fake.ran("push") and not fake.ran("pr merge")


def test_a_missing_checkout_fails_without_a_call(tmp_path):
    ship.enqueue("acme/lab", 7, str(tmp_path / "gone"))
    fake = Fake(tmp_path)
    rep = _merger(fake).run()
    assert rep.done[0]["status"] == "failed" and "is gone" in rep.done[0]["reason"] and not fake.calls


def _failing_suite_from(fake: Fake, bad: set[str]):
    """The suite fails on every tip in ``bad`` (the scratch's commit, as the fake runner saw it added)."""
    def suite(top, python):
        return [(top, ["pytest-suite", fake.at[str(Path(top))]])]
    fake.rules.insert(0, (r"^pytest-suite", lambda cmd, cwd: ship.Result(1 if cmd[-1] in bad else 0, "F")))
    return suite


def _moving_tip(fake: Fake):
    """origin/main's tip moves on each fetch after a merge: _sha(1), _sha(2), ..."""
    tip = [0]

    def fetched(cmd, cwd):
        tip[0] += 1
        return ship.Result(0)
    fake.rules.insert(0, (r"fetch --quiet origin", fetched))
    fake.rules.insert(0, (r"rev-parse --verify origin/main", lambda c, w: ship.Result(0, _sha(tip[0]))))


def test_the_full_suite_runs_once_per_batch_and_the_bisection_names_the_culprit(tmp_path):
    _queue(tmp_path, 1, 2, 3, 4, 5, 6)
    fake = Fake(tmp_path, _ok_rules())
    _moving_tip(fake)
    suite = _failing_suite_from(fake, {_sha(5), _sha(6)})   # main fails from #5's merge on
    rep = _merger(fake, batch=3, suite=suite).run()
    assert [d["status"] for d in rep.done] == ["merged"] * 6
    assert [(s["prs"], s["result"], s["culprit"]) for s in rep.suites] == [([1, 2, 3], "pass", None),
                                                                            ([4, 5, 6], "fail", 5)]
    runs = [c[-1] for c in fake.calls if c[0] == "pytest-suite"]
    assert runs == [_sha(3), _sha(6), _sha(4), _sha(5)]   # once per batch, then the bisection's two steps
    by = {e["pr"]: e for e in ship.entries()}
    assert by[5]["status"] == "culprit" and "not reverted" in by[5]["reason"] and by[6]["status"] == "merged"
    assert rep.stopped and not rep.ok


def test_a_red_batch_stops_the_run_before_the_next_pr(tmp_path):
    _queue(tmp_path, 1, 2, 3)
    fake = Fake(tmp_path, _ok_rules())
    _moving_tip(fake)
    suite = _failing_suite_from(fake, {_sha(1), _sha(2)})
    rep = _merger(fake, batch=2, suite=suite).run()
    assert [d["pr"] for d in rep.done] == [1, 2] and rep.suites[0]["culprit"] == 1
    assert ship.entries()[2]["status"] == "queued"   # left for the next run, once main is fixed


@pytest.mark.parametrize("answer", [ship.Result(124, "", "pytest: no answer in 3600 s"),
                                    ship.Result(127, "", "python: not found")], ids=["slow", "down"])
def test_a_suite_that_cannot_answer_names_no_culprit_and_stops(tmp_path, answer):
    _queue(tmp_path, 1, 2)
    fake = Fake(tmp_path, [(r"^pytest-suite", answer), *_ok_rules()])
    _moving_tip(fake)
    rep = _merger(fake, batch=2).run()
    assert rep.suites[0]["result"] == "error" and rep.suites[0]["culprit"] is None and rep.stopped
    assert {e["status"] for e in ship.entries()} == {"merged"}


def test_two_repos_in_one_queue_never_mix_their_batches(tmp_path):
    lab = _queue(tmp_path, 1, repo="acme/lab")
    _queue(tmp_path, 1, repo="acme/web")
    ship.enqueue("acme/lab", 2, str(lab))
    fake = Fake(tmp_path, _ok_rules())
    _moving_tip(fake)
    rep = _merger(fake, batch=2).run()
    assert [(d["repo"], d["pr"]) for d in rep.done] == [("acme/lab", 1), ("acme/web", 1), ("acme/lab", 2)]
    assert [(s["repo"], s["prs"]) for s in rep.suites] == [("acme/lab", [1, 2]), ("acme/web", [1])]
    assert ship.place(ship.entries(), "acme/web", 1) == (0, 0)


def test_the_mergers_lock_is_released_when_its_run_raises(tmp_path):
    def gate(*a):
        raise RuntimeError("an unexpected failure in the gate")
    _queue(tmp_path, 1)
    with pytest.raises(RuntimeError):
        ship.merge_queue(runner=Fake(tmp_path), gate=gate, suite=_suite, say=lambda line: None)
    assert ship.lock_holder() == {} and not filelock.Lock(ship.LOCK, 1).path.exists()


def test_a_dry_run_says_the_plan_and_calls_nothing(tmp_path, capsys, monkeypatch):
    _queue(tmp_path, 1, 2, 3)
    called = []
    monkeypatch.setattr(ship, "run", lambda *a, **k: called.append(a))
    monkeypatch.setattr(ship, "merge_queue", lambda *a, **k: called.append(a))
    assert cli.main(["ship", "--run", "--dry-run", "--batch", "2"]) == 0
    out = capsys.readouterr().out
    assert "3 PR(s) open" in out and "would ship acme/lab#1" in out and "a batch of 2" in out
    assert "for its last 1 merge(s)" in out and not called and not filelock.Lock(ship.LOCK, 1).path.exists()


def test_the_real_gate_and_real_git_on_a_local_origin(make_repo, tmp_path):
    """The gate's own function, git for real on a local bare origin: a PR behind main is caught up and pushed; gh
    and the brain and pytest children are faked."""
    origin = git_init(tmp_path / "origin.git", bare=True)
    work = make_repo("lab", {"a.txt": "a\n", "b.txt": "b\n"})
    run_git(work, "remote", "add", "origin", str(origin))
    run_git(work, "push", "-q", "origin", "main")
    run_git(work, "switch", "-q", "-c", "feat")
    head = make_repo.commit(work, {"a.txt": "a, changed\n"})
    run_git(work, "push", "-q", "origin", "feat")
    run_git(work, "switch", "-q", "main")
    make_repo.commit(work, {"b.txt": "b, on main\n"})
    run_git(work, "push", "-q", "origin", "main")
    review.stamp(head, 0, 0)
    green = [{"__typename": "CheckRun", "name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"}]
    data = {"number": 7, "state": "OPEN", "isDraft": False, "mergeable": "MERGEABLE", "headRefName": "feat",
            "headRefOid": head, "baseRefName": "main", "title": "t", "body": "b", "statusCheckRollup": green,
            "url": "https://github.com/acme/lab/pull/7"}

    def real(cmd, cwd=None, timeout=0, env=None):
        if Path(cmd[0]).stem == "git":
            return ship.run(cmd, cwd, timeout, env)
        if cmd[1:3] == ["pr", "view"]:
            return ship.Result(0, json.dumps(data))
        return ship.Result(0)
    calls = []

    def runner(cmd, cwd=None, timeout=0, env=None):
        calls.append([str(c) for c in cmd])
        return real([str(c) for c in cmd], cwd, timeout, env)
    ship.enqueue("acme/lab", 7, str(work), "origin", "t", "feat")
    rep = ship.merge_queue(runner=runner, suite=lambda top, py: [], say=lambda line: None)
    assert rep.ok, rep.done
    new = run_git(origin, "rev-parse", "feat").strip()
    assert new != head and run_git(origin, "merge-base", "--is-ancestor", "main", "feat") == ""
    assert [c for c in calls if c[1:3] == ["pr", "merge"]][0][-1] == new
    assert ship.lock_holder() == {}


# --- the command line -------------------------------------------------------------------------------------------


def test_the_command_line_takes_the_parents_flags_after_and_refuses_a_mixed_mode(capsys):
    p = cli.build_parser()
    a = p.parse_args(["ship", "12", "--project", "lab", "--repo-dir", "x", "--json"])
    assert (a.cmd, a.pr, a.project, a.repo_dir, a.json) == ("ship", "12", "lab", "x", True)
    assert cli.main(["ship"]) == 2 and cli.main(["ship", "12", "--list"]) == 2
    assert cli.main(["ship", "12", "--batch", "3"]) == 2 and cli.main(["ship", "--run", "--batch", "0"]) == 2
    assert "give one of" in capsys.readouterr().err


def test_list_json_and_text(tmp_path, capsys):
    assert cli.main(["ship", "--list"]) == 0 and "the queue is empty" in capsys.readouterr().out
    _queue(tmp_path, 4)
    assert cli.main(["ship", "--list", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [e["pr"] for e in out["entries"]] == [4] and out["lock"] is None
    lk = filelock.Lock(ship.LOCK, 60).acquire()
    try:
        assert cli.main(["ship", "--list"]) == 0
        text = capsys.readouterr().out
        assert "| 1 | acme/lab | #4 | queued | PR 4 |" in text and f"pid {os.getpid()}" in text
        assert cli.main(["ship", "--run"]) == 1   # another merger holds the lock
        assert "another merger runs: pid" in capsys.readouterr().err
    finally:
        lk.release()


def test_the_queue_command_exits_non_zero_when_it_cannot_queue(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(ship, "queue_pr", lambda *a, **k: (_ for _ in ()).throw(ship.ShipError("no repo here")))
    assert cli.main(["ship", "3"]) == 1 and "no repo here" in capsys.readouterr().err


def _doc_lines() -> list[tuple[str, str]]:
    """Every ``brain ship ...`` command line of the docs that name it."""
    files = [ROOT / "README.md", ROOT / "docs" / "merge-driver.md"]
    out = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            for m in re.finditer(r"(?:^|`)(brain ship[^`#]*)", line.strip()):
                cmd = m.group(1).strip()
                if cmd != "brain ship":
                    out.append((f.name, cmd))
    return out


def test_every_brain_ship_line_of_the_docs_passes_the_real_parser():
    lines = _doc_lines()
    assert len(lines) >= 5, lines
    p = cli.build_parser()
    for name, line in lines:
        words = [w for w in shlex.split(line.replace("[", "").replace("]", "").replace("...", ""))
                 if w not in ("|",)]
        words = ["12" if w == "PR" else "3" if w == "N" else "." if w == "D" else
                 "acme/lab" if w == "OWNER/NAME" else "origin" if w == "R" else w for w in words]
        try:
            p.parse_args(words[1:])
        except SystemExit:
            pytest.fail(f"{name}: {line!r} does not parse")
