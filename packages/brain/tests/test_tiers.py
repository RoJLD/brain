import io
import json

import pytest

from brain import alerts, cli, paths, probe, stacks, tiers

REGISTRY = """\
infra:
  root: {tmp}/infra
  stacks:
    docker:
      start: [docker-desktop]
      detach: true
      health: {{cmd: [docker, info]}}
      class: service
      profile: recommended
      provides: [container runtime]
      requires: [docker]
      resources: {{ram_mb: 1000}}
      fallback: none; the container stacks are off
      recommend_when: [memory_gb >= 7]
app:
  root: {tmp}/app
  stacks:
    gitnexus:
      depends_on: [docker]
      start: [docker, compose, up, -d]
      health: {{urls: ['http://localhost:4747/api/health']}}
      class: service
      profile: recommended
      provides: [code graph]
      requires: [docker]
      resources: {{ram_mb: 300, disk_gb: 3}}
      fallback: the CodeRefs checked by the AST
      recommend_when: [memory_gb >= 7]
{extra}"""

BIG = {"os": "windows", "memory_gb": 63.9, "gpu": True, "gpu_vram_gb": 16.0, "cpu_cores": 16, "docker": True,
       "container_runtime": True, "git": True, "bash": True, "textual": True, "gh": True, "gitleaks": False,
       "wsl": False}
SMALL = {"os": "linux", "memory_gb": 3.8, "gpu": False, "gpu_vram_gb": 0.0, "cpu_cores": 2, "git": True,
         "bash": True}


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """A registry with two declared stacks, this machine named box1, config.json at tmp_path (absent at first)."""
    f = tmp_path / "projects.yaml"
    f.write_text(REGISTRY.format(tmp=tmp_path.as_posix(), extra=""), encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(f))
    monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("BRAIN_MACHINE", "box1")
    return tmp_path


def _reg(root=None):
    reg, errors = tiers.registry(root)
    assert errors == []
    return reg


def test_the_engine_registry_declares_every_key_and_the_profiles_follow_the_classes(brain):
    caps, errors = tiers.capabilities()
    assert errors == []
    assert {e.cls for e in caps.values()} == set(tiers.CLASSES)
    reg = _reg()
    lite, default = tiers.preset(reg, "lite"), tiers.preset(reg, "default")
    assert lite == {e.id for e in caps.values() if e.cls == "core"}   # Lite: the core, no dependency
    assert default - lite == {"tui"}                                   # Défaut: Lite and the cockpit's TUI only
    assert not any(reg[e].cls == "service" for e in default)           # no service before Recommandé
    assert "docker" not in default and "gitleaks" not in default and "html-views" not in default


@pytest.mark.parametrize("decl, message", [
    ({"class": "extra", "profile": "default", "provides": [], "requires": [], "resources": {}}, "missing fallback"),
    ({"class": "core", "profile": "default", "provides": [], "requires": [], "resources": {}}, "every profile"),
    ({"class": "service", "profile": "recommended", "provides": [], "requires": [], "resources": {}, "fallback": "x"},
     "missing recommend_when"),
    ({"class": "extra", "profile": "custom", "provides": [], "requires": [], "resources": {}, "fallback": "x",
      "recommend_when": []}, "recommend_when is for profile recommended only"),
    ({"class": "extra", "profile": "recommended", "provides": [], "requires": ["Docker Desktop"], "resources": {},
      "fallback": "x", "recommend_when": ["memory_gb >= "]}, "requirement 'Docker Desktop'"),
    ({"class": "extra", "profile": "recommended", "provides": [], "requires": [], "resources": {"ram": 1},
      "fallback": "x", "recommend_when": []}, "resources is a mapping"),
    ({"class": "big", "profile": "full", "provides": [], "requires": [], "resources": {}}, "class 'big'"),
])
def test_a_declaration_without_its_keys_is_refused(decl, message):
    errors = " | ".join(tiers._shape("x", decl, "stack 'x' (app)", stack=True))
    assert message in errors


