"""Conflict markers (brain.markers; wi-brain-guard-conflict-markers): the commit guard refuses a commit that adds one
(check markers), brain check fails on a store, journal, decision log or record that holds one; a Markdown setext
heading and a test fixture pass. The markers are assembled at run time, so this file never holds one at a line's
start."""

import shutil
import subprocess

import pytest
from conftest import run_git
from test_guards import bash, pwsh

from brain import cli, graph, guards, markers, paths

OURS, THEIRS, MID, BASE = "<" * 7 + " HEAD", ">" * 7 + " claude/other", "=" * 7, "|" * 7 + " base"
CONFLICT = f"- {{id: wi-a, status: todo}}\n{OURS}\n- {{id: wi-b, status: doing}}\n{MID}\n" \
           f"- {{id: wi-b, status: done}}\n{THEIRS}\n"


# --- brain.markers --------------------------------------------------------------------------------------------------

def test_scan_text_finds_each_marker_with_its_line():
    assert markers.scan_text("notes/graph/nodes/work.yaml", CONFLICT) == [
        "notes/graph/nodes/work.yaml:2", "notes/graph/nodes/work.yaml:4", "notes/graph/nodes/work.yaml:6"]
    assert markers.scan_text("a.py", f"x = 1\n{BASE}\n") == ["a.py:2"]
    assert markers.scan_text("a.py", f"{MID}=\n{'<' * 7}x\n  {MID}\nx = '{OURS}'\n") == []   # not a marker's shape


@pytest.mark.parametrize("path,text,hits", [
    ("README.md", f"Title\n{MID}\n\nText.\n", []),                        # a setext heading
    ("docs/guide.rst", f"Usage\n{MID}\n", []),
    ("README.md", f"Text.\n\n{MID}\n", ["README.md:3"]),                   # under a blank line: no heading
    ("README.md", f"{MID}\nTitle\n", ["README.md:1"]),                     # at the top
    ("notes/journal.md", f"- a\n{OURS}\n- b\n{MID}\n- c\n{THEIRS}\n",      # a conflict in Markdown: the ======= is
     ["notes/journal.md:2", "notes/journal.md:4", "notes/journal.md:6"]),  # under a marker, not text
    ("config.yaml", f"Title\n{MID}\n", ["config.yaml:2"]),                 # no heading outside Markdown
    ("tests/fixtures/merge/work.yaml", CONFLICT, []),                      # a test's data
    ("tests/testdata/conflict.txt", CONFLICT, []),
])
def test_setext_headings_and_fixtures_pass(path, text, hits):
    assert markers.scan_text(path, text) == hits


def test_scan_diff_reads_added_lines_with_the_line_above():
    diff = (f"diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -3,1 +3,3 @@\n Intro\n"
            f"+Usage\n+{MID}\n"
            f"diff --git a/w.yaml b/w.yaml\n--- a/w.yaml\n+++ b/w.yaml\n@@ -1,1 +1,3 @@\n-{OURS}\n x: 1\n"
            f"+{THEIRS}\n+{MID}\n")
    assert markers.scan_diff(diff) == ["w.yaml:2", "w.yaml:3"]   # a removed marker is no hit


# --- the commit guard -----------------------------------------------------------------------------------------------

@pytest.fixture
def repo(git_repo, monkeypatch):
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    monkeypatch.setattr(guards, "gitleaks", lambda repo: None)
    monkeypatch.setenv("BRAIN_PROJECTS", str(git_repo / "no-registry.yaml"))
    return git_repo


def test_a_staged_marker_is_refused_with_file_and_line(repo):
    (repo / "work.yaml").write_text(CONFLICT, encoding="utf-8")
    run_git(repo, "add", "work.yaml")
    reason = bash(repo, 'git commit -m "merge"')
    assert "git commit refused: work.yaml:2 and 2 more adds a conflict marker" in reason
    assert "BRAIN_GUARD_ALLOW=markers" in reason
    assert "work.yaml:2" in pwsh(repo, 'git commit -m "merge"')


