import json
import os
import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest
import yaml

from brain import __version__, cli, permissions, queue

INSTALLER = Path(__file__).resolve().parents[1] / "installer" / "install.ps1"
ENGINE = ("# header: what this file is\n\n# brain up: start the stacks (Ada, 2026-11-01)\nBash(brain up)\n"
          "Bash(brain up *)\n# a comment after the rules starts a new block\nPowerShell(brain up)\n")
HEAD = ("v: 1\nprofiles: {lite: {title: the lite profile}}\n"
        "machines: {BOX1: {title: a workstation, profile: lite}, BOX2: {title: another}}\n"
        "tenants: {acme: {title: a client, projects: [app]}}\n"
        "sessions: {review: {title: a review session, project: mine}, deep: {title: its sub-session, parent: review}}\n")
WHY = "why: \"a reason long enough\""


def _brain(tmp_path, monkeypatch, rules: str = "", head: str = HEAD, engine: str = ENGINE):
    """A personal brain at tmp_path/brain: two projects (mine at the root; app, a production checkout), allow-rules.txt,
    permissions.yaml with ``rules``; this machine is BOX1 and Claude Code's home is tmp_path/claude-home."""
    root = tmp_path / "brain"
    (root / "notes" / "graph").mkdir(parents=True)
    (root / "app").mkdir()
    (root / "projects.yaml").write_text("mine: {root: .}\napp: {root: app, production: [.]}\n", encoding="utf-8")
    (root / permissions.ENGINE_FILE).write_text(engine, encoding="utf-8")
    (root / permissions.FILE).write_text(head + "rules:\n" + rules, encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    monkeypatch.setenv(permissions.ENV, str(root / permissions.FILE))
    monkeypatch.setenv("COMPUTERNAME", "BOX1")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    return root


def _rules(*lines: str) -> str:
    return "".join(f"  - {{{line}, {WHY}}}\n" for line in lines)


# --- rules: syntax, narrowness, matching ---

def test_shell_is_bash_and_powershell_and_a_trailing_colon_star_is_a_wildcard():
    assert permissions.atoms("Shell(docker inspect *)") == ["Bash(docker inspect *)", "PowerShell(docker inspect *)"]
    assert permissions.atoms("Bash(npm run:*)") == ["Bash(npm run *)"]
    assert permissions.atoms("Read") == ["Read"]
    assert permissions.parse("Bash()") is None and permissions.parse("not a rule") is None


@pytest.mark.parametrize("rule, broad", [
    ("Bash", True), ("Shell(*)", True), ("Bash(* --version)", True), ("Bash(python *)", True),
    ("Bash(C:/Python312/python.exe *)", True), ("PowerShell(pwsh -Command *)", True), ("Bash(npm run *)", True),
    ("Agent(Explore)", True), ("Edit", True), ("Read", True), ("mcp__*", True),
    ("Bash(python -m pytest)", False), ("Bash(npm test)", False), ("Bash(git status *)", False),
    ("Read(./docs/**)", False), ("WebFetch(domain:example.com)", False), ("Bash(brain up *)", False),
    ("mcp__gitnexus__*", False),
    # the review's bypasses (2026-11-02): the :* form, other interpreter and runner shapes, paths, domains
    ("Bash(python:*)", True), ("Shell(sudo:*)", True), ("Bash(python*)", True), ("Bash(python3.12 *)", True),
    ('Bash("python" *)', True), ("Bash(VAR=1 python *)", True), ("PowerShell(saps *)", True),
    ("PowerShell(icm *)", True), ("Bash(npm *)", True), ("Bash(npm r*)", True), ("Bash(uv *)", True),
    ("Edit(**)", True), ("Edit(//**)", True), ("Read(~/**)", True), ("Write(/**)", True), ("Edit(//c/**)", True),
    ("WebFetch(domain:*)", True), ("Bash(npm test *)", False), ("Edit(./src/**)", False), ("Bash(git status:*)", False),
])
def test_broad_allow_rules(rule, broad):
    assert bool(permissions.broad(rule)) is broad


@pytest.mark.parametrize("rule, tool, text, hit", [
    ("Bash(git push *)", "Bash", "git push origin main", True),
    ("Bash(git push *)", "Bash", "git push", True),          # a trailing ' *' matches the bare command too
    ("Bash(ls *)", "Bash", "lsof", False),
    ("Bash(npm test)", "Bash", "npm test --watch", False),   # exact
    ("Bash(gh pr merge * --merge)", "Bash", "gh pr merge 12 -R x/y --merge", True),
    ("PowerShell(brain up *)", "PowerShell", "BRAIN UP docker", True),   # PowerShell is case-insensitive
    ("Bash", "Bash", "anything", True),
    ("Bash(git *)", "PowerShell", "git status", False),
])
def test_matching_follows_claude_code(rule, tool, text, hit):
    assert permissions.matches(rule, tool, text) is hit


# --- the never-grantable categories ---

def test_the_categories_are_the_engines_and_a_file_only_adds(tmp_path):
    cats, errors = permissions.categories({"never": {
        "visibility": {"why": "the owner decides", "find": r"\bgh repo rename\b"},
        "installer": {"find": r"install\.ps1.*-Apply", "why": "the owner runs it", "deny": ["Bash(gh repo delete *)"]},
        "keys": {"find": ""}, "bad": {"why": "no find"}}})
    by = {c.name: c for c in cats}
    assert errors == ["permissions.yaml: never.bad: a new category needs its find pattern"]
    assert [c[0] for c in permissions.NEVER] == list(by)[:len(permissions.NEVER)]
    assert permissions.never_category("gh repo create x --public", cats) == "visibility"   # the engine's
    assert permissions.never_category("gh repo rename y", cats) == "visibility"             # added
    assert permissions.never_category("powershell -File install.ps1 -Apply", cats) == "installer"
    assert permissions.never_category("rotate the admin password", cats) == "keys"         # '' adds nothing
    assert by["installer"].deny == ["Bash(gh repo delete *)"] and by["visibility"].source == "engine+file"


@pytest.mark.parametrize("rule, category", [
    ("Bash(gh repo edit --vis*)", "visibility"),             # a truncated word: its pattern matches a probe
    ("PowerShell(Register-Scheduled*)", "scheduled"),
    ("Bash(schtask* *)", "scheduled"), ("Bash(cronta*)", "scheduled"),
    ("Bash(gh repo edit --visibi\\lity public)", "visibility"),   # an escape the shell drops
    ("Bash(gh repo edit *)", "visibility"),                  # covers gh repo edit X --visibility public
    ("Bash(gh *)", "keys"), ("Shell(gh secret *)", "keys"),
    ("Bash(gh pr merge * --merge)", ""), ("Shell(docker inspect *)", ""), ("Bash(brain up *)", ""),
    ("Bash(gh auth status)", ""),
])
def test_an_allow_rule_falls_in_a_category_by_its_text_or_its_pattern(rule, category):
    cats, _ = permissions.categories({})
    assert permissions.never_rule(rule, cats) == category


def test_a_file_adds_probes(tmp_path):
    cats, errors = permissions.categories({"never": {"legal": {"probes": ["sign-contract FILE"]},
                                                     "money": {"probes": "pay"}}})
    assert errors == ["permissions.yaml: never.money.probes: a list of commands"]
    assert permissions.never_rule("Bash(sign-contract *)", cats) == "legal"


@pytest.mark.parametrize("head", [
    "v: 1\nnever: {keys: {find: '(?x)foo'}, money: {names: '(?i)pay'}}\n",
    "v: 1\nprofiles: {lite: {title: t}}\nmachines: {BOX1: {title: t, profile: [lite]}}\n",
    "v: 1\ntenants: {t: {title: t, projects: 5}}\n",
    "v: 1\ntenants: {t: {title: t, projects: [[mine]]}}\n",
    "v: 1\nsessions: {s: {title: t, project: [mine], parent: [x]}}\n",
    "v: 1\nnever: [keys]\nmachines: [BOX1]\n",
    "- just\n- a list\n",
    "v: 1\nrules:\n  - {allow: [Bash(x)], why: \"a reason long enough\"}\n  - 5\n",
])
def test_a_malformed_file_never_raises(tmp_path, monkeypatch, head):
    root = _brain(tmp_path, monkeypatch, head="")
    (root / permissions.FILE).write_text(head, encoding="utf-8")
    model = permissions.load()                       # reported, never raised
    permissions.effective(model, permissions.context(model, "mine", session="s"))
    permissions.default_categories()
    assert queue.owner_only("gh secret set X") == "keys"


def test_the_file_of_the_checkout_acted_on_comes_first(tmp_path, monkeypatch):
    root = _brain(tmp_path, monkeypatch)
    monkeypatch.delenv(permissions.ENV)
    other = tmp_path / "installed"
    other.mkdir()
    (other / "projects.yaml").write_text("mine: {root: .}\n", encoding="utf-8")
    (other / permissions.FILE).write_text("v: 1\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PROJECTS", str(other / "projects.yaml"))
    assert permissions.permissions_file(root) == root / permissions.FILE
    assert permissions.permissions_file(tmp_path) == other / permissions.FILE


def test_queue_classes_owner_actions_by_the_same_categories(tmp_path, monkeypatch):
    assert queue.owner_only("gh repo create acme/engine --public") == "visibility"
    assert queue.owner_only("powershell -File install.ps1 -Apply") == ""
    f = tmp_path / "p.yaml"
    f.write_text("v: 1\nnever:\n  installer: {find: 'install\\.ps1.*-Apply', why: the owner runs it}\n", encoding="utf-8")
    monkeypatch.setenv(permissions.ENV, str(f))
    assert queue.owner_only("powershell -File install.ps1 -Apply") == "installer"
    assert "installer" in queue.rules()["categories"]


# --- the model: levels, checks, precedence ---

def test_engine_rules_carry_the_comment_above_them(tmp_path, monkeypatch):
    _brain(tmp_path, monkeypatch)
    model = permissions.load()
    assert model.errors == []
    engine = [r for r in model.rules if r.level == "engine"]
    assert [(r.text, r.where) for r in engine] == [("Bash(brain up)", "allow-rules.txt:4"),
                                                   ("Bash(brain up *)", "allow-rules.txt:5"),
                                                   ("PowerShell(brain up)", "allow-rules.txt:7")]
    assert engine[0].why == "brain up: start the stacks (Ada, 2026-11-01)" == engine[1].why
    assert engine[2].why == "a comment after the rules starts a new block"


def test_levels_and_precedence(tmp_path, monkeypatch):
    _brain(tmp_path, monkeypatch, _rules(
        "allow: \"Shell(docker inspect *)\"",
        "ask: \"Bash(docker inspect *)\", project: mine",
        "deny: \"Bash(git push *)\", machine: BOX1",
        "allow: \"Bash(git push origin *)\", project: mine",
        "allow: \"Bash(make test)\", profile: lite",
        "allow: \"Bash(make lint)\", project: mine, machine: BOX1",
        "allow: \"Bash(make docs)\", project: mine, machine: BOX2",
        "allow: \"Bash(tox)\", tenant: acme",
        "allow: \"Bash(pytest *)\", session: review",
        "deny: \"Bash(pytest -x *)\", session: deep"))
    model = permissions.load()
    assert model.errors == []
    ctx = permissions.context(model, "mine")
    assert (ctx.machine, ctx.profile, ctx.tenant, ctx.sessions) == ("BOX1", "lite", "", [])
    rows = {e["rule"]: e for e in permissions.effective(model, ctx)}
    inspect = rows["Bash(docker inspect *)"]
    assert inspect["verdict"] == "ask" and inspect["sources"][0]["level"] == "project"
    assert [o["level"] for o in inspect["overridden"]] == ["global"]   # a project tightens a global allow
    assert rows["PowerShell(docker inspect *)"]["verdict"] == "allow"
    assert rows["Bash(git push origin *)"]["shadowed_by"] == ["Bash(git push *)"]
    assert "Bash(make test)" in rows and "Bash(make lint)" in rows and "Bash(make docs)" not in rows
    assert "Bash(tox)" not in rows and "Bash(pytest *)" not in rows
    assert [e["verdict"] for e in permissions.effective(model, ctx)][:2] == ["deny", "ask"]
    app = permissions.context(model, "app", "BOX2")
    assert app.tenant == "acme" and app.profile == ""
    assert {e["rule"] for e in permissions.effective(model, app)} >= {"Bash(tox)"}
    deep = permissions.context(model, session="deep")
    assert deep.project == "mine" and deep.sessions == ["review", "deep"]
    rows = {e["rule"]: e["verdict"] for e in permissions.effective(model, deep)}
    assert rows["Bash(pytest *)"] == "allow" and rows["Bash(pytest -x *)"] == "deny"


def test_a_call_is_decided_part_by_part(tmp_path, monkeypatch):
    _brain(tmp_path, monkeypatch, _rules("allow: \"Bash(git status *)\"", "allow: \"Bash(head *)\"",
                                         "deny: \"Bash(git push *)\"", "ask: \"Bash(git log *)\""))
    model = permissions.load()
    ctx = permissions.context(model, "mine")
    assert permissions.decide(model, ctx, "Bash: git status --short | head -3")["verdict"] == "allow"
    assert permissions.decide(model, ctx, "Bash: git status && tail -2 x")["verdict"] == "none"
    assert permissions.decide(model, ctx, "Bash(git status; git push origin main)")["verdict"] == "deny"
    assert permissions.decide(model, ctx, "git log -1 | head -1")["verdict"] == "ask"
    d = permissions.decide(model, ctx, "Bash: git status > out.txt")
    assert d["verdict"] == "allow" and d["parts"][0]["part"] == "git status"   # a redirection is not a word
    assert permissions.decide(model, ctx, "Bash: gh repo create x --public")["never"] == "visibility"
    assert permissions.decide(model, ctx, "Bash: git status `rm -rf ~`")["verdict"] == "none"   # a substitution
    assert permissions.decide(model, ctx, 'PowerShell: git status "$(Remove-Item x)"')["verdict"] == "none"


def test_a_line_of_allow_rules_txt_that_is_no_rule_is_an_error(tmp_path, monkeypatch):
    _brain(tmp_path, monkeypatch, engine="Bash(brain up)\n*\nBash(\n")
    errors = permissions.check()
    assert errors == ["allow-rules.txt:2: '*' is not a rule (Tool or Tool(specifier))",
                      "allow-rules.txt:3: 'Bash(' is not a rule (Tool or Tool(specifier))"]


@pytest.mark.parametrize("line, error", [
    ("allow: \"Bash(gh secret set *)\"", "falls in keys, which only the owner does: never grantable"),
    ("allow: \"Bash(gh repo edit x --visibility public)\", project: mine", "falls in visibility"),
    ("allow: \"Bash(schtasks *)\", machine: BOX1", "falls in scheduled"),
    ("allow: \"Bash(python *)\"", "too broad (python with a wildcard runs any code)"),
    ("allow: \"Bash(x)\", machine: NOPE", "machine 'NOPE' is not declared under machines:"),
    ("allow: \"Bash(x)\", project: ghost", "project 'ghost' is not registered"),
    ("allow: \"Bash(x)\", tenant: t", "tenant 't' is not declared under tenants:"),
    ("allow: \"Bash(x)\", session: s", "session 's' is not declared under sessions:"),
    ("allow: \"Bash(x)\", profile: lite, machine: BOX1", "profile and machine: one level at a time"),
    ("allow: \"Bash(x)\", deny: \"Bash(y)\"", "exactly one of allow, ask or deny"),
    ("allow: \"Bash(x)\", colour: blue", "unknown key(s) colour"),
    ("allow: \"not a rule\"", "is not a rule"),
])
def test_what_no_level_may_hold(tmp_path, monkeypatch, line, error):
    _brain(tmp_path, monkeypatch, _rules(line))
    assert any(error in e for e in permissions.check()), permissions.check()


def test_ask_and_deny_are_fine_in_a_never_category_and_the_engine_is_checked_too(tmp_path, monkeypatch):
    _brain(tmp_path, monkeypatch, _rules("deny: \"Bash(gh secret set *)\"", "ask: \"Bash(gh repo create *)\""),
           engine="Bash(gh auth token)\nBash(sudo *)\n")
    errors = permissions.check()
    assert len(errors) == 2 and "allow-rules.txt:1: allow Bash(gh auth token) falls in keys" in errors[0]
    assert "allow-rules.txt:2: allow Bash(sudo *) is too broad" in errors[1]


def test_the_file_is_checked(tmp_path, monkeypatch):
    head = ("v: 0\ncolour: blue\nprofiles: {lite: {title: lite}}\nmachines: {BOX1: {title: x, profile: full}}\n"
            "tenants: {a: {title: a, projects: [mine]}, b: {title: b, projects: [mine, ghost]}}\n"
            "sessions: {s1: {title: s, parent: s2}, s2: {title: s, parent: s1}, s3: {title: s, parent: none}}\n"
            "machines_note: 1\n")
    _brain(tmp_path, monkeypatch, _rules("allow: \"Bash(a)\"", "allow: \"Shell(a)\"", "allow: \"Bash(b)\", why: x"
                                         ).replace(", why: x, why: \"a reason long enough\"", ", why: x"), head=head)
    text = "\n".join(permissions.check())
    for part in ("unknown key(s) colour, machines_note", "v is 1", "machines.BOX1.profile 'full'",
                 "project 'mine' is in two tenants (a, b)", "tenants.b.projects: 'ghost' is not registered",
                 "its parents loop (s1 -> s2 -> s1)", "sessions.s3.parent 'none' is not declared",
                 "allow Shell(a) is already declared at permissions.yaml rules[0]",
                 "rules[2]: why, a reason of 15 characters at least"):
        assert part in text, part
    root = tmp_path / "brain"
    (root / permissions.FILE).write_text("v: 1\nrules:\n  - {allow: \"Bash(a)\", " + WHY + "}\nmachines: {}\n",
                                         encoding="utf-8")
    assert "rules is the file's last key (brain permissions grant appends to it)" in "\n".join(permissions.check())


def test_a_newer_hierarchy_is_refused_and_a_newer_key_is_read(tmp_path, monkeypatch, capsys):
    """wi-brain-tolerant-reader: a higher v is refused whole ("brain update"); outside CI an unknown key is a note,
    and an allow rule that carries one is left out (the key may narrow it), a deny rule kept."""
    root = _brain(tmp_path, monkeypatch, "  - {allow: \"Bash(a)\", " + WHY + "}\n", head="v: 2\nfuture: {}\n")
    errors = permissions.check()
    assert errors == [f"{permissions.FILE}: v2 is written by brain > {__version__}, which reads v1: brain update"]
    (root / permissions.FILE).write_text(
        "v: 1\nfuture: {x: 1}\nrules:\n  - {allow: \"Bash(a)\", only_on: BOX2, " + WHY + "}\n"
        "  - {deny: \"Bash(b)\", only_on: BOX2, " + WHY + "}\n", encoding="utf-8")
    assert sorted(permissions.check()) == [
        f"{permissions.FILE} rules[0]: unknown key(s) only_on (known: {', '.join(sorted(permissions.RULE_KEYS))})",
        f"{permissions.FILE} rules[1]: unknown key(s) only_on (known: {', '.join(sorted(permissions.RULE_KEYS))})",
        f"{permissions.FILE}: unknown key(s) future (known: {', '.join(permissions.SECTIONS)})"]
    monkeypatch.setenv("BRAIN_STRICT", "0")
    capsys.readouterr()
    assert permissions.check() == []
    err = capsys.readouterr().err
    assert "unknown key(s) future" in err and "rules[0]: allow rule left out" in err
    texts = {(r.verdict, r.text) for r in permissions.load().rules}
    assert ("deny", "Bash(b)") in texts and ("allow", "Bash(a)") not in texts
    assert permissions.load().data["future"] == {"x": 1}


def test_no_file_runs_on_allow_rules_alone(tmp_path, monkeypatch):
    root = _brain(tmp_path, monkeypatch)
    (root / permissions.FILE).unlink()
    model = permissions.load()
    assert model.errors == [] and [r.level for r in model.rules] == ["engine"] * 3


# --- rendering: Claude Code's settings ---

def test_render_adds_the_missing_rules_and_never_removes_one(tmp_path, monkeypatch):
    root = _brain(tmp_path, monkeypatch, _rules("allow: \"Shell(make test)\", project: mine",
                                                "deny: \"Bash(git push --force *)\", project: mine",
                                                "allow: \"Bash(make lint)\", project: mine, machine: BOX1",
                                                "allow: \"Bash(make docs)\", machine: BOX1"))
    settings = root / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"enabledPlugins": {"x@y": True}, "permissions": {"allow": ["Bash(mine *)"]}}),
                        encoding="utf-8")
    model = permissions.load()
    ctx = permissions.context(model, "mine")
    plans = permissions.render(model, ctx, "project")
    assert [Path(p["file"]) for p in plans] == [settings]
    assert plans[0]["missing"] == {"deny": ["Bash(git push --force *)"], "ask": [],
                                   "allow": ["Bash(make test)", "PowerShell(make test)"]}
    assert plans[0]["unmanaged"]["allow"] == ["Bash(mine *)"] and plans[0]["refused"] == ""
    permissions.render(model, ctx, "project", write=True)
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["enabledPlugins"] == {"x@y": True}
    assert data["permissions"] == {"allow": ["Bash(mine *)", "Bash(make test)", "PowerShell(make test)"],
                                   "deny": ["Bash(git push --force *)"]}
    again = permissions.render(model, ctx, "project", write=True)
    assert again[0]["written"] is False and again[0]["present"] == again[0]["total"] == 3
    local = permissions.render(model, ctx, "local", write=True)
    assert json.loads((root / ".claude" / "settings.local.json").read_text(encoding="utf-8")) == \
        {"permissions": {"allow": ["Bash(make lint)"]}} and local[0]["written"]
    user = permissions.plan(model, ctx, "user")
    assert user[0]["missing"]["allow"] == ["Bash(brain up)", "Bash(brain up *)", "PowerShell(brain up)",
                                           "Bash(make docs)"]
    assert user[0]["refused"] == "install.ps1 -Apply writes the user settings (the owner's)"


