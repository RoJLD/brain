"""brain audit's measure (brain.audit): one project's repos read at their committed state, each repo's findings
(:func:`measure`, :func:`trees_now`), its waivers and stale waive globs."""

from __future__ import annotations

import ast
import fnmatch
import os
import posixpath
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import audit_checks as checks
from . import config, features, inventory, links, moves, projects, public, standards, testcov
from .audit_checks import SEVERITIES, _registries, finding, generated_doc
from .inventory import AuditError

README_LINES = 10
SECTIONS = {"install": ("install", "setup", "getting started"),
            "usage": ("usage", "quick start", "quickstart", "example", "commands"),
            "tests": ("test", "development", "contributing")}
DOC_PATH = re.compile(r"(?<![\w./\\-])((?:[\w.-]+/)+[\w.-]*[\w-]\.(?:py|ps1|sh|md|yaml|psd1))(?![\w-])")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*)$")
BACKTICK = re.compile(r"`([^`\s]+)`")
TICK_DOTTED = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")
FILE_EXTS = {"py", "md", "yaml", "yml", "json", "jsonl", "toml", "txt", "csv", "parquet", "ps1", "psd1", "psm1",
             "sh", "bat", "cmd", "ipynb", "html", "log", "lock", "cfg", "ini", "exe"}
EXTERNAL = re.compile(r"https?://(?:www\.)?(?:github\.com|gitlab\.com|bitbucket\.org)/[\w.-]+/([\w.-]+)")


# --- measuring a project ---

def _rel(path: Path, base: Path) -> str | None:
    try:
        rel = os.path.relpath(path, base)
    except ValueError:  # another drive
        return None
    return None if rel.startswith("..") else Path(rel).as_posix()


def _store_refs(p: projects.Project, cfgs: list[projects.Repo]) -> list[tuple[str, str]]:
    out = []
    for s in p.stores:
        for c in cfgs:
            rel = _rel(s, c.path)
            if rel is not None:
                out.append((c.name, rel))
                break
    return out


def _chain(depth_chain) -> str:
    depth, chain = depth_chain
    if not chain:
        return ""
    return " > ".join(("...",) + chain[-3:] if len(chain) > 4 else chain)


def _docs_index(rf: inventory.RepoFacts) -> dict:
    """What the docs set names: words, dotted names (a `make <target>` names the modules its recipe runs with -m),
    file paths (and their suffixes), backticked words and the leading parts of a backticked dotted name (a catalog's
    `stationarity.adf_test` names the module stationarity; `config.yaml` names no module), and the text itself."""
    words: set = set()
    dotted: set = set()
    ticks: set = set()
    files: dict = {}
    texts = []
    make = inventory.make_targets(rf.tree)
    for d in rf.docs:
        text = rf.tree.text(d) or ""
        texts.append(text)
        words.update(inventory.WORD.findall(text))
        dotted.update(inventory.DOTTED.findall(text))
        dotted.update(inventory.DASH_M.findall(text))   # python -m <package>
        for target in inventory.MAKE_CALL.findall(text):
            dotted.update(make.get(target, ()))
        for tok in BACKTICK.findall(text):
            ticks.add(tok)
            m = TICK_DOTTED.match(tok)
            if m and m.group(0).rsplit(".", 1)[1].lower() not in FILE_EXTS:
                parts = m.group(0).split(".")
                ticks.update(".".join(parts[:i]) for i in range(1, len(parts)))
        inventory.text_tokens(text, {}, files, d)
    return {"words": words, "dotted": dotted, "files": files, "ticks": ticks, "text": "\n".join(texts)}


def _named(files: dict, path: str) -> bool:
    """A doc names ``path``, or a path ending like it (hooks/capture.sh names plugins/x/hooks/capture.sh)."""
    segs = path.split("/")
    return any("/".join(segs[i:]) in files for i in range(len(segs)))


def _documented(u: inventory.Unit, rf: inventory.RepoFacts, docs: dict, shims: dict) -> bool:
    """cmd.documented: a console script named as a word, or its module, or its file (a package.json bin: also the
    README of its package); a command module by dotted path, -m, file path or backticked stem, or through a shim
    script of it that the docs name (the hook capture.sh runs capture.py, which runs brain.capture)."""
    if u.name in rf.console:
        return _script_documented(u, rf, docs)
    return _module_named(u, rf, docs) or any(_shim_named(rf.tree, s, docs) for s in shims.get(u.path, []))


def _script_documented(u: inventory.Unit, rf: inventory.RepoFacts, docs: dict) -> bool:
    """A console script: its name as a word, its module, its file (or the file's name in the text), or the README
    of the package whose package.json bin it is."""
    target = rf.console[u.name]
    if u.name in docs["words"] or target in docs["dotted"] or _named(docs["files"], target):
        return True
    base = target.rsplit("/", 1)[-1]
    if "." in base and re.search(rf"(?<![\w.-]){re.escape(base)}(?![\w-])", docs["text"]):
        return True
    pkg = posixpath.dirname(rf.bins.get(u.name, ""))
    return bool(pkg) and f"{pkg}/README.md" in rf.docs


