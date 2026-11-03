"""The boundary between the public engine and the personal brain, file by file (wi-brain-personal-brain,
docs/specs/2026-11-02-personal-brain-boundary-design.md §3): ``boundary.yaml`` at the repo's root and
``brain boundary [--check] [--side S] [--readiness] [--json]``.

Each tracked file (``git ls-files``) takes the side of the first rule whose glob matches (``**`` any folders, ``*``
and ``?`` within a name):

- ``engine``: leaves for the engine's public repo, at the rule's ``target`` (a folder ending in ``/`` receives the
  path below the glob's fixed prefix; any other target is the file's new path);
- ``personal``: stays here, the owner's content;
- ``claude``: the Claude rendering (plugin and marketplace manifests), written by ``brain render --target claude``
  once the engine has left (wi-brain-neutral-source);
- ``generated``: a view a command writes; it follows its store.

A personal or claude rule may name its ``init``: the setup wizard's step that writes the file's first version for a
new user (``brain init``, ``brain project add --template T``, ``brain render --target claude``), the PB-1 answer
(every personal configuration initialisable by a wizard); ``--side`` shows it, and wi-brain-setup-wizard builds the
steps. ``--check`` fails on a tracked file no rule classifies, an engine rule without a target, an ``init`` on an
engine or generated rule and two engine files with the same target; a rule that classifies nothing is a warning. The **readiness** of the engine side counts the terms of
config.json's ``public.deny`` found in its files (whole words, case-insensitive, ``/`` and ``\\`` alike), the files
under ``public.allow`` excepted: what has to leave the code before it can be published. ``readiness_max`` in
boundary.yaml is its ratchet (wi-brain-owner-neutral): ``--check`` fails when the readiness rises above it, and each
drop lowers it. ``brain check --public`` (brain.public) applies the same scan, and more, to a public repo before a push.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import config, graph

FILE = "boundary.yaml"
SIDES = ("engine", "personal", "claude", "generated")
RULE_KEYS = {"glob", "side", "target", "init", "why"}
INIT_SIDES = ("personal", "claude")  # the sides a new user's brain starts with


class BoundaryError(ValueError):
    """A bad boundary.yaml (brain boundary exits 2)."""


@dataclass
class Rule:
    glob: str
    side: str
    target: str = ""
    why: str = ""
    regex: re.Pattern = field(default=None, repr=False)
    init: str = ""                   # the wizard step that writes the file's first version (personal, claude)

    def target_of(self, path: str) -> str:
        if not self.target.endswith("/"):
            return self.target
        prefix = re.split(r"[*?\[]", self.glob, maxsplit=1)[0]
        prefix = prefix[:prefix.rfind("/") + 1]
        return self.target + path[len(prefix):]


def glob_regex(glob: str) -> re.Pattern:
    """A glob as a regex over a /-separated path: ``**/`` any folders (none included), ``**`` anything, ``*`` and
    ``?`` within one name."""
    out, i = "", 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif glob.startswith("**", i):
            out, i = out + ".*", i + 2
        elif glob[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif glob[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(glob[i]), i + 1
    return re.compile(out + r"\Z")


def load(root: Path) -> list[Rule]:
    f = root / FILE
    if not f.is_file():
        raise BoundaryError(f"no {FILE} at {root}")
    data = graph.load_yaml_file(f) or {}
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list) or not rules:
        raise BoundaryError(f"{FILE}: rules is a list of {{glob, side, target, why}}")
    out = []
    for i, r in enumerate(rules):
        where = f"{FILE}: rules[{i}]"
        if not isinstance(r, dict) or not isinstance(r.get("glob"), str) or not r["glob"]:
            raise BoundaryError(f"{where}: a mapping with a glob")
        unknown = set(r) - RULE_KEYS
        if unknown:
            raise BoundaryError(f"{where}: unknown key(s) {', '.join(sorted(unknown))} "
                                f"(known: {', '.join(sorted(RULE_KEYS))})")
        if r.get("side") not in SIDES:
            raise BoundaryError(f"{where} ({r['glob']}): side is one of {', '.join(SIDES)}")
        init = r.get("init")
        if init is not None and not (isinstance(init, str) and init.strip()):
            raise BoundaryError(f"{where} ({r['glob']}): init names the wizard step, a string")
        out.append(Rule(r["glob"], r["side"], str(r.get("target") or ""), str(r.get("why") or ""),
                        glob_regex(r["glob"]), str(init or "")))
    return out


def readiness_max(root: Path) -> int | None:
    """boundary.yaml's ``readiness_max``: the most denied terms the engine side may hold (None: no ratchet)."""
    data = graph.load_yaml_file((root / FILE)) or {}
    value = data.get("readiness_max") if isinstance(data, dict) else None
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
        raise BoundaryError(f"{FILE}: readiness_max is a count, 0 or more")
    return value


