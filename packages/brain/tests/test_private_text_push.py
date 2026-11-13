"""The private-text advice on a push to a public repo (wi-brain-private-text-prepush, brain.guards.private_text_note):
the lines a push sends that share 8 words or more with the owner's rules or notes on this machine are named in the
session's context, never refused, so that they are reworded in their PR rather than before the tag. Owner Ada, her
invented rules and notes, the public repo acme/engine."""

import io
import json

import pytest
from brain import cli, config, guards, privatetext
from conftest import run_git

RULE = "Never push to the shared branch on a Friday after six in the evening."
NOTE = "The orchard keys sit in the blue drawer of the old desk."


@pytest.fixture
def ada(tmp_path, monkeypatch, make_repo):
    """Ada's brain (a rule and a note), her public engine checkout with a copied rule already on its remote."""
    brain = tmp_path / "ada-brain"
    (brain / "rules").mkdir(parents=True)
    (brain / "rules" / "global.md").write_text(f"# Rules\n\n{RULE}\n", encoding="utf-8")
    (brain / "memory" / "proj").mkdir(parents=True)
    (brain / "memory" / "proj" / "n.md").write_text(NOTE + "\n", encoding="utf-8")
    (brain / config.FILE).write_text(json.dumps({
        "v": 1, "identity": {"owner": "Ada"}, "rules": ["rules/global.md"],
        "public": {"repos": ["acme/engine"], "allow": {"docs/quoted.md": "a quotation the owner allowed"}}}),
        encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(brain / config.FILE))
    repo = make_repo("engine", {"README.md": "# engine\n\nA graph engine.\n",
                                "docs/old.md": f"Already public: {RULE}\n"})
    run_git(repo, "remote", "add", "origin", "https://github.com/acme/engine.git")
    run_git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")   # what the remote has
    return repo


def push(repo, command="git push origin main", tool="Bash"):
    """(the hook's decision, its text) for a push: deny with its reason, advice with its context, or None."""
    out = io.StringIO()
    guards.main(io.StringIO(json.dumps({"tool_name": tool, "tool_input": {"command": command}, "cwd": str(repo)})),
                out)
    if not out.getvalue():
        return None
    hso = json.loads(out.getvalue())["hookSpecificOutput"]
    return hso.get("permissionDecision", "advice"), hso.get("permissionDecisionReason") or hso["additionalContext"]


def stamp(repo):
    assert cli.main(["check", "--public", "--repo", str(repo), "--history"]) == 0


def test_a_push_that_sends_copied_text_gets_advice_never_a_refusal(ada, make_repo, brain_home):
    (brain_home / "ledger").mkdir(parents=True)
    make_repo.commit(ada, {"docs/new.md": "Intro line.\nOurs: never PUSH to the shared\nbranch on a Friday, after "
                                          "six in the evening!\n",
                           "docs/other.md": f"Where? {NOTE}\n"})
    stamp(ada)
    decision, text = push(ada)
    assert decision == "advice" and text.startswith("brain guard, advice (nothing refused): this push sends 2 passage")
    assert "docs/new.md:2 (from rules/global.md)" in text and "docs/other.md:1 (from memory/proj/n.md)" in text
    assert "docs/old.md" not in text          # the remote has it already: an earlier push's
    assert RULE not in text and NOTE not in text   # it names where, never the text
    rows = [json.loads(line) for f in (brain_home / "ledger").glob("guards-*.jsonl")
            for line in f.read_text(encoding="utf-8").splitlines()]
    assert ("public", "private-text", "warned") in {(r["guard"], r["check"], r["decision"]) for r in rows}


def test_the_refusal_comes_first_and_the_advice_only_on_a_push_that_passes(ada, make_repo):
    make_repo.commit(ada, {"docs/new.md": RULE + "\n"})
    decision, text = push(ada)   # not stamped: refused, as before
    assert decision == "deny" and "brain check --public --history" in text


@pytest.mark.parametrize("command", ["git push https://github.com/acme/other.git main", "git status",
                                     "git push origin --delete old"])
def test_no_advice_for_another_repo_or_what_sends_nothing(ada, make_repo, command):
    make_repo.commit(ada, {"docs/new.md": RULE + "\n"})
    stamp(ada)
    assert push(ada, command) is None


def test_no_advice_for_an_allowed_file_or_new_words(ada, make_repo):
    make_repo.commit(ada, {"docs/quoted.md": RULE + "\n", "docs/mine.md": "Pushing late in the week is avoided here.\n"})
    stamp(ada)
    assert push(ada) is None