def test_a_marker_staged_by_the_same_command_or_commit_all_is_refused(repo):
    (repo / "notes" / "decisions.md").write_text(f"# Decisions\n{OURS}\nA\n{MID}\nB\n{THEIRS}\n", encoding="utf-8")
    assert "notes/decisions.md:2" in bash(repo, 'git commit -am "decisions"')
    assert "notes/decisions.md:2" in bash(repo, 'git add notes && git commit -m "decisions"')
    (repo / "new.yaml").write_text(f"{THEIRS}\n", encoding="utf-8")
    assert "new.yaml:1" in bash(repo, 'git add new.yaml && git commit -m "new"')


def test_a_merge_continue_is_read_too(repo):
    (repo / "work.yaml").write_text(CONFLICT, encoding="utf-8")
    run_git(repo, "add", "work.yaml")
    for sub in ("merge", "rebase", "cherry-pick"):
        assert f"git {sub} --continue refused: work.yaml:2" in bash(repo, f"git {sub} --continue")


@pytest.mark.parametrize("name,text", [
    ("README.md", f"# Demo\n\nUsage\n{MID}\n\nRun it.\n"),
    ("tests/fixtures/merge/work.yaml", CONFLICT),
    ("code.py", f"SEP = '{MID}'\nMARK = '{OURS}'\n"),
])
def test_headings_fixtures_and_quoted_markers_commit(repo, name, text):
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text, encoding="utf-8")
    run_git(repo, "add", name)
    assert bash(repo, 'git commit -m "x"') is None


