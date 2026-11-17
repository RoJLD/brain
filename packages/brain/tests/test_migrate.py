"""brain migrate (wi-brain-migrate): step functions per format, a plan then an apply,
idempotent, a backup first, an applied-steps log, the first failure leaving the file as it was; brain update prints
the pending migrations. The engine ships no real step yet: each test registers its own, on a format whose version it
moves up for the test."""

import importlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from brain import cli, config, faults, migrate, migrations, paths, stateio, update
from conftest import git_init, run_git

SRC = Path(__file__).resolve().parents[1] / "src"
DOCS = [SRC.parent / "README.md", SRC.parent / "docs" / "formats.md"]


def rename_owner(data: dict) -> dict:
    """A test step: config.json identity.owner renamed identity.id (a rename bumps v)."""
    ident = dict(data.get("identity") or {})
    if "owner" in ident:
        ident["id"] = ident.pop("owner")
    return {**data, "identity": ident}


def add_seen(data: dict) -> dict:
    return {**data, "seen": True}


@pytest.fixture
def steps(monkeypatch):
    """A clean registry; ``bump(format, to)`` moves a format's known version up for the test, ``add(...)`` registers
    a step: both undone after the test."""
    monkeypatch.setattr(migrations, "STEPS", {})

    def bump(fid: str, to: int) -> None:
        old = migrations.BY_ID[fid]
        new = migrations.Format(old.id, old.path, old.store, to, old.owner, old.reads)
        monkeypatch.setattr(migrations, "FORMATS", tuple(new if f.id == fid else f for f in migrations.FORMATS))
        monkeypatch.setitem(migrations.BY_ID, fid, new)

    def add(fid: str, frm: int, fn, about: str = "a test step") -> migrations.Step:
        if migrations.BY_ID[fid].known() < frm + 1:
            bump(fid, frm + 1)
        return migrations.register(migrations.Step(fid, frm, frm + 1, fn, about))
    add.bump = bump
    return add


