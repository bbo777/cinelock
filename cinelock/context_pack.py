from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from .compiler import MODE_LABELS, compile_all
from .context import ProjectContext
from .continuity import build_state_snapshots
from .util import read_json, short_hash, utc_now, write_json, write_text
from .validate import validate_context

PACK_SCHEMA_VERSION = "1.0"
STATUS_LABELS = {
    "ready": "可执行",
    "warning": "可执行（有告警）",
    "not_ready": "未就绪",
    "blocked": "阻断",
}


class PackError(Exception):
    pass


def context_dir(ctx: ProjectContext) -> Path:
    return ctx.root / "context"


def pack_path(ctx: ProjectContext) -> Path:
    return context_dir(ctx) / "context_pack.json"


def _safe_name(value: Any) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._")
    return name or "unknown"


def variant_status(variant: Dict[str, Any]) -> str:
    if variant.get("blockers"):
        return "blocked"
    dispatch = variant.get("dispatch") or {}
    if not dispatch.get("ready"):
        return "not_ready"
    if variant.get("warnings"):
        return "warning"
    return "ready"


def _compute_stats(compiled: List[Dict[str, Any]], provider_ids: List[str], shot_count: int) -> Dict[str, Any]:
    providers: Dict[str, Dict[str, Any]] = {
        pid: {"variants": 0, "references": 0, "warnings": 0, "blockers": 0, "statuses": {}} for pid in provider_ids
    }
    modes: Dict[str, int] = {}
    statuses: Dict[str, int] = {}
    total_refs = 0
    for variant in compiled:
        pid = str(variant.get("provider_id") or "")
        stat = providers.setdefault(pid, {"variants": 0, "references": 0, "warnings": 0, "blockers": 0, "statuses": {}})
        status = variant_status(variant)
        stat["variants"] += 1
        stat["references"] += int(variant.get("reference_count") or 0)
        stat["warnings"] += len(variant.get("warnings") or [])
        stat["blockers"] += len(variant.get("blockers") or [])
        stat["statuses"][status] = stat["statuses"].get(status, 0) + 1
        modes[str(variant.get("mode"))] = modes.get(str(variant.get("mode")), 0) + 1
        statuses[status] = statuses.get(status, 0) + 1
        total_refs += int(variant.get("reference_count") or 0)
    return {
        "shot_count": shot_count,
        "provider_count": len(provider_ids),
        "variant_count": len(compiled),
        "total_references": total_refs,
        "modes": modes,
        "statuses": statuses,
        "providers": providers,
    }


def _variant_summary(variant: Dict[str, Any]) -> Dict[str, Any]:
    refs = variant.get("references") or []
    return {
        "provider_id": variant.get("provider_id"),
        "mode": variant.get("mode"),
        "mode_label": variant.get("mode_label"),
        "duration_sec": variant.get("duration_sec"),
        "reference_count": variant.get("reference_count"),
        "first_reference": refs[0].get("asset_id") if refs else None,
        "prompt_sha256": variant.get("prompt_sha256"),
        "short_prompt_hash": short_hash(str(variant.get("prompt_sha256") or ""), 12),
        "prompt_chars": variant.get("prompt_chars"),
        "status": variant_status(variant),
        "dispatch_ready": bool((variant.get("dispatch") or {}).get("ready")),
        "warning_count": len(variant.get("warnings") or []),
        "blocker_count": len(variant.get("blockers") or []),
    }


def _provider_entries(ctx: ProjectContext, provider_ids: List[str]) -> List[Dict[str, Any]]:
    entries = []
    profiles = ctx.provider_profiles()
    for order, pid in enumerate(provider_ids, 1):
        profile = profiles[pid]
        entries.append(
            {
                "id": pid,
                "order": order,
                "display_name": profile.get("display_name"),
                "adapter": profile.get("adapter"),
                "preset": profile.get("preset"),
                "enabled": bool(profile.get("enabled", True)),
                "experimental": bool(profile.get("experimental")),
                "modes": list(profile.get("modes") or []),
                "max_refs": profile.get("max_refs"),
                "durations": list(profile.get("durations") or []),
                "ref_semantics": profile.get("ref_semantics"),
                "supports_negative_prompt": bool(profile.get("supports_negative_prompt")),
                "supports_seed": bool(profile.get("supports_seed")),
                "prompt_suffix": profile.get("prompt_suffix"),
            }
        )
    return entries


