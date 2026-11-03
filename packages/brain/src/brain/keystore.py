"""The OS keystore that keeps the vault's device key (wi-brain-vault; spec-brain-vault-heirs-identity §3.3).

One secret per name, readable by this machine's user only, never printed, never logged, never on a command line:

- ``wincred``: Windows' Credential Manager (DPAPI under it), through advapi32 by ctypes, no dependency; persisted on
  this machine only (``CRED_PERSIST_LOCAL_MACHINE``), never roamed with the profile;
- ``keychain``: macOS's ``security``, the value written through ``security -i``'s standard input;
- ``secret-service``: Linux's libsecret through ``secret-tool``, the value on its standard input;
- ``keyring``: the Python keyring package when it is importable (any system);
- ``file``: ``$BRAIN_VAULT_IDENTITY_FILE``, a file the owner mounts (a container instance's Secret): read only;
- ``memory``: a process-local dict, for the tests only (``BRAIN_KEYSTORE=memory``).

:func:`backend` picks ``$BRAIN_KEYSTORE`` when set, else the file when ``$BRAIN_VAULT_IDENTITY_FILE`` is set, else the
system's own, else keyring; ``None`` when none is available (the vault is then "available, off" on this machine).
A value is one line of text: a caller encodes a binary or multi-line key (base64).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

SERVICE = "brain-vault"
BACKENDS = ("wincred", "keychain", "secret-service", "keyring", "file", "memory")


class KeystoreError(RuntimeError):
    """The keystore refused or failed: the message never holds the value."""


class Backend:
    name = ""

    def available(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        raise NotImplementedError

    def set(self, key: str, value: str) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> bool:
        raise NotImplementedError


def _one_line(value: str) -> str:
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        raise KeystoreError("a keystore value is one non-empty line (encode a binary or multi-line key)")
    return value


class Memory(Backend):
    """The tests' keystore: a dict shared by the process."""
    name = "memory"
    data: dict[str, str] = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = _one_line(value)

    def delete(self, key):
        return self.data.pop(key, None) is not None


class File(Backend):
    """A file the owner mounts: one identity, whatever the key asked; never written by the brain."""
    name = "file"

    def __init__(self, path: str):
        self.path = path

    def available(self):
        return os.path.isfile(self.path)

    def get(self, key):
        try:
            with open(self.path, encoding="utf-8") as f:
                text = f.read().strip()
        except OSError:
            return None
        return text or None

    def set(self, key, value):
        raise KeystoreError(f"the file keystore is read only: the owner mounts it ({self.path})")

    def delete(self, key):
        raise KeystoreError("the file keystore is read only: the owner removes it")


class WinCred(Backend):
    """Windows' Credential Manager, generic credentials named ``brain-vault/<key>``."""
    name = "wincred"
    TYPE_GENERIC, PERSIST_LOCAL_MACHINE, NOT_FOUND = 1, 2, 1168

    def available(self):
        return sys.platform == "win32"

    def _api(self):
        import ctypes
        from ctypes import wintypes

        class FILETIME(ctypes.Structure):
            _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

        class CREDENTIAL(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                        ("Comment", wintypes.LPWSTR), ("LastWritten", FILETIME),
                        ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
                        ("Attributes", ctypes.c_void_p), ("TargetAlias", wintypes.LPWSTR),
                        ("UserName", wintypes.LPWSTR)]

        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        adv.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIAL), wintypes.DWORD]
        adv.CredWriteW.restype = wintypes.BOOL
        adv.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.POINTER(ctypes.POINTER(CREDENTIAL))]
        adv.CredReadW.restype = wintypes.BOOL
        adv.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        adv.CredDeleteW.restype = wintypes.BOOL
        adv.CredFree.argtypes = [ctypes.c_void_p]
        return ctypes, adv, CREDENTIAL

    @staticmethod
    def target(key: str) -> str:
        return f"{SERVICE}/{key}"

    def get(self, key):
        ctypes, adv, CREDENTIAL = self._api()
        ptr = ctypes.POINTER(CREDENTIAL)()
        if not adv.CredReadW(self.target(key), self.TYPE_GENERIC, 0, ctypes.byref(ptr)):
            err = ctypes.get_last_error()
            if err == self.NOT_FOUND:
                return None
            raise KeystoreError(f"Credential Manager: read failed (error {err})")
        try:
            cred = ptr.contents
            return bytes(cred.CredentialBlob[:cred.CredentialBlobSize]).decode("utf-8")
        finally:
            adv.CredFree(ptr)

    def set(self, key, value):
        ctypes, adv, CREDENTIAL = self._api()
        blob = _one_line(value).encode("utf-8")
        buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
        cred = CREDENTIAL()
        cred.Type, cred.TargetName, cred.Persist = self.TYPE_GENERIC, self.target(key), self.PERSIST_LOCAL_MACHINE
        cred.Comment, cred.UserName = "brain vault: this machine's key", SERVICE
        cred.CredentialBlobSize, cred.CredentialBlob = len(blob), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
        if not adv.CredWriteW(ctypes.byref(cred), 0):
            raise KeystoreError(f"Credential Manager: write failed (error {ctypes.get_last_error()})")

    def delete(self, key):
        ctypes, adv, _ = self._api()
        if adv.CredDeleteW(self.target(key), self.TYPE_GENERIC, 0):
            return True
        if ctypes.get_last_error() == self.NOT_FOUND:
            return False
        raise KeystoreError(f"Credential Manager: delete failed (error {ctypes.get_last_error()})")


