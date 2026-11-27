"""brain ship: a local merge queue. The queue file (idempotent, per repo, any title kept and escaped, a PR of another
repo refused), the merger (the merge gate's every block refuses, a fork PR and a push to the base refused, the
catch-up, a caught-up head stamped, pushed, its CI awaited and gated again, the merge read back, the batch's full
suite per repo and base, its confirmed bisection, a red base waiting), and every external system down, slow or
answering garbage. gh, git and pytest are faked through the runner; the test that runs git for real uses a local
bare origin, never a real remote."""

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest
from brain import cli, filelock, mergeready, review, ship
from conftest import git_init, run_git

HEAD = "a" * 40
NEW = "b" * 40   # the caught-up head the scratch's HEAD reads
CHECKS = ("open", "fresh", "merge-check", "ci", "review", "public", "body", "pins")
ROOT = Path(__file__).resolve().parents[1]   # packages/brain


def _sha(n: int) -> str:
    return f"{n:040x}"


@pytest.fixture(autouse=True)
def _own_temp(tmp_path, monkeypatch):
    """The scratch worktrees' folder under this test's own temporary folder."""
    monkeypatch.setattr(ship.tempfile, "tempdir", str(tmp_path / "tmp"))
    (tmp_path / "tmp").mkdir()


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


class Hub:
    """GitHub as the merger reads it: each PR's head, branch, base, fork flag and checks; a merge makes a merge
    commit on its base, whose parent is the base's tip before it."""

    def __init__(self):
        self.prs: dict[tuple[str, int], dict] = {}
        self.count = 100
        self.parent: dict[str, str] = {}
        self.tip: dict[tuple[str, str], str] = {}
        self.methods = {"mergeCommitAllowed": True, "squashMergeAllowed": True}
        self.pushes: list[str] = []

    def pr(self, repo: str, n: int, **kw) -> dict:
        p = {"head": HEAD, "branch": f"feat-{n}", "base": "main", "cross": False, "state": "OPEN", "merge": "",
             "checks": "SUCCESS", "new_checks": "SUCCESS"}
        p.update(kw)
        self.prs[(repo, n)] = p
        return p

    def _of(self, cmd):
        return self.prs[(cmd[cmd.index("--repo") + 1], int(cmd[3]))]

    def view(self, cmd, cwd):
        n, p = int(cmd[3]), self._of(cmd)
        checks = p["new_checks"] if p["head"] == NEW else p["checks"]
        rollup = [{"__typename": "CheckRun", "name": "tests", "status": "IN_PROGRESS" if checks == "RUNNING" else
                   "COMPLETED", "conclusion": "" if checks == "RUNNING" else checks}]
        return ship.Result(0, json.dumps({
            "number": n, "state": p["state"], "isDraft": False, "mergeable": "MERGEABLE", "headRefName": p["branch"],
            "headRefOid": p["head"], "baseRefName": p["base"], "isCrossRepository": p["cross"],
            "headRepositoryOwner": {"login": "ada"}, "statusCheckRollup": rollup, "title": f"PR {n}", "body": "",
            "mergeCommit": {"oid": p["merge"]} if p["merge"] else None, "url": f"https://github.com/x/y/pull/{n}"}))

    def merge(self, cmd, cwd):
        p = self._of(cmd)
        repo = cmd[cmd.index("--repo") + 1]
        if p["state"] != "OPEN" or cmd[-1] != p["head"]:
            return ship.Result(1, "", "the head moved")
        self.count += 1
        oid = _sha(self.count)
        self.parent[oid] = self.tip.get((repo, p["base"]), _sha(99))
        self.tip[(repo, p["base"])] = oid
        p.update(state="MERGED", merge=oid)
        return ship.Result(0, "merged")

    def push(self, cmd, cwd):
        branch = cmd[-1].split("refs/heads/", 1)[1]
        self.pushes.append(branch)
        for p in self.prs.values():
            if p["branch"] == branch:
                p["head"] = NEW
        return ship.Result(0)

    def rules(self):
        return [(r"^gh pr view", self.view), (r"^gh pr merge", self.merge),
                (r"^gh repo view", lambda c, w: ship.Result(0, json.dumps(self.methods))),
                (r"^git push", self.push), (r"rev-parse --verify HEAD", ship.Result(0, NEW + "\n")),
                (r"rev-parse --verify [0-9a-f]{40}\^1", lambda c, w: ship.Result(
                    0, self.parent.get(c[-1].split("^")[0], _sha(99)) + "\n")),
                (r"symbolic-ref", ship.Result(0, "origin/main\n"))]


def _gate(blocks=(), on_new=()):
    """A gate that reads the PR through the merger's view (gh through the runner), then answers ``blocks`` on the
    PR's own head and ``on_new`` on the caught-up head."""
    def gate(top, pr, slug, remote, view):
        data = view(pr, slug, top)
        g = mergeready.Gate(int(pr), slug, data["headRefOid"], data["baseRefName"])
        b = on_new if data["headRefOid"] == NEW else blocks
        for c in CHECKS:
            g.add(c, c not in b, f"{c} detail")
        return g
    return gate


