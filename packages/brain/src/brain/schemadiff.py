"""``brain schema diff`` (wi-brain-schema-diff; spec-brain-data-compat N6, COMPAT-1 to COMPAT-6): what a change of a
format's schema narrows, so that a breaking format change is seen before it merges.

The schemas are the contract, in any language (spec-brain-data-compat § 3): the JSON Schemas (``*.schema.json``) and
the graph stores' ``schema.yaml`` (a store's, or a template's: ``templates/**/schema.yaml``,
``templates/schemas/*.yaml``). Each one the change touches is compared with its base, and what a file valid before
would no longer satisfy is a **narrowing**:

- JSON Schema: a property removed (``properties``, ``$defs``), a field newly ``required``, an ``enum`` that lost a
  value or appeared, a ``type`` that lost one or appeared, a ``const`` added or changed, ``additionalProperties``
  closed, a bound tightened or added (``minimum``, ``minLength``, ``minItems`` up; ``maximum``, ``maxLength``,
  ``maxItems`` down), a ``pattern`` or ``format`` added or changed (the comparison cannot tell a wider pattern: it errs
  towards a narrowing), an ``allOf`` entry added;
- schema.yaml: a node type, an edge type or a status removed, a status of a type removed (``status_by_type``, or a
  type given a list it had not), a prop newly required (``required_props``).

Adding is never a narrowing: an optional property, a type, a status, a value. Prose (``description``, ``title``,
``$comment``, ``examples``) is not compared.

A narrowing is resolved, not refused, when the PR says how an owner gets over it, on its **Compat: line** (in the PR
body or a commit message of the range, read as the scout reads ``Root cause:``):

- ``Compat: migration <id>``, with the format's ``v`` bumped (its ``properties.v.const``) and a fixture of the new
  version (``fixtures/formats/<format>/v<N>/``, ``<format>`` the file's name without ``.schema.json``) in the change's
  tree: the format moves, as the norm says (a rename or a removal bumps ``v`` and ships its migration);
- ``Compat: breaking <adr-id>``: the decision that drops the reader is named (a reader is dropped only by an ADR).

``Compat: additive`` with a narrowing found says the opposite of the diff: the narrowing stays. An unresolved
narrowing is a ``schema.narrowed`` finding of the scout (``brain audit --diff``): an info line, never blocking, unless
the owner opts in with config.json ``audit.schema_diff_strict`` (then NEW, to fix or resolve in the PR); a patch never
newly refuses. ``brain schema diff --against <tag>`` prints the same over the range from the tag to the working tree,
exit 1 on an unresolved narrowing under the opt-in or ``--strict``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import config, inventory

STRICT_KEY = "schema_diff_strict"
PROSE = ("description", "title", "$comment", "examples")
LOWER = ("minimum", "exclusiveMinimum", "minLength", "minItems", "minProperties")   # a higher one narrows
UPPER = ("maximum", "exclusiveMaximum", "maxLength", "maxItems", "maxProperties")   # a lower one narrows
EXACT = ("pattern", "format")                                                          # any change may narrow
COMPAT = re.compile(r"^[ \t]*(?:[-*>][ \t]*)?(?:\*\*|__)?compat(?:\*\*|__)?[ \t]*:(?:\*\*|__)?[ \t]*`?"
                    r"(additive|migration|breaking)\b[ \t(`]*([\w.-]*)", re.IGNORECASE | re.MULTILINE)
PLACEHOLDER = re.compile(r"\{\w+\}")   # a template's variables ({owner_line}): rendered by brain init


def is_schema(path: str) -> bool:
    """A schema the diff compares: a JSON Schema, or a graph store's (or a template's) schema.yaml."""
    low = path.lower()
    base = low.rsplit("/", 1)[-1]
    if inventory.skipped(path) or inventory.frozen_store(path):
        return False
    return base.endswith(".schema.json") or base == "schema.yaml" or (
        "/templates/schemas/" in f"/{low}" and base.endswith((".yaml", ".yml")))


def format_of(path: str) -> str:
    """The format a JSON Schema file describes: its name without ``.schema.json`` (``ddr.schema.json``: ddr)."""
    base = path.rsplit("/", 1)[-1]
    return base[: -len(".schema.json")] if base.lower().endswith(".schema.json") else ""


@dataclass
class Diff:
    """What one schema file's change narrows, and how the PR resolves it."""
    path: str
    narrowed: list[str] = field(default_factory=list)
    v: tuple[int | None, int | None] = (None, None)    # (before, after): properties.v.const
    resolved: str = ""                                 # how, when it is
    error: str = ""                                    # the file could not be read: compared as a narrowing


