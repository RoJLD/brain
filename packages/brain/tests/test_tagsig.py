"""Signed engine releases (wi-brain-release-signing, STD-3; the owner's answers of 2026-11-11): a release tag is
verified with git verify-tag against an allowed_signers file generated from members.yaml's releaser role, the install
goes by the commit the signed tag names, and nothing is refused unless config.json engine.verify_tags is on. The keys
and the tags are made in each test's own temp folder."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from brain import cli, identity, sshsig, tagsig

FIXTURES = Path(__file__).parent / "fixtures"
KEYGEN = shutil.which("ssh-keygen")
KADA, KBOB, KCY, KNEW = (f"ssh-ed25519 {c * 68}" for c in "ABCD")   # schema-valid public halves
needs_ssh = pytest.mark.skipif(not KEYGEN or not shutil.which("git"), reason="ssh-keygen (OpenSSH 8.2+) or git missing")


@pytest.fixture(autouse=True)
def no_owner_git_config(tmp_path, monkeypatch):
    """git here reads none of the owner's config (a global gpg.ssh.program, say), as on a fresh machine."""
    empty = tmp_path / "gitconfig-empty"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@needs_ssh
def test_an_owner_signing_program_does_not_break_the_check(engine, tmp_path, monkeypatch):
    """The owner's git config may name a signing program (an agent's) that cannot verify: git's ssh-keygen verifies."""
    repo, pub, _ = engine
    cfg = tmp_path / "gitconfig-owner"
    cfg.write_text('[gpg "ssh"]\n\tprogram = C:/nonexistent/op-ssh-sign.exe\n', encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    assert tagsig.verify_remote(repo.as_uri(), "v1.0.0", allowed(pub))["status"] == tagsig.VERIFIED


def make_key(folder: Path, name: str = "key") -> tuple[Path, str]:
    """A test's own ed25519 key pair, without a passphrase, in its temp folder: (private file, public line)."""
    key = folder / name
    subprocess.run([KEYGEN, "-q", "-t", "ed25519", "-N", "", "-C", f"{name}@test", "-f", str(key)], check=True,
                   capture_output=True, timeout=60)
    key.chmod(0o600)
    return key, key.with_suffix(".pub").read_text(encoding="utf-8").strip()


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com",
                           "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", *args],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.fixture
def engine(tmp_path):
    """An engine repo with v1.0.0 signed by the releaser's key, v1.0.1 signed by another key, v0.9.0 annotated but
    unsigned and v0.8.0 lightweight: (repo, releaser public key, the commit)."""
    keys = tmp_path / "keys"
    keys.mkdir()
    good, good_pub = make_key(keys, "releaser")
    other, _ = make_key(keys, "other")
    repo = tmp_path / "engine"
    repo.mkdir()
    git(repo, "init", "--quiet")
    git(repo, "commit", "--quiet", "--allow-empty", "-m", "release")
    for tag, key in (("v1.0.0", good), ("v1.0.1", other)):
        git(repo, "-c", "gpg.format=ssh", "-c", f"user.signingkey={key.as_posix()}",
            "-c", f"gpg.ssh.program={Path(KEYGEN).as_posix()}", "tag", "-s", tag, "-m", f"brain {tag}")
    git(repo, "tag", "-a", "v0.9.0", "-m", "brain 0.9.0, unsigned")
    git(repo, "tag", "v0.8.0")
    return repo, good_pub, git(repo, "rev-parse", "HEAD")


def allowed(pub: str, person: str = "ada") -> str:
    return tagsig.HEADER + sshsig.allowed_signers({person: [pub]}, tagsig.NAMESPACE)


