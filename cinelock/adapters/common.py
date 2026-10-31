from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..util import display_path, resolve_within, sha256_file


@dataclass
class AdapterRequest:
    """Everything an adapter is allowed to know about a generation.

    The engine compiles the Context Pack first; adapters never read project
    JSON directly. This keeps the provider projection auditable and lets new
    adapters be added without touching the compiler.
    """

    job_id: str
    project_root: Path
    project_id: str
    output_dir: Path
    exports_dir: Path
    variant: Dict[str, Any]
    config_dir: Optional[Path] = None
    context_pack_path: Optional[Path] = None
    options: Dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False

    @property
    def prompt(self) -> str:
        return str(self.variant.get("prompt") or "")

    @property
    def negative_prompt(self) -> str:
        return str(self.variant.get("negative_prompt") or "")

    @property
    def duration_sec(self) -> float:
        return float(self.variant.get("duration_sec") or 0)

    @property
    def seed(self) -> Optional[int]:
        value = self.variant.get("seed")
        return int(value) if isinstance(value, int) else None

    @property
    def provider(self) -> Dict[str, Any]:
        return dict(self.variant.get("provider") or {})

    @property
    def references(self) -> List[Dict[str, Any]]:
        return list(self.variant.get("references") or [])

    def reference_files(self) -> List[Dict[str, Any]]:
        resolved = []
        for ref in self.references:
            item = dict(ref)
            rel = str(ref.get("path") or "")
            item["source_path"] = rel
            if rel:
                try:
                    item["file_path"] = resolve_within(self.project_root, rel)
                except (ValueError, OSError):
                    item["file_path"] = None
            else:
                item["file_path"] = None
            resolved.append(item)
        return resolved

    def option(self, key: str, default: Any = None) -> Any:
        if key in self.options and self.options[key] not in (None, ""):
            return self.options[key]
        return self.provider.get(key, default)

    @classmethod
    def from_context(
        cls,
        ctx: Any,
        variant: Dict[str, Any],
        job_id: str,
        *,
        context_pack_path: Optional[Path] = None,
        options: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> "AdapterRequest":
        return cls(
            job_id=job_id,
            project_root=ctx.root,
            project_id=ctx.project_id,
            output_dir=ctx.root / "outputs",
            exports_dir=ctx.root / "exports",
            variant=variant,
            config_dir=ctx.config_dir,
            context_pack_path=context_pack_path,
            options=dict(options or {}),
            dry_run=dry_run,
        )


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
        "origin": "local",
    }
    entry.update(extra)
    return entry


def remote_output(url: str, kind: str = "remote_video", **extra: Any) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"kind": kind, "url": url, "origin": "remote"}
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


def json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")