def test_the_terminal_panel_and_powershell_get_it_too(ada, make_repo):
    make_repo.commit(ada, {"docs/new.md": RULE + "\n"})
    stamp(ada)
    assert push(ada, tool="PowerShell")[0] == "advice"
    out = io.StringIO()
    guards.main(io.StringIO(json.dumps({"tool_name": "mcp__terminal__run_in_terminal",
                                        "tool_input": {"command": "git push origin main", "cwd": str(ada)},
                                        "cwd": str(ada)})), out)
    assert "advice (nothing refused)" in out.getvalue()


def test_a_failing_scan_lets_the_push_through_and_is_logged(ada, make_repo, brain_home, monkeypatch):
    make_repo.commit(ada, {"docs/new.md": RULE + "\n"})
    stamp(ada)
    monkeypatch.setattr(privatetext, "index", lambda cfg: 1 / 0)
    assert push(ada) is None
    assert "ZeroDivisionError" in (brain_home / "ledger" / "errors.log").read_text(encoding="utf-8")


def test_no_rules_or_notes_no_advice(ada, make_repo, monkeypatch):
    make_repo.commit(ada, {"docs/new.md": RULE + "\n"})
    stamp(ada)
    monkeypatch.setattr(privatetext, "sources", lambda cfg: [])
    assert push(ada) is None


def test_many_passages_are_counted_past_the_ones_named(ada, make_repo):
    make_repo.commit(ada, {f"docs/n{i}.md": RULE + "\n" for i in range(7)})
    stamp(ada)
    text = push(ada)[1]
    assert "this push sends 7 passage(s)" in text and "; and 2 more." in text


# --- found by the review of the PR -----------------------------------------------------------------------------------

def test_a_push_that_adds_no_line_builds_no_index(ada, make_repo, monkeypatch):
    stamp(ada)   # HEAD is what the remote has: nothing new
    monkeypatch.setattr(privatetext, "hashed_index", lambda cfg: 1 / 0)
    assert push(ada) is None


def test_the_index_is_cached_as_hashes(ada, make_repo, brain_home, monkeypatch):
    make_repo.commit(ada, {"docs/new.md": RULE + "\n"})
    stamp(ada)
    assert push(ada)[0] == "advice"
    cache = (brain_home / "cache" / "private-text.json").read_text(encoding="utf-8")
    assert "shared branch" not in cache and "orchard" not in cache   # hashes and source paths only
    monkeypatch.setattr(privatetext, "index", lambda cfg: 1 / 0)       # the cache answers
    assert push(ada)[0] == "advice"


def test_two_hunks_never_join_into_one_passage(ada, make_repo):
    lines = [f"filler {i}" for i in range(20)]
    make_repo.commit(ada, {"docs/split.md": "\n".join(lines) + "\n"})
    run_git(ada, "update-ref", "refs/remotes/origin/main", "HEAD")   # the remote has the filler
    lines[2], lines[15] = "Never push to the shared branch", "on a Friday after six"   # two hunks, 6 and 5 words
    make_repo.commit(ada, {"docs/split.md": "\n".join(lines) + "\n"})
    stamp(ada)
    assert push(ada) is None
    lines[3] = "on a Friday after six"   # adjacent: one run, one passage
    make_repo.commit(ada, {"docs/split.md": "\n".join(lines) + "\n"})
    stamp(ada)
    assert "docs/split.md:3 (from rules/global.md)" in push(ada)[1]


def test_a_url_remote_excludes_only_what_that_repo_has(ada, make_repo):
    run_git(ada, "update-ref", "refs/remotes/mirror/main", "HEAD")
    run_git(ada, "remote", "add", "mirror", "https://code.example/ada/mirror.git")
    make_repo.commit(ada, {"docs/new.md": RULE + "\n"})
    run_git(ada, "update-ref", "refs/remotes/mirror/main", "HEAD")   # the private mirror has it, the public repo not
    stamp(ada)
    assert push(ada, "git push https://github.com/acme/engine.git main")[0] == "advice"


def test_the_owner_turns_the_advice_off(ada, make_repo, monkeypatch):
    make_repo.commit(ada, {"docs/new.md": RULE + "\n"})
    stamp(ada)
    monkeypatch.setenv(guards.ALLOW_ENV, "public:private-text")
    assert push(ada) is None


def test_a_git_failure_is_logged_never_read_as_nothing(ada, make_repo, brain_home, monkeypatch):
    make_repo.commit(ada, {"docs/new.md": RULE + "\n"})
    stamp(ada)
    real = guards._git_out
    monkeypatch.setattr(guards, "_git_out", lambda repo, *a, strict=False: (
        (_ for _ in ()).throw(guards.GuardError("git log: timeout")) if "log" in a else real(repo, *a, strict=strict)))
    assert push(ada) is None
    assert "GuardError" in (brain_home / "ledger" / "errors.log").read_text(encoding="utf-8")