def _run(argv: list[str], stdin: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=30,
                              stdin=None if stdin is not None else subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise KeystoreError(f"{argv[0]}: {type(exc).__name__}") from None


class Keychain(Backend):
    """macOS's login keychain, generic passwords of service ``brain-vault``."""
    name = "keychain"
    run = staticmethod(_run)

    def available(self):
        return sys.platform == "darwin" and bool(shutil.which("security"))

    def get(self, key):
        r = self.run(["security", "find-generic-password", "-s", SERVICE, "-a", key, "-w"])
        return r.stdout.strip() or None if r.returncode == 0 else None

    def set(self, key, value):
        value = _one_line(value)
        if '"' in value or "\\" in value:
            raise KeystoreError("keychain: a value with quotes or backslashes (encode it)")
        r = self.run(["security", "-i"], stdin=f'add-generic-password -U -s {SERVICE} -a {key} -w "{value}"\n')
        if r.returncode:
            raise KeystoreError(f"keychain: write failed (exit {r.returncode})")

    def delete(self, key):
        return self.run(["security", "delete-generic-password", "-s", SERVICE, "-a", key]).returncode == 0


class SecretService(Backend):
    """Linux's Secret Service (GNOME Keyring, KWallet) through secret-tool."""
    name = "secret-service"
    run = staticmethod(_run)

    def available(self):
        return sys.platform.startswith("linux") and bool(shutil.which("secret-tool"))

    def get(self, key):
        r = self.run(["secret-tool", "lookup", "service", SERVICE, "account", key])
        return r.stdout.strip() or None if r.returncode == 0 else None

    def set(self, key, value):
        r = self.run(["secret-tool", "store", f"--label={SERVICE} {key}", "service", SERVICE, "account", key],
                     stdin=_one_line(value))
        if r.returncode:
            raise KeystoreError(f"secret-tool: write failed (exit {r.returncode})")

    def delete(self, key):
        return self.run(["secret-tool", "clear", "service", SERVICE, "account", key]).returncode == 0


class Keyring(Backend):
    """The Python keyring package, whatever its backend."""
    name = "keyring"

    def _mod(self):
        import keyring  # noqa: PLC0415 - optional
        return keyring

    def available(self):
        try:
            self._mod()
        except ImportError:
            return False
        return True

    def get(self, key):
        return self._mod().get_password(SERVICE, key)

    def set(self, key, value):
        self._mod().set_password(SERVICE, key, _one_line(value))

    def delete(self, key):
        try:
            self._mod().delete_password(SERVICE, key)
        except Exception:  # noqa: BLE001 - keyring's PasswordDeleteError: not there
            return False
        return True


def make(name: str) -> Backend:
    if name not in BACKENDS:
        raise KeystoreError(f"unknown keystore {name!r} (one of {', '.join(BACKENDS)})")
    if name == "file":
        return File(os.environ.get("BRAIN_VAULT_IDENTITY_FILE", ""))
    return {"wincred": WinCred, "keychain": Keychain, "secret-service": SecretService, "keyring": Keyring,
            "memory": Memory}[name]()


def backend() -> Backend | None:
    """$BRAIN_KEYSTORE, else the mounted file, else this system's keystore, else keyring; None when none is there."""
    forced = os.environ.get("BRAIN_KEYSTORE")
    if forced:
        return make(forced)
    if os.environ.get("BRAIN_VAULT_IDENTITY_FILE"):
        return make("file")
    for b in (WinCred(), Keychain(), SecretService(), Keyring()):
        if b.available():
            return b
    return None
