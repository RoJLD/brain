"""``brain merge-ready PR --with PR...``: PRs green alone checked as they will be merged, together
(wi-brain-merge-ready-together; packages/brain/docs/merge-driver.md, « The merge gate »).

Each PR first passes the merge gate alone (brain.mergeready.gate). Then the set is integrated on the base, in the
order given, at zero token and with nothing checked out: each head merged into the result so far by ``git
merge-tree`` with the repo's merge driver (``merge=brain``: the attributes of the base's ``.gitattributes``, the
driver of the repo's git config, else this engine's), its tree committed by ``git commit-tree`` for the next one. A
head that conflicts is listed with its files and left out (it conflicts with a PR before it: one of them merges
the other's change first); the order that merges is the merge order said. The same merges are also made as plain
text (no driver, as GitHub merges): a PR that conflicts there once those before it are merged must merge the base
again locally, where the driver resolves it, and push before its own merge.

The tests are chosen by the files the set touches (brain.impact, from the base to the integrated commit);
``--test`` runs them in a scratch worktree of that commit (``<python> -m pytest -q``, the checkout's ``src`` folders
first on PYTHONPATH), removed afterwards. Ready means every PR ready alone, every head merged, and the tests green
when they ran: each head then gets its stamp (brain.mergeready.stamp), which names the PRs it was checked with.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from . import mergedriver, mergeready
from .inventory import AuditError, git

TEXT_DRIVER = "git merge-file --marker-size=%L %A %O %B"   # a merge with no driver of its own, as GitHub's
TEST_TIMEOUT = 1800


@dataclass
class Step:
    pr: int
    head: str
    merged: bool = False
    conflicts: list[str] = field(default_factory=list)   # with the driver: the files left conflicted
    as_text: list[str] = field(default_factory=list)     # with no driver (GitHub's merge): the files that conflict


@dataclass
class Together:
    gates: list[mergeready.Gate]
    base: str = ""                                       # the base's commit
    result: str = ""                                     # the integrated commit
    steps: list[Step] = field(default_factory=list)      # in the order tried
    tests: list[str] = field(default_factory=list)       # the test modules impact chose
    tests_note: str = ""
    tests_rc: int | None = None                          # pytest's exit, when --test ran them
    error: str = ""

    @property
    def order(self) -> list[int]:
        return [s.pr for s in self.steps if s.merged]

    @property
    def left(self) -> list[Step]:
        """The heads that did not merge."""
        return [s for s in self.steps if not s.merged]

    @property
    def ready(self) -> bool:
        return (not self.error and all(g.ready for g in self.gates) and not self.left
                and self.tests_rc in (None, 0))

    def to_json(self) -> dict:
        return {"ready": self.ready, "base": self.base, "result": self.result, "order": self.order,
                "steps": [vars(s) for s in self.steps], "tests": self.tests, "tests_note": self.tests_note,
                "tests_rc": self.tests_rc, "error": self.error, "prs": [g.to_json() for g in self.gates]}


def _attributes(repo: Path, base: str) -> str:
    try:
        return git(repo, "show", f"{base}:.gitattributes", allow=(0, 128))
    except AuditError:
        return ""


def _driver(repo: Path) -> str:
    cur = git(repo, "config", f"merge.{mergedriver.NAME}.driver", allow=(0, 1)).strip()
    return cur or mergedriver.command()


def merge_tree(repo: Path, ours: str, theirs: str, driver: str, attrs: Path) -> tuple[str, list[str]]:
    """(the merged tree, the conflicted paths) of ``git merge-tree``, the driver ``driver`` for merge=brain and only
    the attributes file ``attrs``. Git runs from the scratch folder ``attrs`` sits in, the repo named by GIT_DIR: the
    driver's temporary files land there, never in a checkout; the driver marks no view (a check, not a merge)."""
    common = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    env = {**os.environ, mergedriver.NO_MARK: "1", "GIT_DIR": common}
    try:
        r = subprocess.run(["git", "-c", f"core.attributesFile={attrs.as_posix()}", "-c",
                            f"merge.{mergedriver.NAME}.driver={driver}", "merge-tree", "--write-tree", "--name-only",
                            "--no-messages", ours, theirs], cwd=attrs.parent, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600, env=env, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise mergeready.GateError(f"git merge-tree: {exc}") from None
    if r.returncode not in (0, 1):
        raise mergeready.GateError(f"git merge-tree {ours[:8]} {theirs[:8]}: {r.stderr.strip() or r.returncode}")
    lines = [x for x in r.stdout.splitlines() if x]
    return (lines[0] if lines else ""), lines[1:]


def _commit(repo: Path, tree: str, parents: list[str], pr: int) -> str:
    args = ["commit-tree", tree, *(x for p in parents for x in ("-p", p)), "-m", f"brain merge-ready --with: #{pr}"]
    env = {"GIT_AUTHOR_NAME": "brain", "GIT_AUTHOR_EMAIL": "brain@localhost", "GIT_COMMITTER_NAME": "brain",
           "GIT_COMMITTER_EMAIL": "brain@localhost"}
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=120,
                       env={**os.environ, **env}, stdin=subprocess.DEVNULL)
    if r.returncode:
        raise mergeready.GateError(f"git commit-tree: {r.stderr.strip() or r.returncode}")
    return r.stdout.strip()


