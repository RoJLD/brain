"""Action records (AR) from git and gh commands: parse the command, ask the local repo (never the network), build
the AR. Used live by the PostToolUse hook and afterwards on transcripts (``brain record ar --from-transcript``).

What counts as evidence:
- commit: HEAD of the resolved repo, committed less than 15 minutes before the hook runs; on a transcript (the tool
  output rarely shows the SHA: ``git commit -q``), the one commit of the repo's history whose committer date falls
  within the tool call and whose subject is written in the command;
- push: the refs git printed (``src -> dst``), the tool's ``gitOperation.push``, or GitHub's
  ``remote: .../pull/new/<branch>`` line; a command that only mentions ``git push`` (in a commit message, say)
  records nothing;
- pull request: the PR URL gh printed, the tool's ``gitOperation.pr``, or the number given to ``gh pr merge``;
- tag: a ``git tag <name>`` that creates a tag;
- ADR: a ``## YYYY-MM-DD — title`` heading the commit added to notes/decisions.md or notes/scientific_decisions.md.
The repo is the command's ``git -C <dir>`` or last ``cd <dir>``, else the hook's cwd. On a transcript, a folder that
is gone (a removed worktree) is replaced by the repo of its nearest existing parent, and what only the local repo
could tell (a push's SHA, a repo name) is left out rather than read from today's state.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import diffs, secretscan
from .transcript import iso, iter_records, parse_ts

COMMIT_MAX_AGE_S = 900
_SEP_RE = re.compile(r"&&|\|\||;|\||\n")
_ASSIGN_RE = re.compile(r"^\s*(?:export\s+|\$env:)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\"[^\"]*\"|'[^']*'|\S+)\s*$")
_CD_RE = re.compile(r"^\s*(?:cd|pushd|Set-Location|Push-Location|sl)\s+(?:-Path\s+|-LiteralPath\s+)?(\"[^\"]*\"|'[^']*'|\S+)\s*$", re.I)
_GIT_RE = re.compile(
    r"^\s*(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*git((?:\s+(?:-C\s+(?:\"[^\"]*\"|'[^']*'|\S+)|-c\s+\S+|--no-pager|--git-dir=\S+|--work-tree=\S+))*)\s+(commit|push|tag)\b(.*)$"
)
_GIT_C_RE = re.compile(r"-C\s+(\"[^\"]*\"|'[^']*'|\S+)")
_GH_RE = re.compile(r"^\s*gh\s+pr\s+(create|merge)\b(.*)$")
_PR_URL_RE = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")
_REF_RE = re.compile(r"^\s*[+*-]?\s*(\[[^\]]+\]|[0-9a-f]{7,40}\.\.\.?([0-9a-f]{7,40}))\s+(\S+)\s+->\s+(\S+)", re.M)
_TO_RE = re.compile(r"^To\s+(\S+)", re.M)
_ESCAPED_RE = re.compile(r"\\([\\\"`$])")
_REMOTE_RE = re.compile(r"^(?:(?!file:)[a-z][a-z0-9+.\-]*://[^/\s]+/|[\w.-]+@[\w.-]+:/?)(?:[\w.-]+/)*?"
                        r"([\w.-]+/[\w.-]+?)(?:\.git)?/?$")
_PULL_NEW_RE = re.compile(r"^remote:\s+https://github\.com/([\w.-]+/[\w.-]+)/pull/new/(\S+)", re.M)
_ADR_HEAD_RE = re.compile(r"^\+##\s+(\d{4}-\d{2}-\d{2})\s*[—:\-]*\s*(.*?)\s*$")
_NODE_RE = re.compile(r"^- \{id:\s*([A-Za-z0-9_.-]+)")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slug(text: str, maxlen: int = 48) -> str:
    """research_graph's slug (``research_graph.sync._slug``): ADR ids must match the ones it generates."""
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:maxlen].strip("-") or "entry"


def _unquote(s: str) -> str:
    s = s.strip()
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'" else s


def _expand(word: str, env: dict[str, str]) -> str:
    def sub(m):
        name = m.group(1) or m.group(2) or m.group(3)
        return env.get(name, os.environ.get(name, m.group(0)))
    return re.sub(r"\$\{([A-Za-z_]\w*)\}|\$env:([A-Za-z_]\w*)|\$([A-Za-z_]\w*)", sub, word)


