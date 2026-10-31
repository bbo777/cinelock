from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List

from ..util import resolve_within, utc_now, write_json, write_text
from .common import AdapterOutcome, AdapterRequest, file_output

ROLE_HINTS = {
    "identity": "身份锚点：优先上传，保证脸、发型和球衣号码",
    "geometry": "几何/侧面：约束脸型、发量与身体比例",
    "expression": "表情参考：锁定本镜情绪",
    "injury": "伤情状态：淤青、破口、撕裂球衣等必须延续",
    "wardrobe": "服装状态：本镜的脏污/服装版本",
    "scene": "场景参考：地点、光线和构图",
    "style": "风格锚点",
    "override": "镜头级覆盖参考",
    "first_frame": "首帧",
    "last_frame": "尾帧",
}


def _safe(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "")).strip("._") or "ref"


def _readme(project_id: str, variant: Dict[str, Any], job_id: str, manifest: Dict[str, Any]) -> str:
    lines = [
        "# 手工交接包 · %s" % variant.get("shot_id"),
        "",
        "由 CineLock 生成。目标模型可以是任何支持多参考图/图生视频的平台。",
        "",
        "## 参数",
        "",
        "- 镜头：`%s`" % variant.get("shot_id"),
        "- 厂商变体：`%s`（%s）" % (variant.get("provider_id"), variant.get("provider", {}).get("display_name")),
        "- 模式：`%s`（%s）" % (variant.get("mode"), variant.get("mode_label")),
        "- 时长：%s 秒" % variant.get("duration_sec"),
        "- 画幅：%s，分辨率 %s，%s fps" % (variant.get("aspect_ratio"), variant.get("resolution"), variant.get("fps")),
        "- Seed：%s（若目标模型支持）" % variant.get("seed"),
        "- 上下文版本：`%s`" % variant.get("context_revision"),
        "- 提示词哈希：`%s`" % variant.get("prompt_sha256"),
        "- 项目：`%s`" % project_id,
        "- 任务：`%s`" % job_id,
        "",
        "## 使用步骤",
        "",
        "1. 打开目标模型的视频生成界面。",
        "2. 按顺序上传 `refs/` 下的参考图；第 1 张必须是身份锚点，不要改顺序。",
        "3. 把 `prompt.txt` 粘贴到正向提示词框。",
    ]
    if manifest.get("negative_file"):
        lines.append("4. 如果有负向提示词框，粘贴 `negative.txt` 的内容。")
    else:
        lines.append("4. 该变体没有独立负向提示词文件；负向约束已按厂商能力处理。")
    lines += [
        "5. 设置上面列出的时长、画幅和分辨率；模型不支持目标时长时选最接近的值。",
        "6. 若模型支持首尾帧，按 manifest 中 `role` 为 `first_frame` / `last_frame` 的图使用；若只支持单图，只用第 1 张身份锚点。",
        "7. 生成后不要用同一提示词重新随机抽卡时丢掉参考图；身份锚点必须每次都带上。",
        "",
        "## 参考图",
        "",
        "| 顺序 | 文件 | asset_id | 用途 |",
        "| --- | --- | --- | --- |",
    ]
    for ref in manifest.get("references") or []:
        lines.append(
            "| %s | `%s` | `%s` | %s |"
            % (
                ref.get("order"),
                ref.get("file"),
                ref.get("asset_id"),
                ROLE_HINTS.get(str(ref.get("role")), ref.get("role") or ""),
            )
        )
    lines += [
        "",
        "## 说明",
        "",
        "- 参考图顺序和多参考组合是角色一致性的主要来源，优先保证身份锚点。",
        "- 本包不包含 Cookie、API Key 或账号登录态。",
        "- 提示词与参考图来自同一个 Context Pack；换了角色/时间线后请重新导出，不要混用旧包。",
        "",
    ]
    return "\n".join(lines)