@pytest.fixture
def brain_root(tmp_path, monkeypatch):
    """Ada's brain in a git repo, config.json committed, found by --root (no BRAIN_CONFIG)."""
    monkeypatch.delenv("BRAIN_CONFIG", raising=False)
    monkeypatch.delenv("BRAIN_PROJECTS", raising=False)
    root = git_init(tmp_path / "ada-brain")
    data = {"v": 1, "identity": {"owner": "ada", "display_name": "Ada"}, "engine": {"pin": "v0.4.0"}}
    (root / "config.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "-m", "Ada's brain")
    return root


def tui(body: dict | None = None) -> Path:
    f = paths.brain_home() / "tui.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(body or {"cockpit": 1, "panels": {"a": 1}}, indent=1) + "\n", encoding="utf-8")
    return f


def run(*argv: str) -> int:
    return cli.main(list(argv))


# --- the registry ---

def test_each_format_is_its_owners_file_and_version():
    """A format's path and version are its reader's: a module that bumps its constant moves this table too."""
    for fmt in migrations.FORMATS:
        if fmt.repo:
            continue
        mod, attr = fmt.owner.rsplit(".", 1)
        f = getattr(importlib.import_module(mod), attr)()
        f = f / "state.json" if f.name in ("alerts", "memory-sync") else f
        assert f == paths.brain_home() / fmt.path, fmt.id
    consts = {"schedules": ("brain.schedule", "RECORD_V"), "alerts": ("brain.alerts", "STATE_V"),
              "vault": ("brain.vault", "STATE_V"), "vault-device": ("brain.vault", "DEVICE_V"),
              "usage": ("brain.usage", "LEDGER_V"), "cockpit": ("brain.cockpit", "STATE_V"),
              "memory-sync": ("brain.memory", "STATE_V"), "machine": ("brain.machine", "V"),
              "spool": ("brain.spool", "INDEX_V"), "session-archive": ("brain.sessionarchive", "INDEX_V")}
    assert set(consts) | {"config", "net", "outbox"} == set(migrations.BY_ID)
    for fid, (mod, attr) in consts.items():
        assert migrations.BY_ID[fid].known() == getattr(importlib.import_module(mod), attr), fid
    assert migrations.BY_ID["net"].known() == migrations.BY_ID["outbox"].known() == 1   # stateio.load's default
    assert migrations.BY_ID["config"].known() == 1
    from brain import classes
    assert all(f.store in classes.ENGINE_STORES for f in migrations.FORMATS if not f.repo)


def test_every_older_version_has_a_step_or_is_read_in_place_by_its_reader():
    """No gap in a chain: every version below a format's own has its step, or its reader declares it reads it."""
    for (fid, frm), s in migrations.STEPS.items():
        assert s.format == fid and s.frm == frm and s.to <= migrations.BY_ID[fid].known()
    for fmt in migrations.FORMATS:
        for v in range(1, fmt.known()):
            assert (fmt.id, v) in migrations.STEPS or v in fmt.reads, f"{fmt.id} v{v}: no step, not read in place"
        assert all(1 <= v < fmt.known() for v in fmt.reads), fmt.id


def test_every_step_lives_in_the_registry_module():
    """A step registered beside its reader exists only once that module is imported: brain migrate's own path
    imports few of them. So every step is in brain.migrations, which migrate, stateio and config import."""
    calls = re.compile(r"\b(?:migrations\.)?(?:step|register)\(\s*(?:Step\(|[\"'])")
    found = [f.relative_to(SRC).as_posix() for f in (SRC / "brain").rglob("*.py")
             if f.name != "migrations.py" and calls.search(f.read_text(encoding="utf-8"))]
    assert found == []
    r = _py("import sys\nfrom brain import cli\ncli.main(['migrate', '--plan'])\n"
            "print('brain.migrations' in sys.modules)")
    assert r.returncode == 0 and r.stdout.strip().endswith("True"), r.stdout + r.stderr
    for mod in ("stateio.py", "config.py", "migrate.py"):
        assert "from . import" in (SRC / "brain" / mod).read_text(encoding="utf-8") and \
            "migrations" in (SRC / "brain" / mod).read_text(encoding="utf-8"), mod


def test_every_stateio_reader_is_a_format_or_excluded_with_its_reason():
    owners = {f.owner.rsplit(".", 1)[0] for f in migrations.FORMATS if not f.repo}
    callers = {"brain." + f.stem for f in (SRC / "brain").glob("*.py")
               if "stateio.load(" in f.read_text(encoding="utf-8") and f.stem != "stateio"}
    assert callers - owners - set(migrations.EXCLUDED) == set()
    assert set(migrations.EXCLUDED) <= callers and all(len(why) > 20 for why in migrations.EXCLUDED.values())


@pytest.mark.parametrize("fid, frm, to, why", [
    ("nope", 1, 2, "not a format"), ("cockpit", 1, 3, "one version up"), ("cockpit", 0, 1, "one version up")])
def test_a_step_that_breaks_the_registrys_rules_is_refused(steps, fid, frm, to, why):
    with pytest.raises(ValueError, match=why):
        migrations.register(migrations.Step(fid, frm, to, add_seen, "x"))


def test_one_step_per_format_and_version(steps):
    steps("cockpit", 1, add_seen)
    with pytest.raises(ValueError, match="already has a step from v1"):
        migrations.step("cockpit", 1, "again")(add_seen)


# --- the plan ---

def test_nothing_pending_writes_nothing(brain_root, capsys):
    f = tui()
    before = sorted(p for p in paths.brain_home().rglob("*"))
    assert run("migrate", "--root", str(brain_root)) == 0
    out = capsys.readouterr().out
    assert out.startswith("brain migrate: nothing pending (2 file(s) read")
    assert sorted(p for p in paths.brain_home().rglob("*")) == before and f.is_file()
    assert run_git(brain_root, "status", "--porcelain") == ""


def test_the_plan_lists_each_step_from_to_and_writes_nothing(brain_root, steps, capsys):
    steps("config", 1, rename_owner, "identity.owner renamed identity.id")
    steps("config", 2, add_seen)
    f = tui()
    steps("cockpit", 1, add_seen)
    cfg_before, tui_before = (brain_root / "config.json").read_bytes(), f.read_bytes()
    assert run("migrate", "--root", str(brain_root), "--plan") == 0
    out = capsys.readouterr().out
    assert out.startswith("brain migrate: 3 step(s) pending on 2 file(s); nothing written")
    assert "pending  config.json (config) v1 -> v2  config-v1-v2: identity.owner renamed identity.id" in out
    assert "pending  config.json (config) v2 -> v3  config-v2-v3" in out
    assert "pending  $BRAIN_HOME/tui.json (cockpit) v1 -> v2  cockpit-v1-v2" in out
    assert (brain_root / "config.json").read_bytes() == cfg_before and f.read_bytes() == tui_before
    assert not migrate.log_file().exists()
    assert run("migrate", "--root", str(brain_root), "--json") == 0
    data = json.loads(capsys.readouterr().out)
    assert set(data) == {"engine", "log", "files", "pending", "unfinished"} and data["pending"] == 3
    cfg = data["files"][0]
    assert cfg["format"] == "config" and cfg["status"] == "pending" and cfg["v"] == 1 and cfg["known"] == 3
    assert [(s["from"], s["to"]) for s in cfg["steps"]] == [(1, 2), (2, 3)]


def test_a_newer_or_unreadable_file_is_listed_and_left_as_it_is(brain_root, steps, capsys):
    steps("cockpit", 1, add_seen)
    f = tui({"v": 7, "cockpit": 1})
    vault = paths.brain_home() / "vault" / "state.json"
    vault.parent.mkdir(parents=True)
    vault.write_text("{not json", encoding="utf-8")
    assert run("migrate", "--root", str(brain_root)) == 0
    out = capsys.readouterr().out
    assert "newer    $BRAIN_HOME/tui.json: written by a newer brain (v 7, this engine knows v 2): brain update" in out
    assert "unreadable $BRAIN_HOME/vault/state.json: is not JSON" in out
    before = f.read_bytes(), vault.read_bytes()
    assert run("migrate", "--root", str(brain_root), "--apply") == 0
    assert (f.read_bytes(), vault.read_bytes()) == before and "nothing to apply" in capsys.readouterr().out


def test_a_v_older_than_the_engines_with_no_step_is_read_in_place(steps, brain_root):
    """usage/sessions.json v1 under LEDGER_V 2: its reader upcasts it, nothing to migrate."""
    f = paths.brain_home() / "usage" / "sessions.json"
    f.parent.mkdir(parents=True)
    f.write_text('{"v": 1, "sessions": {}}\n', encoding="utf-8")
    (e,) = [e for e in migrate.plan(brain_root) if e.format == "usage"]
    assert e.status == "current" and e.v == 1 and e.known == 2 and e.steps == []


# --- the apply ---

def test_apply_backs_up_writes_once_logs_each_step_and_a_second_run_applies_nothing(brain_root, steps, capsys):
    steps("cockpit", 1, add_seen, "seen added")
    steps("cockpit", 2, lambda d: {**d, "panels": {**d["panels"], "b": 2}})
    f = tui({"cockpit": 1, "zeta": "kept", "panels": {"a": 1}})
    old = f.read_bytes()
    assert run("migrate", "--root", str(brain_root), "--apply") == 0
    out = capsys.readouterr().out
    assert "cockpit-v1-v2 v1 -> v2" in out and "cockpit-v2-v3 v2 -> v3" in out and "2 step(s) applied" in out
    text = f.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data == {"v": 3, "cockpit": 1, "zeta": "kept", "panels": {"a": 1, "b": 2}, "seen": True}
    assert text.startswith('{\n "v": 3,\n "cockpit": 1,\n "zeta": "kept"')   # v first, the order and indent kept
    (bak,) = [p for p in f.parent.iterdir() if p.name.startswith("tui.json.") and p.name.endswith(".bak")]
    assert bak.read_bytes() == old                                             # the backup beside it, as it was
    rows = migrate.applied()
    assert [(r["step"], r["from"], r["to"]) for r in rows] == [("cockpit-v1-v2", 1, 2), ("cockpit-v2-v3", 2, 3)]
    assert all(r["file"] == str(f) and r["backup"] == str(bak) and r["v"] == 1 for r in rows)
    log = migrate.log_file().read_bytes()
    assert run("migrate", "--root", str(brain_root), "--apply") == 0          # idempotent: the file says v3
    assert "nothing to apply" in capsys.readouterr().out
    assert migrate.log_file().read_bytes() == log and json.loads(f.read_text(encoding="utf-8")) == data
    from brain import classes
    assert classes.home_unknown([]) == []                                      # the log and the backup have a store


def test_a_step_that_fails_leaves_its_file_and_the_later_ones_as_they_were(brain_root, steps, capsys):
    def boom(data):
        raise KeyError("identity")
    steps("config", 1, boom)
    steps("cockpit", 1, add_seen)
    f = tui()
    cfg, before = brain_root / "config.json", (brain_root / "config.json").read_bytes()
    tui_before = f.read_bytes()
    assert run("migrate", "--root", str(brain_root), "--apply") == 1
    out = capsys.readouterr().out
    assert "failed   " in out and "step config-v1-v2 failed (KeyError" in out and "nothing further applied" in out
    assert cfg.read_bytes() == before and f.read_bytes() == tui_before and not migrate.log_file().exists()
    assert run_git(brain_root, "status", "--porcelain") == ""


def test_a_step_that_returns_no_record_or_one_json_cannot_hold_writes_nothing(brain_root, steps, capsys):
    f = tui()
    before = f.read_bytes()
    steps("cockpit", 1, lambda d: [d])
    assert run("migrate", "--root", str(brain_root), "--apply") == 1 and f.read_bytes() == before
    assert "returned a list, not a record" in capsys.readouterr().out
    migrations.STEPS.clear()
    steps("cockpit", 1, lambda d: {**d, "bad": {1, 2}})
    assert run("migrate", "--root", str(brain_root), "--apply", "--json") == 1 and f.read_bytes() == before
    data = json.loads(capsys.readouterr().out)
    assert data["applied"] == [] and "JSON cannot hold" in data["failed"]["why"]


def test_a_full_disk_leaves_the_file_whole_and_the_next_run_resumes(brain_root, steps, monkeypatch, capsys):
    steps("cockpit", 1, add_seen)
    f = tui()
    before = f.read_bytes()
    monkeypatch.setenv(faults.FAULT_ENV, "write@*tui.json:disk-full")
    assert run("migrate", "--root", str(brain_root), "--apply") == 1
    assert "the write failed (OSError" in capsys.readouterr().out
    assert f.read_bytes() == before and not list(f.parent.glob("*.tmp")) and migrate.applied() == []
    (cut,) = migrate.unfinished()                                              # the started line names the copy
    assert Path(cut["backup"]).read_bytes() == before and cut["from"] == 1 and cut["to"] == 2
    monkeypatch.delenv(faults.FAULT_ENV)
    assert run("migrate", "--root", str(brain_root)) == 0
    assert f"cut      {f}: a run stopped after its backup" in capsys.readouterr().out
    assert run("migrate", "--root", str(brain_root), "--apply") == 0
    assert json.loads(f.read_text(encoding="utf-8"))["v"] == 2 and len(migrate.applied()) == 1
    assert migrate.unfinished() == []


KILL = """
import sys
from brain import cli, migrations
old = migrations.BY_ID["cockpit"]
new = migrations.Format(old.id, old.path, old.store, 2, old.owner, old.reads)
migrations.FORMATS = tuple(new if f.id == "cockpit" else f for f in migrations.FORMATS)
migrations.BY_ID["cockpit"] = new
migrations.register(migrations.Step("cockpit", 1, 2, lambda d: {**d, "seen": True}, "a test step"))
sys.exit(cli.main(["migrate", "--apply"]))
"""


def _py(code: str, **env) -> subprocess.CompletedProcess:
    e = {**os.environ, "PYTHONPATH": str(SRC), **env}
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=e, timeout=120)