def _module_named(u: inventory.Unit, rf: inventory.RepoFacts, docs: dict) -> bool:
    """A command module by dotted path, file path (from the repo or from its package root) or backticked stem."""
    root = rf.root_of.get(u.path, "")
    return bool(u.name in docs["dotted"] or _named(docs["files"], u.path) or u.name.split(".")[-1] in docs["ticks"]
                or (root and _named(docs["files"], u.path[len(root) + 1:])))


def _shim_named(t: inventory.Tree, shim: str, docs: dict) -> bool:
    """The docs name a file of the shim's folder with the shim's stem (capture.sh for the shim capture.py)."""
    folder, stem_ = posixpath.dirname(shim), posixpath.basename(shim).rsplit(".", 1)[0]
    same = [p for p in t.files if posixpath.dirname(p) == folder and posixpath.basename(p).rsplit(".", 1)[0] == stem_]
    return any(_named(docs["files"], p) for p in same)


def _parsers_added(text: str) -> list[str]:
    """The parsers a Python file adds itself: the name of each add_parser call ("?" when it is not a literal)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    calls = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "add_parser"), key=lambda n: (n.func.end_lineno, n.func.end_col_offset))
    return [str(n.args[0].value) if n.args and isinstance(n.args[0], ast.Constant) else "?" for n in calls]


def _imports_register(text: str) -> bool:
    """A module-level import binds the name register (from ._impl import register; inventory.has_symbol reads
    definitions only)."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    return any((a.asname or a.name) == "register" for s in tree.body if isinstance(s, ast.ImportFrom) for a in s.names)


def _unregistered(t: inventory.Tree, pkg: str) -> list[str]:
    """The modules of ``pkg``commands/ (not the ``_`` helpers) that define or import no register."""
    mods = [p for p in sorted(t.files) if posixpath.dirname(p) == f"{pkg}commands" and p.endswith(".py")]
    return [p for p in mods if not posixpath.basename(p).startswith("_")
            and inventory.has_symbol(t, p, "register") is False and not _imports_register(t.text(p) or "")]


def registry_findings(repo: str, rf: inventory.RepoFacts) -> list[dict]:
    """cmd.registry (wi-brain-cli-registry): in a package whose commands/ lists its own modules (a command registry,
    brain.commands), the cli.py beside it adds no parser itself, and every module of commands/ but the ``_`` ones
    (helpers) defines register: a command is a module of the registry, never a line of a shared file."""
    t = rf.tree
    units = {u.path: u for u in rf.units if u.kind == "module"}
    out = []
    for pkg in _registries(t):
        cli = f"{pkg}cli.py"
        names = _parsers_added(t.text(cli) or "") if t.has(cli) else []
        if names:
            shown = ", ".join(names[:5]) + ("..." if len(names) > 5 else "")
            out.append(finding(repo, "cmd.registry", cli, f"{cli} adds {len(names)} parser(s) itself, outside the "
                               f"command registry: {shown}", f"make each command a module of {pkg}commands/ (its "
                               "register, run or early)", units.get(cli)))
        out += [finding(repo, "cmd.registry", path, f"{path} is a command module with no register: brain never adds "
                        "its command", "define register(sub, ctx), or name it _<name>.py (a helper, not a command)",
                        units.get(path)) for path in _unregistered(t, pkg)]
    return out


def _readme(rf: inventory.RepoFacts) -> str:
    return next((p for p in sorted(rf.tree.files) if "/" not in p and p.lower() == "readme.md"), "")


def _headings(text: str) -> list[str]:
    out, fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        elif not fence:
            m = HEADING.match(line)
            if m:
                out.append(m.group(1).strip().lower())
    return out


def _test_dir(rf: inventory.RepoFacts) -> str:
    dirs = sorted({t.split("/", 1)[0] for t in rf.tests if "/" in t})
    return "tests" if "tests" in dirs or not dirs else dirs[0]


_TOKENS: dict[tuple[str, float], set[str]] = {}   # registry file and its mtime -> its repo tokens (the trend's weeks)


def _repo_tokens(p: projects.Project, cfgs: list[projects.Repo]) -> set[str] | None:
    """The repo tokens a CodeRef may name: the project's own repos (cloned here or not) and every one of the registry
    the project came from (projects.repo_tokens at its registry_dir). None when that registry is unknown or does not
    load: then no CodeRef is called unregistered (not measured, never a false P0)."""
    if p.registry_dir is None:
        return None
    f = projects.registry_file(p.registry_dir)
    try:
        key = (str(f), f.stat().st_mtime) if f else ("", 0.0)
        if key not in _TOKENS:
            _TOKENS[key] = projects.repo_tokens(p.registry_dir)
    except (OSError, ValueError, yaml.YAMLError):
        return None
    return _TOKENS[key] | {c.name.lower() for c in cfgs} | {c.folder.lower() for c in cfgs if c.folder}


