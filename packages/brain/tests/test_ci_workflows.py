"""The engine's own CI workflows (wi-brain-harness-negative-controls): a step that writes a command substitution to
GITHUB_OUTPUT tests first that it is not empty. An empty output is no error to the shell: compat-prev once found no
tag and went on, green, testing nothing (the skeptic review of brain #52). This checks the engine's .github/workflows
only, so no user repository is newly refused."""

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO / ".github" / "workflows"

SUBST = re.compile(r"\$\(|`")
OUTPUT = re.compile(r"(?:>>|\btee\s+-a)\s*\"?\$(?:env:)?\{?GITHUB_OUTPUT\b")
ASSIGN = re.compile(r"^\s*(?:export\s+|local\s+|readonly\s+)?([A-Za-z_]\w*)=(.*)$")
VAR = re.compile(r"\$\{?([A-Za-z_]\w*)")


def checked_nonempty(var: str, lines: list[str]) -> bool:
    """A test, in ``lines``, that ``var`` is not empty: test -n / [ -n ] / [[ -n ]], test -z (or [ -z ]) followed by
    an exit or ||, or ${var:?}."""
    v = rf"\"?\$\{{?{var}\}}?\"?"
    nonempty = re.compile(rf"(?:\btest|\[\[?)\s+-n\s+{v}")
    empty = re.compile(rf"(?:\btest|\[\[?)\s+-z\s+{v}.*(?:\bexit\b|\|\|)")
    required = re.compile(rf"\$\{{{var}:\?")
    return any(nonempty.search(x) or empty.search(x) or required.search(x) for x in lines)


def unchecked_outputs(script: str) -> list[str]:
    """Each line of a step's script that writes a command substitution to GITHUB_OUTPUT (directly, or through a
    variable assigned one) with no test before it that the value is not empty."""
    lines = [x for x in script.splitlines() if not x.lstrip().startswith("#")]
    assigned: dict[str, int] = {}          # a variable assigned a command substitution: the line it was
    found = []
    for i, line in enumerate(lines):
        out = OUTPUT.search(line)
        if not out:
            m = ASSIGN.match(line)
            if m and SUBST.search(m.group(2)):
                assigned[m.group(1)] = i
            continue
        written = line[:out.start()]
        if SUBST.search(written):
            found.append(line.strip())
            continue
        if any(v in assigned and not checked_nonempty(v, lines[assigned[v] + 1:i + 1]) for v in VAR.findall(written)):
            found.append(line.strip())
    return found


def workflow_steps(path: Path):
    """(job, step name, run script) of each step of a workflow that runs a script."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for job, spec in (data.get("jobs") or {}).items():
        for i, step in enumerate((spec or {}).get("steps") or []):
            if isinstance(step, dict) and isinstance(step.get("run"), str):
                yield job, step.get("name") or f"step {i + 1}", step["run"]


def test_the_engines_workflows_test_each_substitution_they_output():
    files = sorted(WORKFLOWS.glob("*.y*ml"))
    assert files, WORKFLOWS
    found = [f"{f.name}: {job} / {name}: {line}" for f in files for job, name, run in workflow_steps(f)
             for line in unchecked_outputs(run)]
    assert not found, "a command substitution written to GITHUB_OUTPUT untested (test -n first):\n" + "\n".join(found)
    # not vacuous: the engine's workflows do write such an output (compat-prev's last tag)
    assert any(OUTPUT.search(run) for f in files for _, _, run in workflow_steps(f))


@pytest.mark.parametrize("script, refused", [
    ('tag=$(git describe --tags)\necho "tag=$tag" >> "$GITHUB_OUTPUT"', True),
    ('tag=$(git describe --tags)\ntest -n "$tag"\necho "tag=$tag" >> "$GITHUB_OUTPUT"', False),
    ('tag=`git describe`\n[ -n "$tag" ] || exit 1\necho "tag=${tag}" >> $GITHUB_OUTPUT', False),
    ('tag=$(git describe)\n[ -z "$tag" ] && exit 1\necho "tag=$tag" >> "$GITHUB_OUTPUT"', False),
    ('tag=$(git describe)\necho "tag=${tag:?no tag}" >> "$GITHUB_OUTPUT"', False),
    ('echo "tag=$(git describe --tags)" >> "$GITHUB_OUTPUT"', True),
    ('tag=$(git describe)\ntest -n "$other"\necho "tag=$tag" >> "$GITHUB_OUTPUT"', True),
    ('echo "tag=$tag"\ntag=$(git describe)\n# test -n "$tag"\necho "tag=$tag" >> "$GITHUB_OUTPUT"', True),
    ('echo "run=true" >> "$GITHUB_OUTPUT"', False),
    ('echo "tag=$(git describe)" | tee -a "$GITHUB_OUTPUT"', True),
    ('"tag=$(git describe)" >> $env:GITHUB_OUTPUT', True),
    ('name=${{ github.ref_name }}\necho "name=$name" >> "$GITHUB_OUTPUT"', False),
])
def test_a_substitution_written_untested_is_refused(script, refused):
    assert bool(unchecked_outputs(script)) is refused, script


def test_compat_prev_without_its_guard_is_refused():
    """The negative control on the real workflow: ci.yml's last-tag step with its ``test -n "$tag"`` line removed is
    the check's finding."""
    text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    unguarded, n = re.subn(r'^[ \t]*test -n "\$tag"\r?\n', "", text, flags=re.M)
    assert n == 1
    runs = [s["run"] for spec in yaml.safe_load(unguarded)["jobs"].values() for s in spec.get("steps", [])
            if "GITHUB_OUTPUT" in str(s.get("run", ""))]
    assert runs and any(unchecked_outputs(r) for r in runs)
