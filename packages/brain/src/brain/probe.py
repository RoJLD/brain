"""This machine's facts for ``brain doctor`` (alias ``brain profile``), at zero token and without the network
(wi-brain-profile).

The report has the fields of the machines brick's inventory contract:
``schema``, ``health`` (ok, or degraded when a GPU's memory is unknown) and ``inventory`` with
``cpu`` (model, logical cores, avx2, avx512), ``memory`` (total_bytes, free_bytes), ``gpus`` (vendor, name,
vram_bytes, vram_free_bytes, utilization_percent; null when the source does not say), ``inference`` (the backend and
every one available, in the order cuda, rocm, metal, cpu), ``load`` (load1) and ``platform`` (os, distro, version,
arch). What that contract does not carry goes to a ``brain`` block: the machine's name, the time, the disks, the
tools, the container runtime, the Kubernetes context, the disk encryption and each probe's time.

Each probe runs in its own thread with its own timeout (:data:`TIMEOUTS`): one that does not answer in time is
reported as timed out and the report goes on without it. A command is run with a timeout too, never through a shell.
The GPU's memory on Windows is read from the display adapters' registry keys (``HardwareInformation.qwMemorySize``):
WMI's ``AdapterRAM`` is a 32-bit value capped at 4 GiB. Side effects are module functions the tests replace, as in
brain.stacks: ``_run``, ``_which``, ``_read``, ``_system`` and the Windows readers ``_win_cpu``, ``_win_memory``,
``_win_gpus``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as ProbeTimeout
from datetime import datetime, timezone
from pathlib import Path

from . import config, paths

# The inventory contract's id when config.json names none (inventory.schema: the owner's machines brick, whose agent
# emits the same document).
SCHEMA = "brain.status/v1"
TIMEOUTS = {"cpu": 1.0, "memory": 1.0, "gpus": 4.0, "tools": 2.0, "docker": 3.0, "kube": 2.0, "disk": 1.5,
            "encryption": 4.0, "hardware": 4.0}
SLOW = ("docker", "kube", "encryption", "hardware")   # skipped by --quick: each starts a program that may take a second or more
TOOLS = ("git", "bash", "gh", "docker", "podman", "nerdctl", "kubectl", "wsl", "ollama", "gitleaks", "node",
         "nvidia-smi", "rocm-smi", "age", "gpg")
MODULES = ("textual",)     # pip extras' modules, importable or not
RUNTIMES = ("docker", "podman", "nerdctl")
BACKENDS = ("cuda", "rocm", "metal", "cpu")
GIB = 2 ** 30
CAP32 = 0xFFF00000         # what a 32-bit adapter memory reads at its cap (4,293,918,720 bytes)
VENDORS = {"10de": "nvidia", "1002": "amd", "1022": "amd", "8086": "intel", "106b": "apple"}
BITLOCKER = {1: "on", 2: "off", 3: "encrypting", 4: "decrypting", 5: "suspended", 6: "on (locked)"}
# Win32_PhysicalMemoryArray.MemoryErrorCorrection: 3 none, 4 parity (no correction), 5 single-bit ECC, 6 multi-bit
# ECC, 7 CRC; 0, 1 and 2 (reserved, other, unknown) say nothing
ECC_YES, ECC_NO = {5, 6, 7}, {3, 4}
WALK_BUDGET = 1.0          # seconds to measure BRAIN_HOME's size


# Side effects, replaced by fakes in the tests.

def _run(argv: list[str], timeout: float) -> tuple[int | None, str]:
    """(exit code, stdout and stderr); exit code None when it did not finish within ``timeout`` or could not run."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return p.returncode, (p.stdout or "") + (p.stderr or "")


_which = shutil.which
_system = platform.system


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _win_cpu() -> dict:
    """{model, avx2, avx512} from the registry and IsProcessorFeaturePresent (Windows)."""
    import ctypes
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
        model = str(winreg.QueryValueEx(k, "ProcessorNameString")[0]).strip()
    present = ctypes.windll.kernel32.IsProcessorFeaturePresent
    return {"model": model, "avx2": bool(present(40)), "avx512": bool(present(41))}  # PF_AVX2, PF_AVX512F


