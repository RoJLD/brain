import json
from datetime import datetime, timedelta, timezone

from conftest import git_init, run_git

from brain import actions, schema

META = {"session_id": "s-1", "tool": "claude-code", "model": "claude-opus-5-5", "effort": "xhigh"}


def test_parse_command_follows_cd_dash_c_and_variables(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    ops = actions.parse_command(
        f'W="{tmp_path.as_posix()}/a"; cd "$W" && git -C b commit -m "x; git push" && git push -u origin feat 2>&1 '
        f"| tail -1; gh pr create --fill",
        tmp_path)
    assert [(o["op"], o["dir"].name) for o in ops] == [("commit", "b"), ("push", "a"), ("push", "a"),
                                                       ("pr-create", "a")]
    assert actions.parse_command("echo git commit", tmp_path) == []
    assert actions.parse_command("git status && git log -1", tmp_path) == []


def test_commit_records_items_and_adrs(git_repo):
    run_git(git_repo, "remote", "add", "origin", "https://someone:" + "x" * 12 + "@github.com/RoJLD/demo.git")
    work = git_repo / "notes" / "graph" / "nodes" / "work.yaml"
    work.write_text(work.read_text(encoding="utf-8").replace("priority: P1", "priority: P0"), encoding="utf-8")
    with open(git_repo / "notes" / "decisions.md", "a", encoding="utf-8") as fh:
        fh.write("\n## 2026-10-31 — Registres DDR, SR et AR (ADR)\n\nBody.\n")
    run_git(git_repo, "commit", "-qam", "Records and capture")
    ars = actions.from_tool_call("git commit -qam 'Records and capture'", git_repo, {"stdout": ""}, META)
    commit, adr = ars
    sha = run_git(git_repo, "rev-parse", "HEAD").strip()
    assert commit["kind"] == "commit" and commit["sha"] == sha and commit["repo"] == "RoJLD/demo"
    assert commit["branch"] == "main" and commit["subject"] == "Records and capture"
    assert commit["items"] == ["wi-a"]
    assert adr["kind"] == "adr" and adr["adr"] == {"id": "adr-2026-10-31-registres-ddr-sr-et-ar-adr",
                                                   "title": "Registres DDR, SR et AR (ADR)", "file": "notes/decisions.md"}
    assert commit["session"]["model"] == "claude-opus-5-5"
    for a in ars:
        assert schema.check("ar", a) == ([], [])


def test_old_head_is_not_a_new_commit(git_repo):
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    assert actions.from_tool_call("git commit -m x", git_repo, {}, META, now=later) == []


def test_push_needs_evidence(git_repo, tmp_path):
    out = "To https://github.com/RoJLD/demo.git\n   1234567..89abcde  main -> main\n"
    (push,) = actions.from_tool_call("git push", git_repo, {"stderr": out}, META)
    assert push["refs"] == ["main -> main"] and push["sha"] == "89abcde" and push["repo"] == "RoJLD/demo"
    assert actions.from_tool_call("git push", git_repo, {"stderr": "Everything up-to-date"}, META) == []
    # quiet push: the remote-tracking ref equals the local branch
    remote = tmp_path / "remote.git"
    git_init(remote, bare=True)
    run_git(git_repo, "remote", "add", "origin", str(remote))
    run_git(git_repo, "push", "-q", "-u", "origin", "main")
    (quiet,) = actions.from_tool_call("git push -q -u origin main", git_repo, {"stdout": ""}, META)
    assert quiet["branch"] == "main" and quiet["sha"] == run_git(git_repo, "rev-parse", "HEAD").strip()
    assert actions.from_tool_call("git push -q", git_repo, {}, META, source="transcript") == []


def test_pull_requests(tmp_path):
    out = {"stdout": "https://github.com/RoJLD/demo/pull/12\n"}
    (pr,) = actions.from_tool_call('gh pr create --title "x"', tmp_path, out, META)
    assert pr["id"].endswith("-pr-demo-12-created") and pr["repo"] == "RoJLD/demo"
    chain = actions.from_tool_call("gh pr create --fill && gh pr merge --squash", tmp_path,
                                   {"stdout": "https://github.com/RoJLD/demo/pull/13\n",
                                    "gitOperation": {"pr": {"number": 13, "action": "created",
                                                            "url": "https://github.com/RoJLD/demo/pull/13"}}}, META)
    assert [(a["pr"]["number"], a["pr"]["action"]) for a in chain] == [(13, "created"), (13, "merged")]
    (merged,) = actions.from_tool_call("gh pr merge 14 --repo RoJLD/other --merge", tmp_path, {}, META)
    assert merged["repo"] == "RoJLD/other" and merged["pr"] == {"number": 14, "action": "merged"}
    (named,) = actions.from_tool_call('R=RoJLD/third; gh pr merge 15 --repo "$R" --merge', tmp_path, {}, META)
    assert named["repo"] == "RoJLD/third"
    assert actions.from_tool_call("gh pr merge 16 --repo RoJLD/$1 --merge", tmp_path, {}, META) == []
    assert actions.from_tool_call("gh pr create --fill", tmp_path, {"stdout": "no url"}, META) == []
    assert actions.from_tool_call("gh pr create --fill", tmp_path, out, META, family="git") == []


def _call(tuid, command, cwd, t_use, t_result, stdout="", branch="main"):
    """The two transcript records of one Bash call: the tool use and its result."""
    use = {"type": "assistant", "sessionId": "s-1", "timestamp": t_use, "cwd": str(cwd), "gitBranch": branch,
           "version": "2.1.320", "entrypoint": "cli",
           "message": {"id": f"msg_{tuid}", "model": "claude-opus-5-5", "role": "assistant",
                       "content": [{"type": "tool_use", "id": tuid, "name": "Bash", "input": {"command": command}}]}}
    result = {"type": "user", "sessionId": "s-1", "timestamp": t_result, "cwd": str(cwd), "gitBranch": branch,
              "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tuid, "content": "ok"}]},
              "toolUseResult": {"stdout": stdout, "stderr": ""}}
    return [use, result]


def test_transcript_commits_are_found_in_the_history(git_repo, tmp_path, monkeypatch):
    run_git(git_repo, "remote", "add", "origin", "https://github.com/RoJLD/demo.git")

    def commit(when, *args):
        monkeypatch.setenv("GIT_COMMITTER_DATE", when)
        run_git(git_repo, "commit", "-q", *args)
        return run_git(git_repo, "rev-parse", "HEAD").strip()

    work = git_repo / "notes" / "graph" / "nodes" / "work.yaml"
    work.write_text(work.read_text(encoding="utf-8").replace("priority: P1", "priority: P0"), encoding="utf-8")
    with open(git_repo / "notes" / "decisions.md", "a", encoding="utf-8") as fh:
        fh.write("\n## 2026-10-30 — Backfill (ADR)\n\nBody.\n")
    first = commit("2026-10-30T10:00:05Z", "-am", 'Records "and" capture')
    second = commit("2026-10-30T10:00:06Z", "--allow-empty", "-m", "Second one")
    gone = commit("2026-10-30T10:05:05Z", "--allow-empty", "-m", "From a removed worktree")
    commit("2026-10-30T10:10:02Z", "--allow-empty", "-m", "Merge x")
    lines = (_call("toolu_c1", 'git commit -qam "Records \\"and\\" capture" && git commit -q --allow-empty -m '
                               "'Second one'", git_repo, "2026-10-30T10:00:00Z", "2026-10-30T10:00:10Z")
             + _call("toolu_c2", f'cd "{(tmp_path / "gone-wt").as_posix()}" && git commit -qm "From a removed worktree"',
                     tmp_path, "2026-10-30T10:05:00Z", "2026-10-30T10:05:10Z")
             + _call("toolu_c3", "git commit -q --no-edit", git_repo, "2026-10-30T10:10:00Z", "2026-10-30T10:10:05Z")
             + _call("toolu_c4", 'git commit -qm "Second one"', git_repo, "2026-10-30T11:00:00Z",
                     "2026-10-30T11:00:05Z"))
    t = tmp_path / "t.jsonl"
    t.write_text("".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")
    ars = actions.from_transcript(t, history=actions.History([git_repo]))
    commits = {a["sha"]: a for a in ars if a["kind"] == "commit"}
    assert set(commits) == {first, second, gone}  # not the --no-edit merge, not a commit outside the call's time
    assert commits[first]["subject"] == 'Records "and" capture' and commits[first]["items"] == ["wi-a"]
    assert commits[first]["branch"] == "main" and commits[first]["repo"] == "RoJLD/demo"
    assert commits[first]["id"] == f"ar-2026-10-30-commit-demo-{first[:10]}"  # the hook's id: one action, one id
    assert "branch" not in commits[gone] and commits[gone]["at"] == "2026-10-30T10:05:05Z"
    (adr,) = [a for a in ars if a["kind"] == "adr"]
    assert adr["sha"] == first and adr["adr"]["id"] == "adr-2026-10-30-backfill-adr"
    assert actions.from_transcript(t) == [a for a in ars if a["kind"] != "commit" or a["sha"] != gone]
    for a in ars:
        assert schema.check("ar", a) == ([], [])


def test_push_evidence_on_a_transcript(git_repo, tmp_path):
    new = ("remote: \nremote: Create a pull request for 'feat/x' on GitHub by visiting:\n"
           "remote:      https://github.com/RoJLD/demo/pull/new/feat/x        \nremote: \n")
    (push,) = actions.from_tool_call("git push -q -u origin feat/x 2>&1 | tail -4", tmp_path, {"stdout": new}, META,
                                     source="transcript", tool_use_id="toolu_abcd1234")
    assert push["repo"] == "RoJLD/demo" and push["branch"] == "feat/x" and "sha" not in push
    assert push["id"] == "ar-" + push["at"][:10] + "-push-demo-feat-x-abcd1234"
    rejected = "To https://github.com/RoJLD/demo.git\n ! [rejected]        main -> main (fetch first)\n"
    assert actions.from_tool_call("git push", git_repo, {"stderr": rejected}, META, source="transcript") == []
    # a transcript's push takes no SHA from today's branch: a rerun finds the same id
    created = "To https://github.com/RoJLD/demo.git\n * [new branch]      main -> main\n"
    (p,) = actions.from_tool_call("git push -u origin main", git_repo, {"stderr": created}, META,
                                  source="transcript", tool_use_id="toolu_efgh5678")
    assert "sha" not in p and p["id"].endswith("-push-demo-main-efgh5678")


def test_remote_repo_names_only_published_remotes():
    assert actions.remote_repo("https://user:" + "x" * 12 + "@github.com/RoJLD/demo.git") == "RoJLD/demo"
    assert actions.remote_repo("git@github.com:RoJLD/demo.git") == "RoJLD/demo"
    assert actions.remote_repo("ssh://git@gitlab.example/group/sub/name") == "sub/name"
    for local in ("D:/work/brain", "/c/Users/someone/scratchpad/cb-audit", "file:///srv/git/demo.git", ""):
        assert actions.remote_repo(local) == "", local


def test_tag(git_repo):
    run_git(git_repo, "tag", "-a", "v0.1.0", "-m", "first")
    (tag,) = actions.from_tool_call('git tag -a v0.1.0 -m "first"', git_repo, {}, META)
    assert tag["tag"] == "v0.1.0" and tag["sha"] == run_git(git_repo, "rev-parse", "HEAD").strip()
    assert actions.from_tool_call("git tag -l", git_repo, {}, META) == []
