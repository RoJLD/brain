"""The signed release tag in one owner gesture (wi-brain-release-tag-command; docs/release.md, « 3. The tag »).

``brain release tag vX.Y.Z`` prints its plan, asks the owner one y (``--yes`` in a script of theirs), then runs the
runbook's lines in this order, stopping at the first that fails and saying which:

1. **switch**: the engine checkout to ``main`` (``--branch``: ``release/X.Y`` for a fix that cannot wait), refused
   while a tracked file has changes (nothing is switched, stashed or reset);
2. **pull**: ``git pull --ff-only <remote> <branch>``;
3. **free**: the tag is not on the remote yet (``git ls-remote``): a pushed tag is never moved;
4. **merge**: HEAD is the version PR's merge commit: its message names ``release-X.Y.Z`` (« Release X.Y.Z »),
   both ``__version__`` are the version while its first parent's is another (a PR merged after it is refused), and
   the brain's CHANGELOG holds its heading, whose theme makes the tag message;
5. **public**: ``brain check --public --remote R --history`` (the stamp the push guard reads);
6. **private**: ``brain check --public --remote R --private-text`` (no sentence of the owner's rules or notes in the
   engine);
7. **sign**: ``git tag -s vX.Y.Z -m "brain X.Y.Z and research-graph X.Y.Z — <theme>"``, git asking the owner's key
   for its passphrase in their terminal (a local tag already at HEAD, from a run that stopped later, is kept);
8. **verify**: the tag checked against the planning brain's allowed signers (``--planning``, else ``--root``, else
   the personal brain: its members.yaml's releaser keys, else its ``allowed_signers``, whatever ``$BRAIN_CONFIG``
   names), fetched alone into a temporary repo as ``brain update`` does (brain.tagsig.verify_remote);
9. **push**: ``git push <remote> <tag object>:refs/tags/vX.Y.Z``, the object verified (a tag moved since is refused).

An owner gesture (brain.gestures, category release: never queued, it needs the owner's terminal for the
passphrase): refused in an agent's session after the plan (brain.detail.refused; ``--json`` prints the plan and
exits 1 there), and the owner guard refuses it to a session's tool call. Without ``--yes`` and with no terminal to
answer, nothing runs and it exits 1. The engine never reads a key: git signs with the owner's own
``user.signingkey`` (``gpg.format ssh``). A rerun resumes: a step already done is said ``same``.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .release import INIT, RG_INIT, ReleaseError, find_repo

TAG = re.compile(r"v(\d+\.\d+\.\d+)")
CHANGELOG = "packages/brain/CHANGELOG.md"
STEPS = ("switch", "pull", "free", "merge", "public", "private", "sign", "verify", "push")
TIMEOUT_S = 120
Runner = Callable[..., subprocess.CompletedProcess]


@dataclass
class TagPlan:
    repo: Path
    tag: str
    version: str
    branch: str = "main"
    remote: str = "origin"
    planning: Path | None = None
    lines: list[str] = field(default_factory=list)   # what each step will do, as the plan says it


def heading(text: str, version: str) -> str:
    """The theme of the CHANGELOG heading ``## X.Y.Z — date — theme`` ('' when the section is missing)."""
    m = re.search(rf"^## {re.escape(version)} [—-] \S+ [—-] (.+?)\s*$", text, re.M)
    return m.group(1) if m else ""


def _version(text: str) -> str:
    m = re.search(r'__version__ = "([^"]+)"', text or "")
    return m.group(1) if m else ""


def message(version: str, theme: str) -> str:
    return f"brain {version} and research-graph {version} — {theme}"


def names_release(text: str, version: str) -> bool:
    """Whether a commit message names the version PR of ``version``: « release » right before the version
    (``chore/release-X.Y.Z``, « Release X.Y.Z: theme », « Release vX.Y.Z »), not a longer version, and not a later
    PR that only names both (``fix/release-status-X.Y.Z``)."""
    return bool(re.search(rf"(?i)\brelease[-/ ]v?{re.escape(version)}(?![\d]|\.\d)", text))


