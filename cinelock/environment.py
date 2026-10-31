from __future__ import annotations

import os
import platform
import shutil
from typing import Any, Dict

from .adapters import adapter_names
from .context import ProjectContext


def _env_status(profile: Dict[str, Any]) -> Dict[str, Any]:
    names = []
    for key in ("api_key_env", "access_key_env", "secret_key_env"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            names.append(value.strip())
    for name in profile.get("requires_env") or []:
        if isinstance(name, str) and name.strip() and name.strip() not in names:
            names.append(name.strip())
    if not names:
        return {"configured": None, "env": []}
    return {
        "configured": all(bool(os.environ.get(name)) for name in names),
        "env": names,
        "missing": [name for name in names if not os.environ.get(name)],
    }


def environment_report(ctx: ProjectContext) -> Dict[str, Any]:
    profiles = ctx.provider_profiles()
    providers = []
    for provider_id in ctx.provider_order():
        profile = profiles.get(provider_id) or {}
        item: Dict[str, Any] = {
            "provider_id": provider_id,
            "adapter": profile.get("adapter"),
            "preset": profile.get("preset"),
            "enabled": bool(profile.get("enabled", True)),
            "experimental": bool(profile.get("experimental")),
            "base_url": profile.get("base_url"),
        }
        item.update(_env_status(profile))
        providers.append(item)

    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "project_root": str(ctx.root),
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "ffprobe": bool(shutil.which("ffprobe")),
        "node_required": False,
        "adapters": adapter_names(),
        "providers": providers,
    }
