"""The owner and power guards (brain.guards: check_owner, check_power) on real command shapes, Bash and PowerShell,
and the path of a refusal into the owner's queue (brain queue add --guard, brain.queue). The tests run as owner Ada,
on an invented platform: its node lifecycle CLIs kubectl-acme, acme-cli and acme, its hosts box1 to box4."""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from research_graph import init
from test_guards import _needs_python, bash, decide, payload, pwsh

from brain import guards, permissions, projects, queue, records

PERMISSIONS = Path(__file__).resolve().parent / "fixtures" / "permissions.yaml"  # an owner's hierarchy
AT = "2026-11-02T20:00:00Z"
# Ada's config.json: the platform's node tools the power guard knows by name (config.json's power).
POWER = {"node_clis": ["kubectl-acme", "acme-cli", "acme"], "node_services": ["acme-node-agent"]}


@pytest.fixture
def owner(tmp_path, monkeypatch):
    """An owner's permissions.yaml (the never-grantable categories it declares, installer included), Ada's config.json
    with her platform's node tools, a working folder."""
    monkeypatch.setenv("BRAIN_PERMISSIONS", str(PERMISSIONS))
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "no-projects.yaml"))
    monkeypatch.delenv(guards.ALLOW_ENV, raising=False)
    cfg = tmp_path / "ada-config.json"
    cfg.write_text(json.dumps({"v": 1, "identity": {"owner": "Ada", "kind": "person"}, "power": POWER}),
                   encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(cfg))
    work = tmp_path / "work"
    work.mkdir()
    return work


def refused(reason, guard, check):
    return reason is not None and f"{guards.ALLOW_ENV}={guard} (or {guard}:{check})" in reason


# --- actions only the owner takes -----------------------------------------------------------------------------------

OWNER_REFUSED = [
    ("visibility", "gh repo edit acme/demo-brain --visibility public --accept-visibility-change-consequences"),
    ("visibility", "gh repo edit --visibility=private acme/x"),
    ("visibility", "gh repo create acme/new-engine --public --source . --push"),
    ("visibility", "gh gist create -p notes.md"),
    ("visibility", "gh api -X PATCH repos/acme/x -f private=false"),
    ("visibility", "gh api --method PATCH repos/acme/x -F visibility=public"),
    ("visibility", "gh api graphql -f query='mutation { updateRepository(input: {repositoryId: \"R\", "
                   "visibility: PUBLIC}) { repository { id } } }'"),
    ("visibility", "curl -X PATCH -H \"Authorization: token $T\" https://api.github.com/repos/acme/x "
                   "-d '{\"private\": false}'"),
    ("keys", "gh secret set BRAIN_NTFY_TOPIC --body x"),
    ("keys", "printf %s \"$K\" | gh secret set KEY -R acme/x"),
    ("keys", "gh secret delete OLD"),
    ("keys", "gh auth token"),
    ("keys", "gh ssh-key add ~/.ssh/id_ed25519.pub"),
    ("keys", "gh api -X PUT repos/acme/x/actions/secrets/KEY -f encrypted_value=x -f key_id=1"),
    ("keys", "ssh-keygen -t ed25519 -f ~/.ssh/box1_shutdown -N ''"),
    ("keys", "age-keygen -o ~/.brain/device.key"),
    ("keys", "gpg --quick-generate-key ada@example.invalid"),
    ("keys", "kubectl create secret generic brain-token --from-literal=t=x -n brain"),
    ("keys", "docker secret create brain_key key.txt"),
    ("accounts", "gh auth login --with-token < t.txt"),
    ("accounts", "gh auth refresh -s delete_repo"),
    ("accounts", "docker login ghcr.io -u ada --password-stdin"),
    ("accounts", "npm login"),
    ("accounts", "az login"),
    ("accounts", "gcloud auth login"),
    ("accounts", "argocd login argocd.example.invalid"),
    ("accounts", "sudo useradd -m brain"),
    ("accounts", "net user brain s3cret /add"),
    ("scheduled", "schtasks /Create /SC DAILY /TN BrainDigest /TR \"brain digest --write\""),
    ("scheduled", "schtasks.exe /change /tn \\Demo\\cycle /tr x"),
    ("scheduled", "schtasks /delete /tn BrainDigest /f"),
    ("scheduled", "crontab -e"),
    ("scheduled", "(crontab -l; echo '0 3 * * * brain digest') | crontab -"),
    ("scheduled", "sudo systemctl enable --now brain-digest.timer"),
    ("scheduled", "systemctl --user enable brain.service"),
    ("scheduled", "systemd-run --on-calendar=daily brain digest"),
    ("scheduled", "sc.exe create BrainSvc binPath= C:\\brain\\svc.exe start= auto"),
    ("scheduled", "sc config BrainSvc start= auto"),
    ("scheduled", "nssm install BrainMCP C:\\brain\\venv\\Scripts\\brain.exe"),
    ("scheduled", "echo 'brain digest' | at 03:00"),
    ("scheduled", "reg add 'HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' /v Brain /d brain.exe"),
    ("scheduled", "launchctl load ~/Library/LaunchAgents/brain.plist"),
    ("scheduled", "cp brain.service ~/.config/systemd/user/brain.service"),
    ("scheduled", "echo '0 3 * * * root brain' > /etc/cron.d/brain"),
    ("arming", "python -m demo_fund.cli.cross_venue_testnet --arm --mode probe"),
    ("arming", "cd ../demo-fund && uv run python -m demo_fund.cli.cross_venue_testnet --arm"),
    ("installer", "powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1 -Apply"),
    ("installer", "powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:/work/demo-brain/install.ps1 -Apply "
                  "-Extras tui"),
    ("installer", "pwsh -File ./install.ps1 -apply:$true"),
    ("installer", "bash -c 'powershell -File install.ps1 -A'"),
    # found by the independent review (2026-11-02)
    ("keys", "gh.exe secret set FOO --body x"),
    ("keys", "\"C:/Program Files/GitHub CLI/gh.exe\" secret set FOO --body x"),
    ("keys", "curl -sX PUT -H 'Authorization: token x' https://api.github.com/repos/o/r/actions/secrets/FOO -d '{}'"),
    ("keys", "curl -sSX DELETE https://api.github.com/repos/o/r/actions/secrets/FOO"),
    ("keys", "gh repo deploy-key add k.pub --allow-write"),
    ("keys", "gh api -X POST user/keys -f key=x"),
    ("keys", "gh api -X POST repos/o/r/keys -f key=x"),
    ("keys", "gpg --armor --export-secret-key ABCD"),
    ("keys", "npm config set //registry.npmjs.org/:_authToken=$T"),
    ("accounts", "gcloud auth application-default login"),
    ("accounts", "docker -H ssh://box1 login -u x"),
    ("accounts", "gh api -X PUT repos/o/r/collaborators/u"),
    ("scheduled", "reg import run.reg"),
]

