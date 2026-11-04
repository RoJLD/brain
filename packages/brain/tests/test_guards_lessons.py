"""The guards the lessons registry asked for (wi-brain-guard-public-commit, wi-brain-guard-public-chain,
wi-brain-guard-heredoc-backslash): the public check at the commit, the chained check-and-push's hint, and the heredoc
warning."""

import io
import json

import pytest

from brain import cli, config, guards

from conftest import run_git

PUBLIC = {"v": 1, "identity": {"owner": "Ada"},
          "public": {"repos": ["acme/engine"],
                     "deny": {"people": ["Ada"], "repos": ["ada-private"]},
                     "allow": {"LICENSE": "the licence keeps its author's name"}}}


@pytest.fixture
def pub(tmp_path, monkeypatch, make_repo):
    cfg = tmp_path / "ada-brain" / config.FILE
    cfg.parent.mkdir()
    cfg.write_text(json.dumps(PUBLIC), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    monkeypatch.setattr(guards, "gitleaks", lambda repo: None)
    repo = make_repo("engine", {"README.md": "# engine\n", "LICENSE": "MIT License\n\nCopyright (c) 2026 Ada\n"})
    run_git(repo, "remote", "add", "origin", "https://github.com/acme/engine.git")
    return repo


def _refused(repo, command, guard="public"):
    p = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(repo)}
    return [reason for g, _, reason, _ in guards.refusals(p) if g == guard]


# --- the public check at the commit ---

def test_a_commit_naming_the_owner_in_a_public_repo_is_refused(pub):
    (pub / "tests").mkdir()
    (pub / "tests" / "test_x.py").write_text('PR = "ada-private #185"\nOK = "acme #1"\n', encoding="utf-8")
    run_git(pub, "add", "tests/test_x.py")
    (reason,) = _refused(pub, 'git commit -m "tests"')
    assert reason.startswith("git commit refused: tests/test_x.py:1: denied: people term 'Ada' and 1 more")
    assert "acme/engine is a public repo" in reason and "invented people and repos" in reason
    run_git(pub, "reset", "-q")
    (pub / "tests" / "test_x.py").write_text('OK = "acme #1"\n', encoding="utf-8")
    assert not _refused(pub, 'git add -A && git commit -m "tests"')


def test_what_a_git_add_in_the_same_call_stages_is_read(pub):
    (pub / "notes.md").write_text("Written by Ada.\n", encoding="utf-8")
    (reason,) = _refused(pub, 'git add notes.md && git commit -m "notes"')
    assert "notes.md:1: denied: people term 'Ada'" in reason
    (pub / "LICENSE").write_text("MIT License\n\nCopyright (c) 2026 Ada, again\n", encoding="utf-8")
    assert not _refused(pub, 'git commit -am "licence"')  # public.allow excepts the licence


def test_a_private_repo_commits_freely(pub):
    run_git(pub, "remote", "set-url", "origin", "https://github.com/acme/private.git")
    (pub / "notes.md").write_text("Written by Ada.\n", encoding="utf-8")
    assert not _refused(pub, 'git add notes.md && git commit -m "notes"')


def test_added_lines_number_each_file():
    diff = ("diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1,0 +2,2 @@\n+one\n+two\n"
            "diff --git a/y b/y\n--- /dev/null\n+++ b/y\n@@ -0,0 +1 @@\n+new\n")
    assert guards.added_lines(diff) == {"x": [(2, "one"), (3, "two")], "y": [(1, "new")]}
    tab = "diff --git a/a b b/a b\n--- a/a b\t\n+++ b/a b\t\n@@ -0,0 +1,2 @@\n+++ not a header\n+x\n"
    assert guards.added_lines(tab) == {"a b": [(1, "++ not a header"), (2, "x")]}


# --- the review of #37 ---

def test_git_add_u_stages_no_untracked_file(pub):
    (pub / "notes.md").write_text("Written by Ada.\n", encoding="utf-8")   # untracked: git add -u leaves it out
    (pub / "README.md").write_text("# engine\n\nmore\n", encoding="utf-8")
    assert not _refused(pub, 'git add -u && git commit -m "readme"')
    assert _refused(pub, 'git add . && git commit -m "all"')


