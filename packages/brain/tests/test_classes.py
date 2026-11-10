import json

import pytest

from brain import classes, config

from conftest import run_git

MACHINE = {name: {"class": cls, "paths": [path]} for name, (path, cls) in classes.KNOWN.items()}


@pytest.fixture
def brain(make_repo, tmp_path, monkeypatch):
    """A personal brain repo with a private remote: memory/, records/ddr, notes/, a sealed file; its config.json is
    the test's ``stores`` (machine stores added unless told not to)."""
    root = make_repo("brain", {"memory/a.md": "a\n", "records/ddr/d.yaml": "id: d\n", "records/sr/s.yaml": "id: s\n",
                               "notes/journal.md": "# J\n", "README.md": "# R\n", "vault/x.tar.gz.age": "sealed\n"})
    run_git(root, "remote", "add", "origin", "git@github.com:someone/brain-private.git")
    monkeypatch.setenv("BRAIN_CONFIG", str(root / config.FILE))
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "no-projects.yaml"))
    monkeypatch.delenv("BRAIN_SCOPES", raising=False)

    def write(stores: dict | None, machine: bool = True, **extra) -> config.Config:
        data = {"v": 1, "identity": {"owner": "Ada"}, **extra}
        if stores is not None:
            data["classes"] = {"stores": {**stores, **(MACHINE if machine else {})}}
        (root / config.FILE).write_text(json.dumps(data), encoding="utf-8")
        return config.load(root)

    write.root = root
    return write


def test_the_matrix_covers_every_class_and_exit():
    for cls, row in classes.POLICY.items():
        assert set(row) == set(classes.EXITS) and set(row.values()) <= set(classes.HOW), cls
    assert classes.how("secret", "local-model") == "never" and classes.how("public", "git-public") == "clear"
    assert classes.how("sealed", "offsite") == "sealed" and classes.how("resident", "offsite") == "never"
    assert classes.how("confidential", "git-private") == "sealed" and classes.how("tenant:team-z", "offsite") == "sealed"
    assert classes.class_ok("tenant:team-z") and not classes.class_ok("tenant:") and not classes.class_ok("top")
    assert len(classes.matrix()) == len(classes.POLICY) + 1


def test_a_brain_without_classes_is_refused(brain):
    cfg = brain(None)
    rep = classes.check(cfg=cfg)
    assert rep.errors == [f"{config.FILE} declares no data classes (classes.stores): every store needs one "
                          "(brain classes --suggest prints a starting set)"]


def test_every_store_has_a_class(brain):
    """A tracked file without a class fails; an engine store the brain does not declare takes its suggested class
    and is noted, never failed (COMPAT-6)."""
    rep = classes.check(cfg=brain({"notes": {"class": "private", "paths": ["notes/**"]}}, machine=False))
    assert any(e.startswith("5 tracked file(s) have no class") for e in rep.errors)
    assert not any("engine" in e or "BRAIN_HOME" in e for e in rep.errors)
    assert [s.name for s in rep.defaulted] == list(classes.ENGINE_STORES)
    assert {s.name: s.cls for s in rep.defaulted}["ledger"] == "sealed"
    assert rep.home_notes[0].startswith(f"{len(classes.ENGINE_STORES)} engine store(s) undeclared take their "
                                        "suggested class by default: ledger (sealed), sessions (sealed)")
    assert "transcripts (sealed)" in rep.home_notes[0] and "secrets (secret)" in rep.home_notes[0]


def test_destinations_the_class_forbids_are_refused(brain):
    """The refusal: confidential files in clear in a private remote, a resident store sent offsite, a sealed store
    declared for a notes service."""
    cfg = brain({"memory": {"class": "confidential", "paths": ["memory/**"]},
                 "ddr": {"class": "confidential", "paths": ["records/ddr/**"],
                         "waive": {"git-private": "in clear until the encrypted-git trial decides"}},
                 "sealed-files": {"class": "sealed", "paths": ["vault/**"]},
                 "rows": {"class": "resident", "paths": ["$BRAIN_HOME/rows"], "to": ["offsite"]},
                 "index": {"class": "sealed", "paths": ["$BRAIN_HOME/index"], "to": ["third-party", "offsite"]},
                 "repo": {"class": "private", "paths": ["**"]}})
    rep = classes.check(cfg=cfg)
    assert rep.remote == "git-private"
    assert ("store memory (confidential): 1 tracked file(s) go to git-private in clear, which its class allows "
            "sealed only (untrack them, seal them, or waive it with its reason)") in rep.errors
    assert "store rows (resident) declares offsite, which its class forbids" in rep.errors
    assert "store index (sealed) declares third-party, which its class forbids" in rep.errors
    assert not any("index (sealed) declares offsite" in e for e in rep.errors)  # sealed: allowed through the vault
    assert not any("store sealed-files" in e for e in rep.errors)  # already sealed files are not in clear
    assert rep.waived == ["store ddr (confidential): 1 tracked file(s) go to git-private in clear, which its class "
                          "allows sealed only; reason: in clear until the encrypted-git trial decides"]
    assert classes.main(None, check_only=True) == 1


def test_a_public_remote_takes_public_classes_only(brain):
    root = brain.root
    run_git(root, "remote", "set-url", "origin", "https://github.com/someone/brain.git")
    rep = classes.check(cfg=brain({"repo": {"class": "public", "paths": ["memory/**", "records/**", "notes/**",
                                                                         "README.md"]},
                                   "sealed-files": {"class": "sealed", "paths": ["vault/**"]}},
                                  public={"repos": ["someone/brain"]}))
    assert rep.remote == "git-public" and rep.errors == []
    rep = classes.check(cfg=brain({"all": {"class": "private", "paths": ["**"]}}, public={"repos": ["someone/brain"]}))
    assert any("go to git-public in clear, which its class forbids" in e for e in rep.errors)


