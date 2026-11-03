import json
from pathlib import Path

import pytest

from brain import boundary, cli, config

from conftest import run_git

REPO = Path(__file__).resolve().parents[1]

MANIFEST = """v: 1
rules:
  - {glob: "notes/**/_generated_*.yaml", side: generated}
  - {glob: "src/brain/**", side: engine, target: "packages/brain/src/brain/"}
  - {glob: "install.ps1", side: engine, target: "packages/brain/installer/install.ps1"}
  - {glob: ".claude-plugin/*.json", side: claude}
  - {glob: "notes/**", side: personal}
  - {glob: "LICENSE", side: personal}
  - {glob: "boundary.yaml", side: personal}
  - {glob: "config.json", side: personal, init: "brain init"}
  - {glob: "old/**", side: personal}
"""


@pytest.fixture
def repo(git_repo, monkeypatch):
    """git_repo plus engine, personal, claude and generated files, a config.json with denied terms, boundary.yaml."""
    files = {"src/brain/cli.py": "# Ada's command, run from E:\\Work\\box1\n", "src/brain/sub/x.py": "ada = 1\n",
             "install.ps1": "Write-Host 'for Ada on BOX1'\n", ".claude-plugin/marketplace.json": "{}\n",
             "notes/graph/nodes/_generated_x.yaml": "[]\n", "LICENSE": "Copyright Ada\n",
             "src/brain/data.bin": b"\xff\xfe\x00Ada"}
    for rel, text in files.items():
        p = git_repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text) if isinstance(text, bytes) else p.write_text(text, encoding="utf-8")
    (git_repo / boundary.FILE).write_text(MANIFEST, encoding="utf-8")
    (git_repo / config.FILE).write_text(json.dumps(
        {"v": 1, "identity": {"owner": "Ada"},
         "public": {"repos": ["someone/brain"], "deny": {"people": ["Ada"], "hosts": ["box1"], "paths": ["E:/Work"]},
                    "allow": {"LICENSE": "the licence keeps its author's name"}}}), encoding="utf-8")
    run_git(git_repo, "add", "-A")
    run_git(git_repo, "commit", "-q", "-m", "files")
    monkeypatch.setenv("BRAIN_CONFIG", str(git_repo / config.FILE))
    monkeypatch.delenv("BRAIN_PROJECTS", raising=False)
    return git_repo


def test_glob_regex():
    rx = boundary.glob_regex
    assert rx("notes/**").match("notes/a/b.md") and rx("notes/**").match("notes/x")
    assert rx("**/_generated_*.yaml").match("_generated_a.yaml") and rx("**/_generated_*.yaml").match("a/b/_generated_x.yaml")
    assert rx("a/*.py").match("a/x.py") and not rx("a/*.py").match("a/b/x.py")
    assert rx("README.md").match("README.md") and not rx("README.md").match("docs/README.md")
    assert rx("a?.md").match("ab.md") and not rx("a?.md").match("a/.md")


def test_targets():
    r = boundary.Rule("plugins/x/brain/**", "engine", "packages/brain/src/brain/")
    assert r.target_of("plugins/x/brain/schemas/a.json") == "packages/brain/src/brain/schemas/a.json"
    assert boundary.Rule("install.ps1", "engine", "installer/install.ps1").target_of("install.ps1") == \
        "installer/install.ps1"
    assert boundary.Rule("hooks/*.sh", "engine", "adapters/").target_of("hooks/a.sh") == "adapters/a.sh"