def build_pack(
    ctx: ProjectContext,
    provider_ids: Optional[List[str]] = None,
    *,
    write: bool = True,
) -> Dict[str, Any]:
    validation = validate_context(ctx)
    if not validation.ok:
        lines = ["上下文校验失败（%d 错误），未生成 Context Pack：" % len(validation.errors)]
        for issue in validation.errors[:20]:
            lines.append("- [%s] %s %s" % (issue.code, issue.where, issue.message))
        raise PackError("\n".join(lines))

    ids = list(provider_ids or ctx.provider_order())
    profiles = ctx.provider_profiles()
    unknown = [pid for pid in ids if pid not in profiles]
    if unknown:
        raise PackError("未知 provider：%s" % ", ".join(unknown))
    if not ids:
        raise PackError("没有可编译的 provider")

    snapshots = build_state_snapshots(ctx)
    compiled = compile_all(ctx, ids, snapshots=snapshots)
    revision = ctx.context_revision()
    revisions = {v.get("context_revision") for v in compiled}
    if revisions != {revision}:
        raise PackError("内部错误：编译变体的 context_revision 不一致：%s" % sorted(str(x) for x in revisions))

    generated_at = utc_now()
    shots: List[Dict[str, Any]] = []
    for shot in ctx.shots():
        sid = str(shot.get("shot_id"))
        variants = [_variant_summary(v) for v in compiled if v.get("shot_id") == sid]
        shots.append(
            {
                "shot_id": sid,
                "scene_id": shot.get("scene_id"),
                "duration_sec": shot.get("duration_sec"),
                "shot_size": shot.get("shot_size"),
                "camera_move": shot.get("camera_move"),
                "character_ids": list(shot.get("character_ids") or []),
                "expressions": dict(shot.get("expressions") or {}),
                "action_en": shot.get("action_en"),
                "risk_level": shot.get("risk_level"),
                "status": shot.get("status"),
                "notes": shot.get("notes"),
                "snapshot": snapshots.get(sid),
                "variants": variants,
            }
        )

    stats = _compute_stats(compiled, ids, len(shots))
    pack: Dict[str, Any] = {
        "schema_version": PACK_SCHEMA_VERSION,
        "project_id": ctx.project_id,
        "title": ctx.title,
        "subtitle": ctx.project.get("subtitle"),
        "episode_id": ctx.timeline.get("episode_id"),
        "episode_title": ctx.timeline.get("title"),
        "context_revision": revision,
        "short_revision": short_hash(revision),
        "generated_at": generated_at,
        "source_hashes": ctx.source_hashes(),
        "format": ctx.project.get("format") or {},
        "style": {
            "anchor": (ctx.project.get("style") or {}).get("anchor"),
            "palette": (ctx.project.get("style") or {}).get("palette"),
            "quality_suffix": (ctx.project.get("style") or {}).get("quality_suffix"),
        },
        "providers": _provider_entries(ctx, ids),
        "validation": validation.to_dict(),
        "snapshots": snapshots,
        "shots": shots,
        "variants": compiled,
        "stats": stats,
    }

    if write:
        _write_pack(ctx, pack)
    return pack


def _write_pack(ctx: ProjectContext, pack: Dict[str, Any]) -> None:
    out_dir = context_dir(ctx)
    write_json(out_dir / "context_pack.json", pack)
    write_json(
        out_dir / "continuity.json",
        {
            "context_revision": pack.get("context_revision"),
            "episode_id": pack.get("episode_id"),
            "generated_at": pack.get("generated_at"),
            "snapshots": pack.get("snapshots") or {},
        },
    )
    shots_root = out_dir / "shots"
    if shots_root.exists():
        shutil.rmtree(shots_root)
    for variant in pack.get("variants") or []:
        shot_id = _safe_name(variant.get("shot_id"))
        provider_id = _safe_name(variant.get("provider_id"))
        folder = shots_root / shot_id
        write_json(folder / ("%s.json" % provider_id), variant)
        write_text(folder / ("%s.prompt.txt" % provider_id), str(variant.get("prompt") or "") + "\n")
        if variant.get("negative_prompt"):
            write_text(folder / ("%s.negative.txt" % provider_id), str(variant["negative_prompt"]) + "\n")
    write_text(out_dir / "CONTEXT.md", render_markdown(ctx, pack))


