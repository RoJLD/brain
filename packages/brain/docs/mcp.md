# The Brain as an MCP server

`brain mcp serve` (`brain.mcpserver`, `wi-brain-mcp-server`) lets any agent that speaks the Model Context Protocol
read and use the Brain the way Claude Code does through its files and the `brain` command: Cursor, other desktop
clients and, once the owner decides to expose it, hosted agents. One tool layer serves two transports, so a tool
behaves the same on either.

Nothing starts on its own. `brain mcp serve` runs in the foreground of whoever launched it; the container definition
never restarts by itself. Running it as a service, and anything that makes it reachable from another machine, is the
owner's decision.

## What it serves

Read from the personal brain it runs in (`brain --root DIR mcp serve`, else the personal brain `brain` finds):

| MCP primitive | What | Where it comes from |
|---|---|---|
| resources | `brain://rules/<file>`: each rules file of the neutral source, as an agent reads it (`# title`, intro, the rules, ids taken out) | `source/rules/` (`brain.neutral`) |
| resources | `brain://procedures/<name>/<file>`: each file of each procedure | the engine's procedures, the owner's laid over them |
| resources | `brain://decisions`: the decision log's index (date and title of every ADR) | `notes/decisions.md` |
| resource template | `brain://decisions/{ref}`: one ADR by its id, title or the start of its id | `brain adr show` |
| prompts | each procedure (its `SKILL.md`), with an optional `task` argument | the procedures |
| tools | see below | |

`brain mcp tools` lists the tools:

| Tool | Kind | What it runs |
|---|---|---|
| `brain_items` | read | `brain items` with its filters (status, text, wave, priority, type, milestone, limit) |
| `brain_item_show` | read | `brain item show ID` |
| `brain_adr_show` | read | `brain adr show REF [--titles]` |
| `brain_spec_show` | read | `brain spec show REF [--section N \| --toc]` |
| `brain_next` | read | `brain next` |
| `brain_check` | read | `brain check` |
| `memory_read` | read | the memory notes of this machine: the folders, a folder's notes, a note |
| `memory_propose` | write | writes a note into this machine's memory folder of a project; the memory sync exports it by a reviewed PR, never to main (`brain memory`) |

