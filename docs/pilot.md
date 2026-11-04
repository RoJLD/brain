# The brain pilot

Thank you for trying the brain. This page says what the pilot is, what to try in about an hour, and how to tell us
what went wrong. The install itself is in [install.md](install.md).

## What the pilot is

- **Free and self-hosted.** You install the public engine (this repo, at the tag you were given) on your own machine.
  Nobody hosts anything for you, and nothing is billed.
- **Your data stays yours.** Your brain is a folder and a git repo of your own, pushed (if at all) to a private repo
  in your own account or organisation. The engine sends nothing anywhere: telemetry is off by default, and there is
  no account and no upload. Once your version has `brain update`, the cockpit reads the public repo's release tags once a day (a `git
  ls-remote`, no token) to tell you an update is out; it sends nothing about you. Its machine-local state stays in
  `~/.brain`.
- **Your keys are yours.** Claude Code runs on your own subscription or API key; the brain never reads, stores or asks
  for a key, and its guard refuses to commit one.
- **Nothing is pooled.** What you write is never collected, compared with other testers' or used to train anything.
  When you send us a report, you choose what is in it.
- **The licence.** From 0.2.2 the brain command is under the Business Source License 1.1
  ([packages/brain/LICENSE](../packages/brain/LICENSE)): you may use, modify and run it for your own work and reuse
  it in your own products, with a visible credit to Brain and its author and its `NOTICE` file kept; offering it to
  others as a hosted or managed service needs a commercial licence. `research-graph` stays under the MIT License.
- **No guarantee of service.** It is a pilot: things will break, and the engine changes between tags. The pilot
  agreement you signed says the rest.

## What to try (about an hour)

1. **Install** (install.md, steps 1 to 3): the command, then `brain init` and the first commit. Note anything that
   was unclear or failed, and how long it took. Before a Claude Code session, set the pilot's three settings
   (install.md, *Before the first session*): `BRAIN_MEMORY_SYNC=0`, the engine's venv at `%USERPROFILE%\.brain\venv`
   (or `BRAIN_PYTHON`), and Git Bash's `HOME` the same as your user folder (or `BRAIN_HOME`).
2. **The backlog.** Add three items, one after another (`brain item add ID --title ... --after OTHER`), set a priority
   (`brain item set ID priority=P1`), close one (`brain item close ID --pr "none"`, or the PR that did it), then
   `brain sync` and look at `notes/kanban_graph.md`.
3. **A decision.** Ask yourself one (`brain decision ask ...` with two options, the recommended first), see it in
   `brain queue`, answer it (`brain decision answer ID <option>`).
4. **The journal and the history.** `brain journal add --title "Day 1" "what I did"`, then `brain status` and
   `brain digest`.
5. **The cockpit.** `brain tui` (or `brain tui --once`): does it show your name, your queue, your items?
6. **With Claude Code** (install.md, step 4), on a small project of yours: start a session in your brain's folder.
   Does it know your rules? Ask it to add an item or ask you a decision through the `brain` commands. Ask it to do
   something that is yours alone (`gh repo create test --public`, say): the guard should refuse and point to your
   queue.
7. **Publishable by construction.** Add a file under `src/` or `fixtures/` with your own name in it, `git add` it and
   run `brain check`: it should refuse. Take the name out: it passes.

Anything else you want to try is welcome; what you expected and did not get is the most useful thing to tell us.

## Updates during the pilot

Fixes come as new tags (0.2.4 brought `brain update`, 0.2.5 the lessons, merge-check and the schedules, then later ones), announced by the person who invited you. 0.2.2 has no update
command: move to the next tag by hand (install.md, *Upgrade by hand*) until your version has one
(`brain update --help` answers). From then on, `brain update` shows what changes and installs it on your `y`, and the
cockpit's title bar (`brain tui`) says when a newer version is out (`u` opens the same plan). Nothing is ever
installed without your yes. After an update, set `engine.pin` in your brain's `config.json` to the new tag and
commit it, then `brain sync` (it refuses until the pin is the engine you run) and restart Claude Code's sessions.

## How to report an issue

Send what you found to the person who invited you, by the channel you agreed on. For a bug, please give:

- what you did (the command), what you expected, and what happened (the output, as text);
- `brain --version`, your OS and Python version (`py -3 --version` or `python3 --version`);
- `brain check` and, if it is about the machine, `brain profile` (it shows your machine's name and hardware: remove
  what you would rather not share).

You may also open an issue on [RoJLD/brain](https://github.com/RoJLD/brain/issues): it is **public**, so put nothing
of your brain in it (no item titles, decisions, paths, names or keys), only the commands and the engine's messages.

Never send your brain repo, `~/.brain`, a session transcript or a key: we do not need them, and the pilot never asks
for them.

## Ending the pilot

Your brain stays yours: keep using it, or delete it. To remove the engine, see *Upgrade, uninstall* in install.md.
