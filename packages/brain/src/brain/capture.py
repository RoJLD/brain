"""Zero-token capture, run by the brain's hooks: ``capture.py <event> [git|gh]`` with the hook's JSON on stdin.

It writes the machine-local ledger under $BRAIN_HOME (default ~/.brain), never the repo, never the network, never
stdout (a SessionStart hook's stdout would enter Claude's context). It always exits 0: a failure goes to
``ledger/errors.log`` and the session goes on. ``BRAIN_CAPTURE=0`` turns it off.

Events (hook payload fields checked against the Claude Code hooks reference, 2026-10-30):
- ``session-start`` (SessionStart: session_id, transcript_path, cwd, source, model when present): one event line;
- ``post-tool-use git|gh`` (PostToolUse on Bash or PowerShell: tool_input.command, tool_response.stdout / stderr /
  gitOperation, tool_use_id, cwd, permission_mode, effort.level): ARs for commits, pushes, tags, PRs and the ADRs
  a commit added; the model and version come from the transcript's last assistant record;
- ``post-tool-use`` on AskUserQuestion (tool_input.questions, tool_response.answers): one DDR per question, answered
  and read by the asking session, plus its AR;
- ``post-tool-use`` on a plan tool (``brain.plan.PLAN_TOOLS``: the desktop app's update_plan and wrap_up, TodoWrite;
  tool_input): the session's plan, ``sessions/<session_id>.plan.json``, its steps n/m for the cockpit;
- ``stop`` (Stop): the session's SR snapshot, ``sessions/<session_id>.json``, updated incrementally;
- ``session-end`` (SessionEnd: reason; 1.5 s budget): one event line.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from . import actions, midsession, paths, plan, schema, secretscan, transcript
from . import answers as answers_lane


def _now() -> str:
    return transcript.iso(datetime.now(timezone.utc))


def _append(name: str, record: dict) -> None:
    d = paths.ledger_dir()
    d.mkdir(parents=True, exist_ok=True)
    month = (record.get("at") or _now())[:7]
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(d / f"{name}-{month}.jsonl", "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line)


def _recent_ids(name: str, n: int = 400) -> set[str]:
    f = paths.ledger_dir() / f"{name}-{_now()[:7]}.jsonl"
    if not f.exists():
        return set()
    try:
        tail = f.read_bytes()[-200_000:].decode("utf-8", "replace").splitlines()[-n:]
    except OSError:
        return set()
    ids = set()
    for line in tail:
        m = re.search(r'"id":"([^"]+)"', line)
        if m:
            ids.add(m.group(1))
    return ids


def _log_error(event: str, exc: BaseException) -> None:
    try:
        d = paths.ledger_dir()
        d.mkdir(parents=True, exist_ok=True)
        f = d / "errors.log"
        if f.exists() and f.stat().st_size > 1_000_000:
            f.replace(d / "errors.log.1")
        text, _ = secretscan.clean_text("".join(traceback.format_exception_only(type(exc), exc)).strip())
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(f"{_now()} {event}: {text}\n")
    except OSError:
        pass


def _meta(payload: dict) -> dict:
    meta = {"session_id": payload.get("session_id"), "tool": "claude-code",
            "permission_mode": payload.get("permission_mode"), "agent": payload.get("agent_type")}
    effort = payload.get("effort")
    if isinstance(effort, dict) and effort.get("level"):
        meta["effort"] = effort["level"]
    tail = transcript.last_assistant(payload["transcript_path"]) if payload.get("transcript_path") else {}
    for k in ("model", "version", "surface"):
        if tail.get(k):
            meta[k] = tail[k]
    if not meta.get("effort") and tail.get("effort"):
        meta["effort"] = tail["effort"]
    return meta


def _write_ars(ars: list[dict]) -> int:
    seen = _recent_ids("ar")
    n = 0
    for ar in ars:
        if ar["id"] in seen:
            continue
        errors, _ = schema.check("ar", ar)
        if errors:
            raise ValueError(f"invalid AR {ar['id']}: {errors[:3]}")
        _append("ar", ar)
        seen.add(ar["id"])
        n += 1
    return n


def session_start(payload: dict) -> None:
    event = {"at": _now(), "event": "session_start", "session_id": payload.get("session_id"),
             "source": payload.get("source"), "model": payload.get("model"), "cwd": payload.get("cwd"),
             "permission_mode": payload.get("permission_mode"), "agent": payload.get("agent_type"),
             "transcript": paths.relative_transcript(payload["transcript_path"]) if payload.get("transcript_path") else None}
    _append("events", secretscan.clean({k: v for k, v in event.items() if v})[0])


def session_end(payload: dict) -> None:
    event = {"at": _now(), "event": "session_end", "session_id": payload.get("session_id"),
             "reason": payload.get("reason")}
    _append("events", {k: v for k, v in event.items() if v})


def _ask_question(payload: dict) -> None:
    questions = (payload.get("tool_input") or {}).get("questions") or []
    response = payload.get("tool_response") or {}
    answers = response.get("answers") or {} if isinstance(response, dict) else {}
    annotations = response.get("annotations") or {} if isinstance(response, dict) else {}
    meta = _meta(payload)
    now = _now()
    tuid = payload.get("tool_use_id") or ""
    seen = _recent_ids("ddr")
    asked = answers_lane.read(answers_lane.ASKED)
    for i, q in enumerate(questions):
        if not isinstance(q, dict) or not q.get("question"):
            continue
        notes = (annotations.get(q["question"]) or {}).get("notes") \
            if isinstance(annotations.get(q["question"]), dict) else None
        tied = answers_lane.capture(q, answers.get(q["question"]), notes, at=now, tool_use_id=tuid, index=i,
                                    session=meta.get("session_id") or "", asked=asked)
        if tied is not None:  # a question brain decision batch printed: its answer goes to its own DDR
            if tied:
                _write_ars([actions.make_ar("ddr", tied["id"], now, meta, "hook", tuid, ddr=tied["ddr"])])
            continue
        ddr = ddr_from_question(q, answers.get(q["question"]), now, meta, tuid, i, notes=notes)
        if ddr["id"] in seen:
            continue
        errors, _ = schema.check("ddr", ddr)
        if errors:
            raise ValueError(f"invalid DDR {ddr['id']}: {errors[:3]}")
        _append("ddr", ddr)
        _write_ars([actions.make_ar("ddr", ddr["id"][15:], now, meta, "hook", tuid, ddr=ddr["id"])])


def ddr_from_question(q: dict, answer: str | None, at: str, meta: dict, tool_use_id: str = "", index: int = 0,
                      notes: str | None = None) -> dict:
    """A DDR from one question of Claude Code's question tool, and its answer when there is one."""
    options = []
    recommended = None
    for o in q.get("options") or []:
        if not isinstance(o, dict) or not o.get("label"):
            continue
        label = o["label"]
        if answers_lane.MARK_RE.search(label):  # (Recommended), (Recommandé)
            label = answers_lane.MARK_RE.sub("", label)
            recommended = recommended or label
        opt = {"label": label}
        if o.get("description"):
            opt["consequences"] = o["description"]
        options.append(opt)
    if recommended:  # the recommended option first, as rule R1 wants
        options.sort(key=lambda o: o["label"] != recommended)
    header = q.get("header") or q["question"][:60]
    suffix = actions.slug(f"{tool_use_id[-6:]}-{index}" if tool_use_id else str(index), 12)
    ddr: dict = {
        "v": 1,
        "id": f"ddr-{at[:10]}-{actions.slug(header, 40)}-{suffix}",
        "title": header[:100],
        "question": q["question"],
        "options": options[:4],
        "recommendation": {"option": recommended, "why": "" if recommended else "not given"},
        "multi_select": bool(q.get("multiSelect")),
        "other_allowed": True,
        "status": "pending",
        "asked": {"at": at, "by": meta.get("session_id") or "unknown", "via": "ask-tool"},
    }
    if meta.get("model"):
        ddr["asked"]["model"] = meta["model"]
    if answer:
        # the tool joins the labels of a multiple choice with ", "
        norm = re.sub(r"\s*\((?:recommandée?|recommended)\)", "", answer, flags=re.I)
        choices = [o["label"] for o in ddr["options"] if norm == o["label"] or f", {o['label']}, " in f", {norm}, "]
        ans: dict = {"at": at, "by": "user", "via": "ask-tool"}
        if choices:
            ans["choices"] = choices if ddr["multi_select"] else choices[:1]
        else:
            ans["other"] = answer
        if notes:
            ans["notes"] = notes
        ddr["answer"] = ans
        ddr["status"] = "answered"
        ddr["read"] = {"at": at, "session": meta.get("session_id") or "unknown"}
    return secretscan.clean(ddr)[0]