def measure(p: projects.Project, cfgs: list[projects.Repo], trees: dict[str, inventory.Tree],
            only: set[str] | None = None, layered: set[str] | None = None,
            extra_dirs: dict[str, set] | None = None, linked: dict | None = None,
            featured: bool | None = None, coverage: dict | None = None, stale: bool = True) -> dict:
    """Every check on every repo of ``p`` that has a tree (its findings only for the repos in ``only`` when given):
    the project's result, as the JSON output carries it. ``layered``: the repos whose store has a code layer, given
    by the trend from today's measure (a layer added since then is a rule of today, not a rise of the debt);
    ``linked``, likewise, the repos whose own store takes the Doc and Test links (doc.links, test.links), and
    ``featured``, whether the project's store has the Feature type (then a week before it has no feature), and
    ``coverage``, each repo's coverage summary (test.coverage: a summary committed since is a rule of today).
    ``extra_dirs``: more top-level folders whose paths a doc names are checked (the scout passes the base tree's, so
    a folder a change empties still has its dead references). ``stale``: waive.stale measured (the trend turns it
    off: today's waive globs against a past week's tree would count a file added since as a stale glob then, and its
    fix as a fall of the debt)."""
    moved = _moved(p)
    registered = _repo_tokens(p, cfgs)   # before the filter: a repo of the project not cloned here is registered
    cfgs = [c for c in cfgs if c.name in trees]
    feats, featured = _features(p, cfgs, trees, featured)
    facts = {c.name: inventory.collect(trees[c.name], c.name, c.lang, c.roots, c.waive) for c in cfgs}
    idx = inventory.Index.build(facts)
    tops = idx.top_packages()
    missing = _classify(cfgs, facts, idx)
    stores = inventory.code_stores(facts, _store_refs(p, cfgs))
    mod_evidence = _mod_evidence(cfgs, facts, idx, tops)
    refs = _code_refs(stores, facts, registered)
    if layered is None:
        layered = _layered(stores, facts)
    if linked is None:
        linked = _linked_stores(p, cfgs, trees)
    if coverage is None:
        coverage = _coverage(cfgs, linked, trees)
    out_repos = []
    for c in cfgs:
        if only is not None and c.name not in only:
            continue
        ctx = {"rf": facts[c.name], "idx": idx, "store": linked.get(c.name), "cache": {}, "cfg": c,
               "features": feats["features"], "trees": trees, "project": p, "moved": moved, "stale": stale,
               "flabel": feats["flabel"], "fhome": feats["fhome"], "fpublic": feats["fpublic"],
               "fstrict": feats["fstrict"], "coverage": coverage.get(c.name),
               "mod_ev": {path: v for (r, path), v in mod_evidence.items() if r == c.name}}
        out_repos.append(_repo_result(c, facts[c.name], idx, tops, mod_evidence, facts, refs.dangling.get(c.name, []),
                                      sorted(set(refs.unregistered.get(c.name, []))), refs.covered, layered,
                                      missing.get(c.name, []), (extra_dirs or {}).get(c.name, set()), ctx))
    return {"name": p.name, "root": str(p.root), "repos": out_repos, "counts": _sum(out_repos), "facts": facts,
            "mod_evidence": mod_evidence, "layered": layered, "linked": linked, "featured": featured,
            "coverage": coverage}


def _features(p: projects.Project, cfgs: list[projects.Repo], trees: dict[str, inventory.Tree],
              featured: bool | None) -> tuple[dict, bool]:
    """What the feature checks read (:func:`_feature_model`): the model (an empty one when ``featured`` is true and
    no store gives one, None when it is false), its store's folder, the repos that hold it, the public repos and
    whether only their render passes; and ``featured`` itself (when None: whether a store has the Feature type)."""
    fm, flabel, fhome = _feature_model(p, cfgs, trees)
    fpublic, fstrict = _public_repos(p, cfgs) if fm is not None else (set(), False)
    if featured is None:
        featured = fm is not None
    return {"features": (fm or features.Model()) if featured else None, "flabel": flabel, "fhome": fhome,
            "fpublic": fpublic, "fstrict": fstrict}, featured


def _seeds(cfgs: list[projects.Repo], facts: dict[str, inventory.RepoFacts]) -> dict[str, list[str]]:
    """The closure's seeds by repo: its declared entries, else every console script of a production repo."""
    seeds = {}
    for c in cfgs:
        if c.entry is not None:
            seeds[c.name] = list(c.entry)
        elif c.production:
            seeds[c.name] = [f"script:{n}" for n in facts[c.name].console]
    return seeds


def _classify(cfgs: list[projects.Repo], facts: dict[str, inventory.RepoFacts], idx: inventory.Index) -> dict:
    """The production closure from the seeds: each unit's class (entry, prod) and chain set on its repo's facts, and
    a production repo that no entry reaches marked no_entry; returns the seeds that name nothing, by repo."""
    seeds = _seeds(cfgs, facts)
    reached, missing = inventory.closure(facts, seeds, idx)
    hit_repos = {r for r, _ in reached}
    for c in cfgs:
        seeded = len(missing.get(c.name, [])) < len(seeds.get(c.name, []))
        rf = facts[c.name]
        # conservative: a production repo (listed, or with declared entries) that no entry reaches is all production
        rf.no_entry = (c.production or c.entry is not None) and not seeded and c.name not in hit_repos
        _classify_units(rf, c.name, reached)
    return missing