def _win_memory() -> tuple[int, int]:
    """(total, available) bytes of physical memory (GlobalMemoryStatusEx)."""
    import ctypes

    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                    ("avail", ctypes.c_ulonglong), ("page_total", ctypes.c_ulonglong),
                    ("page_avail", ctypes.c_ulonglong), ("virt_total", ctypes.c_ulonglong),
                    ("virt_avail", ctypes.c_ulonglong), ("ext_avail", ctypes.c_ulonglong)]

    s = Status()
    s.length = ctypes.sizeof(Status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s)):
        raise OSError("GlobalMemoryStatusEx failed")
    return int(s.total), int(s.avail)


def _win_gpus() -> list[dict]:
    """The display adapters' registry values (Windows): one dict per adapter key, the values that exist."""
    import winreg
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    names = ("DriverDesc", "ProviderName", "MatchingDeviceId", "HardwareInformation.qwMemorySize",
             "HardwareInformation.MemorySize")
    out = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(k, i)
            except OSError:
                break
            i += 1
            if not sub.isdigit():
                continue
            try:
                with winreg.OpenKey(k, sub) as key:
                    vals = {}
                    for n in names:
                        try:
                            vals[n] = winreg.QueryValueEx(key, n)[0]
                        except OSError:
                            pass
            except OSError:
                continue
            if vals:
                out.append(vals)
    return out


# The probes: each returns its part of the report, or raises (reported as the probe's error).

def _os() -> str:
    return {"Windows": "windows", "Darwin": "darwin"}.get(_system(), _system().lower() or "unknown")


def probe_cpu() -> dict:
    cores = os.cpu_count() or 0
    system = _os()
    if system == "windows":
        return {**_win_cpu(), "cores": cores}
    if system == "darwin":
        _, model = _run(["sysctl", "-n", "machdep.cpu.brand_string"], TIMEOUTS["cpu"])
        _, feats = _run(["sysctl", "-n", "machdep.cpu.leaf7_features"], TIMEOUTS["cpu"])
        return {"model": model.strip(), "cores": cores, "avx2": "AVX2" in feats, "avx512": "AVX512F" in feats}
    info = _read("/proc/cpuinfo")
    model = next((ln.split(":", 1)[1].strip() for ln in info.splitlines()
                  if ln.lower().startswith(("model name", "hardware", "processor\t: arm"))), "")
    flags = set(next((ln.split(":", 1)[1].split() for ln in info.splitlines()
                      if ln.lower().startswith(("flags", "features"))), []))
    return {"model": model, "cores": cores, "avx2": "avx2" in flags, "avx512": "avx512f" in flags}


def probe_memory() -> dict:
    system = _os()
    if system == "windows":
        total, free = _win_memory()
        return {"total_bytes": total, "free_bytes": free}
    if system == "darwin":
        _, out = _run(["sysctl", "-n", "hw.memsize"], TIMEOUTS["memory"])
        return {"total_bytes": int(out.strip() or 0), "free_bytes": None}
    kb = {m.group(1): int(m.group(2)) * 1024
          for m in re.finditer(r"^(\w+):\s+(\d+) kB", _read("/proc/meminfo"), re.M)}
    return {"total_bytes": kb.get("MemTotal", 0), "free_bytes": kb.get("MemAvailable", kb.get("MemFree"))}


def _gpu(vendor: str, name: str, vram=None, free=None, util=None, source: str = "") -> dict:
    return {"vendor": vendor, "name": name, "vram_bytes": vram, "vram_free_bytes": free,
            "utilization_percent": util, "source": source}


def _vendor(text: str) -> str:
    m = re.search(r"ven_([0-9a-f]{4})", text.lower())
    if m and m.group(1) in VENDORS:
        return VENDORS[m.group(1)]
    low = text.lower()
    for key, vendor in (("nvidia", "nvidia"), ("advanced micro devices", "amd"), ("amd", "amd"), ("intel", "intel")):
        if key in low:
            return vendor
    return "unknown"


def _registry_vram(vals: dict) -> int | None:
    """The adapter's memory in bytes: qwMemorySize (64 bits), else MemorySize unless it reads at the 32-bit cap."""
    q = vals.get("HardwareInformation.qwMemorySize")
    if isinstance(q, int) and q > 0:
        return q
    m = vals.get("HardwareInformation.MemorySize")
    if isinstance(m, (bytes, bytearray)):
        m = int.from_bytes(bytes(m)[:8], "little") if m else None
    if isinstance(m, int) and 0 < m < CAP32:
        return m
    return None