PS_OWNER_REFUSED = [
    ("installer", ".\\install.ps1 -Apply"),
    ("installer", "& 'D:\\work\\demo-brain\\install.ps1' -Ap"),
    ("installer", ". .\\install.ps1 -Apply"),
    ("installer", "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -File install.ps1 -Apply'"),
    ("scheduled", "Register-ScheduledTask -TaskName BrainDigest -Action $a -Trigger $t"),
    ("scheduled", "$a = New-ScheduledTaskAction -Execute brain.exe; Register-ScheduledTask BrainDigest -Action $a"),
    ("scheduled", "Unregister-ScheduledTask -TaskName 'Demo cycle' -Confirm:$false"),
    ("scheduled", "Set-ScheduledTask -TaskName BrainDigest -Trigger $t"),
    ("scheduled", "New-Service -Name BrainMCP -BinaryPathName C:\\brain\\brain.exe"),
    ("scheduled", "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' -Name Brain "
                  "-Value brain.exe"),
    ("scheduled", "schtasks /create /tn x /tr y /sc onlogon"),
    ("keys", "Set-Secret -Name ntfy -Secret $s"),
    ("keys", "cmdkey /add:box1 /user:ops /pass:x"),
    ("keys", "gh secret set TOKEN --body $env:TOKEN"),
    ("accounts", "New-LocalUser -Name brain -NoPassword"),
    ("accounts", "Add-LocalGroupMember -Group Administrators -Member brain"),
    ("visibility", "Invoke-RestMethod -Method Patch -Uri https://api.github.com/repos/acme/x "
                   "-Body (@{private=$false} | ConvertTo-Json)"),
    ("visibility", "pwsh -Command \"gh repo edit acme/x --visibility public\""),
    ("installer", ".\\install.ps1 –Apply"),
    ("keys", "Invoke-RestMethod -Method:Put -Uri https://api.github.com/repos/o/r/actions/secrets/FOO -Body $b"),
    ("scheduled", "New-ItemProperty -Path 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Run' -Name x -Value y"),
]


@pytest.mark.parametrize("category, command", OWNER_REFUSED)
def test_owner_refuses_in_bash(owner, category, command):
    reason = bash(owner, command)
    assert refused(reason, "owner", category), reason
    assert f"{category} is Ada's alone" in reason and "brain queue add --kind action --guard guard-" in reason


@pytest.mark.parametrize("category, command", PS_OWNER_REFUSED)
def test_owner_refuses_in_powershell(owner, category, command):
    reason = pwsh(owner, command)
    assert refused(reason, "owner", category), reason


@pytest.mark.parametrize("command", [
    "gh repo view acme/demo-brain --json visibility",
    "gh repo edit acme/x --description 'the Brain'",
    "gh repo create acme/scratch --private",
    "gh secret list",
    "gh auth status",
    "gh api repos/acme/x --jq .private",
    "gh api -X PATCH repos/acme/x -f description=new",
    "gh pr create --title 'Guard gh repo edit --visibility' --body 'refuses gh secret set and schtasks /create'",
    "git commit -m 'refuse install.ps1 -Apply, crontab -e and --arm in the owner guard'",
    "brain queue add --kind action --title 'Make the engine public' --what 'gh repo edit acme/brain "
    "--visibility public'",
    "grep -rn 'Register-ScheduledTask\\|schtasks /create' plugins/",
    "schtasks /query /tn \\Demo\\ /fo LIST",
    "crontab -l",
    "systemctl status brain.service",
    "ssh-keygen -lf ~/.ssh/id_ed25519.pub",
    "ssh-keygen -R box1",
    "gpg --list-secret-keys",
    "docker ps",
    "npm install",
    "sc query BrainSvc",
    "powershell.exe -NoProfile -ExecutionPolicy Bypass -File install.ps1",
    "python -m demo_fund.cli.cross_venue_testnet --mode probe",
    "net user",
    "kubectl create configmap brain-config --from-file=c.yaml -n brain",
    "gpg --batch --homedir /tmp/vault-test/h1 --passphrase '' --quick-gen-key canary@example.invalid",
    "python -c \"import json; print(json.dumps({'file_path': '.claude/settings.json', 'content': "
    "'BRAIN_GUARD_ALLOW'}))\"",
    "reg query HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
    "cat /etc/cron.d/brain",
    "grep -rn -- --arm src/",
    "git grep -n -- --arm",
    "rg -n -e --arm plugins/",
    "cp agent.service deploy/etc/systemd/system/",
    "echo x > infra/etc/cron.d/backup",
    "aws configure list",
    "aws configure get region",
    "docker login --help",
    "ssh-keygen --help",
    "gh secret set --help",
])
def test_owner_passes_reads_and_mentions(owner, command):
    assert bash(owner, command) is None


