"""wi-brain-session-provenance (spec-brain-multi-agent-connector § 9, MA-5): where a session ran. Session records gain
provider, harness (tool read as its fallback) and an account alias with its plan, never an e-mail address; additive:
old records stay valid and read alike; brain usage and brain status break the cost down by provider, harness and
account (brain.provenance, brain.cost)."""

import io
import json

import pytest

from brain import backfill, capture, cli, config, cost, projects, provenance, records, schema, status, usage

ADDRESS = "ada" + "@" + "example.org"   # an e-mail-shaped value (never a real one)
UUID = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"
ACCOUNTS = [{"alias": "solo", "plan": "Pro", "since": ""},
            {"alias": "main", "plan": "Max", "since": "2026-11-05"},
            {"alias": "ide", "plan": "Team", "since": "2026-11-01", "harness": "cursor", "provider": "anthropic"}]


@pytest.fixture
def ada_config(tmp_path, monkeypatch):
    """Ada's config.json with her accounts (config.json usage.accounts); BRAIN_CONFIG points at it."""
    base = json.loads(open(config.config_file(), encoding="utf-8").read())
    base["usage"] = {"accounts": ACCOUNTS}
    f = tmp_path / "ada" / "config.json"
    f.parent.mkdir()
    f.write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    return f


# --- the values ---

@pytest.mark.parametrize("model, provider", [
    ("claude-opus-5-5", "anthropic"),
    ("us.anthropic.claude-sonnet-5-5-v1:0", "bedrock"),
    ("anthropic.claude-haiku-5-5-v1:0", "bedrock"),
    ("arn:aws:bedrock:us-east-1:123:inference-profile/x", "bedrock"),
    ("claude-opus-5-5@20261101", "vertex"),
    ("<synthetic>", ""), ("", ""), (None, ""), ("gpt-9", ""),
])
def test_the_provider_a_model_id_implies(model, provider):
    assert provenance.provider_from_model(model) == provider


def test_the_provider_claude_codes_environment_switches_to():
    assert provenance.provider_from_env({}) == "" and provenance.provider_from_env(None) == ""
    assert provenance.provider_from_env({"CLAUDE_CODE_USE_BEDROCK": "1"}) == "bedrock"
    assert provenance.provider_from_env({"CLAUDE_CODE_USE_VERTEX": "true"}) == "vertex"
    assert provenance.provider_from_env({"CLAUDE_CODE_USE_FOUNDRY": "1"}) == "foundry"
    assert provenance.provider_from_env({"CLAUDE_CODE_USE_BEDROCK": "0", "CLAUDE_CODE_USE_VERTEX": ""}) == ""


def test_harness_takes_over_tool_read_as_its_fallback():
    assert provenance.harness_of({"harness": "cursor", "tool": "claude-code"}) == "cursor"
    assert provenance.harness_of({"tool": "claude-code"}) == "claude-code"   # an old record
    assert provenance.harness_of({}) == "claude-code"                         # a ledger row (Claude Code's reader)
    assert provenance.harness_of({"harness": "Not An Id!"}) == "claude-code"


def test_an_alias_is_never_an_email_address_nor_an_account_id():
    assert provenance.safe_alias("main") == "main" and provenance.safe_alias("team-2.b_x") == "team-2.b_x"
    for bad in (ADDRESS, UUID, UUID.replace("-", ""), "", " main", "a b", "x" * 41, None, 3):
        assert provenance.safe_alias(bad) == ""


def test_the_account_in_force_on_a_day_of_its_harness():
    accts = provenance.accounts({"accounts": ACCOUNTS + [{"alias": ADDRESS, "plan": "Max"}, "junk", {"plan": "x"}]})
    assert [a["alias"] for a in accts] == ["solo", "ide", "main"]   # the e-mail-shaped entry is never used
    assert provenance.account_on("2026-11-02", accts)["alias"] == "solo"
    assert provenance.account_on("2026-11-05", accts)["alias"] == "main"
    assert provenance.account_on("2026-11-02", accts, harness="cursor")["alias"] == "ide"
    assert provenance.account_on("2026-11-07", accts, alias="ide")["plan"] == "Team"
    assert provenance.account_on("2026-11-07", accts, alias="other") == {"alias": "other"}
    assert provenance.account_on("2026-11-07", []) == {}