def test_brain_check_refuses_a_stack_without_its_tier_and_an_unknown_override(brain, monkeypatch):
    (brain / "projects.yaml").write_text(REGISTRY.format(tmp=brain.as_posix(), extra=(
        "web:\n  root: x\n  stacks:\n    site: {start: [a], health: {cmd: [b]}}\n")), encoding="utf-8")
    (brain / "config.json").write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"},
                                                   "tier": {"base": "lite", "components": {"nope": True}}}),
                                       encoding="utf-8")
    errors = " | ".join(tiers.check(None))
    assert "stack 'site' (web): missing class, profile, provides, requires, resources" in errors
    assert "tier.components names 'nope'" in errors
    reg = _reg()
    assert tiers.state(reg["site"], set(), BIG) == ("undeclared", "no tier keys (brain check --all)")
    assert "site" in tiers.preset(reg, "lite")   # undeclared: in every profile, as before profiles


@pytest.mark.parametrize("clause, ok", [("memory_gb >= 7", True), ("memory_gb > 64", False), ("docker", True),
                                        ("not docker", False), ("not wsl", True), ("os == windows", True),
                                        ("os != linux", True), ("gpu_vram_gb >= 12", True), ("cpu_cores < x", False),
                                        ("bad clause !", False)])
def test_recommend_when_clauses(clause, ok):
    assert tiers.holds(clause, BIG) is ok


def test_recommended_is_computed_per_machine_and_a_stack_needs_its_dependency(brain):
    reg = _reg()
    assert tiers.recommend(reg, BIG) == {"docker": "memory_gb >= 7", "gitnexus": "memory_gb >= 7"}
    assert tiers.recommend(reg, SMALL) == {}
    assert tiers.recommend(reg, {**BIG, "docker": False}) == {}
    reg["docker"].recommend_when = ["memory_gb >= 128"]   # the dependency fails its rule: the dependent goes too
    assert tiers.recommend(reg, BIG) == {}
    assert set(tiers.would_fit(_reg(), BIG)) == {"html-views", "mcp-server", "local-model"}
    assert set(tiers.would_fit(_reg(), SMALL)) == {"html-views", "mcp-server"}


def test_the_machine_file_wins_over_config_which_wins_over_the_built_in_base(brain):
    assert (tiers.choice(None).base, tiers.choice(None).source) == ("default", "built-in")
    (brain / "config.json").write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"},
                                                   "tier": {"base": "lite", "components": {"tui": True}}}),
                                       encoding="utf-8")
    ch = tiers.choice(None)
    assert (ch.base, ch.source, ch.components) == ("lite", "config", {"tui": True})
    path, written = tiers.write(tiers.Choice("recommended", {"docker": True}, machine="box1"))
    assert written and path == tiers.machine_file()
    ch = tiers.choice(None)   # the machine's components merged key by key over config.json's (R25)
    assert (ch.base, ch.source, ch.components) == ("recommended", "machine", {"tui": True, "docker": True})
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**data, "machine": "other"}), encoding="utf-8")
    ch = tiers.choice(None)
    assert ch.source == "config" and "written for other, not box1" in ch.warnings[0]


def test_set_freezes_recommended_and_a_second_apply_changes_nothing(brain):
    reg, cur = _reg(), tiers.choice(None)
    new = tiers.plan(reg, cur, "recommended", [], ["gitnexus"], BIG)
    assert (new.base, new.components) == ("recommended", {"docker": True})
    assert new.computed_from["memory_gb"] == 63.9
    assert tiers.write(new)[1] is True
    again = tiers.plan(reg, tiers.choice(None), "recommended", [], ["gitnexus"], BIG)
    assert tiers.write(again)[1] is False
    on, warnings = tiers.active(reg, tiers.choice(None))
    assert {"docker", "tui", "guards"} <= on and "gitnexus" not in on and warnings == []
    # no base: the current choice with these overrides; turning gitnexus on brings its dependency
    later = tiers.plan(reg, tiers.Choice("default", {}, machine="box1"), None, ["gitnexus"], [], None)
    assert later.components == {"gitnexus": True}
    assert {"gitnexus", "docker"} <= tiers.active(reg, later)[0]
    off = tiers.Choice("default", {"gitnexus": True, "docker": False}, machine="box1")
    assert tiers.active(reg, off)[1] == ["gitnexus needs docker, which the overrides turn off"]
    assert tiers.plan(reg, cur, "lite", ["all"], [], None).components == {
        "docker": True, "gitnexus": True, "tui": True, "infra-node": True}


