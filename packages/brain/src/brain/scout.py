"""``brain audit --diff``: the scout. What the units a change touches miss, with the full audit's checks (brain.audit)
run on the change's tree and again on its base.

The repo is the git checkout of --repo-dir or the current folder (a worktree resolves to its registered repo through
its main checkout; an unregistered repo is audited with the defaults, its graph checks N/A). The range: from the
newer of merge-base(HEAD, the default branch) and merge-base(HEAD, origin's default branch) to the working tree
(untracked files included); ``--diff BASE`` from merge-base(BASE, HEAD); ``--diff A..B`` commits only (replay,
calibration).

NEW: a finding the base did not have, in any repo of the project: only the change can have made it (a deleted or
renamed module a doc runs or a CodeRef names, a deleted test, a dangling CodeRef added, a console script declared,
an emptied folder a doc still names). LEFT: a finding the base had, on a unit the change touches (the changed modules
and scripts and their commands, the changed docs for doc.dead-ref, the README or pyproject.toml for readme.exists,
the files a CodeRef names); a test's edit touches no module. A light touch (Python equal once imports and docstrings
are dropped, whitespace only elsewhere, a pure rename) never makes a LEFT finding block. Blocking: every NEW finding,
and the LEFT findings of at most --limit units (the repo's scout_limit, default 3; a doc counts once for all its dead
references), the most severe first, then entry, then prod, then path; the other LEFT findings are DEFERred to the
repo's debt item. PENDING, N/A, info and light never block, but for feature.coverage (an info of the full audit:
a command or module of a command registry that no feature names, brain.feature_coverage): NEW on a unit the change
adds, DEFER on a touched one, LEFT there only under config.json audit.feature_coverage_strict. The structure signals (brain.structure: a file past
max_lines, a function past the complexity threshold, a dependency no decision log names, an incomplete shortcut:
marker, a symptom fix with no Root cause: line) join them: NEW, DEFER to the debt item for a file or function already
past its threshold that grows, or justified (a Justified: or Root cause: line in --pr-body or a commit message: shown,
never blocking). A project's migrations: rules (brain.formats: a change of a when file, a model or an SQL schema,
with no new file of an add glob, a migration or a fixture) are NEW on that file, justified the same way. The norm
lints (brain.norms: a subprocess or urlopen without a timeout, a text open() without an
encoding, a naive datetime stored, a secret in a child's argv or env) are info lines on what the change adds, NEW
under config.json audit.norm_lints_strict, and DEFER lines, by file and norm, for those already in a touched file.
Exit code 1 when something is to fix in this PR, 2 for a usage or git error (no base found).
"""

from __future__ import annotations

import ast
import dataclasses
import json
import sys
from pathlib import Path

from . import (audit, docsgraph, feature_coverage, formats, graph, inventory, links, norms, paths, projects, schemadiff,
               structure)
from .inventory import AuditError, git

ORDER = {"entry": 0, "prod": 1, "other": 2, "": 3}
TAGS = ["NEW", "LEFT", "DEFER", "justified", "light", "info"]


def _rank(f: dict) -> tuple:
    return TAGS.index(f["tag"]), f["severity"], ORDER[f["class"]], f["unit"], f["check"]


def resolve(args, root: Path | None) -> tuple[projects.Project, list[projects.Repo], projects.Repo, Path, bool]:
    """(project, its repos, the repo changed, its checkout, registered) for --repo-dir or the current folder."""
    d = Path(args.repo_dir).resolve() if args.repo_dir else (root or Path.cwd())
    top = Path(git(d, "rev-parse", "--show-toplevel").strip()).resolve()
    main = (paths.main_checkout(top) or top).resolve()
    reg = projects.load(root)
    if args.project:
        if args.project not in reg:
            raise AuditError(projects.unloaded(args.project, root)
                             or f"unknown project {args.project!r} (known: {', '.join(reg) or 'none'})")
        reg = {args.project: reg[args.project]}
    for p in reg.values():
        cfgs = projects.repos_of(p)
        for c in cfgs:
            if c.path.resolve() in (main, top):
                if c.path.resolve() == p.root.resolve() and top != main:
                    p = projects.get(p.name, top)   # the project's own repo in a worktree: its stores there
                    cfgs = projects.repos_of(p)
                    c = next(x for x in cfgs if x.path.resolve() == top)
                return p, cfgs, dataclasses.replace(c, path=top), top, True
    print(f"warning: {top} is in no registered project: audited with the defaults, graph checks N/A",
          file=sys.stderr)
    p = projects.for_root(top)
    c = projects.Repo(main.name.lower(), top)
    return p, [c], c, top, False


