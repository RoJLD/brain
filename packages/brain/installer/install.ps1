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
      pointer      <BRAIN_HOME>\personal.json, {"root": <the personal brain's main checkout>}: how the engine and its
                   hooks find the personal brain from anywhere ($env:BRAIN_PERSONAL overrides it)
      profile      this machine's profile (brain profile, alias brain doctor: Lite, Défaut, Recommandé,
                   Personnalisable), read once the brain command is installed: the pip extras it wants join -Extras
                   (Défaut, the built-in base, brings the cockpit's tui). -Tier lite|default|recommended, -With ID and
                   -Without ID change it: brain profile set prints the plan, and with -Apply writes
                   <BRAIN_HOME>\profile.json (recommended: the set this machine allows, frozen there). An extra the
                   profile no longer wants is left installed; the stacks it turns on start on demand (brain up).
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
                   permissions.yaml or any other failure of the command stops -Apply (brain permissions check)
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
$wanted = @($Extras | Where-Object { $_ } | Sort-Object -Unique)
function Get-Spec([string[]]$extras) {
    $name = if ($extras) { "brain[$($extras -join ',')]" } else { 'brain' }
    if ($Engine) { if ($extras) { return "$Engine[$($extras -join ',')]" } else { return $Engine } }
    "$name @ git+https://github.com/$engine_repo.git@$engine_pin#subdirectory=packages/brain"
}

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

# Background auto-update is off for a third-party marketplace until a settings entry turns it on.
$settings_path = Join-Path $home_claude 'settings.json'
function Set-AutoUpdate {
    $settings = Get-Content $settings_path -Raw -Encoding UTF8 | ConvertFrom-Json
    $entry = $settings.extraKnownMarketplaces.$marketplace
    if (-not $entry) { throw "$settings_path declares no extraKnownMarketplaces.$marketplace after the add" }
    $entry | Add-Member -NotePropertyName autoUpdate -NotePropertyValue $true -Force
    # UTF-8 without BOM, as Claude Code writes it.
    [IO.File]::WriteAllText($settings_path, ($settings | ConvertTo-Json -Depth 32), (New-Object Text.UTF8Encoding $false))
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

    $settings = if (Test-Path $settings_path) { Get-Content $settings_path -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
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
    if ((Test-Path $to) -and (Get-FileHash $to).Hash -eq (Get-FileHash $from).Hash) { return 'same' }
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

if (-not $SkipCommand) {
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
    $settings = if (Test-Path $settings_path) { Get-Content $settings_path -Raw -Encoding UTF8 | ConvertFrom-Json } else { $null }
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
        [IO.File]::WriteAllText($settings_path, ($settings | ConvertTo-Json -Depth 32), (New-Object Text.UTF8Encoding $false))
    }
}
# --- end of the permissions step ---

$allow_file = Join-Path $engine_root 'src\brain\adapters\claude\allow-rules.txt'
if ($claude_steps) { Update-Permissions }
if (-not $repo -and -not $Apply) { 'next     brain init <folder> --owner <you> --apply (after -Apply installs the command), then .\install.ps1 -Personal <folder>' }
if (-not $Apply) { '(plan only: run with -Apply to install)' }