@pytest.mark.parametrize("with_, without, message", [
    (["nope"], [], "no capability or stack 'nope'"), (["plane"], [], "plane is planned (wi-brain-plane-view)"),
    ([], ["guards"], "guards is core"), ([], ["gitleaks"], "a profile does not turn it on or off")])
def test_set_refuses_what_cannot_be_chosen(brain, with_, without, message):
    with pytest.raises(tiers.TierError, match=message.replace("(", r"\(").replace(")", r"\)")):
        tiers.plan(_reg(), tiers.choice(None), "default", with_, without, BIG)


def test_states_say_on_off_to_install_fallback_unavailable_and_planned(brain):
    reg = _reg()
    on, _ = tiers.active(reg, tiers.Choice("default", {"docker": True}, machine="box1"))
    st = {e: tiers.state(reg[e], on, {**SMALL, "docker": False})[0] for e in reg}
    assert st["guards"] == "on" and st["tui"] == "to install" and st["docker"] == "fallback"
    assert st["gitnexus"] == "unavailable" and st["plane"] == "planned" and st["gitleaks"] == "fallback"
    assert st["notify"] == "auto"
    st = {e: tiers.state(reg[e], on, BIG)[0] for e in reg}
    assert st["tui"] == "on" and st["docker"] == "on" and st["gitnexus"] == "off" and st["gh"] == "on"


def test_render_gives_install_ps1_the_extras_and_the_stacks(brain, monkeypatch):
    reg = _reg()
    monkeypatch.setattr(probe, "_module", lambda name: True)   # textual installed
    r = tiers.render(reg, tiers.Choice("lite", {"gitnexus": True}, machine="box1"))
    assert r["extras"] == [] and r["extras_outside"] == ["tui"]
    assert r["stacks"] == {"on": ["docker", "gitnexus"], "off": []} and r["label"].startswith("lite (Lite,")
    r = tiers.render(reg, tiers.choice(None))
    assert r["extras"] == ["tui"] and r["extras_outside"] == [] and r["stacks"]["off"] == ["docker", "gitnexus"]


class Down:
    """Every stack down (docker info fails, the URL refuses)."""

    def __init__(self, monkeypatch):
        monkeypatch.setattr(stacks, "_probe_url", lambda url, timeout: "connection refused")
        monkeypatch.setattr(stacks, "_run", lambda argv, cwd, timeout: (1, "error during connect"))
        monkeypatch.setattr(stacks, "_resolve", lambda argv: list(argv))


def test_health_reports_a_stack_outside_the_profile_off_never_as_a_failure(brain, monkeypatch):
    Down(monkeypatch)
    out = io.StringIO()
    assert stacks.health(stacks.load(), [], every=True, out=out) == 0
    assert out.getvalue().splitlines() == [
        "docker OFF: outside this machine's profile, default; brain profile set --with docker adds it",
        "gitnexus OFF: outside this machine's profile, default; brain profile set --with gitnexus adds it"]
    tiers.write(tiers.Choice("default", {"gitnexus": True}, machine="box1"))
    out = io.StringIO()
    assert stacks.health(stacks.load(), [], every=True, out=out) == 1
    assert out.getvalue().splitlines() == ["docker DOWN: docker info exited 1: error during connect",
                                           "gitnexus DOWN: http://localhost:4747/api/health: connection refused"]
    cfg = alerts.Config("app", stacks=["gitnexus"])
    rows = [{"name": "gitnexus", "state": "OFF", "why": "outside"}, {"name": "docker", "state": "DOWN", "why": "x"}]
    assert [a.key for a in alerts.stack_alerts(cfg, rows, {"docker"})] == ["stack:docker"]