@pytest.mark.parametrize("command", [
    ".\\install.ps1",
    "Get-ScheduledTask -TaskPath \\Demo\\",
    "Get-Service sshd",
    "Get-Secret -Name x -AsPlainText:$false | Out-Null",
    "Get-LocalUser",
    "Get-ItemProperty 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run'",
    "sc 'notes.txt' 'text'",
])
def test_owner_passes_powershell_reads(owner, command):
    reason = pwsh(owner, command)
    assert reason is None or f"{guards.ALLOW_ENV}=owner " not in reason


def _probes():
    data = yaml.safe_load(PERMISSIONS.read_text(encoding="utf-8"))
    cats, errors = permissions.categories(data)
    assert not errors
    return [(c.name, p) for c in cats for p in c.probes]


@pytest.mark.parametrize("category, probe", _probes())
def test_every_probe_of_the_never_list_is_refused(owner, category, probe):
    """The probes (permissions.PROBES and permissions.yaml's) are the commands of the never-grantable categories: the
    guard refuses each, in PowerShell, and in Bash too when it has no Windows path."""
    assert refused(pwsh(owner, probe), "owner", category), probe
    if "\\" not in probe:
        assert refused(bash(owner, probe), "owner", category), probe


def test_the_list_is_permissions_yaml(tmp_path, owner, monkeypatch):
    """One source: a category the file does not declare (installer, before the owner's answer) is not guarded; a deny
    rule the file adds is, through nested shells, wrappers, paths and ssh; a new category with a deny rule too."""
    cmd = "powershell.exe -NoProfile -File install.ps1 -Apply"
    monkeypatch.setenv("BRAIN_PERMISSIONS", str(tmp_path / "missing.yaml"))
    assert bash(owner, cmd) is None
    f = tmp_path / "permissions.yaml"
    f.write_text("v: 1\nnever:\n  keys:\n    deny: [\"Shell(fly secrets set *)\"]\n"
                 "  installer:\n    why: \"Ada runs the installer\"\n    find: 'install\\.ps1'\n"
                 "  publishing:\n    why: \"Ada publishes packages herself\"\n    find: '\\bnpm publish\\b'\n"
                 "    deny: [\"Bash(npm publish*)\", \"PowerShell(npm publish*)\"]\n", encoding="utf-8")
    monkeypatch.setenv("BRAIN_PERMISSIONS", str(f))
    assert refused(bash(owner, cmd), "owner", "installer")
    for command in ("fly secrets set KEY=x", "sudo env A=1 fly secrets set KEY=x", "bash -c 'fly secrets set K=x'",
                    "C:/tools/fly.exe secrets set KEY=x", "ssh deploy@box fly secrets set KEY=x"):
        assert refused(bash(owner, command), "owner", "keys"), command
    assert refused(pwsh(owner, "npm publish --access public"), "owner", "publishing")
    assert bash(owner, "fly secrets list") is None


def test_override_is_the_owners_and_per_category(owner, monkeypatch, brain_home):
    (brain_home / "ledger").mkdir(parents=True)
    monkeypatch.setenv(guards.ALLOW_ENV, "owner:installer")
    assert bash(owner, "powershell -File install.ps1 -Apply") is None
    assert refused(bash(owner, "gh secret set X"), "owner", "keys")
    monkeypatch.setenv(guards.ALLOW_ENV, "owner")
    assert bash(owner, "gh secret set X") is None
    monkeypatch.setenv(guards.ALLOW_ENV, "all")
    assert bash(owner, "shutdown /s /t 0") is None
    rows = [json.loads(x) for f in (brain_home / "ledger").glob("guards-*.jsonl") for x in f.read_text().splitlines()]
    assert [r["decision"] for r in rows] == ["overridden", "denied", "overridden", "overridden"]


@pytest.mark.parametrize("tool, command", [
    ("PowerShell", "setx BRAIN_GUARD_ALLOW all"),
    ("PowerShell", "[Environment]::SetEnvironmentVariable('BRAIN_GUARD_ALLOW', 'owner', 'User')"),
    ("PowerShell", "Set-ItemProperty HKCU:\\Environment -Name BRAIN_GUARD_ALLOW -Value all"),
    ("Bash", "echo 'export BRAIN_GUARD_ALLOW=all' >> ~/.bashrc"),
    ("Bash", "python -c \"import json; p='C:/Users/x/.claude/settings.json'; d=json.load(open(p)); "
             "d['env']={'BRAIN_GUARD_ALLOW':'all'}; json.dump(d, open(p, 'w'))\""),
])
def test_the_override_cannot_be_set_by_a_session(owner, tool, command):
    reason = decide(payload(tool, owner, command=command, description="x"))
    assert refused(reason, "owner", "override"), reason
    assert "override is Ada's" in reason


