from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

NODE_MIN_MAJOR = 20
TRUE_VALUES = ("1", "true", "yes", "on")

from ..context import ProjectContext
from ..jobs import outputs_dir
from ..media import probe_video
from ..util import write_json
from .common import AdapterOutcome, decode_output, file_output, remote_output, tail, tool_path

MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
USER_AGENT = "CineLock/0.2 (+local context orchestrator)"


class QuotaFlowError(Exception):
    pass


def _sibling_js_entry(shim: Path) -> Optional[Path]:
    """npm 全局 .cmd shim 旁边的真实 JS 入口。"""
    candidate = shim.parent / "node_modules" / "@quota-flow" / "cli" / "dist" / "cli.cjs"
    return candidate if candidate.is_file() else None


def _node_executable() -> str:
    override = os.environ.get("QUOTA_FLOW_NODE", "").strip()
    if override:
        return override
    return tool_path("node") or "node"


def _materialize_cli(path: Path) -> List[str]:
    suffix = path.suffix.lower()
    if suffix in (".js", ".mjs", ".cjs"):
        return [_node_executable(), str(path)]
    if suffix in (".cmd", ".bat"):
        entry = _sibling_js_entry(path)
        bundled = path.parent / "node.exe"
        if entry is not None and bundled.is_file():
            # nvm/全局安装自带的 node.exe 可能远新于 PATH 里的默认 node，直接用它跑入口。
            return [str(bundled), str(entry)]
    return [str(path)]


def _nvm_bins(root: Path) -> List[Path]:
    if not root.is_dir():
        return []
    version_dirs = [item for item in root.iterdir() if item.is_dir() and re.match(r"^v\d+", item.name)]
    version_dirs.sort(key=lambda item: [int(part) for part in re.findall(r"\d+", item.name)], reverse=True)
    return [item / "quota-flow.cmd" for item in version_dirs]


