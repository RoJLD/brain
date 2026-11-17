"""``brain release``: the version PR's mechanical part (``prepare``) and the planning brain's pin PR (``pin``) in one
command each (brain.release), a plan then --write; where a release stands (``status``) and the after-install checks
(``verify``) (brain.releasestatus)."""

from __future__ import annotations

ORDER = 905   # its place in brain --help's list of commands (brain.commands)
PHASE = "early"   # its handlers: early only, before any root is resolved (brain.commands)
USAGE_ORDER = 905   # its usage lines' place in brain --help's epilog
USAGE = """\
  brain release prepare X.Y.Z --theme T [--repo DIR] [--planning ROOT] [--store DIR] [--repo-name NAME]
                 [--no-freeze] [--write]   the engine checkout's version PR, its mechanical part, as a plan (the
                 checkout found from here, else --repo): both __version__, the research-graph pin, brain_version,
                 the install lines and the stranger test's --ref; freeze_store.py vP (the store the previous release
                 wrote; skipped once frozen); changelog.py compile; FEATURES.md and docs/reference/ rendered from the
                 planning brain (--planning, else the personal brain; the public render of --repo-name, default
                 brain); release_check.py (--store: the planning brain's notes/graph by default), then its --preview;
                 --write runs them in that order and stops at the first that fails; the Upgrade steps' prose, the
                 pilot page's line and the review stay a model's (docs/release.md, « The version PR »)
  brain release pin vX.Y.Z [--planning ROOT] [--write] [--json]   the planning brain's pin PR (--planning, else
                 --root, else the brain checkout holding this folder, else the personal brain), as a plan:
                 config.json engine.pin, the engine stores its classes: block leaves at their default (brain classes
                 --suggest; this engine's stores), the adapter plugin's shim PIN line when it keeps one, the tag's
                 Upgrade steps since the pin that name config.json (to read; the standard install step aside), and
                 its open PRs naming the version (the lot PRs that waited for the tag); --write writes the shim then
                 config.json, refused on the brain's default branch; --json prints the plan, writes nothing; then by
                 hand: brain sync with the new engine, the ADR, the journal (docs/release.md, « 4. The pin and the
                 machines »)
  brain release status [X.Y.Z] [--planning ROOT] [--store DIR] [--offline] [--json]   where a release stands, at
                 zero token: its wave closed, the version PR merged, the tag cut and signed, the pin PR merged, the
                 engine installed and verified on this machine, each done, pending or unknown; then the next step and
                 whose it is (the version: the lowest live wave above the pin, else the pin's); --offline reads no
                 network (docs/release.md, « Where a release stands »)
  brain release verify [--planning ROOT] [--no-tests] [--json]   the after-install checks in one call: the engine
                 against the pin, brain probes, brain classes --check, the brain's tests (python -m pytest tests);
                 each one's output in $BRAIN_HOME/release/<check>.log, one line each; recorded for brain release
                 status; exit 1 when one fails
"""
NO_PROJECT = {"release"}   # its parsers that take no --project after them


def register(sub, ctx) -> None:
    rel = sub.add_parser("release", help="the version PR's mechanical part and the pin PR: a plan, then --write "
                                         "(brain.release)").add_subparsers(dest="release_cmd", required=True)
    pr = rel.add_parser("prepare", help="versions, the previous store frozen, the changelog compiled, FEATURES.md "
                                        "and the reference rendered, release_check: a plan, then --write")
    pr.add_argument("version", help="the new version, X.Y.Z")
    pr.add_argument("--theme", required=True, help="the release's theme (the CHANGELOG heading, the tag message)")
    pr.add_argument("--repo", help="the engine checkout (default: the one holding the current folder)")
    pr.add_argument("--planning", help="the brain that plans the releases (default: --root, else the personal brain)")
    pr.add_argument("--store", help="the graph store release_check reads the wave from (default: the planning "
                                    "brain's notes/graph)")
    pr.add_argument("--repo-name", default="brain", help="the engine's repo name in the planning brain (default "
                                                         "brain)")
    pr.add_argument("--no-freeze", dest="freeze", action="store_false",
                    help="skip freeze_store.py (release_check then refuses the version PR)")
    pr.add_argument("--write", action="store_true", help="run the steps, in order, stopping at the first that fails")
    pin = rel.add_parser("pin", help="the planning brain's pin PR: engine.pin, the missing engine stores, the shim's "
                                     "PIN, the Upgrade steps naming config.json, the PRs waiting for the tag")
    pin.add_argument("tag", help="the release tag to pin, vX.Y.Z")
    pin.add_argument("--planning", help="the brain whose pin moves (default: --root, else the brain checkout "
                                         "holding this folder, else the personal brain)")
    pin.add_argument("--write", action="store_true", help="write config.json and the shim (in a pin branch)")
    pin.add_argument("--json", action="store_true", help="the plan as JSON; nothing written")
    st = rel.add_parser("status", help="where a release stands: wave, version PR, tag, pin PR, install, verify; "
                                        "the next step and its owner (brain.releasestatus)")
    st.add_argument("version", nargs="?", default="", help="X.Y.Z (default: the lowest live wave above the pin, "
                                                           "else the pin's)")
    st.add_argument("--planning", help="the planning brain (default: --root, else the brain checkout holding this "
                                       "folder, else the personal brain)")
    st.add_argument("--store", help="its graph store (default: <planning>/notes/graph)")
    st.add_argument("--offline", action="store_true", help="no network: the version, tag and pin PR steps unknown")
    st.add_argument("--json", action="store_true", help="the steps as JSON")
    ve = rel.add_parser("verify", help="the after-install checks in one call, logged and recorded "
                                       "(brain.releasestatus)")
    ve.add_argument("--planning", help="the planning brain (default: --root, else the brain checkout holding this "
                                       "folder, else the personal brain)")
    ve.add_argument("--no-tests", dest="tests", action="store_false", help="skip the brain's own tests")
    ve.add_argument("--json", action="store_true", help="the record as JSON")


def early(args) -> int:
    """No project's root: the engine checkout is the one here (or --repo), the planning brain --planning or --root."""
    from .. import release, releasestatus
    if args.release_cmd == "status":
        return releasestatus.main_status(args)
    if args.release_cmd == "verify":
        return releasestatus.main_verify(args)
    return release.main_pin(args) if args.release_cmd == "pin" else release.main_prepare(args)