@pytest.mark.parametrize("tool, command", [
    ("Bash", "cat > notes.md <<'EOF'\nThe owner sets it: setx BRAIN_GUARD_ALLOW all\nEOF"),
    ("Bash", "grep -rn BRAIN_GUARD_ALLOW README.md plugins/"),
    ("PowerShell", "Get-ChildItem Env:BRAIN_GUARD_ALLOW"),
    ("Bash", "git commit -m 'Document setx BRAIN_GUARD_ALLOW as owner-only'"),
])
def test_mentions_of_the_override_pass(owner, tool, command):
    assert decide(payload(tool, owner, command=command, description="x")) is None


def test_edits_that_set_the_override_or_start_programs(owner, tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    settings = home / ".claude" / "settings.json"
    reason = decide(payload("Edit", owner, file_path=str(settings), old_string="{", new_string='{"env": '
                            '{"BRAIN_GUARD_ALLOW": "all"},'))
    assert refused(reason, "owner", "override") and "the override is Ada's" in reason
    assert decide(payload("Edit", owner, file_path=str(settings), old_string="a", new_string="b")) is None
    startup = home / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    reason = decide(payload("Write", owner, file_path=str(startup / "brain.cmd"), content="brain up"))
    assert refused(reason, "owner", "scheduled") and "--guard guard-" in reason and "is Ada's alone" in reason
    reason = decide(payload("Write", owner, file_path=str(home / ".config" / "systemd" / "user" / "b.service"),
                            content="[Service]"))
    assert refused(reason, "owner", "scheduled")
    assert decide(payload("Write", owner, file_path=str(owner / "brain.cmd"), content="brain up")) is None
    # a repo's own deploy/etc/systemd/system or dotfiles/.config/autostart starts nothing on this machine
    for repo_path in (owner / "deploy" / "etc" / "systemd" / "system" / "x.service",
                      owner / "dotfiles" / ".config" / "autostart" / "x.desktop",
                      tmp_path / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" /
                      "Startup" / "x.cmd"):
        assert decide(payload("Write", owner, file_path=str(repo_path), content="x")) is None, repo_path


@pytest.mark.parametrize("tool, command", [
    ("PowerShell", "Add-Content $PROFILE '$env:BRAIN_GUARD_ALLOW=\"all\"'"),
    ("Bash", "python -c \"import pathlib; p=pathlib.Path.home()/'.claude'/'settings.json'; "
             "p.write_text('{\\\"env\\\": {\\\"BRAIN_GUARD_ALLOW\\\": \\\"all\\\"}}')\""),
])
def test_the_override_written_to_a_path_the_guard_cannot_resolve(owner, tool, command):
    assert refused(decide(payload(tool, owner, command=command, description="x")), "owner", "override")


def test_a_check_that_fails_lets_the_others_run(owner, brain_home):
    """A manifest that makes a check fail never lets the rest of the call through: the manifest cannot be read
    (refused), and the power guard still sees the shutdown after it."""
    (owner / "bad.yaml").write_text("kind: Job\nmetadata: oops\n", encoding="utf-8")
    assert "goes to the context's namespace" in bash(owner, "kubectl apply -f bad.yaml")
    assert refused(bash(owner, "kubectl -n brain apply -f bad.yaml; shutdown /s /t 0"), "power", "machine")
    (owner / "nons.yaml").write_text("kind: Job\nmetadata: {name: x}\n", encoding="utf-8")
    assert bash(owner, "kubectl -n brain apply -f nons.yaml") is None
    assert "namespace kube-system" in bash(owner, "kubectl -n brain apply -f nons.yaml --namespace=kube-system")
    stale = "cat > nons.yaml <<'X'\nkind: Job\nmetadata: {name: x, namespace: kube-system}\nX\n" \
            "kubectl -n brain apply -f nons.yaml"
    assert "this command writes it first" in bash(owner, stale)


def test_the_scheduled_tasks_tool(owner):
    reason = decide(payload("mcp__scheduled-tasks__create_scheduled_task", owner, taskId="digest",
                            cronExpression="0 8 * * *", prompt="brain digest"))
    assert refused(reason, "owner", "scheduled")


# --- power and cluster ------------------------------------------------------------------------------------------------

POWER_REFUSED = [
    ("machine", "shutdown /s /t 0"),
    ("machine", "shutdown.exe /r /f /t 0"),
    ("machine", "shutdown /h"),
    ("machine", "sudo shutdown -h now"),
    ("machine", "systemctl poweroff"),
    ("machine", "sudo systemctl suspend"),
    ("machine", "systemctl start hibernate.target"),
    ("machine", "loginctl reboot"),
    ("machine", "sudo reboot"),
    ("machine", "poweroff"),
    ("machine", "init 0"),
    ("machine", "rundll32.exe powrprof.dll,SetSuspendState 0,1,0"),
    ("machine", "bcdedit /set {fwbootmgr} bootsequence {a1b2c3d4-0000-0000-0000-000000000000}"),
    ("machine", "sudo efibootmgr -n 0003"),
    ("machine", "ipmitool -I lanplus -H box2-bmc -U ops-power -L OPERATOR chassis power off"),
    ("machine", "ipmitool chassis bootdev pxe"),
    ("machine", "pmset sleepnow"),
    ("machine", "ssh box1 'sudo shutdown -h now'"),
    ("machine", "ssh -i ~/.ssh/box1_shutdown -p 22 ops@box1 sudo systemctl poweroff"),
    ("machine", "ssh box1 shutdown /s /t 0"),
    ("machine", "cmd /c shutdown /r /t 0"),
    ("machine", "timeout 5 bash -c 'sudo reboot'"),
    ("node", "sudo systemctl stop k3s-agent"),
    ("node", "sudo systemctl stop acme-node-agent"),
    ("node", "ssh box1 sudo /usr/local/bin/k3s-killall.sh"),
    ("node", "kubectl acme wake box1"),
    ("node", "kubectl-acme shutdown box1 --reason idle"),
    ("node", "acme-cli sleep box2"),
    ("node", "acme --output json wake box1"),
    ("node", "python scripts/cluster/sigma_node_power.py wake box2 --timeout 200"),
    ("node", "python scripts/cluster/sigma_node_power.py sleep box2"),
    ("node", "python -m scripts.cluster.node_power.controller wake box1"),
    ("wake", "wakeonlan aa:bb:cc:dd:ee:ff"),
    ("wake", "sudo etherwake -i eth0 aa:bb:cc:dd:ee:ff"),
    ("wake", "python -m wakeonlan aa:bb:cc:dd:ee:ff"),
    ("wake", "python3 -c \"from wakeonlan import send_magic_packet; send_magic_packet('aa:bb:cc:dd:ee:ff')\""),
    ("wake", "python -c \"import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); "
             "s.sendto(b'\\xff'*6 + bytes.fromhex('aabbccddeeff')*16, ('255.255.255.255', 9))\""),
    ("bot", "curl -s https://api.telegram.org/bot$TOKEN/sendMessage -d chat_id=1 -d text='/power box1 off'"),
    ("cluster", "kubectl drain box1 --ignore-daemonsets --delete-emptydir-data"),
    ("cluster", "kubectl cordon box1"),
    ("cluster", "kubectl uncordon box1"),
    ("cluster", "kubectl taint nodes box1 gpu=true:NoSchedule"),
    ("cluster", "kubectl delete node box1"),
    ("cluster", "kubectl label node box1 acme.io/power=off --overwrite -n brain"),
    ("cluster", "kubectl patch acmenode box1 --type merge -p '{\"spec\":{\"power\":\"off\"}}'"),
    ("cluster", "kubectl delete pod gpu-job-1"),
    ("cluster", "kubectl -n acme-ai scale deployment ollama --replicas 0"),
    ("cluster", "kubectl rollout restart deployment/ollama -n acme-ai"),
    ("cluster", "kubectl delete pods --all -A"),
    ("cluster", "kubectl create namespace brain-tmp"),
    ("cluster", "kubectl exec -n kube-system coredns-1 -- sh"),
    ("cluster", "kubectl apply -k gitops/brain"),
    ("cluster", "kubectl apply -f https://example.invalid/x.yaml -n brain"),
    ("cluster", "kubectl debug node/box1 -it --image=busybox -n brain"),
    ("cluster", "k3s kubectl drain box1"),
    ("cluster", "ssh box4 kubectl cordon box1"),
    ("cluster", "kubectl node-shell box1"),
    # the shapes an independent review found passing (2026-11-02): stdin fed to a shell, ssh's options after the
    # host, launchers, kubectl's last namespace, raw paths, unknown kinds, argocd's destination, helm's options
    ("machine", "ssh box1 <<'EOF'\nsudo reboot\nEOF"),
    ("node", "ssh box1 'bash -s' <<'EOF'\nsudo systemctl stop k3s\nEOF"),
    ("machine", "bash <<'EOF'\nsudo reboot\nEOF"),
    ("machine", "echo \"sudo reboot\" | bash"),
    ("machine", "bash <<< 'sudo reboot'"),
    ("machine", "ssh box1 -t 'sudo reboot'"),
    ("machine", "ssh ada@box1 -p 2222 'sudo systemctl poweroff'"),
    ("machine", "ssh box1 -- sudo reboot"),
    ("machine", "gsudo shutdown /r /t 0"),
    ("machine", "doas reboot"),
    ("machine", "pkexec reboot"),
    ("node", "wsl -- sudo systemctl stop k3s"),
    ("node", "uv run python scripts/cluster/sigma_node_power.py off box1"),
    ("wake", "uvx wakeonlan aa:bb:cc:dd:ee:ff"),
    ("wake", "npx wol aa:bb:cc:dd:ee:ff"),
    ("machine", "eval sudo reboot"),
    ("machine", "sudo --user root reboot"),
    ("machine", "sudo -iu root reboot"),
    ("machine", "chroot /host reboot"),
    ("machine", "nsenter -t 1 -m -- reboot"),
    ("machine", "ansible box1 -b -m reboot"),
    ("machine", "ansible box1 -m shell -a 'sudo reboot'"),
    ("node", "python -X utf8 scripts/cluster/sigma_node_power.py off box1"),
    ("node", "python -W ignore agents/forge_boot.py arm box1"),
    ("bot", "python3 -c \"import requests; requests.post('https://api.telegram.org/botT/sendMessage', "
            "data={'chat_id': 1, 'text': '/power off box1'})\""),
    ("wake", "python3 -c \"import socket; s.sendto(bytes([255]*6) + mac*16, ('255.255.255.255', 9))\""),
    ("cluster", "kubectl -n brain delete --raw /api/v1/namespaces/kube-system"),
    ("cluster", "kubectl -n brain delete gatewayclass edge"),
    ("cluster", "kubectl create clusterrolebinding x --clusterrole=admin --user=brain -n brain"),
    ("cluster", "argocd app create brain-x --repo https://example.invalid/r --path p --dest-namespace kube-system "
                "--sync-policy automated"),
    ("cluster", "helm --registry-config x uninstall traefik -n kube-system"),
    ("cluster", "helm upgrade --install ollama charts/ollama -n brain"),
    ("cluster", "helm uninstall ollama -n acme-ai"),
    ("cluster", "argocd app sync acme-ai"),
    ("cluster", "argocd app sync -l app.kubernetes.io/part-of=acme"),
    ("cluster", "argocd app delete brain acme-ai"),
    ("cluster", "argocd cluster rm https://box4:6443"),
]

PS_POWER_REFUSED = [
    ("machine", "Stop-Computer -Force"),
    ("machine", "Restart-Computer -ComputerName box1 -Force"),
    ("machine", "Start-Process shutdown -ArgumentList '/r /t 0'"),
    ("machine", "(Get-WmiObject Win32_OperatingSystem).Win32Shutdown(1)"),
    ("machine", "Invoke-CimMethod -ClassName Win32_OperatingSystem -MethodName Reboot"),
    ("machine", "Add-Type -AssemblyName System.Windows.Forms; "
                "[System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)"),
    ("machine", "Invoke-Command -ComputerName box1 -ScriptBlock { Stop-Computer -Force }"),
    ("wake", "$mac = [byte[]](0xAA,0xBB,0xCC,0xDD,0xEE,0xFF); $p = [byte[]](,0xFF * 6) + $mac * 16; "
             "$u = New-Object Net.Sockets.UdpClient; $u.Send($p, $p.Length, '255.255.255.255', 9)"),
    ("bot", "Invoke-RestMethod \"https://api.telegram.org/bot$t/sendMessage\" "
            "-Body @{chat_id=1; text='/power box1 on'}"),
    ("cluster", "kubectl delete node box1"),
    ("machine", "\"Restart-Computer -Force\" | Invoke-Expression"),
    ("machine", "runas /user:Administrator \"shutdown /r /t 0\""),
    ("machine", "(Get-WmiObject Win32_OperatingSystem).Reboot()"),
    ("wake", "$p = [byte[]](,[byte]255 * 6) + $mac * 16; $u.Send($p, $p.Length, '255.255.255.255', 9)"),
]


@pytest.mark.parametrize("check, command", POWER_REFUSED)
def test_power_refuses_in_bash(owner, check, command):
    reason = bash(owner, command)
    assert refused(reason, "power", check), reason
    assert "brain queue add --kind action --guard guard-" in reason
    assert ("GitOps PR" in reason) == (check == "cluster")
    assert "Ada's queue" in reason


@pytest.mark.parametrize("check, command", PS_POWER_REFUSED)
def test_power_refuses_in_powershell(owner, check, command):
    reason = pwsh(owner, command)
    assert refused(reason, "power", check), reason


@pytest.mark.parametrize("command", [
    "shutdown /a",
    "shutdown -c",
    "systemctl status k3s",
    "systemctl --user list-timers",
    "bcdedit /enum",
    "efibootmgr -v",
    "ipmitool -I lanplus -H box2-bmc chassis power status",
    "ssh box1 uptime",
    "ssh -p 22 box1 'systemctl status k3s-agent'",
    "kubectl get nodes -o wide",
    "kubectl get pods -A",
    "kubectl --context brain-observer --request-timeout=2s get acmenodes",
    "kubectl describe node box1",
    "kubectl logs -n kube-system coredns-1",
    "kubectl -n brain scale deployment mcp --replicas 1",
    "kubectl rollout restart deployment/mcp -n brain",
    "kubectl rollout status deployment/ollama -n acme-ai",
    "kubectl --context admin delete pod job-1 --namespace=brain",
    "kubectl auth can-i create pods -n brain",
    "kubectl acme status box1",
    "kubectl-acme history",
    "python scripts/cluster/sigma_node_power.py status --all --json",
    "python scripts/cluster/sigma_node_power.py wake box3 --dry-run",
    "argocd app sync brain",
    "argocd app get acme-ai",
    "argocd app list",
    "helm list -A",
    "helm template ollama charts/ollama -n brain",
    "curl -d text='power status' https://ntfy.sh/topic",
    "git commit -m 'refuse shutdown, kubectl drain and wakeonlan'",
    "grep -n 'Stop-Computer\\|systemctl poweroff' README.md",
    "echo reboot",
    "cat /sys/power/state",
    "kubectl create deployment web --image=nginx --dry-run=client -o yaml",
    "kubectl krew list",
    "kubectl tree deploy brain -n brain",
    "kubectl delete --help",
    "acme --output json status",
    "acme-cli wake --help",
    "systemctl status acme-node-agent",
    "python scripts/cluster/sigma_node_power.py --help",
    "bcdedit /enum firmware",
    "argocd app actions list brain",
    "argocd app create brain-mcp --repo https://example.invalid/r --path gitops/brain --dest-namespace brain",
    "curl -d 'text=/power status' https://ntfy.sh/x",
    "ssh box1 'cat /etc/os-release' <<'EOF'\nsudo reboot\nEOF",
    "git commit -F - <<'EOF'\nRefuse sudo reboot fed to bash\nEOF",
    "bash script.sh <<'EOF'\nsudo reboot\nEOF",
])
def test_power_passes_reads_and_the_brain_namespace(owner, command):
    assert bash(owner, command) is None


def test_the_node_tools_are_config_json_s(owner, tmp_path, monkeypatch):
    """One source: the node CLIs and services the power guard knows by name are config.json's power (the engine names
    none). Without it, a platform's CLI is a program like any other, and kubectl's plugin one the guard does not read;
    a name that is not a program's is dropped."""
    assert guards.node_tools() == {k: frozenset(v) for k, v in POWER.items()}
    bare = tmp_path / "bare-config.json"
    bare.write_text(json.dumps({"v": 1, "identity": {"owner": "Ada"},
                                "power": {"node_clis": ["acme-cli", "x|y", "", 3], "node_services": "acme"}}),
                    encoding="utf-8")
    monkeypatch.setenv("BRAIN_CONFIG", str(bare))
    assert guards.node_tools() == {"node_clis": frozenset({"acme-cli"}), "node_services": frozenset()}
    assert bash(owner, "acme wake box1") is None
    assert bash(owner, "sudo systemctl stop acme-node-agent") is None
    reason = bash(owner, "kubectl acme status box1")
    assert refused(reason, "power", "cluster") and "a verb or plugin the guard does not read" in reason
    assert refused(bash(owner, "acme-cli wake box1"), "power", "node")


def test_kubectl_reads_the_manifests(owner):
    (owner / "job.yaml").write_text("apiVersion: batch/v1\nkind: Job\nmetadata: {name: index, namespace: brain}\n"
                                    "---\napiVersion: v1\nkind: ConfigMap\nmetadata: {name: c}\n", encoding="utf-8")
    (owner / "acme.yaml").write_text("kind: Deployment\nmetadata: {name: x, namespace: acme-ai}\n",
                                     encoding="utf-8")
    (owner / "rbac.yaml").write_text("kind: List\nitems:\n- kind: ClusterRoleBinding\n  metadata: {name: x}\n",
                                     encoding="utf-8")
    (owner / "secret.yaml").write_text("kind: Secret\nmetadata: {name: t, namespace: brain}\n", encoding="utf-8")
    (owner / "gitops").mkdir()
    shutil.copy(owner / "job.yaml", owner / "gitops" / "job.yaml")
    assert bash(owner, "kubectl apply -f job.yaml -n brain") is None
    assert bash(owner, "kubectl apply -f gitops/ -n brain") is None
    assert bash(owner, "kubectl delete -f job.yaml --namespace brain") is None
    assert "the context's namespace" in bash(owner, "kubectl apply -f job.yaml")   # the ConfigMap has none
    assert "goes to namespace acme-ai" in bash(owner, "kubectl apply -f acme.yaml -n brain")
    assert "ClusterRoleBinding is cluster-scoped" in bash(owner, "kubectl apply -f rbac.yaml -n brain")
    assert "cannot be read" in bash(owner, "kubectl apply -f missing.yaml -n brain")
    assert "cannot be read" in bash(owner, "cat job.yaml | kubectl apply -f - -n brain")
    assert refused(bash(owner, "kubectl apply -f secret.yaml -n brain"), "owner", "keys")
    assert "cannot be read" in bash(owner, "ssh box4 kubectl apply -f job.yaml -n brain")


# --- into the owner's queue -------------------------------------------------------------------------------------------

def _store(tmp_path):
    root = tmp_path / "brainrepo"
    store = root / "notes" / "graph"
    (store / "nodes").mkdir(parents=True)
    (store / "edges").mkdir()
    (store / "schema.yaml").write_text(init.template("schema.yaml").replace("{owner_line}", "owner: Ada\n"),
                                       encoding="utf-8")
    (store / "nodes" / "work.yaml").write_text("- {id: wi-brain-x, type: WorkItem, status: todo, title: \"X\"}\n",
                                                encoding="utf-8")
    (store / "edges" / "work.yaml").write_text("", encoding="utf-8")
    return root


def test_a_refusal_goes_to_the_owners_queue_with_its_exact_command(owner, tmp_path, brain_home, monkeypatch):
    root = _store(tmp_path)
    monkeypatch.setenv("BRAIN_PROJECTS", str(tmp_path / "projects.yaml"))
    (tmp_path / "projects.yaml").write_text(f"brain: {{root: {root.as_posix()}}}\n", encoding="utf-8")
    command = "gh repo edit acme/brain --visibility public --accept-visibility-change-consequences"
    reason = bash(root, f"cd {root.as_posix()} && {command}")
    assert "put it in Ada's queue with the exact command" in reason
    ref = reason.split("--guard ")[1].split()[0]
    assert ref.startswith("guard-") and (brain_home / "ledger").is_dir()
    assert bash(root, command).split("--guard ")[1].split()[0] == ref   # the same action, the same ref

    proj = projects.for_root(root)
    entry = next(e for e in queue.collect([proj], with_graph=False)[0]["entries"] if e["id"] == ref)
    assert entry["kind"] == "action" and entry["source"] == "guard" and entry["category"] == "visibility"
    assert entry["count"] == 2 and entry["title"] == command and entry["folders"] == [str(root)]
    assert f"--guard {ref}" in entry["how"]

    ddr, out, _ = queue.add(root, kind="action", title="", what="", at=AT, guard=ref, items=["wi-brain-x"])
    assert ddr["kind"] == "action" and ddr["guard"] == ref and ddr["question"] == command
    assert "command" not in ddr   # the owner's Apply runs a brain or install.ps1 command only (brain queue apply)
    assert ddr["title"].startswith("Ada's alone (visibility): gh repo edit --visibility")
    assert records.check(root) == ([], [])
    entries = queue.collect([proj], with_graph=False)[0]["entries"]
    assert ref not in {e["id"] for e in entries}   # queued once, as the DDR that carries it
    queued = next(e for e in entries if e["id"] == ddr["id"])
    assert queued["detail"] == command and queued["guard"] == ref

    installer = pwsh(root, ".\\install.ps1 -Apply").split("--guard ")[1].split()[0]
    ddr, _, _ = queue.add(root, kind="action", title="", what="", at=AT, guard=installer, slug="installer")
    assert ddr["command"] == ".\\install.ps1 -Apply" and ddr["cwd"] == str(root)   # what Apply shows and runs

    other = bash(root, "gh secret set KEY --body x").split("--guard ")[1].split()[0]
    print(queue.done(root, other, at="2099-01-01T00:00:00Z", note="Ada set it"))
    assert other not in {e["id"] for e in queue.collect([proj], with_graph=False)[0]["entries"]}
    with pytest.raises(queue.QueueError, match="no refusal guard-0000000000 of the owner or power guard"):
        queue.add(root, kind="action", title="", what="", at=AT, guard="guard-0000000000")


def test_without_the_ledger_the_hint_carries_the_command(owner, monkeypatch):
    monkeypatch.setenv("BRAIN_CAPTURE", "0")
    reason = bash(owner, "gh secret set KEY --body x")
    assert "--guard" not in reason
    assert "brain queue add --kind action --title 'Ada'\"'\"'s alone (keys): gh secret set' --what 'gh secret set " \
           "KEY --body x'" in reason
    reason = pwsh(owner, "schtasks /create /tn x /tr y")
    assert "--what 'schtasks /create /tn x /tr y'" in reason


def test_cli_queue_add_guard(owner, tmp_path, brain_home, capsys):
    from brain import cli, decisions
    root = _store(tmp_path)
    ref = bash(owner, "gh secret set KEY --body x").split("--guard ")[1].split()[0]
    assert cli.main(["--root", str(root), "queue", "add", "--guard", ref, "--item", "wi-brain-x"]) == 0
    _, ddr = decisions.find(root, "keys")
    assert ddr["guard"] == ref and ddr["question"] == "gh secret set KEY --body x"
    assert ddr["links"]["items"] == ["wi-brain-x"]
    assert cli.main(["--root", str(root), "queue", "add", "--kind", "action"]) == 1
    assert "--title and --what, or --guard" in capsys.readouterr().err


# --- the pre-filter ---------------------------------------------------------------------------------------------------

def test_prefilter_starts_python_for_every_refused_shape(owner):
    guards.node_tools()   # what a first Python run does: config.json's node CLIs into guard.sh's cache
    commands = [c for _, c in OWNER_REFUSED + PS_OWNER_REFUSED + POWER_REFUSED + PS_POWER_REFUSED]
    missed = [c for c, started in zip(commands, _needs_python(commands)) if not started]
    assert not missed


def test_prefilter_reads_the_node_clis_from_the_cache(owner, brain_home):
    """guard.sh cannot find config.json: it reads the node CLIs from <BRAIN_HOME>/cache/node-clis.txt, which a Python
    run keeps current; none until then, and none once config.json names none."""
    cache = brain_home / "cache" / guards.NODE_CLI_CACHE
    assert not cache.exists() and _needs_python(["acme-cli wake box1", "acme wake box1"]) == [False, False]
    assert refused(bash(owner, "acme-cli wake box1"), "power", "node")
    assert cache.read_text(encoding="utf-8") == "acme|acme-cli|kubectl-acme\n"
    assert _needs_python(["acme-cli wake box1", "acme wake box1", "kubectl-acme sleep box2", "acmex wake",
                          "ls my-acme", "echo kubectl-acmes"]) == [True, True, True, False, False, False]
    cache.write_text("\n", encoding="utf-8")
    assert _needs_python(["acme-cli wake box1"]) == [False]


def test_prefilter_names_the_deny_rules_programs():
    """A deny rule of permissions.yaml names a program guard.sh's pre-filter starts Python for; add the name to
    guard.sh's owner_power list along with the rule."""
    cats, _ = permissions.categories(yaml.safe_load(PERMISSIONS.read_text(encoding="utf-8")))
    specs = [permissions.parse(a)[1] for c in cats for r in c.deny for a in permissions.atoms(r)]
    commands = sorted({s.replace("*", "x") for s in specs if s})
    assert commands
    missed = [c for c, started in zip(commands, _needs_python(commands)) if not started]
    assert not missed


def test_off_windows_the_exact_command_and_the_registry_keep_their_backslashes(owner, monkeypatch, brain_home):
    """Where a backslash is read as a separator (guards.BACKSLASH_SEP, Linux and macOS), only paths change: the
    registry key of the user's environment is still that, and the queued command is the one typed."""
    monkeypatch.setattr(guards, "BACKSLASH_SEP", True)
    reason = decide(payload("PowerShell", owner, command=r"Set-ItemProperty HKCU:\Environment -Name BRAIN_GUARD_ALLOW "
                                                         "-Value all", description="x"))
    assert refused(reason, "owner", "override"), reason
    ref = pwsh(owner, r".\install.ps1 -Apply").split("--guard ")[1].split()[0]
    rows = [json.loads(x) for f in (brain_home / "ledger").glob("guards-*.jsonl") for x in f.read_text().splitlines()]
    assert next(r["request"] for r in rows if (r.get("request") or {}).get("ref") == ref)["command"] == \
        r".\install.ps1 -Apply"
