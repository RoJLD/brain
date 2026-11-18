"""The owner's answers, one writer per batch (wi-brain-answers-lane): the question tool's capture ties each answer to
the DDR it came from, and ``brain decision answer --captured`` records a batch in one PR.

Three machine-local ledgers under $BRAIN_HOME/ledger (never the repo):

- ``asked-<yyyy-mm>.jsonl``: each question ``brain decision batch`` printed for the question tool (its text, header and
  labels as the tool gets them, the DDR's id, labels and project), written by the command (:func:`remember`);
- ``answer-<yyyy-mm>.jsonl``: each answer the question tool returned to one of those questions, written by the capture
  hook (:func:`capture`): the DDR's id, the answer exactly as the tool returned it, the labels it names (the DDR's own,
  the ``(Recommandé)`` mark dropped), the owner's free text (``other``) and notes, the session and the tool call;
- ``answer-recorded-<yyyy-mm>.jsonl``: the captures ``--captured`` recorded, with their PR, and the ones it retired
  without writing them (``retired``: not answered, a label that names no option, older than the DDR's answer).

A question is tied to its DDR by the id a repeated question carries at its end, else by its text and header, else by
its header and labels (only a question this session's batch printed); a question that matches no printed one (asked
by hand) stays an ad-hoc DDR of the capture (brain.capture). Matching is exact (whitespace aside): a label is the
tool's, never a prefix of one. The tool returns a multiple choice as a list of labels; a question the owner did not
answer (they sent a message instead: the tool's placeholder, :data:`UNANSWERED_RE`) is captured as no answer at all.
A label the session shortened or reworded in the tool, which names no option of the DDR, is kept ``unmapped``, never
turned into the owner's free text: ``--captured`` refuses it.

``record_captured`` (``brain decision answer --captured``): the session's captured answers not recorded yet, written in
a worktree of the project's main checkout on a new branch from its default branch, the views refreshed (``brain
refresh``), committed, pushed, one PR opened, then merged with its retries (main moved: merge it, take its side of the
generated files, refresh again, push, retry). One writer per batch: the session that asked the owner records. A
capture older than the answer the DDR already holds is stale: never written, even with ``--again``, and retired; an
answer captured before a low-stakes deadline replaces the default taken meanwhile (the owner answered in time).
Each answer goes where its DDR lives (wi-brain-captured-in-branch): run in the asking session's own checkout (a checkout
of the project's repo on a branch other than the default one), an answer whose DDR only that checkout holds (asked on
its branch, not merged yet) is written, refreshed, committed on that branch and pushed, carried by that branch's own
PR; the others take the PR from the default branch, both in one run. A checkout with uncommitted changes is refused,
so the commit holds the answers alone, and a failure before that commit puts it back as it was.

``refusal`` is the other half of that rule: in an agent's session, ``brain decision answer`` (``--batch``, and ``brain
record ddr`` when it writes an answer) records
only an answer this session's own question tool captured; an answer relayed by a message is never recorded, the
session that receives it applies it and acknowledges it once the asking session recorded it (the mid-session announce
names it). The owner's own terminal records anything.

The part the capture hook runs is standard library only; the recording imports the engine lazily.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import faults, paths, secretscan, timing

ASKED, CAPTURED, RECORDED = "asked", "answer", "answer-recorded"
MARK_RE = re.compile(r"\s*\((?:recommandée?|recommended)\)\s*$", re.I)
ID_SUFFIX_RE = re.compile(r"\s*\((ddr-[a-z0-9-]+)\)\s*$")
# The question tool's placeholder for a question the owner did not answer (they sent a message instead), as Claude
# Code returns it: "[User did not answer this question — they sent a message instead. ...]".
UNANSWERED_RE = re.compile(r"^\s*\[user did not answer\b", re.I)
AGENT_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "BRAIN_AGENT_SESSION")   # as brain.vault
SESSION_ENV = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID")
RETRIES = 3
BRANCH = "claude/answers-{stamp}"


class AnswersError(Exception):
    pass


def _now() -> str:
    return faults.now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(text) -> str:
    return " ".join(str(text or "").split())


# --- the ledgers ---

def read(name: str, months: int = 2, since: str = "") -> list[dict]:
    """The records of one ledger, its last ``months`` monthly files, or every file from the month ``since`` (yyyy-mm)
    on when it is given."""
    out = []
    files = sorted(paths.ledger_dir().glob(f"{name}-[0-9][0-9][0-9][0-9]-[0-9][0-9].jsonl"))
    files = [f for f in files if f.stem[-7:] >= since[:7]] if since else files[-months:]
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    return out


def _append(name: str, recs: list[dict]) -> None:
    if not recs:
        return
    d = paths.ledger_dir()
    by_month: dict[str, list[dict]] = {}
    for r in recs:
        by_month.setdefault(r["at"][:7], []).append(r)
    for month, rows in by_month.items():   # one locked write per month file (brain.timing.append_lines)
        timing.append_lines(d / f"{name}-{month}.jsonl", rows)


# --- what brain decision batch printed ---

def remember(project: str, root: str | Path, batches: list[dict], at: str = "", session: str | None = None) -> int:
    """Write the questions of ``batches`` (brain.batch.build's) to the asked ledger, once each per session (the one
    the command runs in, CLAUDE_CODE_SESSION_ID, unless ``session`` is given); the count written."""
    at = at or _now()
    session = session_id() if session is None else session
    seen = {r.get("id") for r in read(ASKED)}
    out = []
    for b in batches:
        for ddr_id, q, e in zip(b["ids"], b["questions"], b["entries"]):
            labels = [o["label"] for o in q["options"]]
            key = json.dumps([project, ddr_id, q["question"], q["header"], labels] + ([session] if session else []),
                             ensure_ascii=False)
            rid = "aq-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
            if rid in seen:
                continue
            seen.add(rid)
            out.append({"v": 1, "id": rid, "at": at, "project": project, "root": str(root), "ddr": ddr_id,
                        "question": q["question"], "header": q["header"], "labels": labels,
                        "options": [o["label"] for o in e.get("options") or []], "multi": bool(q["multiSelect"]),
                        **({"session": session} if session else {})})
    _append(ASKED, out)
    return len(out)


def match(q: dict, asked: list[dict], session: str = "") -> dict | None:
    """The printed question a question of the tool is (the latest one), None when none is, or several DDRs are. The
    header-and-labels fallback looks only at the questions ``session``'s own batch printed: a question asked by hand
    elsewhere with the same header and labels is not tied to some DDR printed weeks ago."""
    text, head = _norm(q.get("question")), q.get("header") or ""
    labels = [o.get("label") for o in q.get("options") or [] if isinstance(o, dict)]
    m = ID_SUFFIX_RE.search(text)
    if m:
        cands = [r for r in asked if r.get("ddr") == m.group(1)]
    else:
        cands = [r for r in asked if _norm(r.get("question")) == text and r.get("header") == head]
        if not cands:
            cands = [r for r in asked if r.get("header") == head and r.get("labels") == labels
                     and session and r.get("session") == session]
    if len({r.get("ddr") for r in cands}) > 1:
        cands = [r for r in cands if r.get("labels") == labels]
    if not cands or len({r.get("ddr") for r in cands}) > 1:
        return None
    return max(cands, key=lambda r: r.get("at") or "")


def unanswered(raw) -> bool:
    """True when the tool's answer is none: empty, or its placeholder for a question the owner did not answer."""
    if isinstance(raw, (list, tuple)):
        return all(unanswered(r) for r in raw)
    return raw is None or not str(raw).strip() or bool(UNANSWERED_RE.match(str(raw)))


