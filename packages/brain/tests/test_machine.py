"""wi-brain-machine-facts: one machine identity (the OS install's anchor), facts in three states with their source,
the ECC and battery probes, engine.min."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import brain
from brain import machine, memory, probe, records, skew, tiers

STATUS = Path(__file__).parent / "fixtures" / "formats" / "status" / "v1"
RAW = "4c4c4544-0000-1111-2222-b3c04f4e3233"   # an invented install id


@pytest.fixture
def box(monkeypatch, tmp_path):
    """A Windows machine named box1 whose install id is RAW; config.json at tmp_path (absent at first)."""
    monkeypatch.setenv("BRAIN_MACHINE", "Box1")
    monkeypatch.setenv("BRAIN_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr(machine, "_os", lambda: "windows")
    monkeypatch.setattr(machine, "_install_id_raw", lambda system: RAW)
    return tmp_path


def _cfg(tmp_path, **data):
    (tmp_path / "config.json").write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"}, **data}),
                                          encoding="utf-8")
    return {"v": 1, **data}


ANCHOR = hashlib.sha256(f"{RAW}\0windows".encode()).hexdigest()


# --- the identity ---

def test_one_name_everywhere(box, monkeypatch):
    assert machine.name() == memory.machine() == probe.machine() == "box1"
    monkeypatch.setenv("BRAIN_MACHINE", "My_Lab.Box")
    assert machine.name() == "my-lab-box"
    monkeypatch.delenv("BRAIN_MACHINE")
    monkeypatch.setattr(machine, "_hostname", lambda: "HOST-7")
    assert machine.name() == "host-7"


def test_the_anchor_is_a_hash_of_the_install_id_and_never_the_id(box):
    assert machine.anchor() == (ANCHOR, "MachineGuid")
    ident = machine.identity({})
    assert ident["state"] == "new" and ident["anchor"] == ANCHOR and ident["declare"].endswith(f'"{ANCHOR}"}}}}')
    text = machine.machine_file().read_text(encoding="utf-8")
    assert RAW not in text and json.loads(text)["name"] == "box1"
    assert machine.identity({})["state"] == "ok"


def test_a_doubt_holds_the_memory_export(box, monkeypatch):
    machine.identity({})
    assert memory.export_held() == ""
    monkeypatch.setenv("BRAIN_MACHINE", "box2")
    assert "first seen as box1" in memory.export_held()


def test_doubts_renamed_moved_reused_duplicate_and_no_anchor(box, monkeypatch):
    machine.identity({})                                         # first sight: box1 on RAW
    monkeypatch.setenv("BRAIN_MACHINE", "box2")
    ident = machine.identity({})
    assert ident["state"] == "renamed" and "first seen as box1" in ident["doubt"] and ident["asked"]
    assert json.loads(machine.machine_file().read_text(encoding="utf-8"))["name"] == "box1"   # never rewritten
    monkeypatch.setenv("BRAIN_MACHINE", "box1")
    monkeypatch.setattr(machine, "_install_id_raw", lambda system: "another-install")
    assert machine.identity({})["state"] == "moved"
    assert machine.in_doubt({})
    monkeypatch.setattr(machine, "_install_id_raw", lambda system: RAW)
    assert machine.identity({"hosts": {"box1": {"anchor": "0" * 64}}})["state"] == "reused"
    assert machine.identity({"hosts": {"box1": {"anchor": ANCHOR}, "old": {"anchor": ANCHOR}}})["state"] == "duplicate"
    ok = machine.identity({"hosts": {"box1": {"anchor": ANCHOR}}})
    assert ok["state"] == "ok" and ok["doubt"] == "" and "declare" not in ok
    monkeypatch.setattr(machine, "_install_id_raw", lambda system: (_ for _ in ()).throw(OSError("denied")))
    assert machine.identity({})["state"] == "no-anchor"


# --- the facts, their states and their sources ---

def test_an_unknown_fact_holds_neither_way():
    assert tiers.truth("ecc", {}) is None and tiers.truth("not ecc", {"ecc": None}) is None
    assert not tiers.holds("ecc", {"ecc": None}) and not tiers.holds("not ecc", {"ecc": None})
    assert tiers.holds("not ecc", {"ecc": False}) and tiers.holds("ecc", {"ecc": True})
    e = tiers.Entry("x", "capability", "x", requires=["ecc"])
    assert tiers.missing(e, {"ecc": None}) == ["ecc"]   # a requirement unknown is missing (safe)


def test_the_probe_wins_then_the_nodes_file_then_hosts_then_unknown(box, monkeypatch):
    genome = {"version": 2, "nodes": [{"name": "rack-7", "hardware": {"ecc": True, "gpu": False},
                                       "kind": "server"}]}
    monkeypatch.setattr(machine, "_git_show", lambda checkout, ref, file: json.dumps(genome))
    cfg = {"hosts": {"box1": {"aliases": ["rack-7"], "battery": True, "ecc": False, "type": "desktop"}},
           "inventory": {"nodes_file": {"checkout": "/x", "file": "nodes.yaml", "versions": [2],
                                        "fields": {"ecc": "hardware.ecc", "gpu": "hardware.gpu", "type": "kind"}}}}
    flat, sourced, errors = machine.facts({"gpu": True, "ecc": None, "battery": None, "encrypted": None}, cfg)
    assert errors == []
    assert sourced["gpu"]["source"] == "probed" and flat["gpu"] is True                   # the probe wins
    assert flat["ecc"] is True and sourced["ecc"]["source"].startswith("nodes-file@origin/main:")   # probe unknown
    assert (flat["type"], flat["battery"]) == ("server", True) and sourced["battery"]["source"] == "declared"
    assert flat["encrypted"] is None and sourced["encrypted"]["source"] == "unknown"
    bad = {**cfg["inventory"]["nodes_file"], "ref": "--output=x"}
    assert "starts with -" in machine.facts({}, {**cfg, "inventory": {"nodes_file": bad}})[2][0]
    genome["version"] = 3
    _, sourced, errors = machine.facts({}, cfg)
    assert "is not one this brain reads" in errors[0] and sourced["ecc"]["source"] == "declared"


def test_the_agent_report_counts_only_when_infra_node_is_on_and_recent(box, tmp_path):
    report = json.loads((STATUS / "older.json").read_text(encoding="utf-8"))
    now = datetime(2026, 11, 11, 13, 0, tzinfo=timezone.utc)
    (tmp_path / "box1.json").write_text(json.dumps(report), encoding="utf-8")
    cfg = {"inventory": {"agent_json": {"path": str(tmp_path / "{machine}.json")}}}
    flat, sourced, _ = machine.facts({"cpu_cores": 4}, cfg, infra_node=True, now=now)
    assert sourced["cpu_cores"]["source"] == "agent" and flat["cpu_cores"] != 4
    assert machine.facts({"cpu_cores": 4}, cfg, infra_node=False, now=now)[0]["cpu_cores"] == 4
    late = now + timedelta(days=2)
    flat, sourced, errors = machine.facts({"cpu_cores": 4}, cfg, infra_node=True, now=late)
    assert flat["cpu_cores"] == 4 and "older than 24 h" in errors[0]


@pytest.mark.parametrize("codes, dimms, battery, ecc", [
    ([6], [72, 64, 72, 64], 1, True), ([6], [64, 64], 0, False),   # an ECC board with non-ECC DIMMs: no ECC
    ([6], [], 0, True), ([3, 3], [], 0, False), ([2], [], 0, None), ([], [], 0, None)])
def test_the_windows_hardware_probe(monkeypatch, codes, dimms, battery, ecc):
    monkeypatch.setattr(probe, "_system", lambda: "Windows")
    monkeypatch.setattr(probe, "_run", lambda argv, timeout: (0, json.dumps({"ecc": codes, "dimms": dimms,
                                                                            "battery": battery})))
    hw = probe.probe_hardware()
    assert (hw["ecc"], hw["battery"]) == (ecc, bool(battery))


def test_flattened_facts_ecc_battery_encrypted_and_an_unprobed_gpu(monkeypatch):
    doc = json.loads((STATUS / "older.json").read_text(encoding="utf-8"))
    doc["brain"]["hardware"] = {"ecc": True, "battery": False}
    doc["brain"]["encryption"] = [{"volume": "D:", "state": "on", "source": "bitlocker"}]
    f = probe.facts(doc)
    assert (f["ecc"], f["battery"], f["encrypted"]) == (True, False, True)
    doc["brain"]["encryption"], doc["brain"]["hardware"] = None, None
    doc["inventory"]["gpus"], doc["brain"]["probes"]["gpus"] = [], {"ok": False, "seconds": 4.0}
    f = probe.facts(doc)
    assert f["ecc"] is f["battery"] is f["encrypted"] is f["gpu"] is None


def test_doctor_shows_the_identity_and_each_facts_source(box):
    _cfg(box, hosts={"box1": {"ecc": True}})
    doc = json.loads((STATUS / "older.json").read_text(encoding="utf-8"))
    doc["brain"]["hardware"] = {"ecc": None, "battery": False}
    doc = tiers.doctor(None, doc=doc)
    prof = doc["brain"]["profile"]
    assert prof["identity"]["state"] == "new" and prof["sources"]["ecc"] == {"value": True, "source": "declared"}
    text = "\n".join(tiers.render_doctor(doc))
    assert "identity  new, anchor " in text and "ecc yes (declared)" in text and "battery no (probed)" in text
    cached = json.loads((Path(brain.paths.brain_home()) / "facts.json").read_text(encoding="utf-8"))
    assert cached["machine"] == "box1" and cached["facts"]["ecc"]["source"] == "declared"


def test_infra_node_is_a_custom_capability_off_by_default(box):
    reg, _ = tiers.registry(None)
    e = reg["infra-node"]
    assert (e.cls, e.profile, e.auto) == ("extra", "custom", False)
    assert "infra-node" not in tiers.active(reg, tiers.choice(None))[0]


# --- engine.min ---

def test_below_engine_min_reads_and_writes_no_shared_format(box, store, monkeypatch):
    _cfg(box, engine={"repo": "o/brain", "pin": "v0.3.2", "min": "v99.0.0"})
    assert "below config.json engine.min v99.0.0" in skew.below_min(None)
    assert any("engine.min" in line for line in skew.check_lines(None))
    _cfg(box, engine={"repo": "o/brain", "min": "v99.0.0"})   # no pin: the minimum is still said
    assert any("engine.min" in line for line in skew.check_lines(None))
    root = store.parents[1]
    monkeypatch.setenv("BRAIN_CONFIG", str(box / "config.json"))
    from test_records import DDR
    with pytest.raises(SystemExit, match="no DDR written"):
        records.write(root, "ddr", DDR)
    assert "engine.min" in memory.export_held()   # the export held, the import goes on
    _cfg(box, engine={"repo": "o/brain", "pin": "v0.3.2", "min": "v0.0.1"})
    assert skew.below_min(None) == ""


def test_profile_json_overrides_config_key_by_key_and_never_copies_it(box, monkeypatch):
    """R25: the default common (config.json tier.components), the override local (profile.json), merged key by key."""
    _cfg(box, tier={"base": "default", "components": {"infra-node": True}})
    reg, _ = tiers.registry(None)
    assert "infra-node" in tiers.active(reg, tiers.choice(None))[0]
    new = tiers.plan(reg, tiers.choice(None), None, [], ["infra-node"], None)
    tiers.write(new)
    assert json.loads(tiers.machine_file().read_text(encoding="utf-8"))["components"] == {"infra-node": False}
    assert "infra-node" not in tiers.active(reg, tiers.choice(None))[0]   # this machine turns it off
    tiers.machine_file().write_text(json.dumps({"v": 1, "machine": "box1", "base": "default", "components": {}}),
                                    encoding="utf-8")
    ch = tiers.choice(None)
    assert ch.components == {"infra-node": True} and ch.own == {}   # a key it does not name keeps the default
    later = tiers.plan(reg, ch, None, ["tui"], [], None)
    assert "infra-node" not in later.components                     # config.json's default is never copied
