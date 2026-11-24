"""brain render --target cursor --home: the machine-wide MCP servers (those of the packs without projects) merged into
the user-level ~/.cursor/mcp.json behind an explicit flag (wi-brain-render-user-mcp). Every test runs on a temporary
home folder (HOME and USERPROFILE), never the owner's."""

import json
import stat
from pathlib import Path

import pytest
import test_render
from brain import cli, render
from test_render import MCP, PACKS, write

ada = test_render.ada   # the invented brain's fixture (test_render), shared

MACHINE_PACK = "  brain-mcp:\n    mcp: [brain]\n"
MACHINE_SERVER = "  brain:\n    transport: stdio\n    command: brain\n    args: [mcp, serve]\n"
BRAIN_ENTRY = {"type": "stdio", "command": "brain", "args": ["mcp", "serve"]}


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A temporary home folder: Path.home() reads USERPROFILE on Windows, HOME elsewhere; both point here."""
    h = tmp_path / "user-home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("USERPROFILE", str(h))
    assert Path.home().resolve() == h.resolve()
    return h


@pytest.fixture
def machine(ada, home):
    """Ada's brain with a pack that applies to every project (no projects) and names one server: machine-wide."""
    write(ada / "source", {"packs.yaml": PACKS + MACHINE_PACK, "mcp.yaml": MCP + MACHINE_SERVER})
    return ada


def _file(home: Path) -> Path:
    return home / ".cursor" / "mcp.json"


def test_the_machine_wide_servers_are_those_of_the_packs_without_projects(machine):
    r = render.render(machine, "cursor", home=True)
    assert [(o.base, o.rel, o.merge) for o in r.outputs] == [("user", ".cursor/mcp.json", ("mcpServers",))]
    assert json.loads(r.outputs[0].text) == {"brain": BRAIN_ENTRY}   # ops's graph and sidecar name a project: per repo


def test_the_plan_names_the_home_file_and_its_entries_and_write_leaves_it(machine, home, capsys):
    assert render.main(machine, "cursor", project="demo", project_root=machine) == 0
    out = capsys.readouterr().out
    assert f"new      {_file(home)}  [mcpServers]  brain: add" in out
    assert "--write never writes the home folder): brain render --target cursor --home --write" in out
    assert render.main(machine, "cursor", project="demo", project_root=machine, do_write=True) == 0
    assert not _file(home).exists()   # --write alone: the repo's files only
    assert json.loads((machine / ".cursor" / "mcp.json").read_text(encoding="utf-8"))["mcpServers"]["brain"] \
        == BRAIN_ENTRY   # the per-repo render is unchanged: every project's pack is in each repo too


def test_home_write_merges_its_entries_keeps_the_rest_and_runs_once(machine, home, capsys):
    mine = {"mcpServers": {"mine": {"command": "x", "args": ["--a"]}}, "other": {"k": [1, 2]}}
    text = json.dumps(mine, indent=2) + "\n"
    write(home, {".cursor/mcp.json": text})
    assert render.main(machine, "cursor", home=True) == 0
    assert "brain: add" in capsys.readouterr().out
    assert render.main(machine, "cursor", home=True, do_write=True) == 0
    assert "written" in capsys.readouterr().out
    after = _file(home).read_bytes()
    data = json.loads(after)
    assert data == {"mcpServers": {"mine": mine["mcpServers"]["mine"], "brain": BRAIN_ENTRY}, "other": {"k": [1, 2]}}
    assert after.decode("utf-8") == json.dumps(data, indent=2) + "\n"   # a file in this form keeps every other byte
    stamp = _file(home).stat().st_mtime_ns
    assert render.main(machine, "cursor", home=True, do_write=True) == 0   # the second run: a no-op
    assert "written" not in capsys.readouterr().out
    assert _file(home).read_bytes() == after and _file(home).stat().st_mtime_ns == stamp
    assert render.main(machine, "cursor", home=True, check=True) == 0
    assert [p.name for p in _file(home).parent.iterdir()] == ["mcp.json"]   # no temporary file left


def test_a_missing_file_is_created_with_its_folder(machine, home):
    assert render.main(machine, "cursor", home=True, check=True) == 1
    assert render.main(machine, "cursor", home=True, do_write=True) == 0
    assert json.loads(_file(home).read_text(encoding="utf-8")) == {"mcpServers": {"brain": BRAIN_ENTRY}}
    assert _file(home).read_bytes().endswith(b"}\n")