def _pr_json(pr=7, branch="feat", title="Adds a line"):
    return ship.Result(0, json.dumps({"number": pr, "state": "OPEN", "headRefName": branch, "title": title,
                                      "url": f"https://github.com/acme/lab/pull/{pr}"}))


def _queue(tmp_path, *prs, repo="acme/lab", hub=None, **kw):
    d = tmp_path / repo.replace("/", "-")
    d.mkdir(exist_ok=True)
    for pr in prs:
        ship.enqueue(repo, pr, str(d), "origin", f"PR {pr}", f"feat-{pr}")
        if hub is not None:
            hub.pr(repo, pr, **kw)
    return d


def _suite_at(fake: Fake, bad=()):
    """The suite: one pytest run per tip; it fails on the tips in ``bad`` (a callable for a changing answer)."""
    def answer(cmd, cwd):
        failing = bad(cmd[-1]) if callable(bad) else cmd[-1] in bad
        return ship.Result(1 if failing else 0, "1 failed" if failing else "")
    fake.rules.insert(0, (r"^pytest-suite", answer))

    def suite(top, python):
        return [(top, ["pytest-suite", fake.at[str(Path(top))]])]
    return suite


def _setup(tmp_path, *prs, rules=(), **kw):
    hub = Hub()
    _queue(tmp_path, *prs, hub=hub, **kw)
    fake = Fake(tmp_path, [*rules, *hub.rules()])
    return hub, fake


def _merger(fake, gate=None, batch=5, suite=None, **kw):
    kw = {"say": lambda line: None, "is_public": lambda repo: False, "sleep": lambda s: None, "ci_wait": 0, **kw}
    return ship.Merger(fake, gate or _gate(), suite or _suite_at(fake), batch, **kw)


BEHIND = (r"merge-base --is-ancestor", ship.Result(1))


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


def test_a_queue_a_newer_brain_wrote_is_read_but_never_written(tmp_path, capsys, monkeypatch):
    ship.queue_path().parent.mkdir(parents=True)
    ship.queue_path().write_text(json.dumps({"v": 2, "entries": [{"repo": "acme/lab", "pr": 1, "status": "queued",
                                                                  "lane": "a newer key"}]}), encoding="utf-8")
    assert [e["pr"] for e in ship.entries()] == [1]
    with pytest.raises(ship.stateio.StateError):
        ship.enqueue("acme/lab", 2, str(tmp_path))
    monkeypatch.setattr(ship, "merge_queue", lambda *a, **k: (_ for _ in ()).throw(ship.stateio.StateError("newer")))
    assert cli.main(["ship", "--run"]) == 1 and "newer" in capsys.readouterr().err
    assert json.loads(ship.queue_path().read_text(encoding="utf-8"))["v"] == 2


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


def test_a_pr_of_another_repo_than_the_checkouts_is_refused(tmp_path):
    fake = Fake(tmp_path, [*_locate_rules(tmp_path), (r"^gh pr view", _pr_json(5))])
    with pytest.raises(ship.ShipError, match="not a PR of this checkout's repo"):
        ship.queue_pr("https://github.com/acme/web/pull/5", tmp_path, runner=fake)
    with pytest.raises(ship.ShipError, match="acme/web#5 is not a PR"):
        ship.queue_pr("5", tmp_path, slug="acme/web", runner=fake)
    assert ship.entries() == [] and not fake.ran("pr view")
    e, *_ = ship.queue_pr("5", tmp_path, slug="ACME/lab", runner=fake)   # the same repo, any case
    assert e["repo"] == "ACME/lab"


def test_the_finished_entries_past_the_newest_kept_are_dropped_and_a_culprit_stays(tmp_path, monkeypatch):
    monkeypatch.setattr(ship, "KEEP_FINISHED", 2)
    _queue(tmp_path, 1, 2, 3, 4)
    _queue(tmp_path, 1, repo="acme/web")
    for pr, st in ((1, "culprit"), (2, "merged"), (3, "failed")):
        ship.update("acme/lab", pr, status=st)
    ship.update("acme/web", 1, status="merged")
    ship.update("acme/lab", 4, status="merged")   # a third finished one of acme/lab: the oldest goes
    assert [(e["repo"], e["pr"]) for e in ship.entries()] == [("acme/lab", 1), ("acme/lab", 3), ("acme/lab", 4),
                                                              ("acme/web", 1)]


# --- the merger -------------------------------------------------------------------------------------------------


def test_an_up_to_date_pr_is_checked_and_merged_at_the_head_the_gate_saw(tmp_path):
    hub, fake = _setup(tmp_path, 7)
    rep = _merger(fake).run()
    assert rep.ok and [d["status"] for d in rep.done] == ["merged"], rep.done
    assert fake.ran("merge-base --is-ancestor origin/main HEAD") and not hub.pushes
    assert fake.ran(f"pr merge 7 --repo acme/lab --merge --match-head-commit {HEAD}")
    assert fake.ran(r"-m brain test --changed origin/main --repo-dir .* --strict$") and not fake.ran("merge-check")
    assert rep.suites and rep.suites[0]["prs"] == [7] and rep.suites[0]["result"] == "pass"   # the partial batch
    e = ship.entries()[0]
    assert e["status"] == "merged" and e["head"] == HEAD and e["merged"] == _sha(101)
    assert mergeready.stamp_path("acme/lab", HEAD).is_file()   # the gate's own stamp, for the head merged
    assert not any(Path(p).exists() for p in fake.at)   # the scratch worktrees removed