def test_a_run_killed_before_the_move_leaves_the_file_as_it_was_then_resumes(brain_home, monkeypatch):
    monkeypatch.setenv("BRAIN_CONFIG", str(brain_home / "no-config.json"))
    f = tui()
    before = f.read_bytes()
    r = _py(KILL, BRAIN_FAULT="write@*tui.json:killed")
    assert r.returncode == faults.KILLED_EXIT, r.stdout + r.stderr
    assert f.read_bytes() == before and migrate.applied() == []                # never half a file, no step logged
    (cut,) = migrate.unfinished()                                              # but its backup's path is on record
    assert Path(cut["backup"]).read_bytes() == before
    r = _py(KILL)
    assert r.returncode == 0 and "1 step(s) applied" in r.stdout, r.stdout + r.stderr
    assert json.loads(f.read_text(encoding="utf-8"))["seen"] is True and len(migrate.applied()) == 1


def test_a_file_another_command_writes_meanwhile_is_never_written_over(brain_root, steps, monkeypatch):
    steps("cockpit", 1, add_seen)
    f = tui()
    (e,) = [e for e in migrate.plan(brain_root) if e.format == "cockpit"]
    f.write_text('{"v": 2, "cockpit": 1}\n', encoding="utf-8")   # migrated since the plan, by another run
    with pytest.raises(migrate.Failed, match="changed since the plan"):
        migrate.apply_one(e)
    tui()
    backup = migrate._backup

    def racing(fmt, path):   # another command writes the file between the read and the write
        path.write_text('{"cockpit": 1, "panels": {"other": 1}}\n', encoding="utf-8")
        return backup(fmt, path)
    monkeypatch.setattr(migrate, "_backup", racing)
    with pytest.raises(migrate.Failed, match="changed while it was migrated"):
        migrate.apply_one(e)
    assert json.loads(f.read_text(encoding="utf-8")) == {"cockpit": 1, "panels": {"other": 1}}