A graph tool takes an optional `project` (a registered project; default: the brain's own). The memory tools'
`project` is a memory folder's key (`memory_read` with no argument lists them), required by `memory_propose`. A graph
tool runs the `brain` command in a child process with a deadline (`BRAIN_MCP_TIMEOUT`, seconds, default 120). Its
arguments are validated first: an id never starts with `-`, a free text goes as `--text=VALUE`, an argument the tool
does not declare is refused, and nothing runs when one is wrong. `brain_spec_show`'s `ref` stays inside the project's
repos: a Spec id, a Doc id or a relative path, never an absolute path, a drive, a backslash or a `..` part
(`brain spec show` reads the path it is given). `memory_propose` refuses a note whose text matches a secret pattern,
and a project folder that does not exist on this machine.

**No secret in an answer.** Every answer (a tool's, a resource's, a prompt's) passes `brain.secretscan.clean` before
it is cut to its size limit: a line with a key's shape is dropped, and the answer says how many lines were; the whole
result is scanned again, names and descriptions included. An internal error reaches the client as its type only; the
detail goes to the server's stderr. The scan knows keys by their shape: it is a net, not a reason to serve a file.

## The guards

Other clients run none of Claude Code's hooks, so the server applies the guards itself (`brain.mcpguards`,
`wi-brain-mcp-guards`): every tool call is judged before it runs, and a refused call runs nothing. Each tool states
what its call does as the payload a `PreToolUse` hook would get (its effect): a `brain` command is a Bash call of that
command in the brain's root; `memory_propose` is a Write of its note's path. In order:

1. **The tool's declaration.** A write tool that declares no effect is refused, and so is an effect the guards do not
   read (anything but a shell call or a file write: starting an agent or a session, say): a guard that exists only as
   a Claude hook is ported, or its tool is refused.
2. **The owner's gestures.** The `brain` commands only the owner runs are refused whatever the tool: `decision
   answer`, `queue done`, `schedule install`, `ipc` (`token`, `otel-headers`), `vault`, `identity`, `update`,
   `init`, `up`, `down`, `bundle apply`, `permissions grant`, `session-archive`, and any `--arm` (or a prefix argparse
   expands to it). A
   command behind an option that is not `--root`, `--project` or `--store` spelled in full (`--proj=P`, which
   argparse would expand) is refused: it could not be read.
3. **The secret scan of a write's arguments.** A string argument of a write tool that matches a secret pattern is
   refused; nothing is written.
4. **The engine's guards** (`brain.guards.refusals`, strict) on the effect: on a shell call, production checkouts,
   the owner's never-grantable categories, power and cluster, third-party kits, attribution, the public and secrets
   checks, conflict markers and branch names; on a file write (`memory_propose`), production checkouts and the
   owner's categories (step 3 covers its text). Strict: a check that fails to judge the call refuses it, where a hook
   lets it through. The resource `brain://decisions/{ref}`, which runs `brain adr show`, is judged the same way.

`BRAIN_GUARD_ALLOW` lifts nothing here, so the one variable meant to lift the guards cannot be set in a client's
configuration file, which an agent may be able to edit. The rest of the server's environment is the owner's
configuration: whoever writes that file also chooses `BRAIN_HOME`, `BRAIN_PROJECTS` (the production checkouts) and
`BRAIN_CAPTURE`, as for any `brain` command; keep it the owner's file. A refusal reaches the client as a tool error, `refused by the <guard> guard: <reason>`,
and goes to the guards ledger (`<BRAIN_HOME>/ledger/guards-<month>.jsonl`, when it exists) with the tool as
`mcp:<name>` and the client's name as its session. Then every answer passes the secret scan (above).

| Claude Code hook | For an MCP client |
|---|---|
| `guard.sh` (PreToolUse: shell, edit, scheduled tasks, session settings, Terminal) | ported: step 4 judges every call's effect |
| `governor.sh` (PreToolUse: agents, workflows, sessions) | no tool starts an agent or a session; an effect that would is refused (step 1) until the governor is ported |
| `readhint.sh` (PreToolUse: read hints) | a hint, not a guard: no tool reads arbitrary files |
| `inject-rules.sh`, `announce.sh`, `health.sh`, `resume.sh`, `memory.sh` (SessionStart) | context: the rules and procedures are resources and prompts, the instructions say to read the rules first |
| `capture.sh`, `budget.sh`, `midsession.sh` | measure Claude's own sessions: the calls' refusals go to the guards ledger; per-client attribution is `wi-brain-agent-attribution` |

Git's own hooks stay the second line for what reaches a repository, whichever agent wrote it.

## The transports

### stdio (the default)

The client launches `brain mcp serve` and speaks newline-delimited JSON-RPC 2.0 on its stdin and stdout (UTF-8, bare
newlines). Nothing is exposed. A client's configuration, Cursor's `~/.cursor/mcp.json` for instance:

```json
{"mcpServers": {"brain": {"command": "brain", "args": ["mcp", "serve"]}}}
```

### HTTP on loopback, with the machine's token

`brain mcp serve --http [--host 127.0.0.1] [--port 8791]` speaks Streamable HTTP: a `POST /mcp` per message (or
batch), each answer a JSON body; a notification gets `202`. The server sends no request of its own, so it opens no
stream: `GET` and `DELETE` answer `405`.

- **Loopback only.** It refuses to bind any address but 127.0.0.0/8, `::1` or `localhost`. Inside its container
  (`BRAIN_MCP_CONTAINER=1`, set by the image) it binds the container's addresses, and the compose file publishes the
  port on `127.0.0.1` only.
- **The machine's token** on every request: `Authorization: Bearer <token>`, compared in constant time; without it,
  `401`. The token is the one `brain ipc token --init` makes once (below); the server refuses to start without one.
- **Host and Origin.** A request whose `Host` is not a loopback name, or whose `Origin` names another host (a page in
  a browser, DNS rebinding), gets `403`.
- **Limits.** A body over 1 MB gets `413`; an `MCP-Protocol-Version` header naming a version it does not speak gets
  `400` (it speaks 2025-06-18, 2025-03-26 and 2024-11-05). A refused request closes its connection, and a connection
  silent for 30 s is closed.

A client's configuration with a header, the token taken from an environment variable the owner fills from the file:

```json
{"mcpServers": {"brain": {"url": "http://127.0.0.1:8791/mcp",
                          "headers": {"Authorization": "Bearer ${env:BRAIN_IPC_TOKEN}"}}}}
```

## The machine's token: `brain ipc token`

One token per machine for every local service the Brain starts (`brain.ipcauth`), in `<BRAIN_HOME>/ipc/token`
(`$BRAIN_IPC_TOKEN_FILE` names another file; the container reads the copy its compose file mounts as a secret).

- `brain ipc token`: the file, and whether it holds a usable token (exit 1 when not).
- `brain ipc token --init`: makes it when there is none, from 32 random bytes, the file readable by its owner only;
  an existing usable token is kept. A rotation is the file's deletion, then `--init`, then each client updated. The
  server reads the file on each request: the old token is refused at once, with no restart (and while there is no
  file, every request is).
- `brain ipc otel-headers`: the headers of Claude Code's OTLP export, for its `otelHeadersHelper` setting (below,
  « The Brain's other local services »).

The token is printed only by `brain ipc otel-headers`, to the helper that runs it; it is never in a log line (the
server logs the request line and the status only) and never in the image.

## The Brain's other local services (`wi-brain-local-ipc-auth`)

Every local service the Brain starts binds a loopback address and, where it can check one, requires the machine's
token; its container runs as a user that is not root.

| Service | Loopback | Token |
|---|---|---|
| `brain mcp serve --http` | always (it refuses another address) | always |
| the collector (`otel-collector` of the sovereign bundle) | its ports published on 127.0.0.1 (`brain bundle plan` refuses another) | opt-in: `config.json` `"ipc": {"require_token": ["otel-collector"]}`, then `brain bundle apply` |
| the other sovereign components (Prometheus, Loki, Grafana, Qdrant) | published on 127.0.0.1 | Grafana its own login; the others none |
| GitNexus (the code index) | its port on loopback | none: GitNexus has no authentication of its own |

**The collector's token is opt-in**, because it newly refuses a client that sends none (a patch never newly refuses).
With `ipc.require_token: [otel-collector]`, `brain bundle apply` renders:
- the collector's configuration with otelcol-contrib's `bearertokenauth` extension on every OTLP receiver (gRPC and
  HTTP), the token read from `/run/secrets/brain_ipc_token`;
- that secret in the compose file, from the machine's token file. The component waits for the owner while the token
  is missing (`brain ipc token --init`).

Claude Code's export then needs the header. **`brain ipc otel-headers`** gives it: Claude Code's `otelHeadersHelper`
setting runs a command at startup and every 29 minutes (`CLAUDE_CODE_OTEL_HEADERS_HELPER_DEBOUNCE_MS`) and sends the
JSON object it prints as the export's headers. The command prints `{"Authorization": "Bearer <token>"}`, read from
the token file each time (a rotation reaches the export at its next refresh), and nothing else; without a usable
token it prints nothing on stdout, names the fix on stderr and exits 1: Claude Code then exports nothing and warns
once (`otelHeadersHelper failed; telemetry is not being exported`, also in `/status`). The setting sits in the
owner's user settings (`~/.claude/settings.json`), never a session's, written by the installer from the brain's
config.json (below, « Claude Code's export settings »), not by hand:

```json
{"otelHeadersHelper": "brain ipc otel-headers"}
```

- The helper works with the `http/protobuf` and `http/json` protocols (`OTEL_EXPORTER_OTLP_PROTOCOL`); with `grpc`,
  Claude Code sends only the static `OTEL_EXPORTER_OTLP_HEADERS`.
- It prints a key, so a session does not run it: the owner guard refuses it whatever runs it (category `keys`, as
  `gh auth token`), and so does the MCP server (`ipc` is an owner's gesture). This is a layer, not a wall: the
  guards do not yet refuse a session that reads the token file itself.
- Without the helper, the static fallback is `OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer <token>` in Claude
  Code's environment. Its limit: the token then sits in clear in that environment (every child process inherits it,
  and a rotation means editing it again), where the helper keeps it in the token file.

### Claude Code's export settings (`wi-brain-install-claude-telemetry`)

The brain records them; the installer writes them. config.json `adapters.claude.telemetry`:

```json
{"adapters": {"claude": {"telemetry": {"enabled": true}}}, "ipc": {"require_token": ["otel-collector"]}}
```

| Key | Default | Claude Code's setting |
|---|---|---|
| `enabled` | false (nothing written) | `env.CLAUDE_CODE_ENABLE_TELEMETRY` = `1` |
| `endpoint` | `http://127.0.0.1:4318` (the sovereign collector's OTLP HTTP port) | `env.OTEL_EXPORTER_OTLP_ENDPOINT` |
| `protocol` | `http/protobuf` (or `http/json`, `grpc`) | `env.OTEL_EXPORTER_OTLP_PROTOCOL` |
| `exporters` | `["metrics", "logs"]` | `env.OTEL_METRICS_EXPORTER`, `env.OTEL_LOGS_EXPORTER` = `otlp` |
| `env` | none | other `OTEL_*` variables, as strings (`OTEL_METRIC_EXPORT_INTERVAL`, say) |
| `headers_helper` | `auto`: when `ipc.require_token` names `otel-collector` (or `always`, `never`) | `otelHeadersHelper` = `brain ipc otel-headers` |

`brain ipc claude-settings [--json] [--settings FILE]` renders them (it prints no secret). It refuses, exit 1 and
nothing for the installer to write: an endpoint with a user part, a backslash or a space (two URL parsers could read
two hosts there); the helper with `grpc` (Claude Code would not send it) or with an endpoint off loopback (the
machine's token would leave it; loopback is read strictly: `127.x.x.x`, `localhost`, `[::1]`); an `env` name that is
not `OTEL_*`, one that names headers (the token goes through the helper, never in clear in `settings.json`), or one
the section's own keys set. Since the installer only adds, the helper is judged against the export Claude Code's user
settings would then make: an endpoint off loopback (`OTEL_EXPORTER_OTLP_ENDPOINT` or a signal's own,
`OTEL_EXPORTER_OTLP_METRICS_ENDPOINT` say) or a `grpc` protocol already there, and kept, refuses it too.

`install.ps1` (its telemetry step, after the permissions) adds them to `~/.claude/settings.json`
(`$CLAUDE_CONFIG_DIR` when set): the plan says each one it would set, `-Apply` writes them. Additions only: a key
already there with another value is kept and said, its value never printed (one the owner set may be a secret), and
nothing is removed; turning the section off writes nothing and takes nothing out. `settings.json` is handled as the
permissions step handles it (refused when it is not a JSON object, kept as it was in `settings.json.bak`). An
installed brain command older than `brain ipc claude-settings` only says so.

An engine older than this one does not know the section: in strict mode (CI) `brain config --check` refuses it as an
unknown key, so a personal brain moves `engine.pin` to a release that has it before (or with) the section.

The order of the collector's switch (the owner's): `brain ipc token --init`, the section with `enabled: true` and
`install.ps1 -Apply` (the helper is written once `ipc.require_token` names the collector, so both in one change of
config.json), then `brain bundle apply sovereign`, then `brain health ipc`.

On a Linux host the secret is the token file itself, mode 0600 and owned by the owner: give the collector's user
(10001 in its image) read access with an ACL, `setfacl -m u:10001:r <BRAIN_HOME>/ipc/token`. `brain health ipc`
accepts a group bit or an ACL entry, and refuses a token readable by every user.

**`brain health ipc`** (and `brain health --all`) reads, starts nothing, and says on one line each:
- the token file (usable; on POSIX not readable by every user);
- the MCP server: a request without the token must get 401 (`ipc.mcp_port`, default 8791; nothing answering: OFF;
  another program answering while the machine has no token: OFF too, since no MCP server can run without one);
- each running container of the Brain's Compose projects (`brain-sovereign`, `brain-mcp`) and of the code index:
  a port published beyond loopback is a FAIL, a container running as root a warning (Qdrant's image does);
- which services take requests without the token (the collector while not opted in, GitNexus);
- when the collector requires the token, Claude Code's export as its user settings say it: on with no
  `otelHeadersHelper` is a FAIL (the collector refuses the export: the section above, then `install.ps1 -Apply`), the
  helper with `grpc` or with an endpoint off loopback too (it would not be sent, or would send the token away), the
  token in clear in `OTEL_EXPORTER_OTLP_HEADERS` a warning; the export off, or one that goes off loopback without the
  helper (another backend's, not the collector's), is OK. Project or managed settings are not read.

Exit 1 on a FAIL. A required token that is missing is a FAIL. Under `--all`, a machine that never made the token and
requires none gets no line: nothing is probed and Docker is not asked, so `--all` says what it said before. Its
containers are then not inspected either: `brain health ipc`, named, always inspects them.

### What the collector keeps (`wi-brain-otel-telemetry`)

Claude Code's export puts the account on every record: `user.email` in clear, `user.account_uuid` and
`user.account_id`, and `process.owner` (the system's user name) on the resource. A tool's parameters
(`tool_parameters`: an MCP call's server and tool, a shell command with `OTEL_LOG_TOOL_DETAILS`) and a failure's
`error` are text that can quote a command's output. The collector's processors (`compose/sovereign/otelcol.yaml`), in
every pipeline and before any exporter (Prometheus, Loki, the JSONL files):

| Processor | Pipelines | What it does |
|---|---|---|
| `transform/tool-names` | logs | copies the names a call's parameters carry to `mcp_server.name`, `mcp_tool.name` and `skill.name` |
| `attributes/private` | metrics, logs | deletes `prompt`, `prompt_text`, `response`, `tool_parameters`, `error`, `user.email`, `user.account_uuid`, `user.account_id` and `process.owner` from a data point's or an event's attributes |
| `resource/private` | metrics, logs | deletes the same keys from the resource |

A failure keeps its class (`error_type`), never its text (the owner's decisions ST-7 and ST-8).
`OTEL_LOG_USER_PROMPTS` and `OTEL_LOG_TOOL_DETAILS` stay off in Claude Code's settings; the processors hold even when
one is turned on. `session.id` (the transcript's id) and the pseudonymous `user.id` and `organization.id` are kept:
the first joins a record to the session tree. `tests/test_otel.py` checks every pipeline of the shipped file; where
the collector's pinned image is on the machine, it also sends the fixtures through it and reads what comes out.

The collector reads its configuration when it starts: after `brain bundle apply sovereign` writes a new one,
`brain down otel-collector` then `brain up otel-collector` restarts it on that file. What it wrote before keeps those
attributes until its rotation drops the file (31 days, `max_days`), and so do Loki and Prometheus within their
retention; `brain telemetry` drops them when it reads (README, « Claude Code's telemetry »).

The processors are a denylist, so a key a newer Claude Code adds is kept until someone looks at it:
`brain.otel.KNOWN_KEYS` lists the keys reviewed, `brain telemetry summary` names any other it meets, and
`tests/test_otel.py` fails on one in its fixtures, which are refreshed from the real files.

`brain telemetry status` says whether the export is on (config.json `adapters.claude.telemetry` and Claude Code's user
settings), whether the collector's health endpoint answers (`http://127.0.0.1:13133/`, the whole answer within
`--timeout`, 1 s by default, no redirect followed; on Windows a refused loopback connection is retried for about 2 s,
so a stopped collector reads « stopped, or slow ») and how old each exported signal's last record is. On, answering,
nothing for `--stale-hours` (24) and a transcript under `$CLAUDE_CONFIG_DIR/projects` written more than that after
the last record (a bounded walk) is a FAIL: the collector receives nothing (its endpoint or its token:
`brain health ipc`). Without such a transcript it is a warning, no activity: Claude Code exports only while a
session runs. Answering while the export is off is a warning too. `brain telemetry summary` reads the files.

## The container

`packages/brain/container/` holds the image's definition, versioned with the engine:

- `Dockerfile`: the base image pinned by digest, the engine installed from this checkout, a user that is not root
  (uid 10001), the image's version label from the build argument `BRAIN_VERSION`. Build it from the repo's root:
  `docker build -f packages/brain/container/Dockerfile --build-arg BRAIN_VERSION=<version> -t brain-mcp:<version> .`
- `compose.yaml`: the personal brain's checkout mounted read-only at `/brain` (`BRAIN_ROOT_DIR`), the token file as a
  secret (`BRAIN_IPC_TOKEN`), the port published on `127.0.0.1:8791`, a read-only root file system, every capability
  dropped, no new privileges, `restart: "no"`. Its `BRAIN_HOME` is a named volume. On a Linux host, outside swarm
  mode, the secret is the token file itself (its owner, mode 0600): run the container as that file's owner with
  `BRAIN_UID=$(id -u) BRAIN_GID=$(id -g)` (default 10001). The server refuses to serve as root in its container.

A remote endpoint (a tunnel, the cluster) waits on the owner's answers to the connector spec's open questions: which
projects it serves, which providers, where it runs.
