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
from the tag you were given (here v0.2.4):

```powershell
git clone --depth 1 --branch v0.2.4 https://github.com/RoJLD/brain.git "$HOME\brain-engine"
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\brain-engine\packages\brain\installer\install.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\brain-engine\packages\brain\installer\install.ps1" -Apply
```

`-ExecutionPolicy Bypass` applies to that one run only; it changes no setting. Open a new PowerShell window, then:

```powershell
brain --version        # brain 0.2.4
```

Without the installer, the same by hand (the venv must be `~/.brain\venv` for the hooks to find it):

```powershell
py -3 -m venv "$HOME\.brain\venv"
& "$HOME\.brain\venv\Scripts\python.exe" -m pip install "brain @ git+https://github.com/RoJLD/brain.git@v0.2.4#subdirectory=packages/brain"
& "$HOME\.brain\venv\Scripts\brain.exe" --version
```

Add `"brain[tui] @ ..."` for the cockpit's full-screen app (Textual); without it, `brain tui` draws a text view.

The Claude Code hooks look for the engine's Python in `%USERPROFILE%\.brain\venv`. If you install it anywhere else,
set the user variable `BRAIN_PYTHON` to that venv's `python.exe`: otherwise the hooks pick a Python that has no
brain, and the guards let every call through.

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

**Before the first session**, check three things. They are your user environment variables (System settings, or
`[Environment]::SetEnvironmentVariable('NAME', 'value', 'User')` in PowerShell), set once; open a new window after.

- **Memory sync off for the pilot: `BRAIN_MEMORY_SYNC=0`.** At the end of each session the core plugin's memory hook
  copies Claude Code's memory notes of every project into your brain and pushes them to your brain's remote by a PR.
  Turn it off until you have decided you want that: `[Environment]::SetEnvironmentVariable('BRAIN_MEMORY_SYNC', '0', 'User')`.
- **The engine's Python**: the venv at `%USERPROFILE%\.brain\venv` (the installer's), or `BRAIN_PYTHON` naming it
  (step 2). In a session, `brain --version` must answer.
- **Git Bash's HOME is your user folder.** The hooks run in Git's bash and find `~/.brain` from its `HOME`; Python
  finds it from `%USERPROFILE%`. In Git Bash, `echo $HOME` should print `/c/Users/<you>`. If it prints anything else
  (a `HOME` variable set for another tool), set `BRAIN_HOME` to `%USERPROFILE%\.brain` so that both read the same
  folder.

Telemetry is off by default: the engine sends nothing anywhere, and nothing changes that unless you turn it on.

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
~/.brain/venv/bin/pip install "brain @ git+https://github.com/RoJLD/brain.git@v0.2.4#subdirectory=packages/brain"
mkdir -p ~/.local/bin && ln -sf ~/.brain/venv/bin/brain ~/.local/bin/brain    # ~/.local/bin on your PATH
brain --version
brain init ~/my-brain --owner "Your Name" --apply
cd ~/my-brain && git init && git add -A && git commit -m "my brain" && brain check
```

Then steps 4 and 5 above, with `~/my-brain` for the folder.

## Upgrade, uninstall

- **Upgrade with `brain update`** (a version that has it: `brain update --help` answers): it prints the plan (the
  new version, what its CHANGELOG says, the install into `~/.brain\venv`, the launcher swap) and installs it when you
  answer `y`; `brain update --check` only prints it. The cockpit's title bar shows the installed version and, when a
  newer one is out, « brain X · Y available »; `u` opens the same plan. Then, in your brain, move `engine.pin` in
  `config.json` to the new tag and commit it (the plan reminds you; otherwise the installer's next `-Apply` puts the
  pinned tag back), then `brain sync` (the plugin's hooks). Until the pin moves, `brain sync` refuses to write with an
  engine other than the pinned one and says which line to change.
- **Upgrade through your brain's installer**, when your brain has one and declares it (`config.json` `engine`
  `installer`, say `"install.ps1"`): after the PR that moves `engine.pin`, the cockpit's title bar reads « brain X ·
  pin vY: -Apply » and `u` shows that installer's plan, then runs `-Apply` on `y` in a new window, once the cockpit
  has closed, and opens the cockpit again.
- **Upgrade by hand** (0.2.2, and any version where `brain update --help` fails): the same `pip install` with the new
  tag, in the venv, for instance
  `& "$HOME\.brain\venv\Scripts\python.exe" -m pip install "brain[tui] @ git+https://github.com/RoJLD/brain.git@v0.2.4#subdirectory=packages/brain"`
  (or `install.ps1 -Apply` from a clone of that tag, which also swaps the launcher), then `brain --version`,
  `engine.pin` moved and committed as above, then `brain sync` in your brain.
- **Uninstall**: `claude plugin uninstall brain-core@brain` and `claude plugin marketplace remove brain`, delete
  `~/.brain` (the venv, the ledgers, the pointer) and remove `~/.brain\bin` from your user PATH. Your brain repo is
  yours to keep.

## When something fails

`brain --version`, `brain profile` and `brain check` tell most of it. The [pilot guide](pilot.md) says how to report
an issue.
