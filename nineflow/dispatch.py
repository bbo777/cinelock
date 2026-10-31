from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .adapters import mock, handoff, quota_flow
from .adapters.common import AdapterOutcome, tail
from .context import ProjectContext
from .context_pack import PackError, get_variant, load_pack, pack_is_current
from .jobs import create_job, update_job


class DispatchError(Exception):
    pass


def _adapter_outcome(
    adapter: str,
    ctx: ProjectContext,
    variant: Dict[str, Any],
    job_id: str,
    dry_run: bool,
) -> AdapterOutcome:
    if adapter == "mock":
        return mock.run(ctx, variant, job_id, dry_run=dry_run)
    if adapter == "handoff":
        return handoff.run(ctx, variant, job_id, dry_run=dry_run)
    if adapter == "quota_flow":
        return quota_flow.run(ctx, variant, job_id, dry_run=dry_run)
    raise DispatchError("未知适配器：%s" % adapter)


def execute(
    ctx: ProjectContext,
    shot_id: str,
    provider_id: str,
    *,
    dry_run: bool = False,
    pack: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if pack is None:
        try:
            pack = load_pack(ctx)
        except PackError as exc:
            raise DispatchError(str(exc))
        if pack is None:
            raise DispatchError("还没有 Context Pack；先运行 build 再执行")
    if not pack_is_current(ctx, pack):
        raise DispatchError(
            "上下文已变化：当前修订 %s，包内修订 %s。先重新 build，避免把旧提示词发给新上下文。"
            % (ctx.context_revision()[:12], str(pack.get("short_revision") or "?"))
        )
    variant = get_variant(pack, shot_id, provider_id)
    if variant is None:
        raise DispatchError(
            "Context Pack 中没有 %s × %s 的编译结果；检查 provider 是否参与本次 build" % (shot_id, provider_id)
        )

    adapter = str((variant.get("dispatch") or {}).get("adapter") or "manual")
    job = create_job(ctx, variant, dry_run=dry_run, adapter=adapter)

    blockers = variant.get("blockers") or []
    if blockers:
        error = "；".join(str(item.get("message") or item.get("code")) for item in blockers)
        update_job(ctx, job, status="blocked", error=error, message="编译阶段存在阻断项")
        return job
    if not dry_run and not (variant.get("dispatch") or {}).get("ready"):
        reasons = (variant.get("dispatch") or {}).get("block_reasons") or ["执行前置条件未满足"]
        update_job(ctx, job, status="blocked", error="；".join(str(x) for x in reasons), message="前置条件未满足")
        return job

    update_job(ctx, job, status="running", message="开始执行 %s" % adapter)
    started = time.monotonic()
    try:
        outcome = _adapter_outcome(adapter, ctx, variant, str(job["job_id"]), dry_run)
    except Exception as exc:
        update_job(
            ctx,
            job,
            status="failed",
            error=str(exc),
            duration_ms=int((time.monotonic() - started) * 1000),
            message="适配器异常",
        )
        return job

    duration_ms = int((time.monotonic() - started) * 1000)
    message = {
        "succeeded": "执行成功",
        "failed": "执行失败",
        "blocked": "执行被阻断",
        "dry_run": "演练完成（未调用厂商）",
    }.get(outcome.status, "执行结束：%s" % outcome.status)
    fields: Dict[str, Any] = {
        "outputs": outcome.outputs,
        "command": outcome.command,
        "plan": outcome.plan,
        "stdout_tail": tail(outcome.stdout),
        "stderr_tail": tail(outcome.stderr),
        "adapter_meta": outcome.meta,
        "duration_ms": duration_ms,
    }
    if outcome.error:
        fields["error"] = outcome.error
    update_job(
        ctx,
        job,
        status=outcome.status,
        message=message,
        append_warnings=outcome.warnings,
        **fields
    )
    return job


def execute_many(
    ctx: ProjectContext,
    *,
    shot_ids: Optional[List[str]] = None,
    provider_ids: Optional[List[str]] = None,
    dry_run: bool = False,
    stop_on_error: bool = False,
    pack: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    if pack is None:
        try:
            pack = load_pack(ctx)
        except PackError as exc:
            raise DispatchError(str(exc))
        if pack is None:
            raise DispatchError("还没有 Context Pack；先运行 build 再执行")
    if not pack_is_current(ctx, pack):
        raise DispatchError(
            "上下文已变化：当前修订 %s，包内修订 %s。先重新 build。"
            % (ctx.context_revision()[:12], str(pack.get("short_revision") or "?"))
        )
    shots = set(shot_ids) if shot_ids else None
    providers = set(provider_ids) if provider_ids else None
    selected = []
    for variant in pack.get("variants") or []:
        if shots is not None and variant.get("shot_id") not in shots:
            continue
        if providers is not None and variant.get("provider_id") not in providers:
            continue
        selected.append(variant)
    if not selected:
        raise DispatchError("没有匹配的编译变体；检查 shot/provider 过滤条件")

    jobs = []
    for variant in selected:
        job = execute(
            ctx,
            str(variant.get("shot_id")),
            str(variant.get("provider_id")),
            dry_run=dry_run,
            pack=pack,
        )
        jobs.append(job)
        if stop_on_error and job.get("status") in ("failed", "blocked"):
            break
    return jobs