def norm_dir(word: str, base: str | Path | None, env: dict[str, str] | None = None,
             exists: bool = True) -> Path | None:
    """A folder named in a command, made absolute against ``base``; None when it cannot be resolved (or, with
    ``exists``, is not there)."""
    p = _expand(_unquote(word), env or {})
    if "$" in p or "%" in p or "`" in p:
        return None
    p = os.path.expanduser(p)
    m = re.match(r"^/([a-zA-Z])(/.*)?$", p)
    if os.name == "nt" and m:  # Git Bash /d/work -> D:/work
        p = f"{m.group(1).upper()}:{m.group(2) or '/'}"
    if not os.path.isabs(p) and base is None:
        return None
    path = Path(p) if os.path.isabs(p) else Path(base) / p
    if not exists:
        return Path(os.path.normpath(path))
    try:
        return path.resolve() if path.is_dir() else None
    except OSError:
        return None


def parse_command(command: str, cwd: str | Path) -> list[dict]:
    """Git and gh operations in a shell command, each with the folder it runs in (``dir``, an existing one) and the
    folder the command named (``path``, which may be gone since; None when a variable is unknown).

    [{"op": "commit"|"push"|"tag"|"pr-create"|"pr-merge", "dir": Path, "path": Path | None, "args": str}]"""
    env: dict[str, str] = {}
    here = want = Path(cwd)
    ops: list[dict] = []
    for seg in _SEP_RE.split(command or ""):
        if not seg.strip():
            continue
        m = _ASSIGN_RE.match(seg)
        if m and not seg.strip().startswith("git"):
            env[m.group(1)] = _expand(_unquote(m.group(2)), env)
            continue
        m = _CD_RE.match(seg)
        if m:
            d = norm_dir(m.group(1), here, env)
            if d:
                here = d
            want = norm_dir(m.group(1), want, env, exists=False)
            continue
        m = _GIT_RE.match(seg)
        if m:
            d, p = here, want
            for c in _GIT_C_RE.findall(m.group(1)):
                d = norm_dir(c, d, env) or d
                p = norm_dir(c, p, env, exists=False)
            ops.append({"op": m.group(2), "dir": d, "path": p, "args": m.group(3).strip()})
            continue
        m = _GH_RE.match(seg)
        if m:
            ops.append({"op": f"pr-{m.group(1)}", "dir": here, "path": want,
                        "args": _expand(m.group(2).strip(), env)})
    return ops


def replay_dir(path: Path | None, history: "History | None" = None) -> Path | None:
    """For a command read in a transcript: the work tree of the folder it named, else of its nearest existing parent
    (a removed worktree's commits live in its main checkout); None when no repo holds it."""
    if path is None:
        return None
    for p in (path, *path.parents):
        if p.is_dir():
            if history:
                return history.top(p)
            top = git(p, "rev-parse", "--show-toplevel")
            return Path(top) if top else None
    return None


