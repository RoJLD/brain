"""``brain merge-ready PR --with PR...``: PRs green alone checked as they will be merged, together
(wi-brain-merge-ready-together; packages/brain/docs/merge-driver.md, « The merge gate »).

Each PR first passes the merge gate alone (brain.mergeready.gate); a PR given twice counts once, and a set needs two.
Then the set is integrated on the base, in the order given, at zero token and with nothing checked out: each head
merged into the result so far by ``git merge-tree`` with the repo's merge driver (``merge=brain``: the attributes of
the base's ``.gitattributes``, the driver of the repo's git config, else this engine's own), its tree committed by
``git commit-tree`` for the next one. A head that conflicts is listed with its files and left out (it conflicts with a
PR before it: one of them merges the other's change first); the order that merges is the merge order said.

GitHub merges with no driver. So the same merges are also made as plain text, on a chain of their own (the text
result where it is clean, the driver's where GitHub would have needed a local merge): a head whose text merge
conflicts once those before it merged needs a new head (the base merged into it locally, where the driver resolves
it, pushed, its CI again) before its own merge: it is not ready as it is, and gets no stamp.

The tests are chosen by the files the set touches (brain.impact, from the base to the integrated commit);
``--test`` runs them in a scratch worktree of that commit (``<python> -m pytest -q``, the checkout's ``src`` folders
first on PYTHONPATH, no git hook run), removed afterwards (pruned when its removal fails). Under ``--test``, a test
choice that failed is not ready. Ready means every PR ready alone, every head merged as it is, and the tests green
when they ran; each head ready as it is gets its stamp (brain.mergeready.stamp), which names the PRs it was checked
with, even when the set is not ready (the first ones may merge while a later one gets its new head).
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
    as_text: list[str] = field(default_factory=list)     # GitHub's merge after those before it: the files that conflict
    own_text: list[str] = field(default_factory=list)    # GitHub's merge onto the base alone: the files that conflict

    @property
    def needs_new_head(self) -> bool:
        """Merged by the driver, but GitHub's merge conflicts once those before it merged (not on the base alone)."""
        return self.merged and bool(self.as_text) and not self.own_text


@dataclass
class Together:
    gates: list[mergeready.Gate]
    base: str = ""                                       # the base's commit
    result: str = ""                                     # the integrated commit
    steps: list[Step] = field(default_factory=list)      # in the order tried
    tests: list[str] = field(default_factory=list)       # the test modules impact chose
    tests_note: str = ""
    tests_rc: int | None = None                          # pytest's exit, when --test ran them
    tests_error: str = ""                                # under --test: why no test could be chosen or run
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
        return (not self.error and all(g.ready for g in self.gates) and not self.left and not self.tests_error
                and not any(s.needs_new_head for s in self.steps) and self.tests_rc in (None, 0))

    def stampable(self) -> list[mergeready.Gate]:
        """The heads ready as they are: ready alone, merged, no new head needed, the tests green when they ran."""
        if self.error or self.tests_error or self.tests_rc not in (None, 0):
            return []
        ok = {s.pr for s in self.steps if s.merged and not s.needs_new_head}
        return [g for g in self.gates if g.ready and g.pr in ok]

    def to_json(self) -> dict:
        return {"ready": self.ready, "base": self.base, "result": self.result, "order": self.order,
                "steps": [{**vars(s), "needs_new_head": s.needs_new_head} for s in self.steps], "tests": self.tests,
                "tests_note": self.tests_note, "tests_rc": self.tests_rc, "tests_error": self.tests_error,
                "error": self.error, "prs": [g.to_json() for g in self.gates]}


def _attributes(repo: Path, base: str) -> str:
    try:
        return git(repo, "show", f"{base}:.gitattributes", allow=(0, 128))
    except AuditError:
        return ""