# --- JSON Schema -----------------------------------------------------------------------------------------------------

def _types(s: dict) -> set[str] | None:
    t = s.get("type")
    if t is None:
        return None
    return {t} if isinstance(t, str) else {x for x in t if isinstance(x, str)}


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _children(old: dict, new: dict, where: str) -> list[str]:
    """The named subschemas (properties, $defs, patternProperties): one removed narrows, one kept is compared."""
    out: list[str] = []
    for key in ("properties", "$defs", "patternProperties"):
        o, n = old.get(key) or {}, new.get(key) or {}
        if not (isinstance(o, dict) and isinstance(n, dict)):
            continue
        for name in o:
            sub = f"{where}/{name}" if key == "properties" else f"{where}/{key}/{name}"
            out += json_narrowed(o[name], n[name], sub) if name in n else [
                f"{where}/{name}: removed" if key == "properties" else f"{where or '/'}: {key} {name} removed"]
    return out


def _required(old: dict, new: dict, where: str) -> list[str]:
    return [f"{where}/{name}: newly required"
            for name in sorted(set(new.get("required") or []) - set(old.get("required") or []))]


def _enum(old: dict, new: dict, where: str) -> list[str]:
    if "enum" not in new:
        return []
    if "enum" not in old:
        return [f"{where or '/'}: an enum added"]
    lost = [v for v in old["enum"] if v not in new["enum"]]
    return [f"{where or '/'}: enum narrowed (no longer {', '.join(map(json.dumps, lost))})"] if lost else []


def _type(old: dict, new: dict, where: str) -> list[str]:
    t0, t1 = _types(old), _types(new)
    if t1 is None or (t0 is not None and not t0 - t1):
        return []
    return [f"{where or '/'}: type narrowed ({'any' if t0 is None else '|'.join(sorted(t0))} -> {'|'.join(sorted(t1))})"]


def _const(old: dict, new: dict, where: str) -> list[str]:
    if "const" not in new or old.get("const", object()) == new["const"]:
        return []
    return [f"{where or '/'}: const {json.dumps(old['const']) if 'const' in old else 'added'} -> "
            f"{json.dumps(new['const'])}"]


def _additional(old: dict, new: dict, where: str) -> list[str]:
    ap0, ap1 = old.get("additionalProperties", True), new.get("additionalProperties", True)
    if ap1 is False and ap0 is not False:
        return [f"{where or '/'}: closed (additionalProperties false)"]
    return json_narrowed(ap0, ap1, f"{where}/*") if isinstance(ap0, dict) and isinstance(ap1, dict) else []


def _bounds(old: dict, new: dict, where: str) -> list[str]:
    out = []
    for key in LOWER + UPPER:
        o, n = old.get(key), new.get(key)
        if _num(n) and (not _num(o) or (n > o if key in LOWER else n < o)):
            out.append(f"{where or '/'}: {key} {o if _num(o) else 'added'} -> {n}")
    return out + [f"{where or '/'}: {key} {'changed' if key in old else 'added'}"
                  for key in EXACT if key in new and old.get(key) != new[key]]


def _items(old: dict, new: dict, where: str) -> list[str]:
    if "items" not in new:
        return []
    if isinstance(old.get("items"), dict):
        return json_narrowed(old["items"], new["items"], f"{where}[]")
    return [] if "items" in old else [f"{where or '/'}: items constrained"]


