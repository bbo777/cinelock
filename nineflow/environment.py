from __future__ import annotations

import platform
import shutil
from typing import Any, Dict

from .adapters.quota_flow import NODE_MIN_MAJOR, _cli_node, _needs_node, _node_major, _resolve_cli
from .context import ProjectContext


def environment_report(ctx: ProjectContext) -> Dict[str, Any]:
    cli, notes = _resolve_cli()
    needs_node = _needs_node(cli) if cli else False
    node_path = _cli_node(cli) if cli else None
    node_major = _node_major(node_path) if needs_node else None
    node_ok = bool(node_major) and node_major >= NODE_MIN_MAJOR
    quota_flow_ready = bool(cli) and (not needs_node or node_ok)
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "project_root": str(ctx.root),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "quota_flow_found": bool(cli),
        "quota_flow_cli": " ".join(cli) if cli else None,
        "quota_flow_node": node_path,
        "quota_flow_notes": notes,
        "quota_flow_ready": quota_flow_ready,
        "node_version": node_major,
        "node_min_major": NODE_MIN_MAJOR,
        "node_ok": node_ok,
    }
