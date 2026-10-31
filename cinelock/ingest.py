from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from .adapters.common import file_output
from .context import ProjectContext
from .context_pack import PackError, get_variant, load_pack, pack_is_current
from .jobs import create_job, update_job
from .media import probe_video
from .util import utc_now

VIDEO_SUFFIXES = {".mp4", ".mov", ".webm"}
MIN_PREFIX = 8


class IngestError(Exception):
    pass


def _matches(value: str, full: str, short: str, label: str) -> bool:
    candidate = str(value or "").strip().lower()
    if not candidate:
        return True
    if len(candidate) < MIN_PREFIX:
        raise IngestError("%s 至少给出 %d 位，避免误匹配" % (label, MIN_PREFIX))
    return full.lower().startswith(candidate) or short.lower().startswith(candidate)


def import_external_artifact(
    ctx: ProjectContext,
    shot_id: str,
    source_path: Path,
    *,
    model: str = "",
    note: str = "",
    provider_id: str = "handoff",
    revision: str = "",
    prompt_hash: str = "",
) -> Dict[str, Any]:
    try:
        pack = load_pack(ctx)
    except PackError as exc:
        raise IngestError(str(exc))
    if pack is None:
        raise IngestError("还没有 Context Pack；先运行 build")
    if not pack_is_current(ctx, pack):
        raise IngestError(
            "上下文已变化：当前修订 %s，包内修订 %s。先重新 build 并重新导出 handoff。"
            % (ctx.context_revision()[:12], str(pack.get("short_revision") or "?"))
        )

    variant = get_variant(pack, shot_id, provider_id)
    if variant is None:
        raise IngestError("Context Pack 中没有 %s × %s 的编译结果" % (shot_id, provider_id))

    full_revision = str(pack.get("context_revision") or "")
    short_revision = str(pack.get("short_revision") or "")
    if not _matches(revision, full_revision, short_revision, "修订号"):
        raise IngestError(
            "外部包修订 %s 与当前修订 %s 不一致；请用同一修订重新导出 handoff，不要混用旧包。"
            % (revision, short_revision or full_revision[:12])
        )
    full_prompt = str(variant.get("prompt_sha256") or "")
    if not _matches(prompt_hash, full_prompt, full_prompt[:12], "提示词哈希"):
        raise IngestError("外部包提示词哈希与当前编译结果不一致；这条结果不能挂到当前修订上。")

    source = Path(source_path).expanduser()
    if not source.is_file():
        raise IngestError("视频文件不存在：%s" % source)
    suffix = source.suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        raise IngestError("只支持 .mp4 / .mov / .webm，当前为 %s" % (suffix or "无扩展名"))

    probe = dict(probe_video(source))
    if probe.get("available") and not probe.get("ok"):
        raise IngestError("ffprobe 无法解析该文件：%s" % probe.get("error"))
    probe.pop("path", None)

    job = create_job(ctx, variant, dry_run=False, adapter="handoff_import")
    target = ctx.root / "outputs" / (str(job["job_id"]) + suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

    warnings = [
        "外部导入：CineLock 只核验产物哈希与上下文绑定，不验证该视频是否真由所声明的模型生成，也不判断画面中的脸、服装与伤情是否连续。"
    ]
    if not probe.get("available"):
        warnings.append("未找到 ffprobe，未做媒体完整性校验。")
    else:
        requested_duration = variant.get("duration_sec")
        actual_duration = probe.get("duration_sec")
        if requested_duration and actual_duration and abs(float(actual_duration) - float(requested_duration)) > 1.0:
            warnings.append(
                "实际时长 %.2fs 与编译目标 %ss 不一致；任务记录按实际文件保存。"
                % (float(actual_duration), requested_duration)
            )
        resolution = str(variant.get("resolution") or "")
        if "x" in resolution:
            try:
                expected_w, expected_h = [int(part) for part in resolution.lower().split("x", 1)]
            except ValueError:
                expected_w = expected_h = 0
            if expected_w and (probe.get("width") != expected_w or probe.get("height") != expected_h):
                warnings.append(
                    "实际分辨率 %sx%s 与编译目标 %s 不一致。"
                    % (probe.get("width"), probe.get("height"), resolution)
                )

    external = {
        "model": model or "未声明",
        "source_filename": source.name,
        "note": note,
        "imported_at": utc_now(),
        "declared_revision": revision or short_revision,
        "declared_prompt_sha256": prompt_hash or full_prompt,
        "verification": "artifact_integrity_only",
        "probe": probe,
    }
    outputs = [file_output(target, "video", ctx.root, origin="external", model=model or None)]
    update_job(
        ctx,
        job,
        status="succeeded",
        message="外部产物已导入并写入任务账本",
        append_warnings=warnings,
        provider_display_name=(model + "（外部导入）") if model else "外部导入",
        external=external,
        outputs=outputs,
        command=["external-import", model or "unknown-model", source.name],
        plan=[
            "读取当前 Context Pack 中 %s × %s 的编译结果" % (shot_id, provider_id),
            "核对声明的修订号与提示词哈希",
            "复制产物到 outputs/ 并记录 SHA-256",
            "用同一套 13 项审计核验上下文绑定与文件完整性",
        ],
        duration_ms=0,
    )
    return job
