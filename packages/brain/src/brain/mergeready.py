"""``brain merge-ready <pr>``: the merge gate's question, at zero token (wi-brain-merge-gate; RETRO-7 of 2026-11-03;
the lesson les-brain-stale-base-ci). Every check runs, and the answer is exit 0 or the list of what blocks:

- **open**: the PR is open, not a draft, and GitHub does not see a conflict;
- **fresh**: the base and the PR's head fetched again; main did not move, since the merge base, under a file the PR
  touches (a green CI on a stale base is not the merged tree: merge main, the CI runs again); a PR behind main on
  other files only is fresh;
- **merge-check**: ``brain merge-check`` on the head against the merge base: nothing the base brought up to it is lost
  (its lines in the journals, decision logs, edge files and CHANGELOGs, its nodes), a head that merged an older base
  included; a no-op for a head that merged nothing;
- **ci**: every check of the head completed green (success, neutral or skipped); one running or failed blocks. A
  repo whose config.json says it has no CI (``merge.repos.<owner/name>.ci: false``) and whose head reports no check
  blocks here with a check marked :data:`LOCAL`: the merger's own local checks (brain ship: the views regenerated or
  the store checked, the targeted tests) answer it, never ``brain merge-ready`` alone;
- **review**: ``brain review stamp`` recorded the review of this head, with no finding left open; a PR whose every
  file a glob of ``merge.repos.<owner/name>.review_exempt`` covers (records, docs, views: the review-every-pr rule
  asks code PRs only) passes without one (:func:`review_exempt`);
- **public**: for a public repo (config.json ``public.repos``), ``brain check --public --history`` stamped this head
  and the stamp is valid now (the push guard's question);
- **body**: the PR's title and body hold nothing ``brain check --public`` refuses (a private term, a secret, an
  address); public rules that do not load block too. For a private repo only a secret blocks: its PR may name its
  owner, projects and hosts;
- **pins**: each pinned decision the change touches (brain.pins) is kept or overridden in the PR body: ``Keeps <id or
  alias>`` for one in force, ``Overrides <id or alias>: <why>`` for one a later ADR supersedes (in a public repo's PR,
  its alias: ``brain adr pin --alias``, else ``pin-<8 hex>``).

A green answer writes the stamp ``<BRAIN_HOME>/merge-ready/<owner>/<repo>/<head sha>.json`` (what a merge guard
will ask; a push after it is a new head) and names the head to merge: ``gh pr merge N --match-head-commit <sha>``
refuses a head pushed since. gh reads the PR (``gh pr view --json``, run in the checkout); the repo is ``--slug``,
the remote's, else the PR's URL's.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config, mergecheck, paths, public, resume, review
from .inventory import AuditError, git

FOLDER = "merge-ready"
FIELDS = "number,state,isDraft,mergeable,headRefName,headRefOid,baseRefName,title,body,statusCheckRollup,url"
GH_TIMEOUT = 120
GREEN = {"SUCCESS", "NEUTRAL", "SKIPPED"}
LOCAL = "local"   # a check's key: a block the merger's own local checks answer (brain ship), not this gate


class GateError(Exception):
    pass


@dataclass
class Gate:
    pr: int
    slug: str
    head: str = ""
    base: str = ""
    checks: list[dict] = field(default_factory=list)   # {"check", "ok", "detail"}

    def add(self, check: str, ok: bool, detail: str, local: bool = False) -> None:
        self.checks.append({"check": check, "ok": ok, "detail": detail, **({LOCAL: True} if local else {})})

    @property
    def ready(self) -> bool:
        return bool(self.checks) and all(c["ok"] for c in self.checks)

    @property
    def blocks(self) -> list[dict]:
        return [c for c in self.checks if not c["ok"]]

    def to_json(self) -> dict:
        return {"pr": self.pr, "repo": self.slug, "head": self.head, "base": self.base, "ready": self.ready,
                "checks": self.checks}


def gh_view(pr: str, slug: str, cwd: Path | None = None) -> dict:
    """The PR as ``gh pr view --json`` gives it, gh run in the checkout (``cwd``) when no slug names the repo."""
    exe = shutil.which("gh")
    if not exe:
        raise GateError("gh is not on the PATH")
    try:
        r = subprocess.run([exe, "pr", "view", str(pr), *(["--repo", slug] if slug else []), "--json", FIELDS],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=cwd,
                           timeout=GH_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError(f"gh pr view {pr}: {exc}") from None
    if r.returncode != 0:
        raise GateError(f"gh pr view {pr}: {(r.stderr or r.stdout).strip()[:300]}")
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise GateError(f"gh pr view {pr}: not JSON: {r.stdout.strip()[:200]}") from None


def slug_of_url(url: str) -> str:
    """``owner/name`` of a PR's URL (https://github.com/owner/name/pull/N), else ''."""
    m = re.search(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/pull/", url or "")
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def _fetch(repo: Path, remote: str, base: str, pr: int, branch: str) -> None:
    """The base (into its remote-tracking ref, whatever the remote's refspec) and the PR's head fetched again (its
    pull ref, else its branch)."""
    git(repo, "fetch", "--quiet", remote, f"+refs/heads/{base}:refs/remotes/{remote}/{base}")
    try:
        git(repo, "fetch", "--quiet", remote, f"+refs/pull/{pr}/head")
    except AuditError:
        git(repo, "fetch", "--quiet", remote, branch)


def _has(repo: Path, sha: str) -> bool:
    return bool(sha) and bool(git(repo, "cat-file", "-t", sha, allow=(0, 1, 128)).strip() == "commit")


def _names(repo: Path, a: str, b: str) -> set[str]:
    """The paths changed from ``a`` to ``b``, a rename as both its old and its new path."""
    return set(git(repo, "diff", "--name-only", "--no-renames", "-z", a, b).split("\0")) - {""}


def stale_files(repo: Path, base_sha: str, head: str) -> tuple[str, list[str]]:
    """(the merge base, the files main changed since it that the PR also changes)."""
    mb = git(repo, "merge-base", base_sha, head, allow=(0, 1)).strip()
    if not mb:
        raise GateError(f"no merge base between the base {base_sha[:8]} and the head {head[:8]}")
    return mb, sorted(_names(repo, mb, base_sha) & _names(repo, mb, head))


def _check_state(c: dict) -> str:
    """ok, running or failed: a check run by its status and conclusion, a commit status by its state."""
    if c.get("__typename") == "StatusContext":
        state = str(c.get("state") or "")
        return "running" if state in ("PENDING", "EXPECTED") else "ok" if state == "SUCCESS" else "failed"
    if str(c.get("status") or "") != "COMPLETED":
        return "running"
    return "ok" if str(c.get("conclusion") or "") in GREEN else "failed"


def ci(rollup: list[dict]) -> tuple[bool, str]:
    """(green, what is not): every check completed with success, neutral or skipped."""
    if not rollup:
        return False, "no check reported on the head"
    by: dict[str, list[str]] = {"ok": [], "running": [], "failed": []}
    for c in rollup:
        name = c.get("name") or c.get("context") or "?"
        state = _check_state(c)
        by[state].append(name if state != "failed" else f"{name} ({str(c.get('conclusion') or c.get('state') or '?').lower()})")
    if by["failed"] or by["running"]:
        return False, "; ".join(f"{k}: {', '.join(v)}" for k, v in by.items() if k != "ok" and v)
    return True, f"{len(rollup)} check(s) green"


def repo_settings(slug: str, cfg: config.Config) -> dict:
    """config.json ``merge.repos``'s entry for the repo ``slug`` (owner/name, any case); {} when it has none."""
    merge = cfg.data.get("merge") if isinstance(cfg.data.get("merge"), dict) else {}
    repos = merge.get("repos") if isinstance(merge.get("repos"), dict) else {}
    want = (slug or "").lower()
    return next((v for k, v in repos.items() if str(k).lower() == want and isinstance(v, dict)), {})


def has_ci(slug: str, cfg: config.Config) -> bool:
    """False only when config.json says so (``merge.repos.<slug>.ci: false``): a repo has a CI unless told."""
    return repo_settings(slug, cfg).get("ci") is not False


def no_ci_detail(slug: str) -> str:
    return (f"no CI: config.json merge.repos.{slug}.ci is false; the merger's local checks stand for it (brain ship: "
            "brain refresh or brain check, the targeted tests)")


def answer_local(g: Gate, head: str) -> None:
    """The checks of ``g`` marked :data:`LOCAL` (a repo that declares no CI) answered by the merger's own local
    checks, which passed on ``head`` before it calls this (brain.ship): each becomes ok, saying so."""
    for c in g.checks:
        if c.get(LOCAL) and not c["ok"]:
            c.update(ok=True, detail=f"no CI declared: the merger's local checks passed on {head[:8]} (the views or "
                                     "the store checked, the targeted tests)")


def review_exempt(slug: str, cfg: config.Config, files) -> str:
    """Why the PR of ``files`` needs no review stamp: every file matches a glob of config.json
    ``merge.repos.<slug>.review_exempt`` (records, docs, views: the review-every-pr rule asks code PRs only); '' when
    it needs one (no glob, no file, or a file no glob covers: a code PR, fail closed)."""
    globs = repo_settings(slug, cfg).get("review_exempt")
    globs = [x for x in globs if isinstance(x, str) and x] if isinstance(globs, list) else []
    files = sorted(files)
    if not globs or not files:
        return ""
    from .boundary import glob_regex
    rx = [glob_regex(x) for x in globs]
    if any(not any(r.match(f) for r in rx) for f in files):
        return ""
    return (f"n/a: {len(files)} file(s), each under merge.repos.{slug}.review_exempt (records, docs or views): the "
            "review is asked of code PRs only")


def stamp_path(slug: str, head: str) -> Path:
    owner, _, name = slug.partition("/")
    return paths.brain_home() / FOLDER / owner.lower() / name.lower() / f"{head}.json"


def stamp(g: Gate, together: dict | None = None) -> Path:
    """The head's stamp; ``together`` (brain merge-ready --with): the PRs it was checked with, the order, the tests."""
    f = stamp_path(g.slug, g.head)
    f.parent.mkdir(parents=True, exist_ok=True)
    rec = {"v": 1, "pr": g.pr, "repo": g.slug, "head": g.head, "base": g.base,
           "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "checks": [c["check"] for c in g.checks]}
    if together:
        rec["together"] = together
    f.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8", newline="\n")
    return f


def _open(g: Gate, data: dict) -> None:
    state, draft, conflict = data.get("state"), data.get("isDraft"), data.get("mergeable") == "CONFLICTING"
    g.add("open", state == "OPEN" and not draft and not conflict,
          str(state).lower() + (", a draft" if draft else "") + (", a conflict with the base" if conflict else ""))


def _fresh(g: Gate, repo: Path, base_ref: str) -> str:
    """The fresh check; the merge base of the base and the head."""
    base_sha = git(repo, "rev-parse", "--verify", f"{base_ref}^{{commit}}").strip()
    mb, stale = stale_files(repo, base_sha, g.head)
    if stale:
        more = " ..." if len(stale) > 8 else ""
        why = (f"{base_ref} moved under {len(stale)} file(s) the PR touches: {', '.join(stale[:8])}{more}; merge it, "
               "the CI runs again")
    else:
        why = f"behind {base_ref} on other files only" if mb != base_sha else f"up to date with {base_ref}"
    g.add("fresh", not stale, why)
    return mb


def _merge_check(g: Gate, repo: Path, mb: str) -> None:
    """brain merge-check on the head against the merge base: what the base brought up to it is not lost (a head that
    merged an older base too); a no-op for a head that merged nothing."""
    try:
        project = resume.project_for(repo)
    except (OSError, ValueError):
        project = None
    r = mergecheck.check(repo, project if project and project.registered else None, mb, fetch=False, head=g.head)
    lost = mergecheck.failed(r)
    g.add("merge-check", not lost, f"{len(r['lost'])} line(s) or node change(s) and {len(r['lost_ids'])} node id(s) "
                                   "of the base lost" if lost else "nothing the base brought is lost")


def carried_review(repo: Path, head: str, base_sha: str) -> tuple[dict | None, str]:
    """(the review stamp ``head`` carries, how) when ``head`` is only the base merged into a reviewed head: a merge
    commit of two parents, the first one stamped, the second one on the base (``base_sha`` or before it), and its tree
    git's own merge of the two (the repo's merge driver, nothing resolved by hand: no conflict, no file changed after
    the merge). (None, '') otherwise: such a head needs its own stamp."""
    import tempfile

    from . import inventory, mergetogether  # mergetogether imports this module
    try:
        parents = git(repo, "rev-list", "--parents", "-n", "1", head).split()[1:]
    except AuditError:
        return None, ""
    if len(parents) != 2:
        return None, ""
    ours, theirs = parents
    st = review.check(ours)
    if not st or inventory._run_git(repo, ["merge-base", "--is-ancestor", theirs, base_sha])[0] != 0:
        return None, ""
    try:
        with tempfile.TemporaryDirectory(prefix="brain-carry-") as d:
            attrs = Path(d) / "attributes"
            attrs.write_text(mergetogether._attributes(repo, theirs), encoding="utf-8")
            tree, conflicts = mergetogether.merge_tree(repo, ours, theirs, mergetogether._driver(repo), attrs)
        mine = git(repo, "rev-parse", f"{head}^{{tree}}").strip()
    except (AuditError, GateError, OSError):
        return None, ""
    if conflicts or not tree or tree != mine:
        return None, ""
    return st, f"carried from {ours[:8]}: the head only merges the base into it, as git merges it"


def _review(g: Gate, repo: Path | None = None, base_sha: str = "", exempt: str = "") -> None:
    if exempt:   # a records, docs or views PR: no stamp asked (review_exempt)
        g.add("review", True, exempt)
        return
    st, how = review.check(g.head), ""
    if not st and repo is not None and base_sha:
        st, how = carried_review(repo, g.head, base_sha)
    left = int((st or {}).get("open") or 0)
    if not st:
        g.add("review", False, "no review stamp for the head (brain review stamp)")
    else:
        g.add("review", not left, f"{left} finding(s) left open" if left else
              f"reviewed: {st.get('findings', 0)} finding(s), {st.get('fixed', 0)} fixed" + (f" ({how})" if how else ""))


def _pins(g: Gate, repo: Path, data: dict, remote: str = "origin") -> None:
    """Each pinned decision the change touches kept or overridden in the PR body (brain.pins, wi-brain-decision-pins)."""
    try:
        touched, blocks = review.pins_gate(repo, f"{remote}/{g.base or 'main'}", g.head,
                                           str(data.get("body") or ""))
    except Exception as exc:   # an unreadable log or pins file blocks this check, never the gate's run
        g.add("pins", False, f"the pins could not be read: {exc}")
        return
    g.add("pins", not blocks, "; ".join(blocks[:3]) if blocks else
          f"{len(touched)} pinned decision(s) touched, each kept or overridden" if touched else "no pinned decision "
          "touched")


def _public(g: Gate, data: dict, cfg: config.Config) -> None:
    pub = public.is_public(g.slug, cfg)
    if pub:
        why = public.stamp_refusal(g.slug, g.head, cfg)
        g.add("public", not why, f"the head {why} (brain check --public --history)" if why else "the head is stamped")
    else:
        g.add("public", True, "n/a: not a public repo")
    rules = public.rules(cfg)
    text = [str(data.get("title") or ""), *str(data.get("body") or "").splitlines()]
    found = public.scan_lines("PR title and body", enumerate(text), rules)   # line 0: the title
    if not pub:   # a private repo's PR may name its owner, projects and hosts: a secret alone blocks
        found = [f for f in found if f.check == "secret"]
    if rules.errors and pub:
        g.add("body", False, "the public rules do not load: " + "; ".join(rules.errors[:3]))
    else:
        g.add("body", not found, "; ".join(f"{'title' if f.line == 0 else f'body line {f.line}'}: {f.what}"
                                           for f in found[:5]) if found else
              "nothing private" if pub else "no secret (a private repo: names allowed)")


def _fetched(repo: Path, remote: str, g: Gate, branch: str, fetch: bool) -> None:
    """The base and the head fetched (unless ``fetch`` is off); the head must then be here."""
    if fetch:
        try:
            _fetch(repo, remote, g.base, g.pr, branch)
        except AuditError as exc:
            raise GateError(f"git fetch: {exc}") from None
    if not _has(repo, g.head):
        raise GateError(f"the head {g.head[:8] or '?'} is not in {repo} after the fetch")


def gate(repo: Path, pr: str, slug: str = "", remote: str = "", fetch: bool = True, view=gh_view,
         cfg: config.Config | None = None) -> Gate:
    """Every check of the PR ``pr`` of the repo checked out at ``repo`` (``slug``: owner/name, default the remote's)."""
    cfg = cfg or config.load()
    remote = remote or "origin"
    slug = slug or public.repo_slug(git(repo, "remote", "get-url", remote, allow=(0, 2)).strip())
    data = view(pr, slug, repo)
    slug = slug or slug_of_url(str(data.get("url") or ""))
    if not slug:
        raise GateError(f"the GitHub repo of PR {pr} is unknown (--slug OWNER/NAME)")
    g = Gate(int(data.get("number") or 0), slug, str(data.get("headRefOid") or ""),
             str(data.get("baseRefName") or ""))
    _open(g, data)
    _fetched(repo, remote, g, str(data.get("headRefName") or ""), fetch)
    mb = _fresh(g, repo, f"{remote}/{g.base}")
    _merge_check(g, repo, mb)
    rollup = data.get("statusCheckRollup") or []
    if not rollup and not has_ci(slug, cfg):   # no CI declared: the merger's local checks answer it (LOCAL)
        g.add("ci", False, no_ci_detail(slug), local=True)
    else:
        g.add("ci", *ci(rollup))
    _review(g, repo, git(repo, "rev-parse", "--verify", f"{remote}/{g.base}^{{commit}}", allow=(0, 128)).strip(),
            review_exempt(slug, cfg, _names(repo, mb, g.head)))
    _public(g, data, cfg)
    _pins(g, repo, data, remote)
    return g


def lines(g: Gate) -> list[str]:
    """The answer in text; a ready one names the full head to merge, so that no later push is merged unchecked."""
    out = [f"merge-ready {g.slug}#{g.pr} at {g.head[:8]} onto {g.base}: "
           + (f"READY: gh pr merge {g.pr} --match-head-commit {g.head}" if g.ready else f"{len(g.blocks)} block(s)")]
    out += [f"  {'ok   ' if c['ok'] else 'BLOCK'} {c['check']:<11} {c['detail']}" for c in g.checks]
    return out