def _discover_cli() -> Optional[Path]:
    candidates: List[Path] = []
    for env_name in ("NVM_HOME", "NVM_SYMLINK"):
        value = os.environ.get(env_name, "").strip()
        if value:
            candidates.extend(_nvm_bins(Path(value)))
    local_app = os.environ.get("LOCALAPPDATA", "").strip()
    app_data = os.environ.get("APPDATA", "").strip()
    if local_app:
        candidates.extend(_nvm_bins(Path(local_app) / "nvm"))
    if app_data:
        candidates.extend(_nvm_bins(Path(app_data) / "nvm"))
        candidates.append(Path(app_data) / "npm" / "quota-flow.cmd")
    candidates.extend(
        [
            Path("C:/Program Files/nodejs/quota-flow.cmd"),
            Path("C:/Program Files (x86)/nodejs/quota-flow.cmd"),
            Path("/usr/local/bin/quota-flow"),
            Path.home() / ".local" / "bin" / "quota-flow",
            Path.home() / ".npm-global" / "bin" / "quota-flow",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _resolve_cli() -> Tuple[Optional[List[str]], List[str]]:
    warnings: List[str] = []
    env_path = os.environ.get("QUOTA_FLOW_CLI", "").strip()
    if env_path:
        path = Path(env_path).expanduser()
        if not path.is_file():
            warnings.append("QUOTA_FLOW_CLI 指向的文件不存在：%s" % env_path)
            return None, warnings
        return _materialize_cli(path), warnings

    for name in ("quota-flow", "quota-flow.cmd", "quota-flow.exe", "quota-flow.bat"):
        found = tool_path(name)
        if found:
            return _materialize_cli(Path(found)), warnings

    discovered = _discover_cli()
    if discovered is not None:
        return _materialize_cli(discovered), warnings

    warnings.append(
        "未找到 Quota-Flow CLI。安装后加入 PATH，或设置 QUOTA_FLOW_CLI 指向可执行文件/JS 入口。"
    )
    return None, warnings


def _cli_node(cli: List[str]) -> Optional[str]:
    if not cli:
        return None
    head = Path(cli[0])
    if len(cli) > 1 and head.name.lower().startswith("node"):
        return str(head)
    if head.suffix.lower() in (".cmd", ".bat"):
        bundled = head.parent / "node.exe"
        if bundled.is_file():
            return str(bundled)
    return tool_path("node")


def _node_major(node: Optional[str] = None) -> Optional[int]:
    node = node or tool_path("node")
    if not node:
        return None
    try:
        proc = subprocess.run([node, "--version"], capture_output=True, timeout=10)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    text = decode_output(proc.stdout).strip().lstrip("v")
    match = re.match(r"^(\d+)", text)
    return int(match.group(1)) if match else None


def _needs_node(cli: List[str]) -> bool:
    if not cli:
        return False
    if len(cli) > 1:
        return cli[1].lower().endswith((".js", ".mjs", ".cjs")) or Path(cli[0]).name.lower().startswith("node")
    return Path(cli[0]).name.lower().endswith((".cmd", ".bat"))


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _build_command(ctx: ProjectContext, variant: Dict[str, Any], cli: List[str]) -> Tuple[List[str], List[str]]:
    warnings: List[str] = []
    dispatch = variant.get("dispatch") or {}
    mode = variant.get("mode")
    qf_mode = dispatch.get("quota_flow_mode")
    qf_provider = dispatch.get("quota_flow_provider")
    urls = list(dispatch.get("image_urls") or [])
    defaults = ctx.project.get("defaults") or {}
    strategy = str(defaults.get("strategy") or "quality_first")
    fallback = _env_int("CINELOCK_QF_FALLBACK_ROUNDS", 0)
    command = list(cli) + [
        "generate",
        "--mode",
        str(qf_mode or ""),
        "--prompt",
        str(variant.get("prompt") or ""),
        "--provider",
        str(qf_provider or ""),
        "--strategy",
        strategy,
        "--fallback-rounds",
        str(fallback),
        "--json",
    ]
    engine = os.environ.get("CINELOCK_QF_ENGINE", "").strip()
    if engine:
        if engine in ("fetch", "browser"):
            command += ["--engine", engine]
        else:
            warnings.append("CINELOCK_QF_ENGINE=%s 非法，已忽略（可选 fetch / browser）" % engine)

    if mode == "img2video":
        if len(urls) != 1:
            warnings.append("图生视频需要恰好 1 张公网参考图，当前 %d 张" % len(urls))
        if urls:
            command += ["--imageUrl", urls[0]]
    elif mode in ("multi_ref", "first_last"):
        if not urls:
            warnings.append("多参考/首尾帧模式没有公网参考图")
        command += ["--imageUrls", ",".join(urls)]
    elif mode != "text2video":
        warnings.append("未知生成模式：%s" % mode)

    if fallback > 0:
        warnings.append("fallback-rounds=%d 可能切换到其他厂商，破坏逐厂商对比；建议设为 0" % fallback)
    warnings.append("Quota-Flow CLI 没有时长参数；编译期选择 %ss，实际时长由厂商模型决定" % variant.get("duration_sec"))
    warnings.append("Quota-Flow CLI 不传 seed；seed 仅用于记录与手工交接")
    return command, warnings


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    decoder = json.JSONDecoder()
    candidates: List[Dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(text, index)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if "ok" in obj or "result" in obj:
            return obj
        candidates.append(obj)
    return candidates[-1] if candidates else None


def _attempt_warnings(payload: Dict[str, Any]) -> List[str]:
    warnings = []
    for attempt in payload.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        if attempt.get("ok"):
            continue
        pid = attempt.get("providerId") or "?"
        reason = attempt.get("errorMessage") or attempt.get("error") or "失败"
        warnings.append("Quota-Flow 尝试 %s 失败：%s" % (pid, reason))
    return warnings


def _dry_run_note(payload: Dict[str, Any]) -> Optional[str]:
    result = payload.get("result") or {}
    raw = result.get("raw") or {}
    trace = str(result.get("traceId") or "").lower().replace("-", "")
    url = str(result.get("videoUrl") or result.get("downloadUrl") or "").lower()
    warning = str(raw.get("warning") or "")
    if "dryrun" in trace or "dry-run" in warning.lower() or "dryrun" in url:
        return warning.strip() or "Quota-Flow 返回 dry-run，没有生成真实视频"
    return None


def _provider_switch_allowed() -> bool:
    return os.environ.get("CINELOCK_QF_ALLOW_PROVIDER_SWITCH", "").strip().lower() in TRUE_VALUES


def _download(url: str, target: Path, timeout: int = 180) -> int:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise QuotaFlowError("视频 URL 不是 http(s)：%s" % url[:120])
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            length = response.headers.get("Content-Length")
            if length:
                try:
                    if int(length) > MAX_DOWNLOAD_BYTES:
                        raise QuotaFlowError("视频超过 %d MB 上限" % (MAX_DOWNLOAD_BYTES // (1024 * 1024)))
                except ValueError:
                    pass
            with part.open("wb") as fh:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise QuotaFlowError("视频超过 %d MB 上限" % (MAX_DOWNLOAD_BYTES // (1024 * 1024)))
                    fh.write(chunk)
        os.replace(str(part), str(target))
        return total
    finally:
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass


def _quota_flow_meta(payload: Optional[Dict[str, Any]], provider_id: Optional[str]) -> Dict[str, Any]:
    result = (payload or {}).get("result") or {}
    meta = {
        "trace_id": result.get("traceId"),
        "used_provider": result.get("providerId"),
        "quota_used": result.get("quotaUsed"),
        "quality_score": result.get("qualityScore"),
        "remote_url": result.get("videoUrl") or result.get("downloadUrl"),
        "rounds": (payload or {}).get("rounds"),
    }
    if provider_id and result.get("providerId") and result.get("providerId") != provider_id:
        meta["provider_mismatch"] = True
    return {key: value for key, value in meta.items() if value is not None}


def run(ctx: ProjectContext, variant: Dict[str, Any], job_id: str, *, dry_run: bool = False) -> AdapterOutcome:
    cli, warnings = _resolve_cli()
    cli_found = cli is not None
    if cli is None:
        cli = ["quota-flow"]

    if not dry_run and not (variant.get("dispatch") or {}).get("ready"):
        reasons = (variant.get("dispatch") or {}).get("block_reasons") or ["Quota-Flow 前置条件未满足"]
        return AdapterOutcome(status="blocked", error="；".join(str(x) for x in reasons), warnings=warnings)

    needs_node = _needs_node(cli)
    node = _cli_node(cli) if needs_node else None
    node_major = _node_major(node) if needs_node else None
    if needs_node:
        if node_major is None:
            warnings.append("未找到 Node.js；Quota-Flow CLI 需要 Node.js >= 20")
        elif node_major < NODE_MIN_MAJOR:
            warnings.append(
                "当前 Node.js %s（%s），低于 Quota-Flow 要求的 >= 20；真实执行可能失败"
                % (node_major, node or "node")
            )

    command, command_warnings = _build_command(ctx, variant, cli)
    warnings.extend(command_warnings)
    plan = [
        "调用 Quota-Flow：provider=%s，mode=%s，canonical=%s"
        % (
            (variant.get("dispatch") or {}).get("quota_flow_provider"),
            (variant.get("dispatch") or {}).get("quota_flow_mode"),
            variant.get("mode"),
        ),
        "使用 %d 张公网参考图" % len((variant.get("dispatch") or {}).get("image_urls") or []),
        "解析 --json 输出并下载视频 → outputs/%s.mp4" % job_id,
        "用 ffprobe 校验下载视频的时长、分辨率与编码",
        "保存原始输出 → outputs/%s.quota_flow.json" % job_id,
    ]

    if dry_run:
        return AdapterOutcome(status="dry_run", command=command, plan=plan, warnings=warnings)

    if not cli_found:
        return AdapterOutcome(
            status="blocked",
            command=command,
            warnings=warnings,
            error="未找到 Quota-Flow CLI，无法真实执行。请安装 CLI 或设置 QUOTA_FLOW_CLI。",
        )

    if needs_node and (node_major is None or node_major < NODE_MIN_MAJOR):
        return AdapterOutcome(
            status="blocked",
            command=command,
            warnings=warnings,
            error="Quota-Flow 需要 Node.js >= 20；当前 %s。请升级 Node 或设置 QUOTA_FLOW_NODE / QUOTA_FLOW_CLI。"
            % (("Node %s（%s）" % (node_major, node)) if node_major else "未安装 Node"),
        )

    timeout = max(30, _env_int("CINELOCK_QF_TIMEOUT_SEC", 1800))
    try:
        proc = subprocess.run(
            command,
            cwd=str(ctx.root),
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return AdapterOutcome(
            status="failed",
            command=command,
            warnings=warnings,
            error="Quota-Flow 执行超时（%ss）" % timeout,
        )
    except Exception as exc:
        return AdapterOutcome(
            status="failed",
            command=command,
            warnings=warnings,
            error="Quota-Flow 调用异常：%s" % exc,
        )

    stdout = decode_output(proc.stdout)
    stderr = decode_output(proc.stderr)
    payload = _extract_json(stdout)
    raw_path = outputs_dir(ctx) / ("%s.quota_flow.json" % job_id)
    if payload is not None:
        try:
            write_json(raw_path, payload)
        except Exception:
            pass

    if proc.returncode != 0:
        return AdapterOutcome(
            status="failed",
            command=command,
            stdout=tail(stdout),
            stderr=tail(stderr),
            warnings=warnings,
            error="Quota-Flow 退出码 %s%s" % (proc.returncode, _error_suffix(payload)),
            meta=_quota_flow_meta(payload, (variant.get("dispatch") or {}).get("quota_flow_provider")),
        )
    if payload is None:
        return AdapterOutcome(
            status="failed",
            command=command,
            stdout=tail(stdout),
            stderr=tail(stderr),
            warnings=warnings,
            error="无法从 Quota-Flow 输出中解析 JSON",
        )

    warnings.extend(_attempt_warnings(payload))
    if not payload.get("ok"):
        return AdapterOutcome(
            status="failed",
            command=command,
            stdout=tail(stdout),
            stderr=tail(stderr),
            warnings=warnings,
            error="Quota-Flow 生成失败%s" % _error_suffix(payload),
            meta=_quota_flow_meta(payload, (variant.get("dispatch") or {}).get("quota_flow_provider")),
        )

    result = payload.get("result") or {}
    requested_provider = (variant.get("dispatch") or {}).get("quota_flow_provider")
    meta = _quota_flow_meta(payload, requested_provider)
    used_provider = result.get("providerId")
    if requested_provider and used_provider and used_provider != requested_provider and not _provider_switch_allowed():
        warnings.append(
            "Quota-Flow 实际使用厂商 %s，与请求的 %s 不一致；已拒绝把这次结果记到 %s 名下。"
            % (used_provider, requested_provider, requested_provider)
        )
        if meta.get("quota_used"):
            warnings.append("注意：这次调用可能已经扣减了 %s 的本地额度。" % used_provider)
        outputs = [file_output(raw_path, "quota_flow_json", ctx.root)] if raw_path.is_file() else []
        return AdapterOutcome(
            status="failed",
            outputs=outputs,
            command=command,
            stdout=tail(stdout),
            stderr=tail(stderr),
            warnings=warnings,
            error="Quota-Flow 厂商不一致：请求 %s，实际 %s。设置 CINELOCK_QF_ALLOW_PROVIDER_SWITCH=1 可接受切换。"
            % (requested_provider, used_provider),
            meta=meta,
        )

    dry_note = _dry_run_note(payload)
    if dry_note:
        warnings.append("Quota-Flow 未生成真实视频：%s" % dry_note)
        if meta.get("quota_used"):
            warnings.append(
                "注意：CLI 在 dry-run 时仍可能扣减本地额度（quotaUsed=%s）；可用 quota-flow refresh 重置演示额度。"
                % meta.get("quota_used")
            )
        outputs = [file_output(raw_path, "quota_flow_json", ctx.root)] if raw_path.is_file() else []
        return AdapterOutcome(
            status="dry_run",
            outputs=outputs,
            command=command,
            stdout=tail(stdout),
            stderr=tail(stderr),
            warnings=warnings,
            meta=dict(meta, dry_run=True),
        )

    remote_url = result.get("videoUrl") or result.get("downloadUrl")
    if not remote_url:
        return AdapterOutcome(
            status="failed",
            command=command,
            stdout=tail(stdout),
            stderr=tail(stderr),
            warnings=warnings,
            error="Quota-Flow 返回成功但没有视频 URL",
            meta=meta,
        )

    outputs = []
    if raw_path.is_file():
        outputs.append(file_output(raw_path, "quota_flow_json", ctx.root))

    video_path = outputs_dir(ctx) / ("%s.mp4" % job_id)
    try:
        _download(str(remote_url), video_path)
    except Exception as exc:
        warnings.append("视频已生成但下载失败：%s；保留远程 URL" % exc)
        outputs.append(remote_output(str(remote_url), "remote_video", trace_id=meta.get("trace_id")))
        return AdapterOutcome(
            status="succeeded",
            outputs=outputs,
            command=command,
            stdout=tail(stdout),
            stderr=tail(stderr),
            warnings=warnings,
            meta=dict(meta, ffprobe=tool_path("ffprobe")),
        )

    probe = probe_video(video_path)
    probe_fields = {
        key: probe[key]
        for key in ("duration_sec", "width", "height", "codec", "format")
        if probe.get(key) is not None
    }
    outputs.append(file_output(video_path, "video", ctx.root, source_url=str(remote_url), **probe_fields))
    meta["probe"] = probe
    meta["ffprobe"] = tool_path("ffprobe")
    if not probe.get("available"):
        warnings.append("未找到 ffprobe；下载视频未做媒体完整性校验")
    elif not probe.get("ok"):
        warnings.append("视频下载成功但 ffprobe 校验失败：%s" % probe.get("error"))
        return AdapterOutcome(
            status="failed",
            outputs=outputs,
            command=command,
            stdout=tail(stdout),
            stderr=tail(stderr),
            warnings=warnings,
            error="下载视频未通过 ffprobe 校验：%s" % probe.get("error"),
            meta=meta,
        )

    return AdapterOutcome(
        status="succeeded",
        outputs=outputs,
        command=command,
        stdout=tail(stdout),
        stderr=tail(stderr),
        warnings=warnings,
        meta=meta,
    )


def _error_suffix(payload: Optional[Dict[str, Any]]) -> str:
    if not payload:
        return ""
    result = payload.get("result") or {}
    message = result.get("errorMessage") or result.get("error") or ""
    if message:
        return "：%s" % message
    steps = payload.get("nextSteps") or []
    if steps:
        return "：%s" % "；".join(str(x) for x in steps[:3])
    return ""
