"""wi-brain-project-formats: projects.yaml formats: and migrations: (brain.formats; spec-brain-data-compat § 3
« Other projects », the owner's PF-1 answer « Opt-in run »). The declarations are checked with the registry, always;
the check: commands run only on demand (brain formats check, brain check --formats), bounded, cached by the hashes of
the files they judge; a project the brain only reads declares none; the scout finds a when file changed with no new
add file."""

import json
import sys

import pytest

from brain import cli, formats, projects
from brain.commands import formats as formats_cmd

from test_scout import _append, _scout, _setup


def _cmd(code: str) -> str:
    """A check: command as a YAML flow list: this Python running ``code``."""
    return json.dumps([sys.executable, "-c", code])


COUNT = "import pathlib, sys; f = pathlib.Path(sys.argv[1]); f.write_text(f.read_text() + 'x' if f.exists() else 'x')"


def _project(tmp_path, monkeypatch, formats_yaml: str = "", extra: str = "", files=None):
    """A project ``lab`` at a plain folder holding ``files`` (default: two order files, a schema, fixtures)."""
    root = tmp_path / "lab"
    for rel, text in (files if files is not None else {
            "orders/a.json": "{}", "orders/b.json": "{}", "schemas/orders.schema.json": "{}",
            "tests/fixtures/orders/v1.json": "{}"}).items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    root.mkdir(exist_ok=True)
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"lab:\n  root: {root.as_posix()}\n" + (f"  formats:\n{formats_yaml}" if formats_yaml else "")
                   + extra, encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    return root


def _fmt(check: str = "", **over) -> str:
    keys = {"id": "orders", "glob": "orders/*.json", "class": "private", "version": "SCHEMA_VERSION",
            "schema": "schemas/orders.schema.json", "fixtures": "tests/fixtures/orders", **over}
    if check:
        keys["check"] = check
    body = "".join(f"      {k}: {v}\n" for k, v in keys.items() if v is not None)
    return "    - " + body.lstrip()


def test_the_keys_are_registered_and_a_valid_declaration_passes(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch, _fmt() + _fmt(id="orders-2", schema=None, fixtures=None, check=_cmd("pass"),
                                                  timeout=30),
             extra="  migrations:\n    - {when: ['models/**/*.py'], add: ['migrations/*.py', 'tests/fixtures/db/**']}\n")
    assert {"formats", "migrations"} <= set(projects.KEYS)
    assert projects.check() == []
    p = projects.load()["lab"]
    fmts = formats.formats_of(p.formats)
    assert [(f.id, f.cls, f.version, f.timeout) for f in fmts] == [("orders", "private", "SCHEMA_VERSION", 120),
                                                                    ("orders-2", "private", "SCHEMA_VERSION", 30)]
    assert fmts[0].check is None and fmts[1].check == [sys.executable, "-c", "pass"]
    assert [(m.when, m.add) for m in formats.migrations_of(p.migrations)] == [
        (["models/**/*.py"], ["migrations/*.py", "tests/fixtures/db/**"])]


@pytest.mark.parametrize("entry, message", [
    ("    - {glob: 'a/*', class: private, version: v}\n", "formats[0]: id is required"),
    ("    - {id: x, glob: 'orders/*.json', class: open, version: v}\n", "format x: class is one of public"),
    ("    - {id: X!, glob: 'orders/*.json', class: private, version: v}\n", "id is lowercase letters"),
    ("    - {id: x, glob: '/etc/*', class: private, version: v}\n", "glob is relative to the repo"),
    ("    - {id: x, glob: '../up/*', class: private, version: v}\n", "glob is relative to the repo"),
    ("    - {id: x, glob: 'orders/*.json', class: private, version: v, timeout: 0}\n", "timeout is a whole number"),
    ("    - {id: x, glob: 'orders/*.json', class: private, version: v, check: ''}\n", "check is a command"),
    ("    - {id: x, glob: 'orders/*.json', class: private, version: v, repo: other}\n",
     "repo 'other' is not one of the project's repos (lab)"),
    ("    - {id: x, glob: 'orders/*.json', class: private, version: v}\n    - {id: x, glob: 'orders/*.json', "
     "class: private, version: v}\n", "format x: its id is used twice"),
    ("    - {id: x, glob: 'nothing/*.json', class: private, version: v}\n", "matches no file in lab"),
    ("    - {id: x, glob: 'orders/*.json', class: private, version: v, schema: s.json}\n",
     "its schema s.json is not a file in lab"),
    ("    - {id: x, glob: 'orders/*.json', class: private, version: v, fixtures: fx}\n",
     "its fixtures fx is not a folder in lab"),
    ("    - {id: x, glob: 'orders/*.json', class: private, version: v, owner: me}\n", "format x: unknown key(s) owner"),
])
def test_a_bad_declaration_is_named_by_the_registry_check(tmp_path, monkeypatch, entry, message):
    _project(tmp_path, monkeypatch, entry)
    errors = projects.check()
    assert any(message in e for e in errors), errors