def _nvidia_smi() -> list[dict]:
    if not _which("nvidia-smi"):
        return []
    code, out = _run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free,utilization.gpu",
                      "--format=csv,noheader,nounits"], TIMEOUTS["gpus"] - 0.5)
    if code != 0:
        return []
    gpus = []
    for line in out.splitlines():
        cells = [c.strip() for c in line.split(",")]
        if len(cells) != 4 or not cells[0]:
            continue
        num = [float(c) if re.fullmatch(r"[\d.]+", c) else None for c in cells[1:]]
        mib = [int(n * 2 ** 20) if n is not None else None for n in num[:2]]
        gpus.append(_gpu("nvidia", cells[0], mib[0], mib[1], num[2], "nvidia-smi"))
    return gpus


def _sysfs_amd() -> list[dict]:
    gpus = []
    for card in sorted(Path("/sys/class/drm").glob("card*/device")) if Path("/sys/class/drm").is_dir() else []:
        if _read(str(card / "vendor")).strip().lower() != "0x1002":
            continue
        total = _read(str(card / "mem_info_vram_total")).strip()
        used = _read(str(card / "mem_info_vram_used")).strip()
        vram = int(total) if total.isdigit() else None
        free = vram - int(used) if vram is not None and used.isdigit() else None
        name = _read(str(card / "product_name")).strip() or f"AMD GPU ({card.parent.name})"
        gpus.append(_gpu("amd", name, vram, free, None, "sysfs"))
    return gpus


def probe_gpus() -> list[dict]:
    system = _os()
    nvidia = _nvidia_smi()
    if system == "windows":
        gpus, seen = [], set()
        for vals in _win_gpus():
            name = str(vals.get("DriverDesc") or "").strip()
            device = str(vals.get("MatchingDeviceId") or "")
            if not name or name.startswith("Microsoft") or not device.lower().startswith("pci\\"):
                continue  # the basic display driver, remote and virtual adapters
            vendor = _vendor(device + " " + str(vals.get("ProviderName") or ""))
            key = (name, _registry_vram(vals))
            if key in seen:
                continue
            seen.add(key)
            smi = next((g for g in nvidia if g["name"] == name), None) if vendor == "nvidia" else None
            gpus.append(smi or _gpu(vendor, name, key[1], None, None, "registry qwMemorySize"
                                    if vals.get("HardwareInformation.qwMemorySize") else "registry MemorySize"))
        return gpus
    if system == "darwin":
        if platform.machine().lower() in ("arm64", "aarch64"):
            return [_gpu("apple", "Apple GPU (unified memory)", None, None, None, "platform")]
        return nvidia
    return nvidia + _sysfs_amd()


def _version(argv: list[str], timeout: float) -> str | None:
    code, out = _run(argv, timeout)
    if code != 0:
        return None
    m = re.search(r"\d+\.\d+(?:\.\d+)?", out)
    return m.group(0) if m else out.strip()[:40] or None


def probe_tools() -> dict:
    tools = {"python": platform.python_version()}
    for t in TOOLS:
        tools[t] = bool(_which(t))
    if tools["git"]:
        tools["git_version"] = _version(["git", "--version"], TIMEOUTS["tools"] - 0.2)
    for m in MODULES:
        tools[m] = _module(m)
    return tools


def probe_docker() -> dict:
    """The container runtime: the first of docker, podman and nerdctl found, its client and server versions."""
    runtime = next((r for r in RUNTIMES if _which(r)), None)
    if not runtime:
        return {"runtime": None, "client": None, "server": None}
    t = TIMEOUTS["docker"] - 0.2
    client = _version([runtime, "version", "--format", "{{.Client.Version}}"], t) if runtime != "nerdctl" else None
    server = _version([runtime, "version", "--format", "{{.Server.Version}}"], t) if runtime != "nerdctl" else None
    return {"runtime": runtime, "client": client, "server": server}


def probe_kube() -> dict:
    """The current Kubernetes context of the user's own kubeconfig, by name only: no cluster is called."""
    if not _which("kubectl"):
        return {"kubectl": False, "context": None}
    code, out = _run(["kubectl", "config", "current-context"], TIMEOUTS["kube"] - 0.2)
    return {"kubectl": True, "context": out.strip() if code == 0 and out.strip() else None}


def _existing(p: Path) -> Path:
    """``p``, else its nearest ancestor that exists (BRAIN_HOME before its first write)."""
    return next((d for d in (p, *p.parents) if d.exists()), Path.cwd())