def _git(repo: Path, args: list[str], runner: Runner, timeout: float = TIMEOUT_S) -> tuple[int, str]:
    """(exit code, what git said) of a git command in the checkout: its stdout when it succeeds (a warning on stderr,
    an ssh banner, is no value), its stdout and stderr when it fails; (127, why) when git could not run. git reads
    no signature while it prints (log.showSignature off)."""
    try:
        r = runner(["git", "-C", str(repo), "-c", "log.showSignature=false", *args], capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, f"git could not run ({exc.__class__.__name__}: {exc})"
    if r.returncode == 0:
        return 0, (r.stdout or "").strip()
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def _out(repo: Path, args: list[str], runner: Runner) -> str:
    code, text = _git(repo, args, runner)
    return text if code == 0 else ""


def _last(text: str, n: int = 3) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return " / ".join(lines[-n:]) or "no output"


def plan(repo: Path, tag: str, *, branch: str = "main", remote: str = "origin", planning: Path | None = None,
         runner: Runner = subprocess.run) -> TagPlan:
    """The plan, read without writing anything; ReleaseError on a tag that is not a release or a folder that is not
    an engine checkout."""
    m = TAG.fullmatch(tag or "")
    if not m:
        raise ReleaseError(f"{tag!r}: a release tag vX.Y.Z")
    if not (repo / INIT).is_file():
        raise ReleaseError(f"{repo}: no {INIT} (--repo names the engine checkout)")
    p = TagPlan(repo=repo, tag=tag, version=m.group(1), branch=branch, remote=remote, planning=planning)
    here = _out(repo, ["branch", "--show-current"], runner) or "a detached HEAD"
    p.lines = [
        f"switch   git switch {branch}" + (" (on it already)" if here == branch else f" (on {here} now); refused "
                                                                                    "while a tracked file has changes"),
        f"pull     git pull --ff-only {remote} {branch}",
        f"free     {tag} not on {remote} yet (git ls-remote): a pushed tag is never moved",
        f"merge    HEAD is the version PR's merge commit: its message names release-{p.version}, it moves both "
        f"__version__ to {p.version} (its first parent holds another), {CHANGELOG} has ## {p.version}",
        f"public   brain check --public --remote {remote} --history (the stamp the push guard reads)",
        f"private  brain check --public --remote {remote} --private-text (no sentence of your rules or notes in the "
        "engine)",
        f"sign     git tag -s {tag} -m \"{message(p.version, '<the theme of ## ' + p.version + '>')}\" "
        "(your key's passphrase)",
        f"verify   {tag} against the allowed signers of " + (str(planning) if planning else "the personal brain")
        + " (members.yaml's releaser keys, else allowed_signers)",
        f"push     git push {remote} <the verified tag object>:refs/tags/{tag}",
    ]
    return p


# --- the steps: each returns (outcome, detail), outcome done, same or failed ---

def _switch(p: TagPlan, ctx: dict) -> tuple[str, str]:
    code, dirty = _git(p.repo, ["status", "--porcelain", "--untracked-files=no"], ctx["runner"])
    if code != 0:
        return "failed", f"git status failed: {_last(dirty)}"
    if dirty:
        return "failed", (f"tracked files have changes ({_last(dirty, 2)}): commit or set them aside yourself, then "
                          "run it again (nothing was switched)")
    if _out(p.repo, ["branch", "--show-current"], ctx["runner"]) == p.branch:
        return "same", f"on {p.branch}"
    code, text = _git(p.repo, ["switch", p.branch], ctx["runner"])
    return ("done", f"on {p.branch}") if code == 0 else ("failed", f"git switch {p.branch}: {_last(text)}")


def _pull(p: TagPlan, ctx: dict) -> tuple[str, str]:
    before = _out(p.repo, ["rev-parse", "HEAD"], ctx["runner"])
    code, text = _git(p.repo, ["pull", "--ff-only", p.remote, p.branch], ctx["runner"])
    if code != 0:
        return "failed", f"git pull --ff-only {p.remote} {p.branch}: {_last(text)}"
    after = _out(p.repo, ["rev-parse", "HEAD"], ctx["runner"])
    return ("same", f"{p.branch} up to date at {after[:12]}") if after == before else \
        ("done", f"{p.branch} {before[:12]} -> {after[:12]}")


def _free(p: TagPlan, ctx: dict) -> tuple[str, str]:
    code, text = _git(p.repo, ["ls-remote", "--tags", p.remote, f"refs/tags/{p.tag}"], ctx["runner"])
    if code != 0:
        return "failed", f"git ls-remote {p.remote} could not read its tags: {_last(text)}"
    if text.strip():
        return "failed", (f"{p.tag} is on {p.remote} already: a pushed tag is never moved (a mistake is a new "
                          "version; docs/release.md, « 3. The tag »)")
    return "done", f"{p.tag} not on {p.remote}"


def _merge(p: TagPlan, ctx: dict) -> tuple[str, str]:
    sha = _out(p.repo, ["rev-parse", "--verify", "HEAD"], ctx["runner"])
    if not sha:
        return "failed", "git rev-parse could not read HEAD"
    said = _out(p.repo, ["log", "-1", "--format=%s%n%b", sha], ctx["runner"])
    if not names_release(said, p.version):
        first = said.splitlines()[0] if said else ""
        return "failed", (f"HEAD {sha[:12]} ({first!r}) is not the version PR's merge: its message does not name "
                          f"release-{p.version} (merge it first, or pull again)")
    for rel in (INIT, RG_INIT):
        f = p.repo / rel
        got = _version(f.read_text(encoding="utf-8")) if f.is_file() else ""
        if got != p.version:
            return "failed", f"{rel}: __version__ is {got or 'missing'}, not {p.version}"
    code, before = _git(p.repo, ["show", f"{sha}^1:{INIT}"], ctx["runner"])
    if code == 0 and _version(before) == p.version:
        return "failed", (f"HEAD {sha[:12]} is after the version PR's merge: its first parent is at {p.version} "
                          "already (a PR merged since; tag the version PR's merge by hand, docs/release.md)")
    cl = p.repo / CHANGELOG
    theme = heading(cl.read_text(encoding="utf-8"), p.version) if cl.is_file() else ""
    if not theme:
        return "failed", f"{CHANGELOG} has no heading « ## {p.version} — date — theme » (the version PR's compile)"
    ctx["head"], ctx["message"] = sha, message(p.version, theme)
    return "done", f"HEAD {sha[:12]}, the theme « {theme} »"


def check_argv(p: TagPlan, flag: str) -> list[str]:
    """The arguments of a public check, after the brain command."""
    return ["check", "--public", "--repo", str(p.repo), "--remote", p.remote, flag]


def _check(p: TagPlan, ctx: dict, flag: str) -> tuple[str, str]:
    argv = [*ctx["brain"], *check_argv(p, flag)]
    try:
        r = ctx["runner"](argv, cwd=str(p.repo), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=1800, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        return "failed", f"brain check --public {flag} could not run ({exc.__class__.__name__})"
    text = ((r.stdout or "") + (r.stderr or "")).strip()
    if r.returncode != 0:
        return "failed", f"brain check --public {flag} (exit {r.returncode}):\n{text[-1500:]}"
    return "done", _last(text, 1)


def _local_tag(p: TagPlan, ctx: dict) -> str:
    """The commit a local tag of that name names ('' when there is none)."""
    return _out(p.repo, ["rev-parse", "--verify", "--quiet", f"refs/tags/{p.tag}^{{commit}}"], ctx["runner"])


def _tag_object(p: TagPlan, ctx: dict) -> str:
    """The local tag's object id: what verify checks and push sends ('' when there is none)."""
    return _out(p.repo, ["rev-parse", "--verify", "--quiet", f"refs/tags/{p.tag}"], ctx["runner"])


def signers(planning: Path | None) -> tuple[str, str]:
    """(the allowed-signers text, its source) of the planning brain named: its members.yaml's releaser keys, else its
    allowed_signers file, whatever $BRAIN_CONFIG names; the personal brain's (brain.tagsig.signers) when none is."""
    from . import tagsig
    if planning is None:
        return tagsig.signers(None)
    text = tagsig._from_members(planning)
    if text is not None:
        return (text, f"members.yaml, role {tagsig.RELEASER}") if text else ("", "")
    f = planning / tagsig.FILE
    text = f.read_text(encoding="utf-8", errors="replace") if f.is_file() else ""
    return (text, str(f)) if tagsig._lines(text) else ("", "")


def _sign(p: TagPlan, ctx: dict) -> tuple[str, str]:
    at = _local_tag(p, ctx)
    if at and at == ctx["head"]:
        ctx["object"] = _tag_object(p, ctx)
        return "same", f"{p.tag} is here already, at HEAD (a run that stopped later): verified next"
    if at:
        return "failed", (f"a local {p.tag} names {at[:12]}, not HEAD {ctx['head'][:12]}: it was never pushed (step "
                          f"free), so delete it yourself (git tag -d {p.tag}) and run it again")
    argv = ["git", "-C", str(p.repo), "tag", "-s", p.tag, "-m", ctx["message"]]
    try:   # the owner's terminal: git asks the key's passphrase there (no capture)
        r = ctx["runner"](argv)
    except (OSError, subprocess.SubprocessError) as exc:
        return "failed", f"git tag -s could not run ({exc.__class__.__name__})"
    if r.returncode != 0:
        return "failed", (f"git tag -s {p.tag} failed (exit {r.returncode}): your signing key (git config gpg.format "
                          "ssh, user.signingkey; packages/brain/docs/identity.md, « Signed releases »)")
    ctx["object"] = _tag_object(p, ctx)
    return "done", f"{p.tag} signed: {ctx['message']}"


def _verify(p: TagPlan, ctx: dict) -> tuple[str, str]:
    from . import tagsig
    allowed, source = signers(p.planning)
    undo = f"{p.tag} is local only: git tag -d {p.tag} before signing it again"
    if not allowed:
        return "failed", (f"no releaser key to verify with (members.yaml's {tagsig.RELEASER} role, else "
                          f"{tagsig.FILE} beside config.json of {p.planning or 'the personal brain'}); {undo}")
    v = tagsig.verify_remote(p.repo.resolve().as_uri(), p.tag, allowed, source=source, runner=ctx["runner"])
    if v["status"] != tagsig.VERIFIED:
        return "failed", f"{tagsig.line(v, True)}; {undo}"
    if v["commit"] != ctx["head"]:
        return "failed", f"{p.tag} names {v['commit'][:12]}, not HEAD {ctx['head'][:12]}; {undo}"
    if not ctx["object"]:
        return "failed", f"the tag object of {p.tag} could not be read; {undo}"
    return "done", f"signed by {v['signer']} ({v['source'] or tagsig.FILE})"


def _push(p: TagPlan, ctx: dict) -> tuple[str, str]:
    now = _out(p.repo, ["rev-parse", "--verify", "--quiet", f"refs/tags/{p.tag}"], ctx["runner"])
    if now != ctx["object"]:
        return "failed", (f"{p.tag} moved after it was verified ({ctx['object'][:12]} -> {now[:12] or 'gone'}): "
                          "nothing pushed; check the local tags, then run it again")
    argv = ["git", "-C", str(p.repo), "push", p.remote, f"{ctx['object']}:refs/tags/{p.tag}"]
    try:   # the owner's terminal: git's credential prompt, if any, there
        r = ctx["runner"](argv)
    except (OSError, subprocess.SubprocessError) as exc:
        return "failed", f"git push could not run ({exc.__class__.__name__})"
    if r.returncode != 0:
        return "failed", (f"git push {p.remote} {p.tag} failed (exit {r.returncode}): the tag is signed and verified "
                          "here; run it again once the remote is reachable (it resumes)")
    return "done", f"{p.tag} pushed to {p.remote}"


RUN = {"switch": _switch, "pull": _pull, "free": _free, "merge": _merge,
       "public": lambda p, c: _check(p, c, "--history"), "private": lambda p, c: _check(p, c, "--private-text"),
       "sign": _sign, "verify": _verify, "push": _push}


def run(p: TagPlan, *, runner: Runner = subprocess.run, brain: list[str] | None = None,
        say: Callable[[str], object] = print) -> list[dict]:
    """Each step in order, said as it ends; the first that fails stops the rest (in the rows as ``not run``, not
    said)."""
    ctx = {"runner": runner, "brain": brain or [sys.executable, "-m", "brain"], "head": "", "message": "",
           "object": ""}
    rows, failed = [], False
    for name in STEPS:
        if failed:
            rows.append({"step": name, "outcome": "not run", "detail": ""})
            continue
        outcome, detail = RUN[name](p, ctx)
        rows.append({"step": name, "outcome": outcome, "detail": detail})
        say(f"{name:<9}{outcome:<7}{detail}".rstrip().replace("\n", "\n  "))
        failed = outcome == "failed"
    return rows


def _where(args) -> tuple[Path, Path | None]:
    from . import paths
    repo = Path(args.repo).resolve() if args.repo else find_repo(Path.cwd())
    planning = Path(args.planning).resolve() if args.planning else (
        Path(args.root).resolve() if getattr(args, "root", None) else paths.personal_root())
    return repo, planning


def main(args, *, runner: Runner = subprocess.run, brain: list[str] | None = None, ask=None, out=print,
         refused: str | None = None) -> int:
    """brain release tag: the plan (always), then, in the owner's terminal and on their y, the steps."""
    from . import detail
    try:
        repo, planning = _where(args)
        p = plan(repo, args.tag, branch=args.branch, remote=args.remote, planning=planning, runner=runner)
    except (ReleaseError, OSError) as exc:
        print(f"brain release tag: {exc}", file=sys.stderr)
        return 2
    why = detail.refused() if refused is None else refused
    if args.json:   # the plan as data; in an agent's session refused all the same, as the owner guard refuses it
        out(json.dumps({k: (str(v) if isinstance(v, Path) else v) for k, v in asdict(p).items()},
                       ensure_ascii=False, indent=1))
        return 1 if why else 0
    out(f"release  {p.tag} from {p.repo} ({p.remote}, branch {p.branch})")
    out("\n".join(p.lines))
    if why:
        out(f"brain release tag: {why}; run it yourself in a terminal")
        return 1
    if not args.yes:
        if ask is None and not sys.stdin.isatty():
            out("brain release tag: no terminal to answer y; --yes runs it (nothing tagged)")
            return 1
        if (ask or input)(f"Sign and push {p.tag} now? [y/N] ").strip().lower() not in ("y", "yes", "o", "oui"):
            out("nothing tagged")
            return 0
    rows = run(p, runner=runner, brain=brain, say=out)
    failed = next((r for r in rows if r["outcome"] == "failed"), None)
    if failed:
        out(f"stopped  at {failed['step']}: the steps after it did not run; fix it, then run it again (it resumes)")
        return 1
    out(f"next     brain release status {p.version}; then the pin: brain release pin {p.tag} --write in a pin branch "
        "of the planning brain (docs/release.md, « 4. The pin and the machines »)")
    return 0
