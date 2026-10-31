from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..media import probe_video
from ..util import sha256_file, utc_now
from .common import AdapterOutcome, AdapterRequest, file_output
from .net import (
    AdapterHTTPError,
    download_file,
    image_content_type,
    join_url,
    normalize_base_url,
    post_multipart,
    request_json,
    poll,
)

TOKEN_RE = re.compile(r"__CINELOCK_[A-Z0-9]+__")
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}


def _resolve_workflow(request: AdapterRequest) -> Path:
    raw = str(request.option("workflow") or "config/comfyui/workflow.example.json")
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    roots = [request.project_root]
    if request.config_dir:
        roots.append(request.config_dir)
        roots.append(request.config_dir.parent)
    for root in roots:
        path = (root / candidate).resolve()
        if path.is_file():
            return path
    return (request.project_root / candidate).resolve()


def _substitute(value: Any, tokens: Dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _substitute(item, tokens) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, tokens) for item in value]
    if isinstance(value, str):
        if value in tokens:
            return tokens[value]
        for token, replacement in tokens.items():
            if token in value:
                value = value.replace(token, str(replacement))
        return value
    return value


def _upload_references(
    base_url: str,
    request: AdapterRequest,
    timeout: float,
) -> tuple[Dict[str, Any], List[Dict[str, Any]], List[str]]:
    tokens: Dict[str, Any] = {}
    uploaded: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for index, ref in enumerate(request.reference_files(), 1):
        path = ref.get("file_path")
        if not path or not Path(path).is_file():
            raise AdapterHTTPError("参考图不存在：%s" % ref.get("source_path"))
        source = Path(path)
        response = post_multipart(
            join_url(base_url, "/upload/image"),
            fields={"overwrite": "true", "type": "input"},
            files=[("image", source.name, source.read_bytes(), image_content_type(source))],
            timeout=timeout,
        )
        name = str(response.get("name") or "")
        if not name:
            raise AdapterHTTPError("ComfyUI 上传响应缺少 name：%s" % response)
        subfolder = str(response.get("subfolder") or "")
        tokens["__CINELOCK_REF_%d__" % index] = name
        tokens["__CINELOCK_REF_%d_SUBFOLDER__" % index] = subfolder
        uploaded.append(
            {
                "order": ref.get("order") or index,
                "asset_id": ref.get("asset_id"),
                "name": name,
                "subfolder": subfolder,
                "sha256": ref.get("sha256"),
            }
        )
    if request.references and "__CINELOCK_REF_1__" not in tokens:
        warnings.append("上传了参考图，但工作流没有 __CINELOCK_REF_1__ 占位符")
    return tokens, uploaded, warnings


