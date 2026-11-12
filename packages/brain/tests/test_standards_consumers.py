"""The standards registry's consumers (wi-brain-standards-registry-consumers): the review's standards lens (brain review
prep, brain standards lenses), the audit's standards.gap, the rules text (brain standards rules) and the CI template
(brain standards ci), each read from a project's applicable rows; a project without standards: gets none of them."""

import json
from pathlib import Path

import pytest
import test_standards as ts
import yaml
from test_standards import _catalog, _row

from brain import audit, cli, projects, review, standards

engine, registry = ts.engine, ts.registry   # the fixtures: the engine's catalogs, demo's registry


@pytest.fixture
def consumers(engine, registry):
    """A local catalog with one row of each consumer's level, and demo opted in with a Python and a TypeScript repo."""
    reg_dir = projects.registry_file().parent
    _catalog(reg_dir / "standards", "team", [
        _row("tm-lint", domain="code-quality", profiles=["cli"], stage="prototype", adapter="lint", languages=["py"]),
        _row("tm-cov", domain="testing", profiles=["cli"], stage="prototype", enforcement="measure",
             adapter="coverage", languages=["py", "ts"]),
        _row("tm-boundaries", domain="architecture", profiles=["cli"], stage="prototype", enforcement="review-lens",
             languages=["any"], status="validated"),
        _row("tm-naming", domain="architecture", profiles=["cli"], stage="prototype", enforcement="rule",
             languages=["any"]),
        _row("tm-later", domain="architecture", profiles=["cli"], stage="scale", enforcement="rule",
             languages=["any"]),
    ])

    def opt_in(tools: str = ""):
        registry("  standards: {profiles: [cli], stage: mvp, catalogs: [standards/team.yaml], "
                 "exclude: {sw-atomic-writes: \"a test catalog row, not ours\"}}\n"
                 "  repos: [{path: ., lang: py" + tools + "}, {path: web, lang: ts}]\n")
        return projects.get("demo")
    return opt_in


def test_lenses_rules_and_ci_read_the_applicable_rows_by_level(consumers, capsys):
    p = consumers()
    assert standards.lenses(p) == ["`sw-utc` (time): sw-utc holds.",
                                   "`tm-boundaries` (architecture): tm-boundaries holds."]
    text = standards.rules_text(p)
    assert "## Standards that need judgement (demo)" in text and "### architecture" in text
    assert "`tm-naming` (architecture, proposed): tm-naming holds." in text and "tm-later" not in text   # its stage
    plan = standards.ci_plan(p, {"demo": "py", "web": "ts"}, {})
    assert plan == {"lint": {"rows": ["tm-lint"], "repos": {"demo": ""}},
                    "coverage": {"rows": ["tm-cov"], "repos": {"demo": "", "web": ""}}}
    yml = yaml.safe_load(standards.ci_yaml(p, plan, {"demo": "py", "web": "ts"}, {"demo": ".", "web": "web"}))
    steps = yml["jobs"]["standards"]["steps"]
    assert [s.get("name") for s in steps] == [None, "lint (demo)", "coverage (demo)", "coverage (web)", "Reports"]
    assert all(s["run"].endswith("&& false") for s in steps[1:4])   # fails until filled
    assert "working-directory" not in steps[1] and steps[3]["working-directory"] == "web"
    assert steps[1]["env"] == {"STANDARDS": "tm-lint", "USUAL_TOOL": "ruff check --output-format sarif -o ruff.sarif"}


def test_the_ci_yaml_quotes_whatever_a_name_or_a_path_holds(consumers):
    import shlex
    p = consumers()
    odd = {"my: repo #1": "py"}
    plan = {"lint": {"rows": ["tm-lint"], "repos": {"my: repo #1": "reports\\o'brien \"x\".sarif"}}}
    text = standards.ci_yaml(p, plan, odd, {"my: repo #1": "sub dir/x"})
    steps = yaml.safe_load(text)["jobs"]["standards"]["steps"]
    assert steps[1]["name"] == "lint (my: repo #1)" and steps[1]["working-directory"] == "sub dir/x"
    words = shlex.split(steps[1]["run"])
    assert words[:2] == ["echo", "fill in the lint tool of my: repo #1, writing reports\\o'brien \"x\".sarif"]
    assert "sub dir/x/reports\\o'brien \"x\".sarif" in steps[2]["with"]["path"]


def test_rules_text_gives_each_domain_one_heading(consumers, engine):
    _catalog(engine, "zz", [_row("zz-arch", domain="architecture", profiles=["cli"], stage="prototype",
                                 enforcement="rule", languages=["any"]),
                            _row("zz-test", domain="testing", profiles=["cli"], stage="prototype",
                                 enforcement="rule", languages=["any"])])
    text = standards.rules_text(consumers())
    assert text.count("### architecture") == 1 and text.index("### architecture") < text.index("### testing")