def tracked(root: Path) -> list[str]:
    """The files git tracks under ``root``, /-separated."""
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, text=True,
                         encoding="utf-8", timeout=30, stdin=subprocess.DEVNULL)
    if out.returncode:
        raise BoundaryError(f"git ls-files failed in {root}: {out.stderr.strip()}")
    return sorted(p for p in out.stdout.split("\0") if p)


def classify(rules: list[Rule], files: list[str]) -> dict:
    """{files: {path: (rule index or None)}, by_side: {side: [paths]}, unclassified: [paths], stale: [globs],
    errors: [...]}: the first matching rule wins."""
    hits = {}
    used = set()
    for path in files:
        idx = next((i for i, r in enumerate(rules) if r.regex.match(path)), None)
        hits[path] = idx
        if idx is not None:
            used.add(idx)
    by_side = {s: [p for p, i in hits.items() if i is not None and rules[i].side == s] for s in SIDES}
    errors = [f"{FILE}: engine rule {r.glob!r} has no target" for r in rules if r.side == "engine" and not r.target]
    errors += [f"{FILE}: {r.side} rule {r.glob!r} has an init: only {' and '.join(INIT_SIDES)} files start a new "
               f"user's brain" for r in rules if r.init and r.side not in INIT_SIDES]
    targets: dict[str, str] = {}
    for p in by_side["engine"]:
        rule = rules[hits[p]]
        if not rule.target:
            continue
        t = rule.target_of(p)
        if t in targets:
            errors.append(f"{p} and {targets[t]} both leave for {t}")
        targets[t] = p
    return {"files": hits, "by_side": by_side, "unclassified": [p for p, i in hits.items() if i is None],
            "stale": [r.glob for i, r in enumerate(rules) if i not in used], "errors": errors}


def term_regex(term: str) -> re.Pattern:
    t = re.escape(term.replace("\\", "/"))
    return re.compile(rf"(?i)(?<![A-Za-z0-9_]){t}(?![A-Za-z0-9_])")


def readiness(root: Path, cfg: config.Config, files: list[str]) -> dict:
    """The denied terms (config.json public.deny) in ``files``: {terms: {category: {term: count}}, files: {path:
    {term: count}}, total, allowed: [paths skipped by public.allow], unread: [binary or unreadable paths]}."""
    terms = [(cat, t, term_regex(t)) for cat, t in config.deny_terms(cfg)]
    allow = config.allowed(cfg)
    out: dict = {"terms": {}, "files": {}, "total": 0, "allowed": [], "unread": []}
    for path in files:
        if any(glob_regex(g).match(path) for g in allow):
            out["allowed"].append(path)
            continue
        try:
            text = (root / path).read_text(encoding="utf-8").replace("\\", "/")
        except (OSError, UnicodeDecodeError):
            out["unread"].append(path)
            continue
        for cat, term, rx in terms:
            n = len(rx.findall(text))
            if n:
                out["terms"].setdefault(cat, {})[term] = out["terms"].get(cat, {}).get(term, 0) + n
                out["files"].setdefault(path, {})[term] = n
                out["total"] += n
    return out