def _classify_units(rf: inventory.RepoFacts, name: str, reached: dict) -> None:
    for u in rf.units:
        got = reached.get((name, u.path))
        if rf.no_entry:
            u.cls, u.chain = "prod", "no entry declared"
        elif got:
            u.cls, u.chain = ("entry" if got[0] <= 1 else "prod"), _chain(got)


def _mod_evidence(cfgs: list[projects.Repo], facts: dict[str, inventory.RepoFacts], idx: inventory.Index,
                  tops: set) -> dict[tuple[str, str], tuple[str, list]]:
    """Each unit's test evidence by (repo, path) (inventory.unit_evidence, which also sets each repo's evidence and
    reach on its facts)."""
    out: dict[tuple[str, str], tuple[str, list]] = {}
    for c in cfgs:
        for path, got in inventory.unit_evidence(facts[c.name], idx, tops).items():
            out[(c.name, path)] = got
    return out


@dataclass
class _Refs:
    """What the active CodeRefs of a project's code stores say (:func:`_code_refs`): the files they cover, by the
    repo that holds them; by store repo, the repos they name that no tree here measures (another project's, or one
    not cloned here) and the coderef.dangling findings."""
    covered: dict[str, set] = field(default_factory=dict)
    unregistered: dict[str, list] = field(default_factory=dict)
    dangling: dict[str, list] = field(default_factory=dict)

    def dangle(self, repo: str, cid: str, why: str, fix: str) -> None:
        self.dangling.setdefault(repo, []).append(finding(repo, "coderef.dangling", cid, why, fix))


def _code_refs(stores: list, facts: dict[str, inventory.RepoFacts], registered: set[str] | None) -> _Refs:
    refs = _Refs()
    for st in stores:
        for cid, status in st.code_refs:
            if status == "active":
                _code_ref(refs, st, cid, facts, registered)
    return refs


def _code_ref(refs: _Refs, st, cid: str, facts: dict[str, inventory.RepoFacts], registered: set[str] | None) -> None:
    """One active CodeRef of the store ``st``: malformed; in a repo no tree here holds (registered elsewhere, or a
    registry that does not tell: not measured); in a repo no project registers (P0, ruleset 11); or the file it
    covers, dangling when the file or its symbol is gone."""
    try:
        repo, path, sym = inventory.parse_code_ref(cid)
    except ValueError as exc:
        refs.dangle(st.repo, cid, f"malformed CodeRef id: {exc}", "fix the id")
        return
    target = facts.get(repo.lower())
    if target is None and (registered is None or repo.lower() in registered):   # another project's repo,
        # one not cloned here, or a registry that does not tell
        refs.unregistered.setdefault(st.repo, []).append(repo)
        return
    if target is None:   # no project registers it: nothing will ever measure it (P0, ruleset 11)
        refs.dangle(st.repo, cid, f"{repo} is a repo no project registers (projects.yaml repos:)",
                    f"point it at a registered repo (code:<repo>:<path>), register the repo in a project's repos:, "
                    f"or retire it (status: retired) in {st.repo}/{st.path}")
        return
    t = target.tree
    file = f"src/{path}" if t.has(f"src/{path}") else path
    refs.covered.setdefault(target.name, set()).add(file)
    why = _gone(t, target.name, file, path, sym)
    if why:
        refs.dangle(st.repo, cid, why,
                    f"point it at the moved code, or retire it (status: retired) in {st.repo}/{st.path}")


def _gone(t: inventory.Tree, repo: str, file: str, path: str, sym: str) -> str:
    """Why a CodeRef's file or symbol is not in its repo's tree ('' when both are there)."""
    if not t.has(file):
        return f"neither src/{path} nor {path} in {repo}"
    if not sym:
        return ""
    ok = inventory.has_symbol(t, file, sym)
    return "" if ok else f"{file} does not parse" if ok is None else f"{sym} is not defined in {file}"


def _layered(stores: list, facts: dict[str, inventory.RepoFacts]) -> set[str]:
    """The repos whose node a code store with a code layer holds (repo-<name>)."""
    return {name for st in stores if st.code_layer for name in facts if f"repo-{name}" in st.repo_nodes}


def _coverage(cfgs: list[projects.Repo], linked: dict, trees: dict[str, inventory.Tree]) -> dict:
    """Each repo's coverage summary (brain.testcov), read from the store that takes its links."""
    return {c.name: testcov.load(trees[linked[c.name][2]], linked[c.name][0], c.name)
            for c in cfgs if c.name in linked and linked[c.name][2] in trees}


