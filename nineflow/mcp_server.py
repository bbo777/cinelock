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
from .jobs import (
    JobError,
    list_jobs,
    load_job,
    outputs_dir,
    resolve_job_output,
)
from .media import MediaError, create_contact_sheet
from .util import display_path
from .validate import validate_context

SERVER_NAME = "nineflow"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"

TOOLS: List[Dict[str, Any]] = [
    {
        "name": "nineflow_status",
        "title": "NineFlow 项目状态",
        "description": (
            "读取项目修订、镜头、厂商矩阵、Context Pack 状态和校验摘要。"
            "只读，不写入任何文件。"
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "nineflow_validate",
        "title": "校验共享上下文",
        "description": "校验角色卡、参考图哈希、时间线和厂商配置；只读。",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "nineflow_variant",
        "title": "读取编译后的变体",
        "description": (
            "按镜头和厂商编译一个变体，返回提示词、负向提示词、参考图、"
            "连续性快照、警告与阻断项。只在内存中编译，不写入共享 Context Pack。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "shot_id": {"type": "string", "description": "镜头 ID，例如 E01-001"},
                "provider_id": {"type": "string", "description": "厂商 ID，例如 mock / qwenwan / handoff"},
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
        "name": "nineflow_audit",
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
                    "description": "是否返回 13 项逐项检查结果",
                },
            },
            "required": ["job_id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "nineflow_jobs",
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
        "name": "nineflow_build",
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
        "name": "nineflow_contact_sheet",
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
]


def _json_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _tool_result(payload: Any) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": _json_text(payload)}], "isError": False}


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
                "NineFlow 把项目、角色卡、参考图、时间线和厂商矩阵编译成共享上下文。"
                "先用 nineflow_status 查看当前修订，再用 nineflow_variant 读取某个镜头×厂商的编译结果；"
                "写入共享包需要显式调用 nineflow_build 并设置 write=true。"
            ),
        }

    def _call_tool(self, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str):
            return _tool_error("缺少工具名")
        if not isinstance(arguments, dict):
            return _tool_error("arguments 必须是对象")

        try:
            if name == "nineflow_status":
                return _tool_result(self._status())
            if name == "nineflow_validate":
                return _tool_result(validate_context(self.ctx).to_dict())
            if name == "nineflow_variant":
                return _tool_result(self._variant(arguments))
            if name == "nineflow_audit":
                return _tool_result(self._audit(arguments))
            if name == "nineflow_jobs":
                return _tool_result(self._jobs(arguments))
            if name == "nineflow_build":
                return _tool_result(self._build(arguments))
            if name == "nineflow_contact_sheet":
                return _tool_result(self._contact_sheet(arguments))
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
                    "enabled": profile.get("enabled", True),
                    "default_mode": profile.get("default_mode"),
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
        if self.ctx.shot(shot_id) is None:
            raise ValueError("镜头不存在：%s" % shot_id)
        if provider_id not in self.ctx.provider_profiles():
            raise ValueError("厂商不存在：%s" % provider_id)

        pack = build_pack(self.ctx, [provider_id], write=False)
        variant = get_variant(pack, shot_id, provider_id)
        if variant is None:
            raise ValueError("没有找到变体：%s × %s" % (shot_id, provider_id))

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