def post_tool_use(payload: dict, family: str = "") -> None:
    tool = payload.get("tool_name")
    if tool == "AskUserQuestion":
        _ask_question(payload)
        return
    if tool in plan.PLAN_TOOLS:
        plan.capture(payload, _now())
        return
    if tool not in ("Bash", "PowerShell"):
        return
    command = (payload.get("tool_input") or {}).get("command") or ""
    ars = actions.from_tool_call(command, payload.get("cwd") or ".", payload.get("tool_response"), _meta(payload),
                                 tool_use_id=payload.get("tool_use_id") or "", source="hook", family=family)
    _write_ars(ars)


def stop(payload: dict) -> None:
    sid, path = payload.get("session_id"), payload.get("transcript_path")
    if not sid or not path or not Path(path).exists():
        return
    d = paths.sessions_dir()
    d.mkdir(parents=True, exist_ok=True)
    state_f = d / f"{sid}.state.json"
    stats = transcript.SessionStats()
    if state_f.exists():
        try:
            stats = transcript.SessionStats.from_state(json.loads(state_f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            stats = transcript.SessionStats()
    if stats.offset > Path(path).stat().st_size:  # the file was rewritten: start over
        stats = transcript.SessionStats()
    stats.feed_file(path)
    ar_ids, ddr_ids = _session_ids("ar", sid), _session_ids("ddr", sid)
    sr = stats.record(path, status="open", actions=ar_ids, ddrs=ddr_ids)
    tmp = d / f"{sid}.json.tmp"
    tmp.write_text(json.dumps(sr, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / f"{sid}.json")
    state_f.write_text(json.dumps(stats.to_state(), ensure_ascii=False), encoding="utf-8")


def _session_ids(name: str, sid: str) -> list[str]:
    out = []
    for f in sorted(paths.ledger_dir().glob(f"{name}-*.jsonl"))[-2:]:
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                if sid in line:
                    rec = json.loads(line)
                    owner = (rec.get("session") or {}).get("id") or (rec.get("asked") or {}).get("by")
                    if owner == sid:
                        out.append(rec["id"])
        except (OSError, ValueError):
            continue
    return out


HANDLERS = {"session-start": session_start, "session-end": session_end, "stop": stop}


def main(argv: list[str] | None = None, stdin=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if os.environ.get("BRAIN_CAPTURE", "1") == "0" or not argv:
        return 0
    event = argv[0]
    started = time.monotonic()
    try:
        payload = midsession.read_payload(stdin)   # UTF-8 bytes, whatever the console's codepage
        if event == "post-tool-use":
            post_tool_use(payload, argv[1] if len(argv) > 1 else "")
        elif event in HANDLERS:
            HANDLERS[event](payload)
    except Exception as exc:  # never break the session
        _log_error(event, exc)
    if os.environ.get("BRAIN_CAPTURE_TIMING"):
        _log_error(event, RuntimeError(f"took {time.monotonic() - started:.3f}s"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