def test_a_changed_entry_keeps_its_place_and_the_file_its_format(machine, home, capsys):
    text = ('﻿{\r\n    "mcpServers": {\r\n        "brain": {\r\n            "command": "old"\r\n        },\r\n'
            '        "later": {\r\n            "command": "café"\r\n        }\r\n    }\r\n}')   # BOM, CRLF, 4, no EOL
    _file(home).parent.mkdir()
    _file(home).write_bytes(text.encode("utf-8"))
    assert render.main(machine, "cursor", home=True) == 0
    assert "brain: change" in capsys.readouterr().out
    assert render.main(machine, "cursor", home=True, do_write=True) == 0
    raw = _file(home).read_bytes().decode("utf-8")
    assert raw.startswith('﻿{\r\n    "mcpServers": {\r\n        "brain": {\r\n            "type": "stdio"')
    assert "\n" not in raw.replace("\r\n", "") and not raw.endswith("\n") and "café" in raw
    assert list(json.loads(raw[1:])["mcpServers"]) == ["brain", "later"]


def test_entries_equal_in_another_key_order_are_the_same(machine, home):
    write(home, {".cursor/mcp.json": json.dumps({"mcpServers": {"brain": dict(reversed(BRAIN_ENTRY.items()))}})})
    before = _file(home).read_bytes()
    assert render.main(machine, "cursor", home=True, do_write=True) == 0
    assert _file(home).read_bytes() == before


@pytest.mark.parametrize("text, why", [
    ('{"mcpServers": {}, // a comment\n}', "not readable JSON"),
    ('{"mcpServers": {"a": {}},}', "not readable JSON"),
    ('{"mcpServers": {}, "mcpServers": {"x": {}}}', "twice"),
    ('[1, 2]', "not a JSON object"),
    ('{"mcpServers": [1]}', "mcpServers is not an object"),
])
def test_a_file_it_cannot_read_is_refused_and_never_overwritten(machine, home, capsys, text, why):
    write(home, {".cursor/mcp.json": text})
    assert render.main(machine, "cursor", home=True, do_write=True) == 1
    got = capsys.readouterr()
    assert why in got.out and "not merged" in got.out and "left as they are" in got.err
    assert _file(home).read_text(encoding="utf-8") == text
    assert render.main(machine, "cursor", home=True, check=True) == 1
    got = capsys.readouterr()   # --write cannot fix it: the check never sends the owner there
    assert "--home --write" not in got.out + got.err and "left as they are" in got.err
    assert render.main(machine, "cursor", home=True, as_json=True) == 1   # the plan of --home fails too
    data = json.loads(capsys.readouterr().out)   # one JSON document on stdout, the refusal on stderr
    assert data["files"][0]["state"] == "unreadable" and why in data["files"][0]["what"]
    # the repo's plan still runs: the home row says why, and it exits 0
    assert render.main(machine, "cursor", project="demo", project_root=machine) == 0
    assert f"unreadable {_file(home)}" in capsys.readouterr().out


def test_a_file_not_utf8_is_refused(machine, home, capsys):
    _file(home).parent.mkdir()
    _file(home).write_bytes(b'{"mcpServers": {"x": {"command": "\xe9"}}}')
    assert render.main(machine, "cursor", home=True, do_write=True) == 1
    assert "not UTF-8" in capsys.readouterr().out
    assert _file(home).read_bytes() == b'{"mcpServers": {"x": {"command": "\xe9"}}}'


def test_a_failed_rename_leaves_the_file_and_no_temporary_one(machine, home, monkeypatch, capsys):
    write(home, {".cursor/mcp.json": '{"mcpServers": {}}\n'})

    def busy(src, dst):
        raise PermissionError(13, "in use")
    monkeypatch.setattr(render.os, "replace", busy)
    assert render.main(machine, "cursor", home=True, do_write=True) == 1
    assert "not written (in use)" in capsys.readouterr().out
    assert _file(home).read_text(encoding="utf-8") == '{"mcpServers": {}}\n'
    assert [p.name for p in _file(home).parent.iterdir()] == ["mcp.json"]