def _all_of(old: dict, new: dict, where: str) -> list[str]:
    o_all, n_all = old.get("allOf") or [], new.get("allOf") or []
    out = [f"{where or '/'}: an allOf entry added"] * max(0, len(n_all) - len(o_all))
    for i, (o, n) in enumerate(zip(o_all, n_all, strict=False)):
        out += json_narrowed(o, n, f"{where}/allOf[{i}]")
    return out


KEYWORDS = (_children, _required, _enum, _type, _const, _additional, _bounds, _items, _all_of)


def json_narrowed(old, new, where: str = "") -> list[str]:
    """What ``new`` refuses that ``old`` accepted, keyword by keyword (:data:`KEYWORDS`), as ``<where>: <what>``
    lines."""
    if not (isinstance(old, dict) and isinstance(new, dict)):
        return [] if old == new else [f"{where or '/'}: the schema replaced"]
    return [line for check in KEYWORDS for line in check(old, new, where)]


def version(schema) -> int | None:
    """A format's ``v``, as its schema states it: ``properties.v.const`` (an integer), or None."""
    v = ((schema.get("properties") or {}).get("v") or {}).get("const") if isinstance(schema, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) else None


# --- schema.yaml -----------------------------------------------------------------------------------------------------

def _list(x) -> list:
    return list(x) if isinstance(x, list) else []


def _lost(old, new) -> list[str]:
    """The values of the list ``old`` that the list ``new`` lacks, as text."""
    return [str(x) for x in _list(old) if x not in _list(new)]


def _maps(old: dict, new: dict, key: str) -> tuple[dict, dict]:
    o, n = old.get(key) or {}, new.get(key) or {}
    return (o, n) if isinstance(o, dict) and isinstance(n, dict) else ({}, {})


def _by_type(old: dict, new: dict) -> list[str]:
    """status_by_type: a type's status removed, or a type that took any status given a list."""
    sb0, sb1 = _maps(old, new, "status_by_type")
    known = _list(old.get("node_types"))
    out = [f"status_by_type.{t}: {', '.join(_lost(sb0[t], s))} removed" for t, s in sb1.items()
           if t in sb0 and _lost(sb0[t], s)]
    return out + [f"status_by_type.{t}: its statuses restricted to {', '.join(map(str, _list(s)))}"
                  for t, s in sb1.items() if t not in sb0 and t in known]


def _required_props(old: dict, new: dict) -> list[str]:
    rp0, rp1 = _maps(old, new, "required_props")
    known = _list(old.get("node_types"))
    return [f"required_props.{t}: {', '.join(_lost(props, rp0.get(t)))} newly required" for t, props in rp1.items()
            if t in known and _lost(props, rp0.get(t))]


def store_narrowed(old: dict, new: dict) -> list[str]:
    """What a graph store's schema.yaml change refuses that the old one accepted."""
    out = [f"{key}: {', '.join(_lost(old.get(key), new.get(key)))} removed"
           for key in ("node_types", "edge_types", "statuses") if _lost(old.get(key), new.get(key))]
    return out + _by_type(old, new) + _required_props(old, new)


# --- one file, a change, the Compat: line ----------------------------------------------------------------------------

def _load(path: str, text: str):
    if path.lower().endswith(".json"):
        return json.loads(text)
    import yaml
    return yaml.safe_load("\n".join(PLACEHOLDER.sub("", line) for line in text.splitlines())) or {}


def compare(path: str, before: str | None, after: str | None) -> Diff:
    """One schema file's diff: a file the change removes narrows everything; a new one narrows nothing."""
    d = Diff(path)
    if after is None:
        d.narrowed = ["the schema removed"]
        return d
    if before is None:
        return d
    try:
        old, new = _load(path, before), _load(path, after)
    except Exception as exc:   # JSON or YAML that does not parse: what it narrows cannot be told
        d.error = f"cannot be read: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}"
        d.narrowed = [d.error]
        return d
    if path.lower().endswith(".json"):
        d.v = (version(old), version(new))
        d.narrowed = [x for x in json_narrowed(old, new) if not (x.startswith("/v: const") and _bumped(d.v))]
    elif isinstance(old, dict) and isinstance(new, dict):
        d.narrowed = store_narrowed(old, new)
    return d


