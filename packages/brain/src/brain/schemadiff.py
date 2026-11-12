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
  towards a narrowing), an ``allOf`` entry added, a ``$ref`` changed, the format's ``v`` moved (its files no longer
  validate), and each keyword it does not weigh (``anyOf``, ``oneOf``, ``not``, ``if``, ``uniqueItems``...) added or
  changed; the subschemas are walked (``properties``, ``$defs``, ``items``, ``additionalProperties``, ``allOf``,
  ``then``, ``else``, ``contains``), a boolean one as ``{}`` (true) or nothing (false);
- schema.yaml: a node type, an edge type or a status removed, a status of a type removed (``status_by_type``, or a
  type given a list it had not), a prop newly required (``required_props``);
- either: the file removed or renamed (its readers look it up by its path), or one that cannot be read or compared
  (never a crash).

Adding is never a narrowing: an optional property, a type (``integer`` widened to ``number`` included), a status, a
value. Prose (``description``, ``title``, ``$comment``, ``examples``) is not compared.

A narrowing is resolved, not refused, when the PR says how an owner gets over it, on its **Compat: line** (in the PR
body or a commit message of the range, read as the scout reads ``Root cause:``):

- ``Compat: migration <id>``, with the format's ``v`` bumped (its ``properties.v.const``) and a fixture of the new
  version (``fixtures/formats/<format>/v<N>/``, ``<format>`` the file's name without ``.schema.json``) in the change's
  tree: the format moves, as the norm says (a rename or a removal bumps ``v`` and ships its migration);
- ``Compat: breaking <adr-id>``: the decision that drops the reader is named (a reader is dropped only by an ADR):
  an id ``adr-...``, for every narrowing of the change.

A ``migration`` id with no hyphen (``TBD``) or a ``breaking`` line naming no ``adr-`` id resolves nothing, and
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

# The keywords the checks below read; any other keyword that a change adds or changes counts as a narrowing (the
# comparison errs towards one: anyOf, oneOf, not, uniqueItems, dependentRequired... a rule it cannot weigh).
HANDLED = {"properties", "$defs", "patternProperties", "required", "enum", "type", "const", "additionalProperties",
           "items", "allOf", "then", "else", "contains", "$ref", *LOWER, *UPPER, *EXACT, *PROSE}


def _types(s: dict) -> set[str] | None:
    """The types a schema allows (None: any); a ``type`` that is neither a string nor a list allows nothing known."""
    t = s.get("type")
    if t is None:
        return None
    if isinstance(t, str):
        return {t}
    return {x for x in t if isinstance(x, str)} if isinstance(t, list) else set()


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _norm(s):
    """A subschema as a mapping: ``true`` is ``{}`` (anything), ``false`` stays False (nothing); other values kept."""
    return {} if s is True else s


def _children(old: dict, new: dict, where: str) -> list[str]:
    """The named subschemas (properties, $defs, patternProperties): one removed narrows, one kept is compared."""
    out: list[str] = []
    for key in ("properties", "$defs", "patternProperties"):
        o, n = old.get(key) or {}, new.get(key) or {}
        if not (isinstance(o, dict) and isinstance(n, dict)):
            out += [] if o == n else [f"{where or '/'}: {key} changed"]
            continue
        for name in o:
            sub = f"{where}/{name}" if key == "properties" else f"{where}/{key}/{name}"
            out += json_narrowed(o[name], n[name], sub) if name in n else [
                f"{where}/{name}: removed" if key == "properties" else f"{where or '/'}: {key} {name} removed"]
    return out


def _names(x) -> set[str]:
    return {v for v in x if isinstance(v, str)} if isinstance(x, list) else set()


def _required(old: dict, new: dict, where: str) -> list[str]:
    return [f"{where}/{name}: newly required" for name in sorted(_names(new.get("required")) -
                                                                 _names(old.get("required")))]


def _enum(old: dict, new: dict, where: str) -> list[str]:
    if "enum" not in new:
        return []
    o, n = old.get("enum"), new.get("enum")
    if not isinstance(n, list) or ("enum" in old and not isinstance(o, list)):
        return [] if o == n else [f"{where or '/'}: enum changed"]
    if "enum" not in old:
        return [f"{where or '/'}: an enum added"]
    lost = [v for v in o if v not in n]
    return [f"{where or '/'}: enum narrowed (no longer {', '.join(map(json.dumps, lost))})"] if lost else []


def _type(old: dict, new: dict, where: str) -> list[str]:
    t0, t1 = _types(old), _types(new)
    if t1 is None:
        return []
    lost = (t0 - t1 - ({"integer"} if "number" in t1 else set())) if t0 is not None else {"any"}
    if not lost:
        return []
    return [f"{where or '/'}: type narrowed ({'any' if t0 is None else '|'.join(sorted(t0))} -> "
            f"{'|'.join(sorted(t1)) or repr(new.get('type'))})"]


def _const(old: dict, new: dict, where: str) -> list[str]:
    if "const" not in new or old.get("const", object()) == new["const"]:
        return []
    return [f"{where or '/'}: const {json.dumps(old['const']) if 'const' in old else 'added'} -> "
            f"{json.dumps(new['const'])}"]


def _sub(key: str, label: str):
    """A keyword whose value is one subschema (additionalProperties, items as one schema, then, else, contains):
    absent is anything, as ``true``; compared as a schema."""
    def check(old: dict, new: dict, where: str) -> list[str]:
        if key not in new:
            return []
        o, n = _norm(old.get(key, True)), _norm(new[key])
        if isinstance(o, list) or isinstance(n, list):      # items as a tuple (draft 2019 and before)
            return _tuple(o, n, f"{where}{label}") if isinstance(o, list) and isinstance(n, list) else (
                [] if o == n else [f"{where or '/'}: {key} changed"])
        return json_narrowed(o, n, f"{where}{label}")
    return check


def _tuple(old: list, new: list, where: str) -> list[str]:
    out = [f"{where}: {len(new) - len(old)} tuple item(s) added"] if len(new) > len(old) else []
    for i, (o, n) in enumerate(zip(old, new, strict=False)):
        out += json_narrowed(_norm(o), _norm(n), f"{where}[{i}]")
    return out


def _bounds(old: dict, new: dict, where: str) -> list[str]:
    out = []
    for key in LOWER + UPPER:
        o, n = old.get(key), new.get(key)
        if _num(n) and (not _num(o) or (n > o if key in LOWER else n < o)):
            out.append(f"{where or '/'}: {key} {o if _num(o) else 'added'} -> {n}")
    return out + [f"{where or '/'}: {key} {'changed' if key in old else 'added'}"
                  for key in EXACT if key in new and old.get(key) != new[key]]


def _ref(old: dict, new: dict, where: str) -> list[str]:
    if "$ref" not in new or old.get("$ref") == new["$ref"]:
        return []
    return [f"{where or '/'}: $ref {old.get('$ref', 'added')} -> {new['$ref']}"]


def _all_of(old: dict, new: dict, where: str) -> list[str]:
    o_all, n_all = old.get("allOf"), new.get("allOf")
    o_all, n_all = (o_all if isinstance(o_all, list) else []), (n_all if isinstance(n_all, list) else [])
    out = [f"{where or '/'}: an allOf entry added"] * max(0, len(n_all) - len(o_all))
    for i, (o, n) in enumerate(zip(o_all, n_all, strict=False)):
        out += json_narrowed(_norm(o), _norm(n), f"{where}/allOf[{i}]")
    return out


def _others(old: dict, new: dict, where: str) -> list[str]:
    """Any keyword :data:`HANDLED` does not weigh, added or changed (``if`` among them: a new condition)."""
    return [f"{where or '/'}: {key} {'changed' if key in old else 'added'}"
            for key in sorted(set(new) - HANDLED) if old.get(key, object()) != new[key]]


KEYWORDS = (_children, _required, _enum, _type, _const, _sub("additionalProperties", "/*"), _bounds,
            _sub("items", "[]"), _sub("then", "/then"), _sub("else", "/else"), _sub("contains", "/contains"),
            _ref, _all_of, _others)


def json_narrowed(old, new, where: str = "") -> list[str]:
    """What ``new`` refuses that ``old`` accepted, keyword by keyword (:data:`KEYWORDS`), as ``<where>: <what>``
    lines. A boolean subschema counts as ``{}`` (true) or nothing (false)."""
    old, new = _norm(old), _norm(new)
    if old is False or new == {}:
        return []                           # nothing was accepted, or anything is
    if new is False:
        return [f"{where or '/'}: closed (false: nothing accepted)"]
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
                  for t, s in sb1.items() if isinstance(s, list) and t in known
                  and (t not in sb0 or not isinstance(sb0[t], list))]


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
    try:
        _narrow(d, path, old, new)
    except Exception as exc:   # a schema of an unexpected shape: what it narrows cannot be told, never a crash
        d.error = f"cannot be compared: {type(exc).__name__}: {exc}"
        d.narrowed = [d.error]
    return d


