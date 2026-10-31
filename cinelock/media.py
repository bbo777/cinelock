from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


class MediaError(Exception):
    pass


def _decode(data: bytes) -> str:
    if not data:
        return ""
    for encoding in ("utf-8", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _tail(text: str, limit: int = 1200) -> str:
    text = text or ""
    return text if len(text) <= limit else "…" + text[-limit:]


def probe_video(path: Path, *, timeout: int = 60) -> Dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {"ok": False, "available": False, "error": "未找到 ffprobe"}
    if not path.is_file():
        return {"ok": False, "available": True, "error": "文件不存在：%s" % path}

    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration,size,format_name:stream=index,codec_type,codec_name,width,height,duration",
        "-of",
        "json",
        str(path),
    ]
    try:
        proc = subprocess.run(command, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "available": True, "error": "ffprobe 超时（%ss）" % timeout}
    except Exception as exc:
        return {"ok": False, "available": True, "error": "ffprobe 调用失败：%s" % exc}

    if proc.returncode != 0:
        return {
            "ok": False,
            "available": True,
            "error": "ffprobe 退出码 %s：%s" % (proc.returncode, _tail(_decode(proc.stderr))),
        }
    try:
        payload = json.loads(_decode(proc.stdout))
    except Exception as exc:
        return {"ok": False, "available": True, "error": "ffprobe 输出不是 JSON：%s" % exc}

    streams = payload.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not video:
        return {"ok": False, "available": True, "error": "文件没有视频流"}

    fmt = payload.get("format") or {}
    duration = video.get("duration") or fmt.get("duration")
    try:
        duration_sec = round(float(duration), 3)
    except (TypeError, ValueError):
        duration_sec = None
    width = video.get("width")
    height = video.get("height")
    if not duration_sec or duration_sec <= 0:
        return {"ok": False, "available": True, "error": "视频时长无效"}
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        return {"ok": False, "available": True, "error": "视频分辨率无效"}

    size = fmt.get("size")
    try:
        size_bytes = int(size) if size is not None else path.stat().st_size
    except (TypeError, ValueError, OSError):
        size_bytes = path.stat().st_size

    return {
        "ok": True,
        "available": True,
        "duration_sec": duration_sec,
        "width": width,
        "height": height,
        "codec": video.get("codec_name"),
        "format": fmt.get("format_name"),
        "size": size_bytes,
        "path": str(path),
    }


def create_contact_sheet(
    video_path: Path,
    output_path: Path,
    *,
    columns: int = 3,
    rows: int = 3,
    timeout: int = 180,
) -> Dict[str, Any]:
    if columns < 1 or rows < 1 or columns * rows > 36:
        raise MediaError("九宫格行列数非法：%s x %s" % (columns, rows))
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise MediaError("未找到 ffmpeg，无法生成抽帧九宫格")

    probe = probe_video(video_path)
    if not probe.get("ok"):
        raise MediaError(str(probe.get("error") or "视频无法解析"))

    duration = float(probe["duration_sec"])
    frame_count = columns * rows
    rate = max(0.01, frame_count / max(duration, 0.05))
    cell_width = max(2, (1920 // columns) // 2 * 2)
    cell_height = max(2, (1080 // rows) // 2 * 2)
    vf = (
        "fps=%.6f,scale=%d:%d:force_original_aspect_ratio=decrease,"
        "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black,tile=%dx%d"
        % (rate, cell_width, cell_height, cell_width, cell_height, columns, rows)
    )
    command = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vf",
        vf,
        "-frames:v",
        "1",
        "-f",
        "image2",
        str(output_path),
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(output_path.stem + ".tmp" + output_path.suffix)
    if temp_path.exists():
        temp_path.unlink()
    command[-1] = str(temp_path)
    try:
        proc = subprocess.run(command, capture_output=True, timeout=timeout)
        if proc.returncode != 0 or not temp_path.is_file() or temp_path.stat().st_size == 0:
            raise MediaError(
                "ffmpeg 抽帧失败（exit=%s）：%s"
                % (proc.returncode, _tail(_decode(proc.stderr)))
            )
        os.replace(str(temp_path), str(output_path))
    except subprocess.TimeoutExpired:
        raise MediaError("ffmpeg 抽帧超时（%ss）" % timeout)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    timestamps: List[float] = [
        round((index + 0.5) * duration / frame_count, 3) for index in range(frame_count)
    ]
    return {
        "output": str(output_path),
        "bytes": output_path.stat().st_size,
        "width": cell_width * columns,
        "height": cell_height * rows,
        "columns": columns,
        "rows": rows,
        "timestamps": timestamps,
        "probe": probe,
    }
