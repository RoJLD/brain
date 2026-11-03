# Install the brain from zero

This guide takes a machine with nothing on it to a working brain of your own: the `brain` command installed from a
tag of this repo, a private brain repo created by `brain init`, and, if you use it, Claude Code reading its rules and
guards. Windows first; Linux and macOS at the end. It needs no Docker, no GPU and no service: the Lite profile is the
default, and every command reads files and git, never a model.

Your brain is yours: it lives in a folder and a git repo of your own, in your own account or organisation. The engine
sends nothing anywhere (no telemetry, no account); its machine-local state lives in `~/.brain`. You hold your own keys.

## Windows

### 1. What you need

| Tool | Why | Install |
|---|---|---|
| Python 3.10 or later | the `brain` command | `winget install Python.Python.3.12`, or python.org (tick *Add python.exe to PATH*) |
| Git for Windows | your brain is a git repo; its bash runs the Claude Code hooks | `winget install Git.Git` |
| Claude Code (optional) | the rules injected into each session, the guards | see Anthropic's Claude Code docs |

Open a new PowerShell window afterwards, and check:

```powershell
py -3 --version        # Python 3.10 or later
git --version
```

### 2. The brain command

The installer makes a venv of its own in `~/.brain\venv` (where the hooks look for it), copies the `brain` launcher
into `~/.brain\bin` and adds that folder alone to your user PATH. It prints a plan first; `-Apply` does it. Take it
from the tag you were given (here v0.2.1):

```powershell
git clone --depth 1 --branch v0.2.1 https://github.com/RoJLD/brain.git "$HOME\brain-engine"
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\brain-engine\packages\brain\installer\install.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\brain-engine\packages\brain\installer\install.ps1" -Apply
```

`-ExecutionPolicy Bypass` applies to that one run only; it changes no setting. Open a new PowerShell window, then:

```powershell
brain --version        # brain 0.2.1
```

Without the installer, the same by hand (the venv must be `~/.brain\venv` for the hooks to find it):

```powershell
py -3 -m venv "$HOME\.brain\venv"
& "$HOME\.brain\venv\Scripts\python.exe" -m pip install "brain @ git+https://github.com/RoJLD/brain.git@v0.2.1#subdirectory=packages/brain"
& "$HOME\.brain\venv\Scripts\brain.exe" --version
```

Add `"brain[tui] @ ..."` for the cockpit's full-screen app (Textual); without it, `brain tui` draws a text view.

### 3. Your brain

Pick a folder outside any other repo, and your name as it should appear (in your queue, your rules, your plugin):

```powershell
brain init "$HOME\my-brain" --owner "Your Name"            # the plan: what it would write
brain init "$HOME\my-brain" --owner "Your Name" --apply    # writes it; a second apply changes nothing
cd "$HOME\my-brain"
git init
git add -A
git commit -m "my brain"
brain check                                                # graph-check OK, boundary ... public scan green
```

`brain init` writes the generic template: `config.json` (you, the engine's tag, the Lite profile, and the names that
must never reach a public repo: yours, this machine's user and host), `projects.yaml`, the backlog graph
(`notes/graph`), the decision log and the journal, starter rules (`rules/global.md`: edit them, they are yours),
`boundary.yaml` with a `fixtures/` folder (whatever may be published one day holds nothing private, from the first
commit), and a local Claude Code marketplace (`.claude-plugin/`, `plugins/brain-core/`). It never overwrites a file.

Push it, if you want a remote, to a **private** repo in your own account or organisation, never a public one.

### 4. Claude Code (optional)

Your brain's own folder is a Claude Code marketplace. Once:

```powershell
claude plugin marketplace add "$HOME\my-brain"
claude plugin install brain-core@brain
```

Each new session then gets your rules (`rules/global.md`), the decisions waiting on you, and the guards: a session
cannot push to production checkouts, publish a repo, commit a secret or do an action that is yours alone; it puts it
in your queue instead (`brain queue`). After an engine upgrade, `brain sync` renders the plugin again.

Optional: `install.ps1 -Personal "$HOME\my-brain"` (a plan; `-Apply` to do it) adds the engine's narrow allow rules
for its own commands to your Claude Code settings and copies the brain's memory notes. Read its plan first.

### 5. First steps

```powershell
brain profile                                              # this machine, and the Lite profile
brain item add wi-first --title "My first item" --priority P1 --reason "trying the brain"
brain decision ask --title "Pick a name" --question "Which name?" --option "Orion: short" --option "Atlas: taken" --why "short and free"
brain journal add --title "First day" "Installed the brain."
brain refresh --on-main                                    # regenerate the views and check
brain status
brain queue                                                # what waits on you
brain tui                                                  # the cockpit (brain tui --once: one screen of text)
```

`brain refresh` alone only checks in the main checkout (the views are refreshed from a worktree); working directly
in the main checkout, use `brain sync` after an edit, or `brain refresh --on-main`. Every command has `--help`.

## Linux and macOS

Python 3.10+, `python3-venv` (Debian, Ubuntu) and git; bash is there already.

```bash
python3 -m venv ~/.brain/venv
~/.brain/venv/bin/pip install "brain @ git+https://github.com/RoJLD/brain.git@v0.2.1#subdirectory=packages/brain"
mkdir -p ~/.local/bin && ln -sf ~/.brain/venv/bin/brain ~/.local/bin/brain    # ~/.local/bin on your PATH
brain --version
brain init ~/my-brain --owner "Your Name" --apply
cd ~/my-brain && git init && git add -A && git commit -m "my brain" && brain check
```

Then steps 4 and 5 above, with `~/my-brain` for the folder.

## Upgrade, uninstall

- **Upgrade** to a new tag: the same `pip install` (or `install.ps1 -Apply` from a clone of that tag), then, in your
  brain, `brain sync` (the plugin's hooks) and move `engine.pin` in `config.json` to the new tag.
- **Uninstall**: `claude plugin uninstall brain-core@brain` and `claude plugin marketplace remove brain`, delete
  `~/.brain` (the venv, the ledgers, the pointer) and remove `~/.brain\bin` from your user PATH. Your brain repo is
  yours to keep.

## When something fails

`brain --version`, `brain profile` and `brain check` tell most of it. The [pilot guide](pilot.md) says how to report
an issue.
