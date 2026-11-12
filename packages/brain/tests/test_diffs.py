"""brain.diffs, the engine's one unified-diff reader (wi-brain-diff-parser; the lesson les-brain-unescaped-format):
headers only from the diff's structure, git's names as it writes them, the user's config neutralised, tested once on
real diffs and through each reader that relies on it."""

import pytest

from brain import actions, diffs, guards, impact, markers
from brain.inventory import git
from conftest import run_git

MID = "=" * 7
SIDE = "<" * 7


# --- the parser on hand-written patches: each awkward shape once ---

def test_a_content_line_starting_with_dashes_or_pluses_is_never_a_header():
    """brain #35 finding 3 and #37 finding 9: in a -U0 hunk the deleted line '-- x' reads '--- x' and the added
    '++ y' reads '+++ y'; the hunk's counts say they are content."""
    patch = ("diff --git a/q.sql b/q.sql\nindex 1..2 100644\n--- a/q.sql\n+++ b/q.sql\n"
             "@@ -2 +2 @@\n--- the comment\n+++ added\n")
    [f] = diffs.parse(patch)
    assert (f.old, f.new, f.status) == ("q.sql", "q.sql", "M")
    assert [(ln.kind, ln.old, ln.new, ln.text) for ln in f.hunks[0].lines] == [
        ("-", 2, None, "-- the comment"), ("+", None, 2, "++ added")]


def test_a_path_with_a_space_loses_gits_tab_and_a_quoted_one_is_unquoted():
    """brain #37 finding 14: git ends a ---/+++ name holding a space with a TAB; a name with a quote, a control
    character or (core.quotepath on) a non-ASCII byte is C-quoted."""
    patch = ('diff --git a/my notes.md b/my notes.md\n--- a/my notes.md\t\n+++ b/my notes.md\t\n@@ -0,0 +1 @@\n+x\n'
             'diff --git "a/caf\\303\\251 \\"q\\".md" "b/caf\\303\\251 \\"q\\".md"\n'
             '--- "a/caf\\303\\251 \\"q\\".md"\n+++ "b/caf\\303\\251 \\"q\\".md"\n@@ -1 +1 @@\n-a\n+b\n')
    assert [(f.old, f.new) for f in diffs.parse(patch)] == [("my notes.md", "my notes.md"),
                                                             ('café "q".md', 'café "q".md')]


def test_added_deleted_renamed_binary_and_mode_only_files():
    patch = ("diff --git a/new.txt b/new.txt\nnew file mode 100644\nindex 0..1\n--- /dev/null\n+++ b/new.txt\n"
             "@@ -0,0 +1,2 @@\n+one\n+two\n"
             "diff --git a/gone.txt b/gone.txt\ndeleted file mode 100644\n--- a/gone.txt\n+++ /dev/null\n"
             "@@ -1 +0,0 @@\n-bye\n"
             "diff --git a/old name.py b/new name.py\nsimilarity index 100%\nrename from old name.py\n"
             "rename to new name.py\n"
             "diff --git a/logo.png b/logo.png\nnew file mode 100644\nindex 0..1\nBinary files /dev/null and "
             "b/logo.png differ\n"
             "diff --git a/run.sh b/run.sh\nold mode 100644\nnew mode 100755\n")
    files = diffs.parse(patch)
    assert [(f.status, f.old, f.new, f.binary) for f in files] == [
        ("A", "", "new.txt", False), ("D", "gone.txt", "", False), ("R", "old name.py", "new name.py", False),
        ("A", "", "logo.png", True), ("M", "run.sh", "run.sh", False)]
    assert files[0].added() == [(1, "one"), (2, "two")] and files[1].hunks[0].new_span() is None
    assert files[4].mode == "100755"
    assert diffs.added_lines(patch) == {"new.txt": [(1, "one"), (2, "two")]}   # a deletion adds nothing


