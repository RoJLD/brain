"""Fast YAML reads (wi-brain-yaml-fast-load): one helper for every load of research_graph and of the brain command.

- :func:`loads` parses through libyaml (``CSafeLoader``) when PyYAML has it, else the pure-Python ``SafeLoader``: the
  same data, about 9 times faster (288 store files: 3.96 s pure, 0.43 s with libyaml, measured 2026-11-03).
- :func:`load` reads a file through a per-process memo keyed by (path, size, mtime_ns): a command reads the same
  store file 2 to 7 times (sync, check, status...). The memo keeps the data pickled and each read unpickles a fresh
  copy (copy on read, about 35 times cheaper than parsing again), so a caller may change what it got. A file whose
  modification time is within RACY_NS of when it was read (a write in the same clock tick, as git's racy index) is
  checked against its text's digest too, so two writes of the same size in one tick are never confused.
- ``RESEARCH_GRAPH_YAML_MEMO=0`` turns the memo off; :func:`clear` empties it.
"""

from __future__ import annotations

import hashlib
import os
import pickle
import time
from pathlib import Path

import yaml

LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
RACY_NS = 2_000_000_000   # 2 s: a coarse file system clock (FAT, some network shares) ticks at 2 s
MAX_ENTRIES = 1024

# os.path.normcase(abspath) -> (size, mtime_ns, read_at_ns, digest, pickled data)
_memo: dict[str, tuple[int, int, int, bytes, bytes]] = {}
stats = {"hits": 0, "misses": 0}


def loads(text: str):
    """The data of a YAML text (libyaml when available)."""
    return yaml.load(text, Loader=LOADER)


def _on() -> bool:
    return os.environ.get("RESEARCH_GRAPH_YAML_MEMO", "1") != "0"


def load(path: str | os.PathLike):
    """The data of the YAML file ``path``: from the memo when the file has not changed, else parsed (and kept). Raises
    OSError when it cannot be read, yaml.YAMLError when it is not YAML; neither is kept."""
    p = os.fspath(path)
    st = os.stat(p)
    key = os.path.normcase(os.path.abspath(p))
    hit = _memo.get(key) if _on() else None
    text = None
    if hit and hit[0] == st.st_size and hit[1] == st.st_mtime_ns:
        if hit[2] - st.st_mtime_ns > RACY_NS:
            stats["hits"] += 1
            return pickle.loads(hit[4])
        text = Path(p).read_text(encoding="utf-8")
        if hashlib.blake2b(text.encode("utf-8"), digest_size=16).digest() == hit[3]:
            stats["hits"] += 1
            return pickle.loads(hit[4])
    stats["misses"] += 1
    read_at = time.time_ns()
    if text is None:
        text = Path(p).read_text(encoding="utf-8")
    data = loads(text)
    if _on():
        try:
            blob = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
        except (pickle.PicklingError, TypeError, RecursionError):
            return data
        if len(_memo) >= MAX_ENTRIES:
            _memo.pop(next(iter(_memo)))
        _memo[key] = (st.st_size, st.st_mtime_ns, read_at,
                      hashlib.blake2b(text.encode("utf-8"), digest_size=16).digest(), blob)
    return data


def clear() -> None:
    _memo.clear()
    stats.update(hits=0, misses=0)
