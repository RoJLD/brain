import json
import os
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
BRAIN = FIXTURES / "brain" / "config.json"  # the owner the tests run as: Ada
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_NOSYSTEM": "1"}

# The hermetic environment (wi-brain-hermetic-tests): an allow list, not a deny list. Every variable of the families
# the engine reads (BRAIN_*, CLAUDE*, GIT_*, RESEARCH_GRAPH_*, OTEL_*) is cleared for the whole run, and again before
# each test, unless this file pins it (PINNED, SESSION_PINS) or a test sets it; so is a token that would reach the
# owner's GitHub account (CLEARED). A new variable of a family is cleared the day the engine starts reading it, where a
# deny list let it through (CLAUDE_CODE_HOST_SESSION_ID failed test_resume from a desktop-app session, CLAUDECODE
# test_tui's actions). git reads an empty global configuration (its default ignore and attributes files too) and no
# system one, so a user's diff.noprefix, alias or *.log ignore never reaches a test. tests/test_hermetic.py lists the
# variables the engine reads and fails on one this file leaves set unexamined.
# OTEL_*: the OpenTelemetry export's settings (brain.ipchealth renders and checks Claude Code's), and a shell's
# OTEL_EXPORTER_OTLP_HEADERS may carry the machine's token: none reaches a test
FAMILIES = ("BRAIN_", "CLAUDE", "GIT_", "RESEARCH_GRAPH_", "OTEL_")
# a token that would reach the owner's GitHub account, the editor a test would open on the owner's screen
CLEARED = frozenset({"GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "EDITOR", "VISUAL"})
RUNNER = frozenset({"BRAIN_TEST_ROOT", "BRAIN_TEST_WORKERS"})   # the suite's own knobs, read by this file alone
PINNED = frozenset({"BRAIN_HOME", "BRAIN_SELFTIME", "BRAIN_NOTIFY", "BRAIN_STRICT", "BRAIN_PERMISSIONS",
                    "BRAIN_CONFIG", "CLAUDE_CONFIG_DIR", "LOCALAPPDATA"})   # set before each test by brain_home
SESSION_PINS = frozenset({"GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM"})   # set for the run by pytest_configure
# An owner's opt-in to a test that is skipped otherwise, read by that test through opted_in(): cleared like the rest
# (BRAIN_TEST_KEYSTORE also lets the engine reach the real keystore under pytest), its value kept aside under
# OPT_IN_PREFIX, a name the engine never reads, which xdist's workers inherit.
OPT_INS = ("BRAIN_TEST_KEYSTORE",)
OPT_IN_PREFIX = "HERMETIC_OPT_IN_"
_GIT_FILES: list[str] = []


def hermetic(name: str) -> bool:
    """Whether the hermetic environment clears ``name`` unless it is pinned (case-insensitive, as Windows reads it)."""
    up = name.upper()
    return (up.startswith(FAMILIES) or up in CLEARED) and up not in RUNNER


def opted_in(name: str) -> str:
    """The value the owner gave an opt-in of :data:`OPT_INS` when the run started ('' when none)."""
    return os.environ.get(OPT_IN_PREFIX + name, "")


def hermetic_environment(env, gitconfig: str) -> list[str]:
    """Clears from ``env`` (os.environ, or a dict in a test) every variable :func:`hermetic` names, an opt-in kept
    aside first, then points git at ``gitconfig`` with no system configuration; returns the names cleared."""
    for name in OPT_INS:
        if env.get(name):
            env[OPT_IN_PREFIX + name] = env[name]
    cleared = sorted(k for k in env if hermetic(k))
    for k in cleared:
        del env[k]
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = gitconfig
    return cleared


def clear_leftovers(monkeypatch) -> list[str]:
    """Before each test: a variable of the families set since the run started (os.environ itself, not monkeypatch)
    cleared again, the run's git pins kept; the names cleared."""
    left = [k for k in os.environ if hermetic(k) and k.upper() not in SESSION_PINS]
    for k in left:
        monkeypatch.delenv(k)
    return left


def _empty_git_files() -> str:
    """The run's global git configuration: no setting but the user's default ignore and attributes files
    ($XDG_CONFIG_HOME/git/ignore, git/attributes, which git reads without a setting) pointed at an empty file."""
    paths = []
    for suffix in (".gitconfig", ".empty"):
        fd, path = tempfile.mkstemp(prefix="brain-tests-", suffix=suffix)
        os.close(fd)
        paths.append(path)
    empty = Path(paths[1]).as_posix()
    Path(paths[0]).write_text(f"[core]\n\texcludesFile = {empty}\n\tattributesFile = {empty}\n", encoding="utf-8")
    _GIT_FILES[:] = paths
    return paths[0]


def pytest_configure(config):
    """The run's hermetic environment, before any test module is imported (one reads a variable at import) and before
    xdist starts its workers, which inherit it (and each clear it again: a worker loads this file too)."""
    hermetic_environment(os.environ, _empty_git_files())


def pytest_unconfigure(config):
    for path in _GIT_FILES:
        Path(path).unlink(missing_ok=True)
    _GIT_FILES.clear()


@pytest.hookimpl(tryfirst=True)
def pytest_cmdline_main(config):
    """``-n N`` with no ``--dist``: pytest-xdist's worksteal, not its default load (wi-brain-test-speed-2). load hands
    each worker a fixed share up front, so the suite ends on the one or two workers left with the git-heavy tests
    while the others idle; worksteal lets an idle worker take tests still queued on a busy one. Runs before xdist's
    own hook, which turns ``dist`` from "no" to "load"; an explicit ``--dist`` is kept, and so is load when
    ``--maxschedchunk`` (load's own option) is given; ``-n 0`` stays one process. A conftest hook rather than ``--dist``
    in addopts: a run whose paths span the repo root (``pytest packages/brain/tests tests``) reads the root's pytest
    config, and ``--dist`` there would fail the research-graph job, which has no xdist."""
    if config.pluginmanager.hasplugin("xdist") and config.getoption("dist", "no") == "no" \
            and config.getoption("numprocesses", None) not in (None, 0) \
            and config.getoption("maxschedchunk", None) is None:
        config.option.dist = "worksteal"
    temp_under_test_root(config)


def test_root_dir(kind: str) -> Path | None:
    """``<BRAIN_TEST_ROOT>/<kind>``, made if missing; None when BRAIN_TEST_ROOT is unset (the system's temp folder)."""
    raw = os.environ.get("BRAIN_TEST_ROOT", "").strip()
    if not raw:
        return None
    d = Path(raw).expanduser().resolve() / kind   # absolute: subprocesses run from other folders
    d.mkdir(parents=True, exist_ok=True)
    return d


test_root_dir.__test__ = False   # a helper, not a test


def temp_under_test_root(config) -> None:
    """``BRAIN_TEST_ROOT``: pytest's temporary folders go under ``<root>/tmp`` (wi-brain-test-speed-2), one folder an
    owner can exclude from an on-access antivirus scan, short enough for the venvs some tests build; unset, the
    system's temp folder as before. pytest keeps its numbering and its last three runs there
    (``PYTEST_DEBUG_TEMPROOT``); an explicit ``--basetemp`` or ``PYTEST_DEBUG_TEMPROOT`` wins."""
    if config.getoption("basetemp", None) or os.environ.get("PYTEST_DEBUG_TEMPROOT"):
        return
    tmp = test_root_dir("tmp")
    if tmp is not None:
        os.environ["PYTEST_DEBUG_TEMPROOT"] = str(tmp)


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_auto_num_workers(config):
    """``BRAIN_TEST_WORKERS``: the worker count ``-n auto`` (or ``-n logical``) means; unset, xdist's own answer
    (its ``PYTEST_XDIST_AUTO_NUM_WORKERS``, else the CPU count). The strict form of xdist's variable, which it wins
    over: xdist only warns on a value that is not a number. Measured on a 16-thread Windows machine, 24 and 32 workers
    ran no faster than 16 (wi-brain-test-speed-2): process creation, not the CPU, bounds the suite there; the variable
    is for a machine where it differs. An explicit ``-n N`` wins."""
    raw = os.environ.get("BRAIN_TEST_WORKERS", "").strip()
    if not raw:
        return None
    try:
        workers = int(raw)
    except ValueError:
        raise pytest.UsageError(f"BRAIN_TEST_WORKERS={raw!r}: a whole number of workers (0: one process)") from None
    if workers < 0:
        raise pytest.UsageError(f"BRAIN_TEST_WORKERS={raw!r}: a whole number of workers (0: one process)")
    return workers


@pytest.fixture(autouse=True)
def brain_home(tmp_path, monkeypatch):
    """Every test writes its ledger to a temporary BRAIN_HOME, never ~/.brain, in the hermetic environment: a variable
    of the families an earlier test set without monkeypatch (os.environ itself, a child's leftover) is cleared again,
    so none reaches this one (the agent's session ids, BRAIN_ROOT, BRAIN_CAPTURE, BRAIN_PERSONAL, CLAUDE_BRAIN_DIR,
    BRAIN_IPC_TOKEN_FILE, BRAIN_MCP_CONTAINER...: the tests run as the owner's own terminal, on no machine's brain)."""
    clear_leftovers(monkeypatch)
    home = tmp_path / "brain-home"
    monkeypatch.setenv("BRAIN_HOME", str(home))
    monkeypatch.setenv("BRAIN_SELFTIME", "0")  # the engine's own events: only test_selftime turns them on
    monkeypatch.setenv("BRAIN_NOTIFY", "off")  # no test sends a real notification (test_notify fakes the transports)
    # the checks read strictly, as in CI, whether or not the suite runs there; the tolerant tests set BRAIN_STRICT=0
    monkeypatch.setenv("BRAIN_STRICT", "1")
    from brain import schema
    schema._NOTED.clear()   # each test sees its own read-mode notes
    # no test reads the owner's permissions.yaml unless it says so: the never-grantable categories are the engine's
    monkeypatch.setenv("BRAIN_PERMISSIONS", str(tmp_path / "no-permissions.yaml"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))  # no test reads the owner's transcripts
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))  # nor the desktop app's sessions (brain.tidy)
    # no test reads this checkout's config.json unless it says so: the tests' brain is Ada's (fixtures/brain), so a
    # view that still names someone else fails
    monkeypatch.setenv("BRAIN_CONFIG", str(BRAIN))
    from brain import update  # no test reads the engine's tags or its CHANGELOG on GitHub: offline unless it fakes them

    def offline(*args, **kwargs):
        raise OSError("no network in the tests")
    monkeypatch.setattr(update, "remote_tags", offline)
    monkeypatch.setattr(update, "changelog", lambda *args, **kwargs: None)
    from brain import tagsig  # nor fetches a release tag to verify it: a folder that does not exist instead

    monkeypatch.setattr(tagsig, "repo_url", lambda repo: (tmp_path / "no-network" / repo).as_uri())
    # a test that runs cli.main in a process with no console (a CI runner) lets brain.nowindow wrap Popen: undone after
    monkeypatch.setattr(subprocess.Popen, "__init__", subprocess.Popen.__init__)
    return home


