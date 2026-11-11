"""installer/stranger_test.py, the stranger test's harness (wi-brain-stranger-install-test): its isolation and its leak
scan; the install and the scenario themselves run against a fresh venv (see the script's docstring)."""

import importlib.util
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "installer" / "stranger_test.py"


@pytest.fixture(scope="module")
def st():
    spec = importlib.util.spec_from_file_location("stranger_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_environment_is_a_strangers(st, tmp_path, monkeypatch):
    """A home of its own, none of the caller's brain variables, and a PATH with the venv first and no docker."""
    for k, v in {"BRAIN_CONFIG": "x", "BRAIN_PERSONAL": "x", "CLAUDE_BRAIN_DIR": "x", "BRAIN_PROJECTS": "x",
                 "GH_TOKEN": "x"}.items():
        monkeypatch.setenv(k, v)
    scripts = tmp_path / "venv" / "bin"
    env = st.isolated_env(tmp_path, scripts)
    assert not {"BRAIN_CONFIG", "BRAIN_PERSONAL", "CLAUDE_BRAIN_DIR", "BRAIN_PROJECTS", "GH_TOKEN"} & set(env)
    home = tmp_path / "home"
    assert env["HOME"] == env["USERPROFILE"] == str(home) and env["BRAIN_HOME"] == str(home / ".brain")
    assert env["PATH"].split(os.pathsep)[0] == str(scripts)
    gitconfig = Path(env["GIT_CONFIG_GLOBAL"]).read_text(encoding="utf-8")
    assert f"name = {st.OWNER}" in gitconfig and "example.invalid" in gitconfig


def test_leaks_are_whole_words_in_outputs_and_files(st):
    deny = st.parse_deny(["people:Grace Example", "repos:secret-lab"])
    texts = {"output of status": "waiting on grace example", "notes/x.md": "the secret-labs and secret_lab",
             "README.md": "nothing"}
    assert st.leaks(texts, deny) == [{"category": "people", "term": "Grace Example", "where": "output of status"}]


def test_a_deny_needs_its_category(st):
    with pytest.raises(SystemExit, match="category:term"):
        st.parse_deny(["Grace"])


def test_the_hooks_bash_is_never_wsls(st):
    """On Windows a bare bash is WSL's System32 one, found before the PATH: the harness names Git's."""
    assert "system32" not in st.git_bash().lower()


# --- the upgrade test (--upgrade-from, wi-brain-upgrade-test) -------------------------------------------------------

def test_every_registered_format_has_a_place_in_the_upgrade_test(st, tmp_path):
    """A format registered with its fixtures (tests/fixtures/formats/<format>/v<N>/) and no place in where() would be
    neither written by the older engine nor read back by it: the upgrade test must grow with the registry."""
    names = {fmt for fmt, _ in st.formats()}
    assert {"ar", "config", "ddr", "event", "packs", "permissions", "projects", "sr", "template"} <= names
    assert names <= set(st.where(tmp_path / "brain", tmp_path / "home"))
    for fmt, v in st.formats():
        assert st.fixture(fmt, "older", v).is_file() and st.fixture(fmt, "newer", v).is_file()


def test_a_missing_format_fails_the_formats_step(st, tmp_path):
    root, home = tmp_path / "brain", tmp_path / "home"
    (root / "records" / "ar").mkdir(parents=True)
    (root / "records" / "ar" / "2026-11.jsonl").write_text("{}\n", encoding="utf-8")
    step = st.written(root, home)
    assert not step["ok"] and "missing: config v1" in step["out"] and "ar: 2026-11.jsonl" in step["out"]
    assert "template v1" not in step["out"]          # a template's folder, not a brain's file


def test_the_overlay_adds_only_what_the_newer_fixture_adds(st):
    older = {"mine": {"root": ".", "repos": [{"path": ".", "lang": "py"}]}}       # a fixture's one project
    newer = {"mine": {"root": ".", "repos": [{"path": ".", "lang": "py", "ci": "github"}], "formats": {"a": 1}},
             "new": True}
    target = {"brain": {"root": ".", "title": "Ada", "repos": [{"path": ".", "name": "brain"}]}, "v": 1}
    assert st.overlay(target, older, newer) == {
        "brain": {"root": ".", "title": "Ada", "repos": [{"path": ".", "name": "brain", "ci": "github"}],
                  "formats": {"a": 1}}, "v": 1, "new": True}
    kept = {"identity": {"owner": "Ada Example"}, "v": 1}
    assert st.overlay(kept, {"identity": {"owner": "Ada"}}, {"identity": {"owner": "Ada", "pronouns": "they"}}) == {
        "identity": {"owner": "Ada Example", "pronouns": "they"}, "v": 1}   # the brain's own value never replaced


def test_only_additive_lines_are_laid_over(st):
    """The newer AR fixture also holds a higher v and a new kind: a newer brain's lines, not additive ones."""
    import json
    lines = [json.loads(x) for x in st.additive_lines("ar")]
    assert [(r["v"], r["kind"]) for r in lines] == [(1, "commit")] and lines[0]["signed"] is True
    assert [json.loads(x)["cpu_s"] for x in st.additive_lines("event")] == [0.4]


def test_the_newer_data_reaches_every_file_of_a_format(st, tmp_path):
    import json
    root, home = tmp_path / "brain", tmp_path / "home"
    root.mkdir()
    (root / "config.json").write_text(json.dumps({"v": 1, "identity": {"owner": "Ada Example"}}), encoding="utf-8")
    ledger = home / ".brain" / "ledger" / "engine"
    ledger.mkdir(parents=True)
    (ledger / "exec-2026-11.jsonl").write_text("", encoding="utf-8")
    step = st.add_newer(root, home)
    assert "config: config.json +keys" in step["out"] and "event: exec-2026-11.jsonl +1 line(s)" in step["out"]
    data = json.loads((root / "config.json").read_text(encoding="utf-8"))
    assert data["identity"] == {"owner": "Ada Example", "pronouns": "they"} and data["telemetry"] == {"enabled": False}
    assert '"cpu_s":0.4' in (ledger / "exec-2026-11.jsonl").read_text(encoding="utf-8")
    # the formats it reached no file of fail the step: the rollback would test nothing of them
    assert not step["ok"] and "reached no file: ar v1, ddr v1, members v1, modules v1, packs v1, permissions v1, " \
        "projects v1, readme v1, sr v1, standards v1" in step["out"]


def test_the_newer_data_reaches_the_module_registry(st, tmp_path):
    """modules.yaml is a YAML list: the overlay matches its entries one by one, a realisation's new key included."""
    import yaml
    root, home = tmp_path / "brain", tmp_path / "home"
    (root / "notes" / "graph").mkdir(parents=True)
    (root / "notes" / "graph" / "modules.yaml").write_text(st.fixture("modules", "older").read_text(encoding="utf-8"),
                                                           encoding="utf-8")
    assert st.where(root, home)["modules"] == [root / "notes" / "graph" / "modules.yaml"]
    step = st.add_newer(root, home)
    assert "modules: modules.yaml +keys" in step["out"], step["out"]
    data = yaml.safe_load((root / "notes" / "graph" / "modules.yaml").read_text(encoding="utf-8"))
    assert data[0]["persona"] == ["tea-drinker"] and data[1]["realized_by"][0]["since"] == "0.4.0"


def test_the_newer_data_reaches_a_yaml_file_holding_dates(st, tmp_path):
    """members.yaml's keys carry dates (since:), which YAML reads as dates: the overlay copies them as they are."""
    import yaml
    root, home = tmp_path / "brain", tmp_path / "home"
    root.mkdir()
    (root / "members.yaml").write_text(st.fixture("members", "older").read_text(encoding="utf-8"), encoding="utf-8")
    step = st.add_newer(root, home)
    assert "members: members.yaml +keys" in step["out"], step["out"]
    data = yaml.safe_load((root / "members.yaml").read_text(encoding="utf-8"))
    assert data["people"][0]["pronouns"] == "she" and "passkeys" in data
    assert str(data["people"][0]["keys"]["signing"][0]["since"]) == "2026-11-10"


def test_the_newer_data_reaches_readme_yaml(st, tmp_path):
    """readme.yaml (wi-brain-readme-sync) has its place at the brain's root: the newer keys reach it."""
    import yaml
    root, home = tmp_path / "brain", tmp_path / "home"
    root.mkdir()
    (root / "readme.yaml").write_text(st.fixture("readme", "older").read_text(encoding="utf-8"), encoding="utf-8")
    assert st.where(root, home)["readme"] == [root / "readme.yaml"]
    step = st.add_newer(root, home)
    assert "readme: readme.yaml +keys" in step["out"], step["out"]
    assert "badges" in yaml.safe_load((root / "readme.yaml").read_text(encoding="utf-8"))


def test_the_newer_data_reaches_a_local_standards_catalog(st, tmp_path):
    """A brain's local standards catalog (wi-brain-standards-registry) has its place, standards/ at the brain's root:
    the newer keys reach it, the older engine's rows kept."""
    import yaml
    root, home = tmp_path / "brain", tmp_path / "home"
    (root / "standards").mkdir(parents=True)
    f = root / "standards" / "local.yaml"
    f.write_text(st.fixture("standards", "older").read_text(encoding="utf-8"), encoding="utf-8")
    assert st.where(root, home)["standards"] == [f]
    step = st.add_newer(root, home)
    assert "standards: local.yaml +keys" in step["out"], step["out"]
    data = yaml.safe_load(f.read_text(encoding="utf-8"))
    assert data["owner"] == "a team" and [r["id"] for r in data["rows"]] == ["fx-atomic-writes", "fx-utc"]


def test_a_file_changed_or_removed_is_data_lost_and_a_ledger_may_only_grow(st, tmp_path):
    root = tmp_path / "brain"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "index").write_text("x", encoding="utf-8")
    (root / "a.txt").write_text("a", encoding="utf-8")
    (root / "b.txt").write_text("b", encoding="utf-8")
    ledger = tmp_path / "home" / ".brain" / "ledger"
    ledger.mkdir(parents=True)
    events = ledger / "exec-2026-11.jsonl"
    events.write_text('{"v":1}\n', encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text('{"drill": {}}', encoding="utf-8")
    before = st.snapshot([root, ledger, state])
    assert len(before) == 4                             # .git left out
    (root / ".git" / "index").write_text("y", encoding="utf-8")
    events.write_text('{"v":1}\n{"v":1,"task":"another engine"}\n', encoding="utf-8")   # appended: kept
    assert st.lost(before) == []
    events.write_text('{"v":2}\n', encoding="utf-8")                                    # rewritten: lost
    (root / "a.txt").unlink()
    state.write_text("{}", encoding="utf-8")
    assert st.lost(before) == [f"changed: {events.as_posix()}", f"changed: {state.as_posix()}",
                               f"removed: {(root / 'a.txt').as_posix()}"]
    (root / "b.txt").write_text("bb", encoding="utf-8")                                  # grown, not a ledger: lost
    assert f"changed: {(root / 'b.txt').as_posix()}" in st.lost(before)


def test_upgrade_from_takes_a_tag_or_a_checkout_never_nothing(st, tmp_path):
    assert st.upgrade_from("v0.2.5") == ("v0.2.5", "")
    assert st.upgrade_from(str(tmp_path)) == ("", str(tmp_path.resolve()))
    with pytest.raises(SystemExit, match="empty"):
        st.upgrade_from("")                             # a CI step that found no tag: never the plain test, green
    with pytest.raises(SystemExit, match="the --source checkout itself"):
        st.upgrade_from(str(tmp_path), str(tmp_path))


def test_the_engine_is_named_by_its_install(st, tmp_path, monkeypatch):
    """Two engines can share a version: the venv's brain is told by its direct_url.json."""
    tag = '{"url": "https://github.com/RoJLD/brain.git", "vcs_info": {"vcs": "git", "requested_revision": "v0.2.5"}}'
    folder = '{"url": "file:///D:/a/brain/brain/packages/brain", "dir_info": {}}'
    for out, ref, source, want in ((tag, "v0.2.5", "", True), (tag, "v0.2.4", "", False),
                                   (folder, "", "D:/a/brain/brain", True), (folder, "v0.2.5", "", False),
                                   ("", "v0.2.5", "", False)):
        monkeypatch.setattr(st, "_py", lambda scripts, code, env, root, out=out: (0, out + "\n"))
        assert st.engine_is(tmp_path, {}, tmp_path, ref, source)["ok"] is want, (out, ref, source)


def test_an_older_engine_may_only_refuse_the_newer_keys(st):
    for line, ok in (("error: config.json: unexpected field 'telemetry'", True),
                     ("error: permissions.yaml: unknown key(s) schedules", True),
                     ("error: boundary: x.md: no rule of boundary.yaml classifies it", False)):
        assert bool(st.NEWER.search(line)) is ok


# brain check's output under v0.2.6 after HEAD's sync (compat-prev on RoJLD/brain#71, run 42619784680), shortened
ROLLBACK_CHECK = """\
warning: records/ddr/ddr-2026-11-09-pick-a-colour.yaml: ddr: unknown field 'confidence' (kept: a newer brain's field?)
records: 2 DDR, 1 SR, 2 AR; 0 error(s), 10 warning(s)
warning: the running engine is not config.json engine.pin v0.2.7: brain 0.2.6 is behind the pin v0.2.7
render claude: 1 differs, 22 same
  differs  plugins/brain-core/hooks/common.sh
brain render: 1 file(s) not current: brain render --target claude --write
boundary: 51 tracked file(s) classified; engine side 1 file(s), readiness 0 (max 0), public scan green
$ research_graph check
graph-check OK
== registry
registry: 1 project(s), 1 store(s), ids unique
"""


def test_an_older_engines_check_may_only_find_heads_plugin_render_not_current(st):
    """HEAD's sync renders the plugin with its own hooks (common.sh carries the engine's version): an older engine
    with the read mode finds it not current, exit 1. That alone is allowed; anything else stays a no-go."""
    assert st.stale_render_only(0, "") and st.stale_render_only(1, ROLLBACK_CHECK)
    assert not st.stale_render_only(2, ROLLBACK_CHECK)
    assert not st.stale_render_only(1, "records: 1 DDR; 0 error(s), 0 warning(s)\ngraph-check OK\n")  # another cause
    for before, after in (("plugins/brain-core/hooks/common.sh", "CLAUDE.md"),          # a file of the brain's own
                          ("0 error(s), 10", "2 error(s), 10"),                          # a record refused
                          ("graph-check OK", "graph-check FAILED"),
                          ("public scan green", "public scan red"),
                          ("== registry", "error: a session id matches no session\n== registry")):
        assert not st.stale_render_only(1, ROLLBACK_CHECK.replace(before, after)), after


def test_the_exit_codes_may_be_a_function_of_the_output(st, monkeypatch):
    monkeypatch.setattr(st, "run", lambda cmd, env, root, stdin=None: (1, cmd[1]))
    steps = [("a", ["x", "fine"], None, None, lambda rc, o: o == "fine"),
             ("b", ["x", "bad"], None, None, lambda rc, o: o == "fine"), ("c", ["x", "y"], None, None, (0, 1)),
             ("d", ["x", "y"], None, None)]
    assert [s["ok"] for s in st.run_steps(steps, {}, Path("."))] == [True, False, True, False]


def test_a_new_key_takes_its_place_in_the_newer_fixture(st):
    """permissions.yaml's rules stay its last key (brain permissions grant appends to it): a newer section lands before
    them, where the newer fixture has it."""
    older = {"v": 1, "profiles": {}, "rules": []}
    newer = {"v": 1, "schedules": {"nightly": {}}, "profiles": {}, "rules": []}
    target = {"v": 1, "never": [], "profiles": {"lite": {}}, "rules": [{"deny": "x"}]}
    assert list(st.overlay(target, older, newer)) == ["v", "never", "schedules", "profiles", "rules"]


def test_a_failed_step_after_a_good_install_exits_1(st, tmp_path, monkeypatch):
    """2 is for an install that failed; a scenario or upgrade step that fails is a no-go, 1 (the report's steps list
    used to be the install's own list, so a later failure counted as an install's)."""
    calls = []

    def install(work, ref, source, pre_tag, over=False, step="install"):
        calls.append((ref, source, step))
        return tmp_path / "venv" / "bin", [{"step": step, "cmd": "pip", "rc": 0, "ok": True, "out": ""}]

    bad = [{"step": "check", "cmd": "brain check", "rc": 1, "ok": False, "out": ""}]
    monkeypatch.setattr(st, "install", install)
    monkeypatch.setattr(st, "scenario", lambda work, env, scripts: bad)
    monkeypatch.setattr(st, "upgrade", lambda work, env, scripts, prev, head: bad)
    assert st.main(["--work", str(tmp_path / "a"), "--source", str(tmp_path)]) == 1
    assert st.main(["--work", str(tmp_path / "b"), "--source", str(tmp_path), "--upgrade-from", "v0.2.5"]) == 1
    assert calls[-1] == ("v0.2.5", "", "install previous")     # the tag first; upgrade() installs the source over it


def test_docker_on_the_path_is_a_no_go_for_the_pilot_only(st, tmp_path, monkeypatch):
    """The pilot's go needs a machine without docker; the upgrade test does not (GitHub's Windows runners have it)."""
    good = [{"step": "check", "cmd": "brain check", "rc": 0, "ok": True, "out": ""}]
    monkeypatch.setattr(st, "install", lambda work, ref, source, pre_tag, over=False, step="install": (
        tmp_path / "venv" / "bin", [{"step": step, "cmd": "pip", "rc": 0, "ok": True, "out": ""}]))
    monkeypatch.setattr(st, "scenario", lambda work, env, scripts: good)
    monkeypatch.setattr(st, "upgrade", lambda work, env, scripts, prev, head: good)
    monkeypatch.setattr(st.shutil, "which", lambda name, path=None: "docker" if name == "docker" else None)
    assert st.main(["--work", str(tmp_path / "a"), "--source", str(tmp_path)]) == 1
    assert st.main(["--work", str(tmp_path / "b"), "--source", str(tmp_path), "--upgrade-from", "v0.2.5"]) == 0