def test_a_caught_up_head_is_pushed_its_ci_awaited_and_gated_again_before_its_merge(tmp_path):
    hub, fake = _setup(tmp_path, 7, rules=[BEHIND])
    seen = []
    gate = _gate()

    def watching(top, pr, slug, remote, view):
        g = gate(top, pr, slug, remote, view)
        seen.append(g.head)
        return g
    rep = _merger(fake, watching).run()
    assert rep.ok, rep.done
    steps = (r"merge --no-ff|commit --no-edit|merge-check|test --changed| push |pr view 7 --repo acme/lab --json "
             r"headRefOid,|pr merge")
    order = [re.search(steps, c).group(0).strip().rstrip(",") for c in (" ".join(x) for x in fake.calls)
             if re.search(steps, c)]
    assert order == ["merge --no-ff", "commit --no-edit", "merge-check", "test --changed", "push",
                     "pr view 7 --repo acme/lab --json headRefOid", "pr merge"], order
    assert hub.pushes == ["feat-7"] and fake.ran(f"--match-head-commit {NEW}")
    assert seen == [HEAD, NEW]   # the gate ran on the caught-up head too
    assert mergeready.stamp_path("acme/lab", NEW).is_file() and "gated again" in rep.done[0]["reason"]


def test_a_public_repos_caught_up_head_is_stamped_before_its_push(tmp_path):
    hub, fake = _setup(tmp_path, 7, rules=[BEHIND])
    assert _merger(fake, is_public=lambda repo: repo == "acme/lab").run().ok
    calls = [" ".join(c) for c in fake.calls]
    stamp = next(i for i, c in enumerate(calls) if "check --public --history" in c)
    push = next(i for i, c in enumerate(calls) if " push " in c)
    assert stamp < push
    hub, fake = _setup(tmp_path, 8, rules=[BEHIND, (r"check --public --history", ship.Result(1, "denied 1"))])
    rep = _merger(fake, is_public=lambda repo: True).run()
    assert rep.done[-1]["status"] == "failed" and "brain check --public" in rep.done[-1]["reason"]
    assert not hub.pushes and not fake.ran("pr merge")


@pytest.mark.parametrize("checks,why", [("FAILURE", "the CI of the caught-up head"),
                                        ("RUNNING", "not green in 0 s")], ids=["red", "never-green"])
def test_a_caught_up_head_whose_ci_is_red_or_never_green_fails_and_the_next_goes_on(tmp_path, checks, why):
    hub, fake = _setup(tmp_path, 7, 8, rules=[BEHIND])
    hub.prs[("acme/lab", 7)]["new_checks"] = checks
    hub.prs[("acme/lab", 8)]["branch"] = "feat-8b"
    rep = _merger(fake).run()
    assert [(d["pr"], d["status"]) for d in rep.done] == [(7, "failed"), (8, "merged")]
    assert why in rep.done[0]["reason"] and not fake.ran("pr merge 7 ")


def test_the_ci_wait_polls_until_green(tmp_path):
    hub, fake = _setup(tmp_path, 7, rules=[BEHIND])
    p = hub.prs[("acme/lab", 7)]
    p["new_checks"] = "RUNNING"
    slept = []

    def sleep(s):
        slept.append(s)
        if len(slept) == 2:
            p["new_checks"] = "SUCCESS"
    assert _merger(fake, sleep=sleep, ci_wait=3600).run().ok and slept == [ship.CI_POLL] * 2


def test_the_gate_on_the_caught_up_head_refuses_with_nothing_waived(tmp_path):
    hub, fake = _setup(tmp_path, 7, rules=[BEHIND])
    rep = _merger(fake, _gate(on_new=("review",))).run()
    assert rep.done[0]["status"] == "failed" and "the merge gate on the caught-up head" in rep.done[0]["reason"]
    assert f"a new review stamp for {NEW}" in rep.done[0]["reason"] and not fake.ran("pr merge")
    hub, fake = _setup(tmp_path, 8, rules=[BEHIND])
    rep = _merger(fake, _gate(on_new=("fresh",))).run()   # fresh is waived on the PR's own head only
    assert rep.done[-1]["status"] == "failed" and "fresh: fresh detail" in rep.done[-1]["reason"]


def test_a_graph_store_gets_its_views_regenerated_once_after_the_catch_up(tmp_path):
    def add(cmd, cwd):
        Path(cmd[-2], "notes", "graph").mkdir(parents=True)
        Path(cmd[-2], "notes", "graph", "schema.yaml").write_text("x: 1\n", encoding="utf-8")
        return ship.Result(0)
    hub, fake = _setup(tmp_path, 7, rules=[(r"worktree add", add), BEHIND])
    assert _merger(fake).run().ok
    assert len(fake.ran(r"-m brain --root .* refresh --offline")) == 1 and not fake.ran(r"-m brain --root .* check$")
    hub, fake = _setup(tmp_path, 8, rules=[(r"worktree add", add)])
    assert _merger(fake).run().ok
    assert fake.ran(r"-m brain --root .* check$") and not fake.ran("refresh")