def run(request: AdapterRequest) -> AdapterOutcome:
    variant = request.variant
    job_id = request.job_id
    folder = request.exports_dir / "handoff" / job_id
    refs_folder = folder / "refs"
    refs = variant.get("references") or []
    planned: List[str] = []
    for ref in refs:
        planned.append(
            "%s/refs/%02d_%s%s"
            % (
                _rel(request, folder),
                int(ref.get("order") or 0),
                _safe(ref.get("asset_id")),
                Path(str(ref.get("path") or "")).suffix or ".png",
            )
        )
    base_rel = _rel(request, folder)
    planned += ["%s/prompt.txt" % base_rel, "%s/manifest.json" % base_rel, "%s/README.md" % base_rel]
    if variant.get("negative_prompt"):
        planned.append("%s/negative.txt" % base_rel)
    bundle = str(request.option("bundle") or "folder").lower()
    if bundle == "zip":
        planned.append("%s.zip" % base_rel)

    if request.dry_run:
        return AdapterOutcome(
            status="dry_run",
            plan=["导出交接包 → %s" % base_rel] + planned,
        )

    refs_folder.mkdir(parents=True, exist_ok=True)
    outputs: List[Dict[str, Any]] = []
    manifest_refs: List[Dict[str, Any]] = []
    try:
        for ref in refs:
            source = resolve_within(request.project_root, str(ref.get("path") or ""))
            if not source.is_file():
                raise FileNotFoundError("参考图不存在：%s" % ref.get("path"))
            ext = source.suffix or ".png"
            name = "%02d_%s%s" % (int(ref.get("order") or 0), _safe(ref.get("asset_id")), ext)
            target = refs_folder / name
            shutil.copy2(source, target)
            copied = "refs/%s" % name
            outputs.append(
                file_output(
                    target,
                    "reference",
                    request.project_root,
                    order=ref.get("order"),
                    asset_id=ref.get("asset_id"),
                    role=ref.get("role"),
                )
            )
            manifest_refs.append(
                {
                    "order": ref.get("order"),
                    "asset_id": ref.get("asset_id"),
                    "role": ref.get("role"),
                    "label": ref.get("label"),
                    "file": copied,
                    "source_path": ref.get("path"),
                    "sha256": ref.get("sha256"),
                    "public_url": ref.get("public_url"),
                }
            )
    except Exception as exc:
        return AdapterOutcome(status="failed", outputs=outputs, error="交接包导出失败：%s" % exc)

    prompt_path = folder / "prompt.txt"
    write_text(prompt_path, str(variant.get("prompt") or "") + "\n")
    outputs.append(file_output(prompt_path, "prompt", request.project_root))

    negative_file = None
    if variant.get("negative_prompt"):
        negative_path = folder / "negative.txt"
        write_text(negative_path, str(variant.get("negative_prompt")) + "\n")
        negative_file = "negative.txt"
        outputs.append(file_output(negative_path, "negative", request.project_root))

    manifest = {
        "schema_version": "1.0",
        "job_id": job_id,
        "project_id": request.project_id,
        "shot_id": variant.get("shot_id"),
        "provider_id": variant.get("provider_id"),
        "mode": variant.get("mode"),
        "mode_label": variant.get("mode_label"),
        "duration_sec": variant.get("duration_sec"),
        "aspect_ratio": variant.get("aspect_ratio"),
        "resolution": variant.get("resolution"),
        "fps": variant.get("fps"),
        "seed": variant.get("seed"),
        "context_revision": variant.get("context_revision"),
        "short_revision": variant.get("short_revision"),
        "prompt_sha256": variant.get("prompt_sha256"),
        "negative_sha256": variant.get("negative_sha256"),
        "prompt_file": "prompt.txt",
        "negative_file": negative_file,
        "references": manifest_refs,
        "created_at": utc_now(),
    }
    manifest_path = folder / "manifest.json"
    write_json(manifest_path, manifest)
    outputs.append(file_output(manifest_path, "manifest", request.project_root))

    readme_path = folder / "README.md"
    write_text(readme_path, _readme(request.project_id, variant, job_id, manifest))
    outputs.append(file_output(readme_path, "readme", request.project_root))

    if bundle == "zip":
        zip_path = request.exports_dir / "handoff" / ("%s.zip" % job_id)
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in sorted(folder.rglob("*")):
                if item.is_file():
                    archive.write(item, item.relative_to(request.exports_dir / "handoff"))
        outputs.append(file_output(zip_path, "zip", request.project_root, bundle="handoff"))

    return AdapterOutcome(status="succeeded", outputs=outputs, plan=planned)


def _rel(request: AdapterRequest, path: Path) -> str:
    try:
        return path.resolve().relative_to(request.project_root.resolve()).as_posix()
    except ValueError:
        return str(path)
