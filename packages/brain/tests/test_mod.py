"""wi-brain-mod-command: brain mod, the module face of brain profile: module ids in tier.components and
profile.json expanded to their capabilities, hard and soft dependencies, a plan then an apply, each layer explained."""

import json

import pytest

from brain import cli, mod, tiers

TIERS = """\
capabilities:
  base:
    title: the base
    class: core
    profile: lite
    provides: [base]
    requires: []
    resources: {}
  store:
    title: a store the agent reads
    class: extra
    profile: custom
    provides: [store]
    requires: []
    resources: {disk_mb: 50}
    fallback: no store
  agent:
    title: an agent
    class: extra
    profile: custom
    provides: [agent]
    requires: []
    resources: {ram_mb: 200}
    fallback: the local probe
    depends_on: [store]
  viewer:
    title: a viewer
    class: extra
    profile: custom
    provides: [viewer]
    requires: []
    resources: {}
    fallback: the text view
    uses: [agent]
  finder:
    title: a tool used whenever it is found
    class: extra
    profile: custom
    auto: true
    provides: [finder]
    requires: []
    resources: {}
    fallback: nothing found
"""
MODULES = """\
- {id: M1, name: core-mod, brick: M, phase: MVP, status: tree, capabilities: [base]}
- {id: M2, name: agent-mod, brick: M, phase: MVP, status: tree, capabilities: [agent]}
- {id: M3, name: viewer-mod, brick: M, phase: MVP, status: tree, capabilities: [viewer], uses: [M2]}
- {id: M4, name: store-mod, brick: M, phase: MVP, status: tree, capabilities: [store]}
- {id: M5, name: finder-mod, brick: M, phase: MVP, status: tree, capabilities: [finder]}
"""


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """A brain at tmp_path/root whose store keeps a module registry; its own capabilities file; machine box1."""
    root = tmp_path / "root"
    (root / "notes" / "graph").mkdir(parents=True)
    (root / "notes" / "graph" / "modules.yaml").write_text(MODULES, encoding="utf-8")
    f = tmp_path / "tiers.yaml"
    f.write_text(TIERS, encoding="utf-8")
    real = tiers.capabilities
    monkeypatch.setattr(tiers, "capabilities", lambda path=f: real(path))
    monkeypatch.setenv("BRAIN_CONFIG", str(root / "config.json"))
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "none.yaml"))
    monkeypatch.setenv("BRAIN_MACHINE", "box1")
    return root


def _config(root, components):
    (root / "config.json").write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"},
                                                  "tier": {"base": "default", "components": components}}),
                                      encoding="utf-8")


def _on(root):
    reg, _ = tiers.registry(root)
    return tiers.active(reg, tiers.choice(root))[0]


def test_the_registry_groups_capabilities_and_a_capability_named_directly_wins(brain):
    assert mod.groups(brain) == {"M1": ["base"], "M2": ["agent"], "M3": ["viewer"], "M4": ["store"], "M5": ["finder"]}
    assert tiers.expand({"M3": True, "viewer": False}, mod.groups(brain)) == {"viewer": False}
    _config(brain, {"M3": True})
    assert "viewer" in _on(brain)


def test_enable_pulls_its_hard_dependency_and_a_second_apply_changes_nothing(brain):
    new, lines = mod.plan(brain, "agent-mod", True)
    assert lines[0] == "enable M2 (agent)" and "pulls M4 (store): M2 needs it" in lines[1]
    assert "capabilities on: agent, store" in lines[-1] and "cost" in lines[-1]
    assert tiers.write(new)[1] is True
    assert json.loads(tiers.machine_file().read_text(encoding="utf-8"))["components"] == {"M2": True, "M4": True}
    assert {"agent", "store"} <= _on(brain)
    assert tiers.write(mod.plan(brain, "M2", True)[0])[1] is False


def test_disable_is_refused_while_needed_unless_cascade(brain):
    tiers.write(mod.plan(brain, "M2", True)[0])
    with pytest.raises(mod.ModError, match="needed by M2, which are on: --cascade"):
        mod.plan(brain, "M4", False)
    new, lines = mod.plan(brain, "M4", False, cascade=True)
    assert "cascade: disable M2, which needs it" in lines[1]
    tiers.write(new)
    assert not {"agent", "store"} & _on(brain)
    with pytest.raises(mod.ModError, match="M1 is core"):
        mod.plan(brain, "M1", False)
    with pytest.raises(mod.ModError, match="no module 'nope'"):
        mod.plan(brain, "nope", True)