def test_context_lines_numbers_no_newline_and_a_dropped_blank():
    """An empty line inside a hunk is a context line whose space diff.suppressBlankEmpty dropped; '\\ No newline at
    end of file' is no line; a missing count is 1."""
    patch = ("diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -3,4 +3,4 @@ def f():\n x\n\n-y\n+z\n"
             "\\ No newline at end of file\n w\n@@ -9 +9 @@\n-p\n+q\n")
    [f] = diffs.parse(patch)
    assert [(ln.kind, ln.old, ln.new) for ln in f.hunks[0].lines] == [
        (" ", 3, 3), (" ", 4, 4), ("-", 5, None), ("+", None, 5), (" ", 6, 6)]
    assert [(h.old_start, h.old_count, h.new_start, h.new_count) for h in f.hunks] == [(3, 4, 3, 4), (9, 1, 9, 1)]


def test_lines_split_on_newlines_only_and_a_cr_dropped():
    """str.splitlines would cut a content line at a form feed: the hunk's counts would then read the rest as a
    header."""
    patch = "--- a/x\r\n+++ b/x\r\n@@ -0,0 +1,2 @@\r\n+page\x0cbreak\r\n+--- not a header\r\n"
    [f] = diffs.parse(patch)
    assert f.added() == [(1, "page\x0cbreak"), (2, "--- not a header")]


def test_a_plain_diff_u_with_timestamps_and_no_prefixes():
    patch = ("--- notes.txt\t2026-11-12 10:00:00.000 +0100\n+++ notes.txt\t2026-11-12 11:00:00.000 +0100\n"
             "@@ -1,2 +1,2 @@\n a\n-b\n+c\n--- b.txt\t2026-11-12\n+++ b.txt\t2026-11-12\n@@ -1 +1 @@\n-d\n+e\n")
    files = diffs.parse(patch, prefixes=("", ""))
    assert [(f.old, f.new, f.added()) for f in files] == [("notes.txt", "notes.txt", [(2, "c")]),
                                                          ("b.txt", "b.txt", [(1, "e")])]


def test_a_bare_plus_header_and_a_spaced_mode_change():
    """A patch cut to its +++ line still opens a file; a mode change of a name with a space has only the diff --git
    line to name it."""
    patch = ("+++ b/x.md\n@@ -0,0 +1 @@\n+one\n"
             "diff --git a/my run.sh b/my run.sh\nold mode 100644\nnew mode 100755\n")
    assert [(f.old, f.new, f.added()) for f in diffs.parse(patch)] == [("", "x.md", [(1, "one")]),
                                                                       ("my run.sh", "my run.sh", [])]


def test_a_combined_diff_of_a_merge():
    """git show of a merge: one column per parent; a line is in the result unless a column says '-'."""
    patch = ("diff --cc f.txt\nindex 1,2..3\n--- a/f.txt\n+++ b/f.txt\n@@@ -1,3 -1,2 +1,3 @@@\n  same\n"
             "+ from ours\n +from theirs\n- gone\n")
    [f] = diffs.parse(patch)
    assert f.combined and f.new == "f.txt"
    assert [(ln.kind, ln.new) for ln in f.hunks[0].lines] == [(" ", 1), ("+", 2), ("+", 3), ("-", None)]


def test_a_truncated_hunk_gives_way_to_the_next_file():
    patch = ("diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1,5 +1,5 @@\n-x\n+y\n"
             "diff --git a/b b/b\n--- a/b\n+++ b/b\n@@ -0,0 +1 @@\n+z\n")
    assert diffs.added_lines(patch) == {"a": [(1, "y")], "b": [(1, "z")]}


def test_a_git_log_patch_keeps_each_commits_head():
    log = ("\x00abc123\n\ndiff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -0,0 +1 @@\n+one\n"
           "\x00def456\n\ndiff --git a/y b/y\n--- a/y\n+++ b/y\n@@ -1 +1 @@\n-two\n+--- three\n")
    assert [(head, [(f.new, f.added()) for f in files]) for head, files in diffs.log_records(log)] == [
        ("abc123", [("x", [(1, "one")])]), ("def456", [("y", [(1, "--- three")])])]