@pytest.fixture
def fixture_transcript():
    return FIXTURES / "transcript.jsonl"


@pytest.fixture
def views_strict(tmp_path, monkeypatch):
    """Ada's brain with config.json views.strict true (the owner's opt-in, brain.views.strict): a stale view fails
    brain check on the default branch, and the writers of one committed view refuse an engine other than the pin."""
    folder = tmp_path / "strict-brain"
    folder.mkdir()
    shutil.copy(BRAIN.parent / "rules.md", folder / "rules.md")
    data = json.loads(BRAIN.read_text(encoding="utf-8"))
    data["views"] = {"strict": True}
    cfg = folder / "config.json"
    cfg.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    return cfg


def run_git(cwd, *args):
    env = dict(os.environ, **GIT_ENV)
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env).stdout


_TEMPLATES: dict[str, Path] = {}
NO_LOCKS = shutil.ignore_patterns("*.lock")   # a lock git holds a moment is never part of a template's copy
_TEMPLATE_ROOT: list[Path] = []


@pytest.fixture(scope="session", autouse=True)
def _git_templates(tmp_path_factory):
    """Where this test process (an xdist worker is one) keeps its template repositories, under pytest's basetemp."""
    _TEMPLATE_ROOT[:] = [tmp_path_factory.mktemp("git-templates")]
    yield
    _TEMPLATES.clear()