# --- the repo's file: config.json ---

def test_config_json_is_migrated_in_its_work_tree_backed_up_outside_it(brain_root, steps, capsys):
    steps("config", 1, rename_owner)
    cfg = brain_root / "config.json"
    old = cfg.read_bytes()
    assert run("--root", str(brain_root), "migrate", "--apply") == 0
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["v"] == 2 and data["identity"] == {"id": "ada", "display_name": "Ada"}
    assert cfg.read_text(encoding="utf-8").startswith('{\n  "v": 2,\n  "identity"')   # its indent kept
    assert run_git(brain_root, "status", "--porcelain").strip() == "M config.json"     # no .bak in the repo
    (bak,) = list(paths.backup_dir().rglob("config.json.*.bak"))
    assert bak.read_bytes() == old
    assert migrate.applied()[0]["step"] == "config-v1-v2"
    capsys.readouterr()


def test_config_json_with_changes_not_committed_is_refused(brain_root, steps, capsys):
    steps("config", 1, rename_owner)
    cfg = brain_root / "config.json"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace('"Ada"', '"Ada L."'), encoding="utf-8")
    before = cfg.read_bytes()
    assert run("migrate", "--root", str(brain_root)) == 0
    assert "blocked  config.json: config.json has changes not committed: commit them first" in capsys.readouterr().out
    assert run("migrate", "--root", str(brain_root), "--apply") == 1 and cfg.read_bytes() == before
    assert not list(paths.backup_dir().rglob("config.json.*.bak"))