def _driver(repo: Path) -> str:
    """The repo's own merge.brain.driver, else this engine's (its module run by this Python, as the replay does)."""
    cur = git(repo, "config", f"merge.{mergedriver.NAME}.driver", allow=(0, 1)).strip()
    return cur or f'"{Path(sys.executable).as_posix()}" -m brain.mergedriver %O %A %B %P %L'


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
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=120,
                           env={**os.environ, **env}, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise mergeready.GateError(f"git commit-tree: {exc}") from None
    if r.returncode:
        raise mergeready.GateError(f"git commit-tree: {r.stderr.strip() or r.returncode}")
    return r.stdout.strip()


def integrate(repo: Path, base: str, heads: list[tuple[int, str]]) -> tuple[str, list[Step]]:
    """(the integrated commit, the steps): each head merged in order into the result so far; a conflicting one is
    left out and the next merged without it (a merge only adds: it would conflict at any later place too). Beside it,
    GitHub's chain: the plain-text merges, the driver's result taken where the text conflicts (the new head merged)."""
    driver = _driver(repo)
    with tempfile.TemporaryDirectory(prefix="brain-together-") as d:
        attrs = Path(d) / "attributes"
        attrs.write_text(_attributes(repo, base), encoding="utf-8")
        cur, gh_cur, steps = base, base, []
        for pr, head in heads:
            step = Step(pr, head)
            tree, step.conflicts = merge_tree(repo, cur, head, driver, attrs)
            text_tree, step.as_text = merge_tree(repo, gh_cur, head, TEXT_DRIVER, attrs)
            if step.as_text:
                _, step.own_text = merge_tree(repo, base, head, TEXT_DRIVER, attrs)
            if not step.conflicts and tree:
                cur, step.merged = _commit(repo, tree, [cur, head], pr), True
                gh_cur = cur if step.as_text else _commit(repo, text_tree, [gh_cur, head], pr)
            steps.append(step)
    return cur, steps


def chosen_tests(repo: Path, base: str, result: str, project: str = "") -> tuple[list[str], str, str]:
    """(the test modules brain impact names for the change base..result, a note, the error when impact failed)."""
    from . import impact
    try:
        rep = impact.run(SimpleNamespace(repo_dir=str(repo), diff=f"{base}..{result}", depth=None,
                                         project=project or None), None)
    except Exception as exc:   # the gate says why it chose none, never stops on it
        why = f"brain impact failed: {type(exc).__name__}: {exc}"
        return [], why, why
    mods = sorted({t["path"] for t in rep.tests if t.get("framework") == "pytest" and t["path"].endswith(".py")})
    return mods, f"brain impact ({rep.mode}): {len(mods)} test module(s)", ""


def _src_path(top: Path) -> str:
    roots = [top / "src", *sorted(top.glob("packages/*/src"))]
    return os.pathsep.join(str(r) for r in roots if r.is_dir())


def _remove(repo: Path, scratch: Path) -> str:
    """The scratch worktree removed; when git cannot (a process still holds a file), its folder deleted and the
    worktree pruned. '' or what was left."""
    git(repo, "worktree", "remove", "--force", str(scratch), allow=(0, 128))
    if not scratch.exists():
        return ""
    shutil.rmtree(scratch, ignore_errors=True)
    git(repo, "worktree", "prune", allow=(0, 128))
    return f"the scratch worktree {scratch} could not be removed whole" if scratch.exists() else ""