def resolve(asked: dict, q: dict, raw) -> tuple[list[str], str, list[str]]:
    """(the DDR labels the tool's answer names, the owner's free text, the tool's labels that name no DDR option): a
    label is the tool's exactly; a multiple choice is a list of labels (the tool's shape) or the labels joined by ', '
    (a label may hold ', '), the rest of it the owner's text. A tool label the session reworded so that it names no
    option of the DDR is ``unmapped``, never the owner's text."""
    tool = [o.get("label") for o in q.get("options") or [] if isinstance(o, dict) and o.get("label")]
    ddr_labels = asked.get("options") or []
    if tool == asked.get("labels") and len(tool) == len(ddr_labels):
        to_ddr = dict(zip(tool, ddr_labels))
    else:  # the session changed the labels: only one that is a DDR label once the mark is dropped
        to_ddr = {t: MARK_RE.sub("", t) for t in tool if MARK_RE.sub("", t) in ddr_labels}
    lost = {t for t in tool if t not in to_ddr}
    if isinstance(raw, (list, tuple)):
        items = [str(r) for r in raw if not unanswered(r)]
        picked = list(dict.fromkeys(to_ddr[r] for r in items if r in to_ddr))
        unmapped = [r for r in items if r in lost]
        rest = [r for r in items if r not in to_ddr and r not in lost]
        return picked, ", ".join(rest).strip(), unmapped
    raw = str(raw)
    if raw in to_ddr:
        return [to_ddr[raw]], "", []
    if raw in lost:
        return [], "", [raw]
    if not asked.get("multi"):
        return [], raw, []
    tokens, picked, rest, unmapped, i = raw.split(", "), [], [], [], 0
    while i < len(tokens):
        for j in range(len(tokens), i, -1):
            text = ", ".join(tokens[i:j])
            if text in to_ddr:
                picked.append(to_ddr[text])
            elif text in lost:
                unmapped.append(text)
            else:
                continue
            i = j
            break
        else:
            rest.append(tokens[i])
            i += 1
    return list(dict.fromkeys(picked)), ", ".join(rest).strip(), unmapped