def _size(root: Path, budget: float) -> tuple[int, bool]:
    """(bytes under ``root``, complete): the walk stops at ``budget`` seconds."""
    end, total = time.monotonic() + budget, 0
    stack = [root]
    while stack:
        if time.monotonic() > end:
            return total, False
        try:
            with os.scandir(stack.pop()) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total, True


def probe_disk(roots: list[Path] | None = None) -> dict:
    """Free and total space of the disks that hold BRAIN_HOME and the repo, and BRAIN_HOME's measured size."""
    home = paths.brain_home()
    disks, seen = [], set()
    for label, p in (("brain_home", home), *(("repo", r) for r in roots or [])):
        d = _existing(Path(p))
        try:
            dev = os.stat(d).st_dev
            if dev in seen:
                continue
            seen.add(dev)
            u = shutil.disk_usage(d)
        except OSError:
            continue
        disks.append({"for": label, "path": str(d.resolve()), "free_bytes": u.free, "total_bytes": u.total})
    size, complete = _size(home, WALK_BUDGET) if home.is_dir() else (0, True)
    return {"disks": disks, "brain_home": {"path": str(home), "bytes": size, "complete": complete}}


_PS_BITLOCKER = ("$s = New-Object -ComObject Shell.Application; "
                 "@(Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -ne $null } | ForEach-Object { "
                 "[pscustomobject]@{v = $_.Name; p = $s.NameSpace(\"$($_.Name):\").Self.ExtendedProperty("
                 "'System.Volume.BitLockerProtection')} }) | ConvertTo-Json -Compress")


def _lsblk_crypt(nodes: list, under: bool = False) -> list[dict]:
    out = []
    for n in nodes or []:
        crypt = under or n.get("type") == "crypt"
        for mp in [m for m in ([n.get("mountpoint")] + list(n.get("mountpoints") or [])) if m and m != "[SWAP]"]:
            out.append({"volume": mp, "state": "on" if crypt else "off", "source": "lsblk"})
        out += _lsblk_crypt(n.get("children"), crypt)
    return out


def probe_encryption() -> list[dict]:
    """Each volume's disk encryption: BitLocker by the shell's property (no admin needed; manage-bde -status
    confirms), LUKS by lsblk, FileVault by fdesetup."""
    system = _os()
    t = TIMEOUTS["encryption"] - 0.3
    if system == "windows":
        code, out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_BITLOCKER], t)
        if code != 0:
            raise RuntimeError("powershell did not read BitLockerProtection")
        rows = json.loads(out.strip() or "[]")
        rows = rows if isinstance(rows, list) else [rows]
        return [{"volume": f"{r.get('v')}:", "state": BITLOCKER.get(r.get("p"), "unknown"), "source": "bitlocker"}
                for r in rows if isinstance(r, dict) and r.get("v")]
    if system == "darwin":
        code, out = _run(["fdesetup", "status"], t)
        if code is None:
            raise RuntimeError("fdesetup did not answer")
        return [{"volume": "/", "state": "on" if "is On" in out else "off", "source": "filevault"}]
    if not _which("lsblk"):
        return []
    code, out = _run(["lsblk", "-J", "-o", "NAME,TYPE,MOUNTPOINT"], t)
    if code != 0:
        raise RuntimeError("lsblk failed")
    seen, rows = set(), []
    for r in _lsblk_crypt(json.loads(out).get("blockdevices") or []):
        if r["volume"] not in seen:
            seen.add(r["volume"])
            rows.append(r)
    return rows


_PS_HARDWARE = ("$m = @(Get-CimInstance Win32_PhysicalMemoryArray | ForEach-Object { $_.MemoryErrorCorrection }); "
                "$d = @(Get-CimInstance Win32_PhysicalMemory | ForEach-Object { @($_.TotalWidth, $_.DataWidth) }); "
                "$b = @(Get-CimInstance Win32_Battery).Count; "
                "ConvertTo-Json -Compress @{ecc = $m; dimms = $d; battery = $b}")


def _wmi_ecc(data: dict) -> bool | None:
    """The board's correction method (MemoryErrorCorrection), then the DIMMs' width: an ECC board whose DIMMs carry no
    check bits (TotalWidth == DataWidth) has no ECC."""
    raw = data.get("ecc") if isinstance(data.get("ecc"), list) else [data.get("ecc")]
    codes = {int(c) for c in raw if isinstance(c, (int, float))}
    ecc = True if codes & ECC_YES else False if codes and codes <= ECC_NO else None
    widths = [w for w in (data.get("dimms") or []) if isinstance(w, (int, float))]
    pairs = list(zip(widths[0::2], widths[1::2]))
    return False if ecc and pairs and all(total <= width for total, width in pairs) else ecc


