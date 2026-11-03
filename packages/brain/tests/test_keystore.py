import os
import subprocess
import sys
import uuid

import pytest

from brain import keystore


def test_memory_keeps_one_line(monkeypatch):
    monkeypatch.setenv("BRAIN_KEYSTORE", "memory")
    keystore.Memory.data.clear()
    ks = keystore.backend()
    assert ks.name == "memory" and ks.get("device") is None
    ks.set("device", "value-1")
    assert ks.get("device") == "value-1"
    with pytest.raises(keystore.KeystoreError, match="one non-empty line"):
        ks.set("device", "two\nlines")
    assert ks.delete("device") and not ks.delete("device")


def test_the_mounted_file_is_read_only(monkeypatch, tmp_path):
    f = tmp_path / "identity"
    f.write_text("value-2\n", encoding="utf-8")
    monkeypatch.delenv("BRAIN_KEYSTORE", raising=False)
    monkeypatch.setenv("BRAIN_VAULT_IDENTITY_FILE", str(f))
    ks = keystore.backend()
    assert ks.name == "file" and ks.get("device") == "value-2"
    with pytest.raises(keystore.KeystoreError, match="read only"):
        ks.set("device", "x")


def test_unknown_keystore_is_refused(monkeypatch):
    monkeypatch.setenv("BRAIN_KEYSTORE", "notepad")
    with pytest.raises(keystore.KeystoreError, match="unknown keystore"):
        keystore.backend()


@pytest.mark.parametrize("cls", [keystore.Keychain, keystore.SecretService])
def test_a_value_never_goes_on_a_command_line(cls, monkeypatch):
    calls = []

    def run(argv, stdin=None):
        calls.append((argv, stdin))
        return subprocess.CompletedProcess(argv, 0, "value-3\n", "")

    monkeypatch.setattr(cls, "run", staticmethod(run))
    ks = cls()
    ks.set("device", "value-3")
    assert ks.get("device") == "value-3"
    argv, stdin = calls[0]
    assert "value-3" not in " ".join(argv) and "value-3" in stdin
    assert all("value-3" not in " ".join(a) for a, _ in calls)


@pytest.mark.skipif(sys.platform != "win32" or os.environ.get("BRAIN_TEST_KEYSTORE") != "wincred",
                    reason="writes the real Credential Manager: BRAIN_TEST_KEYSTORE=wincred on Windows")
def test_wincred_round_trip():
    ks = keystore.WinCred()
    key = f"test-{uuid.uuid4().hex[:8]}"
    try:
        assert ks.get(key) is None
        ks.set(key, "value-4")
        assert ks.get(key) == "value-4"
    finally:
        assert ks.delete(key)
    assert ks.get(key) is None and not ks.delete(key)


def test_a_test_never_reaches_the_real_keystore_or_brain_home(monkeypatch):
    """2026-11-03: a test's monkeypatch.undo() dropped the conftest's BRAIN_HOME and the memory keystore, and the rest
    of it rotated the owner's real device key. Under pytest, both are refused unless a test asks for them."""
    from brain import paths
    with monkeypatch.context() as m:
        m.delenv("BRAIN_HOME", raising=False)
        with pytest.raises(RuntimeError, match="a test reached the real ~/.brain"):
            paths.brain_home()
    with monkeypatch.context() as m:
        m.delenv("BRAIN_KEYSTORE", raising=False)
        m.delenv("BRAIN_VAULT_IDENTITY_FILE", raising=False)
        m.delenv("BRAIN_TEST_KEYSTORE", raising=False)
        real = [b for b in (keystore.WinCred(), keystore.Keychain(), keystore.SecretService(), keystore.Keyring())
                if b.available()]
        if real:
            with pytest.raises(keystore.KeystoreError, match="a test reached this machine's keystore"):
                keystore.backend()
        else:
            assert keystore.backend() is None
    monkeypatch.setenv("BRAIN_KEYSTORE", "memory")
    assert keystore.backend().name == "memory"