def test_a_refresh_refused_for_the_engine_pin_says_so(tmp_path):
    def add(cmd, cwd):
        Path(cmd[-2], "notes", "graph").mkdir(parents=True)
        Path(cmd[-2], "notes", "graph", "schema.yaml").write_text("x: 1\n", encoding="utf-8")
        return ship.Result(0)
    hub, fake = _setup(tmp_path, 7, rules=[(r"worktree add", add), BEHIND, (r"refresh --offline", ship.Result(
        1, "", "brain refresh: the running engine is not config.json engine.pin v9"))])
    rep = _merger(fake).run()
    assert "pins another engine" in rep.done[0]["reason"]


@pytest.mark.parametrize("check", [c for c in CHECKS if c != "fresh"])
def test_every_block_of_the_merge_gate_refuses_the_pr(tmp_path, check):
    hub, fake = _setup(tmp_path, 7)
    rep = _merger(fake, _gate(blocks=(check,))).run()
    assert [d["status"] for d in rep.done] == ["refused"] and f"{check}: {check} detail" in rep.done[0]["reason"]
    assert not fake.ran("worktree add") and not fake.ran("pr merge") and not rep.ok
    assert ship.entries()[0]["status"] == "refused"


def _no_ci_gate(blocks=()):
    """A gate for a repo that declares no CI: its ci check blocks marked local (brain.mergeready.LOCAL)."""
    def gate(top, pr, slug, remote, view):
        g = _gate(blocks)(top, pr, slug, remote, view)
        ci = next(c for c in g.checks if c["check"] == "ci")
        ci.update(ok=False, detail=mergeready.no_ci_detail(slug), local=True)
        return g
    return gate


def test_a_no_ci_repos_pr_is_merged_on_the_mergers_local_checks(tmp_path):
    """wi-brain-gate-local-checks-no-ci: the local ci block does not refuse; the targeted tests run, and the gate's
    stamp records ci answered by them."""
    hub, fake = _setup(tmp_path, 7)
    rep = _merger(fake, _no_ci_gate()).run()
    assert [d["status"] for d in rep.done] == ["merged"], rep.done
    assert fake.ran(r"-m brain test --changed origin/main")
    rec = json.loads(mergeready.stamp_path("acme/lab", HEAD).read_text(encoding="utf-8"))
    assert rec["local"] == ["ci"] and "ci" in rec["checks"]   # told apart from a CI's green
    assert "local" not in json.loads(mergeready.stamp(mergeready.Gate(8, "acme/lab", NEW, "main")).read_text(
        encoding="utf-8"))


def test_a_no_ci_repos_caught_up_head_awaits_no_ci_and_a_failed_local_check_refuses_the_merge(tmp_path):
    hub, fake = _setup(tmp_path, 7, rules=[BEHIND])
    p = hub.prs[("acme/lab", 7)]
    p["new_checks"] = "RUNNING"   # no CI to await: a running check never holds the merge
    lag = []

    def lagging(cmd, cwd):   # GitHub reads the pushed head one poll late
        lag.append(1)
        if len(lag) == 1:
            return ship.Result(0, json.dumps({"headRefOid": HEAD, "statusCheckRollup": []}))
        return hub.view(cmd, cwd)
    fake.rules.insert(0, (r"^gh pr view 7 .*headRefOid,statusCheckRollup", lagging))
    slept = []
    rep = _merger(fake, _no_ci_gate(), sleep=slept.append, ci_wait=3600).run()
    assert rep.ok and "gated again" in rep.done[0]["reason"], rep.done
    assert len(lag) == 2 and slept == [ship.CI_POLL] and fake.ran(f"--match-head-commit {NEW}")
    hub, fake = _setup(tmp_path, 8, rules=[(r"test --changed", ship.Result(1, "1 failed"))])
    rep = _merger(fake, _no_ci_gate()).run()
    assert rep.done[-1]["status"] == "failed" and "the targeted tests" in rep.done[-1]["reason"]
    assert not fake.ran("pr merge")


def test_a_local_ci_block_never_waives_another_block(tmp_path):
    hub, fake = _setup(tmp_path, 7)
    rep = _merger(fake, _no_ci_gate(blocks=("review",))).run()
    assert rep.done[0]["status"] == "refused" and "review: review detail" in rep.done[0]["reason"]
    assert "ci:" not in rep.done[0]["reason"] and not fake.ran("worktree add")


def test_fresh_alone_is_the_mergers_own_job_and_a_gate_with_no_check_refuses(tmp_path):
    hub, fake = _setup(tmp_path, 7, rules=[BEHIND])
    assert _merger(fake, _gate(blocks=("fresh",))).run().ok

    def empty(top, pr, slug, remote, view):
        view(pr, slug, top)
        return mergeready.Gate(int(pr), slug, HEAD, "main")
    hub, fake = _setup(tmp_path, 8)
    rep = _merger(fake, empty).run()
    assert rep.done[0]["status"] == "refused" and "no check" in rep.done[0]["reason"]


