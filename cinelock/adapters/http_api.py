from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..media import probe_video
from .common import AdapterOutcome, AdapterRequest, file_output
from .net import (
    AdapterHTTPError,
    download_file,
    env_value,
    get_path,
    image_base64,
    image_data_uri,
    join_url,
    normalize_base_url,
    poll,
    request_json,
)

KLING_BASE = "https://api.klingai.com"
RUNWAY_BASE = "https://api.dev.runwayml.com"
RUNWAY_VERSION = "2024-11-06"

SUCCESS_STATES = {"succeeded", "succeed", "success", "completed", "done", "finished"}
FAILURE_STATES = {"failed", "failure", "error", "cancelled", "canceled", "rejected"}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def kling_jwt(access_key: str, secret_key: str, *, now: Optional[float] = None) -> str:
    issued = int(now or time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"iss": access_key, "exp": issued + 1800, "nbf": issued - 5}
    segments = [
        _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8")),
        _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ]
    signing_input = ".".join(segments).encode("ascii")
    signature = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    segments.append(_b64url(signature))
    return ".".join(segments)


def _auth(request: AdapterRequest, preset: str) -> Tuple[Dict[str, str], Dict[str, Any]]:
    if preset == "kling":
        access_env = str(request.option("access_key_env") or "KLING_ACCESS_KEY")
        secret_env = str(request.option("secret_key_env") or "KLING_SECRET_KEY")
        access, missing = env_value(access_env)
        secret, missing_secret = env_value(secret_env)
        if not access or not secret:
            raise AdapterHTTPError(
                "缺少 Kling 凭证：请设置环境变量 %s 与 %s"
                % (", ".join([access_env] + missing_secret), secret_env)
            )
        return (
            {"Authorization": "Bearer %s" % kling_jwt(access, secret), "Content-Type": "application/json"},
            {"auth": "env"},
        )
    if preset == "runway":
        key_env = str(request.option("api_key_env") or "RUNWAY_API_KEY")
        key, _ = env_value(key_env)
        if not key:
            raise AdapterHTTPError("缺少 Runway 凭证：请设置环境变量 %s" % key_env)
        return (
            {
                "Authorization": "Bearer %s" % key,
                "X-Runway-Version": str(request.option("api_version") or RUNWAY_VERSION),
                "Content-Type": "application/json",
            },
            {"auth": "env"},
        )

    key_env = request.option("api_key_env")
    headers = {"Content-Type": "application/json"}
    if key_env:
        key, _ = env_value(key_env)
        if not key:
            raise AdapterHTTPError("缺少 API 凭证：请设置环境变量 %s" % key_env)
        header = str(request.option("auth_header") or "Authorization")
        prefix = str(request.option("auth_prefix") if request.option("auth_prefix") is not None else "Bearer ")
        headers[header] = prefix + key
    return headers, {"auth": "env" if key_env else "none"}


def _reference_value(
    request: AdapterRequest,
    ref: Dict[str, Any],
    *,
    mode: str,
    purpose: str,
) -> str:
    if mode == "url":
        url = str(ref.get("public_url") or "")
        if not url:
            raise AdapterHTTPError("参考图 %s 缺少 public_url，无法按 URL 模式提交" % ref.get("asset_id"))
        return url
    path = ref.get("file_path")
    if not path or not Path(path).is_file():
        raise AdapterHTTPError("参考图不存在：%s" % ref.get("source_path"))
    if mode == "data_uri":
        return image_data_uri(Path(path))
    return image_base64(Path(path))


def _first_reference(request: AdapterRequest) -> Optional[Dict[str, Any]]:
    refs = request.reference_files()
    return refs[0] if refs else None


def _last_reference(request: AdapterRequest) -> Optional[Dict[str, Any]]:
    refs = request.reference_files()
    return refs[1] if len(refs) > 1 else None


def _ratio(request: AdapterRequest) -> str:
    aspect = str(request.variant.get("aspect_ratio") or "16:9")
    mapping = request.option("ratio_map") or {}
    if isinstance(mapping, dict) and aspect in mapping:
        return str(mapping[aspect])
    return aspect