def _narrow(d: Diff, path: str, old, new) -> None:
    if path.lower().endswith(".json"):
        d.v = (version(old), version(new))
        moved = None not in d.v and d.v[0] != d.v[1]     # both state an integer v: the format's version moved
        d.narrowed = [x for x in json_narrowed(old, new) if not (moved and x.startswith("/v: const"))] + (
            [f"/v: v{d.v[0]} -> v{d.v[1]}: the files of v{d.v[0]} no longer validate (the format moves)"]
            if moved else [])
    elif isinstance(old, dict) and isinstance(new, dict):
        d.narrowed = store_narrowed(old, new)


def _bumped(v: tuple[int | None, int | None]) -> bool:
    return v[0] is not None and v[1] is not None and v[1] > v[0]


ADR_ID = re.compile(r"^adr-[\w.-]+$", re.IGNORECASE)                 # a decision log's id: adr-<date>-<slug>
MIGRATION_ID = re.compile(r"^[a-z][\w.]*-[\w.-]+$", re.IGNORECASE)   # an id, never a word (TBD, changes)


def compat(body: str) -> list[tuple[str, str]]:
    """The Compat: lines of a PR body and commit messages: (kind, its id), kind additive, migration or breaking; an
    id that is not one (``breaking`` naming no ``adr-...``, a ``migration`` id with no hyphen such as TBD) is ''."""
    out = []
    for m in COMPAT.finditer(body or ""):
        kind, ident = m.group(1).lower(), m.group(2)
        ok = {"breaking": ADR_ID, "migration": MIGRATION_ID}.get(kind)
        out.append((kind, ident if ok and ok.match(ident) else ""))
    return out


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
        if old and path and old != path:     # its readers look it up by its path: a rename is a removal for them
            d.narrowed.insert(0, f"renamed from {old}")
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