def _win_hardware() -> dict:
    code, out = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_HARDWARE],
                     TIMEOUTS["hardware"] - 0.3)
    if code != 0:
        raise RuntimeError("powershell did not read the memory arrays")
    data = json.loads(out.strip() or "{}")
    return {"ecc": _wmi_ecc(data), "ecc_source": "wmi", "battery": bool(data.get("battery")), "battery_source": "wmi"}


def probe_hardware() -> dict:
    """ECC memory and a battery, each true, false or None (unknown): WMI on Windows (Win32_PhysicalMemoryArray, no
    admin needed; Win32_Battery), EDAC and /sys/class/power_supply on Linux (no EDAC controller: unknown, the module
    may not be loaded), pmset on macOS (ECC unknown)."""
    system = _os()
    if system == "windows":
        return _win_hardware()
    if system == "darwin":
        code, out = _run(["pmset", "-g", "batt"], TIMEOUTS["hardware"] - 0.3)
        return {"ecc": None, "ecc_source": "", "battery": ("InternalBattery" in out) if code == 0 else None,
                "battery_source": "pmset"}
    mcs = list(Path("/sys/devices/system/edac/mc").glob("mc[0-9]*"))
    supplies = list(Path("/sys/class/power_supply").glob("*"))
    battery = any(_read(str(p / "type")).strip() == "Battery" for p in supplies) if supplies else None
    return {"ecc": True if mcs else None, "ecc_source": "edac", "battery": battery,
            "battery_source": "power_supply"}


def _encrypted(b: dict) -> bool | None:
    """BRAIN_HOME's volume encrypted: True (on), False (off), None (unknown, or not probed)."""
    rows = b.get("encryption")
    home = (b.get("brain_home") or {}).get("path") or ""
    if not rows or not home:
        return None
    norm = home.replace("\\", "/").lower()
    best = max((r for r in rows if norm.startswith(str(r.get("volume") or "").replace("\\", "/").lower())),
               key=lambda r: len(str(r.get("volume") or "")), default=None)
    if best is None:
        return None
    state = str(best.get("state") or "")
    return True if state.startswith("on") else False if state == "off" else None


# The report.

def _arch() -> str:
    m = platform.machine().lower()
    return {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64", "i386": "386",
            "i686": "386"}.get(m, m)


def _platform() -> dict:
    system = _os()
    distro = version = ""
    if system == "linux":
        rel = dict(re.findall(r'^(\w+)="?([^"\n]*)"?$', _read("/etc/os-release"), re.M))
        distro, version = rel.get("ID", ""), rel.get("VERSION_ID", "")
    elif system == "windows":
        version = platform.version()
    elif system == "darwin":
        version = platform.mac_ver()[0]
    return {"os": system, "distro": distro, "version": version, "arch": _arch()}


def _inference(gpus: list[dict], plat: dict) -> dict:
    found = {g.get("vendor") for g in gpus}
    available = [b for b, ok in (("cuda", "nvidia" in found), ("rocm", "amd" in found),
                                 ("metal", plat["os"] == "darwin" and plat["arch"] == "arm64"), ("cpu", True)) if ok]
    return {"backend": available[0], "available": available}


def machine() -> str:
    """This machine's name for the brain: $BRAIN_MACHINE, else the host name, lowercase (brain.machine.name, the
    one identity)."""
    from .machine import name
    return name()