def _kling_payload(request: AdapterRequest) -> Tuple[str, Dict[str, Any]]:
    variant = request.variant
    mode = str(variant.get("mode") or "text2video")
    endpoint = "/v1/videos/image2video" if mode in ("img2video", "first_last") else "/v1/videos/text2video"
    image_mode = str(request.option("image_input") or "base64")
    payload: Dict[str, Any] = {
        "model_name": str(request.option("model") or "kling-v1"),
        "prompt": request.prompt,
        "mode": str(request.option("api_mode") or "std"),
        "duration": str(int(round(request.duration_sec)) or 5),
    }
    if request.negative_prompt:
        payload["negative_prompt"] = request.negative_prompt
    if endpoint.endswith("text2video"):
        payload["aspect_ratio"] = _ratio(request)
    else:
        first = _first_reference(request)
        if first is None:
            raise AdapterHTTPError("Kling 图生视频缺少首帧参考图")
        payload["image"] = _reference_value(request, first, mode=image_mode, purpose="first")
        if mode == "first_last":
            last = _last_reference(request)
            if last is None:
                raise AdapterHTTPError("Kling 首尾帧模式缺少尾帧参考图")
            payload["image_tail"] = _reference_value(request, last, mode=image_mode, purpose="last")
    return endpoint, payload


def _run_kling(request: AdapterRequest) -> AdapterOutcome:
    base_url = normalize_base_url(request.option("base_url"), str(request.provider.get("base_url") or KLING_BASE))
    timeout = float(request.option("timeout_sec", 900))
    poll_interval = float(request.option("poll_interval_sec", 5.0))
    endpoint, payload = _kling_payload(request)
    plan = [
        "提交 Kling %s → %s%s" % (request.variant.get("mode"), base_url, endpoint),
        "轮询 %s%s/{task_id}" % (base_url, endpoint),
        "下载视频并记录 sha256 / ffprobe",
    ]
    meta: Dict[str, Any] = {
        "preset": "kling",
        "base_url": base_url,
        "endpoint": endpoint,
        "model": payload.get("model_name"),
    }
    if request.dry_run:
        return AdapterOutcome(status="dry_run", plan=plan, meta=meta)

    headers, auth_meta = _auth(request, "kling")
    meta.update(auth_meta)
    submitted = request_json(join_url(base_url, endpoint), method="POST", payload=payload, headers=headers, timeout=timeout)
    code = submitted.get("code")
    if code not in (0, None):
        return AdapterOutcome(
            status="failed",
            error="Kling 拒绝任务（code=%s）：%s" % (code, submitted.get("message") or submitted),
            meta=meta,
        )
    task_id = str(get_path(submitted, "data.task_id") or "")
    if not task_id:
        return AdapterOutcome(status="failed", error="Kling 响应缺少 task_id：%s" % submitted, meta=meta)
    meta["task_id"] = task_id

    def fetch():
        return request_json(join_url(base_url, "%s/%s" % (endpoint, task_id)), headers=headers, timeout=timeout)

    def is_done(payload_data: Any):
        state = str(get_path(payload_data, "data.task_status") or "").lower()
        if state in FAILURE_STATES:
            raise AdapterHTTPError(
                "Kling 任务失败：%s" % (get_path(payload_data, "data.task_status_msg") or state)
            )
        if state in ("succeed", "success", "succeeded", "completed"):
            url = get_path(payload_data, "data.task_result.videos.0.url")
            if not url:
                raise AdapterHTTPError("Kling 任务成功但没有视频 URL：%s" % payload_data)
            return True, [str(url)]
        return False, None

    try:
        _, urls = poll(fetch, timeout_sec=timeout, interval_sec=poll_interval, is_done=is_done)
    except AdapterHTTPError as exc:
        return AdapterOutcome(status="failed", error=str(exc), meta=meta)
    return _finish_downloads(request, urls, meta, warnings=[], plan=plan)


def _runway_payload(request: AdapterRequest) -> Tuple[str, Dict[str, Any]]:
    mode = str(request.variant.get("mode") or "text2video")
    endpoint = "/v1/image_to_video" if mode in ("img2video", "first_last") else "/v1/text_to_video"
    payload: Dict[str, Any] = {
        "model": str(request.option("model") or "gen3a_turbo"),
        "promptText": request.prompt,
        "duration": int(round(request.duration_sec)) or 5,
        "ratio": _ratio(request),
    }
    if request.option("send_seed", False) and request.seed is not None:
        payload["seed"] = request.seed
    if endpoint.endswith("image_to_video"):
        first = _first_reference(request)
        if first is None:
            raise AdapterHTTPError("Runway 图生视频缺少首帧参考图")
        image_mode = str(request.option("image_input") or "data_uri")
        payload["promptImage"] = _reference_value(request, first, mode=image_mode, purpose="first")
        if mode == "first_last" and request.option("supports_last_frame", False):
            last = _last_reference(request)
            if last:
                payload["promptImageLast"] = _reference_value(request, last, mode=image_mode, purpose="last")
    return endpoint, payload


