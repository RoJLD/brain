import json
import time

import pytest

from brain import probe


@pytest.fixture
def windows(monkeypatch):
    """A Windows machine: an AMD card whose 64-bit registry value is right, the basic display driver, no nvidia-smi."""
    monkeypatch.setattr(probe, "_system", lambda: "Windows")
    monkeypatch.setattr(probe, "_win_cpu", lambda: {"model": "Some CPU 8-Core", "avx2": True, "avx512": False})
    monkeypatch.setattr(probe, "_win_memory", lambda: (64 * probe.GIB, 20 * probe.GIB))
    monkeypatch.setattr(probe, "_which", lambda name: None)
    gpus = [{"DriverDesc": "AMD Radeon RX 7800 XT", "ProviderName": "Advanced Micro Devices, Inc.",
             "MatchingDeviceId": "PCI\\VEN_1002&DEV_747E", "HardwareInformation.qwMemorySize": 16 * probe.GIB,
             "HardwareInformation.MemorySize": probe.CAP32},
            {"DriverDesc": "Microsoft Basic Display Adapter", "MatchingDeviceId": "PCI\\CC_0300"},
            {"DriverDesc": "Remote Display", "MatchingDeviceId": "ROOT\\RDPIDD"}]
    monkeypatch.setattr(probe, "_win_gpus", lambda: gpus)
    return gpus


def test_windows_gpu_memory_comes_from_the_64_bit_registry_value(windows):
    assert probe.probe_gpus() == [{"vendor": "amd", "name": "AMD Radeon RX 7800 XT", "vram_bytes": 16 * probe.GIB,
                                   "vram_free_bytes": None, "utilization_percent": None,
                                   "source": "registry qwMemorySize"}]
    assert probe.probe_cpu() == {"model": "Some CPU 8-Core", "avx2": True, "avx512": False,
                                 "cores": probe.os.cpu_count() or 0}
    assert probe.probe_memory() == {"total_bytes": 64 * probe.GIB, "free_bytes": 20 * probe.GIB}


def test_a_32_bit_value_at_its_cap_is_unknown_and_the_report_degraded(windows):
    del windows[0]["HardwareInformation.qwMemorySize"]
    gpus = probe.probe_gpus()
    assert gpus[0]["vram_bytes"] is None and gpus[0]["source"] == "registry MemorySize"
    windows[0]["HardwareInformation.MemorySize"] = (2 * probe.GIB).to_bytes(8, "little")  # REG_BINARY, below the cap
    assert probe.probe_gpus()[0]["vram_bytes"] == 2 * probe.GIB
    doc = probe.report({"gpus": [probe._gpu("amd", "x", None)]}, {"gpus": {"ok": True, "seconds": 0.1}})
    assert doc["health"] == "degraded" and doc["inventory"]["inference"] == {"backend": "rocm",
                                                                             "available": ["rocm", "cpu"]}


def test_nvidia_smi_gives_free_memory_and_load_on_linux(monkeypatch):
    monkeypatch.setattr(probe, "_system", lambda: "Linux")
    monkeypatch.setattr(probe, "_which", lambda name: "/usr/bin/" + name if name == "nvidia-smi" else None)
    monkeypatch.setattr(probe, "_run", lambda argv, timeout: (0, "NVIDIA GeForce RTX 4090, 24564, 20000, 7\n"
                                                                 "Old Card, [N/A], [N/A], [N/A]\n"))
    files = {"/proc/cpuinfo": "processor\t: 0\nmodel name\t: Example CPU\nflags\t\t: fpu sse avx2 avx512f\n",
             "/proc/meminfo": "MemTotal:       16384000 kB\nMemFree:  1000 kB\nMemAvailable:    8192000 kB\n"}
    monkeypatch.setattr(probe, "_read", lambda path: files.get(path, ""))
    gpus = probe.probe_gpus()
    assert gpus[0] == {"vendor": "nvidia", "name": "NVIDIA GeForce RTX 4090", "vram_bytes": 24564 * 2 ** 20,
                       "vram_free_bytes": 20000 * 2 ** 20, "utilization_percent": 7.0, "source": "nvidia-smi"}
    assert gpus[1]["vram_bytes"] is None
    assert probe.probe_cpu()["model"] == "Example CPU" and probe.probe_cpu()["avx512"] is True
    assert probe.probe_memory() == {"total_bytes": 16384000 * 1024, "free_bytes": 8192000 * 1024}