def test_a_git_status_that_fails_blocks_config_json_and_takes_no_index_lock(brain_root, steps, monkeypatch, capsys):
    """Fail closed: a repo git refuses to read (another owner's) or no git at all is never migrated blind."""
    steps("config", 1, rename_owner)
    seen = []
    real = subprocess.run

    def refused(cmd, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 128, "", "fatal: detected dubious ownership in repository\n")
    monkeypatch.setattr(migrate.subprocess, "run", refused)
    (e,) = [e for e in migrate.plan(brain_root) if e.format == "config"]
    assert e.status == "pending" and e.why.startswith("git status failed (fatal: detected dubious ownership")
    assert seen[0][:2] == ["git", "--no-optional-locks"]

    def missing(cmd, **kw):
        raise FileNotFoundError("git")
    monkeypatch.setattr(migrate.subprocess, "run", missing)
    assert migrate.plan(brain_root)[0].why.startswith("git status failed (FileNotFoundError)")
    before = (brain_root / "config.json").read_bytes()
    assert run("migrate", "--root", str(brain_root), "--apply") == 1
    assert (brain_root / "config.json").read_bytes() == before
    monkeypatch.setattr(migrate.subprocess, "run", real)
    assert migrate.uncommitted(paths.brain_home() / "x.json") == ""            # outside a work tree: no git asked


def test_the_plan_and_the_apply_give_the_order_across_machines(brain_root, steps, capsys):
    steps("config", 1, rename_owner)
    assert run("migrate", "--root", str(brain_root)) == 0
    order = ("then     commit the migrated config.json once every machine of this brain runs an engine that reads "
             "v 2 (its pin moved and installed): a machine behind fails closed until it updates")
    assert order in capsys.readouterr().out
    assert run("migrate", "--root", str(brain_root), "--apply") == 0
    assert order in capsys.readouterr().out


# --- the command line ---