def _run_runway(request: AdapterRequest) -> AdapterOutcome:
    base_url = normalize_base_url(request.option("base_url"), str(request.provider.get("base_url") or RUNWAY_BASE))
    timeout = float(request.option("timeout_sec", 900))
    poll_interval = float(request.option("poll_interval_sec", 5.0))
    endpoint, payload = _runway_payload(request)
    plan = [
        "提交 Runway %s → %s%s" % (request.variant.get("mode"), base_url, endpoint),
        "轮询 %s/v1/tasks/{task_id}" % base_url,
        "下载视频并记录 sha256 / ffprobe",
    ]
    meta: Dict[str, Any] = {
        "preset": "runway",
        "base_url": base_url,
        "endpoint": endpoint,
        "model": payload.get("model"),
    }
    if request.dry_run:
        return AdapterOutcome(status="dry_run", plan=plan, meta=meta)

    headers, auth_meta = _auth(request, "runway")
    meta.update(auth_meta)
    submitted = request_json(join_url(base_url, endpoint), method="POST", payload=payload, headers=headers, timeout=timeout)
    task_id = str(submitted.get("id") or "")
    if not task_id:
        return AdapterOutcome(status="failed", error="Runway 响应缺少任务 id：%s" % submitted, meta=meta)
    meta["task_id"] = task_id

    def fetch():
        return request_json(
            join_url(base_url, "/v1/tasks/%s" % task_id),
            headers=headers,
            timeout=timeout,
        )

    def is_done(payload_data: Any):
        state = str(get_path(payload_data, "status") or "").upper()
        if state in ("FAILED", "CANCELLED", "CANCELED"):
            raise AdapterHTTPError(
                "Runway 任务失败：%s" % (get_path(payload_data, "failure") or state)
            )
        if state == "SUCCEEDED":
            output = get_path(payload_data, "output") or []
            if isinstance(output, str):
                output = [output]
            if not output:
                raise AdapterHTTPError("Runway 任务成功但没有输出：%s" % payload_data)
            return True, [str(item) for item in output]
        return False, None

    try:
        _, urls = poll(fetch, timeout_sec=timeout, interval_sec=poll_interval, is_done=is_done)
    except AdapterHTTPError as exc:
        return AdapterOutcome(status="failed", error=str(exc), meta=meta)
    return _finish_downloads(request, urls, meta, warnings=[], plan=plan)


def _generic_payload(request: AdapterRequest) -> Dict[str, Any]:
    template = request.option("payload_template")
    first = _first_reference(request)
    last = _last_reference(request)
    image_mode = str(request.option("image_input") or "data_uri")
    values = {
        "prompt": request.prompt,
        "negative_prompt": request.negative_prompt,
        "duration": int(round(request.duration_sec)) or 5,
        "seed": request.seed,
        "aspect_ratio": str(request.variant.get("aspect_ratio") or ""),
        "resolution": str(request.variant.get("resolution") or ""),
        "fps": request.variant.get("fps"),
        "shot_id": request.variant.get("shot_id"),
        "context_revision": request.variant.get("context_revision"),
        "first_image": _reference_value(request, first, mode=image_mode, purpose="first") if first else None,
        "last_image": _reference_value(request, last, mode=image_mode, purpose="last") if last else None,
    }
    if isinstance(template, dict):
        def fill(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: fill(item) for key, item in value.items()}
            if isinstance(value, list):
                return [fill(item) for item in value]
            if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
                return values.get(value[2:-2].strip(), value)
            if isinstance(value, str):
                for key, item in values.items():
                    value = value.replace("{{%s}}" % key, "" if item is None else str(item))
                return value
            return value

        return fill(template)
    return {
        "prompt": request.prompt,
        "negative_prompt": request.negative_prompt,
        "duration": values["duration"],
        "seed": request.seed,
        "aspect_ratio": values["aspect_ratio"],
        "image": values["first_image"],
        "last_frame": values["last_image"],
    }


def _generic_video_url(payload: Any, configured: Any) -> Optional[str]:
    paths = []
    if configured:
        paths.append(str(configured))
    paths += ["output.0", "video_url", "data.video_url", "result.video_url", "data.videos.0"]
    for path in paths:
        value = get_path(payload, path)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return None


