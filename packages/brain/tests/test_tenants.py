"""wi-brain-hmaas-multitenant (spec-brain-hmaas §6): a tenant is another brain, mounted opaque in the operator's
registry. No command reads into a mount, brain check --all refuses a mount that would hold a way in, and brain status
--all counts the mounts without opening them."""

import json
import os

import pytest

from brain import cli, graph, projects, status

MOUNTS = "team-z:\n  title: a hosted brain\n  tenant: {export: tenants/team-z/export.json}\nteam-y: {tenant: {}}\n"


def _registry(tmp_path, monkeypatch, store, extra):
    """demo (the fixture's store) plus ``extra``; BRAIN_HOME in tmp_path, where a mount's export is read from."""
    root = store.parents[1]
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir(exist_ok=True)
    reg.write_text(f"demo: {{root: {root.as_posix()}}}\n{extra}", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    monkeypatch.setenv("BRAIN_HOME", str(tmp_path / "home"))
    return root


def test_a_mount_is_never_loaded_as_a_project_and_cannot_be_named(tmp_path, monkeypatch, store):
    _registry(tmp_path, monkeypatch, store, MOUNTS)
    assert list(projects.load()) == ["demo"]  # every command that walks the registry goes through load()
    mounts = projects.mounts()
    assert list(mounts) == ["team-z", "team-y"]
    assert mounts["team-z"].title == "a hosted brain"
    assert mounts["team-z"].export == tmp_path / "home" / "tenants" / "team-z" / "export.json"  # under BRAIN_HOME
    assert mounts["team-y"].export is None and mounts["team-y"].title == ""
    with pytest.raises(SystemExit, match="tenant mount: another brain, opaque"):
        projects.get("team-z")
    with pytest.raises(SystemExit, match="tenant mount"):
        cli.main(["status", "--project", "team-z", "--quick"])
    assert projects.check() == []
    assert "tenant" in projects.KEYS and set(projects.TENANT_KEYS) == {"export"}  # brain projects --keys shows them


def test_check_refuses_a_mount_that_would_hold_a_way_in(tmp_path, monkeypatch, store, capsys):
    _registry(tmp_path, monkeypatch, store, "bad:\n  root: ../bad\n  stores: [notes/graph]\n  ledgers: {runs: r.jsonl}\n"
                                            "  tenant: {export: 3, keys: x}\nworse: {title: 7, tenant: [a]}\n")
    assert list(projects.load()) == ["demo"]  # loading tolerates them, and still skips them
    errors = projects.check()
    assert ("tenant bad: a tenant mount is opaque and holds title and tenant only, not ledgers, root, stores (the "
            "operator never reads into another brain)") in errors
    assert "tenant bad: tenant: unknown key(s) keys (known: export)" in errors
    assert "tenant bad: tenant.export is a path" in errors
    assert "tenant worse: title is a string" in errors
    assert "tenant worse: tenant is a mapping ({} when nothing is declared)" in errors
    monkeypatch.setattr(graph, "research_graph", lambda root, st, *a: 0)
    assert cli.main(["check", "--all"]) == 1
    assert "tenant bad: a tenant mount is opaque" in capsys.readouterr().out


def test_status_all_counts_the_mounts_and_never_opens_an_export(tmp_path, monkeypatch, store, capsys):
    _registry(tmp_path, monkeypatch, store, MOUNTS + "team-x: {tenant: {export: tenants/team-x/export.json}}\n")
    export = tmp_path / "home" / "tenants" / "team-z" / "export.json"
    export.parent.mkdir(parents=True)
    export.write_text('{"v": 1, "secret_project": "never shown"}', encoding="utf-8")
    os.utime(export, (1_793_620_800, 1_793_620_800))  # 2026-11-02, midday UTC
    opened = []
    real_open = type(export).open
    monkeypatch.setattr(type(export), "open", lambda self, *a, **k: opened.append(self) or real_open(self, *a, **k))
    data = status.run(list(projects.load().values()), every=True, quick=True)
    assert export not in opened  # its size and date are read, never its content
    assert [p["project"] for p in data["projects"]] == ["demo"] and data["total"]["tenants"] == 3
    assert data["tenants"][0] == {"name": "team-z", "title": "a hosted brain", "export": export.as_posix(),
                                  "export_found": True, "export_written": "2026-11-02"}
    assert [(t["name"], t["export_found"], t["export"] is None) for t in data["tenants"][1:]] == [
        ("team-y", False, True), ("team-x", False, False)]
    assert "never shown" not in status.render_json(data)
    text = " ".join(" ".join(status.render(data)).split())  # the row wraps under itself
    assert ("tenants 3 mounted, opaque (never read into): team-z export written 2026-11-02; team-y no export declared; "
            "team-x export missing") in text
    assert cli.main(["status", "--all", "--quick", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["total"]["tenants"] == 3


def test_status_all_without_a_mount_prints_no_tenants_line(tmp_path, monkeypatch, store):
    _registry(tmp_path, monkeypatch, store, "")
    data = status.run(list(projects.load().values()), every=True, quick=True)
    assert data["tenants"] == [] and data["total"]["tenants"] == 0
    assert not any(x.startswith("  tenants") for x in status.render(data))