def test_an_untracked_file_is_judged_by_its_repo_path_and_file_checks(pub):
    (pub / "docs").mkdir()
    (pub / "LICENSE").unlink()
    run_git(pub, "rm", "-q", "--cached", "LICENSE")
    (pub / "LICENSE").write_text("Copyright (c) 2026 Ada\n", encoding="utf-8")   # untracked, allowed by its path
    assert not _refused(pub / "docs", "git add ../LICENSE && git commit -m licence")
    (pub / ".env").write_text("X=1\n", encoding="utf-8")
    (reason,) = _refused(pub, "git add .env && git commit -m env")
    assert ".env: file:" in reason


def test_a_private_fork_with_a_public_upstream_commits_freely(pub):
    run_git(pub, "remote", "rename", "origin", "upstream")
    run_git(pub, "remote", "add", "origin", "https://github.com/acme/private.git")
    (pub / "notes.md").write_text("Written by Ada.\n", encoding="utf-8")
    assert not _refused(pub, 'git add notes.md && git commit -m "notes"')


# --- the chained check and push ---

def test_a_chained_check_and_push_is_told_to_split(pub):
    (plain,) = _refused(pub, "git push origin main")
    assert guards.CHAIN_HINT not in plain
    (chained,) = _refused(pub, f'brain check --public --repo "{pub}" --history && git push origin main')
    assert chained.endswith(guards.CHAIN_HINT)
    assert cli.main(["check", "--public", "--repo", str(pub), "--history"]) == 0
    assert not _refused(pub, "git push origin main")  # stamped: the next call's push passes


# --- the heredoc warning ---

def _hook(command, windows=True):
    return guards.heredoc_note({"tool_name": "Bash", "tool_input": {"command": command}}, windows=windows)


BS2 = "\\" * 2


def test_a_heredoc_with_a_doubled_backslash_feeding_python_is_warned():
    script = "python - <<'EOF'\nprint('a" + BS2 + "nb')\nEOF"
    assert _hook(script) == guards.HEREDOC_NOTE
    assert _hook("cat > f.sh <<'EOF'\ngrep '" + BS2 + "d'\nEOF")
    assert _hook("tee f.txt <<EOF\nx" + BS2 + "y\nEOF")
    assert _hook("python3 <<'EOF'\nprint('a" + BS2 + "nb')\nEOF")      # an interpreter fed by the heredoc itself
    assert _hook("node <<EOF\nconsole.log('" + BS2 + "')\nEOF")


def test_no_warning_without_the_risk():
    assert _hook("python - <<'EOF'\nprint('a')\nEOF") is None            # no doubled backslash
    assert _hook("git commit -F - <<'EOF'\nmsg " + BS2 + "\nEOF") is None  # git reads it, writes no file
    assert _hook("python - <<'EOF'\nx\nEOF\necho '" + BS2 + "'") is None  # after the heredoc's end
    assert _hook("python - <<'EOF'\nprint('a" + BS2 + "nb')\nEOF", windows=False) is None
    assert guards.heredoc_note({"tool_name": "PowerShell", "tool_input": {"command": "x"}}, windows=True) is None


def test_the_hook_prints_the_warning_as_context_and_records_it(monkeypatch, brain_home):
    monkeypatch.setattr(guards, "heredoc_note", lambda payload, windows=None: guards.HEREDOC_NOTE)
    (brain_home / "ledger").mkdir(parents=True)
    out = io.StringIO()
    p = {"tool_name": "Bash", "tool_input": {"command": "python - <<'EOF'\nEOF"}, "cwd": str(brain_home),
         "session_id": "s-9"}
    assert guards.main(io.StringIO(json.dumps(p)), out) == 0
    hso = json.loads(out.getvalue())["hookSpecificOutput"]
    assert hso == {"hookEventName": "PreToolUse", "additionalContext": guards.HEREDOC_NOTE}
    (rec,) = [json.loads(x) for f in (brain_home / "ledger").glob("guards-*.jsonl") for x in f.read_text().splitlines()]
    assert (rec["guard"], rec["check"], rec["decision"], rec["session_id"]) == ("heredoc", "backslash", "warned", "s-9")