def test_bad_migrations_and_a_newer_key_in_read_mode(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch, extra="  migrations:\n    - {when: [], add: 'm/*.py'}\n    - nope\n"
                                          "    - {when: 'a', add: 'b', since: 2}\n")
    errors = projects.check()
    assert any("migrations[0]: when is a glob or a list of globs" in e for e in errors)
    assert any("migrations[1]: a mapping of when, add, repo" in e for e in errors)
    assert any("migrations[2]: unknown key(s) since" in e for e in errors)
    monkeypatch.setenv("BRAIN_STRICT", "0")   # an older engine reading a newer one's key: a note, kept
    assert not any("since" in e for e in projects.check())
    assert len(formats.migrations_of(projects.load()["lab"].migrations)) == 1


def test_the_registry_check_never_runs_a_command(tmp_path, monkeypatch):
    """PF-1: brain check judges the declarations, and nothing more."""
    marker = tmp_path / "ran"
    _project(tmp_path, monkeypatch, _fmt(check=json.dumps([sys.executable, "-c", COUNT, str(marker)])))
    assert projects.check() == []
    assert not marker.exists()


def test_check_runs_bounded_and_caches_a_pass_or_a_fail_by_the_files_hashes(tmp_path, monkeypatch, capsys):
    marker = tmp_path / "count"
    root = _project(tmp_path, monkeypatch, _fmt(check=json.dumps([sys.executable, "-c", COUNT, str(marker)])))
    assert cli.main(["formats", "check", "--project", "lab"]) == 0
    assert "pass     orders (" in capsys.readouterr().out and marker.read_text(encoding="utf-8") == "x"
    assert cli.main(["formats", "check", "--project", "lab"]) == 0   # the same files: the cached pass
    assert "pass     orders (cached)" in capsys.readouterr().out and marker.read_text(encoding="utf-8") == "x"
    cache = json.loads(formats.cache_file("lab").read_text(encoding="utf-8"))
    assert cache["v"] == 1 and cache["results"]["orders"]["status"] == "pass"
    for change in ("orders/b.json", "schemas/orders.schema.json", "tests/fixtures/orders/v1.json"):
        (root / change).write_text('{"changed": "%s"}' % change, encoding="utf-8")
        assert cli.main(["formats", "check", "--project", "lab"]) == 0
        capsys.readouterr()
    assert marker.read_text(encoding="utf-8") == "xxxx"   # each judged file changed: run again
    assert cli.main(["formats", "check", "--project", "lab", "--fresh"]) == 0
    assert marker.read_text(encoding="utf-8") == "xxxxx"