def report(root: Path, cfg: config.Config | None = None) -> dict:
    """The boundary of the repo at ``root``: the classification, each engine file's target, the readiness."""
    rules = load(root)
    files = tracked(root)
    c = classify(rules, files)
    cfg = cfg or config.load(root)
    engine = {p: rules[c["files"][p]].target_of(p) for p in c["by_side"]["engine"]}
    init = {p: rules[c["files"][p]].init for s in INIT_SIDES for p in c["by_side"][s] if rules[c["files"][p]].init}
    repos = (cfg.data.get("public") or {}).get("repos") if isinstance(cfg.data.get("public"), dict) else None
    return {"root": str(root), "rules": len(rules), "files": len(files),
            "counts": {s: len(c["by_side"][s]) for s in SIDES}, "by_side": c["by_side"], "engine_targets": engine,
            "init": init,
            "engine_repo": (repos or [""])[0], "unclassified": c["unclassified"], "stale": c["stale"],
            "errors": c["errors"], "readiness": readiness(root, cfg, c["by_side"]["engine"]),
            "readiness_max": readiness_max(root), "deny_terms": len(config.deny_terms(cfg))}


def over(data: dict) -> int:
    """How many denied terms the engine side holds above readiness_max (0: none, or no ratchet)."""
    cap = data.get("readiness_max")
    return max(0, data["readiness"]["total"] - cap) if cap is not None and data["deny_terms"] else 0


def render(data: dict, *, side: str = "", detail: bool = False) -> list[str]:
    if side:
        files = data["by_side"][side]
        return [f"{p} -> {data['engine_targets'][p]}" if side == "engine" else
                f"{p}  (init: {data['init'][p]})" if p in data["init"] else p for p in files] or [f"(no {side} file)"]
    c = data["counts"]
    started = sum(1 for p in data["by_side"]["personal"] if p in data["init"])
    lines = [f"{FILE}: {data['files']} tracked file(s), {data['rules']} rule(s)",
             f"  engine     {c['engine']:4}  leave for the engine's repo"
             + (f" ({data['engine_repo']})" if data["engine_repo"] else ""),
             f"  personal   {c['personal']:4}  stay here ({started} with an init: the setup wizard writes their first "
             f"version)",
             f"  claude     {c['claude']:4}  the Claude rendering (brain render --target claude writes it)",
             f"  generated  {c['generated']:4}  views written by a command"]
    r = data["readiness"]
    cap = data.get("readiness_max")
    if not data["deny_terms"]:
        lines.append("readiness: no public.deny in config.json, nothing measured")
    elif not r["total"]:
        lines.append(f"readiness: no denied term in the engine side ({data['deny_terms']} term(s) of config.json)"
                     + (f", readiness_max {cap}" if cap is not None else ""))
    else:
        per = ", ".join(f"{t} {n}" for cat in config.DENY for t, n in sorted(r["terms"].get(cat, {}).items(),
                                                                            key=lambda kv: -kv[1]))
        lines.append(f"readiness: {r['total']} denied term(s) in {len(r['files'])} engine file(s): {per}"
                     + (f" (readiness_max {cap})" if cap is not None else ""))
        if detail:
            lines += [f"  {p}: " + ", ".join(f"{t} {n}" for t, n in sorted(hits.items(), key=lambda kv: -kv[1]))
                      for p, hits in sorted(r["files"].items(), key=lambda kv: -sum(kv[1].values()))]
    if r["allowed"]:
        lines.append(f"  excepted by public.allow: {', '.join(r['allowed'])}")
    lines += [f"error: {p}: no rule of {FILE} classifies it (add one: engine, personal, claude or generated)"
              for p in data["unclassified"]]
    lines += [f"error: {e}" for e in data["errors"]]
    if over(data):
        lines.append(f"error: the engine side holds {r['total']} denied term(s), {over(data)} over readiness_max "
                     f"{cap} of {FILE}: take them out (the owner and the personal names come from config.json, "
                     "brain.config), see brain boundary --readiness")
    lines += [f"warning: rule {g!r} classifies no tracked file" for g in data["stale"]]
    return lines


def main(root: Path, *, check: bool = False, side: str = "", detail: bool = False, as_json: bool = False) -> int:
    try:
        data = report(root)
    except BoundaryError as exc:
        print(f"brain boundary: {exc}")
        return 2
    if as_json:
        print(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        print("\n".join(render(data, side=side, detail=detail)))
    return 1 if check and (data["unclassified"] or data["errors"] or over(data)) else 0
