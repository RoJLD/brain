<#
.SYNOPSIS
    Install the brain command on this machine and, for a personal brain, the owner's Claude configuration (plan by
    default, -Apply to change it).

.DESCRIPTION
    Idempotent. Without -Apply, prints what it would do and changes nothing. The personal brain is -Personal, else
    $env:BRAIN_PERSONAL, else the one <BRAIN_HOME>\personal.json points to, else the current folder when it holds a
    config.json; its main checkout is the one kept (a git worktree of it never is). Without one, only the command is
    installed: then brain init writes a personal brain, and a second run with -Personal sets it up. Its personal values
    come from its config.json (brain config): the engine and its tag (engine), the marketplace, the core plugin and the
    GitHub repo they are cloned from (adapters.claude), the global rules (rules).
      command      the brain command: its own venv (<BRAIN_HOME>\venv, default ~/.brain, from -Python or the python
                   on PATH, 3.10+) with brain installed at the tag config.json engine.pin names, from engine.repo
                   (pip install "brain @ git+https://github.com/<repo>.git@<pin>#subdirectory=packages/brain", which
                   brings research-graph at the same tag and PyYAML); without a personal brain, at this installer's
                   own version; -Engine <pip spec> installs another (a local checkout of packages/brain, say). Its
                   launcher is copied into <BRAIN_HOME>\bin and that folder alone added to the user PATH (no python.exe
                   there to shadow another); on Linux and macOS a link in ~/.local/bin. -SkipCommand leaves it out.
                   -Extras tui adds the cockpit's Textual app (brain tui; without it brain tui draws its text view).
      verify       before the install, the pin's tag fetched alone into a temporary repo and checked with git
                   verify-tag against the personal brain's allowed_signers (brain identity allowed-signers --write:
                   members.yaml's releaser keys); after pip, the commits it recorded are checked against the verified
                   one (a tag moved meanwhile). Said either way;
                   config.json engine.verify_tags: true refuses a tag unsigned, signed by another key or that cannot be
                   verified (docs/release.md). -Engine installs what it names, unchecked.
      pointer      <BRAIN_HOME>\personal.json, {"root": <the personal brain's main checkout>}: how the engine and its
                   hooks find the personal brain from anywhere ($env:BRAIN_PERSONAL overrides it)
      profile      this machine's profile (brain profile, alias brain doctor: Lite, Défaut, Recommandé,
                   Personnalisable), read once the brain command is installed: the pip extras it wants join -Extras
                   (Défaut, the built-in base, brings the cockpit's tui). -Tier lite|default|recommended, -With ID and
                   -Without ID change it: brain profile set prints the plan, and with -Apply writes
                   <BRAIN_HOME>\profile.json (recommended: the set this machine allows, frozen there). An extra the
                   profile no longer wants is left installed; the stacks it turns on start on demand (brain up).
      merge        with a personal brain: brain merge-driver install --repo <it> --launcher <the launcher above>,
                   which sets merge.brain.driver in that repo's git config (its worktrees share it), so that the paths
                   its .gitattributes gives merge=brain (brain init writes them: the generated views, the journal and
                   the decision log, the graph's YAML, CHANGELOG.md) merge without a hand in each worktree; a brain
                   command older than the subcommand only says so
      schedule     with a personal brain: brain schedule install, the brain commands its registry's schedules:
                   declare for this machine (projects.yaml: name, command, every / at / at_logon, machines; the
                   alerts pass every 15 minutes and at logon, say): the plan, then with -Apply the Task Scheduler
                   (\Brain\<name>, as you, in your session, through the venv's pythonw.exe: no console window), on
                   Linux a systemd user timer (else your crontab), run through bash -lc so that your profile's
                   variables reach it; one this machine installed and no longer declares is removed, a task you
                   registered by hand never is. Creating a scheduled task is your decision: the plan shows it, -Apply
                   does it. A brain command older than the subcommand only says so
      stamps       with a personal brain and -Apply: brain check --public --refresh, by the engine just installed: each
                   local checkout of config.json public.repos (the registry's repos whose remote is one) checked with
                   its history and stamped again, since the push guard refuses a stamp another engine made; a HEAD
                   already stamped is left, a checkout with uncommitted work skipped and named, a finding said (never
                   an install failure). A brain command older than the flag only says so
    With a personal brain whose config.json has adapters.claude and rules:
      marketplace  adapters.claude.marketplace, cloned by Claude Code from GitHub adapters.claude.source (branch -Ref
                   when given), with background auto-update on (extraKnownMarketplaces.<marketplace>.autoUpdate in
                   settings.json)
      plugin       <adapters.claude.plugin>@<marketplace> at user scope; its hooks inject config.json's rules into
                   every session and subagent
      permissions  the user scope of the permission hierarchy (brain permissions): the engine's narrow rules
                   (allow-rules.txt: brain up / down / health / resume, Bash and PowerShell forms), then the personal
                   brain's permissions.yaml global, profile and machine levels for this host, read from brain
                   permissions render --level user --json and added to permissions.allow / ask / deny in settings.json
                   when missing; it takes out only an expired rule permissions.yaml declares (until past, while an item
                   now closed), never another one. allow-rules.txt alone when the brain command cannot run (a first
                   plan, -SkipCommand without a venv, an installed command older than brain permissions); an error in
                   permissions.yaml or any other failure of the command stops -Apply (brain permissions check).
                   settings.json is Claude Code's file: one that is not a JSON object stops the installer (fix it by
                   hand first, never replaced), one Claude Code wrote meanwhile too (run it again); each write keeps
                   the file as it was in settings.json.bak and replaces it through a temporary file
      retire       ~/.claude/CLAUDE.md when it is the copy an earlier installer put there (moved to a dated .bak), so
                   that the rules load once
      memory       memory\<project>\*.md -> ~/.claude/projects/<project>/memory/ (only files missing locally: the
                   installer never overwrites a local note). The core plugin's SessionEnd hook then keeps the notes in
                   sync both ways by a reviewed PR (brain memory status / sync); -ExportMemory is the manual fallback:
                   it copies them back into the personal brain for a PR by hand
    ~/.claude is $env:CLAUDE_CONFIG_DIR when set. The Claude steps need the Claude Code CLI (on PATH, in the Claude
    desktop app's data folder, or given with -Claude) and git access to the personal brain's private repository
    without a prompt: gh auth login then gh auth setup-git, a credential Git Credential Manager already stores, or an
    SSH key loaded in ssh-agent.

.EXAMPLE
    .\install.ps1                                 # the plan: the command alone, or the personal brain's whole setup
    .\install.ps1 -Apply                          # the command (and, with a personal brain, the rest)
    .\install.ps1 -Apply -Personal D:\me\brain    # set up this personal brain on this machine
    .\install.ps1 -Apply -Ref my-branch           # the marketplace from a branch, to try a PR; -Apply alone goes back
    .\install.ps1 -ExportMemory                   # copy the local memory notes into memory\ (then review, commit, push)
    .\install.ps1 -Apply -Python C:\Python312\python.exe   # the brain command's venv from that interpreter
    .\install.ps1 -Apply -Engine D:\src\brain\packages\brain   # the command from a local checkout of the engine
    .\install.ps1 -Apply -Extras tui             # and the cockpit's Textual app (brain tui)
    .\install.ps1 -Tier recommended               # the plan of this machine's Recommended profile (brain doctor)
    .\install.ps1 -Apply -Tier recommended -Without gitnexus   # applied, with an override (Personnalisable)
#>
param(
    [switch]$Apply,
    [string]$Personal,
    [switch]$ExportMemory,
    [string]$Ref,
    [string]$Claude,
    [switch]$SkipCommand,
    [string]$Python,
    [string]$Engine,
    [ValidateSet('tui')]
    [string[]]$Extras,
    [ValidateSet('lite', 'default', 'recommended')]
    [string]$Tier,
    [string[]]$With,
    [string[]]$Without
)

$ErrorActionPreference = 'Stop'
$engine_root = Split-Path -Parent $PSScriptRoot   # packages\brain: this installer's own engine
$home_claude = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME '.claude' }
$brain_home = if ($env:BRAIN_HOME) { $env:BRAIN_HOME } else { Join-Path $HOME '.brain' }
$pointer = Join-Path $brain_home 'personal.json'
$default_engine = 'RoJLD/brain'   # where this package is published (brain.init.ENGINE_REPO)

function Get-MainCheckout([string]$dir) {
    # The main checkout of the git repo $dir is in, so that the pointer never names a worktree; $dir outside git.
    $ErrorActionPreference = 'Continue'
    $common = & git -C $dir rev-parse --path-format=absolute --git-common-dir 2>$null
    if ($LASTEXITCODE -eq 0 -and $common) { return (Split-Path -Parent ($common -replace '/', '\')) }
    return (Resolve-Path $dir).Path
}

# The personal brain: -Personal, $env:BRAIN_PERSONAL, the pointer, else the current folder when it has a config.json.
$from_pointer = $null
if (Test-Path $pointer) {
    try { $from_pointer = (Get-Content $pointer -Raw -Encoding UTF8 | ConvertFrom-Json).root } catch { $from_pointer = $null }
}
$repo = $null
foreach ($candidate in @($Personal, $env:BRAIN_PERSONAL, $from_pointer, (Get-Location).Path)) {
    if ($candidate -and (Test-Path (Join-Path $candidate 'config.json'))) { $repo = Get-MainCheckout $candidate; break }
    if ($candidate -and $candidate -eq $Personal) { throw "-Personal ${Personal}: no config.json there (brain init writes one)" }
}
$config = if ($repo) { Get-Content (Join-Path $repo 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }

if ($ExportMemory) {
    if (-not $repo) { throw '-ExportMemory needs a personal brain (-Personal <folder with config.json>)' }
    foreach ($dir in Get-ChildItem (Join-Path $home_claude 'projects') -Directory) {
        $src = Join-Path $dir.FullName 'memory'
        if (-not (Test-Path $src)) { continue }
        $dst = Join-Path $repo "memory\$($dir.Name)"
        New-Item -ItemType Directory -Force $dst | Out-Null
        Copy-Item (Join-Path $src '*.md') $dst -Force
        "exported $src -> $dst"
    }
    return
}

if ($repo) { "personal $repo (owner $($config.identity.owner))" } else { 'personal none: the brain command alone (brain init writes a personal brain; then run this again with -Personal <folder>)' }

# The engine to install: -Engine, else config.json's engine (repo and tag), else this installer's own version.
$version = ([regex]'__version__ = "([^"]+)"').Match((Get-Content (Join-Path $engine_root 'src\brain\__init__.py') -Raw)).Groups[1].Value
$engine_repo = if ($config -and $config.engine) { $config.engine.repo } else { $default_engine }
$engine_pin = if ($config -and $config.engine) { $config.engine.pin } else { "v$version" }
$verify_tags = [bool]($config -and $config.engine -and $config.engine.verify_tags -eq $true)
$wanted = @($Extras | Where-Object { $_ } | Sort-Object -Unique)
function Get-Spec([string[]]$extras) {
    $name = if ($extras) { "brain[$($extras -join ',')]" } else { 'brain' }
    if ($Engine) { if ($extras) { return "$Engine[$($extras -join ',')]" } else { return $Engine } }
    "$name @ git+https://github.com/$engine_repo.git@$engine_pin#subdirectory=packages/brain"
}

# --- the tag verification (tests/test_tagsig.py runs it alone) ---
function Test-TagSignature([string]$url, [string]$tag, [string]$allowed) {
    # The release tag fetched alone into a temporary repo and checked with git verify-tag against the allowed_signers
    # file (brain identity allowed-signers --write, from members.yaml's releaser role; namespace git): status verified
    # (with the releaser and the commit the tag names), unsigned, unknown-key or unverifiable. Public keys only.
    $ErrorActionPreference = 'Continue'
    $result = [pscustomobject]@{ status = 'unverifiable'; tag = $tag; signer = ''; commit = ''; why = '' }
    if (-not $allowed -or -not (Test-Path -LiteralPath $allowed)) {
        $result.status = 'no-signers'
        $result.why = 'no allowed_signers beside config.json (brain identity allowed-signers --write)'
        return $result
    }
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("brain-tag-" + [guid]::NewGuid().ToString('N').Substring(0, 12))
    $prompt = $env:GIT_TERMINAL_PROMPT
    $env:GIT_TERMINAL_PROMPT = '0'   # a private or wrong engine.repo fails instead of asking for a password
    try {
        & git init --quiet $tmp 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { $result.why = 'git init failed'; return $result }
        $ref = "refs/tags/$tag"
        $said = @(& git -c credential.helper= -C $tmp fetch --quiet --no-tags --depth 1 --filter=tree:0 $url "+${ref}:${ref}" 2>&1 | ForEach-Object { "$_" })
        if ($LASTEXITCODE -ne 0) { $result.why = "git fetch $tag failed (offline?): $($said | Select-Object -Last 1)"; return $result }
        $kind = "$(& git -C $tmp cat-file -t $ref 2>$null)".Trim()
        $result.commit = "$(& git -C $tmp rev-parse --verify "$ref^{commit}" 2>$null)".Trim()
        if (-not $kind -or -not $result.commit) { $result.why = "git could not read the fetched $tag"; return $result }
        if ($kind -ne 'tag') { $result.status = 'unsigned'; $result.why = "$tag is a lightweight tag: no signature"; return $result }
        $file = (Resolve-Path -LiteralPath $allowed).Path -replace '\\', '/'
        $said = @(& git -C $tmp -c "gpg.ssh.allowedSignersFile=$file" -c gpg.ssh.program=ssh-keygen verify-tag --raw $ref 2>&1 | ForEach-Object { "$_" }) -join "`n"
        $code = $LASTEXITCODE
        if ($code -eq 0 -and $said -match 'Good "git" signature for (\S+) with') {
            $result.status = 'verified'
            $result.signer = $Matches[1]
        } elseif ($said -match 'no signature found') {
            $result.status = 'unsigned'
            $result.why = "$tag carries no signature"
        } elseif ($said -match 'cannot run|No such file|not recognized') {
            $result.why = "git verify-tag could not run ssh-keygen: $(($said -split "`n") | Select-Object -Last 1)"
        } else {
            $result.status = 'unknown-key'
            $result.why = "$tag is not signed by a key of allowed_signers"
        }
        return $result
    } finally {
        $env:GIT_TERMINAL_PROMPT = $prompt
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}
# --- end of the tag verification ---

# The Claude steps: only for a personal brain whose config.json names its marketplace and rules.
$names = if ($config -and $config.adapters) { $config.adapters.claude } else { $null }
$claude_steps = $names -and $names.source -and $names.marketplace -and $names.plugin -and $config.rules
if ($repo -and -not $claude_steps) {
    'note     config.json has no adapters.claude (marketplace, plugin, source) and rules: no Claude marketplace yet (brain render --target claude writes it; push the repo, then set adapters.claude)'
}
if ($claude_steps) {
    $github = $names.source
    $marketplace = $names.marketplace
    $plugin = "$($names.plugin)@$marketplace"
    $rules_cap = 10000   # characters Claude Code keeps from a hook's additionalContext

    $rules = Join-Path $repo (@($config.rules)[0] -replace '/', '\')
    $size = (Get-Content $rules -Raw -Encoding UTF8).Length
    if ($size -gt $rules_cap) { throw "$rules is $size characters, over the $rules_cap a hook can inject" }
    "rules    $rules ($size characters, cap $rules_cap)"

    if (-not $Claude) {
        $Claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
    }
    if (-not $Claude -and $env:LOCALAPPDATA) {
        # The Claude desktop app keeps its own copy of the CLI under claude-code\<version>\<build>\: take the newest.
        $Claude = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Claude-Data\*\claude-code\*\*\claude.exe') -ErrorAction SilentlyContinue |
            Sort-Object { [version]$_.Directory.Parent.Name } -Descending | Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $Claude) { throw 'Claude Code CLI not found: install it, or pass -Claude <path to claude>' }
    "cli      $Claude"
}

# The CLI writes progress to stderr: Windows PowerShell must not turn it into terminating errors, the exit code decides.
function Invoke-Claude {
    $ErrorActionPreference = 'Continue'
    & $Claude @args
    if ($LASTEXITCODE -ne 0) { throw "claude $($args -join ' ') failed with exit code $LASTEXITCODE" }
}

function Get-ClaudeJson {
    $ErrorActionPreference = 'Continue'
    $out = & $Claude @args
    if ($LASTEXITCODE -ne 0) { throw "claude $($args -join ' ') failed with exit code $LASTEXITCODE" }
    $data = ($out | Out-String) | ConvertFrom-Json
    $data   # returned element by element (Windows PowerShell keeps a parsed array whole in a pipeline)
}

# --- the foreign file helpers (tests/test_permissions.py runs them with the permissions step) ---
# settings.json is Claude Code's (brain.stateio's foreign class): read whole or refused (fix it by hand first: never
# replaced when unreadable; an empty one is read as missing); written only when unchanged since it was read, backed up beside itself
# (settings.json.bak), through a temporary file that replaces it.
$foreign_seen = @{}
function Read-ForeignJson([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { $script:foreign_seen[$path] = $null; return $null }
    $raw = [IO.File]::ReadAllText($path)   # UTF-8, a BOM allowed
    $script:foreign_seen[$path] = $raw
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }   # empty (an interrupted write): read as missing
    try { $data = $raw | ConvertFrom-Json } catch { throw "${path}: not readable JSON: fix it by hand first; nothing written" }
    if ($data -isnot [System.Management.Automation.PSCustomObject]) { throw "${path}: not a JSON object: fix it by hand first; nothing written" }
    $data
}
function Write-ForeignJson([string]$path, $data) {
    $now = if (Test-Path -LiteralPath $path) { [IO.File]::ReadAllText($path) } else { $null }
    if ($script:foreign_seen.ContainsKey($path) -and $now -cne $script:foreign_seen[$path]) {
        throw "${path}: changed while the installer edited it (Claude Code wrote it): run it again; nothing written"
    }
    $tmp = "$path.$PID.tmp"
    # UTF-8 without BOM, as Claude Code writes it.
    [IO.File]::WriteAllText($tmp, ($data | ConvertTo-Json -Depth 32), (New-Object Text.UTF8Encoding $false))
    if ($null -ne $now) { [IO.File]::Replace($tmp, $path, "$path.bak") } else { [IO.File]::Move($tmp, $path) }
    $script:foreign_seen[$path] = [IO.File]::ReadAllText($path)
}
# --- end of the foreign file helpers ---

# Background auto-update is off for a third-party marketplace until a settings entry turns it on.
$settings_path = Join-Path $home_claude 'settings.json'
function Set-AutoUpdate {
    $settings = Read-ForeignJson $settings_path
    $entry = if ($settings -and $settings.extraKnownMarketplaces) { $settings.extraKnownMarketplaces.$marketplace }
    if (-not $entry) { throw "$settings_path declares no extraKnownMarketplaces.$marketplace after the add" }
    $entry | Add-Member -NotePropertyName autoUpdate -NotePropertyValue $true -Force
    Write-ForeignJson $settings_path $settings
}

if ($claude_steps) {
    # Marketplace, pinned to -Ref or following the default branch.
    $source = if ($Ref) { "$github#$Ref" } else { $github }
    $known = Get-ClaudeJson plugin marketplace list --json | Where-Object { $_.name -eq $marketplace }
    $fresh = $true   # the settings entry is (re)written by the add, without autoUpdate
    if (-not $known) {
        "add      marketplace $marketplace from $source"
        if ($Apply) { Invoke-Claude plugin marketplace add $source }
    } elseif ("$($known.ref)" -ne "$Ref" -or $known.repo -ne $github) {
        $previous = if ($known.ref) { "$($known.repo)#$($known.ref)" } else { $known.repo }
        "replace  marketplace $marketplace ($previous -> $source)"
        if ($Apply) {
            # Removing the marketplace uninstalls its plugins: when the new source fails, put the previous one back.
            Invoke-Claude plugin marketplace remove $marketplace
            try { Invoke-Claude plugin marketplace add $source }
            catch {
                Invoke-Claude plugin marketplace add $previous
                Set-AutoUpdate
                Invoke-Claude plugin install $plugin --scope user
                throw "could not add $source (is the marketplace on that branch?); $previous is back: $_"
            }
        }
    } else {
        $fresh = $false
        "refresh  marketplace $marketplace ($source)"
        if ($Apply) { Invoke-Claude plugin marketplace update $marketplace }
    }

    $settings = Read-ForeignJson $settings_path
    $entry = if ($settings -and $settings.extraKnownMarketplaces) { $settings.extraKnownMarketplaces.$marketplace } else { $null }
    if (-not $fresh -and $entry -and $entry.autoUpdate -eq $true) {
        "same     auto-update of $marketplace in $settings_path"
    } else {
        "set      auto-update of $marketplace in $settings_path"
        if ($Apply) { Set-AutoUpdate }
    }

    # Plugin at user scope: every project on this machine.
    $installed = if ($known -or $Apply) {
        Get-ClaudeJson plugin list --json | Where-Object { $_.id -eq $plugin -and $_.scope -eq 'user' }
    }
    if (-not $installed) {
        "install  plugin $plugin (user scope)"
        if ($Apply) { Invoke-Claude plugin install $plugin --scope user }
    } else {
        "update   plugin $plugin (installed $($installed.version))"
        if ($Apply) {
            Invoke-Claude plugin update $plugin --scope user
            if (-not $installed.enabled) { Invoke-Claude plugin enable $plugin --scope user }
        }
    }

    # The rules now come from the plugin: retire the copy an earlier installer put in ~/.claude/CLAUDE.md.
    $target = Join-Path $home_claude 'CLAUDE.md'
    if (-not (Test-Path $target)) {
        "absent   $target (the rules come from $plugin)"
    } elseif ((Get-Content $target -TotalCount 5 -Encoding UTF8 | Out-String) -match [regex]::Escape($github)) {
        $backup = "$target.$(Get-Date -Format 'yyyyMMddHHmmss').bak"
        "retire   $target (backup $backup)"
        if ($Apply) { Move-Item $target $backup }
    } else {
        "keep     $target (not from ${github}: check that it does not repeat the rules)"
    }
}

if ($repo) {
    foreach ($dir in Get-ChildItem (Join-Path $repo 'memory') -Directory -ErrorAction SilentlyContinue) {
        $dst = Join-Path $home_claude "projects\$($dir.Name)\memory"
        foreach ($note in Get-ChildItem $dir.FullName -Filter '*.md') {
            $to = Join-Path $dst $note.Name
            if (Test-Path $to) { continue }
            "memory   $to"
            if ($Apply) { New-Item -ItemType Directory -Force $dst | Out-Null; Copy-Item $note.FullName $to }
        }
    }

    # The machine's pointer to its personal brain (brain.paths.personal_root): forward slashes, read by bash too.
    $root_json = ($repo -replace '\\', '/')
    $current = $null
    if (Test-Path $pointer) { try { $current = (Get-Content $pointer -Raw -Encoding UTF8 | ConvertFrom-Json).root } catch { $current = $null } }
    if ($current -eq $root_json) {
        "same     $pointer -> $root_json"
    } else {
        "point    $pointer -> $root_json" + $(if ($current) { " (was $current)" } else { '' })
        if ($Apply) {
            New-Item -ItemType Directory -Force $brain_home | Out-Null
            [IO.File]::WriteAllText($pointer, "{`"root`": `"$root_json`"}`n", (New-Object Text.UTF8Encoding $false))
        }
    }
}

# The brain command: its own venv (never a project's), and only its launcher on the PATH.
$venv = Join-Path $brain_home 'venv'
$windows = $env:OS -eq 'Windows_NT'
if ($windows) {
    $venv_python = Join-Path $venv 'Scripts\python.exe'
    $launcher = Join-Path $venv 'Scripts\brain.exe'
    $bin = Join-Path $brain_home 'bin'
} else {
    $venv_python = Join-Path $venv 'bin/python'
    $launcher = Join-Path $venv 'bin/brain'
    $bin = Join-Path $HOME '.local/bin'
}

function Install-Brain([string]$spec) {
    # pip writes notices to stderr: Windows PowerShell must not turn them into terminating errors. A new tag is a new
    # version, so pip replaces the installed one (an editable install from a checkout included).
    $ErrorActionPreference = 'Continue'
    & $venv_python -m pip install --quiet --disable-pip-version-check $spec
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($code -ne 0) { throw "pip install $spec failed with exit code $code" }
}

function Set-Launcher([string]$from, [string]$to) {
    # Sessions' hooks run brain.exe many times a minute, and Windows refuses to overwrite a running image: an identical
    # launcher is left alone, a new one is copied beside it and swapped in with a short retry, and one still locked is
    # renamed aside (a running image can be renamed) and removed on the next run. Returns same, copied or swapped.
    $leaf = Split-Path $to -Leaf
    Get-ChildItem (Split-Path $to) -Filter "$leaf.old-*" -ErrorAction SilentlyContinue |
        ForEach-Object { Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue }
    # SHA-256 through .NET: Get-FileHash is a script function a spawned Windows PowerShell does not always load
    $sha = [Security.Cryptography.SHA256]::Create()
    $hash = { param($p) [BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes($p))) }
    if ((Test-Path $to) -and (& $hash $to) -eq (& $hash $from)) { return 'same' }
    $new = "$to.new"
    Copy-Item $from $new -Force
    foreach ($wait in 200, 400, 800, 1600) {
        try { Move-Item $new $to -Force -ErrorAction Stop; return 'copied' } catch { Start-Sleep -Milliseconds $wait }
    }
    Rename-Item $to "$leaf.old-$(Get-Date -Format yyyyMMddHHmmss)" -ErrorAction Stop
    Move-Item $new $to -ErrorAction Stop
    'swapped'
}

function Invoke-Brain {
    # The installed brain command: its output as lines (an error's message as is), its exit code in $script:brain_code.
    $ErrorActionPreference = 'Continue'
    $console = [Console]::OutputEncoding
    [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false   # the brain command writes UTF-8 to a pipe
    $root_args = if ($repo) { @('--root', $repo) } else { @() }
    $out = & $venv_python -I -m brain @root_args @args 2>&1 |
        ForEach-Object { if ($_ -is [Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" } }
    $script:brain_code = $LASTEXITCODE
    [Console]::OutputEncoding = $console
    $out
}

# The machine's profile (brain profile): -Tier, -With and -Without go to brain profile set (the plan; with -Apply it
# writes <BRAIN_HOME>\profile.json), then brain profile render says what the profile wants, with this run's changes.
$tier_args = @(@(if ($Tier) { $Tier }) + @($With | Where-Object { $_ } | ForEach-Object { '--with', $_ }) +
    @($Without | Where-Object { $_ } | ForEach-Object { '--without', $_ }))
function Read-Tier {
    $lines = @()
    if ($tier_args) {
        $set = @('profile', 'set') + $tier_args
        if ($Apply) { $set += '--apply' }
        $lines += @(Invoke-Brain @set)
        if ($script:brain_code -ne 0) {
            if ($Apply) { throw "brain profile set failed (exit $script:brain_code): $($lines -join ' ')" }
            return @{ lines = $lines; render = $null }
        }
    }
    $out = Invoke-Brain profile render @tier_args
    $render = $null
    if ($script:brain_code -eq 0) { try { $render = ($out | Out-String) | ConvertFrom-Json } catch { $render = $null } }
    if (-not $render) { $lines += "note     brain profile render failed (exit $script:brain_code): the extras of -Extras only" }
    @{ lines = $lines; render = $render }
}
function Show-Tier($t) {
    $t.lines
    $r = $t.render
    if (-not $r) { return }
    $extras = if ($r.extras) { $r.extras -join ', ' } else { 'none' }
    $on = if ($r.stacks.on) { $r.stacks.on -join ', ' } else { 'none' }
    "profile  $($r.machine): $($r.label); extras $extras; stacks on: $on (they start on demand: brain up)"
    $r.extras_outside | Where-Object { $_ } | ForEach-Object { "keep     the $_ extra is installed but outside the profile: left installed" }
    $r.warnings | Where-Object { $_ } | ForEach-Object { "warning  profile: $_" }
}

function Get-InstalledCommit([string]$dist) {
    # The commit pip recorded for a distribution installed from git (its dist-info's direct_url.json) from the
    # engine's repo, '' when none.
    $sites = if ($windows) { @(Join-Path $venv 'Lib\site-packages') } else {
        @(Get-ChildItem (Join-Path $venv 'lib') -Directory -Filter 'python3*' -ErrorAction SilentlyContinue |
            ForEach-Object { Join-Path $_.FullName 'site-packages' }) }
    foreach ($site in $sites) {
        foreach ($d in Get-ChildItem $site -Directory -Filter "$dist-*.dist-info" -ErrorAction SilentlyContinue) {
            $f = Join-Path $d.FullName 'direct_url.json'
            if (-not (Test-Path $f)) { continue }
            try { $d_url = Get-Content $f -Raw -Encoding UTF8 | ConvertFrom-Json } catch { continue }
            if ("$($d_url.url)" -notlike "*/$engine_repo*") { continue }
            $c = $d_url.vcs_info.commit_id
            if ($c) { return "$c" }
        }
    }
    ''
}

if (-not $SkipCommand) {
    # The release tag's signature (wi-brain-release-signing), before anything is installed: verified against the
    # personal brain's allowed_signers, the install then goes by the commit the signed tag names; said either way,
    # refused only under config.json engine.verify_tags (the owner's opt-in). -Engine installs what it names, unchecked.
    $sig = $null
    if (-not $Engine) {
        $allowed = if ($repo) { Join-Path $repo 'allowed_signers' } else { $null }
        $sig = Test-TagSignature "https://github.com/$engine_repo.git" $engine_pin $allowed
        if ($sig.status -eq 'verified') {
            "verify   ${engine_pin}: signed by $($sig.signer) ($allowed), commit $($sig.commit.Substring(0, 12))"
        } elseif ($verify_tags) {
            "refuse   ${engine_pin}: not verified, $($sig.why) (config.json engine.verify_tags is on)"
            if ($Apply) { throw "$engine_pin is not verified ($($sig.why)): nothing installed (config.json engine.verify_tags is on)" }
        } else {
            "verify   ${engine_pin}: not verified, $($sig.why) (not refused: config.json engine.verify_tags is off)"
        }
    }
    if (Test-Path $venv_python) {
        "same     venv $venv"
    } else {
        if (-not $Python) {
            $Python = @('python', 'python3' | ForEach-Object { (Get-Command $_ -ErrorAction SilentlyContinue).Source } |
                Where-Object { $_ -and $_ -notlike '*\WindowsApps\*' })[0]
        }
        if (-not $Python) { throw 'Python 3.10 or later not found for the brain command: install it, or pass -Python <path>' }
        "create   venv $venv (from $Python)"
        if ($Apply) {
            & $Python -m venv $venv
            if ($LASTEXITCODE -ne 0) { throw "$Python -m venv $venv failed with exit code $LASTEXITCODE" }
        }
    }
    # an extra (the package's optional dependencies) is added; a later run without it leaves it installed
    $spec = Get-Spec $wanted
    "install  brain $engine_pin and its dependencies, research-graph at the same tag among them (pip install `"$spec`") into $venv"
    if ($Apply) { Install-Brain $spec }
    if ($Apply -and $sig -and $sig.status -eq 'verified') {
        # pip installed by the tag: a commit other than the verified one means the tag moved between the check and
        # the install
        foreach ($dist in 'brain', 'research_graph') {
            $got = Get-InstalledCommit $dist
            if ($got -and $got -ne $sig.commit) {
                "warning  $dist was installed from commit $got, not $($sig.commit) which the signed $engine_pin names: the tag moved during the install"
                if ($verify_tags) { throw "the tag $engine_pin moved during the install: the venv holds code the signature does not cover; check the repo's tags, then reinstall with pip install --force-reinstall" }
            }
        }
    }
    # The machine's profile, read from the installed brain command: the extras it wants too.
    if (Test-Path $launcher) {
        $chosen = Read-Tier
        Show-Tier $chosen
        $more = @(if ($chosen.render) { $chosen.render.extras | Where-Object { $_ -and $wanted -notcontains $_ } })
        if ($more) {
            $spec = Get-Spec (@($wanted) + $more | Sort-Object -Unique)
            "install  the profile's extras (pip install `"$spec`")"
            if ($Apply) { Install-Brain $spec }
        }
    } else {
        "profile  read once the brain command is installed (-Apply); the built-in base is default: Lite and the cockpit's tui"
    }
    # pip's Windows launcher holds the venv interpreter's absolute path: a copy runs from anywhere.
    "link     $launcher -> $bin"
    if ($Apply) {
        New-Item -ItemType Directory -Force $bin | Out-Null
        if ($windows) {
            $done = Set-Launcher $launcher (Join-Path $bin 'brain.exe')
            "$($done.PadRight(8)) $(Join-Path $bin 'brain.exe')"
        } else {
            $link = Join-Path $bin 'brain'
            if (Test-Path $link) { Remove-Item $link -Force }
            New-Item -ItemType SymbolicLink -Path $link -Target $launcher | Out-Null
        }
    }
    if ($windows) {
        $user_path = [Environment]::GetEnvironmentVariable('Path', 'User')
        $parts = @("$user_path" -split ';' | Where-Object { $_ })
        if ($parts -contains $bin) {
            "same     $bin on the user PATH"
        } else {
            "path     add $bin to the user PATH (new terminals and sessions see it)"
            if ($Apply) { [Environment]::SetEnvironmentVariable('Path', (($parts + $bin) -join ';'), 'User') }
        }
    } elseif (($env:PATH -split ':') -notcontains $bin) {
        "path     $bin is not on PATH: add it in the shell profile"
    }
}

# --- the permissions step (tests/test_permissions.py runs it alone) ---
function Update-Permissions {
    # Permission rules, versioned in the engine's allow-rules.txt and the personal brain's permissions.yaml, reviewed
    # by PR: the user scope of the hierarchy for this host, as the installed brain command renders it; allow-rules.txt
    # alone when the command cannot run. Added when missing, never removed.
    $wanted_rules = $null
    $from = 'allow-rules.txt'
    if (Test-Path $venv_python) {
        $ErrorActionPreference = 'Continue'
        $console = [Console]::OutputEncoding
        [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false   # the brain command writes UTF-8 to a pipe
        $out = & $venv_python -I -m brain --root $repo permissions render --level user --json 2>$null
        $code = $LASTEXITCODE
        [Console]::OutputEncoding = $console
        $ErrorActionPreference = 'Stop'
        $render = $null
        try { $render = ($out | Out-String) | ConvertFrom-Json } catch { $render = $null }
        if ($render -and $code -eq 0) {
            $wanted_rules = $render
            $from = 'brain permissions (allow-rules.txt, permissions.yaml)'
        } elseif ($render -and $render.errors) {
            $render.errors | ForEach-Object { "error    permissions: $_" }
            if ($Apply) { throw "the permission hierarchy has errors: brain permissions check, then run again" }
        } elseif ($code -eq 2) {
            # argparse's exit: a brain command older than brain permissions (a plan before it is installed)
            "note     the installed brain command has no permissions subcommand: the rules of allow-rules.txt only"
        } else {
            "error    brain permissions render --level user --json failed (exit $code): brain permissions check"
            if ($Apply) { throw "brain permissions failed (exit $code): nothing is added until it runs" }
        }
    }
    if (-not $wanted_rules) {
        $rules_txt = @(Get-Content $allow_file -Encoding UTF8 | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') })
        $wanted_rules = [pscustomobject]@{ allow = $rules_txt; ask = @(); deny = @() }
    }
    $settings = Read-ForeignJson $settings_path
    $total = 0
    $added = 0
    foreach ($verdict in 'allow', 'ask', 'deny') {
        $want = @($wanted_rules.$verdict | Where-Object { $_ })
        $total += $want.Count
        $have = @(if ($settings -and $settings.permissions -and $settings.permissions.$verdict) { $settings.permissions.$verdict })
        $missing = @($want | Where-Object { $have -cnotcontains $_ })   # a Bash rule is case-sensitive
        # an expired rule permissions.yaml declares (until past, while an item now closed) is taken out; nothing else is
        $gone = @(if ($wanted_rules.expired) { @($wanted_rules.expired.$verdict) | Where-Object { $_ -and $have -ccontains $_ } })
        if (-not $missing -and -not $gone) { continue }
        $added += $missing.Count + $gone.Count
        $missing | ForEach-Object { "{0,-8} {1} in {2}" -f $verdict, $_, $settings_path }
        $gone | ForEach-Object { "expired  {0} {1}: taken out of {2}" -f $verdict, $_, $settings_path }
        if ($Apply) {
            if (-not $settings) { $settings = [pscustomobject]@{} }
            if (-not $settings.permissions) {
                $settings | Add-Member -NotePropertyName permissions -NotePropertyValue ([pscustomobject]@{}) -Force
            }
            $kept = @($have | Where-Object { $gone -cnotcontains $_ })
            $settings.permissions | Add-Member -NotePropertyName $verdict -NotePropertyValue ([object[]]($kept + $missing)) -Force
        }
    }
    if (-not $added) {
        "same     $total rule(s) of $from in $settings_path"
    } elseif ($Apply) {
        Write-ForeignJson $settings_path $settings
    }
}
# --- end of the permissions step ---

# --- the merge driver step (tests/test_mergedriver.py runs it alone) ---
function Set-MergeDriver {
    # brain merge-driver install in the personal brain's repo (its worktrees share its git config): the launcher on
    # PATH is the command git runs; a command older than brain merge-driver (argparse's exit 2) only says so.
    $git_launcher = if ($windows) { Join-Path $bin 'brain.exe' } else { Join-Path $bin 'brain' }
    if (-not (Test-Path $venv_python)) {
        "merge    merge.brain.driver in $repo's git config ($git_launcher merge-driver run ...), once the command is installed (-Apply)"
        return
    }
    $merge_args = @('-I', '-m', 'brain', 'merge-driver', 'install', '--repo', $repo, '--launcher', $git_launcher)
    if ($Apply) { $merge_args += '--apply' }
    $ErrorActionPreference = 'Continue'
    $out = & $venv_python @merge_args 2>&1 |
        ForEach-Object { if ($_ -is [Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" } }
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($code -eq 2) { 'merge    the installed brain command has no merge-driver subcommand yet (an older engine)'; return }
    $out
    if ($code -ne 0 -and $Apply) { throw "brain merge-driver install failed (exit $code)" }
}
# --- end of the merge driver step ---

# --- the schedule step (tests/test_schedule.py runs it alone) ---
function Set-Schedules {
    # brain schedule install for the personal brain's registry: its schedules: for this machine, as a plan, created,
    # updated or removed with -Apply; a command older than brain schedule (argparse's exit 2) only says so.
    if (-not (Test-Path $venv_python)) {
        "schedule the registry's schedules: for this machine (brain schedule install), once the command is installed (-Apply)"
        return
    }
    $schedule_args = @('-I', '-m', 'brain', '--root', $repo, 'schedule', 'install')
    if ($Apply) { $schedule_args += '--apply' }
    $ErrorActionPreference = 'Continue'
    $out = @(& $venv_python @schedule_args 2>&1 |
        ForEach-Object { if ($_ -is [Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" } })
    $code = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($code -eq 2 -and -not (($out -join ' ') -match 'brain schedule:')) {
        'schedule the installed brain command has no schedule subcommand yet (an older engine)'
        return
    }
    $out
    if ($code -ne 0 -and $Apply) { throw "brain schedule install failed (exit $code)" }
}
# --- end of the schedule step ---

# --- the stamps step (tests/test_public.py runs it alone) ---
function Update-Stamps {
    # brain check --public --refresh by the engine just installed (wi-brain-public-stamp-refresh): each local checkout
    # of config.json public.repos (the registry's repos) checked with its history and stamped again, since the push
    # guard refuses a stamp of another engine; one with uncommitted work is skipped and named. Said, never a failure of
    # the install; a command older than the flag (argparse's exit 2) only says so.
    if (-not (Test-Path $venv_python)) {
        "stamps   the public repos' local checkouts re-checked and stamped (brain check --public --refresh), once the command is installed (-Apply)"
        return
    }
    if (-not $Apply) {
        'stamps   brain check --public --refresh with -Apply: each local checkout of config.json public.repos re-checked with its history by the installed engine and stamped for the push guard (one with uncommitted work skipped and named)'
        return
    }
    $out = @(Invoke-Brain check --public --refresh)
    if ($script:brain_code -eq 2 -and -not ($out | Where-Object { $_ -match '^(stamps|same|stamped|skip|refused|failed) ' })) {
        'stamps   the installed brain command has no check --public --refresh yet (an older engine): brain check --public --history in each public checkout'
        return
    }
    $out
}
# --- end of the stamps step ---

$allow_file = Join-Path $engine_root 'src\brain\adapters\claude\allow-rules.txt'
if ($repo) { Set-MergeDriver }
if ($repo) { Set-Schedules }
if ($repo -and -not $SkipCommand) { Update-Stamps }
if ($claude_steps) { Update-Permissions }
if (-not $repo -and -not $Apply) { 'next     brain init <folder> --owner <you> --apply (after -Apply installs the command), then .\install.ps1 -Personal <folder>' }
if (-not $Apply) { '(plan only: run with -Apply to install)' }