@pytest.mark.parametrize("code, status, cached", [
    ("import sys; sys.exit(1)", "fail", True),
    ("import sys; sys.exit(3)", "error", False),
    ("import time; time.sleep(30)", "timeout", False),
])
def test_a_fail_is_cached_a_timeout_or_another_exit_never(tmp_path, monkeypatch, capsys, code, status, cached):
    _project(tmp_path, monkeypatch, _fmt(check=_cmd(code), timeout=2))
    assert cli.main(["formats", "check", "--project", "lab", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert [(r["format"], r["status"], r["cached"]) for r in data["projects"][0]["results"]] == [
        ("orders", status, False)]
    cli.main(["formats", "check", "--project", "lab", "--json"])
    again = json.loads(capsys.readouterr().out)["projects"][0]["results"][0]
    assert (again["status"], again["cached"]) == (status, cached)


def test_a_command_not_found_a_format_without_check_and_an_invalid_declaration(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch, _fmt(check="no-such-checker-xyz --check") + _fmt(id="plain"))
    assert cli.main(["formats", "check", "--project", "lab", "--json"]) == 1
    res = {r["format"]: r for r in json.loads(capsys.readouterr().out)["projects"][0]["results"]}
    assert res["orders"]["status"] == "error" and "cannot run 'no-such-checker-xyz'" in res["orders"]["detail"]
    assert res["plain"]["status"] == "skipped"
    assert cli.main(["formats", "check", "--project", "lab", "--format", "plain"]) == 0
    capsys.readouterr()
    assert cli.main(["formats", "check", "--project", "lab", "--format", "nope"]) == 1
    assert "no format 'nope'" in capsys.readouterr().out
    _project(tmp_path, monkeypatch, _fmt(check=_cmd("pass"), **{"class": "open"}))
    assert cli.main(["formats", "check", "--project", "lab", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)["projects"][0]
    assert data["results"] == [] and any("class is one of" in e for e in data["errors"])   # nothing run


def test_list_prints_each_format(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch, _fmt(check="python -m lab.contract --check"))
    assert cli.main(["formats", "list", "--project", "lab", "--json"]) == 0
    (row,) = json.loads(capsys.readouterr().out)["formats"]
    assert row["repo"] == "lab" and row["check"] == ["python", "-m", "lab.contract", "--check"]
    assert cli.main(["formats", "list", "--project", "lab"]) == 0
    out = capsys.readouterr().out
    assert "lab/orders  orders/*.json in lab  class private, version: SCHEMA_VERSION" in out
    assert "check: python -m lab.contract --check (timeout 120 s)" in out


def test_a_read_only_project_declares_no_format_and_nothing_of_it_runs(tmp_path, monkeypatch, capsys):
    marker = tmp_path / "ran"
    _project(tmp_path, monkeypatch, _fmt(check=_cmd("pass")),
             extra=f"upstream:\n  access: read\n  formats:\n    - {{id: x, glob: '*', class: private, version: v, "
                   f"check: {json.dumps([sys.executable, '-c', COUNT, str(marker)])}}}\n")
    assert any("upstream: a read-only project holds title, access, parent and classes only, not formats" in e
               for e in projects.check())
    assert cli.main(["formats", "check", "--all", "--json"]) == 0
    assert [d["project"] for d in json.loads(capsys.readouterr().out)["projects"]] == ["lab"]
    assert not marker.exists()
    with pytest.raises(SystemExit, match="is read only"):
        cli.main(["formats", "check", "--project", "upstream"])


def test_brain_check_formats_runs_them_after_the_check(tmp_path, monkeypatch, capsys, store):
    root = store.parents[1]
    (root / "orders").mkdir()
    (root / "orders" / "a.json").write_text("{}", encoding="utf-8")
    reg = tmp_path / "projects.yaml"
    reg.write_text(f"demo:\n  root: {root.as_posix()}\n  formats:\n    - {{id: orders, glob: 'orders/*.json', class: "
                   f"private, version: v, check: {_cmd('import sys; sys.exit(1)')}}}\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(reg))
    cli.main(["check", "--project", "demo"])
    assert "== formats" not in capsys.readouterr().out   # a plain check runs no command
    assert cli.main(["check", "--project", "demo", "--formats"]) == 1
    out = capsys.readouterr().out
    assert "== formats" in out and "fail     orders" in out


def test_the_cache_is_a_registered_engine_store():
    from brain import classes
    assert classes.ENGINE_STORES["formats"].path == "$BRAIN_HOME/formats"
    assert formats.cache_file("x").parent.name == formats.DIR == "formats"


# --- the scout's glob check ---

RULE = ", migrations: [{when: ['src/lab/core.py'], add: ['migrations/*.py']}]"


def test_a_when_file_changed_without_a_new_add_file_is_new(make_repo, tmp_path, monkeypatch, capsys):
    lab = _setup(make_repo, tmp_path, monkeypatch, extra=RULE)
    _append(lab, "src/lab/core.py", "\n\ndef g():\n    return 1\n")
    _, tags, data = _scout(capsys, lab)
    assert tags[("format.migration", "src/lab/core.py")] == "NEW"
    f = next(x for x in data["findings"] if x["check"] == "format.migration")
    assert "no new file matching migrations/*.py" in f["why"] and "Justified: src/lab/core.py" in f["fix"]
    (lab / "migrations").mkdir()
    (lab / "migrations" / "m0001.py").write_text("STEP = 1\n", encoding="utf-8")
    _, tags, _ = _scout(capsys, lab)
    assert ("format.migration", "src/lab/core.py") not in tags


def test_a_light_touch_or_a_justified_line_never_blocks(make_repo, tmp_path, monkeypatch, capsys):
    lab = _setup(make_repo, tmp_path, monkeypatch, extra=RULE)
    _append(lab, "src/lab/core.py", "\n\n")   # whitespace only
    _, tags, _ = _scout(capsys, lab)
    assert ("format.migration", "src/lab/core.py") not in tags
    _append(lab, "src/lab/core.py", "def g():\n    return 1\n")
    body = tmp_path / "body.md"
    body.write_text("Justified: src/lab/core.py: a helper, no column moves\n", encoding="utf-8")
    _, tags, _ = _scout(capsys, lab, "--pr-body", str(body))
    assert tags[("format.migration", "src/lab/core.py")] == "justified"


def test_a_rule_of_another_repo_is_not_applied(tmp_path):
    rows = [("M", "src/lab/core.py", "src/lab/core.py")]
    rule = formats.Migration(["src/lab/core.py"], ["migrations/*.py"], repo="other")
    assert formats.migration_signals("lab", "lab", [rule], rows, {}, "") == []
    rule.repo = ""
    assert [f["tag"] for f in formats.migration_signals("lab", "lab", [rule], rows, {}, "")] == ["NEW"]
    moved_in = rows + [("R100", "old/m.py", "migrations/m.py")]   # renamed into the add glob: a new migration
    assert formats.migration_signals("lab", "lab", [rule], moved_in, {}, "") == []
    inside = rows + [("R100", "migrations/a.py", "migrations/b.py")]   # renamed within it: none new
    assert len(formats.migration_signals("lab", "lab", [rule], inside, {}, "")) == 1
    assert formats.migration_signals("lab", "lab", [rule], rows + [("A", "", "migrations/m.py")], {}, "") == []


def test_the_command_is_documented():
    usage = " ".join(formats_cmd.USAGE.split())
    assert "brain formats list" in usage and "Never run by a plain brain check" in usage


def test_a_deleted_or_moved_out_when_file_needs_a_migration_too():
    rule = formats.Migration(["models/*.py"], ["migrations/*.py"])
    for rows in ([("D", "models/user.py", "")], [("R100", "models/user.py", "archive/user.py")]):
        (f,) = formats.migration_signals("lab", "lab", [rule], rows, {}, "")
        assert f["unit"] == "models/user.py" and f["tag"] == "NEW"
    pure = [("R100", "models/user.py", "models/account.py")]   # a pure rename inside the models: a light touch
    assert formats.migration_signals("lab", "lab", [rule], pure, {"models/account.py": True}, "") == []


def test_a_string_check_with_a_backslash_is_refused(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch, _fmt(check="'tools\\check.cmd --strict'"))
    assert any("check holds a backslash" in e and "as a list" in e for e in projects.check())


def test_a_checker_script_of_the_repo_is_judged_too(tmp_path, monkeypatch, capsys):
    marker = tmp_path / "count"
    root = _project(tmp_path, monkeypatch, _fmt(check=json.dumps([sys.executable, "tools/chk.py"])))
    (root / "tools").mkdir()
    chk = root / "tools" / "chk.py"
    chk.write_text(COUNT.replace("sys.argv[1]", repr(str(marker))) + "\n", encoding="utf-8")
    p = projects.load()["lab"]
    (f,) = formats.formats_of(p.formats)
    assert "tools/chk.py" in formats.judged(f, root)
    for _ in range(2):
        assert cli.main(["formats", "check", "--project", "lab"]) == 0
    chk.write_text(chk.read_text(encoding="utf-8") + "# stricter\n", encoding="utf-8")
    assert cli.main(["formats", "check", "--project", "lab"]) == 0
    capsys.readouterr()
    assert marker.read_text(encoding="utf-8") == "xx"   # the stricter checker ran again


def test_a_relative_program_is_the_repos_whatever_the_brains_folder(tmp_path, monkeypatch, capsys):
    root = _project(tmp_path, monkeypatch, _fmt(check=json.dumps(["./tools/ok.py"])))
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "tools").mkdir(parents=True)
    monkeypatch.chdir(elsewhere)
    (f,) = formats.formats_of(projects.load()["lab"].formats)
    assert formats.resolve_exe(f.check, root)[0] == str((root / "tools" / "ok.py").resolve())
    with pytest.raises(ValueError, match="outside the repo"):
        formats.resolve_exe(["../elsewhere/tools/x.cmd"], root)
    _project(tmp_path, monkeypatch, _fmt(check=json.dumps(["../escape.cmd"])))
    assert cli.main(["formats", "check", "--project", "lab", "--json"]) == 1
    (r,) = json.loads(capsys.readouterr().out)["projects"][0]["results"]
    assert r["status"] == "error" and "outside the repo" in r["detail"]


@pytest.mark.skipif(sys.platform != "win32", reason="a .cmd wrapper and its child: Windows")
def test_a_timeout_stops_a_cmd_wrapper_and_its_child(tmp_path, monkeypatch, capsys):
    root = _project(tmp_path, monkeypatch, _fmt(check=json.dumps(["slow.cmd"]), timeout=2))
    (root / "slow.cmd").write_text(f'@"{sys.executable}" -c "import time; time.sleep(30)"\r\n', encoding="utf-8")
    assert cli.main(["formats", "check", "--project", "lab", "--json"]) == 1
    (r,) = json.loads(capsys.readouterr().out)["projects"][0]["results"]
    assert r["status"] == "timeout" and r["seconds"] < 15


def test_a_file_it_cannot_read_runs_the_check_and_caches_nothing(tmp_path, monkeypatch, capsys):
    marker = tmp_path / "count"
    _project(tmp_path, monkeypatch, _fmt(check=json.dumps([sys.executable, "-c", COUNT, str(marker)])))

    def locked(path):
        raise PermissionError(path)
    monkeypatch.setattr(formats, "_file_sha", locked)
    for _ in range(2):
        assert cli.main(["formats", "check", "--project", "lab"]) == 0
    capsys.readouterr()
    assert marker.read_text(encoding="utf-8") == "xx" and not formats.cache_file("lab").exists()


def test_all_with_one_format_checks_the_projects_that_declare_it(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch, _fmt(check=_cmd("pass")), extra="other:\n  root: .\n")
    assert cli.main(["formats", "check", "--all", "--format", "orders", "--json"]) == 0
    assert [d["project"] for d in json.loads(capsys.readouterr().out)["projects"]] == ["lab"]
    assert cli.main(["formats", "check", "--all", "--format", "nope"]) == 1
    assert "no format 'nope'" in capsys.readouterr().out


def test_the_walk_starts_at_the_globs_folder(tmp_path):
    (tmp_path / "orders").mkdir()
    (tmp_path / "orders" / "a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "big").mkdir()
    (tmp_path / "big" / "a.json").write_text("{}", encoding="utf-8")
    assert formats._prefix("orders/**/*.json") == "orders" and formats._prefix("**/*.json") == ""
    assert formats.files(tmp_path, ["orders/*.json"]) == ["orders/a.json"]
    assert formats.files(tmp_path, ["**/a.json"]) == ["big/a.json", "orders/a.json"]