def test_a_read_only_file_is_refused_or_replaced_and_no_temporary_file_is_left(machine, home, capsys):
    """Review of #316: the temporary file took the file's read-only mode, so a failed rename (Windows) left it."""
    write(home, {".cursor/mcp.json": '{"mcpServers": {}}\n'})
    _file(home).chmod(stat.S_IREAD)
    try:
        rc = render.main(machine, "cursor", home=True, do_write=True)
        if rc:   # Windows: a read-only file is not replaced
            assert "not written" in capsys.readouterr().out
            assert _file(home).read_text(encoding="utf-8") == '{"mcpServers": {}}\n'
        else:    # POSIX: the folder's permission decides, the file is replaced
            assert json.loads(_file(home).read_text(encoding="utf-8"))["mcpServers"] == {"brain": BRAIN_ENTRY}
        assert [p.name for p in _file(home).parent.iterdir()] == ["mcp.json"]
    finally:
        _file(home).chmod(stat.S_IREAD | stat.S_IWRITE)


def test_a_symbolic_link_stays_one(machine, home, tmp_path):
    real = tmp_path / "dotfiles" / "cursor-mcp.json"
    write(real.parent, {real.name: '{"mcpServers": {}}\n'})
    _file(home).parent.mkdir()
    try:
        _file(home).symlink_to(real)
    except OSError:
        pytest.skip("no symlinks here (Windows without the privilege)")
    assert render.main(machine, "cursor", home=True, do_write=True) == 0
    assert _file(home).is_symlink()
    assert json.loads(real.read_text(encoding="utf-8")) == {"mcpServers": {"brain": BRAIN_ENTRY}}


def test_text_that_needs_escaping_round_trips(machine, home):
    odd = 'a "quoted" 100% $HOME &amp; <x>\nline'
    server = f"  brain:\n    transport: stdio\n    command: brain\n    args: [mcp, serve, {json.dumps(odd)}]\n"
    write(machine / "source", {"mcp.yaml": MCP + server})
    write(home, {".cursor/mcp.json": json.dumps({"mcpServers": {}, "note": odd}, indent=2) + "\n"})
    assert render.main(machine, "cursor", home=True, do_write=True) == 0
    data = json.loads(_file(home).read_text(encoding="utf-8"))
    assert data["mcpServers"]["brain"]["args"][-1] == odd and data["note"] == odd
    assert render.main(machine, "cursor", home=True, check=True) == 0


def test_no_machine_wide_server_writes_nothing(ada, home, capsys):
    assert render.main(ada, "cursor", home=True, do_write=True) == 0
    assert "no machine-wide MCP server" in capsys.readouterr().out
    assert not _file(home).exists()


def test_check_and_sync_never_read_the_home_folder(machine, home):
    write(home, {".cursor/mcp.json": "not json"})
    render.main(machine, "cursor", project="demo", project_root=machine, do_write=True)
    followed = render.rendered(machine, "demo", machine)
    assert [t for t, *_ in followed] == ["agents", "cursor"]
    assert all(row["base"] != "user" for _, _, rows, _ in followed for row in rows)
    assert render.keep_current(machine, "demo", fix=False) == []


@pytest.mark.parametrize("target, why", [("claude", "writes no file in the home folder"),
                                         ("hermes", "added by hand")])
def test_home_on_a_target_without_a_home_file_is_refused(machine, capsys, target, why):
    assert render.main(machine, target, home=True) == 1
    assert why in capsys.readouterr().out


def test_brain_render_home_cli(machine, home, tmp_path, monkeypatch, capsys):
    elsewhere = tmp_path / "elsewhere"   # no registered project here: --home needs none
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    base = ["--root", str(machine), "render", "--target", "cursor", "--home"]
    assert cli.main(base + ["--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["home"] is True and data["project"] is None
    assert [(f["file"], f["state"], f["entries"]) for f in data["files"]] == [(str(_file(home)), "new",
                                                                                {"brain": "add"})]
    assert cli.main(base + ["--write"]) == 0
    assert json.loads(_file(home).read_text(encoding="utf-8"))["mcpServers"] == {"brain": BRAIN_ENTRY}
    assert cli.main(base + ["--check"]) == 0
    assert cli.main(base + ["--repo", str(machine)]) == 2
    assert cli.main(["--root", str(machine), "--project", "demo", "render", "--target", "cursor", "--home",
                     "--check"]) == 0   # the parent's --project is accepted and changes nothing


def test_out_renders_the_home_file_into_the_dry_run_folder(machine, home, tmp_path):
    dry = tmp_path / "dry"
    assert render.main(machine, "cursor", home=True, out=dry, do_write=True) == 0
    assert json.loads((dry / "home" / ".cursor" / "mcp.json").read_text(encoding="utf-8")) == \
        {"mcpServers": {"brain": BRAIN_ENTRY}}
    assert not _file(home).exists()
