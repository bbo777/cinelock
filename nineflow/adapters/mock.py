from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..context import ProjectContext
from ..jobs import outputs_dir
from .common import AdapterOutcome, decode_output, file_output, tail, tool_path

FONT_CANDIDATES = (
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/seguisb.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def _font(size: int):
    from PIL import ImageFont

    for candidate in FONT_CANDIDATES:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _resolution(variant: Dict[str, Any]) -> Tuple[int, int]:
    match = re.match(r"^(\d+)x(\d+)$", str(variant.get("resolution") or ""))
    if match:
        return int(match.group(1)), int(match.group(2))
    return 1920, 1080


def _render_slate(path: Path, variant: Dict[str, Any], job_id: str) -> None:
    from PIL import Image, ImageDraw

    width, height = _resolution(variant)
    img = Image.new("RGB", (width, height), (14, 23, 38))
    draw = ImageDraw.Draw(img)

    accent = (232, 163, 61)
    muted = (122, 143, 166)
    text = (238, 241, 245)
    ghost = (24, 37, 58)

    draw.rectangle([0, 0, width, 12], fill=accent)
    for x in range(0, width, 160):
        draw.line([(x, 0), (x, height)], fill=(19, 30, 48), width=1)
    for y in range(0, height, 160):
        draw.line([(0, y), (width, y)], fill=(19, 30, 48), width=1)

    draw.text((width * 0.72, height * 0.5), "MOCK", font=_font(int(height * 0.24)), fill=ghost, anchor="mm")

    margin = int(width * 0.052)
    draw.text((margin, int(height * 0.07)), "NINEFLOW / MOCK ADAPTER", font=_font(int(height * 0.026)), fill=accent)
    draw.text(
        (width - margin, int(height * 0.07)),
        job_id,
        font=_font(int(height * 0.022)),
        fill=muted,
        anchor="ra",
    )

    draw.text((margin, int(height * 0.17)), str(variant.get("shot_id") or ""), font=_font(int(height * 0.12)), fill=text)

    provider = str(variant.get("provider_id") or "")
    mode = str(variant.get("mode_label") or variant.get("mode") or "")
    duration = variant.get("duration_sec")
    subtitle = "%s  /  %s  /  %ss" % (provider, mode, duration)
    draw.text((margin, int(height * 0.35)), subtitle, font=_font(int(height * 0.042)), fill=text)

    fps = variant.get("fps")
    res = variant.get("resolution")
    refs = variant.get("references") or []
    draw.text(
        (margin, int(height * 0.44)),
        "DURATION %ss   RESOLUTION %s   FPS %s   REFERENCES %d" % (duration, res, fps, len(refs)),
        font=_font(int(height * 0.028)),
        fill=muted,
    )
    draw.text(
        (margin, int(height * 0.51)),
        "PROMPT %s   CONTEXT %s" % ((variant.get("prompt_sha256") or "")[:12], variant.get("short_revision") or ""),
        font=_font(int(height * 0.026)),
        fill=muted,
    )

    ref_text = " / ".join(str(item.get("asset_id") or "") for item in refs[:6])
    if len(ref_text) > 118:
        ref_text = ref_text[:115] + "..."
    draw.text((margin, int(height * 0.60)), "REFS  " + (ref_text or "none"), font=_font(int(height * 0.023)), fill=muted)

    banner_y = int(height * 0.83)
    draw.rounded_rectangle(
        [margin, banner_y, width - margin, banner_y + int(height * 0.09)],
        radius=int(height * 0.012),
        fill=(31, 45, 66),
        outline=accent,
        width=3,
    )
    draw.text(
        (width / 2, banner_y + int(height * 0.045)),
        "PLACEHOLDER SLATE — NOT A MODEL RENDER",
        font=_font(int(height * 0.034)),
        fill=text,
        anchor="mm",
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")


def _build_command(slate_rel: str, video_rel: str, duration: float, fps: int, width: int, height: int) -> list:
    ffmpeg = tool_path("ffmpeg") or "ffmpeg"
    vf = "scale=%d:%d,format=yuv420p,fade=t=in:st=0:d=0.5" % (width, height)
    return [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-loop",
        "1",
        "-i",
        slate_rel,
        "-t",
        "%.3f" % duration,
        "-r",
        str(fps),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        video_rel,
    ]


def _probe(root: Path, rel: str) -> Dict[str, Any]:
    ffprobe = tool_path("ffprobe")
    if not ffprobe:
        return {}
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration,size:stream=width,height,codec_name",
        "-of",
        "json",
        rel,
    ]
    try:
        proc = subprocess.run(cmd, cwd=str(root), capture_output=True, timeout=60)
    except Exception:
        return {}
    if proc.returncode != 0:
        return {}
    try:
        data = json.loads(decode_output(proc.stdout))
    except Exception:
        return {}
    out: Dict[str, Any] = {}
    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    if fmt.get("duration"):
        try:
            out["duration_sec"] = round(float(fmt["duration"]), 3)
        except (TypeError, ValueError):
            pass
    if streams:
        stream = streams[0]
        out["width"] = stream.get("width")
        out["height"] = stream.get("height")
        out["codec"] = stream.get("codec_name")
    return out


def run(ctx: ProjectContext, variant: Dict[str, Any], job_id: str, *, dry_run: bool = False) -> AdapterOutcome:
    width, height = _resolution(variant)
    duration = float(variant.get("duration_sec") or 5)
    fps = int(variant.get("fps") or 24)
    out_dir = outputs_dir(ctx)
    slate_path = out_dir / ("%s.slate.png" % job_id)
    video_path = out_dir / ("%s.mp4" % job_id)
    slate_rel = "outputs/%s.slate.png" % job_id
    video_rel = "outputs/%s.mp4" % job_id
    command = _build_command(slate_rel, video_rel, duration, fps, width, height)

    warnings = []
    if not tool_path("ffmpeg"):
        warnings.append("未找到 ffmpeg；mock 适配器无法编码占位视频")
    if not tool_path("ffprobe"):
        warnings.append("未找到 ffprobe；输出视频无法回读时长/分辨率元数据")

    meta = {
        "engine": "pillow+ffmpeg",
        "ffmpeg": tool_path("ffmpeg"),
        "ffprobe": tool_path("ffprobe"),
        "requested": {"duration_sec": duration, "width": width, "height": height, "fps": fps},
    }

    if dry_run:
        plan = [
            "绘制占位底板 %s" % slate_rel,
            "用 ffmpeg 编码 %.1fs / %dx%d / %dfps 占位视频 → %s" % (duration, width, height, fps, video_rel),
        ]
        return AdapterOutcome(status="dry_run", command=command, plan=plan, warnings=warnings, meta=meta)

    if not tool_path("ffmpeg"):
        return AdapterOutcome(
            status="failed",
            command=command,
            warnings=warnings,
            error="未找到 ffmpeg。请先安装 ffmpeg 并加入 PATH，再运行 mock 生成。",
        )

    try:
        _render_slate(slate_path, variant, job_id)
    except Exception as exc:
        return AdapterOutcome(
            status="failed",
            command=command,
            warnings=warnings,
            error="占位底板绘制失败：%s（mock 适配器需要 Pillow）" % exc,
        )

    try:
        proc = subprocess.run(command, cwd=str(ctx.root), capture_output=True, timeout=180)
    except Exception as exc:
        return AdapterOutcome(
            status="failed",
            command=command,
            warnings=warnings,
            error="ffmpeg 调用异常：%s" % exc,
        )

    stdout = decode_output(proc.stdout)
    stderr = decode_output(proc.stderr)
    if proc.returncode != 0 or not video_path.is_file() or video_path.stat().st_size == 0:
        return AdapterOutcome(
            status="failed",
            command=command,
            stdout=tail(stdout),
            stderr=tail(stderr),
            warnings=warnings,
            error="ffmpeg 编码失败（exit=%s）" % proc.returncode,
        )

    probe = _probe(ctx.root, video_rel)
    outputs = [
        file_output(slate_path, "slate", ctx.root),
        file_output(video_path, "video", ctx.root, **probe),
    ]
    meta["probe"] = probe
    return AdapterOutcome(
        status="succeeded",
        outputs=outputs,
        command=command,
        stdout=tail(stdout),
        stderr=tail(stderr),
        warnings=warnings,
        meta=meta,
    )