def capture(q: dict, raw, notes, *, at: str, session: str, tool_use_id: str, index: int,
            asked: list[dict] | None = None) -> dict | None:
    """The capture hook's half: the answer to a question ``brain decision batch`` printed, written to the answer
    ledger (once per tool call); None when the question is not one of them (an ad-hoc question). An unanswered one
    (empty, or the tool's placeholder when the owner sent a message instead) is matched and writes nothing (``{}``).
    A multiple choice comes as a list of labels (the tool's shape) or as a string."""
    hit = match(q, read(ASKED) if asked is None else asked, session)
    if hit is None:
        return None
    if unanswered(raw):
        return {}
    choices, other, unmapped = resolve(hit, q, raw)
    raw = ", ".join(str(r) for r in raw if not unanswered(r)) if isinstance(raw, (list, tuple)) else str(raw)
    suffix = re.sub(r"[^a-z0-9]+", "-", (tool_use_id[-10:] or at).lower()).strip("-")
    rec = {"v": 1, "id": f"ans-{at[:10]}-{suffix}-{index}", "at": at, "ddr": hit["ddr"], "project": hit["project"],
           "root": hit["root"], "session": session or "unknown", "tool_use_id": tool_use_id,
           "question": q.get("question"), "header": q.get("header"), "answer": raw, "multi": bool(hit.get("multi"))}
    if choices:
        rec["choices"] = choices
    if other:
        rec["other"] = other
    if unmapped:
        rec["unmapped"] = unmapped
    if notes:
        rec["notes"] = str(notes)
    if rec["id"] not in {r.get("id") for r in read(CAPTURED)}:
        _append(CAPTURED, [secretscan.clean(rec)[0]])
    return rec


# --- who may record ---

def agent_session(env=None) -> bool:
    env = os.environ if env is None else env
    return any(env.get(v) for v in AGENT_ENV)


def session_id(env=None) -> str:
    env = os.environ if env is None else env
    return next((env[v] for v in SESSION_ENV if env.get(v)), "")


def captured_by(session: str) -> list[dict]:
    return [r for r in read(CAPTURED) if not session or r.get("session") == session]


def refusal(ddr_id: str, choices: list[str], other: str, env=None) -> str:
    """Why an answer may not be recorded here ('' when it may): in an agent's session, only an answer this session's
    question tool captured, the same choices and free text."""
    if not agent_session(env):
        return ""
    sid = session_id(env)
    for r in captured_by(sid) if sid else []:
        if r.get("ddr") == ddr_id and sorted(r.get("choices") or []) == sorted(choices or []) and \
                _norm(r.get("other")) == _norm(other):
            return ""
    return (f"{ddr_id}: this session's question tool did not capture this answer. An agent's session records only "
            "the answers its own question tool captured (brain decision answer --captured); an answer relayed by a "
            "message is never recorded: apply it, then brain decision ack once the session that asked has recorded "
            "it (the mid-session announce names it)")


