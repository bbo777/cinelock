from __future__ import annotations

from typing import Any, Dict, List

from . import comfyui, handoff, http_api, mock
from .common import AdapterOutcome, AdapterRequest

ADAPTERS = {
    "mock": mock,
    "handoff": handoff,
    "comfyui": comfyui,
    "http_api": http_api,
}


class AdapterNotFound(Exception):
    pass


def get_adapter(name: str):
    module = ADAPTERS.get(str(name or ""))
    if module is None:
        raise AdapterNotFound("未知适配器：%s（可用：%s）" % (name, ", ".join(sorted(ADAPTERS))))
    return module


def adapter_names() -> List[str]:
    return sorted(ADAPTERS)


__all__ = ["AdapterOutcome", "AdapterRequest", "AdapterNotFound", "ADAPTERS", "adapter_names", "get_adapter"]