def _md(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")


def _character_state_text(ctx: ProjectContext, snapshot: Dict[str, Any]) -> str:
    parts = []
    for cid, state in (snapshot.get("characters") or {}).items():
        card = ctx.character(str(cid)) or {}
        name = card.get("name_en") or card.get("name") or cid
        injuries = state.get("injuries") or []
        props = state.get("props") or []
        parts.append(
            "%s：%s · 伤：%s · 道具：%s · 表情：%s"
            % (
                name,
                state.get("wardrobe_state") or "?",
                "、".join(injuries) if injuries else "无",
                "、".join(props) if props else "无",
                state.get("expression") or "neutral",
            )
        )
    return "；".join(parts) if parts else "无角色"


def _changes_text(ctx: ProjectContext, changes: Dict[str, Any]) -> str:
    parts = []
    for cid, items in (changes or {}).items():
        card = ctx.character(str(cid)) or {}
        name = card.get("name_en") or card.get("name") or cid
        parts.append("%s：%s" % (name, "；".join(items)))
    return "；".join(parts) if parts else "无"


def render_markdown(ctx: ProjectContext, pack: Dict[str, Any]) -> str:
    project = ctx.project
    stats = pack.get("stats") or {}
    validation = pack.get("validation") or {}
    lines: List[str] = []
    lines.append("# %s — Context Pack" % pack.get("title"))
    lines.append("")
    if project.get("subtitle"):
        lines.append("> %s" % project["subtitle"])
        lines.append("")
    lines.append("- 项目：`%s`" % pack.get("project_id"))
    lines.append("- 集：`%s` — %s" % (pack.get("episode_id"), pack.get("episode_title") or ""))
    lines.append("- 上下文版本：`%s`" % pack.get("context_revision"))
    lines.append("- 短版本：`%s`" % pack.get("short_revision"))
    lines.append("- 生成时间：%s" % pack.get("generated_at"))
    lines.append(
        "- 规模：%s 个镜头 / %s 个厂商 / %s 个变体"
        % (stats.get("shot_count"), stats.get("provider_count"), stats.get("variant_count"))
    )
    lines.append(
        "- 校验：%s 错误，%s 警告"
        % (validation.get("error_count", 0), validation.get("warning_count", 0))
    )
    lines.append("")
    lines.append("## 唯一输入原则")
    lines.append("")
    lines.append(
        "所有厂商共用同一个 `context_revision`。角色卡、参考图库、时间线状态快照都在本包中固化；"
        "修改角色、参考图、时间线或厂商矩阵都会生成新的版本，旧版本产物不会自动混用。"
    )
    lines.append("")
    lines.append("模式：`text2video` 文生视频，`img2video` 单图首帧，`multi_ref` 多参考，`first_last` 首尾帧。")
    lines.append("")

    lines.append("## 厂商能力")
    lines.append("")
    lines.append("| 厂商 | 名称 | 适配器 | 支持模式 | 参考上限 | 支持时长 | 负向词 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for provider in pack.get("providers") or []:
        lines.append(
            "| `%s` | %s | %s | %s | %s | %s | %s |"
            % (
                _md(provider.get("id")),
                _md(provider.get("display_name")),
                _md(provider.get("adapter")),
                _md(" / ".join(provider.get("modes") or [])),
                _md(provider.get("max_refs")),
                _md(" / ".join(str(x) for x in provider.get("durations") or [])),
                "是" if provider.get("supports_negative_prompt") else "否",
            )
        )
    lines.append("")

    lines.append("## 参考图库")
    lines.append("")
    lines.append("| asset_id | 类型 | 归属 | 状态 | 文件 | sha256 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for asset in ctx.asset_list():
        owner = asset.get("character_id") or asset.get("scene_id") or ""
        lines.append(
            "| `%s` | %s | %s | %s | `%s` | `%s` |"
            % (
                _md(asset.get("asset_id")),
                _md(asset.get("kind")),
                _md(owner),
                _md(asset.get("status")),
                _md(asset.get("path")),
                _md(short_hash(str(asset.get("sha256") or ""), 12)),
            )
        )
    lines.append("")

    lines.append("## 连续性时间线")
    lines.append("")
    lines.append("| 镜头 | 场景 | 角色状态 | 状态变化 | 连续性备注 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for shot in pack.get("shots") or []:
        snapshot = shot.get("snapshot") or {}
        lines.append(
            "| `%s` | `%s` | %s | %s | %s |"
            % (
                _md(shot.get("shot_id")),
                _md(shot.get("scene_id")),
                _md(_character_state_text(ctx, snapshot)),
                _md(_changes_text(ctx, snapshot.get("changes") or {})),
                _md(snapshot.get("notes") or ""),
            )
        )
    lines.append("")

    lines.append("## 编译结果")
    lines.append("")
    lines.append("| 镜头 | 厂商 | 模式 | 时长 | 参考 | 首参考 | 提示词 | 状态 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for shot in pack.get("shots") or []:
        for variant in shot.get("variants") or []:
            status = variant.get("status")
            status_text = STATUS_LABELS.get(str(status), str(status))
            if variant.get("blocker_count"):
                status_text += "（%s 阻断）" % variant.get("blocker_count")
            lines.append(
                "| `%s` | `%s` | `%s` | %ss | %s | `%s` | `%s` | %s |"
                % (
                    _md(shot.get("shot_id")),
                    _md(variant.get("provider_id")),
                    _md(variant.get("mode")),
                    _md(variant.get("duration_sec")),
                    _md(variant.get("reference_count")),
                    _md(variant.get("first_reference") or "—"),
                    _md(variant.get("short_prompt_hash")),
                    _md(status_text),
                )
            )
    lines.append("")

    lines.append("## 目录")
    lines.append("")
    lines.append("```")
    lines.append("context/")
    lines.append("  context_pack.json          全部变体与共享修订的完整清单")
    lines.append("  continuity.json            每个镜头的角色状态快照")
    lines.append("  CONTEXT.md                 本说明")
    lines.append("  shots/<shot_id>/<provider>.json          编译结果")
    lines.append("  shots/<shot_id>/<provider>.prompt.txt    正向提示词")
    lines.append("  shots/<shot_id>/<provider>.negative.txt  负向提示词（如有）")
    lines.append("```")
    lines.append("")

    lines.append("## 限制与边界")
    lines.append("")
    lines.append("- 共享输入与参考图顺序能显著降低漂移，但不能在数学意义上保证同一张脸；高风险特写建议加首尾帧或人工 QC。")
    lines.append("- 单图模式只能放一张身份锚点；多角色镜头中其余角色只能靠提示词描述。")
    lines.append("- ComfyUI 与官方 HTTP API 适配器按工作流/平台配置执行；未配置本地服务或 API Key 时会明确失败，不会伪造成功。")
    lines.append("- 参考图状态仍为 `draft` 时只适合演练；正式生产前应改为 `approved` 或 `locked`。")
    lines.append("- 本包只负责共享上下文与执行参数，不包含 Cookie、API Key 或账号登录态；密钥只从环境变量读取。")
    lines.append("")
    return "\n".join(lines)


def load_pack(ctx: ProjectContext) -> Optional[Dict[str, Any]]:
    path = pack_path(ctx)
    if not path.is_file():
        return None
    try:
        data = read_json(path)
    except Exception as exc:
        raise PackError("Context Pack 不是合法 JSON：%s（%s）" % (path, exc))
    if not isinstance(data, dict):
        raise PackError("Context Pack 顶层必须是对象：%s" % path)
    return data


def pack_is_current(ctx: ProjectContext, pack: Optional[Dict[str, Any]]) -> bool:
    if not pack:
        return False
    return pack.get("context_revision") == ctx.context_revision()


def get_variant(pack: Dict[str, Any], shot_id: str, provider_id: str) -> Optional[Dict[str, Any]]:
    for variant in pack.get("variants") or []:
        if variant.get("shot_id") == shot_id and variant.get("provider_id") == provider_id:
            return variant
    return None


def variant_file(ctx: ProjectContext, shot_id: str, provider_id: str) -> Path:
    return context_dir(ctx) / "shots" / _safe_name(shot_id) / ("%s.json" % _safe_name(provider_id))
