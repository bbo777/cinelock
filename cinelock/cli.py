from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .audit import STATUS_LABELS as AUDIT_STATUS_LABELS, audit_job
from .context import ContextError, ProjectContext, load_context
from .context_pack import (
    PackError,
    STATUS_LABELS,
    build_pack,
    load_pack,
    pack_is_current,
    variant_status,
)
from .dispatch import DispatchError, execute_many
from .hashes import HashRefreshError, refresh_reference_hashes
from .jobs import JobError, list_jobs, load_job, summarize_job
from .media import MediaError, create_contact_sheet
from .report import status_payload
from .util import display_path, resolve_within, short_hash
from .validate import validate_context


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


# ---------- table helpers (CJK aware) ----------


def _display_width(text: Any) -> int:
    width = 0
    for ch in str(text):
        if unicodedata.combining(ch):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def _pad(text: Any, width: int, align: str = "left") -> str:
    text = str(text)
    gap = max(0, width - _display_width(text))
    return (" " * gap + text) if align == "right" else (text + " " * gap)


def _table(headers: Sequence[str], rows: Sequence[Sequence[Any]], aligns: Optional[Sequence[str]] = None) -> str:
    aligns = list(aligns or ["left"] * len(headers))
    widths = []
    for index, header in enumerate(headers):
        widths.append(max([_display_width(header)] + [_display_width(row[index]) for row in rows]))
    lines = ["  ".join(_pad(header, widths[i]) for i, header in enumerate(headers))]
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        lines.append("  ".join(_pad(cell, widths[i], aligns[i]) for i, cell in enumerate(row)))
    return "\n".join(lines)


def _format_bytes(size: Any) -> str:
    try:
        value = float(size or 0)
    except (TypeError, ValueError):
        return "?"
    if value >= 1024 * 1024:
        return "%.1f MB" % (value / (1024 * 1024))
    if value >= 1024:
        return "%.1f KB" % (value / 1024)
    return "%d B" % int(value)


AUDIT_JOB_STATUS_LABELS = {
    "succeeded": "成功",
    "failed": "失败",
    "blocked": "阻断",
    "dry_run": "演练",
    "running": "执行中",
    "canceled": "取消",
    "unknown": "未知",
}


def _status_counts(statuses: Dict[str, int]) -> str:
    order = ["ready", "warning", "needs_public_url", "not_ready", "blocked"]
    parts = []
    for key in order:
        if statuses.get(key):
            parts.append("%s %d" % (STATUS_LABELS.get(key, key), statuses[key]))
    return " · ".join(parts) or "无"


def _shot_summary(ctx: ProjectContext, shot: Dict[str, Any]) -> str:
    snapshot = shot.get("snapshot") or {}
    bits = []
    for cid, state in (snapshot.get("characters") or {}).items():
        card = ctx.character(cid) or {}
        name = card.get("name") or cid
        parts = [str(state.get("wardrobe_state") or "?")]
        injuries = list(state.get("injuries") or [])
        if injuries:
            parts.append("伤：" + "、".join(injuries))
        props = list(state.get("props") or [])
        if props:
            parts.append("道具：" + "、".join(str(p) for p in props))
        bits.append("%s %s" % (name, " · ".join(parts)))
    return " / ".join(bits) or "—"


# ---------- commands ----------


def cmd_validate(args: argparse.Namespace, ctx: ProjectContext) -> int:
    result = validate_context(ctx)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if result.ok else 2
    print("上下文校验 · %s" % ctx.title)
    print("修订 %s · %d 错误 · %d 警告" % (short_hash(ctx.context_revision()), len(result.errors), len(result.warnings)))
    for label, issues in (("错误", result.errors), ("警告", result.warnings)):
        if not issues:
            continue
        print("\n%s：" % label)
        for issue in issues:
            where = (" @ " + issue.where) if issue.where else ""
            print("  [%s]%s %s" % (issue.code, where, issue.message))
    return 0 if result.ok else 2