def test_waiver_needs_a_reason_and_shapes_are_checked(brain):
    rep = classes.check(cfg=brain({"m": {"class": "confidential", "paths": ["memory/**"], "waive": {"git-private": "x"}},
                                   "bad": {"class": "top", "paths": ["a/**"]},
                                   "odd": {"class": "private", "paths": ["**"], "to": ["moon"], "colour": 1}}))
    errs = "\n".join(rep.errors)
    assert "classes.stores.m: waive.git-private needs its reason (15 characters or more)" in errs
    assert "classes.stores.bad: class 'top' is not one of" in errs
    assert "classes.stores.odd: unknown key(s) colour" in errs and "classes.stores.odd: to names exits" in errs


def test_store_of_and_decide(brain, brain_home):
    cfg = brain({"memory": {"class": "confidential", "paths": ["memory/**"], "to": ["cloud-model"]},
                 "notes": {"class": "private", "paths": ["notes/**"], "to": ["third-party"]},
                 "repo": {"class": "private", "paths": ["**"]}})
    declared, _ = classes.stores(cfg)
    assert classes.store_of(declared, "memory/a.md").name == "memory"
    assert classes.store_of(declared, "README.md").name == "repo"
    assert classes.store_of(declared, "$BRAIN_HOME/ledger/x.jsonl").name == "ledger"
    assert classes.store_of(declared, "~/.claude/projects/p/s.jsonl").name == "transcripts"
    assert classes.decide(cfg, "memory", "cloud-model") == "clear"     # opted in
    assert classes.decide(cfg, "repo", "third-party") == "never"       # not opted in
    assert classes.decide(cfg, "notes", "third-party") == "clear"
    assert classes.decide(cfg, "ledger", "offsite") == "sealed"
    assert classes.decide(cfg, "ledger", "git-private") == "never"
    assert classes.decide(cfg, "nope", "offsite") == "never"
    # an engine store the brain leaves undeclared is decided at its suggested class (COMPAT-6)
    cfg = brain({"repo": {"class": "private", "paths": ["**"]}}, machine=False)
    assert classes.decide(cfg, "usage", "offsite") == "sealed"
    assert classes.decide(cfg, "usage", "git-private") == "never"
    assert classes.decide(cfg, "secrets", "offsite") == "never"
    assert classes.decide(cfg, "secrets", "local-model") == "never"


def test_a_store_under_its_scope_floor_is_refused(brain, monkeypatch, tmp_path):
    root = brain.root
    (tmp_path / "projects.yaml").write_text(f"brain:\n  root: {root.as_posix()}\n  parent: finance\n",
                                            encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "projects.yaml"))
    stores = {"memory": {"class": "confidential", "paths": ["memory/**"],
                         "waive": {"git-private": "in clear until the encrypted-git trial decides"}},
              "repo": {"class": "private", "paths": ["**"], "waive": {}}}
    cfg = brain(stores)
    assert any("no scope tree" in n for n in classes.check(cfg=cfg).notes)
    (root / "scopes.yaml").write_text("v: 1\nscopes:\n  pro: {type: sphere}\n"
                                      "  acme: {type: company, parent: pro, classes: {floor: confidential}}\n"
                                      "  finance: {type: unit, parent: acme}\n", encoding="utf-8")
    cfg = config.load(root)
    assert classes.scope_chain(cfg, "brain") == ["finance", "acme", "pro"]
    assert classes.floor(cfg, "brain") == ("confidential", "acme")
    errs = classes.check(cfg=cfg).errors
    assert "store repo (private) is under the floor confidential that scope acme sets for project brain" in errs
    assert not any("store memory" in e and "floor" in e for e in errs)


def test_suggest_is_a_valid_block(brain):
    cfg = brain(None)
    block = classes.suggest(cfg)
    assert list(block["stores"])[-1] == "repo" and block["stores"]["memory"]["class"] == "confidential"
    data = json.loads((brain.root / config.FILE).read_text())
    data["classes"] = block
    (brain.root / config.FILE).write_text(json.dumps(data), encoding="utf-8")
    rep = classes.check(cfg=config.load(brain.root))
    assert not any("has no class" in e for e in rep.errors)
    assert rep.errors == ["store memory (confidential): 1 tracked file(s) go to git-private in clear, which its class "
                          "allows sealed only (untrack them, seal them, or waive it with its reason)",
                          "store records-ddr (confidential): 1 tracked file(s) go to git-private in clear, which its "
                          "class allows sealed only (untrack them, seal them, or waive it with its reason)"]


def test_an_empty_gitkeep_holds_no_data(brain):
    """A confidential folder kept in git by an empty .gitkeep (what brain init writes) sends nothing in clear; a
    .gitkeep with content does."""
    root = brain.root
    (root / "people").mkdir()
    (root / "people" / ".gitkeep").write_text("", encoding="utf-8")
    run_git(root, "add", "people/.gitkeep")
    run_git(root, "commit", "-q", "-m", "keep")
    stores = {"people": {"class": "confidential", "paths": ["people/**"]}, "repo": {"class": "private", "paths": ["**"]}}
    assert not any("store people" in e for e in classes.check(cfg=brain(stores)).errors)
    (root / "people" / ".gitkeep").write_text("a name\n", encoding="utf-8")
    run_git(root, "commit", "-q", "-am", "not empty")
    assert any(e.startswith("store people (confidential): 1 tracked file(s) go to git-private in clear")
               for e in classes.check(cfg=brain(stores)).errors)