def _feature_model(p: projects.Project, cfgs: list[projects.Repo],
                   trees: dict[str, inventory.Tree]) -> tuple[features.Model | None, str, set[str]]:
    """The Feature nodes of the project's stores with the Feature type, read from the trees (committed state), the
    first such store's folder (FEATURES.md names it) and the repos that hold them (brain sync renders their
    FEATURES.md; another repo's is rendered into its checkout); None when no store has the type."""
    models, label, home = [], "", set()
    for repo, rel in _store_refs(p, cfgs):
        if repo not in trees:
            continue
        try:
            m = features.load_tree(trees[repo], rel, repo)
        except features.FeatureError as exc:
            raise AuditError(f"{repo}/{rel}: {exc}") from exc
        if m is not None:
            models.append(m)
            label = label or rel
            home.add(repo)
    return (features.merge(models) if models else None), label or "notes/graph", home


def _public_repos(p: projects.Project, cfgs: list[projects.Repo]) -> tuple[set[str], bool]:
    """(the project's repos whose checkout is a clone of a public repo (config.json public.repos): their FEATURES.md
    is the public render; whether only that render passes, config.json features.public_strict)."""
    cfg = config.load(p.root)
    repos = {c.name for c in cfgs if features.public_checkout(c.path, cfg)} if public.public_repos(cfg) else set()
    return repos, features.public_strict(cfg)


def _store_types(t: inventory.Tree, rel: str) -> list[str]:
    schema = inventory._load_yaml(t, f"{rel}/schema.yaml")
    types = set(schema.get("node_types") or []) if isinstance(schema, dict) else set()
    return sorted(types & set(links.TYPES))


def _linked_stores(p: projects.Project, cfgs: list[projects.Repo], trees: dict[str, inventory.Tree]) -> dict:
    """Repo -> (the folder of the store that takes its links, the Doc, Test and Workflow types its schema has, the
    repo that holds it): its own store (a declared store of the project inside the repo, else its notes/graph), else
    the first store of the project, held by another repo, that takes the links and whose CodeRefs name it (brain sync
    derives its links there, brain.links)."""
    refs = _store_refs(p, cfgs)
    out = {}
    for c in cfgs:
        t = trees[c.name]
        cands = [r for n, r in refs if n == c.name] + ["notes/graph"]
        rel = next((x for x in cands if t.has(f"{x}/schema.yaml")), "")
        if rel:
            out[c.name] = (rel, _store_types(t, rel), c.name)
    for c in cfgs:
        if c.name in out:
            continue
        for holder, rel in refs:
            h = trees.get(holder)
            if holder == c.name or h is None or not h.has(f"{rel}/schema.yaml"):
                continue
            types = _store_types(h, rel)
            if {"Doc", "Test"} & set(types) and c.name in links.coded_repos(links.store_nodes(h, rel)):
                out[c.name] = (rel, types, holder)
                break
    return out


def _sum(repos: list[dict]) -> dict:
    return {s: sum(r.get("counts", {}).get(s, 0) for r in repos) for s in SEVERITIES + ("info",)}


def _moved(p: projects.Project) -> list:
    """config.json's table of moves (brain.moves), read from the brain whose registry the project came from (its
    registry_dir, else its root); [] when it does not load."""
    try:
        return moves.table(config.load(p.registry_dir or p.root))
    except (OSError, ValueError):
        return []


def _moved_refs(name: str, t, docs, moved: list) -> list[dict]:
    """doc.dead-ref for each doc line that names a prefix config.json's table of moves says moved
    (wi-brain-moved-paths): once per doc and old prefix, with the new one to write."""
    found, seen = [], set()
    for d in docs if moved else []:
        for _, n, m in moves.scan_text(d, t.text(d) or "", moved):
            if (d, m.old) not in seen:
                seen.add((d, m.old))
                found.append(finding(name, "doc.dead-ref", f"{d}#{m.old}", f"{d}:{n} names {m.old}: {m.says()}",
                                     f"write {m.new}"))
    return found


@dataclass
class _Repo:
    """One repo as its checks read it (:func:`_repo_result`): what :func:`measure` gathered for it, and what a check
    leaves for a later one (the scripts that are shims of a module, by module, which cmd.documented reads)."""
    c: projects.Repo
    rf: inventory.RepoFacts
    idx: inventory.Index
    tops: set
    mod_evidence: dict
    facts: dict
    dangling: list
    covered: dict
    layered: set
    extra_dirs: set
    ctx: dict | None
    shims: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.c.name

    @property
    def t(self) -> inventory.Tree:
        return self.rf.tree

    def has_code(self) -> bool:
        return bool(self.rf.units or self.rf.console)

    def modules(self) -> list:
        return [u for u in self.rf.units if u.kind == "module"]

    def docs(self):
        """The docs whose paths are checked: a generated doc's paths are its sources' to fix."""
        return (d for d in self.rf.docs if not generated_doc(self.t, d))