def changed(top: Path, base: str, new: str = "") -> list[tuple[str, str, str]]:
    """(status, old path, new path) of each change from ``base`` to ``new`` (the working tree when ''), renames
    found (-M), untracked files as added."""
    out = git(top, "diff", "--name-status", "-M", "-z", base, *([new] if new else []), "--").split("\0")
    rows, i = [], 0
    while i < len(out) and out[i]:
        st = out[i]
        if st[0] in "RC":
            rows.append((st, out[i + 1], out[i + 2]))
            i += 3
        else:
            rows.append((st[0], out[i + 1] if st[0] == "D" else "", out[i + 1] if st[0] != "D" else ""))
            i += 2
    if not new:
        for p in git(top, "ls-files", "-z", "--others", "--exclude-standard").split("\0"):
            if p:
                rows.append(("A", "", p))
    return rows


class _Strip(ast.NodeTransformer):
    def visit_Import(self, node):
        return None

    visit_ImportFrom = visit_Import

    def _body(self, node):
        b = node.body
        if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant) and isinstance(b[0].value.value,
                                                                                                     str):
            node.body = b[1:]
        self.generic_visit(node)
        return node

    visit_Module = visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _body


def _shape(text: str) -> str | None:
    try:
        return ast.dump(_Strip().visit(ast.parse(text)), include_attributes=False)
    except (SyntaxError, ValueError):
        return None


def light_touch(top: Path, row: tuple[str, str, str], base: inventory.Tree, new: inventory.Tree,
                new_rev: str) -> bool:
    """A change that cannot have changed behaviour: a pure rename, Python equal once imports and docstrings are
    dropped, whitespace and blank lines only elsewhere."""
    st, old, path = row
    if st == "R100":
        return True
    if st[0] not in "MR":
        return False
    before = base.text(old or path)
    if path.endswith(".py"):
        a, b = _shape(before or ""), _shape(new.text(path) or "")
        return a is not None and a == b
    return not git(top, "diff", "-w", "--ignore-blank-lines", base.rev, *([new_rev] if new_rev else []), "--",
                   old or path, path, allow=(0, 1)).strip()


def _code_ref_file(unit: str) -> tuple[str, list[str]]:
    try:
        repo, path, _ = inventory.parse_code_ref(unit)
    except ValueError:
        return "", []
    return repo.lower(), [f"src/{path}", path]


def _group(f: dict) -> str:
    """The unit a LEFT finding counts against the limit: a doc for its dead references, else the unit."""
    return f["unit"].split("#", 1)[0] if f["check"] == "doc.dead-ref" else f["unit"]


def _old_unit(check: str, unit: str, renamed: dict[str, str]) -> str:
    if check == "doc.dead-ref" and "#" in unit:
        doc, ref = unit.split("#", 1)
        return f"{renamed.get(doc, doc)}#{ref}"
    return renamed.get(unit, unit)


def _new_defer(f: dict, fresh: bool, here: bool, added: set[str], touched: dict[str, bool], strict: bool) -> list:
    """A 'new+defer' finding (feature.coverage) tagged, in the changed repo (``here``) only: NEW on a unit the change
    adds; on a touched unit that had it, DEFER to the debt item, or LEFT (light for a light touch) under the owner's
    opt-in (config.json audit.feature_coverage_strict); nothing for another unit."""
    unit = f["unit"]
    if not here or (unit not in touched and not (fresh and unit in added)):
        return []
    if fresh and unit in added:
        return [{**f, "tag": "NEW"}]
    return [{**f, "tag": ("light" if touched[unit] else "LEFT") if strict else "DEFER"}]


def _base_keys(base: dict) -> set[str]:
    """The keys of the base's findings a fresh one is told from: every one but an info, a 'new+defer' info kept."""
    return {f["key"] for r in base["repos"] for f in r.get("findings", [])
            if f["severity"] != "info" or audit.CHECKS[f["check"]].scout == "new+defer"}