def _merge_with_a_documented_conflict(repo):
    """main holds a CONTRIBUTING.md quoting a conflict (committed past the guard); branch feat changes work.yaml too,
    and its git merge main stops on work.yaml. Returns work.yaml."""
    work = repo / "notes" / "graph" / "nodes" / "work.yaml"
    run_git(repo, "checkout", "-q", "-b", "feat")
    work.write_text(work.read_text(encoding="utf-8").replace('"B"', '"B feat"'), encoding="utf-8")
    run_git(repo, "commit", "-qam", "feat")
    run_git(repo, "checkout", "-q", "-")
    (repo / "CONTRIBUTING.md").write_text(f"# Merging\n\n```text\n{OURS}\nours\n{MID}\ntheirs\n{THEIRS}\n```\n",
                                          encoding="utf-8")
    work.write_text(work.read_text(encoding="utf-8").replace('"B"', '"B main"'), encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-qm", "main")
    run_git(repo, "checkout", "-q", "feat")
    subprocess.run(["git", "-C", str(repo), "merge", "-q", "--no-edit", "main"], capture_output=True)
    return work


def test_a_merge_resolution_commits_over_what_the_merged_branch_holds(repo):
    """Review of #26, finding 18: during a merge, a line counts only when it is new against every parent; a marker
    the session leaves in the file it resolves is still refused."""
    work = _merge_with_a_documented_conflict(repo)
    resolved = work.read_text(encoding="utf-8")
    work.write_text(resolved.split(OURS)[0] + '- {id: wi-b, type: WorkItem, status: todo, title: "B both"}\n',
                    encoding="utf-8")
    run_git(repo, "add", str(work))
    for command in ('git commit -m "merge main"', "git merge --continue", "git commit --no-edit"):
        assert bash(repo, command) is None, command
    work.write_text(resolved, encoding="utf-8")
    run_git(repo, "add", str(work))
    assert "notes/graph/nodes/work.yaml:" in bash(repo, 'git commit -m "merge main"')


def test_a_whole_tree_add_from_a_subfolder_and_pathspec_magic_are_read(repo):
    """Review of #26, finding 20: git add -A or -u with no pathspec stages the whole worktree from any folder, and
    :/ or an exclusion's magic is no literal path."""
    (repo / "notes" / "decisions.md").write_text(f"# Decisions\n{OURS}\nA\n{MID}\nB\n{THEIRS}\n", encoding="utf-8")
    sub = repo / "notes" / "graph"
    for command in ("git add -A && git commit --no-edit", "git add -u && git commit -m x",
                    "git add -A && git merge --continue", "git add -A ':!junk.stackdump' && git commit -m x",
                    "git add :/ && git commit -m x", "cd nodes && git add --all && git commit -m x"):
        assert "notes/decisions.md:2" in bash(sub, command), command


@pytest.mark.parametrize("command", ["git commit -m x notes/work.yaml", "git commit --only -m x notes/work.yaml",
                                     "git commit -i -m x notes/work.yaml", "git commit -m x -- notes/work.yaml",
                                     "git commit -qm x notes/work.yaml"])
def test_a_commits_own_pathspec_is_read(repo, command):
    """Review of #26, finding 21: git commit PATH records the working tree of PATH, unstaged markers included."""
    (repo / "notes" / "work.yaml").write_text("x: 1\n", encoding="utf-8")
    run_git(repo, "add", "notes/work.yaml")
    run_git(repo, "commit", "-qm", "work")
    (repo / "notes" / "work.yaml").write_text(f"{OURS}\nx: 1\n{MID}\nx: 2\n{THEIRS}\n", encoding="utf-8")
    assert "notes/work.yaml:1" in bash(repo, command)


def test_git_add_u_reads_no_untracked_file(repo):
    """Review of #26, finding 44: git add -u stages no untracked file, so a mergetool's backup is not read; git add
    -A stages it, and is refused."""
    (repo / "work.yaml.orig").write_text(CONFLICT, encoding="utf-8")
    (repo / "notes" / "decisions.md").write_text("# Decisions\n- fixed\n", encoding="utf-8")
    for command in ("git add -u && git commit -m fix", "git add --update && git commit -m fix",
                    "git add -p && git commit -m fix"):
        assert bash(repo, command) is None, command
    assert "work.yaml.orig:2" in bash(repo, "git add -A && git commit -m fix")


def test_a_path_with_a_space_keeps_its_heading(repo):
    """Review of #26, finding 42: git ends a +++ line with a TAB when the path holds a space; a C-quoted path is
    unquoted."""
    for name in ("docs/User guide/index.md", "My notes.md"):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(f"# Guide\n\nLicense\n{MID}\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    assert bash(repo, 'git commit -m "docs"') is None
    assert markers.diff_path("+++ b/docs/User guide/index.md\t") == "docs/User guide/index.md"
    assert markers.diff_path('+++ "b/caf\\303\\251 notes.md"\t') == "café notes.md"
    assert markers.scan_diff(f'+++ "b/caf\\303\\251 notes.md"\t\n@@ -0,0 +1,2 @@\n+License\n+{MID}\n') == []


@pytest.mark.parametrize("name", ["CHANGES.txt", "notes.qmd", "report.Rmd"])
def test_a_heading_in_rest_txt_quarto_and_r_markdown_passes(name):
    """Review of #26, finding 43: reST in .txt (Sphinx, CHANGES.txt), Quarto and R Markdown are markup too."""
    assert markers.scan_text(name, f"Changes\n{MID}\n\nText.\n") == []
    assert markers.scan_text("pricing.py", f'"""\nPricing\n{MID}\n"""\n') == ["pricing.py:3"]   # not markup


def test_a_moved_file_adds_no_line(repo):
    """Review of #26, finding 47: a pure git mv shows no added line, whatever diff.renames says."""
    (repo / "legacy.cfg").write_text(f"Title\n{MID}\n", encoding="utf-8")
    run_git(repo, "add", "legacy.cfg")
    run_git(repo, "commit", "-qm", "legacy")
    run_git(repo, "config", "diff.renames", "false")
    run_git(repo, "mv", "legacy.cfg", "old.cfg")
    assert bash(repo, 'git commit -m "move"') is None


def test_a_big_staged_file_never_hides_a_marker(repo, monkeypatch):
    """Review of #26, finding 48: only the files whose changes hold a marker-like line are read (git diff -G), so a
    big data file never cuts the diff; a diff git cannot show whole is a logged error, never a silent pass; an
    untracked file over 1 MB is read too."""
    monkeypatch.setattr(guards, "GIT_CAP", 4000)
    (repo / "data").mkdir()
    (repo / "data" / "ticks.csv").write_text("t,p\n" + "1,2\n" * 5000, encoding="utf-8")
    (repo / "work.yaml").write_text(CONFLICT, encoding="utf-8")
    run_git(repo, "add", "-A")
    assert "work.yaml:2" in bash(repo, 'git commit -m "x"')
    run_git(repo, "reset", "-q")
    (repo / "work.yaml").unlink()
    (repo / "data" / "markers.txt").write_text(f"{THEIRS}\n" * 1000, encoding="utf-8")
    run_git(repo, "add", "-A")
    with pytest.raises(guards.GuardError, match="not read whole"):
        guards.commit_markers(str(repo), [], False)
    assert bash(repo, 'git commit -m "x"') is None   # an error lets the call through, logged
    assert "GuardError" in (paths.ledger_dir() / "errors.log").read_text(encoding="utf-8")
    run_git(repo, "reset", "-q")
    shutil.rmtree(repo / "data")
    (repo / "big.yaml").write_text("x: 1\n" * 300_000 + f"{THEIRS}\n", encoding="utf-8")
    assert guards.commit_markers(str(repo), [str(repo)], False, [str(repo)])[-1] == "big.yaml:300001"


def test_a_folder_that_is_not_yet_a_repo_logs_no_error(repo, tmp_path, monkeypatch):
    """Review of #79: a commit whose folder does not exist yet when the guard runs (mkdir and git init in the same
    call), or is no repo, has nothing to read, as for git: no GuardError in errors.log, no engine error event."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    plain = tmp_path / "plain"
    plain.mkdir()
    whole = [guards.WHOLE_TREE]
    assert guards.commit_markers(str(tmp_path / "newproj"), whole, True) == []
    assert guards.commit_markers(str(plain), whole, True, whole) == []
    for d, command in ((tmp_path, "mkdir newproj && cd newproj && git init && git add . && git commit -m init"),
                       (plain, 'git commit -m "x"')):
        assert bash(d, command) is None, command
    log = paths.ledger_dir() / "errors.log"
    assert not log.is_file() or "GuardError" not in log.read_text(encoding="utf-8")


@pytest.mark.parametrize("failure", ["git missing", "timeout", "dubious ownership"])
def test_a_git_that_cannot_tell_a_worktree_is_a_logged_error(repo, monkeypatch, failure):
    """Review of #79's skeptic (finding 48): only a missing folder or git's 'not a git repository' pass quietly; git
    missing from the hook's PATH, a timeout or any other failure of the worktree check is a GuardError in errors.log,
    never a silent pass."""
    (repo / "work.yaml").write_text(CONFLICT, encoding="utf-8")
    run_git(repo, "add", "work.yaml")
    real = guards._run

    def run(args, cwd, timeout=10, **kw):
        if args[:2] == ["git", "rev-parse"]:
            if failure == "git missing":
                raise FileNotFoundError(2, "The system cannot find the file specified")
            if failure == "timeout":
                raise subprocess.TimeoutExpired(args, timeout)
            return subprocess.CompletedProcess(args, 128, b"", b"fatal: detected dubious ownership in repository\n")
        return real(args, cwd, timeout, **kw)

    monkeypatch.setattr(guards, "_run", run)
    with pytest.raises(guards.GuardError, match="rev-parse"):
        guards.commit_markers(str(repo), [], False)
    assert bash(repo, 'git commit -m "x"') is None   # an error lets the call through, logged
    assert "GuardError" in (paths.ledger_dir() / "errors.log").read_text(encoding="utf-8")


def test_a_git_dir_is_no_worktree(repo):
    """Inside .git, rev-parse says false (exit 0): no worktree, nothing a commit records, no error."""
    assert guards.commit_markers(str(repo / ".git"), [guards.WHOLE_TREE], True) == []


@pytest.mark.parametrize("name,text,hits", [
    ("requirements.txt", f"numpy==1.26\n{MID}\nnumpy==2.0\n", ["requirements.txt:2"]),
    ("constraints.txt", f"pandas>=2.2,<3\n{MID}\n", ["constraints.txt:2"]),
    ("CHANGES.txt", f"Changes\n{MID}\n", []),        # reST: the title no longer than its underline
    ("README.md", f"A longer title\n{MID}\n", []),   # Markdown has no such rule
])
def test_a_txt_heading_needs_reSTs_shape(name, text, hits):
    """Review of #79 (finding 43's cost): a .txt file is a data file too, so a bare ======= left under a line longer
    than it (a half-resolved requirements.txt) is still a marker."""
    assert markers.scan_text(name, text) == hits
    diff = f"+++ b/{name}\n@@ -0,0 +1,3 @@\n" + "".join(f"+{line}\n" for line in text.splitlines())
    assert markers.scan_diff(diff) == hits


def test_removing_a_marker_commits(repo):
    (repo / "work.yaml").write_text(CONFLICT, encoding="utf-8")
    run_git(repo, "add", "work.yaml")
    run_git(repo, "commit", "-m", "broken")
    (repo / "work.yaml").write_text("- {id: wi-a, status: todo}\n- {id: wi-b, status: done}\n", encoding="utf-8")
    assert bash(repo, 'git commit -am "fix"') is None


# --- brain check ----------------------------------------------------------------------------------------------------

@pytest.fixture
def checked(store, monkeypatch, tmp_path):
    """The store fixture's brain, with research_graph check faked green (the graph check passed #189's stale files)."""
    monkeypatch.setattr(graph, "research_graph", lambda *a: 0)
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "no-registry.yaml"))
    return store.parents[1]


def _check(root):
    return cli.main(["--root", str(root), "check"])


@pytest.mark.parametrize("rel", ["notes/graph/nodes/work.yaml", "notes/graph/nodes/_generated_decisions.yaml",
                                 "notes/journal.md", "notes/decisions.md", "records/sessions/2026-11.jsonl"])
def test_brain_check_fails_on_a_marker(checked, rel, capsys):
    f = checked / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text((f.read_text(encoding="utf-8") if f.is_file() else "") + f"{OURS}\nx\n{THEIRS}\n", encoding="utf-8")
    assert _check(checked) == 1
    out = capsys.readouterr().out
    assert f"{f.as_posix()}:" in out and "holds a conflict marker: finish the merge in that file" in out


TICKS = "`" * 3


def _fenced(info: str) -> str:
    return f"# Merge driver\n\nA conflict looks like this:\n\n{TICKS}{info}\n{OURS}\nours\n{MID}\ntheirs\n{THEIRS}\n{TICKS}\n"


@pytest.mark.parametrize("info, hits", [("text conflict-example", []), (" conflict-example", []),
                                        ("text", ["docs/x.md:6", "docs/x.md:8", "docs/x.md:10"]),
                                        ("", ["docs/x.md:6", "docs/x.md:8", "docs/x.md:10"])])
def test_a_fence_tagged_conflict_example_is_an_example(info, hits):
    """The owner's choice of 2026-11-10 (finding 19 of the review of #26): only a fence whose info string holds the
    tag conflict-example passes; an untagged fence, or no fence, is read like the rest of the file."""
    text = _fenced(info)
    assert markers.scan_text("docs/x.md", text) == hits
    added = "".join(f"+{x}\n" for x in text.splitlines())
    assert markers.scan_diff(f"+++ b/docs/x.md\n@@ -0,0 +1,{len(text.splitlines())} @@\n{added}") == hits


def test_the_example_tag_ends_with_its_fence_and_needs_its_opener_in_the_diff():
    after = _fenced("text conflict-example") + f"\n{OURS}\nleft over\n{THEIRS}\n"
    assert markers.scan_text("docs/x.md", after) == ["docs/x.md:13", "docs/x.md:15"]
    assert markers.scan_text("docs/x.txt", _fenced("text conflict-example")) != []   # Markdown files only
    # a hunk that starts inside the fence, its opener out of the context: read as unfenced (fail closed)
    assert markers.scan_diff(f"+++ b/docs/x.md\n@@ -0,0 +6,2 @@\n+{OURS}\n+{THEIRS}\n") == ["docs/x.md:6", "docs/x.md:7"]


def test_a_tagged_example_commits_and_passes_brain_check(repo, checked, capsys):
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "merge.md").write_text(_fenced("text conflict-example"), encoding="utf-8")
    run_git(repo, "add", "-A")
    assert bash(repo, 'git commit -m "docs: a conflict example"') is None
    (checked / "notes" / "journal.md").write_text("# Journal\n\n" + _fenced("text conflict-example"), encoding="utf-8")
    assert _check(checked) == 0
    assert "conflict marker" not in capsys.readouterr().out


def test_brain_check_passes_a_setext_heading_in_the_journal(checked, capsys):
    (checked / "notes" / "journal.md").write_text(f"Journal\n{MID}\n\n## 2026-11-03\n- a\n", encoding="utf-8")
    assert _check(checked) == 0
    assert "conflict marker" not in capsys.readouterr().out