def integrate(repo: Path, base: str, heads: list[tuple[int, str]]) -> tuple[str, list[Step]]:
    """(the integrated commit, the steps): each head merged in order into the result so far; a conflicting one is
    left out and the next merged without it (a merge only adds: it would conflict at any later place too)."""
    driver = _driver(repo)
    with tempfile.TemporaryDirectory(prefix="brain-together-") as d:
        attrs = Path(d) / "attributes"
        attrs.write_text(_attributes(repo, base), encoding="utf-8")
        cur, steps = base, []
        for pr, head in heads:
            step = Step(pr, head)
            tree, step.conflicts = merge_tree(repo, cur, head, driver, attrs)
            _, step.as_text = merge_tree(repo, cur, head, TEXT_DRIVER, attrs)
            if not step.conflicts and tree:
                cur, step.merged = _commit(repo, tree, [cur, head], pr), True
            steps.append(step)
    return cur, steps


def chosen_tests(repo: Path, base: str, result: str, project: str = "") -> tuple[list[str], str]:
    """(the test modules brain impact names for the change base..result, a note)."""
    from . import impact
    try:
        rep = impact.run(SimpleNamespace(repo_dir=str(repo), diff=f"{base}..{result}", depth=None,
                                         project=project or None), None)
    except Exception as exc:   # the gate says why it chose none, never stops on it
        return [], f"brain impact failed: {type(exc).__name__}: {exc}"
    mods = sorted({t["path"] for t in rep.tests if t.get("framework") == "pytest" and t["path"].endswith(".py")})
    return mods, f"brain impact ({rep.mode}): {len(mods)} test module(s)"


def _src_path(top: Path) -> str:
    roots = [top / "src", *sorted(top.glob("packages/*/src"))]
    return os.pathsep.join(str(r) for r in roots if r.is_dir())


def run_tests(repo: Path, commit: str, tests: list[str], python: str = "") -> tuple[int, str]:
    """pytest on ``tests`` in a scratch worktree of ``commit`` (removed afterwards): (its exit, its last lines)."""
    scratch = Path(tempfile.mkdtemp(prefix="brain-together-wt-"))
    shutil.rmtree(scratch)
    git(repo, "worktree", "add", "--detach", "--quiet", str(scratch), commit)
    try:
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(x for x in (_src_path(scratch),
                                                                         os.environ.get("PYTHONPATH", "")) if x)}
        try:
            r = subprocess.run([python or sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
                               cwd=scratch, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=TEST_TIMEOUT, env=env, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return 124, f"pytest: no answer in {TEST_TIMEOUT} s"
        tail = "\n".join((r.stdout or r.stderr).strip().splitlines()[-5:])
        return r.returncode, tail
    finally:
        git(repo, "worktree", "remove", "--force", str(scratch), allow=(0, 128))


def check(repo: Path, prs: list[str], slug: str = "", remote: str = "", fetch: bool = True, test: bool = False,
          python: str = "", project: str = "", view=None, cfg=None) -> Together:
    """The merge gate for ``prs`` merged together, in that order (module docstring); ``view``: gh pr view's answer
    (default brain.mergeready.gh_view)."""
    view = view or mergeready.gh_view
    gates = [mergeready.gate(repo, pr, slug, remote, fetch=fetch, view=view, cfg=cfg) for pr in prs]
    t = Together(gates)
    bases = {g.base for g in gates}
    if len(bases) != 1:
        t.error = f"the PRs merge into different bases: {', '.join(sorted(bases))}"
        return t
    remote = remote or "origin"
    t.base = git(repo, "rev-parse", "--verify", f"{remote}/{bases.pop()}^{{commit}}").strip()
    t.result, t.steps = integrate(repo, t.base, [(g.pr, g.head) for g in gates])
    if t.left:
        return t
    t.tests, t.tests_note = chosen_tests(repo, t.base, t.result, project)
    if test and t.tests:
        t.tests_rc, tail = run_tests(repo, t.result, t.tests, python)
        t.tests_note += f"; pytest exit {t.tests_rc}" + (f": {tail}" if tail else "")
    elif test:
        t.tests_note += "; none to run"
    return t


def stamps(t: Together) -> list[Path]:
    """Each head's stamp, naming the PRs it was checked with and the merge order."""
    order = t.order
    return [mergeready.stamp(g, {"with": [p for p in order if p != g.pr], "order": order, "integrated": t.result,
                                 "tests": t.tests, "tests_rc": t.tests_rc}) for g in t.gates]


def lines(t: Together) -> list[str]:
    out = []
    for g in t.gates:
        out += mergeready.lines(g)
    if t.error:
        return out + [f"together: {t.error}"]
    out.append(f"together onto {t.base[:8]}: " + ("READY" if t.ready else "not ready")
               + f"; merge order: {', '.join(f'#{n}' for n in t.order) or 'none'}")
    before: list[int] = []
    for s in t.steps:
        if not s.merged:
            out.append(f"  BLOCK #{s.pr} conflicts after {', '.join(f'#{n}' for n in before) or 'the base'}: "
                       + ", ".join(s.conflicts or ["(no tree)"]))
            continue
        if s.as_text and before:
            out.append(f"  then  #{s.pr}: once {', '.join(f'#{n}' for n in before)} merged, GitHub sees a conflict "
                       f"on {', '.join(s.as_text)}: merge the base into it locally (the driver resolves it), push, "
                       "CI again")
        elif s.as_text:
            out.append(f"  note  #{s.pr}: its own merge conflicts as text on {', '.join(s.as_text)} (GitHub)")
        else:
            out.append(f"  ok    #{s.pr} merges clean")
        before.append(s.pr)
    out.append(f"  tests {t.tests_note or 'not chosen (a head did not merge)'}")
    if t.tests:
        out.append("        pytest " + " ".join(t.tests))
    return out