def _bumped(v: tuple[int | None, int | None]) -> bool:
    return v[0] is not None and v[1] is not None and v[1] > v[0]


def compat(body: str) -> list[tuple[str, str]]:
    """The Compat: lines of a PR body and commit messages: (kind, its id), kind additive, migration or breaking."""
    return [(m.group(1).lower(), m.group(2)) for m in COMPAT.finditer(body or "")]


def has_fixture(tree: inventory.Tree, fmt: str, v: int) -> bool:
    """A fixture of version ``v`` of ``fmt`` in the tree: a file under ``fixtures/formats/<fmt>/v<v>/``."""
    needle = f"fixtures/formats/{fmt}/v{v}/"
    return any(needle in f"/{p}" for p in tree.files)


def resolve(d: Diff, lines: list[tuple[str, str]], tree: inventory.Tree) -> Diff:
    """``d.resolved`` set when the Compat: lines resolve its narrowings (module docstring)."""
    if not d.narrowed:
        return d
    fmt = format_of(d.path)
    for kind, ident in lines:
        if kind == "breaking" and ident:
            d.resolved = f"Compat: breaking {ident}"
        elif kind == "migration" and ident and fmt and _bumped(d.v) and has_fixture(tree, fmt, d.v[1]):
            d.resolved = f"Compat: migration {ident}, v{d.v[0]} -> v{d.v[1]} with its fixture"
        if d.resolved:
            break
    return d


def why_not(d: Diff, lines: list[tuple[str, str]], tree: inventory.Tree) -> str:
    """What the PR still lacks to resolve ``d``'s narrowings."""
    fmt = format_of(d.path)
    if not fmt:
        return "a 'Compat: breaking <adr-id>' line naming the decision"
    need = []
    if not _bumped(d.v):
        need.append(f"its v bumped (now {d.v[1] if d.v[1] is not None else 'none'})")
    elif not has_fixture(tree, fmt, d.v[1]):
        need.append(f"a fixture fixtures/formats/{fmt}/v{d.v[1]}/")
    if not any(k == "migration" and i for k, i in lines):
        need.append("a 'Compat: migration <id>' line")
    return " and ".join(need) + ", or a 'Compat: breaking <adr-id>' line"


def diffs(rows: list[tuple[str, str, str]], base: inventory.Tree, new: inventory.Tree, body: str) -> list[Diff]:
    """The schema files of a change (the scout's rows: status, old path, new path), compared and resolved."""
    lines = compat(body)
    out = []
    for _, old, path in rows:
        was = old or path
        if not (is_schema(was) or is_schema(path or "")):
            continue
        before = base.text(was) if base.has(was) else None
        after = new.text(path) if path and new.has(path) else None
        d = compare(path or was, before, after)
        if d.narrowed:
            out.append(resolve(d, lines, new))
    return out


def strict(root) -> bool:
    """Whether the owner opts in to NEW lines for a narrowing (config.json ``audit.schema_diff_strict`` true);
    default false: info lines, never blocking."""
    opts = config.load(root).data.get("audit")
    return isinstance(opts, dict) and opts.get(STRICT_KEY) is True


def signals(repo: str, rows, base: inventory.Tree, new: inventory.Tree, body: str, strict_: bool = False) -> list:
    """The scout's ``schema.narrowed`` findings: one per schema file whose narrowings the PR leaves unresolved (NEW
    under the opt-in, else info), and a justified line for each one it resolves."""
    out = []
    lines = compat(body)
    for d in diffs(rows, base, new, body):
        tag = "justified" if d.resolved else ("NEW" if strict_ else "info")
        why = "; ".join(d.narrowed[:4]) + (f" (+{len(d.narrowed) - 4})" if len(d.narrowed) > 4 else "")
        fix = d.resolved or why_not(d, lines, new)
        out.append({"key": f"{repo}:schema.narrowed:{d.path}", "check": "schema.narrowed",
                    "severity": "P1" if tag == "NEW" else "info", "unit": d.path, "class": "", "chain": "",
                    "via": "", "why": f"narrows: {why}", "fix": fix, "tag": tag})
    return out
