"""brain.neutral and brain.render: the neutral source (rules with scope and id, procedures, MCP servers, packs) and
brain render --target <tool> (wi-brain-neutral-source). The claude target reproduces a hand-written marketplace byte for
byte: a golden test on an invented brain (Ada's), then on this checkout when it has a neutral source."""

import json
from pathlib import Path

import pytest

from brain import cli, neutral, render


RULES = """\
---
# a comment in the front matter
scope: global
title: Ada's rules — every project
intro: |
  Ada's rules for every agent.
claude:
  title: Ada's rules for Claude — every project
  intro: |
    Source: the repo `ada/brain`, injected by the `ada-core` plugin.
    A project rule wins over these.
---

## Language
<!-- id: rule-language -->

English everywhere.

## Git
<!-- id: rule-git; paths: src/**, docs/*.md -->

- Work in a worktree.
- "Quoted" text and a back\\slash.

### A sub-heading stays in its rule

Text.
"""

PACKS = """\
v: 1
marketplace:
  description: "Ada's plugins."
  owner: {name: ada, url: https://example.invalid/ada}
pointers:
  repo: ada/brain
  memory: memory/
  decisions: notes/decisions.md
packs:
  core:
    core: true
    rules: [rules/global.md]
    procedures: [close-item]
    claude:
      plugin:
        displayName: Ada core
        description: "Ada's rules."
        keywords:
          - rules
          - workflow
      listing:
        description: "Ada's rules, listed."
        category: workflow
  ops:
    projects: [demo]
    procedures: [ops-run]
    mcp: [graph, sidecar]
    claude:
      name: ada-ops
      plugin:
        displayName: Ada ops
        keywords: [ops, graph]
      listing: {category: development}
"""

MCP = """\
v: 1
servers:
  graph:
    transport: http
    url: "${GRAPH_API:-http://localhost:4747}/api/mcp"
  sidecar:
    transport: stdio
    command: node
    args: ["${SIDECAR_ROOT:-D:/work/sidecar}/server.mjs", --quiet]
    env:
      GRAPH_API: "${GRAPH_API:-http://localhost:4747}"
      TOKEN: "${SIDECAR_TOKEN}"
"""

SKILL = """\
---
name: close-item
description: Close a finished item by the owner's definition of done.
---

# Close an item

Walk the steps.
"""

OPS = """\
---
name: ops-run
description: Run the demo operations.
---

# Run

Do it.
"""

GRAPH_SCHEMA = "node_types: [Rule, WorkItem]\nedge_types: [decided_by]\nstatuses: [active, retired, todo]\n"
GRAPH_RULES = """\
- {id: rule-language, type: Rule, status: active, title: "English", anchor: "source/rules/global.md#language"}
- {id: rule-git, type: Rule, status: active, title: "Worktrees", anchor: "source/rules/global.md#git"}
"""


