"""Verify SSH signatures with public keys only (wi-brain-identity): ``ssh-keygen -Y verify`` over an allowed-signers
file the engine writes from members.yaml's public keys, in a temporary folder.

The engine never signs: it never generates, reads, stores or prints a private key, and never names one to a tool.
Signing is the owner's own act in their own terminal (``ssh-keygen -Y sign -f <their key> -n brain-decision FILE...``,
docs/identity.md). OpenSSH 8.1 or later has ``-Y``; Windows 10 and later ship it, and so does Git for Windows.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

NAMESPACE = "brain-decision"   # a signature for this namespace verifies nowhere else (a git commit, a file), nor the reverse
TOOL = "ssh-keygen"
TIMEOUT = 30


def tool() -> str:
    """The ssh-keygen on the PATH, '' when there is none."""
    return shutil.which(TOOL) or ""


def allowed_signers(keys: dict[str, list[str]], namespace: str = NAMESPACE) -> str:
    """The allowed-signers text (ssh-keygen(1), ALLOWED SIGNERS): one line per public key, its person as the
    principal, valid for ``namespace`` only."""
    return "".join(f'{person} namespaces="{namespace}" {key.strip()}\n' for person, ks in sorted(keys.items())
                   for key in ks)


def verify(payload: bytes, signature: bytes, keys: dict[str, list[str]], namespace: str = NAMESPACE,
           exe: str = "") -> tuple[str, str]:
    """(the person whose key made ``signature`` over ``payload``, '') when one of ``keys`` ({person: [public key]})
    did, else ('', why). ``ssh-keygen`` missing is a why too: the caller decides whether it fails."""
    exe = exe or tool()
    if not exe:
        return "", "ssh-keygen is not on the PATH: the signature cannot be verified"
    if not keys:
        return "", "no decider's signing key is declared in members.yaml"
    if b"-----BEGIN SSH SIGNATURE-----" not in signature:
        return "", "not an SSH signature (ssh-keygen -Y sign writes -----BEGIN SSH SIGNATURE-----)"
    with tempfile.TemporaryDirectory(prefix="brain-sig-") as tmp:
        allowed, sig = Path(tmp) / "allowed_signers", Path(tmp) / "answer.sig"
        allowed.write_text(allowed_signers(keys, namespace), encoding="utf-8", newline="\n")
        sig.write_bytes(signature)
        for person in sorted(keys):
            try:
                done = subprocess.run([exe, "-Y", "verify", "-f", str(allowed), "-I", person, "-n", namespace,
                                       "-s", str(sig)], input=payload, capture_output=True, timeout=TIMEOUT,
                                      check=False)
            except (OSError, subprocess.SubprocessError) as exc:
                return "", f"ssh-keygen could not run: {exc}"
            if done.returncode == 0:
                return person, ""
    return "", "no decider's key declared in members.yaml made this signature over this answer"