def test_classify_first_rule_wins_and_finds_what_is_wrong():
    rules = [boundary.Rule(g, s, t, regex=boundary.glob_regex(g)) for g, s, t in (
        ("notes/**/_generated_*", "generated", ""), ("notes/**", "personal", ""), ("a/**", "engine", "x/"),
        ("b/one.py", "engine", "x/one.py"), ("c/**", "engine", ""), ("gone/**", "personal", ""))]
    c = boundary.classify(rules, ["notes/g/_generated_a.yaml", "notes/j.md", "a/one.py", "b/one.py", "c/z", "top.md"])
    assert c["by_side"]["generated"] == ["notes/g/_generated_a.yaml"] and c["by_side"]["personal"] == ["notes/j.md"]
    assert c["unclassified"] == ["top.md"] and c["stale"] == ["gone/**"]
    assert "boundary.yaml: engine rule 'c/**' has no target" in c["errors"]
    assert any("both leave for x/one.py" in e for e in c["errors"])


def test_init_names_the_wizard_step_of_a_personal_or_claude_file():
    rules = [boundary.Rule("a/**", "engine", "x/", init="brain init", regex=boundary.glob_regex("a/**")),
             boundary.Rule("v.md", "generated", init="brain init", regex=boundary.glob_regex("v.md")),
             boundary.Rule("c.json", "personal", init="brain init", regex=boundary.glob_regex("c.json")),
             boundary.Rule("m.json", "claude", init="brain render", regex=boundary.glob_regex("m.json"))]
    errors = boundary.classify(rules, ["a/x", "v.md", "c.json", "m.json"])["errors"]
    assert errors == ["boundary.yaml: engine rule 'a/**' has an init: only personal and claude files start a new "
                      "user's brain",
                      "boundary.yaml: generated rule 'v.md' has an init: only personal and claude files start a new "
                      "user's brain"]


def test_manifest_errors(tmp_path):
    with pytest.raises(boundary.BoundaryError, match="no boundary.yaml"):
        boundary.load(tmp_path)
    for text, msg in (("v: 1\n", "rules is a list"), ("rules: [{side: engine}]\n", "a mapping with a glob"),
                      ("rules: [{glob: a, side: public}]\n", "side is one of"),
                      ("rules: [{glob: a, side: personal, owner: x}]\n", "unknown key"),
                      ("rules: [{glob: a, side: personal, init: ''}]\n", "init names the wizard step")):
        (tmp_path / boundary.FILE).write_text(text, encoding="utf-8")
        with pytest.raises(boundary.BoundaryError, match=msg):
            boundary.load(tmp_path)


def test_report_and_readiness(repo):
    data = boundary.report(repo)
    assert data["counts"] == {"engine": 4, "personal": 5, "claude": 1, "generated": 1}
    assert data["engine_targets"]["src/brain/sub/x.py"] == "packages/brain/src/brain/sub/x.py"
    assert data["engine_repo"] == "someone/brain" and data["deny_terms"] == 3
    assert data["unclassified"] == [] and data["errors"] == []
    r = data["readiness"]
    # whole words, case-insensitive, \ and / alike; the binary file is unread, LICENSE is personal anyway
    assert r["files"]["src/brain/cli.py"] == {"Ada": 1, "box1": 1, "E:/Work": 1}
    assert r["files"]["src/brain/sub/x.py"] == {"Ada": 1} and r["files"]["install.ps1"] == {"Ada": 1, "box1": 1}
    assert r["total"] == 6 and r["terms"]["people"] == {"Ada": 3} and r["unread"] == ["src/brain/data.bin"]
    assert data["stale"] == ["old/**"]


def test_allow_skips_a_file(repo):
    cfg = config.load(repo)
    r = boundary.readiness(repo, cfg, ["LICENSE", "install.ps1"])
    assert r["allowed"] == ["LICENSE"] and list(r["files"]) == ["install.ps1"]