@pytest.mark.parametrize("change,why", [({"cross": True}, "a PR from a fork (ada)"),
                                        ({"cross": None}, "a PR from a fork"),
                                        ({"branch": "main"}, "is the base or the default branch"),
                                        ({"branch": "trunk", "base": "trunk"}, "is the base"),
                                        ({"branch": ""}, "(unknown)")],
                         ids=["fork", "fork-unknown", "branch-is-main", "branch-is-base", "no-branch"])
def test_a_fork_pr_or_a_branch_that_is_the_base_is_refused_and_never_pushed(tmp_path, change, why):
    hub, fake = _setup(tmp_path, 7, rules=[BEHIND])
    hub.prs[("acme/lab", 7)].update(change)
    rep = _merger(fake).run()
    assert rep.done[0]["status"] == "refused" and why in rep.done[0]["reason"]
    assert not hub.pushes and not fake.ran("worktree add") and not fake.ran("pr merge")


@pytest.mark.parametrize("answer,why", [(ship.Result(127, "", "gh: not found"), "not found"),
                                        (ship.Result(124, "", "gh: no answer in 120 s"), "no answer"),
                                        (ship.Result(0, "Bad gateway <html>"), "not JSON")],
                         ids=["down", "slow", "garbage"])
def test_gh_down_slow_or_garbage_at_the_gate_fails_that_pr_and_the_next_goes_on(tmp_path, answer, why):
    hub, fake = _setup(tmp_path, 7, 8, rules=[(r"pr view 7 ", answer)])
    rep = _merger(fake).run()
    assert [(d["pr"], d["status"]) for d in rep.done] == [(7, "failed"), (8, "merged")]
    assert why in rep.done[0]["reason"] and "merge gate could not run" in rep.done[0]["reason"]
    assert not fake.ran("pr merge 7 ")


def test_an_unexpected_exception_fails_that_pr_only_and_never_poisons_the_queue(tmp_path):
    hub, fake = _setup(tmp_path, 7, 8)
    gate = _gate()

    def garbage(top, pr, slug, remote, view):   # gh's JSON valid but not the shape: the gate's code raises
        if int(pr) == 7:
            view(pr, slug, top)
            return mergeready._check_state(1)   # AttributeError: 1 is no check
        return gate(top, pr, slug, remote, view)
    rep = _merger(fake, garbage).run()
    assert [(d["pr"], d["status"]) for d in rep.done] == [(7, "failed"), (8, "merged")]
    assert "an unexpected AttributeError" in rep.done[0]["reason"]
    rep = _merger(Fake(tmp_path, hub.rules()), garbage).run()   # the next run: nothing left running to choke on
    assert rep.done == []


@pytest.mark.parametrize("pattern,answer,why", [
    (r"worktree add", ship.Result(127, "", "git: not found"), "git worktree add: git: not found"),
    (r"merge-base --is-ancestor", ship.Result(128, "", "fatal: bad object"), "git merge-base"),
    (r"test --changed", ship.Result(124, "", "python: no answer in 1800 s"), "targeted tests"),
    (r"test --changed", ship.Result(1, "3 failed"), "3 failed"),
], ids=["git-down", "git-garbage", "tests-slow", "tests-red"])
def test_a_step_that_fails_marks_the_pr_failed_with_its_reason(tmp_path, pattern, answer, why):
    first = [True]

    def once(cmd, cwd):   # only the first PR's step fails
        if first[0]:
            first[0] = False
            return answer
        return ship.Result(0)
    hub, fake = _setup(tmp_path, 7, 8, rules=[(pattern, once)])
    rep = _merger(fake).run()
    assert [(d["pr"], d["status"]) for d in rep.done] == [(7, "failed"), (8, "merged")], rep.done
    assert why in rep.done[0]["reason"] and not rep.ok
    assert ship.entries()[0]["reason"] == rep.done[0]["reason"]


def test_the_merge_is_read_back_whatever_gh_pr_merge_answered(tmp_path):
    hub, fake = _setup(tmp_path, 7)
    real = hub.merge
    fake.rules.insert(0, (r"^gh pr merge", lambda c, w: (real(c, w), ship.Result(124, "", "gh: no answer"))[1]))
    rep = _merger(fake).run()   # gh timed out after GitHub merged: merged, in the batch
    assert rep.ok and rep.done[0]["status"] == "merged" and rep.suites[0]["prs"] == [7]
    hub, fake = _setup(tmp_path, 8)
    fake.rules.insert(0, (r"^gh pr merge", ship.Result(0, "queued")))   # GitHub's own queue: still open
    rep = _merger(fake).run()
    assert rep.done[-1]["status"] == "failed" and "still open" in rep.done[-1]["reason"] and not rep.suites


def test_a_merge_whose_outcome_cannot_be_read_stops_the_run(tmp_path):
    hub, fake = _setup(tmp_path, 7, 8)
    merged = []

    def view(cmd, cwd):
        if merged and "state,mergeCommit" in " ".join(cmd):
            return ship.Result(0, "<html>")
        return hub.view(cmd, cwd)

    def merge(cmd, cwd):
        merged.append(1)
        return hub.merge(cmd, cwd)
    fake.rules[:0] = [(r"^gh pr view", view), (r"^gh pr merge", merge)]
    rep = _merger(fake).run()
    assert rep.stopped and "check it by hand" in rep.stopped and [d["pr"] for d in rep.done] == [7]
    assert ship.entries()[1]["status"] == "queued"