def classify(touched: dict[str, bool], deleted: set[str], added: set[str], target: str, new: dict, base: dict,
             renamed: dict[str, str], limit: int, script_exts: set[str], strict: bool = False) -> list[dict]:
    """Tag each relevant finding NEW, LEFT, DEFER, light or info (advisory); ``touched`` maps a unit to whether its
    touch is light. A finding the base did not have, in any repo, can only come from this change: NEW (a module or
    doc the change deletes or renames, a test it deletes, a CodeRef it adds, a console script it declares...). One
    the base had is LEFT when the change touches its unit (in the changed repo; another repo's CodeRef to a touched
    file); the LEFT units past the limit, most severe and production first, are DEFERred. A 'new+defer' check
    (feature.coverage, info in the full audit) is NEW on an added unit and DEFER on a touched one (LEFT under
    ``strict``: _new_defer)."""
    base_keys = _base_keys(base)
    out = []
    for r in new["repos"]:
        for f in r.get("findings", []):
            check, unit = f["check"], f["unit"]
            mode = audit.CHECKS[check].scout
            if mode == "never":
                continue
            fresh = f["key"] not in base_keys and f"{r['name']}:{check}:{_old_unit(check, unit, renamed)}" \
                not in base_keys
            if mode == "new" and (not fresh or unit not in added):   # coderef.module: an added module only
                continue
            if mode == "new+defer":
                out += _new_defer(f, fresh, r["name"] == target, added, touched, strict)
                continue
            light = False
            if r["name"] != target:   # another repo: its CodeRefs to what this change touches
                repo, files = _code_ref_file(unit) if check == "coderef.dangling" else ("", [])
                hit = repo == target and bool(set(files) & (deleted | set(touched)))
            elif check == "doc.dead-ref":
                doc = unit.split("#", 1)[0]
                hit, light = doc in touched, touched.get(doc, False)
            elif check == "coderef.dangling":
                hit = bool(set(_code_ref_file(unit)[1]) & (deleted | set(touched)))
            elif check == "readme.exists":
                hit = bool({"README.md", "pyproject.toml"} & (set(touched) | deleted))
            else:
                hit, light = unit in touched, touched.get(unit, False)
            if f["severity"] == "info":
                if hit and r["name"] == target:
                    out.append({**f, "tag": "info"})
                continue
            if fresh:
                out.append({**f, "tag": "NEW"})
            elif hit:
                tag = "light" if light else "LEFT"
                if check == "test.script" and Path(unit).suffix not in script_exts:
                    tag = "info"
                    f = {**f, "why": f"{f['why']} (advisory: no test runs a {Path(unit).suffix} script here yet)"}
                out.append({**f, "tag": tag})
    rank: dict[str, tuple] = {}
    for f in out:
        if f["tag"] == "LEFT":
            g = _group(f)
            rank[g] = min(rank.get(g, ("P9", 9, g)), (f["severity"], ORDER[f["class"]], g))
    keep = set(sorted(rank, key=rank.get)[:limit])
    for f in out:
        if f["tag"] == "LEFT" and _group(f) not in keep:
            f["tag"] = "DEFER"
    out.sort(key=_rank)
    return out


def _pr_body(spec: str) -> str:
    """The text of --pr-body: a file, or '-' for stdin ('' when not given)."""
    if not spec:
        return ""
    if spec == "-":
        return sys.stdin.read()
    try:
        return Path(spec).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise AuditError(f"--pr-body {spec}: {exc}") from exc