def _readme_checks(r: _Repo) -> list[dict]:
    """readme.exists, readme.sections."""
    found, readme = [], _readme(r.rf)
    text = (r.t.text(readme) if readme else "") or ""
    n = sum(1 for ln in text.splitlines() if ln.strip())
    if n < README_LINES:
        found.append(finding(r.name, "readme.exists", "README.md",
                             f"README.md has {n} non-blank line(s) ({README_LINES} at least)" if readme
                             else "no README.md at the root", "write README.md: what it is, install, usage, tests"))
    if readme and r.has_code():
        heads = _headings(text)
        for group, words in SECTIONS.items():
            if not any(re.search(rf"\b{w}", h) for h in heads for w in words):
                found.append(finding(r.name, "readme.sections", f"README.md#{group}",
                                     f"no heading for {group} ({', '.join(words)})", f"add a {group} section"))
    return found


def _dash_m_refs(r: _Repo, d: str, line: str, seen: set) -> list[dict]:
    """doc.dead-ref for each ``-m <dotted>`` of a doc line that names no module (or a package with no __main__.py) of
    the project's top-level packages."""
    found = []
    for mod in inventory.DASH_M.findall(line):
        if mod.split(".")[0] in r.tops and not r.idx.module_file(mod, main=True) and mod not in seen:
            seen.add(mod)
            what = "a package with no __main__.py" if mod in r.idx.packages else "no such module"
            found.append(finding(r.name, "doc.dead-ref", f"{d}#-m {mod}", f"{d} runs -m {mod}: {what}",
                                 "fix or remove the reference"))
    return found


@dataclass
class _Paths:
    """What a doc's path references are checked against (:func:`_path_refs`)."""
    top_dirs: set      # the repo's top-level folders (and the scout's extra ones)
    owners: dict       # top-level package -> the repo that holds it
    own: set           # the repo's own top-level packages
    known: set         # the project's repos, lowercase, and this repo's folder

    @classmethod
    def of(cls, r: _Repo) -> _Paths:
        owners: dict[str, str] = {}
        for other, f in r.facts.items():
            for d in list(f.modules) + list(f.packages):
                owners.setdefault(d.split(".")[0], other)
        return cls(top_dirs={p.split("/")[0] for p in r.t.files if "/" in p} | set(r.extra_dirs), owners=owners,
                   own={d.split(".")[0] for d in list(r.rf.modules) + list(r.rf.packages)},
                   known={x.lower() for x in r.facts} | {getattr(r.c, "folder", "").lower()})


def _missing_path(r: _Repo, d: str, ref: str) -> bool:
    """Whether a path a doc names is in no tree of the project, beside the doc nor from the root."""
    here = inventory._norm(f"{d.rsplit('/', 1)[0]}/{ref}") if "/" in d else ref
    return not (r.t.has(ref) or r.t.has(here) or any(o.tree.has(ref) for o in r.facts.values()))


def _path_refs(r: _Repo, d: str, line: str, seen: set, paths: _Paths) -> list[dict]:
    """doc.dead-ref for each repo path of a doc line that no tree has: P2 when the path is another repo's (a stale
    cross-repo reference); nothing on a row about another project's repository (its paths are that repo's)."""
    ext = EXTERNAL.search(line)
    if ext and ext.group(1).lower().removesuffix(".git") not in paths.known:
        return []
    found = []
    for m in DOC_PATH.finditer(line):
        ref, before = m.group(1), line[m.start() - 1] if m.start() else ""
        if ref in seen or ref.split("/")[0] not in paths.top_dirs or (before and before in "<*{$"):
            continue
        if not _missing_path(r, d, ref):
            continue
        seen.add(ref)
        segs = ref.split("/")
        pkg = segs[1] if segs[0] == "src" and len(segs) > 2 else segs[0]
        owner = paths.owners.get(pkg, r.name) if pkg not in paths.own else r.name
        if owner != r.name:
            found.append(finding(r.name, "doc.dead-ref", f"{d}#{ref}", f"{d} names {ref}, a path of {owner}: "
                                 f"not there either (a stale cross-repo reference)",
                                 "fix or remove the reference", sev="P2"))
        else:
            found.append(finding(r.name, "doc.dead-ref", f"{d}#{ref}", f"{d} names {ref}: no such file",
                                 "fix or remove the reference"))
    return found


def _doc_dead_refs(r: _Repo) -> list[dict]:
    """doc.dead-ref: the ``-m`` lines and the paths each doc names that do not exist, once per doc."""
    found, paths = [], _Paths.of(r)
    for d in r.docs():
        seen: set = set()
        for line in (r.t.text(d) or "").splitlines():
            found += _dash_m_refs(r, d, line, seen)
            found += _path_refs(r, d, line, seen, paths)
    return found


def _moved_dead_refs(r: _Repo) -> list[dict]:
    """doc.dead-ref for the prefixes config.json's table of moves says moved (:func:`_moved_refs`)."""
    return _moved_refs(r.name, r.t, r.docs(), (r.ctx or {}).get("moved") or [])


def _dangling_refs(r: _Repo) -> list[dict]:
    """coderef.dangling: the repo's store's CodeRefs that name no file or symbol (found by :func:`measure`)."""
    return r.dangling