def _template(kind: str) -> Path:
    """An empty repository made once per test process, copied by git_init: a copy takes a few milliseconds where
    ``git init`` and its config calls take hundreds on Windows."""
    if kind not in _TEMPLATES:
        repo = _TEMPLATE_ROOT[0] / kind
        run_git(_TEMPLATE_ROOT[0], "init", "-q", *(["--bare"] if kind == "bare" else []), "-b", "main", str(repo))
        # no background maintenance after a commit (git maintenance run --auto): its objects/maintenance.lock,
        # made and removed while a test copies the template, failed shutil.copytree in CI
        for key, value in (("commit.gpgsign", "false"), ("core.autocrlf", "false"), ("maintenance.auto", "false"),
                           ("gc.auto", "0")):
            run_git(repo, "config", key, value)
        _TEMPLATES[kind] = repo
    return _TEMPLATES[kind]


def git_init(path, branch: str = "main", bare: bool = False) -> Path:
    """``git init -q -b <branch> [--bare] <path>`` with commit.gpgsign and core.autocrlf off, by copying a template
    repository: ``path`` may exist (empty or not), its files are left as they are."""
    path = Path(path)
    if bare:
        shutil.copytree(_template("bare"), path, dirs_exist_ok=True, ignore=NO_LOCKS)
    else:
        path.mkdir(parents=True, exist_ok=True)
        shutil.copytree(_template("work") / ".git", path / ".git", ignore=NO_LOCKS)
    if branch != "main":
        (path / ("HEAD" if bare else ".git/HEAD")).write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
    return path


