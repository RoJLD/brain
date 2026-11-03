"""Validate DDR, SR and AR records and the ledger's events against their JSON Schemas (schemas/*.schema.json), then
the rules a schema cannot say (the recommended option first, answers among the options...).

The validator covers the subset of JSON Schema 2020-12 the schemas use, with the standard library only, so the
capture hooks and brain.timing can validate what they write: type, const, enum, required, properties, additionalProperties, items,
minItems, maxItems, minLength, maxLength, minimum, pattern, format (date, date-time), $ref to #/$defs, allOf, if/then.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

KINDS = ("ddr", "sr", "ar")
SCHEMAS = KINDS + ("event", "config")  # event: the execution-time ledger and the ops error events (brain.timing);
# config: a personal brain's config.json (brain.config)
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


@lru_cache(maxsize=None)
def load(kind: str) -> dict:
    if kind not in SCHEMAS:
        raise ValueError(f"unknown record kind {kind!r} (expected one of {', '.join(SCHEMAS)})")
    return json.loads((SCHEMA_DIR / f"{kind}.schema.json").read_text(encoding="utf-8"))


def _is_type(value, t: str) -> bool:
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPES[t])


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


def _validate(value, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    if "$ref" in schema:
        _validate(value, _resolve(schema["$ref"], root), root, path, errors)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, t) for t in types):
            errors.append(f"{path}: expected {' or '.join(types)}, got {type(value).__name__}")
            return
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: must be {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
        if "format" in schema and not _format_ok(value, schema["format"]):
            errors.append(f"{path}: {value!r} is not a {schema['format']}")
    if _is_type(value, "number") and "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path}: below {schema['minimum']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        if "items" in schema:
            for i, v in enumerate(value):
                _validate(v, schema["items"], root, f"{path}[{i}]", errors)
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key!r}")
        props = schema.get("properties", {})
        extra = schema.get("additionalProperties", True)
        for key, v in value.items():
            if key in props:
                _validate(v, props[key], root, f"{path}.{key}", errors)
            elif extra is False:
                errors.append(f"{path}: unexpected field {key!r}")
            elif isinstance(extra, dict):
                _validate(v, extra, root, f"{path}.{key}", errors)
    for sub in schema.get("allOf", []):
        if "if" in sub:
            probe: list[str] = []
            _validate(value, sub["if"], root, path, probe)
            if not probe and "then" in sub:
                _validate(value, sub["then"], root, path, errors)
        else:
            _validate(value, sub, root, path, errors)


def schema_errors(kind: str, record: dict) -> list[str]:
    errors: list[str] = []
    schema = load(kind)
    _validate(record, schema, schema, kind, errors)
    return errors


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


def check(kind: str, record: dict) -> tuple[list[str], list[str]]:
    """(errors, warnings) for one record."""
    if not isinstance(record, dict):
        return [f"{kind}: a record is a mapping, got {type(record).__name__}"], []
    errors = schema_errors(kind, record)
    rule_errors, warnings = _RULES[kind](record)
    return errors + rule_errors, warnings
