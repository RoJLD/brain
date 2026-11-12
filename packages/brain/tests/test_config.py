import json

from brain import __version__, cli, config, projects



def _brain(tmp_path, monkeypatch, cfg=None, owner="Ada"):
    """A personal brain at tmp_path/brain: a registry naming it, a store whose schema declares ``owner``, a rules file,
    and config.json when ``cfg`` is given; $BRAIN_CONFIG and $BRAIN_PROJECTS point at it."""
    root = tmp_path / "brain"
    (root / "notes" / "graph").mkdir(parents=True)
    (root / "notes" / "graph" / "schema.yaml").write_text(
        (f"owner: {owner}\n" if owner else "") + "node_types: [WorkItem]\n", encoding="utf-8")
    (root / "rules").mkdir()
    (root / "rules" / "global.md").write_text("# Rules\n", encoding="utf-8")
    (root / "projects.yaml").write_text("mine: {root: .}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    monkeypatch.setenv("BRAIN_CONFIG", str(root / config.FILE))
    if cfg is not None:
        (root / config.FILE).write_text(json.dumps(cfg) if isinstance(cfg, dict) else cfg, encoding="utf-8")
    return root


GOOD = {"v": 1, "identity": {"owner": "Ada", "kind": "team", "tenant": "ada-lab"}, "registry": "projects.yaml",
        "rules": ["rules/global.md"], "engine": {"repo": "someone/brain", "pin": "v0.2.0"},
        "public": {"repos": ["someone/brain"], "deny": {"hosts": ["box1"], "people": ["Ada"]},
                   "allow": {"LICENSE": "the licence keeps its author's name"}},
        "secrets": {"NTFY_TOKEN": "the ntfy server's token"}}


def test_no_file_runs_on_the_defaults_and_the_stores_owner(tmp_path, monkeypatch):
    root = _brain(tmp_path, monkeypatch)
    cfg = config.load(root)
    assert cfg.file is None and cfg.get("registry") == "projects.yaml" and cfg.path("memory") == root / "memory"
    assert config.owner(cfg) == "Ada"
    assert config.check(root) == []
    (root / "notes" / "graph" / "schema.yaml").write_text("node_types: [WorkItem]\n", encoding="utf-8")
    assert config.owner(config.load(root)) == config.NO_OWNER


def test_a_good_config_is_described_and_passes(tmp_path, monkeypatch):
    root = _brain(tmp_path, monkeypatch, GOOD)
    assert config.check(root) == []
    d = config.describe(config.load(root))
    assert d["owner"] == "Ada" and d["kind"] == "team" and d["tenant"] == "ada-lab"
    assert d["engine"] == {"repo": "someone/brain", "pin": "v0.2.0"} and d["public_repos"] == ["someone/brain"]
    # mine, the brain's own project, gives its repo's folder, brain: the engine's own name, never derived
    assert d["deny"] == {"people": 1, "users": 0, "hosts": 1, "repos": 0, "paths": 0}
    assert d["derive"] == ["hosts", "people", "projects", "specs", "modules"] and d["public_names"] == []
    assert d["secrets"] == ["NTFY_TOKEN"] and d["allow"] == ["LICENSE"]
    assert config.deny_terms(config.load(root)) == [("people", "Ada"), ("hosts", "box1")]


def test_the_contract_is_checked(tmp_path, monkeypatch):
    bad = {**GOOD, "v": 1, "colour": "blue", "identity": {"owner": "Ada", "tenant": "Ada Lab"},
           "engine": {"repo": "someone/brain", "pin": "main"}, "rules": ["rules/missing.md"],
           "memory": "nowhere", "public": {"deny": {"hosts": ["x"]}, "allow": {"LICENSE": "short"}},
           "secrets": {"TOKEN": ""}}
    root = _brain(tmp_path, monkeypatch, bad)
    errors = "\n".join(config.check(root))
    for part in ("unexpected field 'colour'", "identity.tenant", "engine.pin",
                 "public.deny.hosts[0]: shorter than 2", "public.allow.LICENSE: shorter than 15",
                 "secrets.TOKEN: shorter than 1", "rules 'rules/missing.md' does not exist",
                 "memory 'nowhere' does not exist"):
        assert part in errors, part
    assert errors.startswith("config.json")
    root = _brain(tmp_path / "newer", monkeypatch, {**bad, "v": 2})
    errors = config.check(root)   # a newer contract: refused alone, its other fields are not judged by this engine
    assert errors[0] == f"config.json: v2 is written by brain > {__version__}, which reads v1: brain update"
    assert not any("colour" in e or "engine.pin" in e for e in errors)
    root = _brain(tmp_path / "zero", monkeypatch, {**bad, "v": 0})
    assert "config.json.v: must be 1" in config.check(root)


def test_usage_guard_percentages_have_a_maximum(tmp_path, monkeypatch):
    """wi-brain-schema-keywords: maximum is enforced, so critical: 950 no longer turns the governor's refusal off."""
    cfg = {"v": 1, "identity": {"owner": "Ada"}, "usage": {"guard": {"warn": 80, "critical": 950, "memory": 100}}}
    root = _brain(tmp_path, monkeypatch, cfg)
    assert config.check(root) == ["config.json.usage.guard.critical: above 100"]


def test_read_mode_keeps_a_newer_brains_key_and_notes_it(tmp_path, monkeypatch, capsys):
    """wi-brain-tolerant-reader: outside CI an unknown key is a note, the file is kept as it is; in CI it is an
    error."""
    root = _brain(tmp_path, monkeypatch, {**GOOD, "colour": "blue", "identity": {**GOOD["identity"], "pet": "x"}})
    monkeypatch.setenv("BRAIN_STRICT", "0")
    assert config.check(root) == []
    err = capsys.readouterr().err
    assert "unknown field 'colour'" in err and "identity: unknown field 'pet'" in err
    assert config.load(root).data["colour"] == "blue"
    monkeypatch.setenv("BRAIN_STRICT", "1")
    assert sorted(config.check(root)) == ["config.json.identity: unexpected field 'pet'",
                                          "config.json: unexpected field 'colour'"]


def test_owner_must_be_the_stores_owner(tmp_path, monkeypatch):
    root = _brain(tmp_path, monkeypatch, {"v": 1, "identity": {"owner": "Bob"}})
    assert config.check(root) == ["config.json: identity.owner 'Bob', but notes/graph/schema.yaml says owner: Ada"]
    assert config.owner(config.load(root)) == "Bob"


def test_unreadable_file_is_reported_never_raised(tmp_path, monkeypatch):
    root = _brain(tmp_path, monkeypatch, "{not json")
    cfg = config.load(root)
    assert cfg.data == {} and cfg.get("records") == "records"
    assert config.check(root)[0].startswith("config.json: not readable JSON")
    root2 = _brain(tmp_path / "b", monkeypatch, "[1, 2]")
    assert config.check(root2) == ["config.json: an object, got list"]


def test_found_like_the_registry(tmp_path, monkeypatch):
    root = _brain(tmp_path, monkeypatch, GOOD)
    monkeypatch.delenv("BRAIN_CONFIG")
    assert config.config_file(root) == root / config.FILE
    monkeypatch.setenv("CLAUDE_BRAIN_DIR", str(root))
    assert config.config_file(tmp_path / "elsewhere") == root / config.FILE


def test_owner_rules_and_claude_names(tmp_path, monkeypatch):
    root = _brain(tmp_path, monkeypatch, {**GOOD, "adapters": {"claude": {"marketplace": "ada-brain",
                                                                           "plugin": "ada-core",
                                                                           "source": "someone/ada-brain"}}})
    cfg = config.load()
    assert config.owner_of() == "Ada" and config.rules_files(cfg) == [root / "rules" / "global.md"]
    assert config.claude(cfg) == {"marketplace": "ada-brain", "plugin": "ada-core", "source": "someone/ada-brain"}
    assert config.check(root) == [] and config.describe(cfg)["claude"]["plugin"] == "ada-core"
    root = _brain(tmp_path / "other", monkeypatch, {"v": 1, "identity": {"owner": "Ada"}})
    assert config.claude(config.load()) == config.CLAUDE and config.rules_files(config.load()) == []
    _brain(tmp_path / "bad", monkeypatch, {"v": 1, "identity": {"owner": "Ada"},
                                           "adapters": {"claude": {"plugin": "Ada Core"}, "cursor": {}}})
    errors = config.check()
    assert any("plugin" in e for e in errors) and any("cursor" in e for e in errors)


def test_the_views_name_the_owner_of_config_json(tmp_path, monkeypatch, capsys):
    """No view, help or default names a person the code chose: they come from config.json."""
    _brain(tmp_path, monkeypatch, {"v": 1, "identity": {"owner": "Bob"}})
    assert config.owner_of() == "Bob"
    try:
        cli.main(["--help"])
    except SystemExit:
        pass
    assert "Bob's decision queue" in capsys.readouterr().out
    assert cli.build_parser().parse_args(["queue", "done", "x"]).by == "Bob"
    assert cli.build_parser().parse_args(["decision", "answer", "x", "1"]).by == "Bob"


def test_keys_come_from_the_schema():
    keys = dict(config.keys())
    for k in ("v", "identity", "identity.owner", "identity.tenant", "registry", "rules", "engine.pin",
              "public.deny.hosts", "public.allow", "secrets"):
        assert k in keys and keys[k], k
    assert "people" in keys["public.deny.people"].lower()


def test_cli_config_show_keys_check_and_json(tmp_path, monkeypatch, capsys):
    root = _brain(tmp_path, monkeypatch, GOOD)
    assert cli.main(["--root", str(root), "config"]) == 0
    out = capsys.readouterr().out
    assert "owner Ada (team, tenant ada-lab)" in out and "someone/brain@v0.2.0" in out and "hosts 1" in out
    assert "box1" not in out  # counts only: the terms stay in the file
    assert cli.main(["--root", str(root), "config", "--keys"]) == 0
    assert "identity.owner" in capsys.readouterr().out
    assert cli.main(["--root", str(root), "config", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["errors"] == [] and data["config"]["owner"] == "Ada"
    (root / config.FILE).write_text(json.dumps({"v": 1}), encoding="utf-8")
    assert cli.main(["--root", str(root), "config", "--check"]) == 1
    assert "missing 'identity'" in capsys.readouterr().out
    assert cli.main(["--root", str(root), "config"]) == 0  # shown, not checked


def test_check_all_reports_a_broken_config(tmp_path, monkeypatch, capsys):
    root = _brain(tmp_path, monkeypatch, {"v": 1, "identity": {"owner": "Bob"}})
    assert cli.check_registry(root, list(projects.load(root).values())) == 1
    assert "identity.owner 'Bob'" in capsys.readouterr().out
