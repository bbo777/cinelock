from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..util import display_path, sha256_file


@dataclass
class AdapterOutcome:
    status: str
    outputs: List[Dict[str, Any]] = field(default_factory=list)
    command: List[str] = field(default_factory=list)
    plan: List[str] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


def file_output(path: Path, kind: str, root: Path, **extra: Any) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "kind": kind,
        "path": display_path(path, root),
        "bytes": path.stat().st_size if path.is_file() else 0,
        "sha256": sha256_file(path) if path.is_file() else "",
    }
    entry.update(extra)
    return entry


def remote_output(url: str, kind: str = "remote_video", **extra: Any) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"kind": kind, "url": url}
    entry.update(extra)
    return entry


def tool_path(name: str) -> Optional[str]:
    return shutil.which(name)


def tail(text: str, limit: int = 4000) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return "…" + text[-limit:]


def decode_output(data: bytes) -> str:
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("gbk")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")