def test_argv_forces_the_prefixes_and_neutralises_the_config():
    a = diffs.argv("diff", "-U0", "HEAD")
    assert a[:a.index("diff")] == list(diffs.CONFIG) and a[-2:] == ["-U0", "HEAD"]
    assert {"--src-prefix=a/", "--dst-prefix=b/", "--no-ext-diff", "--no-textconv", "--no-color"} <= set(a)


# --- real diffs, under a hostile git config, through every reader ---

HOSTILE = {"diff.noprefix": "true", "diff.mnemonicPrefix": "true", "diff.relative": "true",
           "diff.suppressBlankEmpty": "true", "color.diff": "always", "color.ui": "always",
           "diff.external": "brain-no-such-diff-tool", "core.quotepath": "true"}


@pytest.fixture
def hostile(make_repo, monkeypatch):
    """A repo whose diff the user's config would reshape every way it can, run from a subfolder (diff.relative)."""
    repo = make_repo("hostile", {"docs/my notes.md": "# Notes\n\nkeep\n-- the comment\n", "sub/keep.txt": "k\n",
                                 "café.md": "a\n", "graph/nodes/items.yaml": "- {id: wi-x, type: WorkItem}\n"})
    base = run_git(repo, "rev-parse", "HEAD").strip()
    make_repo.write(repo, {"docs/my notes.md": f"# Notes\n\nkeep\n++ added\n{SIDE} ours\n",
                           "café.md": "b\n", "graph/nodes/items.yaml": "- {id: wi-x, type: WorkItem, status: done}\n"})
    for i, (k, v) in enumerate(HOSTILE.items()):
        monkeypatch.setenv(f"GIT_CONFIG_KEY_{i}", k)
        monkeypatch.setenv(f"GIT_CONFIG_VALUE_{i}", v)
    monkeypatch.setenv("GIT_CONFIG_COUNT", str(len(HOSTILE)))
    return repo, base


def test_a_real_diff_under_a_hostile_config_reads_whole_repo_paths(hostile):
    repo, base = hostile
    assert run_git(repo / "sub", "diff", "--no-ext-diff", "-U0", base) == ""   # the config bites: diff.relative
    patch = git(repo / "sub", *diffs.argv("diff", "-U0", base))   # read as UTF-8, as the engine reads it
    files = {f.path: f for f in diffs.parse(patch)}
    assert sorted(files) == ["café.md", "docs/my notes.md", "graph/nodes/items.yaml"]
    assert files["docs/my notes.md"].added() == [(4, "++ added"), (5, f"{SIDE} ours")]
    assert [(ln.kind, ln.text) for ln in files["docs/my notes.md"].hunks[0].lines if ln.kind == "-"] == [
        ("-", "-- the comment")]


def test_every_reader_agrees_on_the_same_hostile_change(hostile):
    """impact's hunks, the public commit check's added lines and the markers guard read one change the same way."""
    repo, base = hostile
    h = impact.hunks(repo, base)
    assert (h["docs/my notes.md"].old_lines, h["docs/my notes.md"].new_lines) == ([(4, 4)], [(4, 5)])
    run_git(repo, "add", "-A")
    patch = git(repo / "sub", *diffs.argv("diff", "--cached", "-U0"))
    assert guards.added_lines(patch)["docs/my notes.md"] == [(4, "++ added"), (5, f"{SIDE} ours")]
    with_context = git(repo / "sub", *diffs.argv("diff", "--cached", *guards.MARKER_DIFF, "HEAD"))
    assert markers.scan_diff(with_context) == ["docs/my notes.md:5"]
    sha = run_git(repo, "commit", "-qm", "close").strip() or run_git(repo, "rev-parse", "HEAD").strip()
    assert actions.changed_items(repo, sha) == ["wi-x"]
