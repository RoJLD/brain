"""``brain gate``: the pre-push checks of a branch in one call, each step's log in a file, a three-line verdict
(brain.verdict); exit 0 only when every step that applies passes.

The steps, in order (the cheap ones first; each runs even when one before it failed, unless ``--fail-fast``):

1. **clean**: no file changed, added or left untracked outside ``.gitignore`` that HEAD lacks (a push carries the
   commit, not the working tree: a new module never added passes the audit, which reads the working tree, and is
   missing from the push);
2. **merge-check**: ``brain merge-check`` against the base, a remote one (``origin/main``) fetched again first: the
   branch holds a fresh main (behind: merge it) and lost nothing main brought;
3. **review**: ``brain review stamp`` recorded the review of HEAD with no finding open (or HEAD is only git's own
   merge of the base into a reviewed head: brain.mergeready.carried_review); a change whose every file config.json
   ``merge.repos.<owner/name>.review_exempt`` covers (records, docs, views) needs none
   (brain.mergeready.review_exempt);
4. **views**: in a repo with a graph store (``notes/graph/schema.yaml``), ``brain refresh --offline``: the views
   regenerated and the store checked (``brain check``); a view it rewrote is a change to commit;
5. **audit**: ``brain audit --diff BASE``, the scout on the change: 0 NEW, 0 LEFT (``--store DIR``: the code store
   of a worktree, for a change that spans two repos);
6. **public**: for a public repo (config.json ``public.repos``), ``brain check --public --history`` on HEAD (a head
   whose stamp is valid passes without running it again);
7. **tests**: ``brain test --changed BASE`` (the targeted tests, run by ``--python`` when the repo's tests need
   their own interpreter; ``--strict`` runs the whole suite when the selection widens); the failed tests' ids in the
   verdict.

A step that does not apply (no graph store, a private repo) is skipped with its reason. ``--skip STEP`` skips one on
purpose: the verdict says INCOMPLETE and the exit is 1 even when nothing failed (a skipped check is no pass). Each
step's command and output go to ``<n>-<step>.log`` in the run's folder (brain.verdict:
``<temp>/brain-gate/<repo>-<head>-<UTC stamp>/``, or ``--logs``), the verdict to ``verdict.json``. The steps'
commands run with this Python (``-m brain``: the engine running the gate), through one injectable runner with a
timeout that stops the whole process tree (brain.ship.run): the tests fake it.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from . import verdict
from .inventory import AuditError, git

KIND = "gate"
STEPS = ("clean", "merge-check", "review", "views", "audit", "public", "tests")
CHECK_TIMEOUT = 900
TEST_TIMEOUT = 3600
GRAPH = Path("notes") / "graph" / "schema.yaml"
ON_PURPOSE = "--skip"   # the detail of a step skipped by --skip


class GateError(Exception):
    pass


@dataclass
class Step:
    name: str
    ok: bool | None          # None: skipped (it does not apply, or --skip)
    detail: str = ""         # why it failed, or what it found
    next: str = ""           # the command to run next when it failed
    log: str = ""            # its log file (posix), '' when it ran nothing


@dataclass
class Report:
    repo: str
    head: str
    base: str
    logs: str
    steps: list[Step] = field(default_factory=list)

    @property
    def skipped_on_purpose(self) -> list[str]:
        return [s.name for s in self.steps if s.ok is None and s.detail == ON_PURPOSE]

    @property
    def ok(self) -> bool:
        """No step failed, and none was skipped on purpose (a skipped check is no pass)."""
        return all(s.ok is not False for s in self.steps) and not self.skipped_on_purpose

    def lines(self) -> list[str]:
        failed = [s for s in self.steps if s.ok is False]
        if failed:
            nxt = failed[0].next
        elif self.skipped_on_purpose:
            nxt = f"brain gate without --skip ({', '.join(self.skipped_on_purpose)}) before the push"
        else:
            nxt = "git push (then gh pr create, or brain ship PR once the PR is open)"
        return verdict.three_lines(KIND, [s.name for s in self.steps if s.ok],
                                   [(s.name, s.detail) for s in failed],
                                   [(s.name, s.detail) for s in self.steps if s.ok is None],
                                   Path(self.logs) if self.logs else None, nxt,
                                   state="" if failed or not self.skipped_on_purpose else "INCOMPLETE")

    def to_json(self) -> dict:
        return {"ok": self.ok, "repo": self.repo, "head": self.head, "base": self.base, "logs": self.logs,
                "steps": [asdict(s) for s in self.steps], "verdict": self.lines()}


def _default_runner():
    from . import ship
    return ship.run


def _is_public(top: Path) -> tuple[bool, str]:
    from . import config, public
    cfg = config.load()
    _, slug = public.remote_of(top, cfg)
    return public.is_public(slug, cfg), slug


def _review_exempt(top: Path, files: list[str]) -> str:
    from . import config, mergeready, public
    cfg = config.load()
    return mergeready.review_exempt(public.remote_of(top, cfg)[1], cfg, files)


def _stamp_valid(slug: str, head: str) -> bool:
    from . import config, public
    return public.stamped(slug, head) and not public.stamp_refusal(slug, head, config.load())


class Gate:
    """One gate's run over the checkout ``top``. ``runner`` (brain.ship.Runner), ``is_public``, ``stamp_valid`` and
    ``review_exempt`` are injectable."""

    def __init__(self, top: Path, base: str = "", *, skip: tuple[str, ...] = (), strict: bool = False,
                 fail_fast: bool = False, python: str = "", workers: str = "", logs: Path | None = None,
                 store: str = "", runner=None,
                 is_public: Callable[[Path], tuple[bool, str]] | None = None,
                 stamp_valid: Callable[[str, str], bool] | None = None, say: Callable[[str], None] | None = None,
                 review_exempt: Callable[[Path, list[str]], str] | None = None):
        unknown = sorted(set(skip) - set(STEPS))
        if unknown:
            raise GateError(f"--skip {', '.join(unknown)}: not a step (the steps: {', '.join(STEPS)})")
        self.top = top
        self.skip, self.strict, self.fail_fast, self.store = set(skip), strict, fail_fast, store
        self.python = python or sys.executable   # the tests' interpreter (brain test --python)
        self.engine = sys.executable              # the one that runs every brain step: this engine
        self.workers = workers                    # the tests' pytest-xdist workers (brain test -n)
        self.runner = runner or _default_runner()
        self.is_public, self.stamp_valid = is_public or _is_public, stamp_valid or _stamp_valid
        self.review_exempt = review_exempt or _review_exempt
        self.say = say or (lambda line: None)
        try:
            self.head = git(top, "rev-parse", "HEAD").strip()
        except AuditError as exc:
            raise GateError(str(exc)) from None
        from . import mergecheck
        self.base = base or mergecheck.default_base(top)
        if not self._base_sha() and not (self._fetch_remote_base() and self._base_sha()):
            raise GateError(f"--base {self.base}: not a commit of this checkout, nor of its remote")
        self.folder = logs if logs is not None else verdict.run_folder(KIND, f"{top.name}-{self.head[:8]}")
        self.folder.mkdir(parents=True, exist_ok=True)
        self.report = Report(top.name, self.head, self.base, self.folder.as_posix())
        self._n = 0

    # --- helpers ---

    def _brain(self, *args: str) -> list[str]:
        return [self.engine, "-m", "brain", *args]

    def _log_path(self, name: str) -> Path:
        self._n += 1
        return self.folder / f"{self._n}-{name}.log"

    def _run(self, name: str, cmd: list[str], timeout: float):
        """The step's command, its log written: (Result, the log's path)."""
        r = self.runner(cmd, self.top, timeout)
        log = verdict.write_log(self._log_path(name), cmd, r.rc, r.out, r.err)
        return r, log.as_posix()

    def _dirty(self) -> list[str]:
        out = git(self.top, "status", "--porcelain", "--untracked-files=normal")
        return [line for line in out.splitlines() if line.strip()]

    def _fetch_remote_base(self) -> bool:
        """A remote base (``origin/x``) this checkout never fetched: its remote fetched once; whether it was one."""
        remote = self.base.split("/", 1)[0] if "/" in self.base else ""
        if remote not in git(self.top, "remote").split():
            return False
        git(self.top, "fetch", "--quiet", remote, allow=(0, 1, 128))
        return True

    def _base_sha(self) -> str:
        return git(self.top, "rev-parse", "--verify", f"{self.base}^{{commit}}", allow=(0, 128)).strip()

    # --- the steps ---

    def clean(self) -> Step:
        dirty = self._dirty()
        log = verdict.write_log(self._log_path("clean"), "git status --porcelain --untracked-files=normal", 0,
                                "\n".join(dirty)).as_posix()
        if dirty:
            return Step("clean", False, f"{len(dirty)} file(s) changed or untracked, not in HEAD "
                                        f"({', '.join(x[3:] for x in dirty[:3])}{', ...' if len(dirty) > 3 else ''})",
                        "git add -A && git commit (or .gitignore what is not the change's), then brain gate", log)
        return Step("clean", True, "nothing left out of HEAD", log=log)

    def merge_check(self) -> Step:
        r, log = self._run("merge-check", self._brain("merge-check", "--repo", str(self.top), "--base", self.base,
                                                      "--json"), CHECK_TIMEOUT)
        try:
            data = json.loads(r.out)
        except ValueError:
            data = None
        if not isinstance(data, dict):
            return Step("merge-check", False, f"brain merge-check: {verdict.last_line(r.err, r.out) or r.rc}",
                        f"brain merge-check --base {self.base}", log)
        if data.get("behind"):
            return Step("merge-check", False, f"behind {self.base}: main is not merged into the branch",
                        f"git merge {self.base}, resolve, commit, then brain gate", log)
        lost = len(data.get("lost") or []) + len(data.get("lost_ids") or [])
        if lost or r.rc:
            return Step("merge-check", False, f"{lost} line(s), node change(s) or id(s) of {self.base} lost",
                        f"brain merge-check --base {self.base} (put each lost line back), then brain gate", log)
        return Step("merge-check", True, f"holds {self.base} ({str(data.get('base_sha', ''))[:8]}), nothing lost",
                    log=log)

    def review(self) -> Step:
        from . import mergeready, review
        base_sha = self._base_sha()
        st, how = review.check(self.head), ""
        if st is None and base_sha:
            st, how = mergeready.carried_review(self.top, self.head, base_sha)
        if st is None and base_sha:   # a records, docs or views change needs no stamp (mergeready.review_exempt)
            mb = git(self.top, "merge-base", base_sha, self.head, allow=(0, 1)).strip()
            exempt = self.review_exempt(self.top, sorted(mergeready._names(self.top, mb, self.head))) if mb else ""
            if exempt:
                return Step("review", True, exempt)
        log = verdict.write_log(self._log_path("review"), f"brain review check {self.head}", 0,
                                json.dumps(st, indent=1) if st else "no stamp", how).as_posix()
        if st is None:   # brain gate runs before the push: the stamp of HEAD, without --pr (it needs the pushed head)
            return Step("review", False, f"no review stamp for HEAD {self.head[:12]}",
                        f"review the branch, then brain review stamp HEAD --note FILE (or --findings N --fixed M; "
                        f"--pr N once pushed)", log)
        left = int(st.get("open", 0) or 0)
        if left:
            return Step("review", False, f"{left} finding(s) left open on {self.head[:12]}",
                        "fix them, commit, review the fix, then brain review stamp HEAD --note FILE (--pr N once "
                        "pushed)", log)
        return Step("review", True, f"reviewed: {st.get('findings', 0)} finding(s), {st.get('fixed', 0)} fixed"
                                    + (f" ({how})" if how else ""), log=log)

    def views(self) -> Step:
        if not (self.top / GRAPH).is_file():
            return Step("views", None, "no graph store")
        before = set(self._dirty())
        r, log = self._run("views", self._brain("--root", str(self.top), "refresh", "--offline", "--no-tidy"),
                           CHECK_TIMEOUT)   # a gate checks: tidy.auto's removals are refresh's own, not the gate's
        if not r.ok:
            return Step("views", False, f"brain refresh: {verdict.last_line(r.err, r.out) or f'exit {r.rc}'}",
                        "brain refresh (read its log), fix, then brain gate", log)
        changed = sorted(set(self._dirty()) - before)
        if changed:
            more = ", ..." if len(changed) > 3 else ""
            return Step("views", False, f"refresh rewrote {len(changed)} file(s) "
                                        f"({', '.join(x[3:] for x in changed[:3])}{more})",
                        "git add -A && git commit (the regenerated views), then brain gate", log)
        return Step("views", True, "views current, the store checked", log=log)

    def audit(self) -> Step:
        r, log = self._run("audit", self._brain("audit", "--diff", self.base, "--repo-dir", str(self.top),
                                                *(["--store", self.store] if self.store else [])), CHECK_TIMEOUT)
        scout = [x for x in r.out.splitlines() if x.startswith("scout:")]
        said = scout[-1] if scout else verdict.last_line(r.err, r.out)
        if not r.ok:
            return Step("audit", False, said or f"exit {r.rc}",
                        f"brain audit --diff {self.base}: fix its NEW and LEFT lines, then brain gate", log)
        return Step("audit", True, said, log=log)

    def public(self) -> Step:
        pub, slug = self.is_public(self.top)
        if not pub:
            return Step("public", None, "not a public repo")
        if self.stamp_valid(slug, self.head):
            return Step("public", True, f"{slug}: the stamp of {self.head[:12]} is valid")
        r, log = self._run("public", self._brain("check", "--public", "--history"), CHECK_TIMEOUT)
        if not r.ok:
            return Step("public", False, f"brain check --public: {verdict.last_line(r.out, r.err) or r.rc}",
                        "brain check --public --history (read its findings), fix them in a new commit, then brain "
                        "gate", log)
        return Step("public", True, f"{slug}: HEAD stamped", log=log)

    def tests(self) -> Step:
        cmd = self._brain("test", "--changed", self.base, "--repo-dir", str(self.top),
                          *(["--strict"] if self.strict else []), "--python", self.python,
                          *(["-n", self.workers] if self.workers else []))
        r, log = self._run("tests", cmd, TEST_TIMEOUT)
        s = verdict.pytest_summary(r.out + "\n" + r.err)
        counts = ", ".join(f"{n} {k}" for k, n in sorted(s.counts.items()))
        widened = "shadow mode: the whole suite is the answer" in r.err
        wide = "; widened: the CI runs the whole suite" if widened else ""
        if not r.ok:
            ids = ", ".join(s.failed[:5]) + (f" and {len(s.failed) - 5} more" if len(s.failed) > 5 else "")
            why = (f"{counts}: {ids}" if ids else counts) or verdict.last_line(r.err, r.out) or f"exit {r.rc}"
            return Step("tests", False, why, f"python -m pytest {' '.join(s.failed[:3]) or '<the failed tests>'} "
                                             f"(in the suite's folder; the log: {log}), fix, then brain gate", log)
        if "no test module to run" in r.err:
            return Step("tests", True, ("no test module selected" if widened else "no test module the change "
                                                                                  "touches") + wide, log=log)
        return Step("tests", True, (counts or "ran") + wide, log=log)

    # --- the run ---

    def run(self) -> Report:
        for name in STEPS:
            if name in self.skip:
                step = Step(name, None, ON_PURPOSE)
            else:
                try:
                    step = getattr(self, name.replace("-", "_"))()
                except (AuditError, OSError, ValueError) as exc:
                    step = Step(name, False, f"could not run: {exc}"[:verdict.DETAIL],
                                f"run the {name} step's command by hand (brain gate's docs), fix, then brain gate")
            self.report.steps.append(step)
            self.say(f"brain gate: {name}: " + {True: "ok", False: "FAILED", None: "skipped"}[step.ok]
                     + (f": {step.detail}" if step.detail else ""))
            if step.ok is False and self.fail_fast:
                break
        (self.folder / "verdict.json").write_text(json.dumps(self.report.to_json(), indent=1) + "\n",
                                                  encoding="utf-8", newline="\n")
        return self.report
