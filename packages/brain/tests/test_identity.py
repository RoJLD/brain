"""A brain's identity (wi-brain-identity; spec-brain-vault-heirs-identity 3.8, the owner's answers of 2026-11-04 and
the 0.3.1 scope of 2026-11-10): members.yaml checked against its schema, owner-decides answers signed by a decider's
key and verified with public keys only, relayed answers marked unsigned, asked.by never unknown, and nothing refused
by default (identity.require_signed is the opt-in). The keys are made in each test's own temp folder."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from brain import cli, config, decisions, graph, identity, records, schema, sshsig

FIXTURES = Path(__file__).parent / "fixtures"
AT = "2026-11-10T09:00:00Z"
KEYGEN = shutil.which("ssh-keygen")
needs_ssh = pytest.mark.skipif(not KEYGEN, reason="ssh-keygen (OpenSSH 8.1+) is not on the PATH")


def make_key(folder: Path, name: str = "key") -> tuple[Path, str]:
    """A test's own ed25519 key pair, without a passphrase, in its temp folder: (private file, public line)."""
    key = folder / name
    subprocess.run([KEYGEN, "-q", "-t", "ed25519", "-N", "", "-C", f"{name}@test", "-f", str(key)], check=True,
                   capture_output=True)
    key.chmod(0o600)
    return key, key.with_suffix(".pub").read_text(encoding="utf-8").strip()


def sign(key: Path, files: list[Path], namespace: str = sshsig.NAMESPACE) -> None:
    """The owner's act, as the docs give it: ssh-keygen -Y sign over the payload files at once."""
    subprocess.run([KEYGEN, "-Y", "sign", "-f", str(key), "-n", namespace, *map(str, files)], check=True,
                   capture_output=True)