def test_the_parents_flags_after_the_subcommand_and_the_exclusive_modes(brain_root, steps, capsys):
    steps("config", 1, rename_owner)
    assert run("migrate", "--root", str(brain_root), "--plan") == 0
    after = capsys.readouterr().out
    assert run("--root", str(brain_root), "migrate", "--plan") == 0
    assert capsys.readouterr().out == after and "config-v1-v2" in after
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["migrate", "--plan", "--apply"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit):   # the brain's and the machine's files: no project's
        cli.build_parser().parse_args(["migrate", "--project", "lab"])


def _doc_lines() -> list[str]:
    """Every ``brain migrate ...`` command the docs give, in a code span or a block."""
    out = []
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        out += [m.strip() for m in re.findall(r"`(brain migrate[^`]*)`", text)]
        out += [m.strip() for m in re.findall(r"^(brain migrate[^\n#]*)", text, re.M)]
    return sorted(set(out))


def test_every_documented_migrate_line_passes_the_real_parser():
    lines = _doc_lines()
    assert {"brain migrate --plan", "brain migrate --apply"} <= set(lines), lines
    for line in lines:
        words = shlex.split(line)[1:]
        if "|" in words or any(w.startswith("[") for w in words):   # a usage line: its forms one by one
            continue
        ns = cli.build_parser().parse_args(words)
        assert ns.cmd == "migrate", line


def test_the_usage_and_help_name_both_modes():
    from brain.commands import migrate as cmd
    usage = " ".join(cmd.USAGE.split())
    assert "brain migrate [--plan | --apply [--dev-engine]] [--json]" in usage and "$BRAIN_HOME/migrate/applied.jsonl" in usage


# --- brain update says what is pending ---

def test_brain_update_prints_the_pending_migrations_read_only(brain_root, steps):
    info = {"installed": "0.5.0", "latest": "0.5.0", "repo": "ada/engine", "newer": False}
    assert update.plan(info, brain_root)["migrations"] == []
    assert not any("Migrations pending" in line for line in update.lines(update.plan(info, brain_root)))
    steps("config", 1, rename_owner)
    before = (brain_root / "config.json").read_bytes()
    p = update.plan(info, brain_root)
    assert p["migrations"] == [{"format": "config", "file": str(brain_root / "config.json"), "from": 1, "to": 2}]
    (line,) = [x for x in update.lines(p) if "Migrations pending" in x]
    assert line == ("Migrations pending for brain 0.5.0's formats: config.json v1 -> v2 (brain migrate --plan, "
                    "then --apply; brain update applies none)")
    assert (brain_root / "config.json").read_bytes() == before and not migrate.log_file().exists()


def test_a_migrate_that_cannot_plan_never_fails_the_update(monkeypatch):
    def broken(root=None):
        raise RuntimeError("no")
    monkeypatch.setattr(migrate, "pending", broken)
    assert update.pending_migrations() == []


# --- a store as the previous releases wrote it ---

def test_a_frozen_old_store_plans_nothing_and_migrates_with_a_registered_step(tmp_path, monkeypatch, steps, capsys):
    """Each frozen brain (tests/fixtures/stores/<tag>): today's engine finds nothing to migrate; with a step of its
    config.json, the apply migrates it, keeps every other key, and a second run applies nothing."""
    from test_old_stores import TAGS, frozen_copy
    assert TAGS
    for tag in TAGS:
        root = frozen_copy(tmp_path / tag, tag, monkeypatch)
        assert config.config_file(root) == root / "config.json"
        assert run("migrate", "--root", str(root)) == 0
        assert capsys.readouterr().out.startswith("brain migrate: nothing pending"), tag
    steps("config", 1, rename_owner)
    for tag in TAGS:
        root = tmp_path / tag / f"old-brain-{tag}"
        before = json.loads((root / "config.json").read_text(encoding="utf-8"))
        assert run("migrate", "--root", str(root), "--apply") == 0, capsys.readouterr().out
        after = json.loads((root / "config.json").read_text(encoding="utf-8"))
        assert after["v"] == 2 and after["identity"]["id"] == before["identity"]["owner"], tag
        assert {k: v for k, v in after.items() if k not in ("v", "identity")} == \
            {k: v for k, v in before.items() if k not in ("v", "identity")}
        assert run("migrate", "--root", str(root), "--apply") == 0
        assert "nothing to apply" in capsys.readouterr().out
    assert len(migrate.applied()) == len(TAGS)