# --- brain decision answer --captured ---

def refused(c: dict) -> str:
    """Why a capture is never recorded ('' when it may be): no answer, or a label that names no option."""
    if unanswered(c.get("answer")):
        return "not answered: the owner sent a message instead, never recorded"
    if c.get("unmapped"):
        return (f"the tool's label {', '.join(map(repr, c['unmapped']))} names no option of the DDR (a label the "
                "session shortened): not recorded as free text; the owner records it from their own terminal "
                f"(brain decision answer {c['ddr']} OPTION)")
    return ""


def unrecorded(session: str = "", project: str = "") -> list[dict]:
    """The captured answers not recorded yet (one per DDR: the latest), of ``session`` and ``project`` when given. A
    capture no later than one of the same DDR already recorded or retired is superseded; a question the owner did not
    answer is returned only when its DDR has no answer captured (``--captured`` then refuses it and retires it). The
    recorded ledger is read from the month of the oldest capture on, so that both windows match."""
    every = read(CAPTURED)
    by_id = {r.get("id"): r for r in every}
    mine = [r for r in every if not session or r.get("session") == session]
    since = min((r.get("at") or "" for r in mine), default="")[:7]
    done: set = set()
    high: dict[str, str] = {}
    for r in read(RECORDED, since=since) if since else []:
        done.add(r.get("id"))
        at = r.get("captured_at") or (by_id.get(r.get("id")) or {}).get("at") or ""
        if r.get("ddr") and at > high.get(r["ddr"], ""):
            high[r["ddr"]] = at
    latest: dict[str, dict] = {}
    for r in mine:
        if r.get("id") in done or (project and r.get("project") != project):
            continue
        at = r.get("at") or ""
        if at <= high.get(r.get("ddr"), ""):
            continue
        cur = latest.get(r.get("ddr"))
        real = not unanswered(r.get("answer"))
        if cur is None or (real, at) >= (not unanswered(cur.get("answer")), cur.get("at") or ""):
            latest[r["ddr"]] = r
    return sorted(latest.values(), key=lambda r: (r.get("at") or "", r["id"]))


def _run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and p.returncode:
        raise AnswersError(f"{' '.join(cmd[:4])}: {(p.stderr or p.stdout).strip()[:400]}")
    return p


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return _run(["git", "-C", str(cwd), *args], cwd, check)