def test_each_probe_has_its_own_timeout_and_a_failure_never_stops_the_report(monkeypatch):
    monkeypatch.setattr(probe, "probe_cpu", lambda: time.sleep(2) or {})
    monkeypatch.setattr(probe, "probe_memory", lambda: 1 / 0)
    monkeypatch.setattr(probe, "probe_gpus", lambda: [])
    monkeypatch.setattr(probe, "probe_tools", lambda: {"python": "3.12", "git": True, "docker": True})
    monkeypatch.setattr(probe, "probe_disk", lambda roots=None: {"disks": [], "brain_home": None})
    t0 = time.monotonic()
    doc = probe.collect(quick=True, timeouts={"cpu": 0.2})
    assert time.monotonic() - t0 < 1.5
    p = doc["brain"]["probes"]
    assert p["cpu"] == {"ok": False, "seconds": 0.2, "error": "timed out after 0.2 s"}
    assert p["memory"]["ok"] is False and "ZeroDivisionError" in p["memory"]["error"]
    assert {p[n]["error"] for n in probe.SLOW} == {"skipped (--quick)"}
    assert doc["schema"] == probe.SCHEMA and doc["inventory"]["memory"] == {"total_bytes": None, "free_bytes": None}
    f = probe.facts(doc)
    assert f["container_runtime"] is True and f["docker_server"] is False and f["gpu"] is False and f["git"] is True


def test_facts_read_the_largest_gpu_and_brain_homes_disk():
    doc = probe.report(
        {"memory": {"total_bytes": 64 * probe.GIB, "free_bytes": None},
         "gpus": [probe._gpu("intel", "iGPU", probe.GIB), probe._gpu("amd", "big", 16 * probe.GIB)],
         "disk": {"disks": [{"for": "brain_home", "path": "C:\\", "free_bytes": 30 * probe.GIB,
                             "total_bytes": 500 * probe.GIB}], "brain_home": None},
         "docker": {"runtime": "docker", "client": "29", "server": "29"},
         "kube": {"kubectl": True, "context": "lab"}},
        {"gpus": {"ok": True, "seconds": 0.1}})
    f = probe.facts(doc)
    assert (f["memory_gb"], f["gpu_vram_gb"], f["disk_free_gb"]) == (64.0, 16.0, 30.0)
    assert f["docker_server"] and f["kube_context"] and f["container_runtime"]


def test_bitlocker_states_and_luks_mounts_are_read(monkeypatch):
    monkeypatch.setattr(probe, "_system", lambda: "Windows")
    monkeypatch.setattr(probe, "_run", lambda argv, timeout: (0, json.dumps([{"v": "C", "p": 2}, {"v": "E", "p": 1},
                                                                             {"v": "F", "p": None}])))
    assert probe.probe_encryption() == [{"volume": "C:", "state": "off", "source": "bitlocker"},
                                        {"volume": "E:", "state": "on", "source": "bitlocker"},
                                        {"volume": "F:", "state": "unknown", "source": "bitlocker"}]
    monkeypatch.setattr(probe, "_system", lambda: "Linux")
    monkeypatch.setattr(probe, "_which", lambda name: "/usr/bin/lsblk")
    tree = {"blockdevices": [{"name": "nvme0n1", "type": "disk", "mountpoint": None, "children": [
        {"name": "p1", "type": "part", "mountpoint": "/boot"},
        {"name": "p2", "type": "part", "mountpoint": None, "children": [
            {"name": "root", "type": "crypt", "mountpoint": "/"}]}]}]}
    monkeypatch.setattr(probe, "_run", lambda argv, timeout: (0, json.dumps(tree)))
    assert probe.probe_encryption() == [{"volume": "/boot", "state": "off", "source": "lsblk"},
                                        {"volume": "/", "state": "on", "source": "lsblk"}]


def test_the_docker_probe_reports_a_client_without_its_server(monkeypatch):
    monkeypatch.setattr(probe, "_which", lambda name: "docker" if name == "docker" else None)
    monkeypatch.setattr(probe, "_run", lambda argv, timeout: (0, "29.9.2") if "{{.Client.Version}}" in argv
                        else (1, "error during connect"))
    assert probe.probe_docker() == {"runtime": "docker", "client": "29.9.2", "server": None}
    monkeypatch.setattr(probe, "_which", lambda name: None)
    assert probe.probe_docker() == {"runtime": None, "client": None, "server": None}
    assert probe.probe_kube() == {"kubectl": False, "context": None}