def _module_test(r: _Repo, u, tdir: str) -> list[dict]:
    """test.module for one module: no test (P1), only an indirect one (P2), or how it is tested (info)."""
    via, tests = r.mod_evidence[(r.name, u.path)]
    s = inventory.stem(u)
    if not via:
        return [finding(r.name, "test.module", u.path, f"no test_{s}.py or test_*_{s}.py, no test imports "
                        f"{u.name}", f"add {tdir}/test_{s}.py", u)]
    if via == "indirect (unnamed)":
        return [finding(r.name, "test.module", u.path, f"no direct test: only reached through what "
                        f"{', '.join(tests[:2])} import", f"add {tdir}/test_{s}.py", u, via, "P2")]
    if via != "name":
        return [finding(r.name, "test.module", u.path, f"tested by {', '.join(tests[:3])}", "", u, via, "info")]
    return []


def _script_test(r: _Repo, u, tdir: str) -> list[dict]:
    """test.script for one script: no test runs it, or how it is tested (info); a script that is a shim of a module
    of the repo is recorded in ``r.shims`` and takes the module's test."""
    via, tests = inventory.script_evidence(u, r.rf.evidence)
    shim = inventory.shim_target(u, r.rf, r.idx)
    if shim and shim[0] == r.name:
        r.shims.setdefault(shim[1], []).append(u.path)
    if not via and shim and r.mod_evidence.get(shim, ("", []))[0] not in ("", "indirect (unnamed)"):
        via, tests = f"shim of {r.idx.dotted_of.get(shim, shim[1])}", r.mod_evidence[shim][1]
    s = u.name.rsplit(".", 1)[0]
    if not via:
        pester = f" or {s}.Tests.ps1 (Pester)" if u.name.endswith((".ps1", ".psm1")) else ""
        why = f"no test runs {u.name} (named in {', '.join(tests[:2])}, never run)" if tests \
            else f"no test names {u.name}"
        return [finding(r.name, "test.script", u.path, why,
                        f"add {tdir}/test_{s.replace('-', '_')}.py{pester} that runs it", u)]
    if via != "name":
        return [finding(r.name, "test.script", u.path, f"tested by {', '.join(tests[:3])}", "", u, via, "info")]
    return []


def _test_checks(r: _Repo) -> list[dict]:
    """test.module, test.script, unit by unit (before cmd.documented, which reads the shims they record)."""
    found, tdir = [], _test_dir(r.rf)
    for u in r.rf.units:
        if u.kind == "module":
            found += _module_test(r, u, tdir)
        elif u.kind == "script":
            found += _script_test(r, u, tdir)
    return found


def _cmd_documented(r: _Repo) -> list[dict]:
    """cmd.documented: each command no doc of the docs set names."""
    docs = _docs_index(r.rf)
    return [finding(r.name, "cmd.documented", u.name, f"no doc of the docs set names {u.name}",
                    f"document {u.name} in README.md or docs/ (what it does, its options)", u)
            for u in r.rf.units if u.kind == "command" and not _documented(u, r.rf, docs, r.shims)]


def _cmd_registry(r: _Repo) -> list[dict]:
    """cmd.registry (:func:`registry_findings`)."""
    return registry_findings(r.name, r.rf)


def _coderef_module(r: _Repo) -> list[dict]:
    """coderef.module: each module no CodeRef names, in a repo whose store has a code layer."""
    if r.name not in r.layered:
        return []
    token = getattr(r.c, "folder", "") or r.name   # a project's code-check finds the repo folder by its exact case
    return [finding(r.name, "coderef.module", u.path, "no CodeRef names this module",
                    f"add code:{token}:{u.path[4:] if u.path.startswith('src/') else u.path} to a "
                    "code store (implemented_by from its node)", u)
            for u in r.modules() if u.path not in r.covered.get(r.name, set())]


# The checks of a repo, in the order its findings are gathered (the sort keeps it among equal keys): one function per
# check, each from the repo to its findings; the test checks run before cmd.documented, which reads their shims.
REPO_CHECKS = (_readme_checks, _doc_dead_refs, _moved_dead_refs, _dangling_refs, _test_checks, _cmd_documented,
               _cmd_registry, _coderef_module)


def _applies(r: _Repo) -> dict[str, bool]:
    """Which of a pending check's ``applies`` scopes (brain.audit_checks.PENDING) hold for the repo."""
    c, ctx, modules = r.c, r.ctx, r.modules()
    return {"every": True, "code": r.has_code(), "python": bool(modules),
            "commands": any(u.kind == "command" for u in r.rf.units), "ts": c.lang == "ts",
            "no-code-layer": bool(modules) and r.name not in r.layered, "tools": bool(c.tools),
            "standards": ctx is not None
            and standards.selection(getattr(ctx.get("project"), "standards", None)) is not None}