def cmd_build(args: argparse.Namespace, ctx: ProjectContext) -> int:
    partial = bool(args.provider)
    try:
        pack = build_pack(ctx, args.provider or None, write=not partial)
    except PackError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(
            json.dumps(
                {
                    "context_revision": pack.get("context_revision"),
                    "short_revision": pack.get("short_revision"),
                    "generated_at": pack.get("generated_at"),
                    "stats": pack.get("stats"),
                    "validation": pack.get("validation"),
                    "partial": partial,
                    "written": not partial,
                    "pack_path": None if partial else str(ctx.root / "context" / "context_pack.json"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    stats = pack.get("stats") or {}
    if partial:
        print("部分编译预览（未写入共享 Context Pack）")
    else:
        print("Context Pack 已生成")
    print("修订 %s · %s" % (pack.get("short_revision"), pack.get("context_revision")))
    print(
        "%d 镜头 × %d 厂商 = %d 变体 · %d 参考图 · %s"
        % (
            stats.get("shot_count", 0),
            stats.get("provider_count", 0),
            stats.get("variant_count", 0),
            stats.get("total_references", 0),
            _status_counts(stats.get("statuses") or {}),
        )
    )
    if partial:
        print("共享包未改变；全量构建请去掉 --provider。")
    else:
        print("输出 %s" % (ctx.root / "context" / "context_pack.json"))
    return 0


def cmd_refresh_hashes(args: argparse.Namespace, ctx: ProjectContext) -> int:
    try:
        report = refresh_reference_hashes(ctx)
    except HashRefreshError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        else:
            print("刷新失败：%s" % exc, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    updated = report.get("updated") or []
    print("参考图哈希已刷新 · 更新 %d · 未变化 %d" % (len(updated), report.get("unchanged", 0)))
    for item in updated:
        print("  %s  %s → %s" % (item["asset_id"], short_hash(str(item.get("old") or "")), short_hash(item["new"])))
    print("修订 %s（刷新记录哈希不会改变 context_revision）" % report.get("short_revision"))
    print("下一步：python studio.py build")
    return 0


def cmd_status(args: argparse.Namespace, ctx: ProjectContext) -> int:
    payload = status_payload(ctx)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    project = payload["project"]
    pack = payload["pack"]
    print("%s · %s" % (project["title"], project.get("episode_id") or ""))
    print("项目 %s · 当前修订 %s" % (project["project_id"], payload["short_revision"]))
    if not pack.get("present"):
        print("Context Pack 尚未构建；运行 `python studio.py build`")
    else:
        if pack.get("current"):
            print("Context Pack 最新 · 生成于 %s · 修订 %s" % (pack.get("generated_at"), pack.get("short_revision")))
        else:
            print(
                "Context Pack 已过期：包内 %s，当前 %s；先运行 build"
                % (pack.get("short_revision") or "?", payload["short_revision"])
            )
        stats = pack.get("stats") or {}
        print(
            "%d 镜头 × %d 厂商 = %d 变体 · %d 参考图"
            % (
                stats.get("shot_count", 0),
                stats.get("provider_count", 0),
                stats.get("variant_count", 0),
                stats.get("total_references", 0),
            )
        )
        print("状态 %s" % _status_counts(stats.get("statuses") or {}))
        print("")

        provider_rows = []
        for provider in pack.get("providers") or []:
            stats_by_provider = (stats.get("providers") or {}).get(provider.get("id")) or {}
            provider_rows.append(
                [
                    provider.get("id"),
                    provider.get("display_name"),
                    provider.get("kind"),
                    " / ".join(provider.get("modes") or []),
                    provider.get("max_refs"),
                    _status_counts(stats_by_provider.get("statuses") or {}),
                ]
            )
        print(_table(["厂商", "名称", "类型", "支持模式", "参考上限", "变体状态"], provider_rows))

        print("")
        shot_rows = []
        for shot in pack.get("shots") or []:
            statuses: Dict[str, int] = {}
            for variant in shot.get("variants") or []:
                status = variant.get("status")
                statuses[status] = statuses.get(status, 0) + 1
            shot_rows.append(
                [
                    shot.get("shot_id"),
                    shot.get("scene_id"),
                    "%ss" % shot.get("duration_sec"),
                    _status_counts(statuses),
                    _shot_summary(ctx, shot),
                ]
            )
        print(_table(["镜头", "场景", "时长", "变体状态", "角色状态"], shot_rows))

    env = payload["environment"]
    qf = "可用" if env.get("quota_flow_ready") else ("已安装但环境不满足" if env.get("quota_flow_found") else "未安装")
    node = env.get("node_version")
    print("")
    print(
        "环境 Python %s · ffmpeg %s · Node %s（需 ≥%s）· Quota-Flow %s"
        % (
            env.get("python"),
            "可用" if env.get("ffmpeg") else "缺失",
            node if node else "缺失",
            env.get("node_min_major"),
            qf,
        )
    )
    if not pack.get("current"):
        print("提示：build 之后所有厂商会共用同一个 context_revision；修改角色/参考图/时间线都会生成新修订。")
    return 0


def _variant_text(ctx: ProjectContext, variant: Dict[str, Any], *, prompt: bool) -> str:
    refs = variant.get("references") or []
    lines = [
        "%s × %s · %s · %ss · %s"
        % (
            variant.get("shot_id"),
            variant.get("provider_id"),
            variant.get("mode_label") or variant.get("mode"),
            variant.get("duration_sec"),
            STATUS_LABELS.get(variant_status(variant), variant_status(variant)),
        ),
        "提示词 %s（%s 字符）· 参考图 %d 张"
        % (short_hash(str(variant.get("prompt_sha256") or "")), variant.get("prompt_chars"), len(refs)),
        "修订 %s" % variant.get("short_revision"),
    ]
    if refs:
        lines.append("")
        lines.append(
            _table(
                ["序", "asset_id", "角色", "用途"],
                [[ref.get("order"), ref.get("asset_id"), ref.get("role"), ref.get("label")] for ref in refs],
            )
        )
    warnings = variant.get("warnings") or []
    blockers = variant.get("blockers") or []
    if warnings:
        lines.append("")
        lines.append("警告：")
        lines.extend("  - %s" % item for item in warnings)
    if blockers:
        lines.append("")
        lines.append("阻断：")
        lines.extend("  - %s" % (item.get("message") or item) for item in blockers)
    if prompt:
        lines.append("")
        lines.append(str(variant.get("prompt") or ""))
        if variant.get("negative_prompt"):
            lines.append("")
            lines.append("[negative]")
            lines.append(str(variant.get("negative_prompt")))
    return "\n".join(lines)


def cmd_compile(args: argparse.Namespace, ctx: ProjectContext) -> int:
    pack = load_pack(ctx)
    if pack is None:
        print("还没有 Context Pack；先运行 `python studio.py build`", file=sys.stderr)
        return 2
    if not pack_is_current(ctx, pack):
        print(
            "上下文已变化：包内 %s，当前 %s；先重新 build"
            % (pack.get("short_revision"), short_hash(ctx.context_revision())),
            file=sys.stderr,
        )
        return 2
    variants = [
        variant
        for variant in pack.get("variants") or []
        if variant.get("shot_id") == args.shot and (not args.provider or variant.get("provider_id") == args.provider)
    ]
    if not variants:
        print("没有匹配的编译结果：%s / %s" % (args.shot, args.provider or "全部厂商"), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(variants if len(variants) > 1 else variants[0], ensure_ascii=False, indent=2))
        return 0
    for index, variant in enumerate(variants):
        if index:
            print("")
        print(_variant_text(ctx, variant, prompt=args.prompt))
    return 0


def _selected_providers(args: argparse.Namespace, ctx: ProjectContext) -> Optional[List[str]]:
    if args.all_providers:
        return None
    if args.provider:
        return list(args.provider)
    default = (ctx.project.get("defaults") or {}).get("provider") or "mock"
    return [str(default)]


def _run_jobs(args: argparse.Namespace, ctx: ProjectContext, providers: Optional[List[str]]) -> int:
    try:
        jobs = execute_many(
            ctx,
            shot_ids=list(args.shot) if args.shot else None,
            provider_ids=providers,
            dry_run=bool(args.dry_run),
            stop_on_error=bool(getattr(args, "stop_on_error", False)),
        )
    except DispatchError as exc:
        print("执行被拒绝：%s" % exc, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(jobs, ensure_ascii=False, indent=2))
    else:
        for index, job in enumerate(jobs, 1):
            label = {
                "succeeded": "成功",
                "failed": "失败",
                "blocked": "阻断",
                "dry_run": "演练",
                "canceled": "取消",
            }.get(str(job.get("status")), str(job.get("status")))
            print(
                "[%d/%d] %s × %s → %s（%s）"
                % (
                    index,
                    len(jobs),
                    job.get("shot_id"),
                    job.get("provider_id"),
                    label,
                    ("%dms" % job["duration_ms"]) if job.get("duration_ms") is not None else "—",
                )
            )
            if job.get("error"):
                print("      %s" % job["error"])
            for output in job.get("outputs") or []:
                target = output.get("path") or output.get("url") or ""
                print(
                    "      %-9s %s%s"
                    % (
                        output.get("kind"),
                        target,
                        (" (%s)" % _format_bytes(output.get("bytes"))) if output.get("bytes") else "",
                    )
                )
            counts = summarize_job(job)
            if counts.get("warning_count"):
                print("      告警 %d 条；详情见任务记录" % counts["warning_count"])
        tally: Dict[str, int] = {}
        for job in jobs:
            tally[str(job.get("status"))] = tally.get(str(job.get("status")), 0) + 1
        print("")
        print(
            "完成 %d 个任务 · 成功 %d · 失败 %d · 阻断 %d · 演练 %d"
            % (
                len(jobs),
                tally.get("succeeded", 0),
                tally.get("failed", 0),
                tally.get("blocked", 0),
                tally.get("dry_run", 0),
            )
        )
    return 0 if all(job.get("status") not in ("failed", "blocked") for job in jobs) else 1


def cmd_run(args: argparse.Namespace, ctx: ProjectContext) -> int:
    return _run_jobs(args, ctx, _selected_providers(args, ctx))


def cmd_handoff(args: argparse.Namespace, ctx: ProjectContext) -> int:
    if not args.shot:
        print("handoff 需要至少一个 --shot", file=sys.stderr)
        return 2
    return _run_jobs(args, ctx, ["handoff"])


def cmd_jobs(args: argparse.Namespace, ctx: ProjectContext) -> int:
    records = list_jobs(
        ctx,
        limit=args.limit,
        shot_id=args.shot,
        provider_id=args.provider,
    )
    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0
    if not records:
        print("还没有任务记录")
        return 0
    rows = []
    for record in records:
        rows.append(
            [
                record.get("job_id"),
                record.get("shot_id"),
                record.get("provider_id"),
                record.get("status"),
                "是" if record.get("dry_run") else "否",
                record.get("created_at"),
                record.get("output_count"),
            ]
        )
    print(_table(["任务", "镜头", "厂商", "状态", "演练", "创建时间", "输出"], rows))
    return 0


def _job_text(ctx: ProjectContext, job: Dict[str, Any], *, prompt: bool) -> str:
    render = job.get("render") or {}
    lines = [
        "任务 %s" % job.get("job_id"),
        "%s × %s · %s · 适配器 %s"
        % (job.get("shot_id"), job.get("provider_id"), render.get("mode_label") or render.get("mode"), job.get("adapter")),
        "状态 %s · 演练 %s · 耗时 %s"
        % (
            job.get("status"),
            "是" if job.get("dry_run") else "否",
            "%dms" % job["duration_ms"] if job.get("duration_ms") is not None else "—",
        ),
        "修订 %s · 提示词 %s · 时长 %ss · Seed %s"
        % (
            job.get("short_revision"),
            short_hash(str(job.get("prompt_sha256") or "")),
            render.get("duration_sec"),
            render.get("seed"),
        ),
    ]
    refs = job.get("references") or []
    if refs:
        lines.append("")
        lines.append(
            _table(
                ["序", "asset_id", "用途"],
                [[ref.get("order"), ref.get("asset_id"), ref.get("role")] for ref in refs],
            )
        )
    outputs = job.get("outputs") or []
    if outputs:
        lines.append("")
        lines.append("输出：")
        for output in outputs:
            lines.append(
                "  %-9s %s%s"
                % (
                    output.get("kind"),
                    output.get("path") or output.get("url"),
                    (" (%s)" % _format_bytes(output.get("bytes"))) if output.get("bytes") else "",
                )
            )
    if job.get("command"):
        lines.append("")
        lines.append("命令：")
        lines.append("  " + " ".join(str(part) for part in job["command"]))
    warnings = job.get("warnings") or []
    if warnings:
        lines.append("")
        lines.append("警告：")
        lines.extend("  - %s" % item for item in warnings)
    if job.get("error"):
        lines.append("")
        lines.append("错误：%s" % job["error"])
    if prompt:
        lines.append("")
        lines.append(str(job.get("prompt") or ""))
        if job.get("negative_prompt"):
            lines.append("")
            lines.append("[negative]")
            lines.append(str(job.get("negative_prompt")))
    return "\n".join(lines)


def cmd_job(args: argparse.Namespace, ctx: ProjectContext) -> int:
    job = load_job(ctx, args.id)
    if args.json:
        print(json.dumps(job, ensure_ascii=False, indent=2))
        return 0
    print(_job_text(ctx, job, prompt=args.prompt))
    return 0


def cmd_contact_sheet(args: argparse.Namespace, ctx: ProjectContext) -> int:
    job = None
    if args.job:
        job = load_job(ctx, args.job)
        video_output = next(
            (
                item
                for item in job.get("outputs") or []
                if item.get("kind") == "video" and item.get("path")
            ),
            None,
        )
        if video_output is None:
            print("任务 %s 没有本地 video 输出，无法抽帧" % args.job, file=sys.stderr)
            return 2
        video_path = resolve_within(ctx.root, str(video_output["path"]))
        output_path = ctx.root / "outputs" / ("%s.contact_sheet.png" % args.job)
    else:
        candidate = Path(args.video).expanduser()
        video_path = candidate if candidate.is_absolute() else resolve_within(ctx.root, str(candidate))
        output_path = ctx.root / "outputs" / ("%s.contact_sheet.png" % video_path.stem)
    if not video_path.is_file():
        print("视频文件不存在：%s" % video_path, file=sys.stderr)
        return 2
    if args.out:
        candidate = Path(args.out).expanduser()
        output_path = candidate if candidate.is_absolute() else resolve_within(ctx.root, str(candidate))

    try:
        sheet = create_contact_sheet(video_path, output_path)
    except MediaError as exc:
        print("九宫格生成失败：%s" % exc, file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "job_id": args.job,
                    "video": display_path(video_path, ctx.root),
                    "output": display_path(output_path, ctx.root),
                    "bytes": sheet["bytes"],
                    "width": sheet["width"],
                    "height": sheet["height"],
                    "columns": sheet["columns"],
                    "rows": sheet["rows"],
                    "timestamps": sheet["timestamps"],
                    "probe": sheet["probe"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print("九宫格已生成 · %d×%d" % (sheet["width"], sheet["height"]))
    print("视频 %s" % display_path(video_path, ctx.root))
    print("输出 %s（%s）" % (display_path(output_path, ctx.root), _format_bytes(sheet["bytes"])))
    print("抽帧时刻 %s" % ", ".join("%.2fs" % value for value in sheet["timestamps"]))
    return 0


def cmd_audit(args: argparse.Namespace, ctx: ProjectContext) -> int:
    job = load_job(ctx, args.id)
    report = audit_job(ctx, job)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        counts = report["summary"]
        print("连续性审计 · %s" % report.get("job_id"))
        print(
            "%s × %s · 适配器 %s · 修订 %s · 当前 %s"
            % (
                report.get("shot_id"),
                report.get("provider_id"),
                report.get("adapter"),
                report.get("short_revision"),
                report.get("current_short_revision"),
            )
        )
        print(
            "证据链 %s · 任务 %s%s · 上下文 %s"
            % (
                AUDIT_STATUS_LABELS.get(report.get("artifact_status") or report["status"], report["status"]),
                AUDIT_JOB_STATUS_LABELS.get(report.get("job_status"), report.get("job_status") or "未知"),
                "（演练）" if report.get("dry_run") else "",
                {
                    "current": "当前修订",
                    "historical": "历史修订",
                    "unknown": "未知",
                }.get((report.get("verdict") or {}).get("current_context"), "未知"),
            )
        )
        print(
            "证据链结论 %s · 通过 %d · 警告 %d · 失败 %d · 跳过 %d"
            % (
                AUDIT_STATUS_LABELS.get(report["status"], report["status"]),
                counts.get("pass", 0),
                counts.get("warn", 0),
                counts.get("fail", 0),
                counts.get("skip", 0),
            )
        )
        print("")
        for check in report["checks"]:
            print(
                "[%s] %s"
                % (AUDIT_STATUS_LABELS.get(check["status"], check["status"]), check["label"])
            )
            print("       %s" % check["detail"])
        print("")
        if report["status"] == "fail":
            print("存在完整性失败：任务记录、参考图或产物与存证不一致。")
        elif report["legacy"]:
            print("旧任务缺少完整存证：已完成提示词、参考图与产物的离线核验；修订锁与快照重放不可用。")
        elif report["status"] == "warn":
            print("存证有效，但存在历史修订、引擎变化或厂商输入投影边界；见上方警告项。")
        else:
            print("存证、快照、输入与产物均通过离线一致性核验（仅代表证据链，不代表生成质量）。")
        if not (report.get("verdict") or {}).get("job_ok", False) and report["status"] != "fail":
            print(
                "注意：证据链通过不等于任务成功；任务状态为 %s。"
                % AUDIT_JOB_STATUS_LABELS.get(report.get("job_status"), report.get("job_status") or "未知")
            )
    return {"pass": 0, "warn": 1, "fail": 2}.get(report["status"], 2)


def cmd_providers(args: argparse.Namespace, ctx: ProjectContext) -> int:
    profiles = ctx.provider_profiles()
    rows = []
    for pid in ctx.provider_order():
        profile = profiles[pid]
        rows.append(
            [
                pid,
                profile.get("display_name"),
                profile.get("kind"),
                " / ".join(profile.get("modes") or []),
                profile.get("max_refs"),
                " / ".join(str(item) for item in profile.get("durations") or []),
                "是" if profile.get("supports_negative_prompt") else "否",
                "是" if profile.get("supports_seed") else "否",
            ]
        )
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    print(_table(["id", "名称", "类型", "支持模式", "参考上限", "时长", "负向词", "Seed"], rows))
    print("")
    print("模式：text2video 文生视频 / img2video 单图首帧 / multi_ref 多参考 / first_last 首尾帧")
    print("Quota-Flow CLI 本身不传时长与 seed；这两项由编译期决定并记录在任务里。")
    return 0


def cmd_serve(args: argparse.Namespace, ctx: ProjectContext) -> int:
    from .dashboard import serve

    return serve(
        project_dir=ctx.root,
        config_dir=ctx.config_dir,
        host=args.host,
        port=args.port,
        open_browser=not args.no_open,
    )


def cmd_mcp(args: argparse.Namespace, ctx: ProjectContext) -> int:
    from .mcp_server import serve

    return serve(ctx)


# ---------- parser ----------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="studio.py",
        description="CineLock · 多厂商共享上下文编排层（角色卡 / 参考图库 / 时间线）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
        "  python studio.py build\n"
        "  python studio.py refresh-hashes\n"
        "  python studio.py status\n"
        "  python studio.py compile --shot E01-004 --provider mock --prompt\n"
        "  python studio.py run --shot E01-004 --provider mock\n"
        "  python studio.py handoff --shot E01-004\n"
        "  python studio.py contact-sheet --job JOB_...\n"
        "  python studio.py audit --id JOB_...\n"
        "  python studio.py serve\n"
        "  python studio.py --project-dir examples/nine-inning-bottom mcp\n",
    )
    parser.add_argument("--project-dir", help="项目目录（默认 examples/nine-inning-bottom）")
    parser.add_argument("--config-dir", help="配置目录（默认 config）")
    sub = parser.add_subparsers(dest="command", metavar="命令")

    p = sub.add_parser("validate", help="校验角色卡、参考图库、时间线")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("build", help="编译全部厂商并生成 Context Pack")
    p.add_argument("--provider", action="append", help="只预览指定厂商（不写入共享包；可重复）")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("refresh-hashes", help="按参考图实际文件重算并写回 sha256")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_refresh_hashes)

    p = sub.add_parser("status", help="查看上下文修订、包状态与厂商矩阵")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("providers", help="查看厂商能力矩阵")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_providers)

    p = sub.add_parser("compile", help="查看某个镜头的编译结果")
    p.add_argument("--shot", required=True, help="镜头 ID，例如 E01-004")
    p.add_argument("--provider", help="厂商 ID；省略则显示该镜头全部厂商")
    p.add_argument("--prompt", action="store_true", help="打印完整提示词")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_compile)

    p = sub.add_parser("run", help="执行编译结果（mock / handoff / Quota-Flow）")
    p.add_argument("--shot", action="append", help="镜头 ID（可重复；省略则全部镜头）")
    p.add_argument("--provider", action="append", help="厂商 ID（可重复；默认项目默认厂商）")
    p.add_argument("--all-providers", action="store_true", help="对全部厂商执行（谨慎）")
    p.add_argument("--dry-run", action="store_true", help="只演练，不调用厂商")
    p.add_argument("--stop-on-error", action="store_true", help="遇到失败或阻断立即停止")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("handoff", help="导出任意模型可用的手工交接包")
    p.add_argument("--shot", action="append", required=True, help="镜头 ID（可重复）")
    p.add_argument("--dry-run", action="store_true", help="只演练，不写文件")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_handoff)

    p = sub.add_parser("jobs", help="列出任务账本")
    p.add_argument("--shot", help="按镜头过滤")
    p.add_argument("--provider", help="按厂商过滤")
    p.add_argument("--limit", type=int, default=50, help="最多显示条数")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_jobs)

    p = sub.add_parser("job", help="查看单个任务详情")
    p.add_argument("--id", required=True, help="任务 ID")
    p.add_argument("--prompt", action="store_true", help="打印完整提示词")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_job)

    p = sub.add_parser("audit", help="核验任务的连续性存证、参考图与产物")
    p.add_argument("--id", required=True, help="任务 ID")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("contact-sheet", help="从任务视频生成 3×3 抽帧九宫格")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--job", help="任务 ID（自动选择本地 video 输出）")
    source.add_argument("--video", help="视频路径（项目内相对路径或绝对路径）")
    p.add_argument("--out", help="输出图片路径（默认 outputs/<job_id>.contact_sheet.png）")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_contact_sheet)

    p = sub.add_parser("serve", help="启动本地看板")
    p.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    p.add_argument("--port", type=int, default=8787, help="端口（默认 8787）")
    p.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("mcp", help="以 MCP stdio Server 运行（Claude Desktop / WorkBuddy）")
    p.set_defaults(func=cmd_mcp)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        ctx = load_context(
            Path(args.project_dir) if args.project_dir else None,
            Path(args.config_dir) if args.config_dir else None,
        )
        return int(args.func(args, ctx))
    except (ContextError, PackError, DispatchError, JobError) as exc:
        print("错误：%s" % exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130