def test_resolve_prefers_what_the_session_captured_then_its_environment():
    cfg = {"accounts": ACCOUNTS}
    assert provenance.resolve("claude-opus-5-5", "2026-11-07", cfg) == {
        "provider": "anthropic", "harness": "claude-code", "account": "main", "plan": "Max"}
    env = {"CLAUDE_CODE_USE_VERTEX": "1", "BRAIN_ACCOUNT": "ide"}
    assert provenance.resolve("claude-opus-5-5", "2026-11-07", cfg, env=env) == {
        "provider": "vertex", "harness": "claude-code", "account": "ide", "plan": "Team"}
    got = provenance.resolve("claude-opus-5-5", "2026-11-07", cfg, env={"BRAIN_ACCOUNT": ADDRESS})
    assert got["account"] == "main" and ADDRESS not in json.dumps(got)   # an e-mail is dropped, never written
    kept = {"provider": "bedrock", "account": "solo", "plan": "Pro"}
    assert provenance.resolve("claude-opus-5-5", "2026-11-07", cfg, env=env, captured=kept) == {
        "provider": "bedrock", "harness": "claude-code", "account": "solo", "plan": "Pro"}
    # no accounts: the plan only from usage.plans the owner set, never the engine's built-in default
    assert provenance.resolve("claude-opus-5-5", "2026-11-07", None) == {"provider": "anthropic",
                                                                         "harness": "claude-code"}
    plans = {"plans": [{"since": "", "plan": "Pro"}, {"since": "2026-11-05", "plan": "Max"}]}
    assert provenance.resolve("claude-opus-5-5", "2026-11-07", plans)["plan"] == "Max"


def test_a_configuration_or_a_snapshot_that_is_garbage_costs_nothing(tmp_path, monkeypatch, brain_home):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(bad))
    (brain_home / "sessions").mkdir(parents=True)
    (brain_home / "sessions" / "s-1.json").write_text("[1, 2", encoding="utf-8")
    assert provenance.captured("s-1") == {} and provenance.captured("../x") == {} and provenance.captured("") == {}
    assert provenance.for_session("claude-opus-5-5", "2026-11-07", session_id="s-1") == {
        "provider": "anthropic", "harness": "claude-code"}
    (brain_home / "sessions" / "s-2.json").write_text(json.dumps(
        {"provider": "vertex", "account": ADDRESS, "plan": "Max"}), encoding="utf-8")
    assert provenance.captured("s-2") == {"provider": "vertex", "plan": "Max"}   # the e-mail-shaped account left out


# --- the session record ---

def _old_sr():
    """An SR as brain 0.5.0 wrote it: tool, no provider, harness or account."""
    return {"v": 1, "id": "sr-2026-11-01-aaaabbbb", "tool": "claude-code",
            "session_id": "aaaabbbb-1111-2222-3333-444455556666", "status": "closed", "model": "claude-opus-5-5",
            "start": "2026-11-01T10:00:00Z", "end": "2026-11-01T11:00:00Z"}


def test_an_old_record_stays_valid_and_reads_alike():
    old = _old_sr()
    assert schema.check("sr", old)[0] == []
    assert provenance.of_row(old) == {"provider": "anthropic", "harness": "claude-code", "account": "(none)",
                                      "plan": "(none)"}
    assert provenance.of_row(old, {"accounts": ACCOUNTS})["account"] == "solo"


def test_an_older_engine_reads_a_new_record_with_notes_only():
    """The SR schema before these fields (brain 0.5.0's: the same, without them) reads a new SR in read mode with an
    unknown field per new key and no error, and keep_unknown carries them through its rewrites."""
    older = json.loads(json.dumps(schema.load("sr")))
    for k in ("provider", "harness", "account", "plan"):
        older["properties"].pop(k)
    new = {**_old_sr(), "harness": "claude-code", "provider": "anthropic", "account": "main", "plan": "Max"}
    errors, unknown = [], []
    schema._validate(new, older, older, "sr", errors, unknown)
    assert errors == [] and sorted(k for _, k in unknown) == ["account", "harness", "plan", "provider"]


