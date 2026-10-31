from __future__ import annotations

from typing import Any, Dict, List

from .context import ProjectContext
from .context_pack import load_pack, pack_is_current
from .environment import environment_report
from .jobs import ledger_size, list_jobs
from .util import short_hash
from .validate import validate_context


def _character_entries(ctx: ProjectContext) -> List[Dict[str, Any]]:
    entries = []
    for card in ctx.character_list():
        cid = card.get("character_id")
        if not cid:
            continue
        wardrobe = card.get("wardrobe_states") or {}
        entries.append(
            {
                "character_id": cid,
                "name": card.get("name"),
                "name_en": card.get("name_en"),
                "role": card.get("role"),
                "status": card.get("status"),
                "is_placeholder": bool(card.get("is_placeholder")),
                "invariants_en": list(card.get("invariants_en") or []),
                "wardrobe_labels": {
                    key: (value or {}).get("label") for key, value in wardrobe.items()
                },
            }
        )
    return entries


def _enrich_shots(ctx: ProjectContext, pack: Dict[str, Any]) -> List[Dict[str, Any]]:
    shots = []
    for shot in pack.get("shots") or []:
        item = dict(shot)
        source = ctx.shot(str(shot.get("shot_id"))) or {}
        for key in ("action_zh", "dialogue", "sfx", "risk_level"):
            if key in source:
                item[key] = source[key]
        snapshot = shot.get("snapshot") or {}
        scene = snapshot.get("scene") or {}
        item["scene_label"] = scene.get("label")
        item["scene_time_of_day"] = scene.get("time_of_day")
        item["scene_location_en"] = scene.get("location_en")
        shots.append(item)
    return shots


def status_payload(ctx: ProjectContext, job_limit: int = 20) -> Dict[str, Any]:
    revision = ctx.context_revision()
    validation = validate_context(ctx)
    pack = load_pack(ctx)
    pack_info: Dict[str, Any] = {
        "present": bool(pack),
        "current": pack_is_current(ctx, pack),
        "path": str(ctx.root / "context" / "context_pack.json"),
    }
    if pack:
        pack_info.update(
            {
                "context_revision": pack.get("context_revision"),
                "short_revision": pack.get("short_revision"),
                "generated_at": pack.get("generated_at"),
                "stats": pack.get("stats"),
                "validation": pack.get("validation"),
                "providers": pack.get("providers") or [],
                "shots": _enrich_shots(ctx, pack),
                "style": pack.get("style"),
                "format": pack.get("format"),
            }
        )
    return {
        "project": {
            "project_id": ctx.project_id,
            "title": ctx.title,
            "subtitle": ctx.project.get("subtitle"),
            "episode_id": ctx.timeline.get("episode_id"),
            "episode_title": ctx.timeline.get("title"),
            "status": ctx.project.get("status"),
            "logline": (ctx.project.get("world") or {}).get("logline"),
            "setting": (ctx.project.get("world") or {}).get("setting"),
        },
        "revision": revision,
        "short_revision": short_hash(revision),
        "validation": validation.to_dict(),
        "pack": pack_info,
        "characters": _character_entries(ctx),
        "environment": environment_report(ctx),
        "jobs": list_jobs(ctx, limit=job_limit),
        "jobs_ledger_bytes": ledger_size(ctx),
    }
