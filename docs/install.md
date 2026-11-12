# Install the brain from zero

This guide takes a machine with nothing on it to a working brain of your own: the `brain` command installed from a
tag of this repo, a private brain repo created by `brain init`, and, if you use it, Claude Code reading its rules and
guards. Windows first; Linux, then macOS, at the end. It needs no Docker, no GPU and no service: the Lite profile is the
default, and every command reads files and git, never a model.

Your brain is yours: it lives in a folder and a git repo of your own, in your own account or organisation. The engine
sends nothing anywhere (no telemetry, no account); its machine-local state lives in `~/.brain`. You hold your own keys.

Read this page at the tag you install, `https://github.com/RoJLD/brain/blob/<tag>/docs/install.md` (for instance
[`blob/v0.3.2`](https://github.com/RoJLD/brain/blob/v0.3.2/docs/install.md)): `main` may already describe commands
that your tag does not have.

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
from the tag you were given (here v0.3.2):

```powershell
git clone --depth 1 --branch v0.3.2 https://github.com/RoJLD/brain.git "$HOME\brain-engine"
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\brain-engine\packages\brain\installer\install.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "$HOME\brain-engine\packages\brain\installer\install.ps1" -Apply
```

`-ExecutionPolicy Bypass` applies to that one run only; it changes no setting. Open a new PowerShell window, then:

```powershell
brain --version        # brain 0.3.2
```

Without the installer, the same by hand (the venv must be `~/.brain\venv` for the hooks to find it):

```powershell
py -3 -m venv "$HOME\.brain\venv"
& "$HOME\.brain\venv\Scripts\python.exe" -m pip install "brain @ git+https://github.com/RoJLD/brain.git@v0.3.2#subdirectory=packages/brain"
& "$HOME\.brain\venv\Scripts\brain.exe" --version
```

Add `"brain[tui] @ ..."` for the cockpit's full-screen app (Textual); without it, `brain tui` draws a text view.

The Claude Code hooks look for the engine's Python in `%USERPROFILE%\.brain\venv`. If you install it anywhere else,
set the user variable `BRAIN_PYTHON` to that venv's `python.exe`: otherwise the hooks pick a Python that has no
brain, and the guards let every call through.

### 3. Your brain

**Git's identity, once per machine.** Every commit carries a name and an email, and a fresh Git for Windows has
neither: the first commit below would stop at « Author identity unknown ». `git config --global user.email` prints
yours; if it prints nothing, set both (any email works for a private repo; GitHub's `...@users.noreply.github.com`
address keeps yours out of the commits you push):

```powershell
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

`brain init --apply` prints these two lines in its next steps when git has no identity yet.

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

To choose your modules at the same time (who you are, your machine, adjust: three screens, offline), add
`--interactive`; it ends on the same choice as one command (`--preset default --with tui`, say), each step of which is
a `brain` command it shows, then runs and logs at `--apply`.

`brain init` writes the generic template: `config.json` (you, the engine's tag, the Lite profile, and the names that
must never reach a public repo: yours, this machine's user and host), `projects.yaml`, the backlog graph
(`notes/graph`), the decision log and the journal, starter rules (`rules/global.md`: edit them, they are yours),
`boundary.yaml` with a `fixtures/` folder (whatever may be published one day holds nothing private, from the first
commit), and a local Claude Code marketplace (`.claude-plugin/`, `plugins/brain-core/`). It never overwrites a file.

Push it, if you want a remote, to a **private** repo in your own account or organisation, never a public one.

**The vault, before anything leaves this machine sealed.** `brain init` ends by naming it. Each part of your brain has
a data class that says where it may go (`brain classes`): the rules, graph and journal may sit in clear in your
private repo, the machine's ledgers and transcripts never leave it in clear. The vault seals what leaves the machine
to your own public keys (a device key per machine, an offline recovery key, a daily canary). Until you set it up,
nothing is sealed and nothing needs it: `brain health vault` says `vault OFF (... nothing is sealed yet)`. When you
want it, `brain vault status` lists the steps left and the [vault runbook](../packages/brain/docs/vault.md) walks
through them, in your own terminal.

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
- **One `.brain` folder.** The hooks run in Git's bash and, like Python, find `.brain` in `%USERPROFILE%` (from
  0.3.2; before, some hooks read Git Bash's `HOME`). When `BRAIN_HOME` is unset and a second `.brain` folder exists
  under another `HOME` (a variable set for another tool), the SessionStart health names both: move what the other
  holds into `%USERPROFILE%\.brain` and remove it, or set `BRAIN_HOME` to the one to keep.

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

## Linux

What follows ran on Ubuntu 24.04 (Python 3.12, git 2.43, PowerShell 7.6), in a container first: the installer under
`pwsh`, a brain of your own, the Lite scenario, the Claude Code hooks under bash and the guards on Linux paths. The
Lite profile asks for Python, git and bash; `pwsh` only runs the installer, so it is optional (by hand below).

### 1. What you need

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv git curl
```

For the installer, PowerShell from Microsoft's repository (optional):

```bash
. /etc/os-release
curl -fsSLo /tmp/ms.deb "https://packages.microsoft.com/config/ubuntu/$VERSION_ID/packages-microsoft-prod.deb"
sudo dpkg -i /tmp/ms.deb && sudo apt-get update && sudo apt-get install -y powershell
```

Name the machine before its first ledger line, in `~/.profile` (the ledgers, the memory notes and the profile carry
it; the host name otherwise):

```bash
echo 'export BRAIN_MACHINE=my-server' >> ~/.profile
```

### 2. The brain command

With the installer (a plan, then `-Apply`): its venv in `~/.brain/venv`, the `brain` command linked into
`~/.local/bin`, which Ubuntu's `~/.profile` puts on the PATH at the next login once the folder exists:

```bash
git clone --depth 1 --branch v0.3.2 https://github.com/RoJLD/brain.git ~/brain-engine
pwsh -NoProfile -File ~/brain-engine/packages/brain/installer/install.ps1
pwsh -NoProfile -File ~/brain-engine/packages/brain/installer/install.ps1 -Apply
exec bash -l               # a login shell again: ~/.local/bin, created by -Apply, is now on the PATH
brain --version
```

By hand, without `pwsh`:

```bash
python3 -m venv ~/.brain/venv
~/.brain/venv/bin/pip install "brain @ git+https://github.com/RoJLD/brain.git@v0.3.2#subdirectory=packages/brain"
mkdir -p ~/.local/bin && ln -sf ~/.brain/venv/bin/brain ~/.local/bin/brain
exec bash -l               # Ubuntu's ~/.profile puts ~/.local/bin on the PATH once it exists
brain --version
```

### 3. Your brain

Git's identity first, once, if `git config --global user.email` prints nothing (see the Windows section, step 3,
for why):

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

```bash
brain init ~/my-brain --owner "Your Name" --apply
cd ~/my-brain && git init && git add -A && git commit -m "my brain" && brain check
pwsh -NoProfile -File ~/brain-engine/packages/brain/installer/install.ps1 -Personal ~/my-brain            # the plan
pwsh -NoProfile -File ~/brain-engine/packages/brain/installer/install.ps1 -Personal ~/my-brain -Apply
```

The second run writes the pointer `~/.brain/personal.json`, defines the merge driver in your brain's git config, reads
the machine's profile (Lite on a server: `-Tier lite`), and plans the schedules (below). A brain cloned from an
existing remote takes the same two runs, or its own bootstrap (`pwsh ./install.ps1 -Apply` in it, when it has one).
The registry's projects whose roots are not on this machine are said `not found on this machine` by `brain status`,
`brain alerts` and `brain health`; nothing fails.

### 4. Claude Code (optional)

Anthropic's installer puts `claude` in `~/.local/bin`; then the steps of the Windows section 4, with `~/my-brain`. Its
login, like `gh auth login` and git's credentials, is yours to do on the machine. The hooks run under bash and find
the engine in `~/.brain/venv/bin/python`.

### 5. The schedules: the alerts pass on a machine that stays on

`brain schedule install` (the installer's schedule step) installs what the registry's `schedules:` declare for this
machine as a systemd user timer, `~/.config/systemd/user/brain-<name>.timer`, or in your crontab where no user
systemd runs (a container, WSL). Both run the command through `bash -lc`, so the variables of your `~/.profile`
reach it: `BRAIN_MACHINE`, and `BRAIN_NTFY_TOPIC` for the alerts pass (without it a pass sends nothing and says so).
A user timer runs while you are logged in; on a server, keep them running with, once:

```bash
loginctl enable-linger "$USER"
brain schedule list        # what is declared, installed, and the alerts pass's last run (SILENT after two cadences)
```

### macOS

Python 3.10+ and git; then section 2 by hand (or `pwsh` from Homebrew) and sections 3 to 4, git's identity included.
`brain schedule` has no macOS scheduler yet: its plan says so.

## Upgrade, uninstall

- **Upgrade with `brain update`** (a version that has it: `brain update --help` answers): it prints the plan (the
  new version, what its CHANGELOG says, its install into `~/.brain\venvs\vX.Y.Z` beside the running one, the health
  check run by it, then the switch of `~/.brain\venv`, a link the launcher follows, switched back if the new version
  does not answer) and installs it when you answer `y`; `brain update --check` only prints it. A failed check switches
  nothing: the version you had keeps running. The cockpit's title bar shows the installed version and, when a
  newer one is out, « brain X · Y available »; `u` opens the same plan. In a brain without an installer of its own
  (one from `brain init`: no `engine.installer` in `config.json`), the same `y` also moves `engine.pin` to the new
  tag, commits `config.json` and runs `brain sync` (the plugin's hooks); the plan shows it first. Run it in your own
  terminal: from a Claude Code session it refuses and says so. If your `config.json` has changes not committed, it
  leaves the pin and says so: commit them, then `brain update` again (it then moves the pin alone; so does the first
  `brain update` after an update to 0.2.6, which an older engine ran and which left the pin behind). In a brain that
  declares its installer, move `engine.pin` by a reviewed PR (the plan reminds you; otherwise the installer's next
  `-Apply` puts the pinned tag back), then `brain sync`. Until the pin moves, `brain sync` refuses to write with an
  engine other than the pinned one and says which line to change.
- **The tag's signature** (from 0.3.2): `brain update` and the installer check the tag with `git verify-tag` before
  installing it, and say `verify   vX.Y.Z: signed by ...` or why not. `brain update` reads the `releaser` keys of your
  `members.yaml` (else `allowed_signers`); the installer reads `allowed_signers` only, the file
  `brain identity allowed-signers --write` generates from those keys. With no key to check against they say so and
  install anyway; `config.json` `engine.verify_tags: true` makes them refuse a tag they cannot verify
  ([`packages/brain/docs/identity.md`](../packages/brain/docs/identity.md), « Signed releases »).
- **Upgrade through your brain's installer**, when your brain has one and declares it (`config.json` `engine`
  `installer`, say `"install.ps1"`): after the PR that moves `engine.pin`, the cockpit's title bar reads « brain X ·
  pin vY: -Apply » and `u` shows that installer's plan, then runs `-Apply` on `y` in a new window, once the cockpit
  has closed, and opens the cockpit again.
- **Upgrade by hand** (0.2.2, and any version where `brain update --help` fails): the same `pip install` with the new
  tag, in the venv, for instance
  `& "$HOME\.brain\venv\Scripts\python.exe" -m pip install "brain[tui] @ git+https://github.com/RoJLD/brain.git@v0.3.2#subdirectory=packages/brain"`
  (or `install.ps1 -Apply` from a clone of that tag, which also swaps the launcher), then `brain --version`,
  `engine.pin` moved and committed as above, then `brain sync` in your brain.
- **Uninstall**: `claude plugin uninstall brain-core@brain` and `claude plugin marketplace remove brain`, delete
  `~/.brain` (the venv, the ledgers, the pointer) and remove `~/.brain\bin` from your user PATH. Your brain repo is
  yours to keep.

## When something fails

`brain --version`, `brain profile` and `brain check` tell most of it. The [pilot guide](pilot.md) says how to report
an issue.
