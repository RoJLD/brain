"""wi-brain-read-only-projects: a registry entry with ``access: read`` is a project the brain reads and never writes. It
holds a title and its access only; no command loads it, names it or writes into it, brain check --all refuses an entry
that would hold a way in, and the views count it."""

import json
import os

import pytest

from brain import cli, graph, guards, neutral, projects, status

READ_ONLY = "upstream:\n  title: a project the brain follows\n  access: read\nmirror: {access: read}\n"


def _registry(tmp_path, monkeypatch, store, extra):
    """demo (the fixture's store) plus ``extra``."""
    root = store.parents[1]
    reg = tmp_path / "brain" / "projects.yaml"
    reg.parent.mkdir(exist_ok=True)
    reg.write_text(f"demo: {{root: {root.as_posix()}}}\n{extra}", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return root


def test_a_read_only_project_is_never_loaded_and_cannot_be_named(tmp_path, monkeypatch, store):
    _registry(tmp_path, monkeypatch, store, READ_ONLY)
    assert list(projects.load()) == ["demo"]  # every command that walks the registry goes through load()
    ro = projects.readonly()
    assert [(r.name, r.title) for r in ro.values()] == [("upstream", "a project the brain follows"), ("mirror", "")]
    with pytest.raises(SystemExit, match="'upstream' is read only: the brain reads it and never writes it"):
        projects.get("upstream")
    for argv in (["item", "add", "wi-x", "--title", "X", "--project", "upstream"],
                 ["journal", "add", "--project", "upstream", "--title", "Day", "x"],
                 ["--project", "mirror", "adr", "new", "T", "--decision", "d"],
                 ["status", "--project", "upstream", "--quick"]):
        with pytest.raises(SystemExit, match="is read only"):
            cli.main(argv)
    assert projects.check() == []
    assert "access" in projects.KEYS and projects.READ_ONLY_KEYS == {"title", "access", "parent", "classes"}


def test_check_refuses_a_read_only_entry_that_would_hold_a_way_in_and_an_unknown_access(tmp_path, monkeypatch, store):
    _registry(tmp_path, monkeypatch, store,
              "upstream:\n  root: ../upstream\n  stores: [notes/graph]\n  production: [.]\n  journal: j.md\n"
              "  repos: [.]\n  access: read\nodd: {root: ../odd, access: maybe}\n"
              "plain: {root: ., access: write}\n")
    errors = projects.check()
    assert ("project upstream: a read-only project holds title, access, parent and classes only, not journal, production, repos, root, "
            "stores (each is a way to write or read into it)") in errors
    assert "project odd: access is read or write, not 'maybe'" in errors
    assert not any(e.startswith("project plain") for e in errors)  # access: write is the default, said
    assert list(projects.load()) == ["demo", "plain"]  # what is not write is never loaded: it narrows
    with pytest.raises(SystemExit, match="'odd' is not loaded: access is read or write, not 'maybe'"):
        projects.get("odd")  # a typo is named as one, not as a read-only project
    assert list(projects.readonly()) == ["upstream"]  # nor listed or counted as one (brain projects, status, check)
    # Fail closed: an entry the walk skips (access: read that check() refuses, or an access value it does not know)
    # still keeps the guards of every local path it declares. A typo in access, or access: read added to a project
    # with a production checkout, must never lift a production or branch guard while check() is red.
    upstream, odd = tmp_path / "upstream", tmp_path / "odd"
    upstream.mkdir()
    odd.mkdir()
    roots = {os.path.normcase(os.path.abspath(r)) for r in guards.production_roots()}
    assert os.path.normcase(str(upstream)) in roots
    folders, _ = guards.registered_repos()
    folders = {os.path.normcase(os.path.abspath(f)) for f in folders}
    assert os.path.normcase(str(upstream)) in folders and os.path.normcase(str(odd)) in folders


def test_only_access_read_is_read_only_and_any_other_value_is_invalid_everywhere(tmp_path, monkeypatch, store,
                                                                                capsys):
    """access: read alone is a read-only project; a value other than read or write (a typo) is reported as invalid
    wherever the registry is read, never shown or counted as read only, and never loaded."""
    assert projects.is_read_only({"access": "read"}) and not projects.bad_access({"access": "read"})
    assert not projects.is_read_only({"access": "write"}) and not projects.bad_access({"access": "write"})
    for value in ("wirte", "Read", "", None, True):
        assert not projects.is_read_only({"access": value}) and projects.bad_access({"access": value}), value
    root = _registry(tmp_path, monkeypatch, store, "upstream: {access: read}\nodd: {title: Odd, access: wirte}\n")
    assert list(projects.load()) == ["demo"] and list(projects.readonly()) == ["upstream"]
    assert projects.invalid_access() == {"odd": "wirte"}
    assert projects.check() == ["project odd: access is read or write, not 'wirte'"]
    assert projects.unloaded("odd") == "'odd' is not loaded: access is read or write, not 'wirte'"
    with pytest.raises(SystemExit, match="'odd' is not loaded: access is read or write, not 'wirte'"):
        cli.main(["status", "--project", "odd", "--quick"])
    source = root / "source"
    (source / "rules" / "scopes").mkdir(parents=True)
    (source / "packs.yaml").write_text("v: 1\npacks:\n  core: {core: true, rules: [rules/global.md]}\n"
                                       "  side: {projects: [odd]}\n", encoding="utf-8")
    (source / "rules" / "global.md").write_text("---\nscope: global\n---\n\n## One\n<!-- id: rule-one -->\n\nText.\n",
                                                encoding="utf-8")
    (source / "rules" / "scopes" / "odd.md").write_text("---\ntitle: Odd\n---\n", encoding="utf-8")
    errors = neutral.check(neutral.load(root))
    assert "rules/scopes/odd.md: scope 'odd' is not loaded: access is read or write, not 'wirte'" in errors
    assert "packs.yaml: pack side: project 'odd' is not loaded: access is read or write, not 'wirte'" in errors
    assert not any("read only" in e or "read-only" in e for e in errors)
    assert cli.main(["projects"]) == 0
    assert "odd" not in capsys.readouterr().out
    data = status.run(list(projects.load().values()), every=True, quick=True)
    assert data["read_only"] == [{"name": "upstream", "title": ""}] and data["total"]["read_only"] == 1


def test_a_valid_read_only_entry_adds_no_guard_and_no_path(tmp_path, monkeypatch, store):
    """title and access only: there is no local path to guard, so the guards' inputs are those of demo alone."""
    _registry(tmp_path, monkeypatch, store, "")
    before = (sorted(guards.production_roots()), guards.registered_repos())
    _registry(tmp_path, monkeypatch, store, READ_ONLY)
    assert (sorted(guards.production_roots()), guards.registered_repos()) == before


def test_sync_check_and_refresh_all_pass_it_by_without_a_store_and_count_it(tmp_path, monkeypatch, store, capsys):
    calls = []
    monkeypatch.setattr(graph, "research_graph", lambda root, st, *a: calls.append((root.name, a)) or 0)
    root = _registry(tmp_path, monkeypatch, store, READ_ONLY)
    assert cli.main(["check", "--all"]) == 0
    out = capsys.readouterr().out
    assert calls == [(root.name, ("check",))] and "upstream" not in out.split("== registry")[0]
    assert "registry: 1 project(s), 1 store(s), ids unique; 2 read only" in out
    calls.clear()
    assert cli.main(["sync", "--all"]) == 0
    assert [c[1][0] for c in calls] == ["sync", "kanban"] and {c[0] for c in calls} == {root.name}
    calls.clear()
    assert cli.main(["refresh", "--all"]) == 0
    assert {c[0] for c in calls} == {root.name} and "; 2 read only" in capsys.readouterr().out


def test_the_rules_never_name_a_read_only_project(tmp_path, monkeypatch, store):
    root = _registry(tmp_path, monkeypatch, store, READ_ONLY)
    source = root / "source"
    (source / "rules" / "scopes").mkdir(parents=True)
    (source / "packs.yaml").write_text("v: 1\npacks:\n  core: {core: true, rules: [rules/global.md]}\n"
                                       "  side: {projects: [upstream]}\n", encoding="utf-8")
    (source / "rules" / "global.md").write_text("---\nscope: global\n---\n\n## One\n<!-- id: rule-one -->\n\nText.\n",
                                                encoding="utf-8")
    (source / "rules" / "scopes" / "upstream.md").write_text("---\ntitle: Upstream\n---\n\n## Two\n"
                                                             "<!-- id: rule-two -->\n\nText.\n", encoding="utf-8")
    errors = "\n".join(neutral.check(neutral.load(root)))
    assert ("rules/scopes/upstream.md: scope 'upstream' is a read-only project: the brain never writes its rules "
            "(its own sessions do)") in errors
    assert "packs.yaml: pack side: project 'upstream' is read only: the brain renders nothing for it" in errors


def test_brain_projects_and_its_json_say_each_access(tmp_path, monkeypatch, store, capsys):
    _registry(tmp_path, monkeypatch, store, READ_ONLY)
    assert cli.main(["projects"]) == 0
    out = capsys.readouterr().out
    assert "upstream (read only: the brain reads it and never writes it): a project the brain follows" in out
    assert "mirror (read only: the brain reads it and never writes it)\n" in out
    assert cli.main(["projects", "--json"]) == 0
    data = {d["name"]: d for d in json.loads(capsys.readouterr().out)["projects"]}
    assert data["demo"]["access"] == "write" and data["demo"]["shares_root_with"] == ""
    assert data["upstream"] == {"name": "upstream", "title": "a project the brain follows", "access": "read"}
    assert cli.main(["projects", "--keys"]) == 0
    assert "  access " in capsys.readouterr().out


def test_status_all_counts_the_read_only_projects(tmp_path, monkeypatch, store, capsys):
    _registry(tmp_path, monkeypatch, store, READ_ONLY)
    data = status.run(list(projects.load().values()), every=True, quick=True)
    assert [p["project"] for p in data["projects"]] == ["demo"] and data["total"]["read_only"] == 2
    assert data["read_only"] == [{"name": "upstream", "title": "a project the brain follows"},
                                 {"name": "mirror", "title": ""}]
    text = " ".join(" ".join(status.render(data)).split())
    assert "read only 2 (the brain reads them, never writes): upstream, mirror" in text
    _registry(tmp_path, monkeypatch, store, "")
    data = status.run(list(projects.load().values()), every=True, quick=True)
    assert data["total"]["read_only"] == 0 and not any(x.startswith("  read only") for x in status.render(data))


def test_audit_and_its_diff_say_a_read_only_project_is_one(tmp_path, monkeypatch, store, git_repo, capsys):
    _registry(tmp_path, monkeypatch, store, READ_ONLY)
    monkeypatch.chdir(git_repo)
    for argv in (["--project", "upstream", "audit", "--write"], ["--project", "upstream", "audit", "--diff"]):
        assert cli.main(argv) == 2
        assert "'upstream' is read only: the brain reads it and never writes it" in capsys.readouterr().err
    assert cli.main(["--project", "nope", "audit"]) == 2
    assert "unknown project 'nope'" in capsys.readouterr().err