def git(d: str | Path, *args: str, timeout: float = 5) -> str:
    """Output of a local git command in ``d`` ('' on any failure); no prompt, no pager."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_PAGER="cat", LC_ALL="C")
    try:
        out = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def remote_repo(url: str) -> str:
    """owner/name of a remote URL (https://, ssh://, git@host:), credentials stripped; '' for a local path or
    file:// (a clone of a folder is not a published repo)."""
    m = _REMOTE_RE.match(secretscan.strip_url_credentials(url))
    return m.group(1) if m else ""


def repo_name(d: str | Path) -> str:
    """owner/name of the origin remote, else the repo folder's name."""
    name = remote_repo(git(d, "remote", "get-url", "origin"))
    if name:
        return name
    top = git(d, "rev-parse", "--show-toplevel")
    return Path(top).name if top else Path(d).name


def _key(text: str) -> str:
    return slug(text.split("/")[-1], 32)


def _session(meta: dict) -> dict:
    s = {"id": meta.get("session_id") or "unknown", "tool": meta.get("tool") or "claude-code"}
    for k in ("model", "version", "effort", "permission_mode", "surface", "agent"):
        if meta.get(k):
            s[k] = str(meta[k])
    return s


def make_ar(kind: str, key: str, at: str, meta: dict, source: str, tool_use_id: str = "", **fields) -> dict:
    rec = {"v": 1, "id": f"ar-{at[:10]}-{kind}-{slug(key, 64)}", "kind": kind, "at": at}
    rec.update({k: v for k, v in fields.items() if v not in (None, "", [], {})})
    rec["session"] = _session(meta)
    rec["source"] = source
    if tool_use_id:
        rec["tool_use_id"] = tool_use_id
    cleaned, _ = secretscan.clean(rec)
    return cleaned


def changed_items(d: str | Path, sha: str) -> list[str]:
    """WorkItem, Milestone and Spec ids whose node blocks a commit changed in any notes/graph/nodes/*.yaml."""
    diff = git(d, *diffs.argv("show", "--format=", "-U0", sha, "--", "*nodes/*.yaml"))
    items: list[str] = []
    lines_by_file: dict[str, list[int]] = {}
    for f in diffs.parse(diff):   # brain.diffs: the engine's one reader (a merge's combined diff included)
        if f.new:
            spans = lines_by_file.setdefault(f.new, [])
            for h in f.hunks:
                spans.extend(range(h.new_start, h.new_start + max(h.new_count, 1)))
    for f, numbers in lines_by_file.items():
        text = git(d, "show", f"{sha}:{f}")
        owner, block_of = None, {}
        for i, line in enumerate(text.splitlines(), 1):
            m = _NODE_RE.match(line)
            if m:
                owner = m.group(1)
            elif line.startswith("#") or (line and not line.startswith(" ")):
                owner = None
            block_of[i] = owner
        for n in numbers:
            nid = block_of.get(n)
            if nid and re.match(r"^(wi|ms|spec)-[a-z0-9-]+$", nid) and nid not in items:
                items.append(nid)
    return items


def added_adrs(d: str | Path, sha: str) -> list[dict]:
    """ADR and SDR headings a commit added to notes/decisions.md or notes/scientific_decisions.md."""
    out = []
    for fname, kind in (("notes/decisions.md", "adr"), ("notes/scientific_decisions.md", "sdr")):
        diff = git(d, *diffs.argv("show", "--format=", "-U0", sha, "--", fname))
        for line in ("+" + text for f in diffs.parse(diff) for _, text in f.added()):
            m = _ADR_HEAD_RE.match(line)
            if m:
                date, title = m.group(1), m.group(2)
                out.append({"id": f"{kind}-{date}-{slug(title) if title else 'entry'}", "title": title[:120],
                            "file": fname})
    return out


def _commit(op: dict, at: str, meta: dict, source: str, tuid: str, now: datetime) -> list[dict]:
    d = op["dir"]
    line = git(d, "log", "-1", "--format=%H%x1f%cI%x1f%s")
    if not line:
        return []
    sha, cdate, subject = (line.split("\x1f") + ["", ""])[:3]
    when = parse_ts(cdate)
    if not when or abs((now - when).total_seconds()) > COMMIT_MAX_AGE_S:
        return []
    branch = git(d, "rev-parse", "--abbrev-ref", "HEAD")
    return _commit_ars(d, sha, when, subject, branch, meta, source, tuid)


def _commit_ars(d: Path, sha: str, when: datetime, subject: str, branch: str, meta: dict, source: str,
                tuid: str, repo: str = "") -> list[dict]:
    """The commit's AR, with the items it changed, and one AR per ADR it added."""
    repo = repo or repo_name(d)
    at_c = iso(when)
    recs = [make_ar("commit", f"{_key(repo)}-{sha[:10]}", at_c, meta, source, tuid, repo=repo,
                    branch=branch if branch != "HEAD" else "", sha=sha, subject=subject, items=changed_items(d, sha))]
    for i, adr in enumerate(added_adrs(d, sha)):
        recs.append(make_ar("adr", f"{_key(repo)}-{sha[:10]}-{i}", at_c, meta, source, tuid, repo=repo, sha=sha,
                            adr=adr))
    return recs


class History:
    """The repos' commit histories, for the commits of a transcript: each repo's ``git log --all``, work tree and
    name read once. ``repos`` are searched when the folder a commit ran in is gone (a removed scratchpad worktree:
    its commits are in its main checkout, which the folder's path does not name). A commit in ``recorded`` (SHAs)
    has its ARs already and is skipped."""

    def __init__(self, repos: list[Path] | None = None, recorded: set[str] | None = None) -> None:
        self.repos = list(repos or [])
        self.recorded = set(recorded or ())
        self._logs: dict[str, list[tuple[str, datetime, str]]] = {}
        self._tops: dict[str, Path | None] = {}
        self._names: dict[str, str] = {}

    def top(self, d: Path) -> Path | None:
        if str(d) not in self._tops:
            top = git(d, "rev-parse", "--show-toplevel")
            self._tops[str(d)] = Path(top) if top else None
        return self._tops[str(d)]

    def name(self, d: Path) -> str:
        if str(d) not in self._names:
            self._names[str(d)] = repo_name(d)
        return self._names[str(d)]

    def log(self, d: Path) -> list[tuple[str, datetime, str]]:
        """(sha, committer date, subject) of every commit reachable from a ref of the repo at ``d``."""
        if str(d) not in self._logs:
            out = []
            for line in git(d, "log", "--all", "--format=%H%x1f%cI%x1f%s", timeout=60).splitlines():
                sha, cdate, subject = (line.split("\x1f") + ["", ""])[:3]
                when = parse_ts(cdate)
                if when:
                    out.append((sha, when, subject))
            self._logs[str(d)] = out
        return self._logs[str(d)]


def _unescape(command: str) -> str:
    """A command's text with the shell escapes of a quoted message undone (bash \\\\ \\" \\` \\$ '\\'', PowerShell
    `")."""
    return _ESCAPED_RE.sub(r"\1", command.replace("'\\''", "'")).replace('`"', '"')


def _commit_logged(op: dict, command: str, start: str, end: str, branch: str, meta: dict, source: str, tuid: str,
                   history: History) -> list[dict]:
    """The commits a call read in a transcript made: those of the repo whose committer date is within the call (a
    second of slack) and whose subject the command holds; the known repos are searched when its folder is gone."""
    t0, t1 = parse_ts(start), parse_ts(end)
    if not t0 or not t1 or op["path"] is None:
        return []
    text = _unescape(command)
    dirs = [op["dir"]] if op["dir"] else []
    if not op["path"].is_dir():
        dirs += [r for r in history.repos if r != op["dir"]]
    out, seen = [], set()
    for d in dirs:
        for sha, when, subject in history.log(d):
            if (sha not in seen and subject and (t0 - when).total_seconds() <= 1 and (when - t1).total_seconds() <= 1
                    and subject in text):
                seen.add(sha)
                if sha not in history.recorded:
                    out += _commit_ars(d, sha, when, subject, branch, meta, source, tuid, history.name(d))
        if seen:
            break
    return out


def _quiet_push(op: dict) -> str | None:
    """The branch a push without output (-q, piped) sent, when its remote-tracking ref now equals the local branch:
    a local check, right after the command."""
    words = [_unquote(w) for w in op["args"].split() if not w.startswith("-") and not re.match(r"^\d?[<>]|&", w)]
    remote = words[0] if words else "origin"
    branch = words[1].split(":")[-1].lstrip("+") if len(words) > 1 else "HEAD"
    if branch == "HEAD":
        branch = git(op["dir"], "rev-parse", "--abbrev-ref", "HEAD")
    if not branch or branch == "HEAD" or not re.fullmatch(r"[\w./-]+", branch + remote):
        return None
    local = git(op["dir"], "rev-parse", f"refs/heads/{branch}")
    tracking = git(op["dir"], "rev-parse", f"refs/remotes/{remote}/{branch}")
    return branch if local and local == tracking else None


def _push(op: dict, output: str, git_op: dict, at: str, meta: dict, source: str, tuid: str) -> list[dict]:
    refs = [f"{m[2]} -> {m[3]}" for m in _REF_RE.findall(output)]
    heads = [m[1] for m in _REF_RE.findall(output) if m[1]]
    pushed = (git_op.get("push") or {}).get("branch") if isinstance(git_op.get("push"), dict) else None
    new = _PULL_NEW_RE.search(output)
    if not refs and not pushed and new:
        pushed = new.group(2)
    if not refs and not pushed and source == "hook":
        pushed = _quiet_push(op)
    if not refs and not pushed:
        return []
    to = _TO_RE.search(output)
    repo = remote_repo(to.group(1)) if to else ""
    repo = repo or (new.group(1) if new else "") or (repo_name(op["dir"]) if op["dir"] else "")
    if not repo:
        return []
    branch = pushed or (refs[0].split(" -> ")[-1] if refs else "")
    sha = heads[0] if heads else git(op["dir"], "rev-parse", branch) if branch and source == "hook" else ""
    key = f"{_key(repo)}-{slug(branch, 24)}-{(sha or tuid[-8:] or at[11:19]).lower()[:10]}"
    return [make_ar("push", key, at, meta, source, tuid, repo=repo, branch=branch,
                sha=sha if re.fullmatch(r"[0-9a-f]{7,40}", sha or "") else "", refs=refs)]


def _pr(op: dict, output: str, git_op: dict, at: str, meta: dict, source: str, tuid: str) -> list[dict]:
    action = "created" if op["op"] == "pr-create" else "merged"
    gpr = git_op.get("pr") if isinstance(git_op.get("pr"), dict) else {}
    if gpr.get("action") not in (None, action):  # a chain like create && merge: the operation is the other one
        gpr = {}
    url, repo, number = gpr.get("url", ""), "", gpr.get("number")
    explicit = re.match(r"(\d+)\b", op["args"]) if action == "merged" else None
    m = _PR_URL_RE.search(url) or _PR_URL_RE.search(op["args"]) or _PR_URL_RE.search(output)
    if explicit:
        number = int(explicit.group(1))
        if m and int(m.group(2)) != number:
            m = None
    if m:
        repo, number, url = m.group(1), int(m.group(2)), url or m.group(0)
    if not number:
        return []
    r = re.search(r"(?:--repo|-R)[=\s]+(\S+)", op["args"])
    named = _unquote(r.group(1)) if r else ""
    if not repo and re.search(r"[$%`]", named):  # a variable the command does not set (a function's $1)
        return []
    repo = repo or named or (repo_name(op["dir"]) if op["dir"] else "")
    if not repo:
        return []
    pr = {"number": int(number), "url": url, "action": action} if url else {"number": int(number), "action": action}
    return [make_ar("pr", f"{_key(repo)}-{number}-{action}", at, meta, source, tuid, repo=repo, pr=pr)]


def _tag(op: dict, at: str, meta: dict, source: str, tuid: str) -> list[dict]:
    words = op["args"].split()
    if not words or any(w in ("-l", "--list", "-d", "--delete", "-v", "--verify", "--contains") for w in words):
        return []
    name, skip = "", False
    for w in words:
        if skip:
            skip = False
            continue
        if w in ("-m", "-F", "-u", "--message", "--file", "--local-user"):
            skip = True
            continue
        if not w.startswith("-"):
            name = _unquote(w)
            break
    sha = git(op["dir"], "rev-parse", f"{name}^{{commit}}") if name else ""
    if not sha:
        return []
    repo = repo_name(op["dir"])
    return [make_ar("tag", f"{_key(repo)}-{slug(name, 32)}", at, meta, source, tuid, repo=repo, tag=name, sha=sha)]


def from_tool_call(command: str, cwd: str | Path, response, meta: dict, at: str | None = None,
                   tool_use_id: str = "", source: str = "hook", family: str = "",
                   now: datetime | None = None, started: str = "", branch: str = "",
                   history: History | None = None) -> list[dict]:
    """ARs for one Bash or PowerShell call. ``family`` limits to 'git' or 'gh' operations (one hook each). A call
    read in a transcript (``source`` transcript) finds its commits in the repos' ``history`` when it is given,
    ``started`` being the time of the call and ``branch`` the session's."""
    now = now or datetime.now(timezone.utc)
    at = at or iso(now)
    resp = response if isinstance(response, dict) else {"stdout": str(response or "")}
    output = f"{resp.get('stdout', '')}\n{resp.get('stderr', '')}"
    git_op = resp.get("gitOperation") if isinstance(resp.get("gitOperation"), dict) else {}
    out: list[dict] = []
    for op in parse_command(command, cwd):
        is_gh = op["op"].startswith("pr-")
        if family and family != ("gh" if is_gh else "git"):
            continue
        moved = False
        if source == "transcript":
            moved = op["path"] != Path(cwd)
            op["dir"] = replay_dir(op["path"], history)
        if op["op"] == "commit" and source == "hook":
            out += _commit(op, at, meta, source, tool_use_id, now)
        elif op["op"] == "commit" and history is not None:
            out += _commit_logged(op, command, started or at, at, "" if moved else branch, meta, source,
                                  tool_use_id, history)
        elif op["op"] == "push":
            out += _push(op, output, git_op, at, meta, source, tool_use_id)
        elif op["op"] == "tag" and source == "hook":
            out += _tag(op, at, meta, source, tool_use_id)
        elif is_gh:
            out += _pr(op, output, git_op, at, meta, source, tool_use_id)
    seen, unique = set(), []
    for r in out:
        if r["id"] not in seen:
            seen.add(r["id"])
            unique.append(r)
    return unique


def from_transcript(path: str | Path, agent: str = "", history: History | None = None) -> list[dict]:
    """ARs recovered from a transcript: pushes, pull requests (created, merged, linked) and the commits the repos'
    history confirms (``_commit_logged``; share one ``History`` across transcripts). Tags need the live hook.
    ``agent`` is the subagent type when the transcript is a subagent's."""
    uses: dict[str, tuple[str, str, str, str]] = {}
    meta: dict = {"tool": "claude-code", "agent": agent}
    history = History() if history is None else history
    out: dict[str, dict] = {}
    linked: list[dict] = []
    for rec, _ in iter_records(path):
        t = rec.get("type")
        if rec.get("sessionId"):
            meta["session_id"] = rec["sessionId"]
        if t == "assistant":
            msg = rec.get("message") or {}
            if msg.get("model") and msg.get("model") != "<synthetic>":
                meta.update(model=msg["model"], version=rec.get("version"), effort=rec.get("effort"),
                            surface=rec.get("entrypoint"))
            for b in msg.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("Bash", "PowerShell"):
                    uses[b.get("id", "")] = ((b.get("input") or {}).get("command", ""), rec.get("cwd") or ".",
                                             rec.get("timestamp") or "", rec.get("gitBranch") or "")
        elif t == "user":
            if rec.get("permissionMode"):
                meta["permission_mode"] = rec["permissionMode"]
            tur = rec.get("toolUseResult")
            content = (rec.get("message") or {}).get("content")
            if not isinstance(tur, dict) or not isinstance(content, list):
                continue
            for b in content:
                if not (isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in uses):
                    continue
                cmd, cwd, started, branch = uses[b["tool_use_id"]]
                for r in from_tool_call(cmd, cwd, tur, dict(meta), at=_iso_ts(rec.get("timestamp")),
                                        tool_use_id=b["tool_use_id"], source="transcript", started=started,
                                        branch=branch, history=history):
                    out.setdefault(r["id"], r)
        elif t == "pr-link" and rec.get("prRepository") and rec.get("prNumber"):
            linked.append(rec)
    have = {(r.get("repo"), (r.get("pr") or {}).get("number")) for r in out.values() if r["kind"] == "pr"}
    for rec in linked:
        repo, n = rec["prRepository"], int(rec["prNumber"])
        if (repo, n) in have:
            continue
        have.add((repo, n))
        r = make_ar("pr", f"{_key(repo)}-{n}-linked", _iso_ts(rec.get("timestamp")), dict(meta), "transcript",
                repo=repo, pr={"number": n, "url": rec.get("prUrl", ""), "action": "linked"})
        out.setdefault(r["id"], r)
    return sorted(out.values(), key=lambda r: (r["at"], r["id"]))


def _iso_ts(ts: str | None) -> str:
    dt = parse_ts(ts)
    return iso(dt) if dt else iso(datetime.now(timezone.utc))
