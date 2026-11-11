import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
BRAIN = FIXTURES / "brain" / "config.json"  # the owner the tests run as: Ada
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_NOSYSTEM": "1"}


@pytest.fixture(autouse=True)
def brain_home(tmp_path, monkeypatch):
    """Every test writes its ledger to a temporary BRAIN_HOME, never ~/.brain."""
    home = tmp_path / "brain-home"
    monkeypatch.setenv("BRAIN_HOME", str(home))
    monkeypatch.delenv("BRAIN_ROOT", raising=False)
    monkeypatch.delenv("BRAIN_CAPTURE", raising=False)
    monkeypatch.setenv("BRAIN_SELFTIME", "0")  # the engine's own events: only test_selftime turns them on
    monkeypatch.delenv("BRAIN_HOOK_T0", raising=False)
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
    monkeypatch.delenv("CLAUDE_BRAIN_DIR", raising=False)
    monkeypatch.delenv("BRAIN_PERSONAL", raising=False)  # and no machine's personal brain: the pointer is in home
    # the tests run as the owner's own terminal unless they say otherwise, even from an agent's shell (brain.answers)
    # (nor the desktop app's session id: brain.sessions stamps it, so a run from a session would differ)
    for var in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "BRAIN_AGENT_SESSION", "CLAUDE_CODE_SESSION_ID",
                "CLAUDE_SESSION_ID", "CLAUDE_CODE_HOST_SESSION_ID"):
        monkeypatch.delenv(var, raising=False)
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
        return run_git(repo, "rev-parse", "HEAD").strip()

    def make(name, files, date="2026-10-01T12:00:00Z", branch="main"):
        repo = git_init(tmp_path / name, branch)
        commit(repo, files, date, "init")
        return repo

    make.commit, make.write = commit, write
    return make