def collect(quick: bool = False, roots: list[Path] | None = None, timeouts: dict | None = None) -> dict:
    """The report: every probe in parallel, each bounded by its own timeout; ``quick`` skips :data:`SLOW`."""
    limits = {**TIMEOUTS, **(timeouts or {})}
    jobs = {"cpu": probe_cpu, "memory": probe_memory, "gpus": probe_gpus, "tools": probe_tools,
            "docker": probe_docker, "kube": probe_kube, "disk": lambda: probe_disk(roots),
            "encryption": probe_encryption, "hardware": probe_hardware}
    if quick:
        jobs = {k: f for k, f in jobs.items() if k not in SLOW}
    results, probes, took = {}, {}, {}

    def timed(name, f):
        t0 = time.monotonic()
        try:
            return f()
        finally:
            took[name] = round(time.monotonic() - t0, 2)

    start = time.monotonic()
    pool = ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="brain-probe")
    futures = {name: pool.submit(timed, name, f) for name, f in jobs.items()}
    for name, fut in futures.items():
        left = start + limits[name] - time.monotonic()
        try:
            results[name] = fut.result(timeout=max(left, 0.0))
            probes[name] = {"ok": True, "seconds": took.get(name, 0.0)}
        except ProbeTimeout:
            probes[name] = {"ok": False, "seconds": limits[name], "error": f"timed out after {limits[name]:g} s"}
        except Exception as exc:  # noqa: BLE001 - a probe's failure is reported, never raised
            probes[name] = {"ok": False, "seconds": took.get(name, 0.0), "error": f"{type(exc).__name__}: {exc}"[:200]}
    pool.shutdown(wait=False, cancel_futures=True)
    for name in SLOW if quick else ():
        probes[name] = {"ok": False, "seconds": 0.0, "error": "skipped (--quick)"}
    return report(results, probes)


def report(results: dict, probes: dict) -> dict:
    """The document from the probes' results (a missing result stays null or empty)."""
    plat = _platform()
    gpus = results.get("gpus") or []
    cpu = results.get("cpu") or {"model": "", "cores": os.cpu_count() or 0, "avx2": None, "avx512": None}
    mem = results.get("memory") or {"total_bytes": None, "free_bytes": None}
    load = None
    if hasattr(os, "getloadavg"):
        try:
            load = round(os.getloadavg()[0], 2)
        except OSError:
            load = None
    degraded = any(g.get("vram_bytes") is None for g in gpus) or not probes.get("gpus", {}).get("ok", False)
    disk = results.get("disk") or {"disks": [], "brain_home": None}
    inv = config.load().data.get("inventory")
    return {
        "schema": (inv.get("schema") if isinstance(inv, dict) else None) or SCHEMA,
        "health": "degraded" if degraded else "ok",
        "inventory": {"cpu": cpu, "memory": mem, "gpus": gpus, "inference": _inference(gpus, plat),
                      "load": {"load1": load}, "platform": plat},
        "brain": {"v": 1, "machine": machine(), "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "tools": results.get("tools") or {}, "container": results.get("docker"),
                  "kube": results.get("kube"), "disks": disk["disks"], "brain_home": disk["brain_home"],
                  "encryption": results.get("encryption"), "hardware": results.get("hardware"),
                  "probes": probes},
    }


def facts(doc: dict) -> dict:
    """The flat facts the registry's requires and recommend_when read: os, arch, cpu_cores, memory_gb, gpu,
    gpu_vram_gb (the largest GPU's, GiB), disk_free_gb (BRAIN_HOME's disk), each tool and module (True when found),
    container_runtime, docker_server, kube_context, python; ecc, battery and encrypted (BRAIN_HOME's volume), each
    true, false or None when unknown (not probed, or the probe could not say); gpu None when its probe failed."""
    inv, b = doc["inventory"], doc["brain"]
    gpus = inv.get("gpus") or []
    vram = max([g["vram_bytes"] for g in gpus if g.get("vram_bytes")] or [0])
    total = (inv.get("memory") or {}).get("total_bytes") or 0
    disks = b.get("disks") or []
    home = next((d for d in disks if d["for"] == "brain_home"), disks[0] if disks else None)
    container = b.get("container") or {}
    f = {"os": inv["platform"]["os"], "arch": inv["platform"]["arch"], "cpu_cores": inv["cpu"].get("cores") or 0,
         "memory_gb": round(total / GIB, 1), "gpu": bool(gpus), "gpu_vram_gb": round(vram / GIB, 1),
         "disk_free_gb": round(home["free_bytes"] / GIB, 1) if home else 0.0, "python": True,
         "container_runtime": bool(container.get("runtime"))
         or any((b.get("tools") or {}).get(r) for r in RUNTIMES), "docker_server": bool(container.get("server")),
         "kube_context": bool((b.get("kube") or {}).get("context"))}
    for k, v in (b.get("tools") or {}).items():
        if isinstance(v, bool):
            f[k] = v
    hw = b.get("hardware") or {}
    f.update(ecc=hw.get("ecc"), battery=hw.get("battery"), encrypted=_encrypted(b))
    if not gpus and (b.get("probes") or {}).get("gpus", {}).get("ok") is False:
        f["gpu"] = None   # not found because not probed: unknown, never false
    return f
