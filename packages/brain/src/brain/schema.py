"""Validate DDR, SR and AR records, the ledger's events and config.json against their JSON Schemas
(schemas/*.schema.json), then the rules a schema cannot say (the recommended option first, answers among the options...).

The validator covers the subset of JSON Schema 2020-12 the schemas use, with the standard library only, so the
capture hooks and brain.timing can validate what they write: type, const, enum, required, properties,
additionalProperties, items, minItems, maxItems, minLength, maxLength, minimum, maximum, pattern, format (date,
date-time), $ref to #/$defs, allOf, if/then. :func:`load` refuses a schema that uses any other keyword
(:data:`KEYWORDS`), so every validator of the contract, in any language, enforces the same rules.

Two modes (docs/formats.md; spec-brain-data-compat N3, N4): :data:`STRICT` for what the engine writes and for the CI at
the pin, where an unknown field is an error; :data:`READ` for what it reads, where an unknown field is reported and
kept, never dropped (a newer brain's additive field: a lossless round trip). In both, a ``v`` above the one this engine
knows is refused: "written by brain > X: brain update". :func:`mode` picks the mode of a check.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

KINDS = ("ddr", "sr", "ar")
SCHEMAS = KINDS + ("event", "config", "members", "readme", "standards", "modules", "status", "permissions",
                     "docgraph", "catalogue", "reference")  # event: the
# execution-time ledger and the ops error events (brain.timing); config: a personal brain's config.json
# (brain.config); members: its members.yaml (brain.identity); readme: a repo's readme.yaml (brain.readme); standards:
# a standards catalog (brain.standards); modules: an entry of a store's modules.yaml (brain.modules, brain.modulemap);
# status: the status document brain doctor --json prints (brain.probe), versioned by its id (schema: <name>/v<N>),
# not by a top-level v; permissions: permissions.yaml (brain.permissions), described for brain schema diff and the
# fixtures, read by brain.permissions itself; docgraph: a documentation graph (brain.docgraph), versioned by its id
# too (docgraph/v1); catalogue: a module catalogue (brain.catalogue), versioned by its id too (catalogue/v1); reference: a repo's
# docs/reference.yaml, the prose of its technical reference (brain.reference, brain.arc42)
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

STRICT, READ = "strict", "read"
# The keywords the validator enforces, then the annotations it reads without enforcing anything.
KEYWORDS = frozenset({"type", "const", "enum", "required", "properties", "additionalProperties", "items", "minItems",
                      "maxItems", "minLength", "maxLength", "minimum", "maximum", "pattern", "format", "$ref", "allOf",
                      "if", "then"})
ANNOTATIONS = frozenset({"$schema", "$id", "$defs", "$comment", "title", "description", "default", "examples"})
_SUBSCHEMA_MAPS = ("properties", "$defs")      # {name: schema}: the names are not keywords
_SUBSCHEMAS = ("additionalProperties", "items", "if", "then")
_NOTED: set[str] = set()                        # the notes printed by this process (brain check may read a file twice)

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def keywords(schema, out: set[str] | None = None) -> set[str]:
    """Every keyword ``schema`` uses, its subschemas' included (a property's name is not a keyword)."""
    out = set() if out is None else out
    if not isinstance(schema, dict):
        return out
    for key, sub in schema.items():
        out.add(key)
        if key in _SUBSCHEMA_MAPS and isinstance(sub, dict):
            for s in sub.values():
                keywords(s, out)
        elif key in _SUBSCHEMAS:
            keywords(sub, out)
        elif key == "allOf" and isinstance(sub, list):
            for s in sub:
                keywords(s, out)
    return out


def _misplaced(schema, inside_allof: bool = False, out: list[str] | None = None) -> list[str]:
    """The shapes the validator would half enforce: if/then outside an allOf entry or beside other keywords there (only
    the pair is read), ``items`` as a list (only a schema is read)."""
    out = [] if out is None else out
    if not isinstance(schema, dict):
        return out
    if ("if" in schema or "then" in schema) and (not inside_allof or set(schema) - {"if", "then", "$comment"}):
        out.append("if/then outside an allOf entry of their own")
    if isinstance(schema.get("items"), list):
        out.append("items as a list")
    for key, sub in schema.items():
        if key in _SUBSCHEMA_MAPS and isinstance(sub, dict):
            for s in sub.values():
                _misplaced(s, False, out)
        elif key in _SUBSCHEMAS:
            _misplaced(sub, False, out)
        elif key == "allOf" and isinstance(sub, list):
            for s in sub:
                _misplaced(s, True, out)
    return out


def unsupported(schema: dict) -> list[str]:
    """The keywords of ``schema`` the validator neither enforces nor reads as an annotation, and the shapes it would
    enforce only in part (:func:`_misplaced`)."""
    return sorted(keywords(schema) - KEYWORDS - ANNOTATIONS) + sorted(set(_misplaced(schema)))


@lru_cache(maxsize=None)
def load(kind: str) -> dict:
    if kind not in SCHEMAS:
        raise ValueError(f"unknown record kind {kind!r} (expected one of {', '.join(SCHEMAS)})")
    data = json.loads((SCHEMA_DIR / f"{kind}.schema.json").read_text(encoding="utf-8"))
    missing = unsupported(data)
    if missing:   # a rule the validator would skip silently: refuse the schema rather than enforce half of it
        raise ValueError(f"{kind}.schema.json uses {', '.join(missing)}, which brain.schema does not implement")
    return data


def mode() -> str:
    """The mode a check reads files in: :data:`STRICT` in CI (``CI`` set, as GitHub Actions does: the engine there is
    the pin) or with ``BRAIN_STRICT=1``; :data:`READ` elsewhere, or with ``BRAIN_STRICT=0`` (an older engine reading a
    newer one's data: a rollback)."""
    forced = os.environ.get("BRAIN_STRICT", "").strip().lower()
    if forced:
        return READ if forced in _OFF else STRICT
    return STRICT if os.environ.get("CI", "").strip().lower() not in ("", *_OFF) else READ


_OFF = ("0", "false", "no", "off", "n", "f")


def known_v(kind: str) -> int:
    """The ``v`` this engine reads and writes for ``kind`` (1 for a format versioned otherwise: status)."""
    return int((load(kind)["properties"].get("v") or {}).get("const", 1))


def newer(where: str, v, known: int = 1) -> str:
    """The refusal of a file or a line whose ``v`` is above ``known``; "" otherwise (an equal or older ``v`` is read:
    an older one is its schema's, or its migration's, to judge)."""
    if isinstance(v, int) and not isinstance(v, bool) and v > known:
        from . import __version__
        return f"{where}: v{v} is written by brain > {__version__}, which reads v{known}: brain update"
    return ""


def tolerate(message: str, strict: bool | None = None, notes: list[str] | None = None) -> list[str]:
    """An unknown key in an owner-edited file: ``[message]`` (an error) in strict mode; in read mode ``[]``, the key
    being a newer brain's, kept and not refused: the note goes to ``notes`` when a loader collects them (a hook prints
    nothing), else to stderr. ``strict`` overrides :func:`mode`."""
    if (mode() == STRICT) if strict is None else strict:
        return [message]
    note = f"{message} (kept: a newer brain's key? strict in CI)"
    if notes is not None:
        notes.append(note)
    elif note not in _NOTED:
        _NOTED.add(note)
        print(f"brain: note: {note}", file=sys.stderr)
    return []


def _is_type(value, t: str) -> bool:
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPES[t])