def test_the_repos_allowed_merge_method_is_used(tmp_path):
    hub, fake = _setup(tmp_path, 7)
    hub.methods = {"mergeCommitAllowed": False, "squashMergeAllowed": True}
    assert _merger(fake).run().ok and fake.ran(r"pr merge 7 --repo acme/lab --squash")


def test_a_conflict_the_driver_leaves_aborts_the_merge_and_fails_the_pr(tmp_path):
    hub, fake = _setup(tmp_path, 7, rules=[BEHIND, (r"merge --no-ff", ship.Result(1, "CONFLICT (content)")),
                                           (r"diff --name-only --diff-filter=U",
                                            ship.Result(0, "README.md\nCHANGELOG.md\n"))])
    rep = _merger(fake).run()
    assert rep.done[0]["status"] == "failed" and "README.md, CHANGELOG.md" in rep.done[0]["reason"]
    assert fake.ran("merge --abort") and not hub.pushes and not fake.ran("pr merge")


def test_a_missing_checkout_fails_without_a_call(tmp_path):
    ship.enqueue("acme/lab", 7, str(tmp_path / "gone"))
    fake = Fake(tmp_path)
    rep = _merger(fake).run()
    assert rep.done[0]["status"] == "failed" and "is gone" in rep.done[0]["reason"] and not fake.calls


def test_a_running_entry_a_live_merger_holds_is_never_taken(tmp_path):
    hub, fake = _setup(tmp_path, 7, 8)
    live = {"pid": os.getpid(), "pstart": filelock.proc_start(os.getpid()), "host": filelock.host(), "token": "t2"}
    ship.update("acme/lab", 7, status="running", merger=live)
    rep = _merger(fake).run()
    assert [d["pr"] for d in rep.done] == [8] and ship.entries()[0]["status"] == "running"
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait(timeout=60)
    ship.update("acme/lab", 7, merger={**live, "pid": dead.pid, "pstart": ""})
    rep = _merger(fake).run()   # its merger is gone: taken
    assert [d["pr"] for d in rep.done] == [7]


# --- the batch's full suite ---------------------------------------------------------------------------------------


def test_the_full_suite_runs_once_per_batch_and_a_confirmed_bisection_names_the_culprit(tmp_path):
    hub, fake = _setup(tmp_path, 1, 2, 3, 4, 5, 6)
    suite = _suite_at(fake, {_sha(105), _sha(106)})   # main fails from #5's merge (the 5th merge commit) on
    rep = _merger(fake, batch=3, suite=suite).run()
    assert [d["status"] for d in rep.done] == ["merged"] * 6
    assert [(s["prs"], s["result"], s["culprit"]) for s in rep.suites] == [([1, 2, 3], "pass", None),
                                                                            ([4, 5, 6], "fail", 5)]
    runs = [c[-1] for c in fake.calls if c[0] == "pytest-suite"]
    # once per batch; the bisection's two steps; the culprit's merge again, then its parent
    assert runs == [_sha(103), _sha(106), _sha(104), _sha(105), _sha(105), _sha(104)]
    by = {e["pr"]: e for e in ship.entries()}
    assert by[5]["status"] == "culprit" and "not reverted" in by[5]["reason"] and by[6]["status"] == "merged"
    assert rep.stopped and not rep.ok and ship.red()["acme/lab@main"]["culprit"] == 5


def test_a_failure_that_does_not_reproduce_is_flaky_and_names_no_culprit(tmp_path):
    hub, fake = _setup(tmp_path, 1, 2)
    calls = []

    def once(sha):
        calls.append(sha)
        return len(calls) == 1
    rep = _merger(fake, batch=2, suite=_suite_at(fake, once)).run()
    assert rep.suites[0]["culprit"] is None and "flaky" in rep.suites[0]["detail"]
    assert {e["status"] for e in ship.entries()} == {"merged"} and rep.stopped


def test_a_main_red_before_the_batch_blames_no_pr_and_its_prs_wait(tmp_path):
    hub, fake = _setup(tmp_path, 1, 2)
    rep = _merger(fake, batch=2, suite=_suite_at(fake, lambda sha: True)).run()
    assert rep.suites[0]["culprit"] is None and "red before #1's merge" in rep.suites[0]["detail"]
    assert {e["status"] for e in ship.entries()} == {"merged"} and "acme/lab@main" in ship.red()
    _queue(tmp_path, 3, hub=hub)
    rep = _merger(Fake(tmp_path, hub.rules())).run()   # main is red: the next PR waits
    assert rep.waiting and ship.entries()[-1]["status"] == "queued" and "waiting" in ship.entries()[-1]["reason"]
    assert not rep.ok
    fake = Fake(tmp_path, hub.rules())
    rep = _merger(fake, force=True).run()   # --force ships it, and a green suite clears the red base
    assert rep.ok and ship.entries()[-1]["status"] == "merged" and ship.red() == {}


@pytest.mark.parametrize("answer", [ship.Result(124, "", "pytest: no answer in 3600 s"),
                                    ship.Result(127, "", "python: not found")], ids=["slow", "down"])
