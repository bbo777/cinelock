from __future__ import annotations

from typing import Any, Dict, List, Optional

from .context import ProjectContext
from .context_pack import PackError, get_variant, load_pack
from .continuity import build_state_snapshots
from .util import resolve_within, sha256_bytes, sha256_file, sha256_json, short_hash, utc_now

SNAPSHOT_KEYS = ("from_shot", "notes", "changes", "characters", "scene")
STATUS_LABELS = {"pass": "通过", "warn": "警告", "fail": "失败", "skip": "跳过"}


def _check(check_id: str, label: str, status: str, detail: str, **data: Any) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "id": check_id,
        "label": label,
        "status": status,
        "detail": detail,
    }
    if data:
        item["data"] = data
    return item


def _variant_snapshot(snapshot: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return None
    return {key: snapshot.get(key) for key in SNAPSHOT_KEYS}


def _audit_local_file(
    ctx: ProjectContext,
    relative: Any,
    expected: Any,
    label: str,
    failures: List[str],
) -> bool:
    if not relative:
        failures.append("%s 缺少 path" % label)
        return False
    try:
        path = resolve_within(ctx.root, str(relative))
    except ValueError as exc:
        failures.append("%s 路径非法（%s）" % (label, exc))
        return False
    if not path.is_file():
        failures.append("%s 文件缺失：%s" % (label, relative))
        return False
    if not expected:
        failures.append("%s 未记录 sha256" % label)
        return False
    actual = sha256_file(path)
    if actual != expected:
        failures.append("%s 哈希不一致（记录 %s，实际 %s）" % (label, short_hash(str(expected)), short_hash(actual)))
        return False
    return True


def audit_job(ctx: ProjectContext, job: Dict[str, Any]) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    provenance = job.get("provenance")
    if not isinstance(provenance, dict):
        provenance = None
    legacy = provenance is None
    job_revision = str(job.get("context_revision") or "")
    current_revision = ctx.context_revision()
    snapshot = (provenance or {}).get("context_snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else None

    try:
        pack = load_pack(ctx)
        pack_error = None
    except PackError as exc:
        pack = None
        pack_error = str(exc)

    # ---------- 存证 ----------

    if legacy:
        checks.append(
            _check(
                "provenance",
                "上下文存证",
                "warn",
                "该任务创建于存证功能之前；只能核验提示词、参考图与本地产物，无法核对修订锁与状态快照。",
            )
        )
    else:
        checks.append(
            _check(
                "provenance",
                "上下文存证",
                "pass",
                "存证 schema %s · 捕获于 %s"
                % (provenance.get("schema_version") or "?", provenance.get("captured_at") or "?"),
            )
        )

    if legacy:
        checks.append(_check("revision_lock", "修订锁", "skip", "旧任务没有 source_hashes，无法重算修订。"))
    else:
        source_hashes = provenance.get("source_hashes")
        recorded = provenance.get("source_hashes_sha256")
        problems = []
        if not isinstance(source_hashes, dict) or not source_hashes:
            problems.append("存证缺少 source_hashes")
        else:
            recomputed = sha256_json(source_hashes)
            if not recorded:
                problems.append("存证缺少 source_hashes_sha256")
            elif recorded != recomputed:
                problems.append("存证自哈希不一致（记录 %s，重算 %s）" % (short_hash(str(recorded)), short_hash(recomputed)))
            if job_revision != recomputed:
                problems.append("任务修订与重算结果不一致（记录 %s，重算 %s）" % (short_hash(job_revision), short_hash(recomputed)))
        if provenance.get("context_revision") and provenance.get("context_revision") != job_revision:
            problems.append("存证内修订与任务修订不一致")
        if problems:
            checks.append(_check("revision_lock", "修订锁", "fail", "；".join(problems)))
        else:
            checks.append(
                _check(
                    "revision_lock",
                    "修订锁",
                    "pass",
                    "存证 source_hashes 与任务修订一致 · %s" % short_hash(job_revision),
                )
            )

    if legacy:
        checks.append(_check("engine", "引擎指纹", "skip", "旧任务没有引擎指纹。"))
    else:
        stored_engine = provenance.get("engine") or {}
        current_engine = ctx.engine_fingerprint()
        if stored_engine == current_engine:
            checks.append(
                _check(
                    "engine",
                    "引擎指纹",
                    "pass",
                    "编译引擎与当前一致 · CineLock %s"
                    % (current_engine.get("cinelock_version") or "?"),
                )
            )
        else:
            stored_version = stored_engine.get("cinelock_version") or "?"
            current_version = current_engine.get("cinelock_version") or "?"
            checks.append(
                _check(
                    "engine",
                    "引擎指纹",
                    "warn",
                    "任务由旧引擎编译（%s），当前为 %s；同一修订重跑也可能得到不同提示词或快照。"
                    % (stored_version, current_version),
                )
            )

    # ---------- 连续性快照 ----------

    if legacy or snapshot is None:
        checks.append(_check("snapshot_integrity", "快照完整性", "skip", "没有可核验的上下文快照。"))
    else:
        expected_hash = provenance.get("context_snapshot_sha256")
        actual_hash = sha256_json(snapshot)
        if not expected_hash:
            checks.append(_check("snapshot_integrity", "快照完整性", "fail", "存证缺少 context_snapshot_sha256。"))
        elif actual_hash != expected_hash:
            checks.append(
                _check(
                    "snapshot_integrity",
                    "快照完整性",
                    "fail",
                    "快照哈希不一致（记录 %s，实际 %s）；服装、伤情、道具或场景可能已被改写。"
                    % (short_hash(str(expected_hash)), short_hash(actual_hash)),
                )
            )
        else:
            characters = list((snapshot.get("characters") or {}).keys())
            checks.append(
                _check(
                    "snapshot_integrity",
                    "快照完整性",
                    "pass",
                    "快照哈希一致 · %d 个角色 · 场景 %s"
                    % (len(characters), (snapshot.get("scene") or {}).get("scene_id") or "?"),
                    characters=characters,
                )
            )

    if legacy or snapshot is None:
        checks.append(_check("continuity_replay", "状态机重放", "skip", "没有快照可重放。"))
    elif job_revision != current_revision:
        checks.append(
            _check(
                "continuity_replay",
                "状态机重放",
                "skip",
                "任务基于历史修订 %s，当前时间线已变化，不做重放比对。"
                % short_hash(job_revision),
            )
        )
    else:
        try:
            replayed = build_state_snapshots(ctx).get(str(job.get("shot_id") or ""))
        except Exception as exc:
            checks.append(
                _check("continuity_replay", "状态机重放", "warn", "无法按当前时间线重放 state_delta：%s" % exc)
            )
        else:
            expected_snapshot = _variant_snapshot(replayed)
            if expected_snapshot is None:
                checks.append(
                    _check(
                        "continuity_replay",
                        "状态机重放",
                        "fail",
                        "当前时间线中找不到镜头 %s，无法重放。" % (job.get("shot_id") or "?"),
                    )
                )
            elif _variant_snapshot(snapshot) == expected_snapshot:
                checks.append(
                    _check(
                        "continuity_replay",
                        "状态机重放",
                        "pass",
                        "按时间线重放 state_delta，服装、伤情、道具、表情与场景逐字段一致。",
                    )
                )
            else:
                checks.append(
                    _check(
                        "continuity_replay",
                        "状态机重放",
                        "fail",
                        "任务快照与当前时间线的重放结果不一致；存证可能被改写，或时间线在未更新修订的情况下被改动。",
                    )
                )

    # ---------- 输入与提示词 ----------

    prompt = str(job.get("prompt") or "")
    prompt_hash = sha256_bytes(prompt.encode("utf-8"))
    prompt_ok = prompt_hash == job.get("prompt_sha256")
    negative = str(job.get("negative_prompt") or "")
    negative_ok = True
    if negative:
        negative_ok = sha256_bytes(negative.encode("utf-8")) == job.get("negative_sha256")
    if prompt_ok and negative_ok:
        checks.append(
            _check(
                "prompt_integrity",
                "提示词完整性",
                "pass",
                "正向 %s%s"
                % (
                    short_hash(prompt_hash),
                    (" · 负向 %s" % short_hash(str(job.get("negative_sha256")))) if negative else " · 无负向词",
                ),
            )
        )
    else:
        checks.append(
            _check(
                "prompt_integrity",
                "提示词完整性",
                "fail",
                "任务提示词与记录哈希不一致；任务内容可能在创建后被修改。",
            )
        )

    references = job.get("references") or []
    if not references:
        checks.append(_check("references", "参考图完整性", "skip", "该任务没有参考图（例如文生视频或演练）。"))
    else:
        failures: List[str] = []
        verified = 0
        for ref in references:
            if _audit_local_file(
                ctx,
                ref.get("path"),
                ref.get("sha256"),
                "参考图 %s" % (ref.get("asset_id") or ref.get("order") or "?"),
                failures,
            ):
                verified += 1
        if failures:
            checks.append(
                _check(
                    "references",
                    "参考图完整性",
                    "fail",
                    "%d/%d 张参考图核验失败：%s" % (len(failures), len(references), "；".join(failures[:5])),
                )
            )
        else:
            checks.append(
                _check(
                    "references",
                    "参考图完整性",
                    "pass",
                    "%d 张参考图均与任务记录的 sha256 一致（离线核验，不访问 public_url）。" % verified,
                )
            )

    outputs = job.get("outputs") or []
    local_outputs = [item for item in outputs if item.get("path")]
    remote_outputs = [item for item in outputs if not item.get("path") and item.get("url")]
    if not outputs:
        checks.append(_check("outputs", "产物完整性", "skip", "演练、阻断或失败任务没有产物。"))
    elif not local_outputs:
        checks.append(
            _check(
                "outputs",
                "产物完整性",
                "warn",
                "只有 %d 个远程产物，未保存到本地，无法离线核验。" % len(remote_outputs),
            )
        )
    else:
        failures = []
        verified = 0
        for output in local_outputs:
            label = "产物 %s" % (output.get("kind") or "?")
            if _audit_local_file(ctx, output.get("path"), output.get("sha256"), label, failures):
                verified += 1
        if failures:
            checks.append(
                _check(
                    "outputs",
                    "产物完整性",
                    "fail",
                    "%d/%d 个本地产物核验失败：%s"
                    % (len(failures), len(local_outputs), "；".join(failures[:5])),
                )
            )
        elif remote_outputs:
            checks.append(
                _check(
                    "outputs",
                    "产物完整性",
                    "warn",
                    "%d 个本地产物哈希一致；另有 %d 个远程产物未离线核验。"
                    % (verified, len(remote_outputs)),
                )
            )
        else:
            checks.append(
                _check(
                    "outputs",
                    "产物完整性",
                    "pass",
                    "%d 个本地产物均与任务记录的 sha256 一致。" % verified,
                )
            )

    if legacy:
        checks.append(_check("recompile", "同修订重编译", "skip", "旧任务没有修订锁与快照，无法重编译比对。"))
    elif job_revision != current_revision:
        checks.append(_check("recompile", "同修订重编译", "skip", "当前工作区已进入新修订，无法复现旧任务。"))
    elif pack_error:
        checks.append(_check("recompile", "同修订重编译", "warn", "Context Pack 无法读取：%s" % pack_error))
    elif pack is None:
        checks.append(_check("recompile", "同修订重编译", "warn", "当前没有 Context Pack，先运行 build。"))
    elif pack.get("context_revision") != current_revision:
        checks.append(
            _check(
                "recompile",
                "同修订重编译",
                "warn",
                "Context Pack 已过期（包内 %s），先重新 build 再核验。"
                % str(pack.get("short_revision") or "?"),
            )
        )
    else:
        variant = get_variant(pack, str(job.get("shot_id") or ""), str(job.get("provider_id") or ""))
        if variant is None:
            checks.append(_check("recompile", "同修订重编译", "warn", "当前包中找不到该镜头 × 厂商变体。"))
        else:
            differences = []
            if variant.get("variant_sha256") != job.get("variant_sha256"):
                differences.append("variant_sha256")
            if variant.get("prompt_sha256") != job.get("prompt_sha256"):
                differences.append("prompt_sha256")
            if _variant_snapshot(variant.get("continuity")) != _variant_snapshot(snapshot):
                differences.append("continuity")
            if differences:
                checks.append(
                    _check(
                        "recompile",
                        "同修订重编译",
                        "fail",
                        "同一修订重新编译后以下字段不一致：%s。任务记录可能被改写，或编译过程不确定。"
                        % "、".join(differences),
                    )
                )
            else:
                checks.append(
                    _check(
                        "recompile",
                        "同修订重编译",
                        "pass",
                        "同一修订重新编译得到相同的 variant_sha256、prompt_sha256 与连续性快照。",
                    )
                )

    # ---------- 连续性覆盖 ----------

    if legacy or snapshot is None:
        checks.append(_check("continuity_coverage", "状态约束覆盖", "skip", "没有快照可核对参考图覆盖。"))
    else:
        characters = snapshot.get("characters") or {}
        if not characters:
            checks.append(_check("continuity_coverage", "状态约束覆盖", "pass", "该镜头快照不包含角色。"))
        else:
            by_character: Dict[str, List[Dict[str, Any]]] = {}
            for ref in references:
                cid = ref.get("character_id")
                if cid:
                    by_character.setdefault(str(cid), []).append(ref)
            missing = [cid for cid in characters if not by_character.get(str(cid))]
            wardrobe_mismatch = []
            for cid, state in characters.items():
                expected = state.get("wardrobe_state")
                char_refs = by_character.get(str(cid)) or []
                wardrobes = sorted({str(ref.get("wardrobe_state")) for ref in char_refs if ref.get("wardrobe_state")})
                if expected and char_refs and str(expected) not in wardrobes:
                    wardrobe_mismatch.append("%s：快照 %s / 参考图 %s" % (cid, expected, "、".join(wardrobes)))
            scene_expected = bool((snapshot.get("scene") or {}).get("refs"))
            scene_covered = any(ref.get("scene_id") for ref in references)
            problems = []
            if missing:
                problems.append("角色未被参考图覆盖：%s" % "、".join(missing))
            if wardrobe_mismatch:
                problems.append("服装状态不一致：%s" % "；".join(wardrobe_mismatch))
            if scene_expected and not scene_covered:
                problems.append("场景参考图未进入本次投影")
            if problems:
                checks.append(
                    _check(
                        "continuity_coverage",
                        "状态约束覆盖",
                        "warn",
                        "；".join(problems) + "。这是输入投影边界，不代表存证被篡改。",
                    )
                )
            else:
                checks.append(
                    _check(
                        "continuity_coverage",
                        "状态约束覆盖",
                        "pass",
                        "%d 个角色均被参考图覆盖，服装状态与快照一致；场景参考图已进入投影。"
                        % len(characters),
                    )
                )

    if legacy:
        checks.append(_check("reference_projection", "参考图投影", "skip", "旧任务没有记录厂商投影。"))
    else:
        projection = job.get("projection") or {}
        dropped = projection.get("dropped_references") or []
        selected = projection.get("selected_refs")
        max_refs = projection.get("max_refs")
        if dropped:
            names = [
                "%s（%s）" % (item.get("asset_id") or "?", item.get("reason") or "?")
                for item in dropped[:6]
                if isinstance(item, dict)
            ]
            checks.append(
                _check(
                    "reference_projection",
                    "参考图投影",
                    "warn",
                    "厂商上限 %s 张，%d 张参考图未进入生成输入：%s。多模型共享同一上下文，但各厂商实际可见的参考图并不相等。"
                    % (max_refs, len(dropped), "、".join(names)),
                )
            )
        else:
            checks.append(
                _check(
                    "reference_projection",
                    "参考图投影",
                    "pass",
                    "%s 张参考图全部进入本次生成输入（厂商上限 %s）。"
                    % (selected if selected is not None else len(references), max_refs if max_refs is not None else "?"),
                )
            )

    # ---------- 当前工作区 ----------

    if legacy:
        checks.append(_check("current_revision", "当前修订", "skip", "旧任务没有修订记录。"))
    elif job_revision == current_revision:
        checks.append(
            _check("current_revision", "当前修订", "pass", "任务修订与当前工作区一致 · %s" % short_hash(current_revision))
        )
    else:
        checks.append(
            _check(
                "current_revision",
                "当前修订",
                "warn",
                "任务基于历史修订 %s，当前为 %s；这是历史记录，不是篡改。需要复现时先切回对应上下文。"
                % (short_hash(job_revision), short_hash(current_revision)),
            )
        )

    if pack_error:
        checks.append(_check("pack", "Context Pack", "warn", "Context Pack 无法读取：%s" % pack_error))
    elif pack is None:
        checks.append(_check("pack", "Context Pack", "warn", "当前没有 Context Pack；运行 build 后可做重编译核验。"))
    elif pack.get("context_revision") == current_revision:
        checks.append(
            _check("pack", "Context Pack", "pass", "Context Pack 与当前修订一致 · %s" % short_hash(current_revision))
        )
    else:
        checks.append(
            _check(
                "pack",
                "Context Pack",
                "warn",
                "Context Pack 已过期：包内 %s，当前 %s。"
                % (str(pack.get("short_revision") or "?"), short_hash(current_revision)),
            )
        )

    counts = {key: 0 for key in ("pass", "warn", "fail", "skip")}
    for check in checks:
        counts[check["status"]] = counts.get(check["status"], 0) + 1
    if counts["fail"]:
        status = "fail"
    elif counts["warn"]:
        status = "warn"
    else:
        status = "pass"

    job_status = str(job.get("status") or "unknown")
    dry_run = bool(job.get("dry_run"))
    job_ok = job_status in ("succeeded", "dry_run")
    if not job_revision:
        current_context = "unknown"
    elif job_revision == current_revision:
        current_context = "current"
    else:
        current_context = "historical"
    if status == "fail":
        overall = "fail"
    elif status == "warn" or not job_ok or current_context in ("historical", "unknown"):
        overall = "warn"
    else:
        overall = "pass"

    return {
        "ok": status != "fail",
        "status": status,
        "artifact_status": status,
        "scope": "artifact_integrity",
        "job_status": job_status,
        "dry_run": dry_run,
        "verdict": {
            "artifacts": status,
            "job": job_status,
            "job_ok": job_ok,
            "current_context": current_context,
            "overall": overall,
        },
        "checked_at": utc_now(),
        "job_id": job.get("job_id"),
        "shot_id": job.get("shot_id"),
        "provider_id": job.get("provider_id"),
        "adapter": job.get("adapter"),
        "context_revision": job_revision,
        "short_revision": short_hash(job_revision),
        "current_revision": current_revision,
        "current_short_revision": short_hash(current_revision),
        "legacy": legacy,
        "summary": counts,
        "checks": checks,
    }