def test_the_new_fields_validate_strict_and_an_email_shaped_alias_is_refused():
    new = {**_old_sr(), "harness": "claude-code", "provider": "anthropic", "account": "main", "plan": "Max 20x"}
    assert schema.check("sr", new)[0] == []
    for bad in (ADDRESS, UUID):
        errors = schema.check("sr", {**new, "account": bad})[0]
        assert any(e.startswith("sr.account") for e in errors)
        assert ADDRESS not in " ".join(errors)   # the value is never printed back
    assert schema.check("sr", {**new, "plan": "Max " + ADDRESS})[0]
    assert schema.check("sr", {**new, "provider": "Bedrock!"})[0]
    with pytest.raises(SystemExit) as exc:
        records.validate("sr", {**new, "account": ADDRESS})
    assert ADDRESS not in str(exc.value)


def test_a_record_built_from_a_transcript_carries_where_it_ran(fixture_transcript, ada_config):
    main, subs, n = __import__("brain").transcript.session_stats(fixture_transcript)
    prov = provenance.for_session("claude-opus-5-5", "2026-11-07", session_id=main.session_id)
    sr = main.record(fixture_transcript, provenance=prov)
    assert list(sr)[:7] == ["v", "id", "tool", "harness", "provider", "account", "plan"]
    assert (sr["tool"], sr["harness"], sr["provider"], sr["account"], sr["plan"]) == \
        ("claude-code", "claude-code", "anthropic", "main", "Max")
    assert schema.check("sr", sr)[0] == []
    assert main.record(fixture_transcript)["harness"] == "claude-code"   # without a configuration: no account


def test_the_stop_hook_records_the_sessions_environment(fixture_transcript, ada_config, brain_home, monkeypatch,
                                                        tmp_path):
    t = tmp_path / "s.jsonl"
    t.write_bytes(fixture_transcript.read_bytes())
    payload = {"session_id": "aaaabbbb-1111-2222-3333-444455556666", "transcript_path": str(t)}
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("BRAIN_ACCOUNT", "ide")
    assert capture.main(["stop"], stdin=io.StringIO(json.dumps(payload))) == 0
    sr = json.loads((brain_home / "sessions" / f"{payload['session_id']}.json").read_text(encoding="utf-8"))
    assert (sr["provider"], sr["harness"], sr["account"], sr["plan"]) == ("bedrock", "claude-code", "ide", "Team")
    assert schema.check("sr", sr)[0] == []
    monkeypatch.delenv("CLAUDE_CODE_USE_BEDROCK")
    monkeypatch.setenv("BRAIN_ACCOUNT", ADDRESS)
    assert capture.main(["stop"], stdin=io.StringIO(json.dumps(payload))) == 0
    text = (brain_home / "sessions" / f"{payload['session_id']}.json").read_text(encoding="utf-8")
    sr = json.loads(text)
    assert ADDRESS not in text and sr["account"] != ADDRESS and sr["provider"] == "anthropic"
    log = (brain_home / "ledger" / "errors.log").read_text(encoding="utf-8")
    assert "BRAIN_ACCOUNT is not an alias" in log and ADDRESS not in log


def test_a_rebuilt_record_keeps_where_it_ran_as_recorded():
    old = {**_old_sr(), "provider": "bedrock", "account": "solo"}
    new = {**_old_sr(), "harness": "claude-code", "provider": "anthropic", "status": "closed"}
    got = backfill._merge(old, new)
    assert got["provider"] == "bedrock" and got["account"] == "solo" and got["harness"] == "claude-code"
    assert list(got).index("account") < list(got).index("session_id")


def test_brain_config_check_refuses_an_email_shaped_alias(tmp_path, monkeypatch):
    base = json.loads(open(config.config_file(), encoding="utf-8").read())
    base["usage"] = {"accounts": [{"alias": ADDRESS, "plan": "Max"}]}
    f = tmp_path / "config.json"
    f.write_text(json.dumps(base), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(f))
    errors = config.check()
    assert any("usage.accounts[0].alias" in e for e in errors) and ADDRESS not in " ".join(errors)
    base["usage"] = {"accounts": ACCOUNTS}
    f.write_text(json.dumps(base), encoding="utf-8")
    assert not [e for e in config.check() if "usage" in e]


# --- brain usage and brain status ---