def test_a_suite_that_cannot_answer_names_no_culprit_and_stops(tmp_path, answer):
    hub, fake = _setup(tmp_path, 1, 2, rules=[(r"^pytest-suite", answer)])
    rep = _merger(fake, batch=2, suite=lambda top, py: [(top, ["pytest-suite"])]).run()
    assert rep.suites[0]["result"] == "error" and rep.suites[0]["culprit"] is None and rep.stopped
    assert {e["status"] for e in ship.entries()} == {"merged"}


def test_a_red_batch_stops_the_run_and_the_other_repos_batches_are_still_tested(tmp_path):
    hub = Hub()
    _queue(tmp_path, 1, repo="acme/web", hub=hub)
    _queue(tmp_path, 1, 2, 3, hub=hub)
    fake = Fake(tmp_path, hub.rules())
    rep = _merger(fake, batch=2, suite=_suite_at(fake, {_sha(102), _sha(103)})).run()
    assert [(d["repo"], d["pr"]) for d in rep.done] == [("acme/web", 1), ("acme/lab", 1), ("acme/lab", 2)]
    assert [(s["repo"], s["prs"], s["result"]) for s in rep.suites] == [("acme/lab", [1, 2], "fail"),
                                                                       ("acme/web", [1], "pass")]
    assert ship.entries("acme/lab")[2]["status"] == "queued" and rep.stopped


def test_two_repos_and_two_bases_never_mix_their_batches(tmp_path):
    hub = Hub()
    lab = _queue(tmp_path, 1, hub=hub)
    _queue(tmp_path, 1, repo="acme/web", hub=hub)
    ship.enqueue("acme/lab", 2, str(lab))
    hub.pr("acme/lab", 2, base="feat-x")
    ship.enqueue("acme/lab", 3, str(lab))
    hub.pr("acme/lab", 3)
    fake = Fake(tmp_path, hub.rules())
    rep = _merger(fake, batch=2).run()
    assert [(d["repo"], d["pr"]) for d in rep.done] == [("acme/lab", 1), ("acme/web", 1), ("acme/lab", 2),
                                                        ("acme/lab", 3)]
    assert sorted((s["repo"], s["base"], s["prs"]) for s in rep.suites) == [
        ("acme/lab", "feat-x", [2]), ("acme/lab", "main", [1, 3]), ("acme/web", "main", [1])]
    assert ship.place(ship.entries(), "acme/web", 1) == (0, 0)


def test_a_lost_lock_marks_the_pending_batch_untested(tmp_path):
    hub, fake = _setup(tmp_path, 1, 2)
    m = _merger(fake, batch=5)

    class Lost:
        token, lost = "t", ""

        def holder(self):
            return {"token": "t"}
    m.lock = Lost()
    real = m.process

    def process(e):
        out = real(e)
        m.lock.lost = "broken by another"
        return out
    m.process = process
    with pytest.raises(filelock.LockError):
        m.run()
    assert m.report.untested and m.report.untested[0]["prs"] == [1]
    assert ship.entries()[0]["suite"].startswith("untested")


def test_the_mergers_lock_is_released_when_its_run_raises(tmp_path):
    def gate(*a):
        raise KeyboardInterrupt
    _queue(tmp_path, 1)
    with pytest.raises(KeyboardInterrupt):
        ship.merge_queue(runner=Fake(tmp_path), gate=gate, suite=lambda t, p: [], say=lambda line: None)
    assert ship.lock_holder() == {} and not filelock.Lock(ship.LOCK, 1).path.exists()


def test_a_run_sweeps_the_scratch_worktrees_a_killed_merger_left(tmp_path):
    left = ship.scratch_root() / "wt-old"
    left.mkdir(parents=True)
    other = Path(ship.tempfile.gettempdir()) / "brain-ship-0123456789" / "wt-x"   # another BRAIN_HOME's: kept
    other.mkdir(parents=True)
    _queue(tmp_path, 1)
    fake = Fake(tmp_path, [(r"pr view", ship.Result(1, "", "down"))])
    ship.merge_queue(runner=fake, suite=lambda t, p: [], say=lambda line: None, is_public=lambda r: False)
    assert not left.exists() and other.exists() and fake.ran("worktree prune")


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
    """The gate's own function, git for real on a local bare origin: a reviewed PR behind main is caught up, pushed,
    gated again (its review carried: git's own merge of main) and merged; gh and the brain children are faked."""
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
    gh_side = tmp_path / "gh-side"
    run_git(tmp_path, "clone", "-q", str(origin), str(gh_side))
    green = [{"__typename": "CheckRun", "name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"}]
    state = {"state": "OPEN", "merge": ""}

    def data():
        return {"number": 7, "state": state["state"], "isDraft": False, "mergeable": "MERGEABLE",
                "headRefName": "feat", "headRefOid": run_git(origin, "rev-parse", "feat").strip(),
                "baseRefName": "main", "title": "t", "body": "b", "statusCheckRollup": green,
                "isCrossRepository": False, "mergeCommit": {"oid": state["merge"]} if state["merge"] else None,
                "url": "https://github.com/acme/lab/pull/7"}

    def runner(cmd, cwd=None, timeout=0, env=None):
        cmd = [str(c) for c in cmd]
        calls.append(cmd)
        if Path(cmd[0]).stem == "git":
            return ship.run(cmd, cwd, timeout, env)
        if cmd[1:3] == ["pr", "view"]:
            return ship.Result(0, json.dumps(data()))
        if cmd[1:3] == ["pr", "merge"]:
            run_git(gh_side, "fetch", "-q", "origin")
            run_git(gh_side, "merge", "-q", "--no-ff", "-m", "Merge PR 7", "origin/feat")
            run_git(gh_side, "push", "-q", "origin", "HEAD:main")
            state.update(state="MERGED", merge=run_git(gh_side, "rev-parse", "HEAD").strip())
            return ship.Result(0)
        return ship.Result(0)
    calls: list[list[str]] = []
    ship.enqueue("acme/lab", 7, str(work), "origin", "t", "feat")
    rep = ship.merge_queue(runner=runner, suite=lambda top, py: [], say=lambda line: None, sleep=lambda s: None)
    assert rep.ok, (rep.done, rep.suites)
    new = run_git(origin, "rev-parse", "feat").strip()
    assert new != head and run_git(origin, "rev-list", "--parents", "-n", "1", new).split()[1:] == [
        head, run_git(origin, "rev-parse", "main^1").strip()]   # main's merge of feat, whose head merged main
    assert run_git(origin, "merge-base", "--is-ancestor", "feat", "main") == ""
    assert [c for c in calls if c[1:3] == ["pr", "merge"]][0][-1] == new
    assert mergeready.stamp_path("acme/lab", new).is_file() and ship.lock_holder() == {}