def _not_measured(r: _Repo, unregistered: list) -> tuple[list[dict], list[dict]]:
    """(the findings of the generator checks that run, the checks not measured here and who owns them)."""
    found, pending, applies = [], [], _applies(r)
    for k, v in checks.PENDING.items():
        if not applies[v.applies]:
            continue
        got = v.owner if v.run is None or r.ctx is None else v.run(r.ctx)
        if isinstance(got, str):
            pending.append({"check": k, "owner": got})
        else:
            found += got
    if r.rf.layout.roots is None:
        pending.insert(0, {"check": "test.module", "owner": r.rf.layout.why})
    if unregistered:
        pending.append({"check": "coderef.dangling", "owner": f"CodeRefs of repos not measured here (another "
                                                              f"project's, or not cloned): {', '.join(unregistered)}"})
    return found, pending


def _repo_result(c: projects.Repo, rf: inventory.RepoFacts, idx: inventory.Index, tops: set, mod_evidence: dict,
                 facts: dict, dangling: list, unregistered: list, covered: dict, layered: set,
                 missing: list, extra_dirs: set = frozenset(), ctx: dict | None = None) -> dict:
    """One repo's result: :data:`REPO_CHECKS` in turn, the generator checks, the waivers, sorted by severity."""
    r = _Repo(c, rf, idx, tops, mod_evidence, facts, dangling, covered, layered, extra_dirs, ctx)
    found = [f for check in REPO_CHECKS for f in check(r)]
    generated, pending = _not_measured(r, unregistered)
    found += generated
    found, waived = waived_findings(found, getattr(c, "waive", None))
    if (ctx or {}).get("stale", True):   # not in the trend's past weeks (measure)
        found += stale_waivers(r.name, rf.tree, getattr(c, "waive", None))
    found.sort(key=lambda f: (f["severity"] if f["severity"] != "info" else "P9", f["check"], f["unit"]))
    return _shape(r, found, pending, waived, missing)


def _shape(r: _Repo, found: list[dict], pending: list[dict], waived: list, missing: list) -> dict:
    """The repo's result as the JSON output carries it, from its sorted findings."""
    c, rf = r.c, r.rf
    counts = {s: sum(1 for f in found if f["severity"] == s) for s in SEVERITIES + ("info",)}
    classes = {k: sum(1 for u in rf.units if u.cls == k) for k in ("entry", "prod", "other")}
    cov = (r.ctx or {}).get("cache", {}).get("feature.coverage")   # feature.coverage's section (feature_cover)
    return {"name": r.name, "path": str(c.path), "production": c.production or c.entry is not None,
            "commit": rf.tree.label, "date": rf.tree.date, "counts": counts, "classes": classes,
            "no_entry": rf.no_entry, "missing_entries": missing, "findings": found,
            "not_measured": pending, "waived": [{"unit": u, "reason": w} for u, w in [*rf.waived, *waived]],
            "exempt": rf.exempt, **({"feature_coverage": cov} if cov else {})}


# The checks on a test module or a doc, which a repo's waive globs also take (a module or a script is waived where
# the units are read, brain.inventory): a test that checks data no module stands for, a template a new brain copies.
WAIVABLE = ("doc.links", "test.links")


def waived_findings(found: list[dict], waive: dict[str, str] | None) -> tuple[list[dict], list[tuple[str, str]]]:
    """(the findings kept, (unit, reason) of those a waive glob takes): only :data:`WAIVABLE` checks, once per unit."""
    keep, out = [], []
    for f in found:
        why = next((r for g, r in (waive or {}).items() if fnmatch.fnmatchcase(f["unit"], g)), "") \
            if f["check"] in WAIVABLE else ""
        if not why:
            keep.append(f)
        elif f["unit"] not in {u for u, _ in out}:
            out.append((f["unit"], why))
    return keep, out


def stale_waivers(repo: str, t: inventory.Tree, waive: dict[str, str] | None) -> list[dict]:
    """waive.stale: each glob of a repo's ``waive:`` that matches no file of its tree (the file renamed or removed):
    it waives nothing today, keeps a reason no unit carries, and would hide the next file that takes its name."""
    return [finding(repo, "waive.stale", glob, f"the waive glob matches no file of {repo} at {t.label} ({reason})",
                    "remove it from projects.yaml (repos[].waive), or fix the glob to the files it means")
            for glob, reason in sorted((waive or {}).items())
            if not any(fnmatch.fnmatchcase(p, glob) for p in t.files)]


def _parallel(fn, items: list) -> list:
    """``fn`` over ``items`` in threads (git calls dominate: each costs a process start)."""
    if len(items) < 2:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=min(8, len(items))) as pool:
        return list(pool.map(fn, items))


def trees_now(cfgs: list[projects.Repo]) -> tuple[dict[str, inventory.Tree], dict[str, str], dict[str, str]]:
    """(trees, the ref each was read at, why a repo was not audited)."""
    errors = {c.name: f"{c.path} not found" for c in cfgs if not c.path.is_dir()}
    live = [c for c in cfgs if c.name not in errors]

    def read(c: projects.Repo):
        ref, branch = inventory.reading_ref(c.path)
        return ref, inventory.git_tree(c.path, ref, branch)

    got = dict(zip([c.name for c in live], _parallel(read, live)))
    return {k: v[1] for k, v in got.items()}, {k: v[0] for k, v in got.items()}, errors