def run_tests(repo: Path, commit: str, tests: list[str], python: str = "") -> tuple[int, str]:
    """pytest on ``tests`` in a scratch worktree of ``commit`` (removed afterwards): (its exit, its last lines);
    127 when the Python does not start, 124 when pytest does not answer in time."""
    scratch = Path(tempfile.mkdtemp(prefix="brain-together-wt-"))
    shutil.rmtree(scratch)
    hooks = tempfile.mkdtemp(prefix="brain-together-hooks-")   # no post-checkout hook runs in the scratch
    try:
        git(repo, "-c", f"core.hooksPath={Path(hooks).as_posix()}", "worktree", "add", "--detach", "--quiet",
            str(scratch), commit)
    finally:
        shutil.rmtree(hooks, ignore_errors=True)
    try:
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(x for x in (_src_path(scratch),
                                                                         os.environ.get("PYTHONPATH", "")) if x)}
        try:
            r = subprocess.run([python or sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests],
                               cwd=scratch, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=TEST_TIMEOUT, env=env, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return 124, f"pytest: no answer in {TEST_TIMEOUT} s"
        except OSError as exc:
            return 127, f"{python or sys.executable}: {exc}"
        return r.returncode, "\n".join((r.stdout or r.stderr).strip().splitlines()[-5:])
    finally:
        left = _remove(repo, scratch)
        if left:
            print(f"brain merge-ready: warning: {left}", file=sys.stderr)


def _gates(repo: Path, prs: list[str], slug: str, remote: str, fetch: bool, view, cfg) -> list[mergeready.Gate]:
    """Each PR's gate, a PR given twice (by number, URL or branch) once."""
    gates: list[mergeready.Gate] = []
    for pr in prs:
        g = mergeready.gate(repo, pr, slug, remote, fetch=fetch, view=view, cfg=cfg)
        if g.pr not in {x.pr for x in gates}:
            gates.append(g)
    return gates


def check(repo: Path, prs: list[str], slug: str = "", remote: str = "", fetch: bool = True, test: bool = False,
          python: str = "", project: str = "", view=None, cfg=None) -> Together:
    """The merge gate for ``prs`` merged together, in that order (module docstring); ``view``: gh pr view's answer
    (default brain.mergeready.gh_view)."""
    t = Together(_gates(repo, prs, slug, remote, fetch, view or mergeready.gh_view, cfg))
    bases = {g.base for g in t.gates}
    if len(t.gates) < 2:
        t.error = "a set of one PR: --with names another (brain merge-ready PR alone checks one)"
    elif len(bases) != 1:
        t.error = f"the PRs merge into different bases: {', '.join(sorted(bases))}"
    if t.error:
        return t
    t.base = git(repo, "rev-parse", "--verify", f"{remote or 'origin'}/{bases.pop()}^{{commit}}").strip()
    t.result, t.steps = integrate(repo, t.base, [(g.pr, g.head) for g in t.gates])
    if t.left:
        return t
    t.tests, t.tests_note, failed = chosen_tests(repo, t.base, t.result, project)
    if test and failed:
        t.tests_error = failed
    elif test and t.tests:
        t.tests_rc, tail = run_tests(repo, t.result, t.tests, python)
        t.tests_note += f"; pytest exit {t.tests_rc}" + (f": {tail}" if tail else "")
    elif test:
        t.tests_note += "; none to run"
    return t


def stamps(t: Together) -> list[Path]:
    """The stamp of each head ready as it is, naming the PRs it was checked with and the merge order."""
    order = t.order
    return [mergeready.stamp(g, {"with": [p for p in order if p != g.pr], "order": order, "integrated": t.result,
                                 "tests": t.tests, "tests_rc": t.tests_rc}) for g in t.stampable()]


def _step_line(s: Step, before: list[int]) -> str:
    """One head's line: left out, to merge the base into after those before it, its own text conflict, or clean."""
    after = ", ".join(f"#{n}" for n in before)
    if not s.merged:
        return f"  BLOCK #{s.pr} conflicts after {after or 'the base'}: " + ", ".join(s.conflicts or ["(no tree)"])
    if s.needs_new_head:
        return (f"  then  #{s.pr}: once {after} merged, GitHub sees a conflict on {', '.join(s.as_text)}: merge the "
                "base into it locally (the driver resolves it), push, CI again; no stamp for this head")
    if s.as_text:
        return f"  note  #{s.pr}: its own merge conflicts as text on {', '.join(s.as_text)} (GitHub)"
    return f"  ok    #{s.pr} merges clean"


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
        out.append(_step_line(s, before))
        if s.merged:
            before.append(s.pr)
    out.append(f"  tests {t.tests_note or 'not chosen (a head did not merge)'}")
    if t.tests_error:
        out.append(f"  BLOCK tests: {t.tests_error}")
    if t.tests:
        out.append("        pytest " + " ".join(t.tests))
    return out