# --- the runner -------------------------------------------------------------------------------------------------


_TREE = """
import subprocess, sys, time
subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
time.sleep(30)
"""


def test_the_runner_stops_the_whole_process_tree_at_its_timeout():
    t0 = time.monotonic()
    r = ship.run([sys.executable, "-c", _TREE], timeout=2)
    assert r.rc == 124 and "process tree stopped" in r.err and time.monotonic() - t0 < 20


def test_the_runner_never_lets_git_prompt_and_says_a_missing_tool():
    r = ship.run([sys.executable, "-c", "import os; print(os.environ['GIT_TERMINAL_PROMPT'], "
                                        "os.environ['GCM_INTERACTIVE'])"], timeout=60)
    assert r.ok and r.out.split() == ["0", "never"]
    assert ship.run(["no-such-tool-here"], timeout=5).rc == 127


# --- the command line -------------------------------------------------------------------------------------------


def test_the_command_line_refuses_project_and_root_and_a_mixed_mode(capsys):
    p = cli.build_parser()
    a = p.parse_args(["ship", "12", "--project", "lab", "--repo-dir", "x", "--json"])
    assert (a.cmd, a.pr, a.project, a.repo_dir, a.json) == ("ship", "12", "lab", "x", True)
    assert cli.main(["ship", "12", "--project", "lab"]) == 2 and "--project and --root" in capsys.readouterr().err
    assert cli.main(["--root", ".", "ship", "12"]) == 2
    assert cli.main(["ship"]) == 2 and cli.main(["ship", "12", "--list"]) == 2
    assert cli.main(["ship", "12", "--batch", "3"]) == 2 and cli.main(["ship", "--run", "--batch", "0"]) == 2
    assert cli.main(["ship", "12", "--force"]) == 2
    assert "give one of" in capsys.readouterr().err


def test_list_json_and_text(tmp_path, capsys):
    assert cli.main(["ship", "--list"]) == 0 and "the queue is empty" in capsys.readouterr().out
    _queue(tmp_path, 4)
    ship.set_red("acme/lab", "main", {"sha": _sha(1), "detail": "1 failed", "culprit": None})
    assert cli.main(["ship", "--list", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [e["pr"] for e in out["entries"]] == [4] and out["lock"] is None and "acme/lab@main" in out["red"]
    lk = filelock.Lock(ship.LOCK, 60).acquire()
    try:
        assert cli.main(["ship", "--list"]) == 0
        text = capsys.readouterr().out
        assert "| 1 | acme/lab | #4 | queued | PR 4 |" in text and f"pid {os.getpid()}" in text
        assert "red: acme/lab@main: 1 failed" in text
        assert cli.main(["ship", "--run"]) == 1   # another merger holds the lock
        assert "another merger runs: pid" in capsys.readouterr().err
        assert cli.main(["ship", "--run", "--json"]) == 1
        assert json.loads(capsys.readouterr().out)["ok"] is False
    finally:
        lk.release()


@pytest.mark.parametrize("exc", [ship.ShipError("no repo here"), PermissionError(13, "no repo here")],
                         ids=["refused", "os-error"])
def test_the_queue_command_exits_non_zero_without_a_traceback(tmp_path, capsys, monkeypatch, exc):
    monkeypatch.setattr(ship, "queue_pr", lambda *a, **k: (_ for _ in ()).throw(exc))
    assert cli.main(["ship", "3"]) == 1 and "no repo here" in capsys.readouterr().err
    assert cli.main(["ship", "3", "--json"]) == 1 and json.loads(capsys.readouterr().out)["ok"] is False


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