def test_a_production_checkout_is_rendered_through_a_worktree_only(tmp_path, monkeypatch):
    root = _brain(tmp_path, monkeypatch, _rules("allow: \"Bash(make test)\", project: app"))
    model = permissions.load()
    ctx = permissions.context(model, "app")
    plans = permissions.render(model, ctx, "project", write=True)
    assert "is a production checkout: render into a worktree of it (--repo)" in plans[0]["refused"]
    assert not plans[0]["written"] and not (root / "app" / ".claude").exists()
    wt = tmp_path / "app-wt"
    plans = permissions.render(model, ctx, "project", repo=wt, write=True)
    assert plans[0]["written"] and json.loads((wt / ".claude" / "settings.json").read_text(encoding="utf-8")) == \
        {"permissions": {"allow": ["Bash(make test)"]}}
    plans = permissions.render(model, ctx, "project", repo=root / "app", write=True)   # --repo is no way around it
    assert "is a production checkout" in plans[0]["refused"] and not (root / "app" / ".claude").exists()
    (root / "app" / "sub").mkdir()
    (root / "app" / "sub" / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")   # a worktree nested in it
    assert permissions.render(model, ctx, "project", repo=root / "app" / "sub", write=True)[0]["written"]


def test_a_production_checkout_behind_a_link_is_still_one(tmp_path, monkeypatch):
    root = _brain(tmp_path, monkeypatch)
    real = tmp_path / "real-app"
    real.mkdir()
    try:
        os.symlink(real, root / "app-link", target_is_directory=True)
    except OSError:
        pytest.skip("no symlinks here")
    (root / "projects.yaml").write_text("mine: {root: .}\napp: {root: app-link, production: [.]}\n", encoding="utf-8")
    assert permissions._production(real) and permissions._production(root / "app-link")


def test_errors_stop_a_render_and_a_session_renders_for_claude_settings(tmp_path, monkeypatch):
    root = _brain(tmp_path, monkeypatch, _rules("allow: \"Bash(pytest *)\", session: review",
                                                "deny: \"Bash(git push *)\", session: deep"))
    model = permissions.load()
    deep = permissions.context(model, session="deep")
    assert permissions.session_settings(model, deep) == \
        {"permissions": {"allow": ["Bash(pytest *)"], "deny": ["Bash(git push *)"]}}
    out = tmp_path / "session.json"   # an existing file is added to, never emptied
    out.write_text(json.dumps({"model": "x", "permissions": {"allow": ["Bash(ls)"], "deny": ["Bash(rm *)"]}}),
                   encoding="utf-8")
    assert permissions.write_session(model, deep, out) == 2
    assert json.loads(out.read_text(encoding="utf-8")) == {"model": "x", "permissions": {
        "allow": ["Bash(ls)", "Bash(pytest *)"], "deny": ["Bash(rm *)", "Bash(git push *)"]}}
    assert permissions.write_session(model, deep, out) == 0
    home = tmp_path / "claude-home"
    home.mkdir()
    with pytest.raises(permissions.PermissionsError, match="is the user settings file"):
        permissions.write_session(model, deep, home / "settings.json")
    with pytest.raises(permissions.PermissionsError, match="production checkout"):
        permissions.write_session(model, deep, root / "app" / "s.json")
    model.errors.append("x")
    with pytest.raises(permissions.PermissionsError, match="nothing is rendered"):
        permissions.render(model, permissions.context(model, "mine"), "project", write=True)
    with pytest.raises(permissions.PermissionsError, match="nothing is rendered"):
        permissions.write_session(model, deep, tmp_path / "other.json")
    assert not (tmp_path / "other.json").exists()


def test_odd_settings_are_refused_not_corrupted(tmp_path):
    f = tmp_path / "settings.json"
    f.write_text(json.dumps({"permissions": {"allow": "Bash(ls)"}}), encoding="utf-8")
    claude = permissions.ClaudeCode()
    assert claude.read(f)["allow"] == []
    with pytest.raises(permissions.PermissionsError, match="permissions.allow is not a list"):
        claude.write(f, {"allow": ["Bash(x)"]})
    f.write_text(json.dumps({"permissions": ["Bash(ls)"]}), encoding="utf-8")
    with pytest.raises(permissions.PermissionsError, match="permissions is not an object"):
        claude.write(f, {"allow": ["Bash(x)"]})
    assert json.loads(f.read_text(encoding="utf-8")) == {"permissions": ["Bash(ls)"]}


# --- grants ---

def test_grant_appends_one_checked_line(tmp_path, monkeypatch):
    root = _brain(tmp_path, monkeypatch)
    f = root / permissions.FILE
    before = f.read_text(encoding="utf-8")
    line, path = permissions.grant(None, rule="Shell(docker inspect *)", selectors={"project": "mine"},
                                   why="reads a container's mounts, read only", by="Ada, 2026-11-02",
                                   origin="perm-60c75cdd84", today="2026-11-02")
    assert path == f and line == ('  - {allow: "Shell(docker inspect *)", project: mine, why: "reads a container\'s '
                                  'mounts, read only", by: "Ada, 2026-11-02", from: perm-60c75cdd84, '
                                  'date: "2026-11-02"}')
    assert f.read_text(encoding="utf-8") == before + line + "\n"
    model = permissions.load()
    assert model.errors == [] and model.rules[-1].level == "project" and model.rules[-1].origin == "perm-60c75cdd84"
    line, _ = permissions.grant(None, rule="Bash(make lint)", selectors={"project": "mine", "machine": "BOX1"},
                                why="the linter on this machine only", dry_run=True)
    assert "machine: BOX1" in line and f.read_text(encoding="utf-8").count("\n  - {") == 1


@pytest.mark.parametrize("kw, error", [
    ({"rule": "Bash(gh secret set *)"}, "falls in keys"),
    ({"rule": "Bash(python *)"}, "too broad"),
    ({"rule": "Bash(gh pr view *)", "denial": "Bash: gh repo create x --public"}, "the denied call falls in visibility"),
    ({"rule": "Bash(brain up)"}, "already declared at allow-rules.txt:4"),
    ({"rule": "Bash(x)", "why": "short"}, "why, a reason of 15 characters"),
    ({"rule": "Bash(x)", "verdict": "maybe"}, "a verdict is allow, ask or deny"),
])
def test_grant_refuses(tmp_path, monkeypatch, kw, error):
    _brain(tmp_path, monkeypatch)
    kw = {"why": "a reason long enough", **kw}
    with pytest.raises(permissions.PermissionsError, match=error):
        permissions.grant(None, selectors={}, **kw)


def test_grant_adds_the_rules_key_when_missing(tmp_path, monkeypatch):
    root = _brain(tmp_path, monkeypatch)
    (root / permissions.FILE).write_text("v: 1\nnever: {}\n", encoding="utf-8")
    permissions.grant(None, rule="Bash(make test)", selectors={}, why="the tests, everywhere", today="2026-11-02")
    data = yaml.safe_load((root / permissions.FILE).read_text(encoding="utf-8"))
    assert data["rules"] == [{"allow": "Bash(make test)", "why": "the tests, everywhere", "date": "2026-11-02"}]


def test_proposals_are_narrow_and_one_per_part():
    p = permissions.propose("Bash: cd /e/x && docker inspect gitnexus --format '{{json .Mounts}}' | head -c 25")
    assert [x["rule"] for x in p] == ["", "Bash(docker inspect *)", "Bash(head *)"]
    assert "a cd" in p[0]["note"] and all("compound command" in x["note"] for x in p)
    assert permissions.propose("Bash: python -c 'print(1)'")[0]["note"].startswith("python with a wildcard")
    assert permissions.propose("WebFetch: https://docs.example.com/a")[0]["rule"] == "WebFetch(domain:docs.example.com)"
    assert permissions.propose("SendMessage: {}")[0]["rule"] == "SendMessage"
    assert permissions.propose("Bash: gh pr merge 108 -R acme/engine --merge")[0]["rule"] == "Bash(gh pr *)"


# --- the command ---

def test_cli_view_explain_check_and_render(tmp_path, monkeypatch, capsys):
    root = _brain(tmp_path, monkeypatch, _rules("ask: \"Bash(git push *)\", project: mine"))
    home = tmp_path / "claude-home"
    home.mkdir()
    (home / "settings.json").write_text(json.dumps({"permissions": {"allow": [
        "Bash(brain up)", "Bash(powershell.exe -File E:/x/install.ps1 *)"]}}), encoding="utf-8")
    assert cli.main(["--root", str(root), "permissions"]) == 0
    out = capsys.readouterr().out
    assert "permissions of mine on BOX1 (profile lite, tenant -): 0 deny, 1 ask, 3 allow" in out
    assert "ask    Bash(git push *)" in out and "project mine" in out
    assert "hard deny  guard production" in out and "never      keys, money, arming" in out
    assert "1 of 3 rule(s) present, 2 missing (install.ps1 -Apply)" in out
    assert "held, declared by no level [broad: powershell with a wildcard runs any code]" in out
    assert cli.main(["--root", str(root), "permissions", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["counts"] == {"deny": 0, "ask": 1, "allow": 3} and data["profile"] == "lite"
    assert cli.main(["--root", str(root), "permissions", "--explain", "Bash(git push *)"]) == 0
    out = capsys.readouterr().out
    assert "ask    at project mine (permissions.yaml rules[0])" in out and "why: a reason long enough" in out
    assert cli.main(["--root", str(root), "permissions", "--all"]) == 0
    assert capsys.readouterr().out.count("permissions of ") == 2
    assert cli.main(["--root", str(root), "permissions", "check"]) == 0
    assert "4 rule(s) with allow-rules.txt, OK" in capsys.readouterr().out
    assert cli.main(["--root", str(root), "permissions", "render", "--level", "user", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["allow"] == ["Bash(brain up)", "Bash(brain up *)", "PowerShell(brain up)"] and data["errors"] == []
    assert cli.main(["--root", str(root), "permissions", "render", "--level", "user", "--write"]) == 1
    assert cli.main(["--root", str(root), "permissions", "render", "--write"]) == 0
    assert json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8")) == \
        {"permissions": {"ask": ["Bash(git push *)"]}}
    (root / permissions.FILE).write_text(HEAD + "rules:\n" + _rules("allow: \"Bash(sudo *)\""), encoding="utf-8")
    assert cli.main(["--root", str(root), "permissions", "check"]) == 1
    assert "error: permissions.yaml rules[0]: allow Bash(sudo *) is too broad" in capsys.readouterr().out
    assert cli.main(["--root", str(root), "permissions", "render", "--level", "user", "--json"]) == 1


def test_cli_grant_in_a_branch_never_on_main(tmp_path, monkeypatch, capsys, git_repo):
    from conftest import run_git
    root = git_repo
    (root / "notes" / "graph" / "schema.yaml").write_text("node_types: [WorkItem]\n", encoding="utf-8")
    (root / "projects.yaml").write_text("mine: {root: .}\n", encoding="utf-8")
    (root / permissions.ENGINE_FILE).write_text("", encoding="utf-8")
    (root / permissions.FILE).write_text("v: 1\nrules:\n", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-q", "-m", "files")
    monkeypatch.setenv("BRAIN_PROJECTS", str(root / "projects.yaml"))
    monkeypatch.delenv(permissions.ENV)
    argv = ["--root", str(root), "permissions", "grant", "--call", "Bash: docker inspect x", "--rule",
            "Shell(docker inspect *)", "--global", "--why", "reads a container, read only"]
    assert cli.main(["--root", str(root), "permissions", "grant", "--call", "Bash: docker inspect x"]) == 1
    assert "proposal: Bash(docker inspect *)" in capsys.readouterr().out
    assert cli.main(argv) == 1
    assert "is the main checkout on main: grant in a worktree's branch" in capsys.readouterr().err
    run_git(root, "checkout", "-q", "-b", "grant")
    assert cli.main(argv) == 0
    assert "appended to" in capsys.readouterr().out
    assert yaml.safe_load((root / permissions.FILE).read_text(encoding="utf-8"))["rules"][0]["allow"] == \
        "Shell(docker inspect *)"
    assert cli.main(["--root", str(root), "permissions", "grant", "--call", "Bash: x", "--rule", "Bash(x)",
                     "--why", "a reason long enough"]) == 2
    assert "name the level" in capsys.readouterr().err
    (root / permissions.FILE).unlink()   # never a file found elsewhere (the main checkout's)
    assert cli.main(argv) == 1
    assert "no permissions.yaml in" in capsys.readouterr().err


def test_check_all_reports_the_hierarchy(tmp_path, monkeypatch, capsys):
    root = _brain(tmp_path, monkeypatch, _rules("allow: \"Bash(sudo *)\""))
    assert cli.check_registry(root, []) == 1
    assert "error: permissions.yaml rules[0]: allow Bash(sudo *) is too broad" in capsys.readouterr().out


# --- the engine's own rules ---

def test_the_engines_allow_rules_load_clean_under_an_owners_categories(monkeypatch):
    """The engine's narrow allow rules ship as package data (adapters/claude/allow-rules.txt) and pass every check
    under an owner's never-grantable categories (tests/fixtures/permissions.yaml, the installer's among them)."""
    fixture = Path(__file__).resolve().parent / "fixtures" / permissions.FILE
    monkeypatch.setenv(permissions.ENV, str(fixture))
    model = permissions.load(fixture.parent)
    assert model.errors == []
    assert model.engine_file == Path(permissions.__file__).resolve().parent / "adapters" / "claude" / \
        permissions.ENGINE_FILE
    assert [r for r in model.rules if r.level == "engine"]
    names = [c.name for c in model.categories]
    assert names[:len(permissions.NEVER)] == [c[0] for c in permissions.NEVER] and "installer" in names
    assert permissions.never_rule("Bash(powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
                                  "install.ps1 *)", model.categories) == "installer"


def _dated(tmp_path, monkeypatch, rules: str):
    """A brain whose store holds wi-open (todo) and wi-closed (done), with ``rules``, on 2026-11-10."""
    root = _brain(tmp_path, monkeypatch, rules)
    store = root / "notes" / "graph"
    (store / "nodes").mkdir()
    (store / "schema.yaml").write_text("node_types: [WorkItem]\n", encoding="utf-8")
    (store / "nodes" / "work.yaml").write_text(
        "- {id: wi-open, type: WorkItem, status: todo, title: \"Open\"}\n"
        "- {id: wi-closed, type: WorkItem, status: done, title: \"Closed\"}\n", encoding="utf-8")
    return root, permissions.load(today=date(2026, 11, 10))


def test_durations_expire_and_a_render_takes_out_only_what_expired(tmp_path, monkeypatch):
    root, model = _dated(tmp_path, monkeypatch, _rules(
        "allow: \"Bash(make a)\", project: mine, until: 2026-11-09",      # past
        "allow: \"Bash(make b)\", project: mine, until: \"2026-11-30\"",
        "allow: \"Bash(make c)\", project: mine, while: wi-closed",
        "allow: \"Bash(make d)\", project: mine, while: wi-open",
        "allow: \"Bash(make e)\", machine: BOX1, until: 2026-11-01"))
    assert model.errors == []
    ctx = permissions.context(model, "mine")
    rows = {e["rule"] for e in permissions.effective(model, ctx)}
    assert {"Bash(make b)", "Bash(make d)"} <= rows and not rows & {"Bash(make a)", "Bash(make c)", "Bash(make e)"}
    assert {x["rule"]: x["reason"] for x in permissions.show(model, ctx)["expired"]} == {
        "Bash(make a)": "until 2026-11-09", "Bash(make c)": "while wi-closed (now done)",
        "Bash(make e)": "until 2026-11-01"}
    settings = root / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(make a)", "Bash(make c)", "Bash(mine *)"]}}),
                        encoding="utf-8")
    plans = permissions.render(model, ctx, "project", write=True)
    assert plans[0]["expired"]["allow"] == ["Bash(make a)", "Bash(make c)"]
    assert plans[0]["unmanaged"]["allow"] == ["Bash(mine *)"]
    assert json.loads(settings.read_text(encoding="utf-8"))["permissions"]["allow"] == \
        ["Bash(mine *)", "Bash(make b)", "Bash(make d)"]
    assert permissions.expired_rules(model, ctx, "user")["allow"] == ["Bash(make e)"]   # install.ps1 takes it out
    assert permissions.decide(model, ctx, "Bash: make a")["verdict"] == "none"


def test_a_duration_is_checked(tmp_path, monkeypatch):
    _, model = _dated(tmp_path, monkeypatch, _rules("allow: \"Bash(x)\", until: soon",
                                                    "allow: \"Bash(y)\", while: wi-ghost",
                                                    "allow: \"Bash(z)\", while: wi-open, until: 2026-12-01",
                                                    "allow: \"Bash(w)\", for: [1]"))
    text = "\n".join(model.errors)
    for part in ("until is a date, YYYY-MM-DD ('soon')", "while wi-ghost: no such item",
                 "until or while, not both", "for is an item or milestone id"):
        assert part in text, part


def test_grant_writes_the_duration_and_the_provenance(tmp_path, monkeypatch):
    root = _brain(tmp_path, monkeypatch)
    line, _ = permissions.grant(None, rule="Bash(make lint)", selectors={"project": "mine"}, why="the linter, for a week",
                                days=7, today="2026-11-02", origin="perm-1", asked_by="sess-1", for_=["wi-a", "ms-b"],
                                by="Ada, 2026-11-02")
    assert 'from: perm-1, asked_by: sess-1, for: [wi-a, ms-b], until: "2026-11-09", date: "2026-11-02"' in line
    r = permissions.load().rules[-1]
    assert (r.until, r.asked_by, r.for_, r.duration()) == ("2026-11-09", "sess-1", ["wi-a", "ms-b"], "until 2026-11-09")


def test_requests_come_from_the_queue_and_the_granted_rules(tmp_path, monkeypatch):
    root = _brain(tmp_path, monkeypatch, _rules(
        "allow: \"Bash(docker inspect *)\", project: mine, from: perm-live, asked_by: s1, until: 2026-11-30",
        "allow: \"Bash(make old)\", from: perm-gone, for: [wi-x, ms-y], until: 2026-11-01"))
    model = permissions.load(today=date(2026, 11, 2))
    denial = {"id": "perm-live", "tool": "Bash", "call": "Bash: docker inspect a | head -1", "via": "auto-mode classifier",
              "reason": "Self-Modification", "first": "2026-11-01T09:00:00Z", "last": "2026-11-01T09:00:00Z",
              "count": 2, "sessions": ["s1"], "cwds": [str(root)], "branches": []}
    other = dict(denial, id="perm-new", call="Bash: npm test", first="2026-10-30T09:00:00Z", sessions=["s2"])
    scanned = {"denials": [denial, other], "guards": []}
    reqs = {r["id"]: r for r in permissions.requests(model, scanned=scanned, today=date(2026, 11, 2))}
    live, new, gone = reqs["perm-live"], reqs["perm-new"], reqs["perm-gone"]
    assert (live["status"], live["scope"], live["duration"]) == ("granted", "project mine", "until 2026-11-30")
    assert live["evidence"] == "Bash: docker inspect a | head -1" and live["sessions"] == ["s1"]
    assert "Self-Modification" in live["reason"] and live["count"] == 2
    assert (new["status"], new["scope"]) == ("pending", "project mine") and new["duration"].startswith("set at the grant")
    assert [p["rule"] for p in new["proposals"]] == ["Bash(npm test *)"]
    assert (gone["status"], gone["source"], gone["items"], gone["milestones"]) == ("expired", "rule", ["wi-x"],
                                                                                    ["ms-y"])
    every = list(reqs.values())
    assert [r["id"] for r in permissions.select(every, status="pending")] == ["perm-new"]
    assert [r["id"] for r in permissions.select(every, sort="age")][0] == "perm-new"
    assert [r["id"] for r in permissions.select(every, item="ms-y")] == ["perm-gone"]
    assert [r["id"] for r in permissions.select(every, scope="global")] == ["perm-gone"]
    assert [r["id"] for r in permissions.select(every, search="docker")] == ["perm-live"]
    text = "\n".join(permissions.requests_text(permissions.select(every)))
    assert "permission requests: 3 (1 pending, 1 granted, 1 expired)" in text and "proposals: Bash(npm test *)" in text


def test_cli_requests(tmp_path, monkeypatch, capsys):
    root = _brain(tmp_path, monkeypatch, _rules("allow: \"Bash(make old)\", from: perm-gone"))
    assert cli.main(["--root", str(root), "permissions", "--requests", "--all"]) == 0
    assert "permission requests of every project: 1 (1 granted)" in capsys.readouterr().out
    assert cli.main(["--root", str(root), "permissions", "--requests", "--status", "pending", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


# --- install.ps1: the permissions step, in PowerShell ---

def _install_block() -> str:
    """The installer's permissions step (the foreign file helpers, its function, then a call), as
    installer/install.ps1 runs it."""
    text = INSTALLER.read_text(encoding="utf-8")
    helpers = text[text.index("# --- the foreign file helpers"):text.index("# --- end of the foreign file helpers")]
    start = text.index("# --- the permissions step")
    end = text.index("# --- end of the permissions step")
    return helpers + text[start:end] + "Update-Permissions\n"


@pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell.exe"), reason="Windows PowerShell")
@pytest.mark.parametrize("render, apply", [("ok", False), ("ok", True), ("none", True), ("error", False),
                                           ("error", True), ("old", True), ("crash", False), ("crash", True)])
def test_install_adds_the_user_scope_and_never_removes(tmp_path, render, apply):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "allow-rules.txt").write_text("# c\nBash(brain up)\nBash(brain down)\n", encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"enabledPlugins": {"a@b": True}, "permissions": {"allow": ["Bash(mine)",
                                                                                               "Bash(brain up)"]}}),
                        encoding="utf-8")
    fake = tmp_path / "python.cmd"
    payload = {"ok": '{"allow": ["Bash(brain up)", "Bash(BRAIN up)", "Bash(make test)"], "ask": ["Bash(git push *)"], '
                     '"deny": ["Bash(gh repo delete *)"], "expired": {"allow": ["Bash(mine)"], "ask": [], "deny": []}, '
                     '"errors": []}',
               "error": '{"allow": [], "ask": [], "deny": [], "errors": ["rules[0]: too broad"]}'}.get(render)
    code = {"error": 1, "old": 2, "crash": 1}.get(render, 0)   # old: argparse's exit; crash: a traceback, no JSON
    fake.write_text(f"@echo off\r\n{'echo ' + payload if payload else ''}\r\nexit /b {code}\r\n", encoding="utf-8")
    script = tmp_path / "install.ps1"   # the installer's permissions step, run as install.ps1 runs it
    script.write_text("$ErrorActionPreference = 'Stop'\n"
                      f"$repo = '{repo}'\n$settings_path = '{settings}'\n$allow_file = '{repo / 'allow-rules.txt'}'\n"
                      f"$venv_python = '{tmp_path / 'absent.exe' if render == 'none' else fake}'\n"
                      f"$Apply = ${str(apply).lower()}\n" + _install_block(), encoding="utf-8")
    res = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                         capture_output=True, text=True, timeout=60)
    after = json.loads(settings.read_text(encoding="utf-8-sig"))
    before = {"allow": ["Bash(mine)", "Bash(brain up)"]}
    if render in ("error", "crash"):   # a broken hierarchy or command stops -Apply: allow-rules.txt is not a way round
        assert ("error    permissions: rules[0]: too broad" if render == "error" else
                "error    brain permissions render --level user --json failed (exit 1)") in res.stdout
        assert (res.returncode != 0) is apply and after["permissions"] == before
        return
    assert res.returncode == 0, res.stdout + res.stderr
    if render in ("none", "old"):   # no brain command, or one older than brain permissions: allow-rules.txt alone
        assert after["permissions"] == {"allow": ["Bash(mine)", "Bash(brain up)", "Bash(brain down)"]}
        assert render == "none" or "has no permissions subcommand" in res.stdout
        return
    assert "allow    Bash(make test) in" in res.stdout and "deny     Bash(gh repo delete *) in" in res.stdout
    assert "expired  allow Bash(mine): taken out of" in res.stdout   # declared expired: the only rule it removes
    if not apply:
        assert after["permissions"] == before
        return
    assert after["enabledPlugins"] == {"a@b": True}
    assert after["permissions"] == {"allow": ["Bash(brain up)", "Bash(BRAIN up)", "Bash(make test)"],
                                    "ask": ["Bash(git push *)"], "deny": ["Bash(gh repo delete *)"]}   # case kept
    again = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                           capture_output=True, text=True, timeout=60)
    assert "same     5 rule(s) of brain permissions" in again.stdout
    bak = json.loads(Path(str(settings) + ".bak").read_text(encoding="utf-8-sig"))
    assert bak["permissions"] == before   # the file as it was before the write, beside it (the foreign class)
    assert not list(tmp_path.glob("settings.json.*.tmp"))


@pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell.exe"), reason="Windows PowerShell")
@pytest.mark.parametrize("text", ["{not json", "[1, 2]"])
def test_install_refuses_an_unreadable_settings_file_and_leaves_it(tmp_path, text):
    """wi-brain-state-safe-io-rest: Claude Code's settings.json is a foreign file: one that is not a JSON object is
    refused (fix it by hand first), never replaced."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "allow-rules.txt").write_text("Bash(brain up)\n", encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(text, encoding="utf-8")
    script = tmp_path / "install.ps1"
    script.write_text("$ErrorActionPreference = 'Stop'\n"
                      f"$repo = '{repo}'\n$settings_path = '{settings}'\n$allow_file = '{repo / 'allow-rules.txt'}'\n"
                      f"$venv_python = '{tmp_path / 'absent.exe'}'\n$Apply = $true\n" + _install_block(),
                      encoding="utf-8")
    res = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                         capture_output=True, text=True, timeout=60)
    assert res.returncode != 0 and "fix it by hand first" in res.stdout + res.stderr
    assert settings.read_text(encoding="utf-8") == text and not Path(str(settings) + ".bak").exists()


@pytest.mark.skipif(os.name != "nt" or not shutil.which("powershell.exe"), reason="Windows PowerShell")
@pytest.mark.parametrize("text", ["", "  \r\n"])
def test_install_reads_an_empty_settings_file_as_a_missing_one(tmp_path, text):
    """An empty settings.json (an interrupted write) is read as missing, as the installer did before the foreign
    file helpers: the rules are written, the empty file kept beside it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "allow-rules.txt").write_text("Bash(brain up)\n", encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_bytes(text.encode("utf-8"))
    script = tmp_path / "install.ps1"
    script.write_text("$ErrorActionPreference = 'Stop'\n"
                      f"$repo = '{repo}'\n$settings_path = '{settings}'\n$allow_file = '{repo / 'allow-rules.txt'}'\n"
                      f"$venv_python = '{tmp_path / 'absent.exe'}'\n$Apply = $true\n" + _install_block(),
                      encoding="utf-8")
    res = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stdout + res.stderr
    assert json.loads(settings.read_text(encoding="utf-8-sig")) == {"permissions": {"allow": ["Bash(brain up)"]}}
    assert Path(str(settings) + ".bak").read_bytes() == text.encode("utf-8")
