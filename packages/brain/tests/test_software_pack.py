"""The software pack extracted from the core (wi-brain-software-pack, spec-brain-typology-packs TYPO-1, door 3): the
registry's software keys grouped under ``software:`` with the top level kept as an alias, and the code duties (brain
audit's default repo, the scout) applied by kind: no typology declared, one unknown, or one meeting the software pack.
Fictitious names only."""

import pytest
from brain import audit, cli, projects, schema, scout, typology_packs


@pytest.fixture
def registry(tmp_path, monkeypatch):
    """write(text): a registry at tmp_path with that text; the projects' roots are made under tmp_path."""
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)
    f = tmp_path / "projects.yaml"
    monkeypatch.setenv("BRAIN_PROJECTS", str(f))

    def write(text: str) -> dict:
        f.write_text(text, encoding="utf-8")
        for name in ("shop", "plan", "svc"):
            (tmp_path / name).mkdir(exist_ok=True)
        return projects.load(tmp_path)
    write.root = tmp_path
    return write


def test_the_engines_software_pack_reads_the_registry_keys_grouped_under_software():
    assert typology_packs.engine()["software"]["registry"] == list(projects.SOFTWARE_KEYS)
    assert "software" in projects.KEYS


def test_software_keys_are_read_under_software_and_at_the_top_level_alike(registry):
    regs = registry("shop:\n  root: shop\n  software:\n    repos: [., {path: ../svc, name: svc}]\n"
                    "    production: [../svc]\n    code_index: [.]\n    audit: {max_lines: 900}\n"
                    "plan:\n  root: plan\n  repos: [.]\n  audit: {max_lines: 700}\n")
    shop, plan = regs["shop"], regs["plan"]
    assert shop.repos == [".", {"path": "../svc", "name": "svc"}] and shop.audit == {"max_lines": 900}
    assert shop.code_index == ["."] and [p.name for p in shop.production] == ["svc"]
    assert plan.repos == ["."] and plan.audit == {"max_lines": 700}           # the alias, as before
    assert [r.name for r in projects.repos_of(shop)] == ["shop", "svc"]
    assert projects.check(registry.root) == []


def test_a_software_key_given_twice_or_unknown_under_software(registry, monkeypatch):
    registry("shop:\n  root: shop\n  repos: [.]\n  software:\n    repos: [.]\n    lint: x\n")
    monkeypatch.setattr(schema, "mode", lambda: schema.STRICT)
    errors = projects.check(registry.root)
    assert any("repos is given twice, at the top level and under software" in e for e in errors)
    assert any("software: unknown key(s) lint" in e for e in errors)
    registry("shop:\n  root: shop\n  software: [repos]\n")
    assert any("software is a mapping of repos, audit, code_index, production" in e
               for e in projects.check(registry.root))


def test_a_read_only_typo_keeps_a_production_checkout_grouped_under_software_guarded(registry):
    registry("shop:\n  root: shop\n  access: reed\n  software:\n    production: [.]\n")
    guarded = {p.name: p for p in projects.guarded(registry.root)}
    assert "shop" in guarded and [p.name for p in guarded["shop"].production] == ["shop"]


@pytest.mark.parametrize("kinds, applies", [
    ("", True),                       # none declared: the rule before the catalog
    ("[cli]", True),                  # a sub-profile of software
    ("[strategy]", False),
    ("[strategy, service]", True),
    ("[softwre]", True),              # unknown: a misspelling never drops a duty
    ("[research]", False),
])
def test_the_code_duties_apply_by_kind(registry, kinds, applies):
    lc = f"  lifecycle: {{typologies: {kinds}}}\n" if kinds else ""
    p = registry(f"plan:\n  root: plan\n{lc}")["plan"]
    assert projects.software(p) is applies
    assert [r.name for r in projects.repos_of(p)] == ["plan"]                 # the repo itself, for every other use
    assert [r.name for r in projects.repos_of(p, audit=True)] == (["plan"] if applies else [])


def test_a_project_of_another_kind_that_declares_repos_is_audited(registry):
    p = registry("plan:\n  root: plan\n  lifecycle: {typologies: [strategy]}\n  software: {repos: [.]}\n")["plan"]
    assert [r.name for r in projects.repos_of(p, audit=True)] == ["plan"]


def test_brain_audit_of_a_strategy_project_measures_no_code_repo(registry, monkeypatch):
    registry("plan:\n  root: plan\n  lifecycle: {typologies: [strategy]}\n")
    seen = []
    monkeypatch.setattr(audit, "trees_now", lambda cfgs: (seen.append(list(cfgs)), ({}, {}, {}))[1])
    monkeypatch.setattr(audit, "measure", lambda p, cfgs, trees, only: {"name": p.name, "repos": [], "layered": None,
                                                                        "linked": None, "featured": None,
                                                                        "coverage": None})
    args = type("A", (), {"all": False, "project": "plan", "scope": None, "repo": None, "write": False,
                          "items": False, "trend": 0})()
    data = audit.run(args, registry.root)
    assert seen == [[]] and [r["name"] for r in data["projects"]] == ["plan"]
    assert "meet no software pack" in data["projects"][0]["not_software"]


def test_the_scout_says_it_is_the_software_packs_and_passes(registry, monkeypatch, capsys):
    p = registry("plan:\n  root: plan\n  lifecycle: {typologies: [strategy]}\n")["plan"]
    monkeypatch.setattr(scout, "resolve", lambda args, root: (p, [], projects.Repo("plan", p.root), p.root, True))
    assert scout.main(type("A", (), {"diff": ""})(), registry.root) == 0
    assert "meet no software pack: the scout is the software pack's" in capsys.readouterr().out


def test_brain_projects_keys_lists_software(registry, capsys):
    registry("shop:\n  root: shop\n")
    assert cli.main(["--root", str(registry.root), "projects", "--keys"]) == 0
    assert "software" in capsys.readouterr().out