def test_catalogs_that_cannot_be_read_whole_feed_no_consumer(consumers, registry, capsys, pr_repo, monkeypatch):
    registry("  standards: {profiles: [cli], stage: mvp, catalogs: [standards/missing.yaml]}\n"
             "  repos: [{path: ., lang: ts}]\n")
    p = projects.get("demo")
    with pytest.raises(standards.StandardsError, match="cannot be read whole"):
        standards.lenses(p)
    for sub in ("lenses", "rules", "ci"):
        assert cli.main(["--project", "demo", "standards", sub]) == 2, sub
        assert "cannot be read whole" in capsys.readouterr().err
    web = projects.repos_of(p)[0]
    assert audit.standards_gap({"cfg": web, "project": p}).startswith("its standards cannot be measured")
    monkeypatch.setattr(standards, "project_of_repo", lambda repo: p)
    monkeypatch.chdir(pr_repo)
    assert cli.main(["review", "prep", "HEAD~1..HEAD", "--no-scout"]) == 0   # the packet, without the lens
    assert "no standards lens" in capsys.readouterr().err


def test_a_declared_tool_names_its_report_and_covers_another_language(consumers):
    p = consumers(", tools: {lint: {report: reports/ruff.sarif, format: sarif}}")
    plan = standards.ci_plan(p, {"demo": "py", "web": "ts"},
                             {"demo": {"lint": {"report": "reports/ruff.sarif"}}, "web": {"lint": {"report": "x"}}})
    assert plan["lint"]["repos"] == {"demo": "reports/ruff.sarif", "web": "x"}   # web's own lint tool: covered


def test_cli_lenses_rules_ci(consumers, capsys, tmp_path):
    consumers()
    assert cli.main(["--project", "demo", "standards", "lenses"]) == 0
    assert "- `tm-boundaries` (architecture)" in capsys.readouterr().out
    out = tmp_path / "rules.md"
    assert cli.main(["--project", "demo", "standards", "rules", "--write", str(out)]) == 0
    assert "tm-naming" in out.read_text(encoding="utf-8") and str(out) in capsys.readouterr().out
    assert cli.main(["--project", "demo", "standards", "ci", "--json"]) == 0
    assert set(json.loads(capsys.readouterr().out)["plan"]) == {"lint", "coverage"}
    assert cli.main(["--project", "demo", "standards", "ci"]) == 0
    assert "name: standards" in capsys.readouterr().out


def test_a_project_without_standards_gets_no_consumer(engine, registry, capsys):
    p = projects.get("demo")
    assert standards.lenses(p) == [] and standards.rules_text(p) == ""
    assert standards.ci_plan(p, {"demo": "py"}, {}) == {}
    for sub in ("lenses", "rules", "ci"):
        assert cli.main(["--project", "demo", "standards", sub]) == 0
        assert capsys.readouterr().out.startswith("no ")


def test_the_audit_names_a_gap_only_where_standards_are_declared(consumers):
    p = consumers()
    web = next(r for r in projects.repos_of(p) if r.lang == "ts")
    got = audit.standards_gap({"cfg": web, "project": p})
    assert [f["unit"] for f in got] == ["tm-lint"] and got[0]["check"] == "standards.gap"
    assert got[0]["severity"] == "P2" and "covers py, not web (ts)" in got[0]["why"]
    assert isinstance(audit.standards_gap({"cfg": web, "project": projects.get("demo")}), list)
    assert audit.CHECKS["standards.gap"].scout == "never" and audit.RULESET >= 10
    assert audit.PENDING["standards.gap"].applies == "standards"


def test_review_prep_adds_the_standards_lens(pr_repo, brain_home):
    p = review.prep(pr_repo, "HEAD~1..HEAD", scout=False, standards=["`tm-boundaries` (architecture): it holds."])
    assert p.lenses[-1] == "standards" and p.standards
    text = (brain_home / "reviews" / p.head[:12] / "README.md").read_text(encoding="utf-8")
    assert "- **standards**: does the change keep each of the project's review-lens standards (1" in text
    assert "  - `tm-boundaries` (architecture): it holds." in text
    plain = review.prep(pr_repo, "HEAD~1..HEAD", scout=False)
    assert "standards" not in plain.lenses


def test_the_project_of_a_repo(consumers, registry, tmp_path, monkeypatch):
    p = consumers()
    assert standards.project_of_repo(p.root).name == "demo"
    web = Path(p.root) / "web"
    web.mkdir(exist_ok=True)
    assert standards.project_of_repo(web).name == "demo"           # a repo demo's repos: lists
    (tmp_path / "elsewhere").mkdir()
    assert standards.project_of_repo(tmp_path / "elsewhere") is None
    bad = tmp_path / "bad.yaml"
    bad.write_text("demo: {root: ., repos: [\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(bad))
    assert standards.project_of_repo(tmp_path / "elsewhere") is None   # a broken registry: no lens, no crash


@pytest.fixture
def pr_repo(make_repo):
    repo = make_repo("app", {"src/a.py": "x = 1\n"})
    make_repo.commit(repo, {"src/a.py": "x = 2\n"})
    return repo
