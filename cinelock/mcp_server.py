from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__
from .audit import audit_job
from .context import ProjectContext
from .context_pack import (
    PackError,
    build_pack,
    get_variant,
    load_pack,
    pack_is_current,
    pack_path,
    variant_status,
)
from .dispatch import execute_variant
from .jobs import (
    JobError,
    exports_dir,
    list_jobs,
    load_job,
    outputs_dir,
    resolve_job_output,
)
from .media import MediaError, create_contact_sheet
from .util import display_path
from .validate import validate_context

SERVER_NAME = "cinelock"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "cinelock_status",
        "title": "CineLock 项目状态",
        "description": (
            "读取项目修订、镜头、适配器矩阵、Context Pack 状态和校验摘要。"
            "只读，不写入任何文件。"
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "cinelock_validate",
        "title": "校验共享上下文",
        "description": "校验角色卡、参考图哈希、时间线和厂商配置；只读。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "cinelock_variant",
        "title": "读取编译后的变体",
        "description": (
            "按镜头和 provider_id 编译一个变体，返回提示词、负向提示词、参考图、"
            "连续性快照、警告与阻断项。provider_id 是通用厂商 ID，例如 "
            "mock / handoff / comfyui / official_kling。只在内存中编译，不写共享包。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "shot_id": {"type": "string", "description": "镜头 ID，例如 E01-001"},
                "provider_id": {
                    "type": "string",
                    "description": "厂商 ID，例如 mock / handoff / comfyui / official_kling",
                },
                "include_prompt": {
                    "type": "boolean",
                    "default": True,
                    "description": "是否返回完整提示词正文",
                },
            },
            "required": ["shot_id", "provider_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "cinelock_audit",
        "title": "审计任务证据链",
        "description": (
            "按 job_id 审计一个任务：上下文存证、状态机重放、提示词、"
            "参考图、产物与重编译一致性。只读。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "任务 ID，例如 JOB_20261031T122108Z_E01-001_mock_f952db"},
                "include_checks": {
                    "type": "boolean",
                    "default": True,
                    "description": "是否返回逐项检查结果",
                },
            },
            "required": ["job_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "cinelock_jobs",
        "title": "列出任务账本",
        "description": "列出最近的生成任务，可按镜头或厂商过滤；只读。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10,
                    "description": "返回条数",
                },
                "shot_id": {"type": "string", "description": "可选：按镜头过滤"},
                "provider_id": {"type": "string", "description": "可选：按厂商过滤"},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "cinelock_build",
        "title": "编译 Context Pack",
        "description": (
            "默认只预览，不写共享包。write=true 时执行全量构建并写入 "
            "context/context_pack.json；provider_id 只能用于预览，不能与 write=true 同时使用。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "write": {
                    "type": "boolean",
                    "default": False,
                    "description": "是否写入共享 Context Pack（默认 false）",
                },
                "provider_id": {
                    "type": "string",
                    "description": "可选：只预览一个厂商；设置后 write 必须为 false",
                },
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "cinelock_contact_sheet",
        "title": "生成九宫格",
        "description": (
            "从任务的本地视频产物生成 3×3、1920×1080 的抽帧九宫格，"
            "写入 outputs/<job_id>.contact_sheet.png。需要 ffmpeg。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "带本地视频产物的任务 ID"},
            },
            "required": ["job_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "cinelock_handoff_export",
        "title": "导出交接包",
        "description": (
            "按 shot_id 直接生成交接包：prompt.txt、negative.txt、refs/、manifest.json、README.md，"
            "可打包成 zip 或保留文件夹。不需要 API Key，不调用任何厂商。"
            "适合把镜头交给 Midjourney、可灵、即梦或社区算力接力。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "shot_id": {"type": "string", "description": "镜头 ID，例如 E01-003"},
                "format": {
                    "type": "string",
                    "enum": ["zip", "folder"],
                    "default": "zip",
                    "description": "zip 生成压缩包；folder 只保留目录",
                },
                "provider_id": {
                    "type": "string",
                    "description": "可选：指定一个 handoff 适配器厂商，默认自动选择",
                },
            },
            "required": ["shot_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    },
    {
        "name": "cinelock_generate_comfyui",
        "title": "调用 ComfyUI 生成",
        "description": (
            "按 shot_id 编译变体，上传参考图到 ComfyUI、提交工作流并轮询 /history，"
            "完成后下载产物并记录 sha256 与 ffprobe 结果。默认连接 http://127.0.0.1:8188；"
            "workflow 可指向任意 API 格式工作流（需要 __CINELOCK_*__ 占位符）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "shot_id": {"type": "string", "description": "镜头 ID"},
                "provider_id": {
                    "type": "string",
                    "description": "可选：指定一个 comfyui 适配器厂商，默认自动选择",
                },
                "base_url": {
                    "type": "string",
                    "description": "可选：ComfyUI 地址，例如 http://127.0.0.1:8188",
                },
                "workflow": {
                    "type": "string",
                    "description": "可选：工作流路径（项目相对或绝对），默认 config/comfyui/workflow.example.json",
                },
                "timeout_sec": {
                    "type": "number",
                    "minimum": 1,
                    "description": "可选：整体超时秒数，默认 600",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "true 时只验证并返回计划，不联网",
                },
            },
            "required": ["shot_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    },
    {
        "name": "cinelock_generate_http",
        "title": "调用官方 HTTP API 生成",
        "description": (
            "按 shot_id 和 provider_id 调用 http_api 适配器（official_kling / official_runway "
            "或自定义通用 HTTP 厂商），轮询任务并下载产物。API Key 只从环境变量读取。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "shot_id": {"type": "string", "description": "镜头 ID"},
                "provider_id": {
                    "type": "string",
                    "description": "http_api 适配器厂商，例如 official_kling / official_runway",
                },
                "base_url": {
                    "type": "string",
                    "description": "可选：覆盖厂商默认 API 地址",
                },
                "timeout_sec": {
                    "type": "number",
                    "minimum": 1,
                    "description": "可选：整体超时秒数，默认 900",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "true 时只验证并返回计划，不联网",
                },
            },
            "required": ["shot_id", "provider_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    },
]

TOOL_ALIASES = {
    "nineflow_status": "cinelock_status",
    "nineflow_validate": "cinelock_validate",
    "nineflow_variant": "cinelock_variant",
    "nineflow_audit": "cinelock_audit",
    "nineflow_jobs": "cinelock_jobs",
    "nineflow_build": "cinelock_build",
    "nineflow_contact_sheet": "cinelock_contact_sheet",
    "nineflow_handoff_export": "cinelock_handoff_export",
    "nineflow_generate_comfyui": "cinelock_generate_comfyui",
    "nineflow_generate_http": "cinelock_generate_http",
}


def _json_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _tool_result(payload: Any, *, is_error: bool = False) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": _json_text(payload)}], "isError": is_error}


def _tool_error(message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": "错误：%s" % message}], "isError": True}


def _rpc_error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class McpServer:
    def __init__(self, ctx: ProjectContext) -> None:
        self.ctx = ctx

    def handle(self, request: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(request, dict):
            return _rpc_error(None, -32600, "Invalid Request")
        method = request.get("method")
        request_id = request.get("id")
        is_notification = "id" not in request

        if method == "notifications/initialized":
            return None
        if not isinstance(method, str):
            return None if is_notification else _rpc_error(request_id, -32600, "Invalid Request")

        try:
            if method == "initialize":
                result = self._initialize(request.get("params") or {})
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = self._call_tool(request.get("params") or {})
            elif method in ("shutdown", "exit"):
                result = {}
            else:
                if is_notification:
                    return None
                return _rpc_error(request_id, -32601, "Method not found: %s" % method)
        except Exception as exc:
            if is_notification:
                return None
            return _rpc_error(request_id, -32603, "Internal error: %s" % exc)

        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        requested = params.get("protocolVersion")
        version = requested if isinstance(requested, str) and requested else DEFAULT_PROTOCOL_VERSION
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
            "instructions": (
                "CineLock 是平台无关的 AI 视频上下文治理引擎。推荐流程："
                "cinelock_status / cinelock_validate 查看当前上下文；"
                "cinelock_variant 读取某个镜头×厂商的编译结果；"
                "cinelock_handoff_export 按 shot_id 导出 zip 或文件夹；"
                "cinelock_generate_comfyui / cinelock_generate_http 直接调用本地或官方 API；"
                "cinelock_audit / cinelock_jobs 复核证据链。"
                "cinelock_build 默认只读，write=true 才写入共享包。"
                "旧版 nineflow_* 工具名仍作为兼容别名接受，对外统一使用 cinelock_*。"
            ),
        }

    def _call_tool(self, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str):
            return _tool_error("缺少工具名")
        if not isinstance(arguments, dict):
            return _tool_error("arguments 必须是对象")
        name = TOOL_ALIASES.get(name, name)

        try:
            if name == "cinelock_status":
                return _tool_result(self._status())
            if name == "cinelock_validate":
                return _tool_result(validate_context(self.ctx).to_dict())
            if name == "cinelock_variant":
                return _tool_result(self._variant(arguments))
            if name == "cinelock_audit":
                return _tool_result(self._audit(arguments))
            if name == "cinelock_jobs":
                return _tool_result(self._jobs(arguments))
            if name == "cinelock_build":
                return _tool_result(self._build(arguments))
            if name == "cinelock_contact_sheet":
                return _tool_result(self._contact_sheet(arguments))
            if name == "cinelock_handoff_export":
                return self._job_tool_result(self._handoff_export(arguments))
            if name == "cinelock_generate_comfyui":
                return self._job_tool_result(self._generate_comfyui(arguments))
            if name == "cinelock_generate_http":
                return self._job_tool_result(self._generate_http(arguments))
        except (PackError, JobError, MediaError, ValueError) as exc:
            return _tool_error(str(exc))
        return _tool_error("未知工具：%s" % name)

    def _status(self) -> Dict[str, Any]:
        ctx = self.ctx
        pack = load_pack(ctx)
        validation = validate_context(ctx)
        profiles = ctx.provider_profiles()
        providers = []
        for provider_id in ctx.provider_order():
            profile = profiles.get(provider_id) or {}
            providers.append(
                {
                    "provider_id": provider_id,
                    "display_name": profile.get("display_name"),
                    "adapter": profile.get("adapter"),
                    "preset": profile.get("preset"),
                    "enabled": profile.get("enabled", True),
                    "experimental": bool(profile.get("experimental")),
                }
            )

        pack_info: Dict[str, Any] = {"exists": False, "current": False}
        if pack:
            stats = pack.get("stats") or {}
            pack_info = {
                "exists": True,
                "current": pack_is_current(ctx, pack),
                "context_revision": pack.get("context_revision"),
                "generated_at": pack.get("generated_at"),
                "variant_count": stats.get("variant_count"),
                "shot_count": stats.get("shot_count"),
                "provider_count": stats.get("provider_count"),
            }

        return {
            "project": {
                "project_id": ctx.project_id,
                "title": ctx.title,
                "project_dir": str(ctx.root),
            },
            "context_revision": ctx.context_revision(),
            "short_revision": ctx.context_revision()[:12],
            "shot_count": len(ctx.shots()),
            "provider_count": len(ctx.provider_order()),
            "shots": [
                {
                    "shot_id": shot.get("shot_id"),
                    "scene_id": shot.get("scene_id"),
                    "duration_sec": shot.get("duration_sec"),
                    "character_ids": list(shot.get("character_ids") or []),
                    "status": shot.get("status"),
                }
                for shot in ctx.shots()
            ],
            "providers": providers,
            "pack": pack_info,
            "validation": {
                "ok": validation.ok,
                "error_count": len(validation.errors),
                "warning_count": len(validation.warnings),
            },
        }

    def _variant(self, args: Dict[str, Any]) -> Dict[str, Any]:
        shot_id = str(args.get("shot_id") or "").strip()
        provider_id = str(args.get("provider_id") or "").strip()
        if not shot_id or not provider_id:
            raise ValueError("shot_id 和 provider_id 必填")
        variant = self._preview_variant(shot_id, provider_id)

        references = []
        for ref in variant.get("references") or []:
            references.append(
                {
                    "order": ref.get("order"),
                    "asset_id": ref.get("asset_id"),
                    "role": ref.get("role"),
                    "label": ref.get("label"),
                    "kind": ref.get("kind"),
                    "path": ref.get("path"),
                    "sha256": ref.get("sha256"),
                    "public_url": ref.get("public_url"),
                    "status": ref.get("status"),
                }
            )

        include_prompt = bool(args.get("include_prompt", True))
        payload = {
            "shot_id": shot_id,
            "provider_id": provider_id,
            "adapter": variant.get("adapter"),
            "mode": variant.get("mode"),
            "mode_label": variant.get("mode_label"),
            "status": variant_status(variant),
            "context_revision": variant.get("context_revision"),
            "short_revision": variant.get("short_revision"),
            "variant_sha256": variant.get("variant_sha256"),
            "prompt_sha256": variant.get("prompt_sha256"),
            "negative_sha256": variant.get("negative_sha256"),
            "duration_sec": variant.get("duration_sec"),
            "seed": variant.get("seed"),
            "reference_count": variant.get("reference_count"),
            "references": references,
            "continuity": variant.get("continuity"),
            "warnings": variant.get("warnings") or [],
            "blockers": variant.get("blockers") or [],
            "dispatch": variant.get("dispatch"),
        }
        if include_prompt:
            payload["prompt"] = variant.get("prompt")
            payload["negative_prompt"] = variant.get("negative_prompt")
        return payload

    def _audit(self, args: Dict[str, Any]) -> Dict[str, Any]:
        job_id = str(args.get("job_id") or "").strip()
        if not job_id:
            raise ValueError("job_id 必填")
        report = audit_job(self.ctx, load_job(self.ctx, job_id))
        if not bool(args.get("include_checks", True)):
            report.pop("checks", None)
        return report

    def _jobs(self, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            limit = int(args.get("limit", 10))
        except (TypeError, ValueError):
            raise ValueError("limit 必须是整数")
        limit = max(1, min(limit, 100))
        records = list_jobs(
            self.ctx,
            limit=limit,
            shot_id=str(args["shot_id"]) if args.get("shot_id") else None,
            provider_id=str(args["provider_id"]) if args.get("provider_id") else None,
        )
        return {"count": len(records), "jobs": records}

    def _build(self, args: Dict[str, Any]) -> Dict[str, Any]:
        write = bool(args.get("write", False))
        provider_id = str(args.get("provider_id") or "").strip() or None
        if write and provider_id:
            raise ValueError("provider_id 只能用于预览；写入共享包必须全量构建（省略 provider_id）")
        if provider_id and provider_id not in self.ctx.provider_profiles():
            raise ValueError("厂商不存在：%s" % provider_id)

        pack = build_pack(self.ctx, [provider_id] if provider_id else None, write=write)
        return {
            "written": write,
            "pack_path": str(pack_path(self.ctx)) if write else None,
            "context_revision": pack.get("context_revision"),
            "short_revision": pack.get("short_revision"),
            "stats": pack.get("stats"),
            "validation": pack.get("validation"),
        }

    def _contact_sheet(self, args: Dict[str, Any]) -> Dict[str, Any]:
        job_id = str(args.get("job_id") or "").strip()
        if not job_id:
            raise ValueError("job_id 必填")
        job = load_job(self.ctx, job_id)
        video = resolve_job_output(self.ctx, job, "video")
        if video is None:
            raise ValueError("任务没有本地视频产物：%s" % job_id)

        output = outputs_dir(self.ctx) / ("%s.contact_sheet.png" % job_id)
        result = create_contact_sheet(video, output)
        return {
            "job_id": job_id,
            "video": display_path(video, self.ctx.root),
            "output": display_path(Path(result["output"]), self.ctx.root),
            "bytes": result.get("bytes"),
            "width": result.get("width"),
            "height": result.get("height"),
            "columns": result.get("columns"),
            "rows": result.get("rows"),
            "timestamps": result.get("timestamps"),
            "probe": result.get("probe"),
        }

    def _handoff_export(self, args: Dict[str, Any]) -> Dict[str, Any]:
        shot_id = str(args.get("shot_id") or "").strip()
        if not shot_id:
            raise ValueError("shot_id 必填")
        provider_id = self._provider_for("handoff", str(args.get("provider_id") or "").strip() or None)
        bundle = str(args.get("format") or "zip").lower()
        if bundle not in ("zip", "folder"):
            raise ValueError("format 只能是 zip 或 folder")
        variant = self._preview_variant(shot_id, provider_id)
        job = execute_variant(self.ctx, variant, options={"bundle": bundle})

        job_id = str(job.get("job_id") or "")
        folder = exports_dir(self.ctx) / "handoff" / job_id
        zip_path = next(
            (item.get("path") for item in job.get("outputs") or [] if item.get("kind") == "zip"),
            None,
        )
        payload = self._job_payload(job)
        payload.update(
            {
                "bundle": bundle,
                "folder": display_path(folder, self.ctx.root) if folder.is_dir() else None,
                "zip": zip_path,
                "files": [
                    item.get("path")
                    for item in job.get("outputs") or []
                    if item.get("path")
                ],
            }
        )
        return payload

    def _generate_comfyui(self, args: Dict[str, Any]) -> Dict[str, Any]:
        shot_id = str(args.get("shot_id") or "").strip()
        if not shot_id:
            raise ValueError("shot_id 必填")
        provider_id = self._provider_for("comfyui", str(args.get("provider_id") or "").strip() or None)
        options = self._execution_options(args, ("base_url", "workflow", "timeout_sec", "poll_interval_sec"))
        variant = self._preview_variant(shot_id, provider_id)
        job = execute_variant(
            self.ctx,
            variant,
            dry_run=bool(args.get("dry_run", False)),
            options=options,
        )
        payload = self._job_payload(job)
        payload["base_url"] = options.get("base_url") or (variant.get("provider") or {}).get("base_url")
        payload["workflow"] = options.get("workflow") or (variant.get("provider") or {}).get("workflow")
        return payload

    def _generate_http(self, args: Dict[str, Any]) -> Dict[str, Any]:
        shot_id = str(args.get("shot_id") or "").strip()
        provider_id = str(args.get("provider_id") or "").strip()
        if not shot_id or not provider_id:
            raise ValueError("shot_id 和 provider_id 必填")
        provider_id = self._provider_for("http_api", provider_id)
        options = self._execution_options(args, ("base_url", "timeout_sec", "poll_interval_sec"))
        variant = self._preview_variant(shot_id, provider_id)
        job = execute_variant(
            self.ctx,
            variant,
            dry_run=bool(args.get("dry_run", False)),
            options=options,
        )
        payload = self._job_payload(job)
        payload["base_url"] = options.get("base_url") or (variant.get("provider") or {}).get("base_url")
        return payload

    def _execution_options(self, args: Dict[str, Any], keys: tuple) -> Dict[str, Any]:
        options: Dict[str, Any] = {}
        for key in keys:
            value = args.get(key)
            if value in (None, ""):
                continue
            if key.endswith("_sec"):
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    raise ValueError("%s 必须是数字" % key)
                if value <= 0:
                    raise ValueError("%s 必须大于 0" % key)
            options[key] = value
        return options

    def _provider_for(self, adapter: str, preferred: Optional[str]) -> str:
        profiles = self.ctx.provider_profiles()
        order = list(self.ctx.provider_order())
        if preferred:
            profile = profiles.get(preferred)
            if not profile:
                raise ValueError("厂商不存在：%s（可用：%s）" % (preferred, ", ".join(order)))
            actual = str(profile.get("adapter") or "")
            if actual != adapter:
                raise ValueError("厂商 %s 使用 %s 适配器，不是 %s" % (preferred, actual or "未知", adapter))
            return preferred
        for provider_id in order:
            profile = profiles.get(provider_id) or {}
            if str(profile.get("adapter") or "") == adapter and profile.get("enabled", True):
                return provider_id
        raise ValueError("没有启用中的 %s 适配器厂商" % adapter)

    def _preview_variant(self, shot_id: str, provider_id: str) -> Dict[str, Any]:
        if self.ctx.shot(shot_id) is None:
            raise ValueError("镜头不存在：%s" % shot_id)
        if provider_id not in self.ctx.provider_profiles():
            raise ValueError("厂商不存在：%s" % provider_id)
        pack = build_pack(self.ctx, [provider_id], write=False)
        variant = get_variant(pack, shot_id, provider_id)
        if variant is None:
            raise ValueError("没有找到变体：%s × %s" % (shot_id, provider_id))
        return variant

    def _job_payload(self, job: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "job_id": job.get("job_id"),
            "status": job.get("status"),
            "dry_run": job.get("dry_run"),
            "shot_id": job.get("shot_id"),
            "provider_id": job.get("provider_id"),
            "adapter": job.get("adapter"),
            "mode": job.get("mode"),
            "context_revision": job.get("context_revision"),
            "short_revision": job.get("short_revision"),
            "variant_sha256": job.get("variant_sha256"),
            "outputs": job.get("outputs") or [],
            "warnings": job.get("warnings") or [],
            "error": job.get("error"),
            "adapter_meta": job.get("adapter_meta") or {},
            "audit_hint": "调用 cinelock_audit 并传入 job_id 可复核证据链",
        }

    def _job_tool_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        failed = payload.get("status") in ("failed", "blocked", "canceled")
        return _tool_result(payload, is_error=failed)


def serve(ctx: ProjectContext, stdin=None, stdout=None) -> int:
    input_stream = stdin or sys.stdin
    output_stream = stdout or sys.stdout
    server = McpServer(ctx)

    for line in input_stream:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _rpc_error(None, -32700, "Parse error: %s" % exc)
        else:
            response = server.handle(request)
        if response is not None:
            output_stream.write(json.dumps(response, ensure_ascii=False) + "\n")
            output_stream.flush()
    return 0