# --- the readers: a file is never saved at a version its data does not have ---

def views(data: dict) -> dict:
    """A test step of tui.json: panels renamed views."""
    out = dict(data)
    out["views"] = out.pop("panels", {})
    return out


def test_a_reader_loads_an_older_file_in_the_shape_its_save_writes_the_v_of(steps):
    steps("cockpit", 1, views)
    f = tui({"cockpit": 1, "panels": {"a": 1}})
    st = stateio.load(f, known=2)
    assert st.status == "ok" and st.v is None and st.upcast == 2                # no v: version 1
    assert st.data == {"cockpit": 1, "views": {"a": 1}}                        # the new shape, in memory only
    assert json.loads(f.read_text(encoding="utf-8")) == {"cockpit": 1, "panels": {"a": 1}}
    st.data["views"]["b"] = 2
    stateio.save(st)                                                           # the owner's own save, no migrate run
    assert json.loads(f.read_text(encoding="utf-8")) == {"v": 2, "cockpit": 1, "views": {"a": 1, "b": 2}}
    (e,) = [e for e in migrate.plan() if e.format == "cockpit"]
    assert e.status == "current" and e.v == 2


def test_a_writer_that_loaded_before_the_apply_saves_the_migrated_shape(brain_root, steps, capsys):
    steps("cockpit", 1, views)
    f = tui({"cockpit": 1, "panels": {"a": 1}})
    held = stateio.load(f, known=2)                                            # the cockpit, open meanwhile
    assert run("migrate", "--root", str(brain_root), "--apply") == 0
    assert json.loads(f.read_text(encoding="utf-8")) == {"v": 2, "cockpit": 1, "views": {"a": 1}}
    held.data["views"]["c"] = 3
    stateio.save(held)                                                         # never undoes the migration
    assert json.loads(f.read_text(encoding="utf-8")) == {"v": 2, "cockpit": 1, "views": {"a": 1, "c": 3}}


def test_a_record_with_its_v_unwritten_gets_it_once_carried_past_1(steps):
    """schedules/installed.json keeps v 1 unwritten (an older engine reads every key as a name): a step to 2 writes
    it, else the file would read as v 1 again."""
    steps("schedules", 1, lambda d: {**d, "ok": {"moved": True}})
    f = paths.brain_home() / "schedules" / "installed.json"
    f.parent.mkdir(parents=True)
    f.write_text('{"nightly": {"task": "x"}}\n', encoding="utf-8")
    st = stateio.load(f, known=2)
    assert st.status == "ok" and st.upcast == 2 and st.data["ok"] == {"moved": True}
    stateio.save(st, write_v=False)
    assert json.loads(f.read_text(encoding="utf-8"))["v"] == 2


def test_a_gap_in_the_chain_is_behind_never_current(brain_root, steps, capsys):
    """known 3 with only the step v2 -> v3: a v1 file is behind, read-only for its reader, refused by --apply."""
    steps.bump("cockpit", 3)
    migrations.register(migrations.Step("cockpit", 2, 3, add_seen, "v2 -> v3"))
    f = tui({"cockpit": 1, "panels": {"a": 1}})
    before = f.read_bytes()
    st = stateio.load(f, known=3)
    assert st.status == "behind" and not st.writable and st.refused
    with pytest.raises(stateio.StateError, match="no migration of this engine reaches v 3"):
        stateio.save(st)
    assert run("migrate", "--root", str(brain_root)) == 0
    assert "behind   $BRAIN_HOME/tui.json: v 1 has no migration to v 3" in capsys.readouterr().out
    assert run("migrate", "--root", str(brain_root), "--apply") == 1 and f.read_bytes() == before
    assert "failed" in capsys.readouterr().out


def test_a_step_that_fails_on_load_leaves_the_file_read_only(steps):
    def boom(data):
        raise KeyError("panels")
    steps("cockpit", 1, boom)
    f = tui()
    st = stateio.load(f, known=2)
    assert st.status == "behind" and "step cockpit-v1-v2 failed (KeyError" in st.why and not st.writable


