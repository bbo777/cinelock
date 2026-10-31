from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .context import ProjectContext
from .util import read_json, sha256_json, utc_now, write_json

JOB_SCHEMA_VERSION = "1.1"
JOB_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,120}$")
FINAL_STATUSES = {"succeeded", "failed", "blocked", "dry_run", "canceled"}


class JobError(Exception):
    pass


def jobs_dir(ctx: ProjectContext) -> Path:
    return ctx.root / "jobs"


def ledger_path(ctx: ProjectContext) -> Path:
    return jobs_dir(ctx) / "jobs.jsonl"


def outputs_dir(ctx: ProjectContext) -> Path:
    return ctx.root / "outputs"


def exports_dir(ctx: ProjectContext) -> Path:
    return ctx.root / "exports"


def job_path(ctx: ProjectContext, job_id: str) -> Path:
    if not JOB_ID_RE.match(job_id or ""):
        raise JobError("非法 job_id：%s" % job_id)
    return jobs_dir(ctx) / ("%s.json" % job_id)


def _slug(value: Any, limit: int = 24) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "-", str(value or "")).strip("-")
    return (text or "x")[:limit]


def new_job_id(shot_id: str, provider_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return "JOB_%s_%s_%s_%s" % (stamp, _slug(shot_id), _slug(provider_id), secrets.token_hex(3))


def _reference_snapshot(variant: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for ref in variant.get("references") or []:
        out.append(
            {
                "order": ref.get("order"),
                "asset_id": ref.get("asset_id"),
                "role": ref.get("role"),
                "label": ref.get("label"),
                "kind": ref.get("kind"),
                "character_id": ref.get("character_id"),
                "scene_id": ref.get("scene_id"),
                "wardrobe_state": ref.get("wardrobe_state"),
                "expression": ref.get("expression"),
                "path": ref.get("path"),
                "sha256": ref.get("sha256"),
                "public_url": ref.get("public_url"),
            }
        )
    return out


def create_job(ctx: ProjectContext, variant: Dict[str, Any], *, dry_run: bool, adapter: str) -> Dict[str, Any]:
    job_id = new_job_id(str(variant.get("shot_id") or ""), str(variant.get("provider_id") or ""))
    now = utc_now()
    provider = variant.get("provider") or {}
    snapshot = variant.get("continuity") or {}
    source_hashes = ctx.source_hashes()
    job = {
        "schema_version": JOB_SCHEMA_VERSION,
        "job_id": job_id,
        "project_id": ctx.project_id,
        "shot_id": variant.get("shot_id"),
        "provider_id": variant.get("provider_id"),
        "provider_display_name": provider.get("display_name"),
        "adapter": adapter,
        "mode": variant.get("mode"),
        "mode_label": variant.get("mode_label"),
        "status": "queued",
        "dry_run": bool(dry_run),
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "context_revision": variant.get("context_revision"),
        "short_revision": variant.get("short_revision"),
        "variant_sha256": variant.get("variant_sha256"),
        "prompt_sha256": variant.get("prompt_sha256"),
        "negative_sha256": variant.get("negative_sha256"),
        "prompt": variant.get("prompt"),
        "negative_prompt": variant.get("negative_prompt"),
        "references": _reference_snapshot(variant),
        "render": {
            "provider_id": variant.get("provider_id"),
            "provider_display_name": provider.get("display_name"),
            "mode": variant.get("mode"),
            "mode_label": variant.get("mode_label"),
            "duration_sec": variant.get("duration_sec"),
            "requested_duration_sec": variant.get("requested_duration_sec"),
            "duration_choice": variant.get("duration_choice"),
            "aspect_ratio": variant.get("aspect_ratio"),
            "resolution": variant.get("resolution"),
            "fps": variant.get("fps"),
            "seed": variant.get("seed"),
            "candidate_index": variant.get("candidate_index"),
        },
        "dispatch": variant.get("dispatch") or {},
        "projection": {
            "mode": variant.get("mode"),
            "max_refs": provider.get("max_refs"),
            "selected_refs": len(variant.get("references") or []),
            "dropped_references": variant.get("dropped_references") or [],
        },
        "provenance": {
            "schema_version": "1.0",
            "captured_at": now,
            "context_revision": variant.get("context_revision"),
            "source_hashes": source_hashes,
            "source_hashes_sha256": sha256_json(source_hashes),
            "context_snapshot": snapshot,
            "context_snapshot_sha256": sha256_json(snapshot),
            "engine": ctx.engine_fingerprint(),
        },
        "variant_warnings": variant.get("warnings") or [],
        "variant_blockers": variant.get("blockers") or [],
        "command": [],
        "plan": [],
        "outputs": [],
        "stdout_tail": "",
        "stderr_tail": "",
        "warnings": [],
        "error": None,
        "events": [{"at": now, "status": "queued", "message": "任务已创建"}],
    }
    save_job(ctx, job)
    append_ledger(ctx, job, "queued")
    return job


def save_job(ctx: ProjectContext, job: Dict[str, Any]) -> None:
    path = job_path(ctx, str(job.get("job_id") or ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, job)


def append_ledger(ctx: ProjectContext, job: Dict[str, Any], event: str) -> None:
    path = ledger_path(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": utc_now(),
        "event": event,
        "job_id": job.get("job_id"),
        "status": job.get("status"),
        "shot_id": job.get("shot_id"),
        "provider_id": job.get("provider_id"),
        "adapter": job.get("adapter"),
        "dry_run": job.get("dry_run"),
        "context_revision": job.get("context_revision"),
        "error": job.get("error"),
    }
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def update_job(
    ctx: ProjectContext,
    job: Dict[str, Any],
    *,
    status: Optional[str] = None,
    message: Optional[str] = None,
    append_warnings: Optional[List[str]] = None,
    **fields: Any,
) -> Dict[str, Any]:
    for key, value in fields.items():
        job[key] = value
    if append_warnings:
        existing = list(job.get("warnings") or [])
        for item in append_warnings:
            if item and item not in existing:
                existing.append(item)
        job["warnings"] = existing
    now = utc_now()
    if status:
        job["status"] = status
        if status == "running" and not job.get("started_at"):
            job["started_at"] = now
        if status in FINAL_STATUSES:
            job["finished_at"] = now
        event = {"at": now, "status": status}
        if message:
            event["message"] = message
        job.setdefault("events", []).append(event)
    elif message:
        job.setdefault("events", []).append({"at": now, "status": job.get("status"), "message": message})
    save_job(ctx, job)
    if status:
        append_ledger(ctx, job, status)
    return job


def load_job(ctx: ProjectContext, job_id: str) -> Dict[str, Any]:
    path = job_path(ctx, job_id)
    if not path.is_file():
        raise JobError("任务不存在：%s" % job_id)
    try:
        data = read_json(path)
    except Exception as exc:
        raise JobError("任务记录不是合法 JSON：%s（%s）" % (path, exc))
    if not isinstance(data, dict):
        raise JobError("任务记录格式非法：%s" % path)
    return data


def summarize_job(job: Dict[str, Any]) -> Dict[str, Any]:
    outputs = job.get("outputs") or []
    local = [o for o in outputs if o.get("path")]
    return {
        "job_id": job.get("job_id"),
        "shot_id": job.get("shot_id"),
        "provider_id": job.get("provider_id"),
        "provider_display_name": job.get("provider_display_name"),
        "adapter": job.get("adapter"),
        "mode": job.get("mode"),
        "mode_label": job.get("mode_label"),
        "status": job.get("status"),
        "dry_run": job.get("dry_run"),
        "created_at": job.get("created_at"),
        "finished_at": job.get("finished_at"),
        "duration_ms": job.get("duration_ms"),
        "short_revision": job.get("short_revision"),
        "short_prompt_hash": (job.get("prompt_sha256") or "")[:12],
        "has_provenance": bool(job.get("provenance")),
        "dropped_reference_count": len((job.get("projection") or {}).get("dropped_references") or []),
        "output_count": len(outputs),
        "local_output_count": len(local),
        "warning_count": len(job.get("warnings") or []) + len(job.get("variant_warnings") or []),
        "error": job.get("error"),
    }


def list_jobs(
    ctx: ProjectContext,
    limit: int = 100,
    *,
    shot_id: Optional[str] = None,
    provider_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    folder = jobs_dir(ctx)
    if not folder.is_dir():
        return []
    records = []
    for path in folder.glob("*.json"):
        if not path.is_file():
            continue
        try:
            data = read_json(path)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if shot_id and data.get("shot_id") != shot_id:
            continue
        if provider_id and data.get("provider_id") != provider_id:
            continue
        records.append(data)
    records.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    if limit and limit > 0:
        records = records[:limit]
    return [summarize_job(item) for item in records]


def job_output_path(job: Dict[str, Any], kind: str) -> Optional[str]:
    for output in job.get("outputs") or []:
        if output.get("kind") == kind and output.get("path"):
            return output["path"]
    return None


def resolve_job_output(ctx: ProjectContext, job: Dict[str, Any], kind: str) -> Optional[Path]:
    rel = job_output_path(job, kind)
    if not rel:
        return None
    path = (ctx.root / rel).resolve()
    try:
        path.relative_to(ctx.root)
    except ValueError:
        return None
    return path if path.is_file() else None


def ledger_size(ctx: ProjectContext) -> int:
    path = ledger_path(ctx)
    if not path.is_file():
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0
