"""The new-project wizard, third slice (brain.project_parts, wi-brain-project-wizard-pack; spec-brain-client-standards
§8): the typology packs a new project's kinds meet and their parts by plan, then --apply runs each part as a brain
command, logged; a step that fails does not stop the next; a brain that exists already gets the plan only. Fictitious
names only."""

import json

import pytest
import yaml
from brain import (
    __version__,
    cli,
    firstrun,
    init,
    neutral,
    paths,
    project_parts,
    render,
    skew,
    typologies,
    typology_packs,
)


@pytest.fixture(autouse=True)
def fresh(monkeypatch, brain_home):
    """As brain init's tests: the tests' own config and registry overrides off, a dev engine standing for its
    release (the steps' brain render would refuse another engine than the new brain's pin)."""
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)
    monkeypatch.delenv("BRAIN_PROJECTS", raising=False)
    monkeypatch.setattr(init, "machine_terms", lambda: {"users": ["ada-l"], "hosts": ["host-a"]})
    monkeypatch.setattr(skew, "running", lambda: [skew.Engine(d, __version__, f"v{__version__}", "0" * 40)
                                                  for d, _ in skew.DISTS])


@pytest.fixture
def cat():
    return typologies.engine()


def words(d, *extra):
    return ["project", "new", str(d), "--kind", "cli", "--kind", "research", "--stage", "mvp", "--name", "lab",
            "--owner", "Ada", *extra]


def ledger() -> list[dict]:
    rows = []
    for f in sorted(paths.ledger_dir().glob(f"{firstrun.LOG}-*.jsonl")):
        rows += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if r.get("via") == project_parts.VIA]


def files_of(d) -> dict:
    return {p.relative_to(d).as_posix(): p.read_bytes() for p in d.rglob("*") if p.is_file()}


def test_the_plan_names_each_pack_its_parts_and_the_steps_and_writes_nothing(tmp_path, capsys):
    d = tmp_path / "lab"
    assert cli.main(words(d)) == 0
    out = capsys.readouterr().out
    assert "pack software (the engine's, for software): packs.yaml takes it (from: engine, projects: [lab])" in out
    assert "pack research (the engine's, for research): packs.yaml takes it" in out
    assert "5 clause(s) of done, 3 one-way door(s), 2 role(s), gates at build, launch" in out
    assert "guards it turns on: branches" in out and "brain permissions --project lab" in out
    assert "CI templates: .github/workflows/ci.yml" in out and "CLAUDE.md: the template's, with « What it" in out
    assert "standards profiles it does not meet" not in out   # cli meets software's profile
    steps = [ln.strip() for ln in out.splitlines() if ln.strip()[:3] in ("1. ", "2. ", "3. ")]
    assert [s.split("   (")[0] for s in steps] == [
        f"1. brain --root {d} typologies propose lab --apply",
        f"2. brain --root {d} render --target claude --write",
        f"3. brain --root {d} --project lab render --target agents --write"]
    assert not d.exists() and ledger() == []


def test_each_step_is_a_command_the_real_parser_takes(tmp_path, cat):
    p = project_parts.plan_new(cat, ["cli"], ["cli"], {"CLAUDE.md": ""}, tmp_path / "a b", "lab")
    for s in p.steps:
        assert s.words[0] == "brain"
        cli.build_parser().parse_args(s.words[1:])   # SystemExit on a word it does not take
    assert '"' in firstrun.shown(p.steps[0].words)   # a folder with a space is quoted as the owner types it