def _collect_outputs(entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    files: List[Dict[str, Any]] = []
    for node_id, output in (entry.get("outputs") or {}).items():
        if not isinstance(output, dict):
            continue
        for key in ("videos", "gifs", "images"):
            for item in output.get(key) or []:
                if isinstance(item, dict) and item.get("filename"):
                    files.append(
                        {
                            "node_id": node_id,
                            "kind": "video" if key in ("videos", "gifs") else "image",
                            "filename": item.get("filename"),
                            "subfolder": item.get("subfolder") or "",
                            "type": item.get("type") or "output",
                        }
                    )
    files.sort(key=lambda item: 0 if item["kind"] == "video" else 1)
    return files


def run(request: AdapterRequest) -> AdapterOutcome:
    base_url = normalize_base_url(
        request.option("base_url"),
        str(request.provider.get("base_url") or "http://127.0.0.1:8188"),
    )
    timeout = float(request.option("timeout_sec", 600))
    poll_interval = float(request.option("poll_interval_sec", 2.0))
    workflow_path = _resolve_workflow(request)
    if not workflow_path.is_file():
        return AdapterOutcome(
            status="failed",
            error="ComfyUI 工作流不存在：%s。复制 config/comfyui/workflow.example.json 并填入你的节点图。" % workflow_path,
            meta={"base_url": base_url, "workflow": str(workflow_path)},
        )

    try:
        import json

        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return AdapterOutcome(
            status="failed",
            error="ComfyUI 工作流不是合法 JSON：%s（%s）" % (workflow_path, exc),
            meta={"base_url": base_url, "workflow": str(workflow_path)},
        )
    if not isinstance(workflow, dict):
        return AdapterOutcome(status="failed", error="ComfyUI 工作流顶层必须是节点对象")

    variant = request.variant
    width, height = _resolution(variant)
    tokens: Dict[str, Any] = {
        "__CINELOCK_PROMPT__": request.prompt,
        "__CINELOCK_NEGATIVE__": request.negative_prompt,
        "__CINELOCK_SEED__": request.seed if request.seed is not None else 0,
        "__CINELOCK_DURATION__": int(round(request.duration_sec)) if request.duration_sec else 5,
        "__CINELOCK_FPS__": int(variant.get("fps") or 24),
        "__CINELOCK_WIDTH__": width,
        "__CINELOCK_HEIGHT__": height,
        "__CINELOCK_ASPECT_RATIO__": str(variant.get("aspect_ratio") or ""),
        "__CINELOCK_SHOT_ID__": str(variant.get("shot_id") or ""),
        "__CINELOCK_CONTEXT_REVISION__": str(variant.get("context_revision") or ""),
    }

    plan = [
        "上传 %d 张参考图到 %s/upload/image" % (len(request.references), base_url),
        "替换工作流占位符 → %s" % workflow_path,
        "提交 POST %s/prompt 并轮询 /history/{prompt_id}" % base_url,
        "下载产物到 outputs/%s.*" % request.job_id,
    ]
    meta: Dict[str, Any] = {
        "base_url": base_url,
        "workflow": str(workflow_path),
        "workflow_sha256": sha256_file(workflow_path),
        "timeout_sec": timeout,
        "started_at": utc_now(),
    }
    if request.dry_run:
        return AdapterOutcome(status="dry_run", plan=plan, meta=meta)

    warnings: List[str] = []
    try:
        ref_tokens, uploaded, upload_warnings = _upload_references(base_url, request, timeout)
        tokens.update(ref_tokens)
        warnings.extend(upload_warnings)
        meta["uploaded_references"] = uploaded

        prepared = _substitute(workflow, tokens)
        leftover = sorted(set(TOKEN_RE.findall(json.dumps(prepared, ensure_ascii=False))))
        if leftover:
            return AdapterOutcome(
                status="failed",
                warnings=warnings,
                error="工作流仍有未替换占位符：%s。检查工作流或补充参考图。" % ", ".join(leftover),
                meta=meta,
            )

        client_id = "cinelock-%s" % request.job_id
        submitted = request_json(
            join_url(base_url, "/prompt"),
            method="POST",
            payload={"prompt": prepared, "client_id": client_id},
            timeout=timeout,
        )
        prompt_id = str(submitted.get("prompt_id") or "")
        if not prompt_id:
            detail = submitted.get("error") or submitted.get("node_errors") or submitted
            return AdapterOutcome(
                status="failed",
                warnings=warnings,
                error="ComfyUI 拒绝工作流：%s" % str(detail)[:800],
                meta=meta,
            )
        meta["prompt_id"] = prompt_id
        meta["submitted_at"] = utc_now()

        def fetch_history():
            return request_json(
                join_url(base_url, "/history/%s" % prompt_id),
                timeout=timeout,
            )

        def is_done(payload: Any):
            if not isinstance(payload, dict) or prompt_id not in payload:
                return False, None
            entry = payload.get(prompt_id) or {}
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                messages = status.get("messages") or []
                raise AdapterHTTPError("ComfyUI 执行失败：%s" % str(messages)[:800])
            files = _collect_outputs(entry)
            if files or status.get("completed"):
                return True, entry
            return False, None

        try:
            entry, finished = poll(
                fetch_history,
                timeout_sec=timeout,
                interval_sec=poll_interval,
                is_done=is_done,
            )
        except AdapterHTTPError as exc:
            return AdapterOutcome(
                status="failed",
                warnings=warnings,
                error=str(exc),
                meta=meta,
            )

        files = _collect_outputs(finished or {})
        if not files:
            return AdapterOutcome(
                status="failed",
                warnings=warnings + ["工作流完成但没有声明 videos/gifs/images 输出"],
                error="ComfyUI 没有返回可下载产物",
                meta=meta,
            )

        outputs = []
        for index, item in enumerate(files, 1):
            filename = Path(str(item.get("filename"))).name
            suffix = Path(filename).suffix or ".bin"
            target = request.output_dir / ("%s%s" % (request.job_id, "" if index == 1 else "-%d" % index))
            if not target.suffix:
                target = target.with_suffix(suffix)
            query = "?filename=%s&subfolder=%s&type=%s" % (
                _quote(str(item.get("filename"))),
                _quote(str(item.get("subfolder") or "")),
                _quote(str(item.get("type") or "output")),
            )
            download_file(join_url(base_url, "/view") + query, target, timeout=timeout)
            kind = "video" if target.suffix.lower() in VIDEO_EXTENSIONS else "image"
            extra: Dict[str, Any] = {
                "node_id": item.get("node_id"),
                "filename": item.get("filename"),
            }
            if kind == "video":
                probe = probe_video(target)
                extra["probe"] = probe
                if not probe.get("ok"):
                    warnings.append("产物不是可解析视频（%s）：%s" % (filename, probe.get("error")))
            outputs.append(file_output(target, kind, request.project_root, **extra))

        meta["finished_at"] = utc_now()
        return AdapterOutcome(
            status="succeeded",
            outputs=outputs,
            warnings=warnings,
            meta=meta,
            plan=plan,
        )
    except AdapterHTTPError as exc:
        return AdapterOutcome(status="failed", warnings=warnings, error=str(exc), meta=meta)
    except Exception as exc:
        return AdapterOutcome(status="failed", warnings=warnings, error="ComfyUI 适配器异常：%s" % exc, meta=meta)


def _resolution(variant: Dict[str, Any]) -> tuple[int, int]:
    match = re.match(r"^(\d+)x(\d+)$", str(variant.get("resolution") or ""))
    if match:
        return int(match.group(1)), int(match.group(2))
    return 1920, 1080


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")
