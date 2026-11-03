"""A stand-in for age and age-keygen in the tests where age is not installed: the same command line (-e -r ... -o,
-d -i FILE|- -o, keygen and keygen -y), no cryptography at all. It checks the vault's wiring: every recipient passed,
the identity read from standard input, a key that is not a recipient refused. Real sealing is tested with gpg (and
with age when it is installed)."""

import base64
import hashlib
import os
import sys
from datetime import datetime, timezone

MAGIC = b"FAKEAGE\n"


def public(ident: str) -> str:
    return "age1fake" + hashlib.sha256(ident.strip().encode()).hexdigest()[:40]


def identity_from(text: str) -> str:
    return next(ln.strip() for ln in text.splitlines() if ln.startswith("AGE-SECRET-KEY-"))


def keygen(args: list[str]) -> int:
    if "-y" in args:
        print(public(identity_from(sys.stdin.read())))
        return 0
    ident = "AGE-SECRET-KEY-1FAKE" + os.urandom(16).hex().upper()
    print(f"# created: {datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}")
    print(f"# public key: {public(ident)}")
    print(ident)
    return 0


def main(args: list[str]) -> int:
    if args and args[0] == "keygen":
        return keygen(args[1:])
    opts, rest, i = {"-r": []}, [], 0
    while i < len(args):
        a = args[i]
        if a in ("-r", "-i", "-o"):
            if a == "-r":
                opts["-r"].append(args[i + 1])
            else:
                opts[a] = args[i + 1]
            i += 2
        elif a in ("-e", "-d"):
            opts["mode"] = a
            i += 1
        else:
            rest.append(a)
            i += 1
    data = open(rest[0], "rb").read()
    if opts.get("mode") == "-e":
        out = MAGIC + "\n".join(opts["-r"]).encode() + b"\n--\n" + base64.b64encode(data)
    else:
        src = sys.stdin.read() if opts.get("-i") == "-" else open(opts["-i"], encoding="utf-8").read()
        head, _, body = data[len(MAGIC):].partition(b"\n--\n")
        if not data.startswith(MAGIC) or public(identity_from(src)) not in head.decode().splitlines():
            print("age: error: no identity matched any of the recipients", file=sys.stderr)
            return 1
        out = base64.b64decode(body)
    with open(opts["-o"], "wb") as f:
        f.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