def test_the_machine_overrides_config_and_explain_shows_each_layer(brain):
    _config(brain, {"M2": True})
    assert {"agent", "store"} <= _on(brain)                        # config.json's default, its dependency pulled
    text = "\n".join(mod.explain(brain, "M4"))
    assert "engine     base default: store off" in text and "store (a dependency of what is on)" in text
    tiers.write(mod.plan(brain, "M2", False)[0])
    assert "agent" not in _on(brain)                               # this machine turns it off
    text = "\n".join(mod.explain(brain, "M2"))
    assert "config.json tier.components: on" in text and "profile.json: off" in text
    rows = {r["id"]: r for r in mod.rows(brain)}
    assert rows["M2"]["source"] == "profile.json" and rows["M2"]["state"] == "off"
    assert rows["M1"]["source"] == "preset" and rows["M3"]["fallback"] == "the text view"


def test_without_a_registry_each_capability_is_a_module(brain):
    (brain / "notes" / "graph" / "modules.yaml").unlink()
    cat = mod.catalogue(brain)
    assert set(cat) == {"base", "store", "agent", "viewer", "finder"} and mod.groups(brain) == {}
    assert cat["viewer"].uses == ["agent"]
    assert "pulls store" in mod.plan(brain, "agent", True)[1][1]


def test_capability_dependencies_name_capabilities(tmp_path):
    f = tmp_path / "tiers.yaml"
    f.write_text(TIERS.replace("depends_on: [store]", "depends_on: [nope]"), encoding="utf-8")
    assert any("depends_on names 'nope'" in e for e in tiers.capabilities(f)[1])


def test_the_cli(brain, capsys):
    assert cli.main(["--root", str(brain), "mod", "list"]) == 0
    assert "M2      off" in capsys.readouterr().out
    assert cli.main(["--root", str(brain), "mod", "enable", "M3"]) == 0
    out = capsys.readouterr().out
    assert "uses M2 when it is on, its fallback otherwise" in out and "plan only" in out
    assert not tiers.machine_file().exists()
    assert cli.main(["--root", str(brain), "mod", "enable", "M3", "--apply"]) == 0
    assert "written" in capsys.readouterr().out and "viewer" in _on(brain)
    assert cli.main(["--root", str(brain), "mod", "disable", "M1"]) == 2
    assert cli.main(["--root", str(brain), "mod", "show", "M2", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["depends_on"] == ["M4"]


# --- the review's cases ---

def _profile(components):
    tiers.machine_file().parent.mkdir(parents=True, exist_ok=True)
    tiers.machine_file().write_text(json.dumps({"v": 1, "machine": "box1", "base": "default",
                                                "components": components}), encoding="utf-8")


def test_brain_check_accepts_a_module_id_in_tier_components(brain):
    _config(brain, {"M2": True, "nope": True})
    errors = " | ".join(tiers.check(brain))
    assert "'M2'" not in errors and "names 'nope', no capability, stack or module" in errors


def test_profile_set_keeps_a_module_override_and_reads_it(brain, capsys):
    _config(brain, {"M4": True})
    tiers.write(mod.plan(brain, "M4", False)[0])
    reg, _ = tiers.registry(brain)
    later = tiers.plan(reg, tiers.choice(brain), None, ["viewer"], [], None)
    assert later.components == {"M4": False, "viewer": True}
    text = "\n".join(tiers.render_plan(reg, tiers.choice(brain), later, False, False, tiers.machine_file()))
    assert "unknown component" not in text and "off      store" not in text


def test_enable_wins_over_a_capability_the_machine_named_directly(brain):
    _config(brain, {"agent": True})
    _profile({"agent": False})
    assert "agent" not in _on(brain)
    tiers.write(mod.plan(brain, "M2", True)[0])
    assert "agent" in _on(brain)
    assert "agent" not in json.loads(tiers.machine_file().read_text(encoding="utf-8"))["components"]


def test_an_auto_module_is_neither_enabled_nor_disabled(brain):
    rows = {r["id"]: r for r in mod.rows(brain)}
    assert rows["M5"]["state"] == "auto"
    for enable in (True, False):
        with pytest.raises(mod.ModError, match="auto"):
            mod.plan(brain, "M5", enable)


def test_a_broken_registry_never_breaks_the_profile(brain):
    (brain / "notes" / "graph" / "modules.yaml").write_text("- {id: M1, capabilities: [base\n  - : :\n",
                                                             encoding="utf-8")
    _config(brain, {"agent": True})
    assert "agent" in _on(brain)


def test_explain_says_profile_json_turned_it_on_not_pulled(brain):
    _config(brain, {"agent": False})
    _profile({"M2": True})
    text = "\n".join(mod.explain(brain, "M2"))
    assert "profile.json: on" in text and "pulled     nothing" in text