def _doc(facts_doc=None):
    return probe.report(
        {"memory": {"total_bytes": 64 * probe.GIB, "free_bytes": 32 * probe.GIB},
         "gpus": [probe._gpu("amd", "Card", 16 * probe.GIB, source="registry qwMemorySize")],
         "tools": {"python": "3.12", "git": True, "bash": True, "docker": True, "textual": True, "gh": True},
         "docker": {"runtime": "docker", "client": "29", "server": None},
         "disk": {"disks": [], "brain_home": None}},
        {n: {"ok": True, "seconds": 0.1} for n in probe.TIMEOUTS})


def test_cli_doctor_list_show_set_and_render(brain, monkeypatch, capsys):
    monkeypatch.setattr(probe, "collect", lambda quick=False, roots=None, timeouts=None: _doc())
    root = str(brain)
    assert cli.main(["--root", root, "doctor", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == probe.SCHEMA and doc["inventory"]["gpus"][0]["vram_bytes"] == 16 * probe.GIB
    prof = doc["brain"]["profile"]
    assert prof["active"]["base"] == "default" and prof["recommended"]["adds"] == {
        "docker": "memory_gb >= 7", "gitnexus": "memory_gb >= 7"}
    assert prof["drift"]["allows"] == ["docker", "gitnexus"] and prof["inventory"]["providers"] == ["local"]
    assert cli.main(["--root", root, "profile"]) == 0
    text = capsys.readouterr().out
    assert "gpu       Card, 16.0 GiB VRAM (registry qwMemorySize)" in text
    assert "proposal  this machine allows docker, gitnexus" in text
    assert cli.main(["--root", root, "profile", "list"]) == 0
    assert "recommended  Recommandé for box1: Défaut + docker, gitnexus" in capsys.readouterr().out
    assert cli.main(["--root", root, "profile", "show", "default", "--json"]) == 0
    assert "tui" in [r["id"] for r in json.loads(capsys.readouterr().out)]
    assert cli.main(["--root", root, "profile", "set", "recommended"]) == 0
    out = capsys.readouterr().out
    assert "on       docker (service, stack)" in out and "plan     " in out and not tiers.machine_file().exists()
    assert cli.main(["--root", root, "profile", "set", "recommended", "--apply"]) == 0
    assert "write    " in capsys.readouterr().out and tiers.machine_file().exists()
    assert cli.main(["--root", root, "profile", "set", "recommended", "--apply"]) == 0
    assert "nothing to change" in capsys.readouterr().out
    assert cli.main(["--root", root, "profile", "set", "--without", "guards"]) == 2
    assert "guards is core" in capsys.readouterr().err
    assert cli.main(["--root", root, "profile", "render", "lite"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["base"] == "lite" and r["extras"] == [] and r["stacks"]["off"] == ["docker", "gitnexus"]
    assert cli.main(["--root", root, "profile", "show", "custom"]) == 0
    assert "docker (service, stack)" in capsys.readouterr().out


def test_render_runs_with_no_root_from_an_empty_home(tmp_path, monkeypatch, capsys):
    """The brain command installed alone (no personal brain, no graph store above the folder): brain profile render
    gives the built-in base's extras instead of stopping on the missing root, so a first install.ps1 -Apply installs
    the cockpit's tui (wi-brain-install-profile-extras); set plans there too, and --root still runs at that root."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths, "package_repo", lambda: None)   # an engine inside a brain of its own finds that root
    monkeypatch.setattr(probe, "collect", lambda quick=False, roots=None, timeouts=None: _doc())
    with pytest.raises(SystemExit):
        paths.find_root()
    assert cli.main(["profile", "render"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["base"] == "default" and r["source"] == "built-in" and r["extras"] == ["tui"]
    assert cli.main(["profile", "set", "lite"]) == 0
    assert "plan     " in capsys.readouterr().out and not tiers.machine_file().exists()
    assert cli.main(["profile", "--quick"]) == 0
    assert "profile" in capsys.readouterr().out
    with pytest.raises(SystemExit):   # a root named that holds no brain is still the root acted on
        cli.main(["--project", "nosuch", "profile", "render"])