@pytest.fixture
def brain(tmp_path, monkeypatch):
    """A brain root: config.json (Ada's), records/ddr, and a members.yaml written by ``members()``."""
    root = tmp_path / "brain"
    (root / "records" / "ddr").mkdir(parents=True)
    data = json.loads((FIXTURES / "brain" / "config.json").read_text(encoding="utf-8"))
    (root / "config.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(root / "config.json"))
    for var in ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID", "CLAUDE_CODE_HOST_SESSION_ID"):
        monkeypatch.delenv(var, raising=False)
    return root


def require_signed(root: Path, on: bool = True) -> None:
    f = root / "config.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    data["identity"]["require_signed"] = on
    f.write_text(json.dumps(data), encoding="utf-8")


def members(root: Path, keys: list[str], *, since: str = "", roles=("owner", "decider"), extra: dict | None = None):
    signing = [{"key": k, "machine": "laptop", **({"since": since} if since else {})} for k in keys]
    data = {"v": 1, "class": "confidential",
            "people": [{"person_id": "ada", "name": "Ada", "keys": {"signing": signing}}],
            "memberships": [{"person_id": "ada", "roles": list(roles)}]}
    data.update(extra or {})
    (root / identity.FILE).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def ask_answer(root: Path, title: str, options: list[str], *, via: str = "ask-tool", at: str = AT, slug: str = ""):
    ddr, _ = decisions.ask(root, title=title, question=f"{title}?", options=options, why="first", at=at,
                           slug=slug)
    return decisions.answer(root, ddr["id"], ["1"], via=via, at=at)


def ddr_file(root: Path, ddr: dict) -> Path:
    return root / "records" / "ddr" / f"{ddr['id']}.yaml"


# --- the schema ---------------------------------------------------------------------------------------------------

def test_the_members_schema_is_registered_and_its_fixtures_read():
    assert "members" in schema.SCHEMAS and schema.unsupported(schema.load("members")) == []
    older = identity.plain(graph.load_yaml_file(FIXTURES / "formats" / "members" / "v1" / "older.yaml"))
    newer = identity.plain(graph.load_yaml_file(FIXTURES / "formats" / "members" / "v1" / "newer.yaml"))
    assert schema.check("members", older) == ([], [])
    errors, _ = schema.check("members", newer, schema.STRICT)
    assert any("pronouns" in e for e in errors) and any("passkeys" in e for e in errors)
    assert schema.check("members", newer, schema.READ)[0] == []          # a newer brain's keys: kept, noted
    assert schema.newer("members", 2, schema.known_v("members"))


def test_without_members_yaml_nothing_changes(brain):
    ddr = ask_answer(brain, "Rotate the deploy key", ["Rotate now", "Later"])
    assert identity.load(brain) is None
    assert identity.check(brain) == ([], []) and identity.marks(brain) == {}
    require_signed(brain)                                                 # the opt-in alone checks nothing either
    assert identity.check(brain) == ([], [])
    assert "(unsigned" not in decisions.view(brain, "demo") and ddr["status"] == "answered"


def test_members_yaml_errors_are_reported(brain, monkeypatch):
    monkeypatch.setenv("BRAIN_STRICT", "0")
    members(brain, ["ssh-rsa AAAAB3NzaC1yc2E= old"], extra={
        "accounts": [{"person_id": "bob", "provider": "github", "subject": "bob"}],
        "organizations": [{"id": "acme", "name": "Acme"}],
        "memberships": [{"person_id": "ada", "roles": ["decider"]}, {"person_id": "ada", "tenant": "acme",
                                                                      "roles": ["member"]}]})
    found = identity.load(brain).errors
    assert any("people[0].keys.signing[0].key" in e for e in found)       # an RSA key: not ed25519
    assert any("accounts[0]: person_id 'bob' is not in people" in e for e in found)
    assert any("tenant 'acme' is not in organizations with kind tenant" in e for e in found)
    text = (brain / identity.FILE).read_text(encoding="utf-8")
    armor = "-----BEGIN OPENSSH " + "PRIVATE KEY-----"                    # built here, so no scanner reads a key
    (brain / identity.FILE).write_text(text + f"# {armor}\n", encoding="utf-8")
    assert any("secret pattern" in e for e in identity.load(brain).errors)
    errors, warnings = identity.check(brain)
    assert errors == [] and warnings                                       # warnings by default
    require_signed(brain)
    assert identity.check(brain)[0]


# --- the class --------------------------------------------------------------------------------------------------

def test_the_owner_decides_class_by_its_words():
    def d(title):
        return {"title": title, "question": "?", "options": [{"label": "a"}, {"label": "b"}]}
    assert identity.owner_class(d("Raise the monthly budget")) == ["money"]
    assert identity.owner_class(d("Rotate the SSH key")) == ["keys"]
    assert identity.owner_class(d("Make the repo public")) == ["visibility"]
    assert identity.owner_class(d("Name the heirs of the vault")) == ["keys", "heirs"]
    assert identity.owner_class(d("A new scheduled task for the nightly run")) == ["scheduled tasks"]
    assert identity.owner_class(d("Open a GitHub account for the bot")) == ["accounts"]
    assert identity.owner_class(d("Rename a column")) == []
    assert identity.owner_class(d("Publish a release")) == []              # publication: not the owner's class


def test_the_payload_is_stable_and_covers_the_answer(brain):
    ddr = ask_answer(brain, "Rotate the deploy key", ["Rotate now", "Later"])
    body = json.loads(identity.payload(ddr))
    assert body["namespace"] == "brain-decision" and body["id"] == ddr["id"]
    assert body["answer"]["choices"] == ["Rotate now"] and body["options"] == ["Rotate now", "Later"]
    assert identity.payload(records.load(brain)["ddr"][0][1]) == identity.payload(ddr)   # as read back
    again = decisions.answer(brain, ddr["id"], ["2"], via="cli", at=AT, again=True)
    assert identity.payload(again) != identity.payload(ddr)


# --- unsigned, signed, verified -----------------------------------------------------------------------------------

@needs_ssh
def test_a_relayed_answer_is_marked_unsigned_then_signed_by_the_owner(brain, tmp_path):
    key, pub = make_key(tmp_path)
    members(brain, [pub])
    ddr = ask_answer(brain, "Rotate the deploy key", ["Rotate now", "Later"])
    ask_answer(brain, "Rename a column", ["Yes", "No"], slug="column")    # not the owner's class: no signature
    errors, warnings = identity.check(brain)
    assert errors == [] and len(warnings) == 1
    assert ddr["id"] in warnings[0] and "unsigned" in warnings[0] and "(ask-tool)" in warnings[0]
    assert identity.marks(brain) == {ddr["id"]: "unsigned"}
    assert f"(unsigned, relayed by session" in decisions.view(brain, "demo")
    require_signed(brain)
    assert identity.check(brain)[0] == warnings                            # the opt-in: the same findings, errors

    out = tmp_path / "to-sign"
    entries = identity.unsigned(brain)
    assert [d["id"] for _, d, _ in entries] == [ddr["id"]]
    payloads = identity.write_payloads(entries, out)
    sign(key, payloads)
    assert identity.attach(brain, [out / f"{ddr['id']}.txt.sig"]) == [f"{ddr['id']}: signed by ada"]
    assert identity.sig_file(ddr_file(brain, ddr)).is_file()
    assert identity.check(brain) == ([], []) and identity.unsigned(brain) == []
    assert "(signed)" in decisions.view(brain, "demo")


@needs_ssh
def test_a_forged_or_stale_signature_does_not_verify(brain, tmp_path):
    key, pub = make_key(tmp_path, "owner")
    other, _ = make_key(tmp_path, "intruder")
    members(brain, [pub])
    ddr = ask_answer(brain, "Rotate the deploy key", ["Rotate now", "Later"])
    out = tmp_path / "sig"
    [payload] = identity.write_payloads(identity.unsigned(brain), out)
    sign(other, [payload])                                                 # a key members.yaml does not declare
    with pytest.raises(identity.IdentityError, match="no decider's key"):
        identity.attach(brain, [payload.with_name(payload.name + ".sig")])
    assert not identity.sig_file(ddr_file(brain, ddr)).exists()          # nothing kept
    sign(key, [payload], namespace="git")                                 # the owner's key, another namespace
    with pytest.raises(identity.IdentityError):
        identity.attach(brain, [payload.with_name(payload.name + ".sig")])
    payload.with_name(payload.name + ".sig").unlink()
    sign(key, [payload])
    identity.attach(brain, [payload.with_name(payload.name + ".sig")])
    decisions.answer(brain, ddr["id"], ["Later"], via="cli", at=AT, again=True)   # the answer changed after
    errors, warnings = identity.check(brain)
    assert errors == [] and len(warnings) == 1 and warnings[0].startswith(f"records/ddr/{ddr['id']}.sig: ")


@needs_ssh
def test_a_revoked_key_and_the_since_day(brain, tmp_path):
    _, pub = make_key(tmp_path)
    members(brain, [pub], since="2026-11-10")
    ask_answer(brain, "Rotate the old deploy key", ["Rotate", "Keep"], at="2026-11-01T09:00:00Z", slug="old")
    new = ask_answer(brain, "Rotate the new deploy key", ["Rotate", "Keep"], slug="new")
    assert [d["id"] for _, d, _ in identity.unsigned(brain)] == [new["id"]]   # before since: no signature asked
    data = yaml.safe_load((brain / identity.FILE).read_text(encoding="utf-8"))
    data["people"][0]["keys"]["signing"][0]["revoked"] = "2026-11-11"
    (brain / identity.FILE).write_text(yaml.safe_dump(data), encoding="utf-8")
    assert identity.deciders(data) == {"ada": []}
    assert identity.unsigned(brain) == []                                  # no key to sign with: nothing asked
    assert any("no person has the decider role" in w for w in identity.check(brain)[1])


def test_deciders_per_project_and_tenant():
    data = {"people": [{"person_id": p, "name": p, "keys": {"signing": [{"key": f"k-{p}"}]}} for p in "abcd"],
            "memberships": [{"person_id": "a", "roles": ["decider"]},
                            {"person_id": "b", "project": "demo", "roles": ["decider"]},
                            {"person_id": "c", "tenant": "acme", "roles": ["decider"]},
                            {"person_id": "d", "project": "demo", "roles": ["member"]}]}
    assert sorted(identity.deciders(data, "demo")) == ["a", "b"]
    assert sorted(identity.deciders(data, "other")) == ["a"]


def test_verify_refuses_without_the_tool_or_a_signature(monkeypatch):
    assert sshsig.verify(b"x", b"not a signature", {"ada": ["ssh-ed25519 AAAA"]}, exe="ssh-keygen")[1].startswith(
        "not an SSH signature")
    assert "no decider" in sshsig.verify(b"x", b"-----BEGIN SSH SIGNATURE-----", {}, exe="ssh-keygen")[1]
    monkeypatch.setattr(sshsig.shutil, "which", lambda name: None)
    assert "not on the PATH" in sshsig.verify(b"x", b"", {"ada": ["k"]})[1]
    assert sshsig.allowed_signers({"ada": ["ssh-ed25519 AAAA c"]}) == \
        'ada namespaces="brain-decision" ssh-ed25519 AAAA c\n'


# --- asked.by and the commands ------------------------------------------------------------------------------------

def test_asked_by_is_never_unknown(brain, monkeypatch):
    ddr, _ = decisions.ask(brain, title="From the owner's terminal", question="?", options=["a", "b"], why="w",
                           at=AT)
    assert ddr["asked"]["by"] == config.owner_of() == "Ada"
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s-123")
    ddr, _ = decisions.ask(brain, title="From a session", question="?", options=["a", "b"], why="w", at=AT)
    assert ddr["asked"]["by"] == "s-123"


def test_brain_check_runs_the_identity_check(brain, capsys):
    from brain.commands import _stores
    members(brain, [])
    assert _stores._check_identity(brain, "demo") == 0
    assert "warning: identity: members.yaml: no person has the decider role" in capsys.readouterr().out
    require_signed(brain)
    assert _stores._check_identity(brain, "demo") == 1
    assert "error: identity:" in capsys.readouterr().out


def test_the_identity_commands(brain, tmp_path, capsys):
    def run(*argv):
        return cli.main(["--root", str(brain), "identity", *argv])
    assert run("check") == 0 and "nothing checked" in capsys.readouterr().out
    assert run("unsigned") == 1 and "no members.yaml" in capsys.readouterr().err
    members(brain, ["ssh-ed25519 " + "A" * 68 + " ada@laptop"])
    ddr = ask_answer(brain, "Rotate the deploy key", ["Rotate now", "Later"])
    assert run("unsigned", "--json") == 0
    assert json.loads(capsys.readouterr().out)[0]["topics"] == ["keys"]
    out = tmp_path / "pay"
    assert run("unsigned", "--write", str(out)) == 0
    said = capsys.readouterr().out
    assert "ssh-keygen -Y sign -f <your signing key> -n brain-decision" in said and (out / f"{ddr['id']}.txt").is_file()
    assert run("payload", ddr["id"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == ddr["id"]
    assert run("payload", "ddr-none") == 1
    assert run("attach", str(out)) == 1 and "no signature file" in capsys.readouterr().err
    assert run("check") == 0 and "unsigned" in capsys.readouterr().out


def test_the_question_tool_and_the_queue_never_ask_as_unknown(brain, monkeypatch):
    from brain import capture, queue
    assert capture._asker({"session_id": "s-9"}) == "s-9"
    assert capture._asker({}, "toolu_abc") == "tool-use:toolu_abc"
    monkeypatch.setenv("CLAUDE_CODE_HOST_SESSION_ID", "local_" + "0" * 8 + "-0000-0000-0000-" + "0" * 12)
    assert capture._asker({}).startswith("local_")
    monkeypatch.delenv("CLAUDE_CODE_HOST_SESSION_ID")
    assert capture._asker({}) == "ask-tool"
    ddr, _, _ = queue.add(brain, kind="action", title="Enter the exchange key", what="in the vault", at=AT)
    assert ddr["asked"]["by"] == "Ada"                                     # the owner's terminal: no session