def write(base: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        f = base / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def ada(tmp_path, monkeypatch):
    """An invented personal brain with a neutral source, a registry (demo here, acme beside) and its Rule nodes."""
    root = tmp_path / "ada-brain"
    write(root, {
        "config.json": json.dumps({"v": 1, "identity": {"owner": "Ada", "kind": "person"},
                                   "rules": ["plugins/ada-core/rules/global.md"],
                                   "adapters": {"claude": {"marketplace": "ada-brain", "plugin": "ada-core",
                                                           "source": "ada/brain"}}}),
        "projects.yaml": "demo:\n  root: .\nacme:\n  root: ../acme\n",
        "CLAUDE.md": "# demo — rules for this repo\n\n## Changing the rules\n\nBy ADR.\n",
        "notes/graph/schema.yaml": GRAPH_SCHEMA,
        "notes/graph/nodes/rules.yaml": GRAPH_RULES,
        "source/packs.yaml": PACKS,
        "source/rules/global.md": RULES,
        "source/mcp.yaml": MCP,
        "source/procedures/ops-run/SKILL.md": OPS,
    })
    (tmp_path / "acme").mkdir()
    monkeypatch.setenv("BRAIN_CONFIG", str(root / "config.json"))
    monkeypatch.delenv("BRAIN_PROJECTS", raising=False)
    monkeypatch.delenv("CLAUDE_BRAIN_DIR", raising=False)
    monkeypatch.setattr(neutral, "engine_procedures", lambda: tmp_path / "engine-procedures")
    write(tmp_path / "engine-procedures", {"close-item/SKILL.md": SKILL})
    return root


# --- the neutral source ---------------------------------------------------------------------------------------------

def test_flow_lists_stay_inline_and_block_lists_match_json_dumps():
    data = neutral.load_yaml("a: [x, y]\nb:\n  - 1\n  - 2\nc: {d: [], e: {f: g}}\n")
    assert isinstance(data["a"], neutral.Flow) and not isinstance(data["b"], neutral.Flow)
    assert render.to_json(data) == ('{\n  "a": ["x", "y"],\n  "b": [\n    1,\n    2\n  ],\n  "c": {\n    "d": [],\n'
                                    '    "e": {\n      "f": "g"\n    }\n  }\n}')
    block = neutral.load_yaml("k:\n  - a\n  - {b: [1, 2]}\nn: null\nt: true\n")
    block["k"][1]["b"] = list(block["k"][1]["b"])
    assert render.to_json(block) == json.dumps(block, indent=2)


def test_a_rules_file_gives_each_rule_its_id_scope_and_meta(ada):
    rf = neutral.load(ada).rule_files["rules/global.md"]
    assert rf.scope == "global" and rf.lock == []
    assert [(r.id, r.title, r.line) for r in rf.rules] == [("rule-language", "Language", 14), ("rule-git", "Git", 19)]
    assert rf.rules[1].paths == ["src/**", "docs/*.md"]
    assert "<!--" not in rf.body() and "### A sub-heading stays in its rule" in rf.rules[1].text


def test_each_target_gets_its_own_title_and_intro_else_the_neutral_ones(ada):
    rf = neutral.load(ada).rule_files["rules/global.md"]
    assert rf.render("claude") == ("# Ada's rules for Claude — every project\n\nSource: the repo `ada/brain`, injected "
                                   "by the `ada-core` plugin.\nA project rule wins over these.\n\n## Language\n\n"
                                   "English everywhere.\n\n## Git\n\nApplies to files matching `src/**`, `docs/*.md`.\n"
                                   "\n- Work in a worktree.\n- \"Quoted\" text and a "
                                   "back\\slash.\n\n### A sub-heading stays in its rule\n\nText.\n")
    assert rf.render("agents").startswith("# Ada's rules — every project\n\nAda's rules for every agent.\n\n## Language")


def test_the_engine_procedures_come_first_and_the_owner_lays_files_over_them(ada, tmp_path):
    write(ada / "source" / "procedures" / "close-item", {"acme.md": "# Acme's addendum\n"})
    proc = neutral.load(ada).procedures["close-item"]
    assert proc.engine and sorted(proc.files) == ["SKILL.md", "acme.md"]
    assert proc.files["SKILL.md"] == tmp_path / "engine-procedures" / "close-item" / "SKILL.md"


def test_a_clean_source_checks_clean(ada):
    assert neutral.check(neutral.load(ada)) == []


def test_check_reports_what_breaks_the_source(ada):
    write(ada / "source", {
        "rules/global.md": RULES.replace("<!-- id: rule-git; paths: src/**, docs/*.md -->",
                                         "<!-- id: rule-language; colour: red -->"),
        "rules/scopes/nowhere.md": "---\nlock: [rule-missing]\n---\n\n## Orphan\n\nNo id.\n",
        "mcp.yaml": MCP.replace("    command: node\n", "") + "  odd:\n    transport: ftp\n    url: x\n    port: 1\n",
        "procedures/ops-run/SKILL.md": OPS.replace("name: ops-run", "name: ops"),
        "packs.yaml": PACKS.replace("procedures: [ops-run]", "procedures: [ops-run, missing]")
                           .replace("projects: [demo]", "projects: [demo, ghost]"),
    })
    errors = "\n".join(neutral.check(neutral.load(ada)))
    for bit in ("rule id rule-language already in", "unknown rule meta key 'colour'",
                "scope 'nowhere' is not a node of the scope tree", "rule 'Orphan' has no id",
                "lock 'rule-missing' names no rule", "a stdio server needs a command", "transport 'ftp'",
                "unknown key 'port'", "name 'ops', the folder is 'ops-run'", "procedure 'missing' not in",
                "project 'ghost' is not registered",
                "rule-git is anchored at source/rules/global.md#git but no rule of the source has that id"):
        assert bit in errors, bit


def test_a_rule_without_its_graph_node_is_an_error(ada):
    write(ada, {"notes/graph/nodes/rules.yaml": GRAPH_RULES.replace("status: active, title: \"Worktrees\"",
                                                                     "status: retired, title: \"Worktrees\"")})
    assert any("rule-git is 'retired' in notes/graph" in e for e in neutral.check(neutral.load(ada)))
    write(ada, {"notes/graph/nodes/rules.yaml": GRAPH_RULES.splitlines()[0] + "\n"})
    assert any("rule-git is not a Rule node" in e for e in neutral.check(neutral.load(ada)))


def test_a_lower_rule_overriding_a_locked_one_is_reported(ada):
    write(ada / "source", {"rules/global.md": RULES.replace("scope: global\n", "scope: global\nlock: [rule-git]\n")})
    write(ada, {"CLAUDE.md": "# demo\n\n## Rebase freely\n<!-- overrides: rule-git -->\n\nText.\n\n"
                             "## Other\n<!-- overrides: rule-nothing -->\n\nText.\n"})
    found = neutral.lock_findings(neutral.load(ada), {"demo": ada})
    assert len(found) == 2
    assert found[0].startswith(f"{ada / 'CLAUDE.md'}:3: ")
    assert "'Rebase freely' overrides rule-git, locked by rules/global.md" in found[0]
    assert "'Other' overrides rule-nothing, which names no rule" in found[1]


def test_a_projects_own_comment_under_a_heading_stays_its_text(ada):
    write(ada, {"CLAUDE.md": "# demo\n\n## Notes\n<!-- TODO: tidy -->\n\nText.\n"})
    rf = neutral.project_rules(ada, "demo")
    assert rf.rules[0].id == "" and "<!-- TODO: tidy -->" in rf.render()


def test_a_projects_chain_is_global_then_its_own_rules_last(ada):
    files = neutral.chain(neutral.load(ada), "demo", ada)
    assert [(f.scope, f.project) for f in files] == [("global", False), ("demo", True)]
    assert neutral.chain(neutral.load(ada), None) == files[:1]


# --- the claude target: byte for byte -------------------------------------------------------------------------------

CLAUDE_GOLDEN = {
    ".claude-plugin/marketplace.json": """\
{
  "name": "ada-brain",
  "description": "Ada's plugins.",
  "owner": {
    "name": "ada",
    "url": "https://example.invalid/ada"
  },
  "plugins": [
    {
      "name": "ada-core",
      "source": "./plugins/ada-core",
      "description": "Ada's rules, listed.",
      "category": "workflow"
    },
    {
      "name": "ada-ops",
      "source": "./plugins/ada-ops",
      "category": "development"
    }
  ]
}
""",
    "plugins/ada-core/.claude-plugin/plugin.json": """\
{
  "name": "ada-core",
  "displayName": "Ada core",
  "description": "Ada's rules.",
  "keywords": [
    "rules",
    "workflow"
  ]
}
""",
    "plugins/ada-ops/.claude-plugin/plugin.json": """\
{
  "name": "ada-ops",
  "displayName": "Ada ops",
  "keywords": ["ops", "graph"]
}
""",
    "plugins/ada-ops/.mcp.json": """\
{
  "mcpServers": {
    "graph": {
      "type": "http",
      "url": "${GRAPH_API:-http://localhost:4747}/api/mcp"
    },
    "sidecar": {
      "type": "stdio",
      "command": "node",
      "args": ["${SIDECAR_ROOT:-D:/work/sidecar}/server.mjs", "--quiet"],
      "env": {
        "GRAPH_API": "${GRAPH_API:-http://localhost:4747}",
        "TOKEN": "${SIDECAR_TOKEN}"
      }
    }
  }
}
""",
    "plugins/ada-core/skills/close-item/SKILL.md": SKILL,
    "plugins/ada-ops/skills/ops-run/SKILL.md": OPS,
}


def _files(base: Path) -> dict[str, bytes]:
    return {p.relative_to(base).as_posix(): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}


def test_the_claude_target_writes_the_marketplace_byte_for_byte(ada, tmp_path):
    out = tmp_path / "out"
    assert render.main(ada, "claude", out=out, do_write=True) == 0
    got = _files(out)
    hooks = {k for k in got if "/hooks/" in k}
    assert not hooks   # no pack declares hooks: true
    assert got.pop("plugins/ada-core/rules/global.md") == neutral.load(ada).rule_files["rules/global.md"] \
        .render("claude").encode()
    assert got == {k: v.encode() for k, v in CLAUDE_GOLDEN.items()}


def test_the_names_come_from_config_json_and_must_agree(ada):
    write(ada / "source", {"packs.yaml": PACKS.replace("  description: \"Ada's plugins.\"",
                                                        "  name: other\n  description: \"Ada's plugins.\"")})
    with pytest.raises(render.RenderError, match="marketplace.name 'other', config.json adapters.claude says"):
        render.render(ada, "claude")


def test_hooks_true_copies_the_engine_hooks(ada, tmp_path, monkeypatch):
    hooks = tmp_path / "engine-hooks"
    write(hooks, {"hooks.json": "{}\n", "inject.sh": "echo hi\n"})
    monkeypatch.setattr(render, "claude_hooks", lambda: hooks)
    write(ada / "source", {"packs.yaml": PACKS.replace("    core: true\n", "    core: true\n    hooks: true\n")})
    rels = [o.rel for o in render.render(ada, "claude").outputs]
    assert "plugins/ada-core/hooks/hooks.json" in rels and "plugins/ada-core/hooks/inject.sh" in rels


def test_check_fails_on_a_hand_edit_and_write_removes_a_stray(ada, capsys):
    assert render.main(ada, "claude", do_write=True) == 0
    assert render.main(ada, "claude", check=True) == 0
    rules = ada / "plugins" / "ada-core" / "rules" / "global.md"
    rules.write_text(rules.read_text(encoding="utf-8") + "A hand edit.\n", encoding="utf-8")
    stray = ada / "plugins" / "ada-ops" / "skills" / "gone" / "SKILL.md"
    write(ada, {stray.relative_to(ada).as_posix(): "old\n"})
    capsys.readouterr()
    assert render.main(ada, "claude", check=True) == 1
    said = capsys.readouterr().out
    assert "differs  plugins/ada-core/rules/global.md" in said and "stray    plugins/ada-ops/skills/gone/SKILL.md" \
        in said and "2 file(s) not current" in said
    assert render.main(ada, "claude", do_write=True) == 0
    assert not stray.exists() and "A hand edit" not in rules.read_text(encoding="utf-8")
    assert render.main(ada, "claude", check=True) == 0


def test_a_crlf_checkout_is_current(ada):
    render.main(ada, "claude", do_write=True)
    f = ada / "plugins" / "ada-core" / "rules" / "global.md"
    f.write_bytes(f.read_bytes().replace(b"\n", b"\r\n"))
    assert render.stale(render.plan(render.render(ada, "claude"), render.bases_for(ada, None, None))) == []


def test_write_refuses_a_production_checkout(ada, monkeypatch, capsys):
    monkeypatch.setattr(render, "_production", lambda path: str(path))
    assert render.main(ada, "claude", do_write=True) == 1
    assert "is a production checkout" in capsys.readouterr().out


# --- the other targets ----------------------------------------------------------------------------------------------

def test_agents_md_flattens_the_chain_nearest_last(ada):
    r = render.render(ada, "agents", "demo", ada)
    text = {o.rel: o.text for o in r.outputs}["AGENTS.md"]
    assert text.startswith(f"<!-- {render.MARK} -->\n\n# Ada's rules — every project\n")
    g, m, p = text.index("## Git"), text.index("## Memory and decisions"), text.index("# demo — rules for this repo")
    assert g < m < p and text.endswith("## Changing the rules\n\nBy ADR.\n")
    assert "## Git\n\nApplies to files matching `src/**`, `docs/*.md`.\n" in text
    rels = [o.rel for o in r.outputs]
    assert ".agents/skills/close-item/SKILL.md" in rels and ".agents/skills/ops-run/SKILL.md" in rels
    skill = {o.rel: o.text for o in r.outputs}[".agents/skills/ops-run/SKILL.md"]
    assert skill.startswith(f"---\n# {render.MARK}\nname: ops-run\n")
    assert neutral.front_matter(skill)[0] == {"name": "ops-run", "description": "Run the demo operations."}


def test_a_pack_reaches_only_the_projects_it_names(ada, tmp_path):
    rels = [o.rel for o in render.render(ada, "agents", "acme", tmp_path / "acme").outputs]
    assert ".agents/skills/close-item/SKILL.md" in rels and not any("ops-run" in x for x in rels)


def test_a_foreign_agents_md_is_kept_unless_forced(ada, tmp_path, capsys):
    repo = tmp_path / "acme"
    write(repo, {"AGENTS.md": "# Written by another tool\n"})
    assert render.main(ada, "agents", project="acme", project_root=repo, do_write=True) == 1
    assert "foreign" in capsys.readouterr().out
    assert (repo / "AGENTS.md").read_text(encoding="utf-8") == "# Written by another tool\n"
    assert render.main(ada, "agents", project="acme", project_root=repo, do_write=True, force=True) == 0
    assert render.MARK in (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert render.main(ada, "agents", project="acme", project_root=repo, check=True) == 0


def test_a_procedure_dropped_from_the_source_is_stray_and_the_tools_own_skills_stay(ada, tmp_path):
    repo = tmp_path / "acme"
    write(repo, {".agents/skills/mine/SKILL.md": "---\nname: mine\ndescription: the owner's own.\n---\n"})
    assert render.main(ada, "agents", project="acme", project_root=repo, do_write=True) == 0
    write(ada / "source", {"packs.yaml": PACKS.replace("procedures: [close-item]", "procedures: []")})
    rows = render.plan(render.render(ada, "agents", "acme", repo), render.bases_for(ada, repo, None))
    assert [(x["rel"], x["state"]) for x in rows if x["state"] == "stray"] == \
        [(".agents/skills/close-item/SKILL.md", "stray")]
    assert render.main(ada, "agents", project="acme", project_root=repo, do_write=True) == 0
    assert not (repo / ".agents" / "skills" / "close-item").exists()
    assert (repo / ".agents" / "skills" / "mine" / "SKILL.md").exists()


def _mcp(ada, target, rel, key="mcpServers"):
    r = render.render(ada, target, "demo", ada)
    return json.loads(next(o.text for o in r.outputs if o.rel == rel and o.merge[-1:] == (key,))), r


def test_cursor_writes_env_variables_and_defaults_as_values(ada):
    servers, r = _mcp(ada, "cursor", ".cursor/mcp.json")
    assert servers["graph"] == {"url": "http://localhost:4747/api/mcp"}
    assert servers["sidecar"] == {"type": "stdio", "command": "node", "args": ["D:/work/sidecar/server.mjs", "--quiet"],
                                  "env": {"GRAPH_API": "http://localhost:4747", "TOKEN": "${env:SIDECAR_TOKEN}"}}
    assert any("Cursor has no default" in n for n in r.notes)


def test_gemini_reads_agents_md_and_uses_httpurl(ada):
    servers, _ = _mcp(ada, "gemini", ".gemini/settings.json")
    names, _ = _mcp(ada, "gemini", ".gemini/settings.json", "fileName")
    assert names == ["AGENTS.md", "GEMINI.md"]
    assert servers["graph"] == {"httpUrl": "${GRAPH_API:-http://localhost:4747}/api/mcp"}
    assert servers["sidecar"]["env"]["TOKEN"] == "${SIDECAR_TOKEN}"


def test_antigravity_uses_serverurl_and_drops_sse(ada):
    write(ada / "source", {"mcp.yaml": MCP + "  old:\n    transport: sse\n    url: http://x\n"})
    write(ada / "source", {"packs.yaml": PACKS.replace("mcp: [graph, sidecar]", "mcp: [graph, sidecar, old]")})
    servers, r = _mcp(ada, "antigravity", ".agents/mcp_config.json")
    assert servers["graph"] == {"serverUrl": "http://localhost:4747/api/mcp"} and "old" not in servers
    assert any("old: Antigravity has no SSE" in n for n in r.notes)


def test_grok_writes_toml_tables_and_its_own_skills_folder(ada):
    r = render.render(ada, "grok", "demo", ada)
    toml = next(o.text for o in r.outputs if o.rel == ".grok/config.toml")
    import tomllib
    data = tomllib.loads(toml)["mcp_servers"]
    assert data["graph"] == {"url": "${GRAPH_API:-http://localhost:4747}/api/mcp"}
    assert data["sidecar"]["args"] == ["${SIDECAR_ROOT:-D:/work/sidecar}/server.mjs", "--quiet"]
    assert ".grok/skills/ops-run/SKILL.md" in [o.rel for o in r.outputs]
    assert any("reads CLAUDE.md beside AGENTS.md" in n for n in r.notes)


def test_hermes_mcp_servers_are_lines_to_add_by_hand(ada, tmp_path):
    r = render.render(ada, "hermes", "demo", ada)
    manual = [o for o in r.outputs if o.manual]
    import yaml
    assert len(manual) == 1 and manual[0].base == "user"
    assert yaml.safe_load(manual[0].text)["mcp_servers"]["sidecar"]["env"]["GRAPH_API"] == "http://localhost:4747"
    rows = render.write(r, render.bases_for(ada, ada, None))
    assert [x for x in rows if x["state"] == "manual" and x["written"]] == []
    assert not (tmp_path / "home").exists()


def test_a_merge_keeps_the_files_other_entries(ada):
    write(ada, {".cursor/mcp.json": '{"mcpServers": {"mine": {"command": "x"}}, "other": 1}\n'})
    assert render.main(ada, "cursor", project="demo", project_root=ada, do_write=True) == 0
    data = json.loads((ada / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert data["other"] == 1 and set(data["mcpServers"]) == {"mine", "graph", "sidecar"}
    assert render.main(ada, "cursor", project="demo", project_root=ada, check=True) == 0


def test_a_rendered_repo_is_kept_current_by_sync_and_reported_by_check(ada, tmp_path):
    acme = tmp_path / "acme"
    assert render.keep_current(ada, "demo", fix=False) == []   # nothing rendered into a repo yet: nothing to follow
    render.main(ada, "agents", project="demo", project_root=ada, do_write=True)
    assert render.keep_current(ada, "demo", fix=False) == []
    assert render.keep_current(acme, "acme", fix=False) == []   # a repo that did not opt in stays out
    write(ada, {"CLAUDE.md": "# demo\n\n## Changed\n\nNew.\n"})
    assert render.keep_current(ada, "demo", fix=False) == [
        "render agents for demo: AGENTS.md differs (brain sync, or brain render --target agents --project demo "
        "--write)"]
    assert render.keep_current(ada, "demo", fix=True) == ["render agents: AGENTS.md written"]
    assert "## Changed\n\nNew.\n" in (ada / "AGENTS.md").read_text(encoding="utf-8")
    assert render.keep_current(ada, "demo", fix=False) == []


def test_a_target_that_adds_to_the_base_is_followed_on_its_own(ada):
    render.main(ada, "agents", project="demo", project_root=ada, do_write=True)
    assert [t for t, *_ in render.rendered(ada, "demo", ada)] == ["agents"]   # cursor not rendered: not followed
    render.main(ada, "cursor", project="demo", project_root=ada, do_write=True)
    assert [t for t, *_ in render.rendered(ada, "demo", ada)] == ["agents", "cursor"]


def test_sync_rewrites_a_rendered_agents_md_and_check_warns(ada, monkeypatch, capsys):
    render.main(ada, "agents", project="demo", project_root=ada, do_write=True)
    write(ada, {"CLAUDE.md": "# demo\n\n## Changed\n\nNew.\n"})
    monkeypatch.setattr(cli.graph, "research_graph", lambda *a, **k: 0)
    store = ada / "notes" / "graph"
    args = cli.build_parser().parse_args(["--root", str(ada), "check"])
    cli._check_store(args, ada, store)
    assert "warning: render agents for demo: AGENTS.md differs" in capsys.readouterr().out
    monkeypatch.setattr(cli, "_records_view", lambda *a: False)
    monkeypatch.setattr(cli.links, "applies", lambda store: False)
    monkeypatch.setattr(cli.features, "has_type", lambda schema: False)
    args = cli.build_parser().parse_args(["--root", str(ada), "sync", "--offline"])
    cli._sync_store(args, ada, store)
    assert "render agents: AGENTS.md written" in capsys.readouterr().out
    assert render.keep_current(ada, "demo", fix=False) == []


def test_the_registry_reports_a_locked_rule_overridden(ada):
    projs = list(__import__("brain.projects", fromlist=["load"]).load(ada).values())
    assert render.registry_warnings(ada, projs) == []
    write(ada / "source", {"rules/global.md": RULES.replace("scope: global\n", "scope: global\nlock: [rule-git]\n")})
    write(ada, {"CLAUDE.md": "# demo\n\n## Rebase\n<!-- overrides: rule-git -->\n\nText.\n"})
    assert render.registry_warnings(ada, projs) == [
        f"rules: {ada / 'CLAUDE.md'}:3: 'Rebase' overrides rule-git, locked by rules/global.md"]


def test_brain_render_cli(ada, monkeypatch, capsys):
    monkeypatch.chdir(ada)
    assert cli.main(["--root", str(ada), "render", "--target", "claude", "--write"]) == 0
    assert cli.main(["--root", str(ada), "render", "--check"]) == 0
    capsys.readouterr()
    assert cli.main(["--root", str(ada), "--project", "demo", "render", "--target", "agents", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["target"] == "agents" and data["project"] == "demo"
    assert {f["rel"]: f["state"] for f in data["files"]}["AGENTS.md"] == "new"


def test_an_unknown_target_or_a_broken_source_renders_nothing(ada, capsys):
    with pytest.raises(render.RenderError, match="unknown target"):
        render.render(ada, "vim")
    write(ada / "source", {"mcp.yaml": "servers: [\n"})
    assert render.main(ada, "claude") == 1
    assert "not readable YAML" in capsys.readouterr().out