def head_sha(repo) -> str:
    """HEAD's sha, read from the branch's loose ref when there is one (a git process costs 50-300 ms on Windows,
    and make_repo commits hundreds of times a run: wi-brain-test-speed-2), else from ``git rev-parse HEAD``."""
    git_dir = Path(repo) / ".git"
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
        sha = (git_dir / head[5:]).read_text(encoding="utf-8").strip() if head.startswith("ref: ") else head
    except OSError:   # a worktree's .git file, a packed ref
        sha = ""
    return sha if len(sha) in (40, 64) and all(c in "0123456789abcdef" for c in sha) \
        else run_git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("git not available")
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    if "git_repo" not in _TEMPLATES:   # its one commit made once per test process, then copied
        repo = git_init(_TEMPLATE_ROOT[0] / "git_repo")
        (repo / "notes" / "graph" / "nodes").mkdir(parents=True)
        (repo / "notes" / "graph" / "nodes" / "work.yaml").write_text(
            "# work\n- {id: wi-a, type: WorkItem, status: todo,\n   title: \"A\",\n   props: {priority: P1}}\n"
            "- {id: wi-b, type: WorkItem, status: todo, title: \"B\"}\n", encoding="utf-8")
        (repo / "notes" / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-q", "-m", "init")
        _TEMPLATES["git_repo"] = repo
    return Path(shutil.copytree(_TEMPLATES["git_repo"], tmp_path / "repo", ignore=NO_LOCKS))


@pytest.fixture
def store(tmp_path):
    """A minimal research_graph store with the work layer."""
    s = tmp_path / "root" / "notes" / "graph"
    (s / "nodes").mkdir(parents=True)
    (s / "edges").mkdir()
    (s / "schema.yaml").write_text(
        "node_types: [ADR, WorkItem, Milestone, Spec, DDR, Session, Action]\n"
        "edge_types: [decided_by, supersedes, part_of, depends_on, specified_by, raised_by, answered_in, about, produced_by, "
        "touches]\n"
        "statuses: [active, todo, doing, done, dropped, pending, reached, proposed, answered, integrated, archived, "
        "open, closed, recorded]\n"
        "status_by_type:\n  WorkItem: [todo, doing, done, dropped]\n  Milestone: [pending, reached]\n", encoding="utf-8")
    (s / "edges.yaml").write_text("", encoding="utf-8")
    (s / "nodes" / "work.yaml").write_text(
        "# Work layer\n\n# --- specs ---\n"
        "- {id: spec-x, type: Spec, status: active, title: \"Spec X\", anchor: \"docs/x.md#top\"}\n"
        "- {id: ms-x, type: Milestone, status: pending, title: \"Milestone X\",\n"
        "   props: {trigger: \"x: y, z\"}}\n"
        "# --- items ---\n"
        "- {id: wi-one, type: WorkItem, status: todo,\n"
        "   title: \"First: with a colon, and a comma\",\n"
        "   props: {priority: P0, theme: \"3.1\", idea: \"Ada, 2026-10-30\"}}\n"
        "- {id: wi-two, type: WorkItem, status: doing, title: \"Second\"}\n", encoding="utf-8")
    (s / "edges" / "work.yaml").write_text("# Work edges\n- {from: wi-one, to: spec-x, type: specified_by}\n",
                                           encoding="utf-8")
    (s / "nodes" / "_generated_decisions.yaml").write_text(
        "- {id: adr-2026-10-30-x, type: ADR, title: \"X\", status: active, anchor: \"notes/decisions.md#2026-10-30-x\"}\n",
        encoding="utf-8")
    return s


@pytest.fixture
def make_repo(tmp_path, monkeypatch):
    """Temporary git repos with dated commits: ``make_repo(name, files, date=...)`` creates one and returns its path;
    ``make_repo.commit(repo, files, date=...)`` writes (None deletes) and commits, returning the sha."""
    if not shutil.which("git"):
        pytest.skip("git not available")
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)

    def write(repo, files):
        for rel, text in (files or {}).items():
            f = repo / rel
            if text is None:
                f.unlink()
                continue
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(textwrap.dedent(text), encoding="utf-8", newline="\n")

    def commit(repo, files=None, date="2026-10-01T12:00:00Z", msg="change"):
        write(repo, files)
        env = dict(os.environ, **GIT_ENV, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        for args in (["add", "-A"], ["commit", "-q", "--allow-empty", "-m", msg]):
            subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)
        return head_sha(repo)

    def make(name, files, date="2026-10-01T12:00:00Z", branch="main"):
        repo = git_init(tmp_path / name, branch)
        commit(repo, files, date, "init")
        return repo

    make.commit, make.write = commit, write
    return make