def test_readiness_max_is_a_ratchet(repo, capsys):
    """boundary.yaml's readiness_max: --check fails once the engine side holds more denied terms."""
    text = (repo / boundary.FILE).read_text(encoding="utf-8")
    (repo / boundary.FILE).write_text(text.replace("v: 1\n", "v: 1\nreadiness_max: 6\n"), encoding="utf-8")
    assert cli.main(["--root", str(repo), "boundary", "--check"]) == 0
    assert "(readiness_max 6)" in capsys.readouterr().out
    (repo / boundary.FILE).write_text(text.replace("v: 1\n", "v: 1\nreadiness_max: 5\n"), encoding="utf-8")
    assert boundary.over(boundary.report(repo)) == 1
    assert cli.main(["--root", str(repo), "boundary", "--check"]) == 1
    assert "error: the engine side holds 6 denied term(s), 1 over readiness_max 5" in capsys.readouterr().out
    assert cli.main(["--root", str(repo), "boundary"]) == 0  # a report, not a check
    capsys.readouterr()
    (repo / boundary.FILE).write_text(text.replace("v: 1\n", "v: 1\nreadiness_max: -1\n"), encoding="utf-8")
    assert cli.main(["--root", str(repo), "boundary"]) == 2


def test_cli_boundary(repo, capsys):
    (repo / "loose.txt").write_text("x\n", encoding="utf-8")
    run_git(repo, "add", "loose.txt")
    assert cli.main(["--root", str(repo), "boundary"]) == 0
    out = capsys.readouterr().out
    assert "leave for the engine's repo (someone/brain)" in out
    assert "readiness: 6 denied term(s) in 3 engine file(s): Ada 3, box1 2, E:/Work 1" in out
    assert "error: loose.txt: no rule of boundary.yaml classifies it" in out
    assert "warning: rule 'old/**' classifies no tracked file" in out
    assert cli.main(["--root", str(repo), "boundary", "--check"]) == 1
    capsys.readouterr()
    assert cli.main(["--root", str(repo), "boundary", "--side", "engine"]) == 0
    assert "install.ps1 -> packages/brain/installer/install.ps1" in capsys.readouterr().out
    assert cli.main(["--root", str(repo), "boundary", "--side", "personal"]) == 0
    personal = capsys.readouterr().out
    assert "config.json  (init: brain init)" in personal and "LICENSE\n" in personal
    assert cli.main(["--root", str(repo), "boundary"]) == 0
    assert "stay here (1 with an init: the setup wizard writes their first version)" in capsys.readouterr().out
    assert cli.main(["--root", str(repo), "boundary", "--readiness"]) == 0
    assert "  src/brain/cli.py: " in capsys.readouterr().out
    assert cli.main(["--root", str(repo), "boundary", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["unclassified"] == ["loose.txt"]
    (repo / boundary.FILE).write_text("v: 1\n", encoding="utf-8")
    assert cli.main(["--root", str(repo), "boundary"]) == 2


def test_this_repo_every_tracked_file_has_a_side(monkeypatch):
    """The guard of the boundary: a new file of this repo gets a rule of boundary.yaml (engine, personal, claude
    or generated), so the engine side stays exact until it leaves."""
    monkeypatch.setenv("BRAIN_CONFIG", str(REPO / config.FILE))
    data = boundary.report(REPO)
    assert data["unclassified"] == [], f"add a rule to boundary.yaml for: {data['unclassified']}"
    assert data["errors"] == []
    assert data["counts"]["engine"] > 0 and data["counts"]["personal"] > 0
    assert all(t.startswith("packages/brain/") for t in data["engine_targets"].values())
    # wi-brain-owner-neutral: the ratchet holds, so no module or test names the owner or a private name again
    assert data["readiness_max"] is not None
    assert data["readiness"]["total"] <= data["readiness_max"], (
        f"the engine side names private terms again: {data['readiness']['files']}; read the owner and the personal "
        "names from config.json (brain.config: owner_of(), claude()), and use invented names in tests (Ada, demo)")
    # PB-1 (answered 2026-11-02): every personal configuration is initialisable by a wizard
    for f in ("config.json", "projects.yaml", "notes/graph/schema.yaml", ".claude-plugin/marketplace.json"):
        assert data["init"].get(f), f"{f}: no init in boundary.yaml"