def _run_generic(request: AdapterRequest) -> AdapterOutcome:
    submit_url = request.option("submit_url")
    if not submit_url:
        return AdapterOutcome(status="failed", error="http_api 适配器缺少 submit_url 配置")
    base_url = str(request.option("base_url") or "")
    submit_url = join_url(base_url, str(submit_url)) if base_url else str(submit_url)
    status_url = request.option("status_url")
    if not status_url:
        return AdapterOutcome(status="failed", error="http_api 适配器缺少 status_url 配置（可用 {task_id}）")
    status_url = join_url(base_url, str(status_url)) if base_url else str(status_url)
    timeout = float(request.option("timeout_sec", 900))
    poll_interval = float(request.option("poll_interval_sec", 5.0))
    payload = _generic_payload(request)
    plan = [
        "提交 %s → %s" % (request.variant.get("provider_id"), submit_url),
        "轮询 %s" % status_url,
        "下载视频并记录 sha256 / ffprobe",
    ]
    meta: Dict[str, Any] = {
        "preset": "generic",
        "submit_url": submit_url,
        "status_url": status_url,
    }
    if request.dry_run:
        return AdapterOutcome(status="dry_run", plan=plan, meta=meta)

    headers, auth_meta = _auth(request, "generic")
    meta.update(auth_meta)
    submitted = request_json(submit_url, method=str(request.option("method") or "POST"), payload=payload, headers=headers, timeout=timeout)
    task_path = str(request.option("task_id_path") or "task_id")
    task_id = get_path(submitted, task_path)
    if task_id is None or str(task_id) == "":
        return AdapterOutcome(status="failed", error="HTTP API 响应缺少任务 ID（%s）：%s" % (task_path, submitted), meta=meta)
    meta["task_id"] = str(task_id)
    status_path = str(request.option("status_path") or "status")
    success_values = {str(x).lower() for x in (request.option("success_values") or SUCCESS_STATES)}
    failure_values = {str(x).lower() for x in (request.option("failure_values") or FAILURE_STATES)}
    video_path = request.option("video_url_path")

    def fetch():
        return request_json(
            str(status_url).replace("{task_id}", str(task_id)),
            headers=headers,
            timeout=timeout,
        )

    def is_done(payload_data: Any):
        state = str(get_path(payload_data, status_path) or "").lower()
        if state in failure_values:
            raise AdapterHTTPError("HTTP API 任务失败：%s" % (get_path(payload_data, str(request.option("error_path") or "error")) or state))
        if state in success_values:
            url = _generic_video_url(payload_data, video_path)
            if not url:
                raise AdapterHTTPError("HTTP API 任务成功但没有视频 URL：%s" % payload_data)
            return True, [url]
        return False, None

    try:
        _, urls = poll(fetch, timeout_sec=timeout, interval_sec=poll_interval, is_done=is_done)
    except AdapterHTTPError as exc:
        return AdapterOutcome(status="failed", error=str(exc), meta=meta)
    return _finish_downloads(request, urls, meta, warnings=[], plan=plan)


def _finish_downloads(
    request: AdapterRequest,
    urls: List[str],
    meta: Dict[str, Any],
    *,
    warnings: List[str],
    plan: List[str],
) -> AdapterOutcome:
    outputs = []
    for index, url in enumerate(urls, 1):
        suffix = Path(url.split("?")[0]).suffix.lower()
        if suffix not in (".mp4", ".webm", ".mov", ".mkv", ".gif"):
            suffix = ".mp4"
        target = request.output_dir / ("%s%s" % (request.job_id, "" if index == 1 else "-%d" % index))
        if not target.suffix:
            target = target.with_suffix(suffix)
        try:
            download_file(url, target, timeout=float(request.option("download_timeout_sec", 600)))
        except AdapterHTTPError as exc:
            return AdapterOutcome(status="failed", outputs=outputs, warnings=warnings, error="视频下载失败：%s" % exc, meta=meta)

        kind = "video" if target.suffix.lower() in (".mp4", ".webm", ".mov", ".mkv") else "artifact"
        extra: Dict[str, Any] = {"remote_url": url}
        if kind == "video":
            probe = probe_video(target)
            extra["probe"] = probe
            if not probe.get("ok"):
                warnings.append("下载产物不是可解析视频：%s" % probe.get("error"))
        outputs.append(file_output(target, kind, request.project_root, **extra))
    meta["downloaded"] = len(outputs)
    return AdapterOutcome(status="succeeded", outputs=outputs, warnings=warnings, meta=meta, plan=plan)


def run(request: AdapterRequest) -> AdapterOutcome:
    preset = str(request.option("preset") or request.provider.get("preset") or "generic").lower()
    try:
        if preset == "kling":
            return _run_kling(request)
        if preset == "runway":
            return _run_runway(request)
        return _run_generic(request)
    except AdapterHTTPError as exc:
        return AdapterOutcome(status="failed", error=str(exc), meta={"preset": preset})
    except Exception as exc:
        return AdapterOutcome(status="failed", error="HTTP API 适配器异常：%s" % exc, meta={"preset": preset})