def gh(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """The gh call (a test replaces it)."""
    return _run(["gh", *args], cwd, check=False)


def refresh(worktree: Path) -> int:
    """``brain refresh --offline --no-tidy`` in the worktree (a test replaces it); its exit code. The answers'
    worktree regenerates its views only: tidy.auto's removals are left to the owner's own refresh."""
    p = subprocess.run([sys.executable, "-m", "brain", "--root", str(worktree), "refresh", "--offline", "--no-tidy"],
                       cwd=str(worktree), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode:
        sys.stderr.write((p.stdout or "")[-2000:] + (p.stderr or "")[-2000:])
    return p.returncode


def _default_branch(root: Path) -> str:
    p = _git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD", check=False)
    name = p.stdout.strip().split("/", 1)[-1] if p.returncode == 0 and p.stdout.strip() else ""
    return name or "main"


def _body(caps: list[dict], owner: str, session: str) -> str:
    rows = [f"- `{c['ddr']}` ({c.get('header') or '?'}): {c['answer']}" + (f" — notes: {c['notes']}"
                                                                            if c.get("notes") else "")
            for c in caps]
    return (f"{owner}'s answers to {len(caps)} decision(s), through the question tool, as it returned them:\n\n"
            + "\n".join(rows) + f"\n\nRecorded by `brain decision answer --captured` from the capture of session "
            f"{session or 'unknown'} (one writer per batch); views refreshed by `brain refresh`. The sessions that "
            "own each decision apply it, then `brain decision ack ID --applied WHERE`.\n")


def _merge(worktree: Path, pr: str, base: str, branch: str, retries: int, wait: float) -> tuple[bool, list[str]]:
    """Merge the PR, retrying when main moved: merge it into the branch (its side of every conflicted file but the
    records, then the views refreshed again), push, wait, try again. (merged, what happened)."""
    log = []
    for attempt in range(retries + 1):
        p = gh(["pr", "merge", pr, "--merge"], worktree)
        if p.returncode == 0:
            log.append(f"merged{f' after {attempt} retry(ies)' if attempt else ''}")
            _git(worktree, "push", "-q", "origin", "--delete", branch, check=False)
            return True, log
        log.append(f"merge refused: {(p.stderr or p.stdout).strip()[:200]}")
        if attempt == retries:
            break
        _git(worktree, "fetch", "-q", "origin", base)
        m = _git(worktree, "merge", "--no-edit", f"origin/{base}", check=False)
        if m.returncode:
            conflicted = _git(worktree, "diff", "--name-only", "--diff-filter=U").stdout.split()
            if any(f.startswith("records/") for f in conflicted):
                _git(worktree, "merge", "--abort", check=False)
                raise AnswersError(f"{pr}: a record conflicts with {base} ({', '.join(conflicted)}): merge it by hand")
            for f in conflicted:
                _git(worktree, "checkout", "--theirs", "--", f)
            _git(worktree, "add", "-A")
            _git(worktree, "commit", "-q", "--no-edit")
        if refresh(worktree):
            raise AnswersError(f"{pr}: brain refresh failed after merging {base}: the worktree {worktree} is kept")
        _git(worktree, "add", "-A")
        if _git(worktree, "status", "--porcelain").stdout.strip():
            _git(worktree, "commit", "-q", "-m", f"Merge {base} into the answers: views refreshed")
        _git(worktree, "push", "-q", "origin", branch)
        log.append(f"merged {base} into {branch}, refreshed, pushed")
        time.sleep(wait * (attempt + 1))
    return False, log


def session_branch(root: Path, here: Path | None, base: str) -> tuple[Path, str] | None:
    """(the checkout, its branch) when ``here`` is in a checkout of ``root``'s repo on a branch other than ``base``
    (the asking session's worktree), else None."""
    if here is None or not Path(here).is_dir():
        return None
    p = _git(Path(here), "rev-parse", "--show-toplevel", check=False)
    top = Path(p.stdout.strip()) if p.returncode == 0 and p.stdout.strip() else None
    if top is None:
        return None
    mine, theirs = paths.main_checkout(top), paths.main_checkout(root)
    if mine is None or theirs is None or os.path.normcase(str(mine.resolve())) != os.path.normcase(
            str(theirs.resolve())):
        return None
    b = _git(top, "rev-parse", "--abbrev-ref", "HEAD", check=False).stdout.strip()
    return (top, b) if b and b not in ("HEAD", base) else None


def _where(root: Path, top: Path | None, c: dict, base: str) -> str:
    """Where a capture goes: ``refused`` (never recorded), ``here`` (the asking session's checkout ``top`` holds its
    DDR, the default branch does not: asked on that branch, not merged yet), ``main`` (the default flow, from the
    default branch), ``missing`` (neither seems to hold it: the default flow leaves it captured)."""
    from . import decisions, records
    if refused(c):
        return "refused"
    if top is not None:
        try:
            f, _ = decisions.find(top, c["ddr"], exact=True)
            rel = Path(f).resolve().relative_to(top.resolve()).as_posix()
        except (decisions.QueueError, ValueError):
            rel = ""
        if rel:
            return "main" if _on(root, base, rel) else "here"
    return "main" if _on(root, base, f"{records.RECORDS_DIR}/ddr/{c['ddr']}.yaml") else "missing"


def _on(root: Path, base: str, rel: str) -> bool:
    return _git(root, "cat-file", "-e", f"origin/{base}:{rel}", check=False).returncode == 0


def _split(root: Path, caps: list[dict], here: Path | None, base: str) -> tuple[tuple[Path, str] | None, list]:
    """(the asking session's checkout and branch, or None; each capture with where it goes, :func:`_where`)."""
    found = session_branch(root, here, base)
    return found, [(c, _where(root, found[0] if found else None, c, base)) for c in caps]


def plan(project, caps: list[dict], here: Path | None = None) -> list[tuple[dict, str]]:
    """Where each capture would go (``--dry-run``), after a fetch of origin (offline: its last state): each capture
    with what :func:`record_captured` would do with it, in words."""
    root = Path(project.root)
    _git(root, "fetch", "-q", "origin", check=False)
    base = _default_branch(root)
    found, where = _split(root, caps, Path.cwd() if here is None else here, base)
    branch = found[1] if found else ""
    words = {"refused": "retired, never recorded",
             "here": f"committed on {branch}, the branch that asked it (its own PR carries it)",
             "main": f"in one PR from {base}",
             "missing": f"left captured: {base} does not hold its DDR yet (record it from the checkout of the branch "
                        "that asked it, or once that branch is merged)"}
    return [(c, words[w]) for c, w in where]


class _Batch:
    """What one ``--captured`` run did, its two flows together: the captures retired or left, the PR's part (the
    default flow) and the asking branch's part."""

    def __init__(self, at: str):
        self.at = at
        self.skipped: list[str] = []
        self.missing: list[str] = []
        self.retired: list[dict] = []
        self.refusals: list[str] = []
        self.errors: list[str] = []
        self.pr = {"pr": "", "branch": "", "worktree": "", "recorded": [], "merged": False, "log": []}
        self.here: dict = {}

    def retire(self, c: dict, why: str) -> None:
        self.refusals.append(f"{c['ddr']} ({why})")
        self.retired.append({"v": 1, "id": c["id"], "at": self.at, "ddr": c["ddr"], "captured_at": c.get("at") or "",
                             "pr": "", "retired": why})

    def recorded(self) -> list[str]:
        return self.pr["recorded"] + self.here.get("recorded", [])

    def result(self) -> dict:
        return {**self.pr, "in_pr": self.pr["recorded"], "recorded": self.recorded(), "in_branch": self.here,
                "skipped": self.skipped, "missing": self.missing, "retired": [r["ddr"] for r in self.retired],
                "refused": self.refusals, "errors": self.errors}


def record_captured(project, caps: list[dict], *, owner: str, session: str = "", merge: bool = True,
                    retries: int = RETRIES, wait: float = 5.0, at: str = "", again: bool = False,
                    here: Path | None = None) -> dict:
    """Record ``caps`` (one project's), each where its DDR lives, in one run. ``here`` (default: the current folder)
    is the asking session's checkout: a capture whose DDR only it holds (asked on its branch, not on the default one
    yet) is recorded on that branch (:func:`_record_in_branch`); every other one by the default flow
    (:func:`_record_from_main`): a worktree on a new branch from the default one, refreshed, committed, pushed, one
    PR, merged with its retries, read from the default branch so that a DDR answered there meanwhile, a stale capture
    or a default are judged on its own copy. A capture names its DDR by its full id: one neither holds is left
    captured and said (``missing``), and a DDR whose id merely contains it is never answered in its place. A capture
    with no answer (the owner sent a message instead) or with a label that names no option is refused and retired;
    one older than the answer the DDR holds is stale: retired, never written (``again`` included); one of a DDR no
    longer pending is left (``skipped``; ``again``: its answer replaced, a default reversed); one captured before a
    low-stakes DDR's deadline replaces the default taken meanwhile. The result holds both parts (``in_pr``, the PR's
    fields; ``in_branch``) and ``errors``: what failed once something was recorded (the asking branch's part, its
    push); with nothing recorded, the failure is raised."""
    if not caps:
        raise AnswersError("no captured answer to record")
    root = Path(project.root)
    out = _Batch(at or _now())
    _git(root, "fetch", "-q", "origin")
    base = _default_branch(root)
    found, where = _split(root, caps, Path.cwd() if here is None else here, base)
    mine = [c for c, w in where if w == "here"]
    others = [c for c, w in where if w in ("main", "missing")]
    if mine:
        _refuse_dirty(*found)
    try:
        for c, w in where:
            if w == "refused":
                out.retire(c, refused(c))
        if others:
            _record_from_main(root, others, out, owner=owner, session=session, merge=merge, retries=retries,
                              wait=wait, again=again, base=base)
        if mine:
            try:
                _record_in_branch(found[0], found[1], mine, out, owner=owner, again=again, base=base)
            except AnswersError as exc:
                if not out.recorded():
                    raise
                out.errors.append(str(exc))
    finally:
        _append(RECORDED, out.retired)
    if not out.recorded():
        raise AnswersError("nothing to record: " + "; ".join(
            out.refusals + out.skipped + [f"{m} (not on {base} yet)" for m in out.missing]))
    return out.result()


def _record_from_main(root: Path, caps: list[dict], out: _Batch, *, owner: str, session: str, merge: bool,
                      retries: int, wait: float, again: bool, base: str) -> None:
    """The default flow: ``caps`` written in a worktree of ``root`` on a new branch from ``base``, refreshed,
    committed, pushed, one PR opened (the captures marked recorded), merged with its retries. Nothing written: the
    worktree and its branch removed, nothing pushed."""
    stamp = out.at[:16].replace("-", "").replace(":", "").replace("T", "-")
    branch = BRANCH.format(stamp=stamp)
    worktree = root / ".claude" / "worktrees" / f"answers-{stamp}"
    _git(root, "worktree", "add", "-q", "-b", branch, str(worktree), f"origin/{base}")
    written: list[dict] = []
    try:
        written = _write_answers(worktree, caps, owner, again, out)
        title = _commit_and_push(worktree, branch, written, owner) if written else ""
    finally:
        if not written or not _git(root, "log", "-1", "--format=%H", f"origin/{branch}", check=False).stdout.strip():
            _git(root, "worktree", "remove", "--force", str(worktree), check=False)
            _git(root, "branch", "-D", branch, check=False)
    if not written:
        return
    p = gh(["pr", "create", "--base", base, "--head", branch, "--title", title, "--body",
            _body(written, owner, session)], worktree)
    if p.returncode:
        raise AnswersError(f"gh pr create: {(p.stderr or p.stdout).strip()[:300]} (branch {branch} is pushed)")
    url = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ""
    _append(RECORDED, [{"v": 1, "id": c["id"], "at": out.at, "ddr": c["ddr"], "captured_at": c.get("at") or "",
                        "pr": url, "branch": branch} for c in written])
    merged, log = (_merge(worktree, url, base, branch, retries, wait) if merge else (False, []))
    if merged:
        _git(root, "worktree", "remove", "--force", str(worktree), check=False)
        _git(root, "branch", "-D", branch, check=False)
    out.pr = {"pr": url, "branch": branch, "worktree": str(worktree), "recorded": [c["ddr"] for c in written],
              "merged": merged, "log": log}


def _commit_and_push(worktree: Path, branch: str, written: list[dict], owner: str) -> str:
    """The default flow's worktree, its answers written: refreshed, committed, pushed; the PR's title."""
    if refresh(worktree):
        raise AnswersError(f"brain refresh failed in {worktree}: fix it there, or remove the worktree")
    _git(worktree, "add", "-A")
    heads = ", ".join(dict.fromkeys(c.get("header") or c["ddr"] for c in written))
    title = f"{owner}'s answers: {heads}"[:120]
    _git(worktree, "commit", "-q", "-m", f"{title} (question tool, captured)")
    _git(worktree, "push", "-q", "-u", "origin", branch)
    return title


def _write_answers(where: Path, caps: list[dict], owner: str, again: bool, out: _Batch) -> list[dict]:
    """Each capture's answer written in the checkout ``where``; the captures written (the ones left go to ``out``:
    skipped, missing; a refused or stale one retired)."""
    from . import decisions  # the engine (YAML), not the hook's part
    written = []
    for c in caps:
        why = refused(c)
        if why:
            out.retire(c, why)
            continue
        try:
            _, ddr = decisions.find(where, c["ddr"], exact=True)
        except decisions.QueueError:
            out.missing.append(c["ddr"])
            continue
        replace = again
        if ddr.get("status") != "pending":
            if not _not_pending(c, ddr, again, out):
                continue
            replace = True
        decisions.answer(where, c["ddr"], c.get("choices") or [], other=c.get("other") or "",
                         notes=c.get("notes") or "", by=owner, via="ask-tool", at=c["at"], again=replace)
        written.append(c)
    return written


def _not_pending(c: dict, ddr: dict, again: bool, out: _Batch) -> bool:
    """A capture of a DDR no longer pending: True when it is written anyway (its answer replaced: a default taken
    after the owner answered yields, or ``again``), False when it is left (stale: retired; else skipped)."""
    from . import defaults
    ans, dflt = ddr.get("answer") or {}, ddr.get("default") or {}
    if ddr.get("status") == "answered" and defaults.by_default(ddr) and dflt.get("after") and \
            defaults.before(c["at"], dflt["after"]):
        return True   # the owner answered before the deadline: the default taken meanwhile yields
    if ans.get("at") and not defaults.before(ans["at"], c["at"]):
        out.retire(c, f"answered at {ans['at']}, not before this capture: stale, retired")
        return False
    if not again:
        out.skipped.append(f"{c['ddr']} ({ddr.get('status')})")
        return False
    return True


def _refuse_dirty(top: Path, branch: str) -> None:
    if _git(top, "status", "--porcelain").stdout.strip():
        raise AnswersError(f"{top} ({branch}) holds uncommitted changes: commit them first, so that the answers' "
                           "commit holds the answers alone (its DDRs are on this branch only)")


def _restore(top: Path) -> None:
    """The asking checkout put back as it was before the answers were written: it was clean then (the dirty check),
    so what differs from its HEAD now is ours: the tracked files reset, the new untracked ones removed (the ignored
    ones, never ours to judge, left)."""
    _git(top, "reset", "-q", "--hard", "HEAD", check=False)
    _git(top, "clean", "-fdq", check=False)


def _push(top: Path, branch: str, base: str) -> str:
    """Push the asking branch: to its upstream when it has one other than the default branch (a local name may track
    another, its PR's head), else to origin under its own name, set as its upstream. '' once pushed, else git's
    message."""
    remote = _git(top, "config", f"branch.{branch}.remote", check=False).stdout.strip()
    ref = _git(top, "config", f"branch.{branch}.merge", check=False).stdout.strip()
    if remote and remote != "." and ref and ref != f"refs/heads/{base}":
        cmd = ["push", "-q", remote, f"HEAD:{ref}"]
    else:
        cmd = ["push", "-q", "-u", "origin", branch]
    p = _git(top, *cmd, check=False)
    return "" if p.returncode == 0 else ((p.stderr or p.stdout).strip()[:300] or f"git push exited {p.returncode}")


def _record_in_branch(top: Path, branch: str, caps: list[dict], out: _Batch, *, owner: str, again: bool,
                      base: str) -> None:
    """``caps``, whose DDRs only the asking session's branch holds (wi-brain-captured-in-branch), written in its
    checkout ``top`` (clean: :func:`_refuse_dirty` ran first), refreshed, committed and pushed; that branch's PR
    carries them, so none is opened or merged here. Any failure before the commit puts the checkout back as it was
    (:func:`_restore`) and raises; a failed push keeps the commit and goes to ``out.errors``."""
    from . import decisions
    try:
        written = _write_answers(top, caps, owner, again, out)
        if not written:
            return
        if refresh(top):
            raise AnswersError(f"brain refresh failed in {top}")
        _git(top, "add", "-A")
        heads = ", ".join(dict.fromkeys(c.get("header") or c["ddr"] for c in written))
        _git(top, "commit", "-q", "-m", f"{owner}'s answers: {heads}"[:120] + " (question tool, captured, in branch)")
    except Exception as exc:
        _restore(top)
        if isinstance(exc, (AnswersError, decisions.QueueError, OSError)):
            raise AnswersError(f"nothing recorded on {branch}: {exc} ({top} is put back as it was)") from exc
        raise
    _append(RECORDED, [{"v": 1, "id": c["id"], "at": out.at, "ddr": c["ddr"], "captured_at": c.get("at") or "",
                        "pr": "", "branch": branch} for c in written])
    failed = _push(top, branch, base)
    if failed:
        out.errors.append(f"not pushed: {failed}: the answers are committed on {branch} in {top}; push it yourself")
    out.here = {"branch": branch, "worktree": str(top), "recorded": [c["ddr"] for c in written],
                "pushed": not failed}