def _row(sid, day, usd, model="claude-opus-5-5", **kw):
    return {"session_id": sid, "folder": "", "start": f"{day}T10:00:00Z", "end": f"{day}T11:00:00Z", "title": "",
            "branch": "b", "kind": "build", "cost": usd, "active_s": 600, "model": model, "tokens": {"output": 10},
            "sub_tokens": {}, "days": {day: {"cost": usd, "messages": 1, "output": 10}}, "brief": {}, "spawned": [],
            "closed": [], "title_items": [], "prs": [], "context": {"peak": 1}, "phases": {}, "signals": {},
            "ngrams": {}, "tools": {}, "commands": {}, "skills": {}, "start_cost": {"cost": 0.1}, **kw}


@pytest.fixture
def lab(store):
    return projects.Project(name="lab", root=store.parents[1], stores=[store])


def _rows(lab):
    rows = [_row("s1", "2026-11-02", 2.0), _row("s2", "2026-11-07", 6.0),
            _row("s3", "2026-11-07", 1.0, model="us.anthropic.claude-opus-5-5-v1:0"),
            _row("s4", "2026-11-07", 1.0, harness="cursor", provider="anthropic"),
            _row("s5", "2026-11-07", 0.5, account=ADDRESS)]
    for r in rows:
        r["folder"] = str(lab.root)
    return rows


def test_usage_breaks_the_cost_down_by_provider_harness_and_account(lab):
    led = cost.Ledger(_rows(lab), [lab], cfg_usage={"accounts": ACCOUNTS})
    rep = cost.report(led, "2026-11-01", "", "summary")
    src = {d: {r["key"]: r for r in rows} for d, rows in rep["sources"].items()}
    assert set(src) == {"provider", "harness", "account"}
    assert src["provider"]["anthropic"]["cost"] == pytest.approx(9.5) and src["provider"]["bedrock"]["sessions"] == 1
    assert src["harness"]["claude-code"]["sessions"] == 4 and src["harness"]["cursor"]["cost"] == pytest.approx(1.0)
    assert src["account"]["main"]["cost"] == pytest.approx(7.0) and src["account"]["main"]["plans"] == ["Max"]
    assert src["account"]["solo"]["sessions"] == 1 and src["account"]["ide"]["plans"] == ["Team"]
    assert src["account"]["(masked)"]["sessions"] == 1
    text = "\n".join(cost.render_report(rep))
    assert "where: provider anthropic" in text and "account main (Max) $7.00" in text and ADDRESS not in text
    for dim in cost.SOURCE_DIMS:
        table = cost.report(led, "2026-11-01", "", dim)["tables"][dim]
        assert sum(r["total"] for r in table) == pytest.approx(10.5)
    assert ADDRESS not in cost.as_json(rep)


def test_usage_without_accounts_reads_old_rows_alike(lab):
    led = cost.Ledger(_rows(lab)[:2], [lab])
    rep = cost.report(led, "", "", "summary")
    assert rep["sources"]["account"] == [{"key": "(none)", "cost": 8.0, "share": 1.0, "sessions": 2, "plans": []}]
    assert rep["sources"]["harness"][0]["key"] == "claude-code"


def test_cli_usage_and_status_json_keys(lab, ada_config, capsys):
    usage.save({f"p/{r['session_id']}.jsonl": r for r in _rows(lab)})
    root = str(lab.root)
    assert cli.main(["--root", root, "usage", "--since", "2026-11-01", "--json", "--no-scan"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert set(rep["sources"]) == {"provider", "harness", "account"}
    assert set(rep["sources"]["account"][0]) == {"key", "cost", "share", "sessions", "plans"}
    assert set(rep["sources"]["provider"][0]) == {"key", "cost", "share", "sessions"}
    assert cli.main(["--root", root, "usage", "--since", "2026-11-01", "--by", "account", "--no-scan"]) == 0
    out = capsys.readouterr().out
    assert "By account" in out and "main" in out and ADDRESS not in out
    s = cost.summary_of(cost.load([lab], refresh=False), "lab", "2026-11-01")
    assert {r["key"] for r in s["sources"]["account"]} == {"solo", "main", "ide", "(masked)"}
    assert "provider anthropic" in cost.summary_line(s) and "account main (Max)" in cost.summary_line(s)
    data = status.collect(lab, quick=True)
    assert "sources" in json.loads(status.render_json({"projects": {"lab": data}}))["projects"]["lab"]["tokens"]
