"""``brain check --public [--repo DIR] [--remote NAME] [--history] [--engine] [--json]``: nothing private leaves for a
public repo (wi-brain-public-boundary-check). Zero token:
git and the files, read by script.

It runs in the checkout of a public repo (config.json ``public.repos``) from the personal brain's installed engine, so
the lists it reads never leave the private side: the config is the brain's (brain.config), never one in the checked
repo. It refuses, one finding per line, exit code 1:

- ``denied``: a term of ``public.deny`` (people, users, hosts, repos, paths), as brain boundary counts it (whole
  words, case-insensitive, ``/`` and ``\\`` alike);
- ``secret``: a line brain.secretscan matches (a private key block included), unless it carries ``gitleaks:allow``;
  with ``--history``, gitleaks over the commits when it is on the PATH (else the patterns alone, and it says so);
- ``pattern``: the generic shapes of personal data, written here with nothing personal in them: an e-mail address
  outside the example and no-reply domains, a home folder (``/Users/x``, ``C:\\Users\\x``, ``/home/x``) other than a
  placeholder; a line that carries ``public-check:allow`` passes;
- ``file``: a data or sealed file: Parquet, Feather, Arrow, SQLite, DuckDB anywhere; CSV, TSV, JSONL under a data
  folder (``data/``, ``datasets/``, ``raw/``, ``exports/``, ``dumps/``, ``ledger/``); ``*.age``, ``*.gpg``, ``*.pgp``;
  the vault's ``heirs.yaml`` and ``members.yaml``; ``.env`` files and key files (``*.pem``, ``*.key``, ``*.p12``,
  ``*.pfx``, ``id_rsa``, ``id_ed25519``); the reference library's binaries, PDF and EPUB (spec-brain-second-brain
  §3.13; a document meant to be published goes under ``public.allow``);
- ``domain``: a domain's own refusals, from its template: ``public.patterns`` (``{name: regex}`` a line must not
  match, a data venue's derived columns say) and ``public.refuse`` (``{glob: reason}`` of files that must not be
  there, the research-IP paths of a split).

``public.allow`` (``{glob: reason}``) excepts a file from every check but ``secret`` (a licence keeps its author's
name). The tracked files are read at HEAD's working tree; ``--history`` adds the lines and the files of every commit
not on the remote yet (``HEAD --not --remotes=<remote>``: the whole history before a first push), their messages
(every check of a line) and their author's and committer's e-mail addresses (a no-reply one passes), the remote being
``--remote``, else the one whose URL is in ``public.repos``, else ``origin``. ``--engine`` checks, in the personal
brain's own checkout, the files brain boundary sends to the engine instead (the extraction's dry run: no history, no
stamp).

A green check with ``--history`` writes the stamp ``<BRAIN_HOME>/public-check/<owner>/<repo>/<sha>`` (HEAD's sha, the
repo's GitHub owner and name): the ``public`` guard (brain.guards) refuses a ``git push`` to a repo of
``public.repos`` until every commit it pushes has one.

:func:`gate` is what ``brain check`` runs in a brain or repo with a boundary.yaml (``brain init`` writes one): brain
boundary's check and the ``--engine`` scan, so that what may be published one day holds nothing private from the
first commit (wi-brain-public-ready-init).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import boundary, config, paths, secretscan

STAMPS = "public-check"
CHECKS = ("denied", "secret", "pattern", "file", "domain")
MAX_FILE = 1_000_000
ALLOW_MARK = "public-check:allow"

_EMAIL = re.compile(r"(?<![\w.%+-])([A-Za-z0-9._%+-]+)@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})(?![\w-])")
_EMAIL_LOCAL_OK = {"noreply", "no-reply", "git"}
_EMAIL_DOMAIN_OK = re.compile(r"(?i)(?:^|\.)(?:example\.(?:com|org|net)|example|invalid|test|localhost|"
                              r"noreply\.github\.com)$")
_HOME = re.compile(r"(?i)(?:\b[A-Z]:[\\/]+Users|(?<![\w.-])/Users|(?<![\w.-])/home)[\\/]+([A-Za-z0-9._-]+)")
_HOME_PLACEHOLDERS = {"user", "username", "you", "your", "name", "me", "runner", "example", "public", "default",
                      "shared", "x", "someone"}
_ALWAYS = {".parquet": "Parquet data", ".feather": "Feather data", ".arrow": "Arrow data", ".sqlite": "a SQLite base",
           ".sqlite3": "a SQLite base", ".db": "a database file", ".duckdb": "a DuckDB base",
           ".age": "a sealed file", ".gpg": "a sealed file", ".pgp": "a sealed file",
           ".pem": "key material", ".key": "key material", ".p12": "key material", ".pfx": "key material",
           ".pdf": "a library binary (PDF)", ".epub": "a library binary (EPUB)"}
_UNDER_DATA = {".csv": "CSV", ".tsv": "TSV", ".jsonl": "JSON lines", ".ndjson": "JSON lines"}
_DATA_DIRS = {"data", "datasets", "raw", "exports", "dumps", "ledger", "ledgers"}
_NAMES = {"heirs.yaml": "the vault's heirs", "members.yaml": "the vault's members", ".env": "an environment file",
          "id_rsa": "a private key", "id_ed25519": "a private key"}


class PublicError(Exception):
    """Not a git checkout, or HEAD unreadable (exit code 2)."""


@dataclass(frozen=True)
class Finding:
    check: str
    path: str
    line: int
    what: str
    commit: str = ""

    def text(self) -> str:
        where = f"{self.commit[:8]}:" if self.commit else ""
        return f"{where}{self.path}" + (f":{self.line}" if self.line else "") + f": {self.check}: {self.what}"


# --- the repo and its stamp ---

def repo_slug(url: str) -> str:
    """``owner/name`` of a GitHub remote URL (https, ssh or scp-like, ``.git`` or not), else ''."""
    m = re.search(r"github\.com[:/]+([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", (url or "").strip())
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def public_repos(cfg: config.Config) -> list[str]:
    pub = cfg.data.get("public") if isinstance(cfg.data.get("public"), dict) else {}
    return [r for r in pub.get("repos") or [] if isinstance(r, str) and r]


def is_public(slug: str, cfg: config.Config) -> bool:
    return bool(slug) and slug.lower() in {r.lower() for r in public_repos(cfg)}


def _git(repo: Path, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=timeout,
                          stdin=subprocess.DEVNULL)


def _out(repo: Path, *args: str) -> str:
    r = _git(repo, *args)
    return r.stdout.decode("utf-8", "replace").strip() if r.returncode == 0 else ""


def remote_of(repo: Path, cfg: config.Config, name: str = "") -> tuple[str, str]:
    """(remote name, owner/name): ``name``, else the remote whose URL is a public repo, else origin."""
    names = _out(repo, "remote").split()
    if name:
        return name, repo_slug(_out(repo, "remote", "get-url", name))
    for n in names:
        slug = repo_slug(_out(repo, "remote", "get-url", n))
        if is_public(slug, cfg):
            return n, slug
    return ("origin", repo_slug(_out(repo, "remote", "get-url", "origin"))) if "origin" in names else ("", "")


def stamp_path(slug: str, sha: str) -> Path:
    owner, _, name = slug.partition("/")
    return paths.brain_home() / STAMPS / owner.lower() / name.lower() / sha


def stamped(slug: str, sha: str) -> bool:
    return bool(slug and sha) and stamp_path(slug, sha).is_file()


# --- the checks ---

@dataclass
class Rules:
    terms: list[tuple[str, str, re.Pattern]]
    allow: list[re.Pattern]
    patterns: list[tuple[str, re.Pattern]]
    refuse: list[tuple[str, re.Pattern, str]]
    errors: list[str]

    def allowed(self, path: str) -> bool:
        return any(rx.match(path) for rx in self.allow)


def rules(cfg: config.Config) -> Rules:
    pub = cfg.data.get("public") if isinstance(cfg.data.get("public"), dict) else {}
    patterns, errors = [], []
    for name, rx in (pub.get("patterns") or {}).items() if isinstance(pub.get("patterns"), dict) else []:
        try:
            patterns.append((str(name), re.compile(str(rx))))
        except re.error as exc:
            errors.append(f"config.json public.patterns {name}: {exc}")
    refuse = [(g, boundary.glob_regex(g), str(why)) for g, why in (pub.get("refuse") or {}).items()] \
        if isinstance(pub.get("refuse"), dict) else []
    return Rules([(cat, t, boundary.term_regex(t)) for cat, t in config.deny_terms(cfg)],
                 [boundary.glob_regex(g) for g in config.allowed(cfg)], patterns, refuse, errors)


def _generic(line: str) -> list[str]:
    out = []
    for m in _EMAIL.finditer(line):
        local, domain = m.group(1), m.group(2)
        if line[max(0, m.start() - 3):m.start()].endswith("//"):
            continue  # a URL's user (https://user@host): a credential is the secrets' check
        if local.lower() not in _EMAIL_LOCAL_OK and not _EMAIL_DOMAIN_OK.search(domain):
            out.append(f"an e-mail address ({m.group(0)})")
    for m in _HOME.finditer(line):
        if m.group(1).lower() not in _HOME_PLACEHOLDERS:
            out.append(f"a home folder ({m.group(0)})")
    return out


def scan_lines(path: str, lines, r: Rules, commit: str = "") -> list[Finding]:
    """The findings of ``lines`` ((number, text) pairs) of the file ``path``."""
    out: list[Finding] = []
    allowed = r.allowed(path)
    for n, line in lines:
        flat = line.replace("\\", "/")
        if not allowed:
            for cat, term, rx in r.terms:
                if rx.search(flat):
                    out.append(Finding("denied", path, n, f"{cat} term {term!r}", commit))
        out += [Finding("secret", path, n, f"looks like a secret ({name})", commit)
                for name in secretscan.find_in_line(line)[:1]]
        if allowed or ALLOW_MARK in line:
            continue
        out += [Finding("pattern", path, n, what, commit) for what in _generic(line)]
        out += [Finding("domain", path, n, f"matches public.patterns {name}", commit)
                for name, rx in r.patterns if rx.search(line)]
    return out


def file_finding(path: str, r: Rules, commit: str = "") -> Finding | None:
    """The finding of the file ``path`` itself: a data, sealed or key file, or a path a domain refuses."""
    if r.allowed(path):
        return None
    parts = path.lower().split("/")
    name = parts[-1]
    ext = os.path.splitext(name)[1]
    what = _NAMES.get(name) or ("an environment file" if name.startswith(".env.") else "") or _ALWAYS.get(ext, "")
    if not what and ext in _UNDER_DATA and _DATA_DIRS & set(parts[:-1]):
        what = f"{_UNDER_DATA[ext]} under a data folder"
    if what:
        return Finding("file", path, 0, what, commit)
    for glob, rx, why in r.refuse:
        if rx.match(path):
            return Finding("domain", path, 0, f"refused by public.refuse {glob} ({why})", commit)
    return None


def scan_tree(repo: Path, files: list[str], r: Rules) -> tuple[list[Finding], list[str]]:
    """The findings of the working tree's ``files``, and the files not read (binary, too large or missing)."""
    out, unread = [], []
    for path in files:
        f = file_finding(path, r)
        if f:
            out.append(f)
        try:
            if (repo / path).stat().st_size > MAX_FILE:
                unread.append(path)
                continue
            text = (repo / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            unread.append(path)
            continue
        out += scan_lines(path, enumerate(text.splitlines(), 1), r)
    return out, unread


def scan_history(repo: Path, rev_range: list[str], r: Rules) -> tuple[list[Finding], int]:
    """The findings of the lines and files the commits of ``rev_range`` add, and how many commits it holds."""
    shas = _out(repo, "rev-list", *rev_range).split()
    if not shas:
        return [], 0
    out: list[Finding] = []
    log = _git(repo, "log", "-p", "-U0", "--no-color", "--no-ext-diff", "--no-renames", "--format=%x00%H",
               *rev_range, timeout=300).stdout.decode("utf-8", "replace")
    commit, path, n, lines = "", "", 0, []

    def flush():
        if path and lines:
            out.extend(scan_lines(path, lines, r, commit))

    for raw in log.splitlines():
        if raw.startswith("\0"):
            flush()
            commit, path, lines = raw[1:].strip(), "", []
        elif raw.startswith("+++ "):
            flush()
            p = raw[4:].strip().strip('"')
            path, lines = (p[2:] if p.startswith("b/") else "" if p == "/dev/null" else p), []
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            n = int(m.group(1)) if m else 0
        elif raw.startswith("+") and path:
            lines.append((n, raw[1:]))
            n += 1
    flush()
    names = _git(repo, "log", "--name-only", "--diff-filter=AMR", "--no-renames", "--format=%x00%H",
                 *rev_range, timeout=300).stdout.decode("utf-8", "replace")
    commit = ""
    for raw in names.splitlines():
        if raw.startswith("\0"):
            commit = raw[1:].strip()
        elif raw.strip():
            f = file_finding(raw.strip(), r, commit)
            if f:
                out.append(f)
    return out + scan_messages(repo, rev_range, r), len(shas)


def scan_messages(repo: Path, rev_range: list[str], r: Rules) -> list[Finding]:
    """The findings of the commits' messages (path ``<message>``: every check of a line) and of their author's and
    committer's e-mail addresses (path ``<author>``: the generic e-mail shape; a no-reply address passes). A name is
    not checked: the owner signs a public commit as they sign its licence."""
    log = _git(repo, "log", "--format=%x00%H%x00%ae%x00%ce%x00%B%x01", *rev_range,
               timeout=300).stdout.decode("utf-8", "replace")
    out: list[Finding] = []
    for record in log.split("\x01"):
        parts = record.lstrip("\r\n").split("\0")
        if len(parts) < 5:
            continue
        _, commit, author, committer, body = parts[:5]
        out += scan_lines("<message>", enumerate(body.strip("\r\n").splitlines(), 1), r, commit)
        for email in dict.fromkeys((author, committer)):
            out += [Finding("pattern", "<author>", 0, what, commit) for what in _generic(email)]
    return out


def gitleaks_history(repo: Path, rev_range: list[str]) -> list[Finding] | None:
    """gitleaks over the commits of ``rev_range`` (``git``, then the older ``detect``): its findings, or None when
    it is not on the PATH or fails."""
    exe = shutil.which("gitleaks")
    if not exe:
        return None
    opts = " ".join(rev_range)
    with tempfile.TemporaryDirectory() as tmp:
        report = os.path.join(tmp, "report.json")
        for sub in (["git", f"--log-opts={opts}"], ["detect", "--source", ".", f"--log-opts={opts}"]):
            try:
                res = subprocess.run([exe, *sub, "--redact", "--no-banner", "--exit-code", "1", "--report-format",
                                      "json", "--report-path", report], cwd=repo, capture_output=True, timeout=300,
                                     stdin=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                return None
            if res.returncode == 0:
                return []
            if res.returncode == 1 and os.path.exists(report):
                with open(report, encoding="utf-8") as fh:
                    found = json.load(fh) or []
                return [Finding("secret", str(f.get("File")), int(f.get("StartLine") or 0),
                                f"gitleaks {f.get('RuleID')}", str(f.get("Commit") or "")) for f in found]
    return None


def _dedupe(found: list[Finding]) -> list[Finding]:
    """One finding per check, file, line and what: a line the tree and a commit both hold shows once (the tree's)."""
    seen, out = set(), []
    for f in found:
        key = (f.check, f.path, f.what) if f.commit else (f.check, f.path, f.line, f.what)
        tree_key = (f.check, f.path, f.what)
        if key in seen or (f.commit and tree_key in seen):
            continue
        seen.update({key, tree_key})
        out.append(f)
    return out


def check(repo: Path, cfg: config.Config | None = None, *, history: bool = False, remote: str = "",
          engine: bool = False) -> dict:
    """The findings of ``repo``, with what was read: {repo, slug, remote, head, files, unread, commits, gitleaks,
    findings, counts, notes}."""
    cfg = cfg or config.load()
    top = _out(repo, "rev-parse", "--show-toplevel")
    if not top:
        raise PublicError(f"{repo}: not a git checkout")
    repo = Path(top)
    head = _out(repo, "rev-parse", "--verify", "HEAD")
    r = rules(cfg)
    notes = list(r.errors)
    if engine:
        try:
            files = boundary.report(repo, cfg)["by_side"]["engine"]
        except boundary.BoundaryError as exc:
            raise PublicError(str(exc)) from exc
        name, slug = "", (public_repos(cfg) or [""])[0]
    else:
        files = boundary.tracked(repo)
        name, slug = remote_of(repo, cfg, remote)
        if not is_public(slug, cfg):
            notes.append(f"{slug or 'this checkout'} is not in config.json public.repos: checked all the same, "
                         "not stamped")
    if not config.deny_terms(cfg):
        notes.append("config.json has no public.deny: no private term is looked for")
    found, unread = scan_tree(repo, files, r)
    commits, leaks = 0, None
    if history and not engine and head:
        rev_range = ["HEAD", "--not", f"--remotes={name}"] if name else ["HEAD"]
        hist, commits = scan_history(repo, rev_range, r)
        found += hist
        leaks = gitleaks_history(repo, rev_range) if commits else []
        found += leaks or []
        if leaks is None:
            notes.append("gitleaks is not on the PATH: the history's secrets by brain.secretscan's patterns only")
    found = _dedupe(found)
    return {"repo": str(repo), "slug": slug, "remote": name, "head": head, "engine": engine, "history": history,
            "files": len(files), "unread": unread, "commits": commits, "gitleaks": leaks is not None,
            "findings": [asdict(f) for f in found],
            "counts": {c: sum(1 for f in found if f.check == c) for c in CHECKS}, "notes": notes}


def stamp(data: dict) -> Path | None:
    """Write the stamp of a green check with its history of a public repo's HEAD; None when it does not qualify."""
    if data["findings"] or not data["history"] or data["engine"] or not data["head"] or not data["slug"]:
        return None
    f = stamp_path(data["slug"], data["head"])
    f.parent.mkdir(parents=True, exist_ok=True)
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    f.write_text(json.dumps({"at": at, "repo": data["repo"], "remote": data["remote"], "files": data["files"],
                             "commits": data["commits"], "gitleaks": data["gitleaks"]}, sort_keys=True) + "\n",
                 encoding="utf-8")
    return f


def render(data: dict, stamped_at: Path | None = None) -> list[str]:
    what = "the engine side of " if data["engine"] else ""
    head = (data["head"] or "no commit")[:8]
    lines = [f"brain check --public: {what}{data['slug'] or Path(data['repo']).name} ({data['repo']}), HEAD {head}, "
             f"{data['files']} file(s)" + (f", {data['commits']} commit(s) not on {data['remote'] or 'a remote'}"
                                          if data["history"] and not data["engine"] else "")]
    c = data["counts"]
    lines.append("  " + ", ".join(f"{k} {c[k]}" for k in CHECKS))
    lines += ["  " + Finding(**f).text() for f in data["findings"]]
    if data["unread"]:
        lines.append(f"  not read (binary, over 1 MB or missing; their names were checked): {len(data['unread'])}")
    lines += [f"  note: {n}" for n in data["notes"]]
    if data["findings"]:
        lines.append(f"refused: {len(data['findings'])} finding(s); take them out (or except a file in public.allow, "
                     f"a line with {ALLOW_MARK}), nothing is stamped")
    elif stamped_at:
        lines.append(f"green: stamped {stamped_at.as_posix()} (the public guard lets git push send {head})")
    elif data["engine"]:
        lines.append("green: the engine side holds nothing private (a dry run: no stamp)")
    else:
        lines.append("green" + ("" if data["history"] else ": the tree only; --history checks the commits to push "
                                "and stamps HEAD for the public guard"))
    return lines


def gate(root: Path, cfg: config.Config | None = None) -> tuple[int, list[str]]:
    """What ``brain check`` adds for a brain or a repo with a boundary.yaml (wi-brain-public-ready-init): brain boundary
    --check (every tracked file classified, the engine side at or under readiness_max) and this module's scan of the
    engine side (``--engine``: no denied term, secret, e-mail address, home folder or data file in what may be
    published one day). (exit code, lines); nothing without a boundary.yaml, a note before the first ``git init``."""
    root = Path(root)
    if not (root / boundary.FILE).is_file():
        return 0, []
    if not _out(root, "rev-parse", "--show-toplevel"):
        return 0, [f"boundary: not a git checkout yet, nothing tracked to check ({boundary.FILE})"]
    cfg = cfg or config.load(root)
    try:
        data = boundary.report(root, cfg)
        scan = check(root, cfg, engine=True)
    except (boundary.BoundaryError, PublicError) as exc:
        return 1, [f"error: boundary: {exc}"]
    errors = [f"error: boundary: {p}: no rule of {boundary.FILE} classifies it (add one: engine, personal, claude or "
              "generated)" for p in data["unclassified"]]
    errors += [f"error: boundary: {e}" for e in data["errors"]]
    if boundary.over(data):
        errors.append(f"error: boundary: the engine side holds {data['readiness']['total']} denied term(s), over "
                      f"readiness_max {data['readiness_max']}: brain boundary --readiness names them")
    errors += [f"error: boundary: public: {Finding(**f).text()}" for f in scan["findings"]]
    if errors:
        return 1, errors + [f"boundary: {len(errors)} error(s); what may be published one day holds nothing private "
                            "(brain boundary, brain check --public --engine)"]
    cap = data["readiness_max"]
    return 0, [f"boundary: {data['files']} tracked file(s) classified; engine side {data['counts']['engine']} file(s), "
               f"readiness {data['readiness']['total']}" + (f" (max {cap})" if cap is not None else "")
               + ", public scan green"]


def main(repo: Path, *, history: bool = False, remote: str = "", engine: bool = False, as_json: bool = False) -> int:
    try:
        data = check(repo, history=history, remote=remote, engine=engine)
    except PublicError as exc:
        print(f"brain check --public: {exc}")
        return 2
    cfg = config.load()
    where = stamp(data) if is_public(data["slug"], cfg) else None
    if as_json:
        print(json.dumps({**data, "stamp": where.as_posix() if where else None}, ensure_ascii=False, indent=1,
                         sort_keys=True))
    else:
        print("\n".join(render(data, where)))
    return 1 if data["findings"] else 0