# A value an error may print back: a short plain word (an enum's typo), never an '@' or an account id (a UUID).
_PLAIN = re.compile(r"(?![\s\S]*[0-9A-Fa-f]{8}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{4}-?[0-9A-Fa-f]{12})"
                    r"[A-Za-z0-9_.:+-]{1,40}")


def _shown(value) -> str:
    """``value`` as an enum or a format error prints it: its repr when it is a short plain word (or not a string),
    else its length only, so an e-mail address, an account id or a long token never reaches a terminal or a log."""
    if not isinstance(value, str) or _PLAIN.fullmatch(value):
        return repr(value)
    return f"its value ({len(value)} character(s))"


def _format_ok(value: str, fmt: str) -> bool:
    try:
        if fmt == "date":
            date.fromisoformat(value)
        elif fmt == "date-time":
            if "T" not in value:
                return False
            datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise ValueError(f"unsupported $ref {ref!r}")
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _validate(value, schema: dict, root: dict, path: str, errors: list[str],
              unknown: list[tuple[str, str]] | None = None) -> None:
    """Append to ``errors`` what ``value`` breaks. An unknown field (additionalProperties: false) goes to ``unknown``
    as (path, key) when a list is given, else to ``errors``."""
    if "$ref" in schema:
        _validate(value, _resolve(schema["$ref"], root), root, path, errors, unknown)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, t) for t in types):
            errors.append(f"{path}: expected {' or '.join(types)}, got {type(value).__name__}")
            return
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {_shown(value)} not in {schema['enum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            # the value is never printed back: it may be an e-mail address, an account id or a secret
            errors.append(f"{path}: its value ({len(value)} character(s)) does not match {schema['pattern']}")
        if "format" in schema and not _format_ok(value, schema["format"]):
            errors.append(f"{path}: {_shown(value)} is not a {schema['format']}")
    if _is_type(value, "number") and "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path}: below {schema['minimum']}")
    if _is_type(value, "number") and "maximum" in schema and value > schema["maximum"]:
        errors.append(f"{path}: above {schema['maximum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, v in enumerate(value):
                _validate(v, schema["items"], root, f"{path}[{i}]", errors, unknown)
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key!r}")
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, v in value.items():
            if key in props:
                _validate(v, props[key], root, f"{path}.{key}", errors, unknown)
            elif extra is False:
                if unknown is None:
                    errors.append(f"{path}: unexpected field {key!r}")
                elif (path, key) not in unknown:
                    unknown.append((path, key))
            elif isinstance(extra, dict):
                _validate(v, extra, root, f"{path}.{key}", errors, unknown)
    for sub in schema.get("allOf", []):
        if "if" in sub:
            probe: list[str] = []
            _validate(value, sub["if"], root, path, probe, None if unknown is None else [])
            if not probe and "then" in sub:
                _validate(value, sub["then"], root, path, errors, unknown)
        else:
            _validate(value, sub, root, path, errors, unknown)


def field_path(path: str, key: str) -> str:
    """The dotted path of a field, list positions kept (``ddr.options[0].note``): what a rewrite carries."""
    return f"{path}.{key}"


def unknown_fields(kind: str, record) -> set[str]:
    """The fields of ``record`` its schema does not know (:func:`field_path`): a newer brain's, which a rewrite keeps."""
    if not isinstance(record, dict):
        return set()
    schema, unknown = load(kind), []
    _validate(record, schema, schema, kind, [], unknown)
    return {field_path(p, k) for p, k in unknown}


def validate(kind: str, record: dict, mode: str = STRICT,
             carry: set[str] | frozenset[str] = frozenset()) -> tuple[list[str], list[str]]:
    """(errors, unknown fields) of ``record`` against its schema. A ``v`` above the known one is the only error (its
    meaning may have changed). :data:`STRICT`: an unknown field is an error, except those in ``carry`` (the fields a
    rewrite keeps from the file it replaces); :data:`READ`: unknown fields are returned, not errors."""
    schema = load(kind)
    refused = newer(kind, record.get("v") if isinstance(record, dict) else None, known_v(kind))
    if refused:
        return [refused], []
    errors: list[str] = []
    unknown: list[tuple[str, str]] = []
    _validate(record, schema, schema, kind, errors, unknown)
    if mode == READ:
        return errors, [f"{p}: unknown field {k!r}" for p, k in unknown]
    return errors + [f"{p}: unexpected field {k!r}" for p, k in unknown if field_path(p, k) not in carry], []


def schema_errors(kind: str, record: dict, mode: str = STRICT) -> list[str]:
    """The errors of :func:`validate` (unknown fields included in :data:`STRICT`)."""
    return validate(kind, record, mode)[0]


def _ddr_rules(r: dict) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    labels = [o.get("label") for o in r.get("options", []) if isinstance(o, dict)]
    if len(set(labels)) != len(labels):
        errors.append("ddr.options: labels must be unique")
    rec = (r.get("recommendation") or {}).get("option")
    captured = (r.get("asked") or {}).get("via") == "ask-tool"
    if (r.get("kind") or "decision") != "decision":  # action and permission entries: options are optional
        pass
    elif rec is None:
        (warnings if captured else errors).append("ddr.recommendation: no recommended option (rule R1 wants one, first)")
    elif labels and rec != labels[0]:
        errors.append(f"ddr.recommendation: {rec!r} must be the first option ({labels[0]!r})")
    answer = r.get("answer")
    if isinstance(answer, dict):
        choices = answer.get("choices") or []
        for c in choices:
            if c not in labels:
                errors.append(f"ddr.answer.choices: {c!r} is not an option label (free text goes in 'other')")
        if not r.get("multi_select") and len(choices) > 1:
            errors.append("ddr.answer.choices: several choices on a single-choice question")
        if not choices and not answer.get("other"):
            errors.append("ddr.answer: no choice and no 'other' text")
        if answer.get("other") and r.get("other_allowed") is False:
            errors.append("ddr.answer.other: this question does not allow 'other'")
    if not str(r.get("id", "")).startswith(f"ddr-{str((r.get('asked') or {}).get('at', ''))[:10]}"):
        warnings.append("ddr.id: its date differs from asked.at")
    return errors, warnings


def _sr_rules(r: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    start, end = r.get("start"), r.get("end")
    if start and end and end < start:
        errors.append("sr.end: before start")
    if start and not str(r.get("id", "")).startswith(f"sr-{start[:10]}"):
        errors.append("sr.id: must start with sr-<start date>")
    if r.get("session_id") and not str(r.get("id", "")).endswith(r["session_id"].replace("-", "")[:8].lower()):
        errors.append("sr.id: must end with the first 8 characters of the session id")
    return errors, []


def _ar_rules(r: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    rid, kind, at = str(r.get("id", "")), r.get("kind"), str(r.get("at", ""))
    if kind and not rid.startswith(f"ar-{at[:10]}-{kind}-"):
        errors.append(f"ar.id: must start with ar-{at[:10]}-{kind}-")
    return errors, []


def _event_rules(r: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    start, end = r.get("start"), r.get("end")
    if isinstance(start, str) and isinstance(end, str) and end < start:
        errors.append("event.end: before start")
    return errors, []


_RULES = {"ddr": _ddr_rules, "sr": _sr_rules, "ar": _ar_rules, "event": _event_rules}


def check(kind: str, record: dict, mode: str = STRICT,
          carry: set[str] | frozenset[str] = frozenset()) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one record, in :func:`validate`'s ``mode`` (in :data:`READ` an unknown field is a
    warning, the record kept as it is)."""
    if not isinstance(record, dict):
        return [f"{kind}: a record is a mapping, got {type(record).__name__}"], []
    errors, unknown = validate(kind, record, mode, carry)
    if newer(kind, record.get("v"), known_v(kind)):
        return errors, []          # a newer format: its rules may have changed too
    rule_errors, warnings = _RULES.get(kind, lambda r: ([], []))(record)
    return errors + rule_errors, warnings + [f"{u} (kept: a newer brain's field? strict in CI)" for u in unknown]