def test_apply_writes_the_packs_claude_md_agents_md_and_the_marketplace_each_step_logged(tmp_path, capsys,
                                                                                         monkeypatch):
    d = tmp_path / "lab"
    assert cli.main(words(d, "--apply")) == 0
    out = capsys.readouterr().out
    assert f"$ brain --root {d} typologies propose lab --apply" in out and "step(s) failed" not in out
    packs = yaml.safe_load((d / "source" / "packs.yaml").read_text(encoding="utf-8"))["packs"]
    assert packs["software"] == {"from": "engine", "projects": ["lab"]} and packs["research"]["from"] == "engine"
    claude = (d / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.startswith("# Ada's brain") and "\n## What it produces\n" in claude
    assert "cli (Command-line tool), research (Research), at mvp (the lifecycle's build)" in claude
    assert "### Software (pack software)" in claude and "- a public API or command line" in claude
    assert "- reviewer: reads a result against its pre-registration" in claude
    assert "- build: each test pre-registered" in claude
    agents = (d / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.rstrip().endswith("- build: each test pre-registered (hypothesis, test, threshold) before its "
                                    "results are seen")   # the project's CLAUDE.md, last
    assert (d / "plugins" / "software" / ".claude-plugin" / "plugin.json").is_file()
    rows = ledger()
    assert [r["exit"] for r in rows] == [0, 0, 0, 0] and rows[0]["command"].endswith("--apply")
    assert rows[0]["command"].startswith("brain project new ") and "typologies propose lab" in rows[1]["command"]
    assert all(r["by"] == "Ada" for r in rows)
    monkeypatch.setenv("BRAIN_PROJECTS", str(d / "projects.yaml"))
    assert neutral.check(neutral.load(d)) == []
    for target, project, root in (("claude", None, None), ("agents", "lab", d)):
        r = render.render(d, target, project, root)
        assert render.stale(render.plan(r, render.bases_for(d, root, None))) == []


def test_a_step_that_fails_does_not_stop_the_next_and_is_named(tmp_path, capsys, monkeypatch):
    def refuse(*a, **k):
        raise ValueError("packs.yaml as it would be: a refusal")
    monkeypatch.setattr(typology_packs, "apply", refuse)
    d = tmp_path / "lab"
    assert cli.main(words(d, "--apply")) == 1
    out = capsys.readouterr().out
    assert f"1 step(s) failed (the brain is written; each re-runs alone): brain --root {d} typologies propose" in out
    assert [r["exit"] for r in ledger()] == [0, 1, 0, 0]   # the renders ran after it
    assert (d / "AGENTS.md").is_file() and "software" not in (d / "source" / "packs.yaml").read_text(encoding="utf-8")


def test_a_step_with_nothing_to_write_is_skipped_and_says_why(tmp_path, capsys):
    s = project_parts.steps(tmp_path, "lab", [], packs_pending=False, claude_stale=False, agents_stale=True)
    assert [x.skip for x in s] == ["no typology pack meets its kinds", "the marketplace is current", ""]
    assert project_parts.run(project_parts.Parts(steps=s[:2]), tmp_path, "Ada") == 0
    out = capsys.readouterr().out
    assert "skipped: brain --root" in out and "(no typology pack meets its kinds)" in out and ledger() == []


def test_an_existing_brain_gets_the_plan_only(tmp_path, capsys):
    d = tmp_path / "lab"
    assert cli.main(words(d, "--apply")) == 0
    capsys.readouterr()
    assert cli.main(words(d, "--apply")) == 0   # every part current: nothing to do, nothing refused
    out = capsys.readouterr().out
    assert "pack software (packs.yaml's, for software): taken" in out and "the answers change nothing there" in out
    assert "its parts' steps" not in out and "in CLAUDE.md « What it produces »" not in out
    claude = d / "CLAUDE.md"
    claude.write_text(claude.read_text(encoding="utf-8") + "\n## Our own\n\nA rule of the project.\n",
                      encoding="utf-8")
    before, n = files_of(d), len(ledger())
    assert cli.main(words(d)) == 0
    out = capsys.readouterr().out
    assert "its parts' steps, by a branch and a PR of that brain (never here):" in out
    assert f"1. brain --root {d} --project lab render --target agents --write" in out
    assert f"skipped: brain --root {d} typologies propose lab --apply (its packs are taken already)" in out
    assert cli.main(words(d, "--apply")) == 2   # pending parts: refused, never run here
    assert files_of(d) == before and len(ledger()) == n


def test_an_existing_brain_without_the_pack_is_shown_the_step_that_takes_it(tmp_path, capsys):
    d = tmp_path / "lab"
    assert cli.main(["project", "new", str(d), "--kind", "cli", "--name", "lab", "--owner", "Ada", "--apply"]) == 0
    capsys.readouterr()
    assert cli.main(words(d)) == 0
    out = capsys.readouterr().out
    assert "pack research (the engine's, for research): packs.yaml takes it" in out
    assert f"1. brain --root {d} typologies propose lab --apply" in out


def test_md_keeps_a_pack_text_on_one_line_and_hides_nothing():
    assert project_parts.md("a\nb  c") == "a b c"
    assert project_parts.md('say "x" & 100% of $HOME <!-- y --> &amp;') == \
        'say "x" &amp; 100% of $HOME &lt;!-- y --> &amp;amp;'


def test_the_section_writes_a_brains_own_pack_text_escaped(cat):
    pr = typology_packs.Proposal("ours", "packs.yaml", ["cli"], False, "add", spec={
        "title": "Ours\n# not a heading", "done": [{"id": "x", "text": "first line\n- not an item <b>"}],
        "roles": [{"id": "lead", "text": "decides"}], "stages": {"build": ["one", "two"]}})
    text = project_parts.claude_section(cat, ["cli"], "mvp", "build", [pr])
    assert "### Ours # not a heading (pack ours)" in text
    assert "- first line - not an item &lt;b>" in text and "- lead: decides" in text and "- build: one; two" in text
    assert "One-way doors" not in text   # a part the pack does not give: no heading of it


def test_a_template_without_claude_md_writes_no_section(tmp_path, cat, capsys):
    p = project_parts.plan_new(cat, ["research"], ["research"], {"projects.yaml": ""}, tmp_path, "lab")
    lines = project_parts.plan_lines(p, "lab", True)
    assert not p.claude and "    CLAUDE.md: none (the template writes none; brain typologies packs shows the packs' " \
        "judgement)" in lines
    assert "CI templates: none" in "\n".join(lines) and "in CLAUDE.md" not in "\n".join(lines)


def test_brain_init_edits_only_the_files_its_template_writes():
    tpl = init.load_template("generic")
    out = init.files_for("Ada", "person", None, "lite", "brain", tpl,
                         edits={"CLAUDE.md": lambda t: t + "X\n", "NOPE.md": lambda t: "never"})
    assert out["CLAUDE.md"].endswith("X\n") and "NOPE.md" not in out


def test_a_sub_profile_meets_its_entrys_standards_profile(cat):
    soft = [c for c in typology_packs.engine_candidates() if c[0] == "software"]
    assert typology_packs.proposals(soft, ["cli"], cat, None, ["cli"])[0].standards == []
    assert typology_packs.proposals(soft, ["cli"], cat, None, ["research"])[0].standards == ["software"]
    assert typology_packs.proposals(soft, ["cli"], cat, None, None)[0].standards == ["software"]
