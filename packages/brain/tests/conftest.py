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
    monkeypatch.setenv("BRAIN_NOTIFY", "off")  # no test sends a real notification (test_notify fakes the transports)
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
    for var in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "BRAIN_AGENT_SESSION", "CLAUDE_CODE_SESSION_ID",
                "CLAUDE_SESSION_ID"):
        monkeypatch.delenv(var, raising=False)
    return home


@pytest.fixture
def fixture_transcript():
    return FIXTURES / "transcript.jsonl"


def run_git(cwd, *args):
    env = dict(os.environ, **GIT_ENV)
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env).stdout


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("git not available")
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-q", "-b", "main")
    run_git(repo, "config", "commit.gpgsign", "false")
    (repo / "notes" / "graph" / "nodes").mkdir(parents=True)
    (repo / "notes" / "graph" / "nodes" / "work.yaml").write_text(
        "# work\n- {id: wi-a, type: WorkItem, status: todo,\n   title: \"A\",\n   props: {priority: P1}}\n"
        "- {id: wi-b, type: WorkItem, status: todo, title: \"B\"}\n", encoding="utf-8")
    (repo / "notes" / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "init")
    return repo


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
        repo = tmp_path / name
        repo.mkdir(parents=True)
        run_git(repo, "init", "-q", "-b", branch)
        run_git(repo, "config", "commit.gpgsign", "false")
        run_git(repo, "config", "core.autocrlf", "false")
        commit(repo, files, date, "init")
        return repo

    make.commit, make.write = commit, write
    return make