def test_config_json_is_read_in_its_new_shape_and_a_gap_fails_closed(brain_root, steps):
    steps("config", 1, rename_owner)
    cfg = config.load(brain_root)
    assert cfg.data["v"] == 2 and cfg.data["identity"]["id"] == "ada" and cfg.error == ""
    assert json.loads((brain_root / "config.json").read_text(encoding="utf-8"))["v"] == 1   # the file untouched
    migrations.STEPS.clear()
    steps.bump("config", 3)
    migrations.register(migrations.Step("config", 2, 3, add_seen, "v2 -> v3"))
    cfg = config.load(brain_root)
    assert "no migration of this engine reaches v 3" in cfg.error
    assert config.unexpected(cfg)                                              # the guards cannot trust it


def test_the_integrity_sidecar_is_rewritten_with_the_migrated_file(brain_root, steps, monkeypatch, capsys):
    import hashlib
    monkeypatch.setenv(stateio.INTEGRITY_ENV, "1")
    f = paths.brain_home() / "tui.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    stateio.save(stateio.load(f), {"cockpit": 1, "panels": {"a": 1}})
    side = stateio.sidecar(f)
    assert side.is_file()
    steps("cockpit", 1, views)
    assert run("migrate", "--root", str(brain_root), "--apply") == 0
    meta = json.loads(side.read_text(encoding="utf-8"))
    assert meta["sha256"] == hashlib.sha256(f.read_bytes()).hexdigest() and meta["size"] == f.stat().st_size
    assert stateio.load(f, known=2).status == "ok"


# --- a dev engine and the default home ---

def test_a_dev_engine_never_migrates_the_default_home_unless_told(brain_root, steps, monkeypatch, capsys, tmp_path):
    from brain import skew
    home = tmp_path / "home"
    with monkeypatch.context() as m:
        m.setattr(migrate.Path, "home", classmethod(lambda cls: home))
        dev = skew.Engine("brain", "0.5.0", folder=str(tmp_path / "checkout" / "src" / "brain"))
        m.setattr(skew, "engine_of", lambda dist, module: dev)
        assert migrate.dev_refusal({}).startswith(f"this engine runs from {dev.folder}, not an installed release")
        assert migrate.dev_refusal({"BRAIN_HOME": str(tmp_path / "test-home")}) == ""   # a home of its own
        clone = skew.Engine("brain", "0.5.0", folder=str(home / ".brain" / "engine" / "v0.5.0" / "src" / "brain"))
        m.setattr(skew, "engine_of", lambda dist, module: clone)
        assert migrate.dev_refusal({}) == ""                                   # a release's clone is no dev engine
        m.setattr(skew, "engine_of", lambda dist, module: skew.Engine("brain", "0.5.0", "v0.5.0", "0" * 40))
        assert migrate.dev_refusal({}) == ""                                   # installed from its tag
    steps("cockpit", 1, add_seen)
    f = tui()
    before = f.read_bytes()
    with monkeypatch.context() as m:
        m.setattr(migrate, "dev_refusal", lambda env=None: "this engine runs from a checkout")
        assert run("migrate", "--root", str(brain_root), "--apply") == 2 and f.read_bytes() == before
        assert "pass --dev-engine" not in capsys.readouterr().out
        assert run("migrate", "--root", str(brain_root), "--plan") == 0        # the plan never asks
        assert run("migrate", "--root", str(brain_root), "--apply", "--dev-engine") == 0
    assert json.loads(f.read_text(encoding="utf-8"))["seen"] is True


# --- the messages say what happened ---

def test_a_file_that_cannot_be_read_is_said_read_only_not_set_aside(tmp_path):
    folder = tmp_path / "a-folder.json"
    folder.mkdir()                                                             # read_bytes: an OSError, as a lock
    raw, why = migrate._read(folder)
    assert raw is None and why.startswith("cannot be read (") and "read-only for its own command" in why
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    assert "its own command sets it aside" in migrate._read(bad)[1]


def test_a_backup_that_fails_says_nothing_of_its_own_and_leaves_no_copy(steps, brain_root, monkeypatch, capsys):
    steps("cockpit", 1, add_seen)
    f = tui()
    real = os.replace

    def full(src, dst):
        if str(dst).endswith(".bak"):
            raise OSError(28, "No space left on device")
        return real(src, dst)
    monkeypatch.setattr(stateio.os, "replace", full)
    assert run("migrate", "--root", str(brain_root), "--apply") == 1
    out, err = capsys.readouterr()
    assert "no backup could be taken: nothing written" in out and "written without one" not in err
    assert not [p for p in f.parent.iterdir() if p.name.endswith(".tmp")]