def _decision_texts(p: projects.Project) -> list[str]:
    out = []
    for f in p.decision_logs:
        try:
            out.append(Path(f).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return out


def _structure(args, p: projects.Project, c: projects.Repo, top: Path, rows: list, base_tree: inventory.Tree,
               new_tree: inventory.Tree, base_rev: str, new_rev: str, root: Path | None,
               touched: dict[str, bool] | None = None, first: str = "") -> list[dict]:
    """The structure signals of the change (brain.structure), with the project's thresholds and decision logs, its
    norm lints (brain.norms, NEW under the owner's opt-in), what its schemas narrow (brain.schemadiff, NEW under
    the owner's opt-in too) and its migrations: glob check (brain.formats: a when file changed with no new add file,
    NEW; ``first``: the project's first repo, the one a rule without repo: names)."""
    body = structure.body_of(top, base_rev, new_rev, _pr_body(getattr(args, "pr_body", None) or ""))
    shape = structure.signals(c.name, rows, base_tree, new_tree, structure.thresholds(p.audit), body,
                              _decision_texts(p))
    return (shape + norms.signals(c.name, rows, base_tree, new_tree, body, norms.strict(root))
            + schemadiff.signals(c.name, rows, base_tree, new_tree, body, schemadiff.strict(root))
            + formats.migration_signals(c.name, first or c.name, formats.migrations_of(p.migrations), rows,
                                        touched or {}, body))


def _reread(p: projects.Project, cfgs: list, c: projects.Repo, top: Path, rows: list, base_rev: str,
            new_rev: str) -> list[dict]:
    """The docs to re-read (brain.docsgraph, info lines): in a store of the changed repo whose links graph is written,
    a doc the change does not touch that cites a node the change edits."""
    main = (paths.main_checkout(top) or top).resolve()
    touched = {x for row in rows for x in row[1:] if x}
    for store in p.stores:
        s = Path(store).resolve()
        rel = next((s.relative_to(b).as_posix() for b in (top.resolve(), main) if s.is_relative_to(b)), None)
        if rel is None:
            continue
        rel = "" if rel == "." else rel   # a store at the repo's root
        here = top / rel if rel else top
        if not docsgraph.applies(here) or not any(t.startswith(f"{rel}/nodes/" if rel else "nodes/") for t in touched):
            continue
        cat = docsgraph.load(top, here, c.name, links.anchor_roots(cfgs, c.name))
        return docsgraph.reread(top, rel, base_rev, new_rev, touched, cat)
    return []


def _tagged(out: list[dict], tag: str) -> int:
    return sum(1 for f in out if f["tag"] == tag)


def _justified(n: int) -> str:
    return f", {n} justified" if n else ""


def base_of(top: Path, spec: str) -> tuple[str, str]:
    """(ref, commit) the change is measured from: merge-base(spec, HEAD); with no spec, the newer merge base of HEAD
    with the local default branch and with origin's (a local main that lags origin would count the PRs merged since
    as this change)."""
    if spec:
        refs = [spec]
    else:
        b = inventory.default_branch(top)
        remote = f"refs/remotes/origin/{b}"
        refs = [b] + ([remote] if git(top, "rev-parse", "--verify", "-q", remote, allow=(0, 1)).strip() else [])
    got = [(ref, git(top, "merge-base", ref, "HEAD", allow=(0, 1)).strip()) for ref in refs]
    got = [(ref, mb) for ref, mb in got if mb]
    if not got:
        raise AuditError(f"no merge base between {refs[0]} and HEAD in {top}")
    best = got[0]
    for ref, mb in got[1:]:
        if mb != best[1] and inventory._run_git(top, ["merge-base", "--is-ancestor", best[1], mb])[0] == 0:
            best = (ref, mb)
    return best[0].replace("refs/remotes/", ""), best[1]


def main(args, root: Path | None) -> int:
    p, cfgs, c, top, registered = resolve(args, root)
    spec = args.diff or ""
    if ".." in spec:
        a, b = spec.split("..", 1)
        base_ref = a
        base_rev = git(top, "rev-parse", "--verify", f"{a}^{{commit}}").strip()
        new_rev = git(top, "rev-parse", "--verify", f"{b or 'HEAD'}^{{commit}}").strip()
    else:
        base_ref, base_rev = base_of(top, spec)
        new_rev = ""
    base_tree = inventory.git_tree(top, base_rev)
    new_tree = inventory.git_tree(top, new_rev) if new_rev else inventory.work_tree(top)
    others = [x for x in cfgs if x.name != c.name]
    trees, _, errors = audit.trees_now(others)
    store_dir = getattr(args, "audit_store", None)
    if store_dir:
        s_top = Path(git(Path(store_dir), "rev-parse", "--show-toplevel").strip()).resolve()
        s_main = (paths.main_checkout(s_top) or s_top).resolve()
        for x in others:
            if x.path.resolve() in (s_main, s_top):
                trees[x.name] = inventory.work_tree(s_top)
    if not registered:
        p.stores = []
    base_dirs = {x.split("/")[0] for x in base_tree.files if "/" in x}   # a folder the change empties still counts
    new = audit.measure(p, cfgs, {**trees, c.name: new_tree}, extra_dirs={c.name: base_dirs})
    base = audit.measure(p, cfgs, {**trees, c.name: base_tree})
    rows = changed(top, base_rev, new_rev)
    deleted = {old for st, old, _ in rows if st[0] in "DR"}
    added = {path for st, _, path in rows if st[0] in "AC"}
    renamed = {path: old for st, old, path in rows if st[0] == "R"}
    touched: dict[str, bool] = {}
    for row in rows:
        if row[2]:
            touched[row[2]] = light_touch(top, row, base_tree, new_tree, new_rev)
    for u in new["facts"][c.name].units:   # a changed module's commands (a test's edit touches no unit)
        if u.kind == "command" and u.path in touched:
            touched.setdefault(u.name, touched[u.path])
    ev = base["facts"][c.name].evidence
    script_exts = {Path(u.path).suffix for u in base["facts"][c.name].units
                   if u.kind == "script" and inventory.script_evidence(u, ev)[0]}
    limit = args.limit if args.limit is not None else c.scout_limit
    out = classify(touched, deleted, added, c.name, new, base, renamed, limit, script_exts,
                   feature_coverage.strict(root))
    out = sorted(out + _structure(args, p, c, top, rows, base_tree, new_tree, base_rev, new_rev, root, touched,
                                  cfgs[0].name if cfgs else c.name)
                 + _reread(p, cfgs, c, top, rows, base_rev, new_rev), key=_rank)
    n_new = sum(1 for f in out if f["tag"] == "NEW")
    n_left = sum(1 for f in out if f["tag"] == "LEFT")
    n_defer = sum(1 for f in out if f["tag"] == "DEFER")
    n_just = _tagged(out, "justified")
    item = audit.item_id(c)
    if args.json:
        print(json.dumps({"scout": 1, "ruleset": audit.RULESET, "project": p.name, "repo": c.name,
                          "base": base_rev, "base_ref": base_ref, "new": new_rev or "worktree", "findings": out,
                          "new_findings": n_new, "left": n_left, "deferred": n_defer, "justified": n_just,
                          "item": item, "structure": structure.thresholds(p.audit)},
                         ensure_ascii=False, indent=1, sort_keys=True))
        return 1 if n_new + n_left else 0
    print(f"== scout {p.name}/{c.name}: {base_ref}@{base_rev[:7]}..{new_rev[:7] or 'worktree'}  (rules "
          f"{audit.RULESET}, {len(rows)} file(s) changed)")
    for f in out:
        cls = f" {f['class']}" if f["class"] else ""
        sev = "" if f["severity"] == "info" else f" {f['severity']}"
        print(f"{f['tag']:<6}{sev} {f['check']:<16} {f['unit']}{cls}: {f['why']}"
              + (f" -> {f['fix']}" if f["fix"] and f["tag"] in ("NEW", "LEFT") else "")
              + (f" -> {item}" if f["tag"] == "DEFER" else ""))
    if n_defer:
        store = p.stores[0] if p.stores else None
        if store is None or not (store / "schema.yaml").is_file() or item not in graph.node_index(store):
            print(f"DEFER  {item} does not exist: brain --project {p.name} item add {item} --title \"{c.name} up to "
                  f"the standard (brain audit debt): by batches, production first\" --prop priority_proposed=P2")
    r = next((x for x in new["repos"] if x["name"] == c.name), {})
    pend = [x["check"] for x in r.get("not_measured", [])]
    if pend:
        print(f"PENDING {', '.join(pend)} (not asked: a generator measures them)")
    if not registered:
        print("N/A    coderef.dangling, coderef.module (an unregistered repo has no code store)")
    for name, why in errors.items():
        print(f"N/A    {name}: {why}")
    print(f"scout: {n_new + n_left} to fix in this PR ({n_new} NEW, {n_left} LEFT), {n_defer} deferred"
          f"{_justified(n_just)}; then brain audit --diff again")
    return 1 if n_new + n_left else 0