@pytest.fixture
def brain(tmp_path, monkeypatch):
    root = tmp_path / "brain"
    root.mkdir()
    data = json.loads((FIXTURES / "brain" / "config.json").read_text(encoding="utf-8"))
    (root / "config.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(root / "config.json"))
    return root


def members(root: Path, keys: dict[str, list[str]], roles: dict[str, list[str]], extra: list[dict] = ()):
    people = [{"person_id": p, "name": p.title(), "keys": {"signing": [{"key": k} for k in ks]}}
              for p, ks in keys.items()]
    data = {"v": 1, "class": "confidential", "people": people,
            "memberships": [{"person_id": p, "roles": r} for p, r in roles.items()] + list(extra)}
    (root / identity.FILE).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def verify_tags(root: Path, on: bool = True) -> None:
    f = root / "config.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    data.setdefault("engine", {"repo": "o/brain", "pin": "v1.0.0"})["verify_tags"] = on
    f.write_text(json.dumps(data), encoding="utf-8")


# --- git verify-tag against the allowed signers ---------------------------------------------------------------------

@needs_ssh
def test_a_tag_signed_by_a_releaser_verifies_and_names_its_commit(engine):
    repo, pub, commit = engine
    v = tagsig.verify_remote(repo.as_uri(), "v1.0.0", allowed(pub))
    assert v["status"] == tagsig.VERIFIED, v
    assert v["signer"] == "ada" and v["commit"] == commit


@needs_ssh
def test_another_key_an_unsigned_and_a_lightweight_tag_do_not_verify(engine):
    repo, pub, commit = engine
    assert tagsig.verify_remote(repo.as_uri(), "v1.0.1", allowed(pub))["status"] == tagsig.UNKNOWN_KEY
    unsigned = tagsig.verify_remote(repo.as_uri(), "v0.9.0", allowed(pub))
    assert unsigned["status"] == tagsig.UNSIGNED and unsigned["commit"] == commit
    assert tagsig.verify_remote(repo.as_uri(), "v0.8.0", allowed(pub))["status"] == tagsig.UNSIGNED


@needs_ssh
def test_an_older_signed_tag_pushed_under_the_pins_name_does_not_verify(engine):
    """The signature covers the tag object, not the ref's name: v2.0.0 pointed at v1.0.0's signed tag object (an
    account that can push but holds no key, rolling the machines back) is misnamed, never verified
    (wi-brain-install-verify-tag's review)."""
    repo, pub, commit = engine
    git(repo, "update-ref", "refs/tags/v2.0.0", git(repo, "rev-parse", "refs/tags/v1.0.0"))
    v = tagsig.verify_remote(repo.as_uri(), "v2.0.0", allowed(pub))
    assert v["status"] == tagsig.MISNAMED and v["commit"] == commit
    assert "the tag object of v1.0.0, not of v2.0.0" in v["why"]


@needs_ssh
def test_a_decision_signature_namespace_does_not_verify_a_tag(engine):
    repo, pub, _ = engine
    wrong = sshsig.allowed_signers({"ada": [pub]}, sshsig.NAMESPACE)   # brain-decision, not git
    assert tagsig.verify_remote(repo.as_uri(), "v1.0.0", wrong)["status"] == tagsig.UNKNOWN_KEY


@needs_ssh
def test_a_missing_tag_is_unverifiable_and_no_signers_reads_nothing(engine):
    repo, pub, _ = engine
    assert tagsig.verify_remote(repo.as_uri(), "v9.9.9", allowed(pub))["status"] == tagsig.UNVERIFIABLE

    def no_git(*a, **k):
        raise AssertionError("no signers: nothing to fetch")
    assert tagsig.verify_remote(repo.as_uri(), "v1.0.0", tagsig.HEADER, runner=no_git)["status"] == tagsig.NO_SIGNERS


@needs_ssh
def test_no_ssh_keygen_is_unverifiable_not_a_foreign_key(engine, monkeypatch, tmp_path):
    repo, pub, _ = engine
    v = tagsig.verify_remote(repo.as_uri(), "v1.0.0", allowed(pub), program=str(tmp_path / "no-such-ssh-keygen.exe"))
    assert v["status"] == tagsig.UNVERIFIABLE and "could not run" in v["why"], v


def test_git_missing_is_said_not_raised():
    def missing(*a, **k):
        raise FileNotFoundError("git")
    v = tagsig.verify_remote("https://example.invalid/x.git", "v1.0.0", allowed("ssh-ed25519 AAAA k"), runner=missing)
    assert v["status"] == tagsig.UNVERIFIABLE and v["why"].startswith("git init failed")


def test_verify_tag_that_cannot_run_is_unverifiable_not_a_foreign_key():
    """git ran for the fetch, then verify-tag could not run (exit 127 from the runner): never « another key »."""
    def runner(cmd, **kw):
        if "verify-tag" in cmd:
            raise OSError("ssh-keygen vanished")
        if cmd[-3:-1] == ["cat-file", "tag"]:   # the tag object's header: v1.0.0 itself, of a commit
            return subprocess.CompletedProcess(cmd, 0, "object c0ffee\ntype commit\ntag v1.0.0\n\nmsg\n", "")
        out = {"cat-file": "tag\n", "rev-parse": "c0ffee\n"}.get(next((a for a in cmd if a in ("cat-file",
                                                                                               "rev-parse")), ""), "")
        return subprocess.CompletedProcess(cmd, 0, out, "")
    v = tagsig.verify_remote("https://example.invalid/x.git", "v1.0.0", allowed("ssh-ed25519 AAAA k"), runner=runner)
    assert v["status"] == tagsig.UNVERIFIABLE and "could not run" in v["why"], v


# --- the allowed signers, generated from members.yaml's releaser role ---------------------------------------------

def test_the_releasers_are_the_brain_wide_role_with_keys_not_revoked(brain):
    members(brain, {"ada": [KADA + " ada@laptop"], "bob": [KBOB + " bob@x"],
                    "cy": [KCY + " cy@x"]},
            {"ada": ["owner", "releaser"], "bob": ["decider"]},
            extra=[{"person_id": "cy", "project": "demo", "roles": ["releaser"]}])
    text = tagsig.generate(brain)
    assert text == tagsig.HEADER + f'ada namespaces="git" {KADA}\n'   # the key's comment (a machine) left out
    data = yaml.safe_load((brain / identity.FILE).read_text(encoding="utf-8"))
    data["people"][0]["keys"]["signing"][0]["revoked"] = "2026-11-11"
    (brain / identity.FILE).write_text(yaml.safe_dump(data), encoding="utf-8")
    assert tagsig.generate(brain) == ""


def test_no_members_or_no_releaser_gives_nothing(brain):
    assert tagsig.generate(brain) == "" and tagsig.signers(brain) == ("", "")
    members(brain, {"ada": [KADA + " ada@laptop"]}, {"ada": ["owner", "decider"]})
    assert tagsig.generate(brain) == ""
    with pytest.raises(ValueError, match="releaser"):
        tagsig.write(brain)


def test_members_yaml_wins_and_the_file_serves_a_brain_without_it(brain):
    members(brain, {"ada": [KADA + " ada@laptop"]}, {"ada": ["releaser"]})
    text, source = tagsig.signers(brain)
    assert text == tagsig.generate(brain) and "members.yaml" in source
    f = tagsig.write(brain)
    assert f == brain / tagsig.FILE and f.read_text(encoding="utf-8") == text
    revoke_all(brain)   # the key revoked in members.yaml: the stale file trusts nothing more
    assert tagsig.signers(brain) == ("", "")
    f.write_text('# a published file\nrel namespaces="git" ssh-ed25519 AAAApub\n', encoding="utf-8")
    members(brain, {"ada": [KADA]}, {"ada": ["owner", "decider"]})   # a brain that names no releaser of its own
    assert tagsig.signers(brain) == (f.read_text(encoding="utf-8"), str(f))   # reads a published file
    assert tagsig.problems(brain) == []   # and does not call it stale
    (brain / identity.FILE).unlink()   # nor does a brain without members.yaml
    assert tagsig.signers(brain) == (f.read_text(encoding="utf-8"), str(f))


def revoke_all(root: Path) -> None:
    data = yaml.safe_load((root / identity.FILE).read_text(encoding="utf-8"))
    for p in data["people"]:
        for k in p["keys"]["signing"]:
            k["revoked"] = "2026-11-11"
    (root / identity.FILE).write_text(yaml.safe_dump(data), encoding="utf-8")


def test_check_warns_of_a_stale_file_and_of_the_opt_in_without_one(brain):
    members(brain, {"ada": [KADA + " ada@laptop"]}, {"ada": ["releaser"]})
    assert tagsig.problems(brain) == []
    tagsig.write(brain)
    members(brain, {"ada": [KNEW + " ada@laptop"]}, {"ada": ["releaser"]})   # a key rotated
    assert any("not what members.yaml" in p for p in tagsig.problems(brain))
    revoke_all(brain)   # the releaser's last key revoked, the file left
    assert any("no releaser key is left" in p for p in tagsig.problems(brain))
    (brain / tagsig.FILE).unlink()
    verify_tags(brain)
    assert any("verify_tags is on" in p for p in tagsig.problems(brain))
    errors, warnings = identity.check(brain)
    assert errors == [] and any(tagsig.FILE in w for w in warnings)   # a warning, never an error


def test_verify_tags_is_off_by_default_and_an_optional_key(brain):
    from brain import schema

    assert tagsig.required(brain) is False
    verify_tags(brain)
    assert tagsig.required(brain) is True
    data = json.loads((brain / "config.json").read_text(encoding="utf-8"))
    assert schema.check("config", data, "strict")[0] == []
    data["engine"]["verify_tags"] = "yes"
    assert schema.check("config", data, "strict")[0] != []


def test_the_command_prints_and_writes_the_file(brain, capsys):
    members(brain, {"ada": [KADA + " ada@laptop"]}, {"ada": ["releaser"]})
    assert cli.main(["--root", str(brain), "identity", "allowed-signers"]) == 0
    assert capsys.readouterr().out == tagsig.generate(brain)
    assert not (brain / tagsig.FILE).exists()
    assert cli.main(["--root", str(brain), "identity", "allowed-signers", "--write"]) == 0
    assert (brain / tagsig.FILE).read_text(encoding="utf-8") == tagsig.generate(brain)


def test_the_command_writes_to_the_file_named(brain, tmp_path):
    members(brain, {"ada": [KADA]}, {"ada": ["releaser"]})
    out = tmp_path / "export" / "signers"
    out.parent.mkdir()
    assert cli.main(["--root", str(brain), "identity", "allowed-signers", "--write", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == tagsig.generate(brain) and not (brain / tagsig.FILE).exists()


def test_the_command_without_a_releaser_fails(brain, capsys):
    members(brain, {"ada": [KADA + " ada@laptop"]}, {"ada": ["decider"]})
    assert cli.main(["--root", str(brain), "identity", "allowed-signers"]) == 1
    assert "releaser" in capsys.readouterr().err


@needs_ssh
def test_verify_reads_the_brains_signers(brain, engine, monkeypatch):
    repo, pub, commit = engine
    members(brain, {"ada": [pub]}, {"ada": ["owner", "releaser"]})
    monkeypatch.setattr(tagsig, "repo_url", lambda r: repo.as_uri())
    v = tagsig.verify(brain, "o/brain", "v1.0.0")
    assert v["status"] == tagsig.VERIFIED and v["commit"] == commit and "members.yaml" in v["source"]
    assert "signed by ada" in tagsig.line(v, False)
    v = tagsig.verify(brain, "o/brain", "v0.9.0")
    assert "not refused" in tagsig.line(v, False) and "refused: config.json" in tagsig.line(v, True)


def test_installed_commit_reads_pips_direct_url(tmp_path):
    sp = tmp_path / "site-packages"
    d = sp / "research_graph-1.0.0.dist-info"
    d.mkdir(parents=True)
    (d / "direct_url.json").write_text(json.dumps({"url": "https://x", "vcs_info": {"vcs": "git",
                                                                                     "commit_id": "abc"}}),
                                       encoding="utf-8")
    assert tagsig.installed_commit([sp], "research_graph") == "abc"
    assert tagsig.installed_commit([sp], "brain") == ""


# --- the installer's own check (install.ps1's Test-TagSignature), before the brain command exists -------------------

INSTALLER = Path(__file__).resolve().parents[1] / "installer" / "install.ps1"
PS = shutil.which("powershell.exe") or shutil.which("pwsh")   # Windows PowerShell, else PowerShell 7 (Linux)
needs_ps = pytest.mark.skipif(not PS, reason="no PowerShell to run install.ps1")


def ps_verify(url: str, tag: str, allowed_file) -> dict:
    """Run the installer's own Test-TagSignature: its result as a dict."""
    text = INSTALLER.read_text(encoding="utf-8-sig")
    func = re.search(r"^function Test-TagSignature\b.*?^}", text, re.S | re.M).group(0)
    script = (f"$ErrorActionPreference = 'Stop'\n{func}\n"
              f"Test-TagSignature '{url}' '{tag}' '{allowed_file}' | ConvertTo-Json -Compress\n")
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])




@needs_ssh
@needs_ps
def test_the_installer_verifies_as_the_engine_does(engine, tmp_path, monkeypatch):
    repo, pub, commit = engine
    f = tmp_path / tagsig.FILE
    f.write_text(allowed(pub), encoding="utf-8", newline="\n")
    url = repo.as_uri()
    good = ps_verify(url, "v1.0.0", f)
    assert good["status"] == "verified" and good["signer"] == "ada" and good["commit"] == commit
    assert ps_verify(url, "v1.0.1", f)["status"] == "unknown-key"
    assert ps_verify(url, "v0.9.0", f)["status"] == "unsigned"
    assert ps_verify(url, "v0.8.0", f)["status"] == "unsigned"
    assert ps_verify(url, "v9.9.9", f)["status"] == "unverifiable"
    assert ps_verify(url, "v1.0.0", tmp_path / "none")["status"] == "no-signers"
    git(repo, "update-ref", "refs/tags/v2.0.0", git(repo, "rev-parse", "refs/tags/v1.0.0"))   # an older signed tag
    assert ps_verify(url, "v2.0.0", f)["status"] == "misnamed"
    cfg = tmp_path / "gitconfig-owner"   # an owner's signing program that cannot verify: git's ssh-keygen does
    cfg.write_text('[gpg "ssh"]\n\tprogram = C:/nonexistent/op-ssh-sign.exe\n', encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    assert ps_verify(url, "v1.0.0", f)["status"] == "verified"


@needs_ps
def test_the_installer_says_whether_it_runs_from_the_signed_commit(tmp_path):
    """Get-OwnCommit: its own folder's HEAD ('+changes' when a tracked file differs), '' outside git; the step says
    'runs from that commit' when it is the verified one, else a note, never a refusal (wi-brain-install-verify-tag)."""
    text = INSTALLER.read_text(encoding="utf-8-sig")
    func = re.search(r"^function Get-OwnCommit\b.*?^}", text, re.S | re.M).group(0)
    repo = tmp_path / "clone"
    (repo / "packages" / "brain" / "installer").mkdir(parents=True)
    tracked = repo / "packages" / "brain" / "installer" / "install.ps1"
    tracked.write_text("'x'\n", encoding="utf-8")
    git(repo, "init", "--quiet")
    git(repo, "add", "-A")
    git(repo, "commit", "--quiet", "-m", "release")
    head = git(repo, "rev-parse", "HEAD")
    (tmp_path / "copy").mkdir()

    def own(folder: Path) -> str:
        r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-Command",
                            f"{func}\n\"[$(Get-OwnCommit '{folder}')]\""], capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()[1:-1]

    (repo / "packages" / "__pycache__").mkdir()   # untracked: no change
    assert own(repo / "packages" / "brain") == head
    tracked.write_text("'changed'\n", encoding="utf-8")
    assert own(repo / "packages" / "brain") == f"{head}+changes"
    assert own(tmp_path / "copy") == ""
    step = text[text.index("if ($sig.status -eq 'verified') {"):text.index("} elseif ($verify_tags) {")]
    assert "$own = Get-OwnCommit $engine_root" in step and "this installer runs from that commit" in step
    assert "throw" not in step


def test_the_installer_refuses_only_under_verify_tags_and_installs_by_the_tag():
    """The command step: not verified -> refused under engine.verify_tags (a throw on -Apply, before the venv), said
    otherwise; pip still installs the tag (brain.skew reads a release by its tag), its commits checked after."""
    text = INSTALLER.read_text(encoding="utf-8-sig")
    assert text.startswith("<#") and INSTALLER.read_bytes().startswith(b"\xef\xbb\xbf")   # PowerShell 5.1 reads UTF-8
    step = text[text.index("if (-not $SkipCommand) {"):text.index("if (Test-Path $venv_python) {")]
    assert "elseif ($verify_tags)" in step and "if ($Apply) { throw" in step
    assert "git+https://github.com/$engine_repo.git@$engine_pin#subdirectory=packages/brain" in text
    assert "$verify_tags = [bool]($config -and $config.engine -and $config.engine.verify_tags -eq $true)" in text
    start = text.index("if ($Apply) { Install-Brain $spec }")
    after = text[start:text.index("# The machine's profile, read", start)]
    assert "foreach ($dist in 'brain', 'research_graph')" in after and "if ($verify_tags) { throw" in after


@needs_ps
def test_the_installer_reads_the_commit_pip_recorded_from_the_engines_repo(tmp_path):
    text = INSTALLER.read_text(encoding="utf-8-sig")
    func = re.search(r"^function Get-InstalledCommit\b.*?^}", text, re.S | re.M).group(0)
    site = tmp_path / "venv" / "Lib" / "site-packages"
    for dist, repo, commit in (("brain", "ada/engine", "c1"), ("research_graph", "RoJLD/brain", "c2")):
        d = site / f"{dist}-1.0.0.dist-info"
        d.mkdir(parents=True)
        (d / "direct_url.json").write_text(json.dumps({"url": f"https://github.com/{repo}.git",
                                                       "vcs_info": {"commit_id": commit}}), encoding="utf-8")
    script = (f"$windows = $true; $venv = '{tmp_path / 'venv'}'; $engine_repo = 'ada/engine'\n{func}\n"
              "\"[$(Get-InstalledCommit 'brain')][$(Get-InstalledCommit 'research_graph')]\"\n")
    r = subprocess.run([PS, "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "[c1][]"   # research-graph from another repo than engine.repo: not compared
