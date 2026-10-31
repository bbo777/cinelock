from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .context import CANONICAL_MODES, ProjectContext
from .util import dedupe_keep_order, sha256_bytes, sha256_json, short_hash, utc_now

MODE_LABELS = {
    "text2video": "文生视频",
    "img2video": "图生视频（单图首帧）",
    "multi_ref": "多参考图",
    "first_last": "首尾帧",
}

ROLE_ORDER = {
    "override": 5,
    "identity": 10,
    "geometry": 20,
    "expression": 30,
    "injury": 35,
    "wardrobe": 40,
    "scene": 50,
    "style": 60,
}

MAX_INLINE_NEGATIVES = 12


class CompileError(Exception):
    pass


def _issue(bucket: List[Dict[str, str]], code: str, message: str) -> None:
    for item in bucket:
        if item["code"] == code and item["message"] == message:
            return
    bucket.append({"code": code, "message": message})


def _char_name(card: Dict[str, Any]) -> str:
    return str(card.get("name_en") or card.get("name") or card.get("character_id") or "?")


def _descriptor_body(card: Dict[str, Any]) -> str:
    desc = str(card.get("descriptor_en") or "").strip()
    for raw_name in (card.get("name_en"), card.get("name")):
        if not raw_name:
            continue
        pattern = r"^%s(?:\s*\([^)]*\))?\s*[,:—–-]\s*" % re.escape(str(raw_name))
        stripped = re.sub(pattern, "", desc, count=1, flags=re.IGNORECASE)
        if stripped != desc:
            return stripped.strip()
    return desc


def _asset_hash(ctx: ProjectContext, asset: Dict[str, Any], asset_hashes: Optional[Dict[str, Optional[str]]]) -> str:
    aid = str(asset.get("asset_id") or "")
    if asset_hashes is not None and aid in asset_hashes:
        return asset_hashes.get(aid) or ""
    return ctx.asset_hash(asset) or ""


def _reference_entry(
    ctx: ProjectContext,
    asset: Dict[str, Any],
    role: str,
    label: str,
    priority: int,
    asset_hashes: Optional[Dict[str, Optional[str]]] = None,
) -> Dict[str, Any]:
    return {
        "order": 0,
        "asset_id": asset.get("asset_id"),
        "role": role,
        "role_label": role.replace("_", " "),
        "label": label,
        "priority": priority,
        "kind": asset.get("kind"),
        "character_id": asset.get("character_id"),
        "scene_id": asset.get("scene_id"),
        "view": asset.get("view"),
        "expression": asset.get("expression"),
        "wardrobe_state": asset.get("wardrobe_state"),
        "path": asset.get("path"),
        "sha256": _asset_hash(ctx, asset, asset_hashes),
        "public_url": asset.get("public_url"),
        "width": asset.get("width"),
        "height": asset.get("height"),
        "status": asset.get("status"),
        "version": asset.get("version"),
    }


def _resolve_ref(
    ctx: ProjectContext,
    asset_id: Any,
    role: str,
    label: str,
    priority: int,
    warnings: List[Dict[str, str]],
    asset_hashes: Optional[Dict[str, Optional[str]]] = None,
) -> Optional[Dict[str, Any]]:
    if not asset_id:
        return None
    asset = ctx.asset(str(asset_id))
    if asset is None:
        _issue(warnings, "W_REF_UNKNOWN", "参考图不存在，已跳过：%s" % asset_id)
        return None
    return _reference_entry(ctx, asset, role, label, priority, asset_hashes)


def _keyframe_entry(
    ctx: ProjectContext,
    asset_id: Any,
    role: str,
    label: str,
    warnings: List[Dict[str, str]],
    asset_hashes: Optional[Dict[str, Optional[str]]] = None,
) -> Optional[Dict[str, Any]]:
    return _resolve_ref(ctx, asset_id, role, label, 0, warnings, asset_hashes)


def _identity_label(card: Dict[str, Any], asset: Dict[str, Any]) -> str:
    label = "%s — identity anchor" % _char_name(card)
    view = asset.get("view")
    if view:
        label += " (%s view)" % str(view).replace("_", " ")
    return label


def _build_reference_pool(
    ctx: ProjectContext,
    shot: Dict[str, Any],
    snapshot: Dict[str, Any],
    warnings: List[Dict[str, str]],
    asset_hashes: Optional[Dict[str, Optional[str]]] = None,
) -> List[Dict[str, Any]]:
    pool: List[Dict[str, Any]] = []
    seen: set = set()
    character_order = {cid: idx for idx, cid in enumerate(shot.get("character_ids") or [])}

    def add(entry: Optional[Dict[str, Any]]) -> None:
        if entry is None:
            return
        aid = entry.get("asset_id")
        if not aid or aid in seen:
            return
        seen.add(aid)
        pool.append(entry)

    for aid in shot.get("reference_overrides") or []:
        asset = ctx.asset(str(aid))
        label = "Shot reference override — %s" % aid
        if asset and asset.get("character_id"):
            card = ctx.character(str(asset.get("character_id"))) or {}
            if card:
                label = "%s — shot override" % _char_name(card)
        add(_resolve_ref(ctx, aid, "override", label, ROLE_ORDER["override"], warnings, asset_hashes))

    for cid in shot.get("character_ids") or []:
        card = ctx.character(str(cid))
        if card is None:
            continue
        name = _char_name(card)
        refs = card.get("refs") or {}
        for aid in refs.get("identity_anchor") or []:
            asset = ctx.asset(str(aid))
            add(
                _resolve_ref(
                    ctx,
                    aid,
                    "identity",
                    _identity_label(card, asset or {"view": None}) if asset else "%s — identity anchor" % name,
                    ROLE_ORDER["identity"],
                    warnings,
                    asset_hashes,
                )
            )
        for key in ("geometry", "turnaround"):
            for aid in refs.get(key) or []:
                add(
                    _resolve_ref(
                        ctx,
                        aid,
                        "geometry",
                        "%s — geometry reference%s" % (name, " (turnaround)" if key == "turnaround" else ""),
                        ROLE_ORDER["geometry"],
                        warnings,
                        asset_hashes,
                    )
                )

        state = (snapshot.get("characters") or {}).get(str(cid)) or {}
        expression = str(state.get("expression") or "neutral")
        expression_refs = (card.get("expression_refs") or {}).get(expression) or []
        for aid in expression_refs:
            add(
                _resolve_ref(
                    ctx,
                    aid,
                    "expression",
                    "%s — expression: %s" % (name, expression),
                    ROLE_ORDER["expression"],
                    warnings,
                    asset_hashes,
                )
            )

        wardrobe_name = str(state.get("wardrobe_state") or "")
        wardrobe = (card.get("wardrobe_states") or {}).get(wardrobe_name) or {}
        injuries = list(state.get("injuries") or [])
        role = "injury" if injuries else "wardrobe"
        priority = ROLE_ORDER[role]
        if injuries:
            label = "%s — injury state (%s)" % (name, wardrobe_name or "current")
        else:
            label = "%s — wardrobe: %s" % (name, wardrobe_name or "current")
        for aid in wardrobe.get("refs") or []:
            add(_resolve_ref(ctx, aid, role, label, priority, warnings, asset_hashes))

    scene = snapshot.get("scene") or {}
    for aid in scene.get("refs") or []:
        add(
            _resolve_ref(
                ctx,
                aid,
                "scene",
                "Scene — %s (%s)" % (scene.get("scene_id") or "scene", scene.get("time_of_day") or "?"),
                ROLE_ORDER["scene"],
                warnings,
                asset_hashes,
            )
        )

    for aid in (ctx.project.get("style") or {}).get("style_refs") or []:
        add(_resolve_ref(ctx, aid, "style", "Style anchor", ROLE_ORDER["style"], warnings, asset_hashes))

    pool.sort(key=lambda item: (item["priority"], character_order.get(item.get("character_id"), 99)))
    return pool


def _can_first_frame(ctx: ProjectContext, shot: Dict[str, Any], pool: List[Dict[str, Any]]) -> bool:
    keyframes = shot.get("keyframes") or {}
    if keyframes.get("first"):
        return True
    if shot.get("reference_overrides"):
        return True
    return bool(pool)


def _choose_mode(
    ctx: ProjectContext,
    shot: Dict[str, Any],
    profile: Dict[str, Any],
    pool: List[Dict[str, Any]],
    first_kf: Optional[Dict[str, Any]],
    last_kf: Optional[Dict[str, Any]],
    warnings: List[Dict[str, str]],
    blockers: List[Dict[str, str]],
) -> Tuple[Optional[str], str]:
    modes = [m for m in profile.get("modes") or [] if m in CANONICAL_MODES]
    hint = str(shot.get("mode_hint") or "auto")
    has_characters = bool(shot.get("character_ids"))

    if hint != "auto":
        if hint not in CANONICAL_MODES:
            _issue(warnings, "W_MODE_HINT_UNKNOWN", "未知 mode_hint：%s，改为自动选择" % hint)
        elif hint not in modes:
            _issue(warnings, "W_MODE_HINT_UNSUPPORTED", "厂商不支持 mode_hint=%s，改为自动选择" % hint)
        elif hint == "first_last" and not (first_kf and last_kf):
            _issue(warnings, "W_HINT_KEYFRAMES_MISSING", "指定首尾帧模式，但镜头缺少 first/last 关键帧，改为自动选择")
        elif hint == "multi_ref" and not pool:
            _issue(warnings, "W_HINT_REFS_MISSING", "指定多参考模式，但没有可用参考图，改为自动选择")
        else:
            return hint, "手动指定：mode_hint=%s" % hint

    if first_kf and last_kf and "first_last" in modes:
        return "first_last", "自动：镜头有首尾关键帧，厂商支持首尾帧"
    if first_kf and "img2video" in modes:
        return "img2video", "自动：镜头有首帧关键帧，厂商支持单图图生视频"
    if "multi_ref" in modes:
        if len(pool) >= 2:
            return "multi_ref", "自动：厂商支持多参考，选用 %d 张共享参考图" % min(len(pool), int(profile.get("max_refs") or len(pool)))
        if "img2video" not in modes:
            if len(pool) < 2:
                _issue(warnings, "W_MULTI_REF_SINGLE_IMAGE", "多参考模式只有 %d 张可用参考图" % len(pool))
            return "multi_ref", "自动：厂商只支持多参考模式（参考图不足两张，仍按多参考提交）"
    if "img2video" in modes and _can_first_frame(ctx, shot, pool):
        return "img2video", "自动：厂商只支持单图图生视频，用身份锚点或首帧作为首帧"
    if "text2video" in modes:
        if has_characters:
            _issue(
                warnings,
                "W_TEXT2VIDEO_IDENTITY_RISK",
                "厂商没有可用的参考图模式，退化为文生视频；角色一致性无法保证",
            )
        return "text2video", "自动：厂商不支持参考图条件生成，退化为文生视频"
    if "multi_ref" in modes:
        _issue(warnings, "W_MULTI_REF_SINGLE_IMAGE", "多参考模式只有一张可用参考图")
        return "multi_ref", "自动：厂商只支持多参考模式（参考图不足）"

    _issue(blockers, "B_NO_COMPATIBLE_MODE", "厂商没有任何可用生成模式")
    return None, "无可用模式"


def _finalize_selection(
    selected: List[Dict[str, Any]],
    pool: List[Dict[str, Any]],
    drop_reason: str,
) -> List[Dict[str, Any]]:
    selected_ids = {item.get("asset_id") for item in selected}
    for idx, item in enumerate(selected, 1):
        item["order"] = idx
    dropped = []
    for item in pool:
        if item.get("asset_id") in selected_ids:
            continue
        dropped.append(
            {
                "asset_id": item.get("asset_id"),
                "label": item.get("label"),
                "role": item.get("role"),
                "reason": drop_reason,
            }
        )
    return dropped


def _select_multi_ref(
    ctx: ProjectContext,
    shot: Dict[str, Any],
    profile: Dict[str, Any],
    pool: List[Dict[str, Any]],
    warnings: List[Dict[str, str]],
    blockers: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    limit = int(profile.get("max_refs") or 0)
    if limit < 1:
        _issue(blockers, "B_MAX_REFS", "厂商 max_refs 配置非法")
        return []
    selected = list(pool[:limit])

    for cid in shot.get("character_ids") or []:
        cid = str(cid)
        has_identity = any(item.get("role") == "identity" and item.get("character_id") == cid for item in selected)
        if has_identity:
            continue
        identities = [item for item in pool if item.get("role") == "identity" and item.get("character_id") == cid]
        if not identities:
            _issue(warnings, "W_IDENTITY_REF_MISSING", "%s 没有身份锚点参考图" % cid)
            continue
        replacement = None
        for idx in range(len(selected) - 1, -1, -1):
            if selected[idx].get("role") != "identity":
                replacement = idx
                break
        if replacement is None:
            _issue(
                blockers,
                "B_MULTI_CHAR_REFS",
                "max_refs=%d 不足以同时保留 %d 个角色的身份锚点" % (limit, len(shot.get("character_ids") or [])),
            )
            continue
        selected[replacement] = identities[0]

    if len(selected) < limit:
        chosen = {item.get("asset_id") for item in selected}
        for item in pool:
            if len(selected) >= limit:
                break
            if item.get("asset_id") not in chosen:
                selected.append(item)
                chosen.add(item.get("asset_id"))

    if selected:
        selected.sort(key=lambda item: item["priority"])
    if len(pool) > len(selected):
        _issue(
            warnings,
            "W_REFS_TRUNCATED",
            "参考图 %d 张，超过厂商上限 %d 张，已按身份优先级截断" % (len(pool), limit),
        )
    return selected


def _select_img2video(
    ctx: ProjectContext,
    shot: Dict[str, Any],
    pool: List[Dict[str, Any]],
    first_kf: Optional[Dict[str, Any]],
    warnings: List[Dict[str, str]],
) -> List[Dict[str, Any]]:
    if first_kf:
        return [dict(first_kf, order=1)]
    for aid in shot.get("reference_overrides") or []:
        entry = ctx.asset(str(aid))
        if entry:
            return [
                _reference_entry(
                    ctx,
                    entry,
                    "first_frame_override",
                    "Shot override — used as first frame",
                    0,
                )
            ]
    character_ids = shot.get("character_ids") or []
    if character_ids:
        cid = str(character_ids[0])
        card = ctx.character(cid) or {}
        identity_id = ((card.get("refs") or {}).get("identity_anchor") or [None])[0]
        identity = ctx.asset(str(identity_id)) if identity_id else None
        if identity:
            if len(character_ids) > 1:
                _issue(
                    warnings,
                    "W_SINGLE_FRAME_MULTI_CHARACTER",
                    "单图模式一镜内有 %d 个角色，只能锚定 %s，其余角色依赖提示词"
                    % (len(character_ids), _char_name(card)),
                )
            _issue(
                warnings,
                "W_IDENTITY_AS_FIRST_FRAME",
                "没有首帧关键帧，使用 %s 的身份锚点作为首帧；背景和姿势需由提示词重建" % _char_name(card),
            )
            return [
                _reference_entry(
                    ctx,
                    identity,
                    "identity_first_frame",
                    "%s — identity anchor used as first frame" % _char_name(card),
                    0,
                )
            ]
    for item in pool:
        if item.get("role") == "scene":
            return [dict(item, role="scene_first_frame", label="%s — used as first frame" % item["label"], order=1)]
    if pool:
        return [dict(pool[0], role="first_frame_fallback", label="%s — used as first frame" % pool[0]["label"], order=1)]
    return []


def _reference_legend(refs: List[Dict[str, Any]], mode: Optional[str]) -> str:
    if not refs:
        return "No reference images."
    ordered = sorted(refs, key=lambda item: item.get("order") or 0)
    listed = "; ".join("[%d] %s" % (item.get("order"), item.get("label")) for item in ordered)
    legend = "Reference images, in order: %s." % listed
    identity = next((item for item in ordered if item.get("role") in ("identity", "identity_first_frame")), None)
    if mode == "multi_ref":
        if identity:
            legend += (
                " Use each reference only for the aspect it anchors; keep the face, hair and costume identity from [%d]."
                % identity.get("order")
            )
        else:
            legend += " Use each reference only for the aspect it anchors."
    elif mode == "first_last":
        legend += " Start exactly from [1] and end exactly at [2]; interpolate the action naturally."
    elif mode == "img2video":
        legend += " Animate from the first-frame still in [1]."
    return legend


def _mode_instruction(mode: Optional[str], shot: Dict[str, Any], refs: List[Dict[str, Any]]) -> str:
    has_characters = bool(shot.get("character_ids"))
    if mode == "text2video":
        if has_characters:
            return (
                "No reference image is available for this shot; reconstruct the character strictly from the description "
                "above and keep the face, hair and costume identity consistent."
            )
        return "No reference image; establish the location, lighting and action from the description."
    if mode == "img2video":
        roles = {item.get("role") for item in refs}
        if "identity_first_frame" in roles:
            return (
                "Animate from the character identity reference in [1]. It is a character sheet, not a shot frame: "
                "restage the pose, camera and background to match the action while preserving the face, hair and every "
                "listed identity invariant."
            )
        if "scene_first_frame" in roles or "first_frame_fallback" in roles:
            return "Animate from the still in [1]; keep the location and lighting, and stage the action inside it."
        return (
            "Animate forward from the first-frame reference in [1]; preserve its composition, face and costume while "
            "playing the described action."
        )
    if mode == "multi_ref":
        return (
            "Combine the references to keep the same character identity, current wardrobe, injuries and scene across "
            "the shot; the action must not change the face or the signature details."
        )
    if mode == "first_last":
        return (
            "Start exactly on the first-frame reference [1], end exactly on the last-frame reference [2], and "
            "interpolate the action naturally between them."
        )
    return ""


def _continuity_text(ctx: ProjectContext, shot: Dict[str, Any], snapshot: Dict[str, Any]) -> str:
    from_shot = snapshot.get("from_shot")
    changes_by_character = snapshot.get("changes") or {}
    interesting = []
    for cid, changes in changes_by_character.items():
        kept = [c for c in changes if c not in ("first appearance", "state carried")]
        if not kept:
            continue
        card = ctx.character(str(cid)) or {}
        interesting.append((_char_name(card) if card else str(cid), kept))

    if from_shot:
        text = "Continuity: this shot follows %s." % from_shot
    else:
        text = "Continuity: this is the first appearance of the character; establish the face, wardrobe and props clearly."
    if interesting:
        fragments = []
        for name, changes in interesting:
            fragments.append("%s: %s" % (name, "; ".join(changes)))
        text += " Changes: %s." % " | ".join(fragments)
        text += " All listed dirt, injuries and props persist into later shots."
    elif from_shot:
        text += " Costume, injuries and props continue unchanged."
    return text


def _merge_negative(ctx: ProjectContext, shot: Dict[str, Any]) -> Tuple[str, List[str]]:
    style = ctx.project.get("style") or {}
    items: List[str] = []
    for chunk in str(style.get("negative_base") or "").split(","):
        chunk = chunk.strip()
        if chunk:
            items.append(chunk)
    character_items: List[str] = []
    for cid in shot.get("character_ids") or []:
        card = ctx.character(str(cid)) or {}
        for item in card.get("negative_en") or []:
            item = str(item).strip()
            if item:
                character_items.append(item)
                items.append(item)
    seen = set()
    merged = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return ", ".join(merged), character_items


def provider_profile(ctx: ProjectContext, provider_id: str) -> Dict[str, Any]:
    profile = ctx.provider(provider_id)
    if profile is None:
        raise CompileError("未知 provider：%s" % provider_id)
    return profile


KNOWN_ADAPTERS = ("mock", "handoff", "comfyui", "http_api")


def dispatch_adapter(profile: Dict[str, Any]) -> str:
    adapter = str(profile.get("adapter") or "")
    if adapter in KNOWN_ADAPTERS:
        return adapter
    legacy_kind = str(profile.get("kind") or "")
    if legacy_kind in ("mock", "handoff"):
        return legacy_kind
    return "manual"


def choose_duration(profile: Dict[str, Any], target: float) -> Tuple[int, str, Optional[str]]:
    durations = sorted(
        {int(d) for d in profile.get("durations") or [] if isinstance(d, (int, float)) and d > 0}
    )
    if not durations:
        return int(round(target)), "fallback", "厂商没有配置支持时长，按目标时长提交"
    target_int = int(round(target))
    if target_int in durations:
        return target_int, "exact", None
    if target_int > durations[-1]:
        return durations[-1], "truncated", "目标 %ss 超过厂商上限 %ss，已截断为 %ss" % (target_int, durations[-1], durations[-1])
    if target_int < durations[0]:
        return durations[0], "extended", "目标 %ss 低于厂商下限 %ss，已延长为 %ss" % (target_int, durations[0], durations[0])
    chosen = min(durations, key=lambda d: (abs(d - target_int), d < target_int, d))
    return chosen, "nearest", "目标 %ss 不在支持列表 %s，已调整为最接近的 %ss" % (
        target_int,
        "/".join(str(d) for d in durations),
        chosen,
    )


def _ensure_period(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    if text[-1] in ".!?。！？…":
        return text
    return text + "."


def _prompt_negative_inline(negative_items: List[str], character_items: List[str]) -> str:
    ordered = dedupe_keep_order(character_items + negative_items)
    picked = ordered[:MAX_INLINE_NEGATIVES]
    return "Avoid: %s." % ", ".join(picked) if picked else ""


def build_prompt(
    ctx: ProjectContext,
    shot: Dict[str, Any],
    snapshot: Dict[str, Any],
    profile: Dict[str, Any],
    mode: Optional[str],
    refs: List[Dict[str, Any]],
    warnings: List[Dict[str, str]],
) -> Tuple[str, str, str, str]:
    prompt_parts: List[str] = []
    style = ctx.project.get("style") or {}
    prompt_parts.append(str(style.get("anchor") or "").strip())

    for cid in shot.get("character_ids") or []:
        cid = str(cid)
        card = ctx.character(cid)
        if card is None:
            continue
        state = (snapshot.get("characters") or {}).get(cid) or {}
        wardrobe_name = str(state.get("wardrobe_state") or "")
        wardrobe = (card.get("wardrobe_states") or {}).get(wardrobe_name) or {}
        block = "%s (%s): %s" % (_char_name(card), cid, _ensure_period(_descriptor_body(card)))
        if wardrobe.get("descriptor_en"):
            block += " Current wardrobe: %s." % wardrobe["descriptor_en"]
        block += " Expression: %s." % (state.get("expression") or "neutral")
        injuries = list(state.get("injuries") or [])
        block += " Visible injuries: %s." % (", ".join(injuries) if injuries else "none")
        props = list(state.get("props") or [])
        block += " Props in hand: %s." % (", ".join(props) if props else "none")
        if card.get("invariants_en"):
            block += " Identity invariants: %s." % "; ".join(card["invariants_en"])
        prompt_parts.append(block)

    scene = snapshot.get("scene") or {}
    scene_block = "Scene: %s, %s." % (scene.get("location_en") or "unspecified location", scene.get("time_of_day") or "unspecified time")
    if scene.get("lighting_en"):
        scene_block += " Lighting: %s." % scene["lighting_en"]
    if scene.get("composition_en"):
        scene_block += " Composition: %s." % scene["composition_en"]
    prompt_parts.append(scene_block)

    shot_maps = ctx.prompt_maps.get("shot_size") or {}
    camera_maps = ctx.prompt_maps.get("camera") or {}
    shot_size = shot_maps.get(str(shot.get("shot_size") or "")) or str(shot.get("shot_size") or "")
    camera_move = camera_maps.get(str(shot.get("camera_move") or "")) or str(shot.get("camera_move") or "")
    shot_block = "Shot: %s. Camera: %s. Action: %s" % (shot_size, camera_move, shot.get("action_en") or "")
    shot_block = shot_block.rstrip()
    if not shot_block.endswith("."):
        shot_block += "."
    prompt_parts.append(shot_block)
    if shot.get("dialogue"):
        prompt_parts.append(
            "Performance: the character speaks a short, restrained line; audio is added in post; no on-screen text."
        )

    prompt_parts.append(_continuity_text(ctx, shot, snapshot))

    if (ctx.project.get("prompt") or {}).get("include_reference_legend", True):
        prompt_parts.append(_reference_legend(refs, mode))
    mode_instruction = _mode_instruction(mode, shot, refs)
    if mode_instruction:
        prompt_parts.append(mode_instruction)

    quality_suffix = str(style.get("quality_suffix") or "").strip()
    if quality_suffix:
        prompt_parts.append(quality_suffix)
    provider_suffix = str(profile.get("prompt_suffix") or "").strip()
    if provider_suffix:
        prompt_parts.append(provider_suffix)

    negative_prompt, character_negatives = _merge_negative(ctx, shot)
    inline_avoid = ""
    if not profile.get("supports_negative_prompt"):
        negative_items = [x.strip() for x in negative_prompt.split(",") if x.strip()]
        inline_avoid = _prompt_negative_inline(negative_items, character_negatives)
        if inline_avoid:
            prompt_parts.append(inline_avoid)
            _issue(
                warnings,
                "W_NEGATIVE_INLINE",
                "厂商不支持独立负向提示词，已把角色负向词并入正向提示词（Avoid: ...）",
            )

    prompt = " ".join(_ensure_period(part) for part in prompt_parts if part and part.strip())
    prompt = re.sub(r"\s+", " ", prompt).strip()
    return prompt, negative_prompt, inline_avoid, mode_instruction


def _required_env(profile: Dict[str, Any]) -> List[str]:
    names = []
    for key in ("api_key_env", "access_key_env", "secret_key_env"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            names.append(value.strip())
    for name in profile.get("requires_env") or []:
        if isinstance(name, str) and name.strip() and name.strip() not in names:
            names.append(name.strip())
    return names


def _build_dispatch(
    profile: Dict[str, Any],
    mode: Optional[str],
    refs: List[Dict[str, Any]],
    blockers: List[Dict[str, str]],
    warnings: List[Dict[str, str]],
) -> Dict[str, Any]:
    adapter = dispatch_adapter(profile)
    if adapter == "manual":
        _issue(
            blockers,
            "B_ADAPTER_UNKNOWN",
            "厂商 %s 没有可用的 adapter 字段；支持 %s" % (profile.get("display_name") or "?", " / ".join(KNOWN_ADAPTERS)),
        )
    if profile.get("enabled", True) is False:
        _issue(
            blockers,
            "B_PROVIDER_DISABLED",
            "厂商 %s 已停用；把 providers.json 中 enabled 改为 true 后再编译" % (profile.get("display_name") or "?"),
        )

    public_urls = [str(ref.get("public_url")) for ref in refs if ref.get("public_url")]
    block_reasons: List[str] = [item["message"] for item in blockers]
    return {
        "adapter": adapter,
        "endpoint": profile.get("base_url"),
        "preset": profile.get("preset"),
        "requires_env": _required_env(profile),
        "experimental": bool(profile.get("experimental")),
        "public_urls": public_urls,
        "ready": not block_reasons,
        "block_reasons": block_reasons,
    }


def compile_shot(
    ctx: ProjectContext,
    shot: Dict[str, Any],
    snapshot: Dict[str, Any],
    provider_id: str,
    *,
    context_revision: Optional[str] = None,
    asset_hashes: Optional[Dict[str, Optional[str]]] = None,
    candidate_index: int = 0,
) -> Dict[str, Any]:
    profile = provider_profile(ctx, provider_id)
    shot_id = str(shot.get("shot_id") or "")
    if not shot_id:
        raise CompileError("镜头缺少 shot_id")
    revision = context_revision or ctx.context_revision()

    warnings: List[Dict[str, str]] = []
    blockers: List[Dict[str, str]] = []

    keyframes = shot.get("keyframes") or {}
    first_kf = _keyframe_entry(ctx, keyframes.get("first"), "first_frame", "First frame (keyframe)", warnings, asset_hashes)
    last_kf = _keyframe_entry(ctx, keyframes.get("last"), "last_frame", "Last frame (keyframe)", warnings, asset_hashes)

    pool = _build_reference_pool(ctx, shot, snapshot, warnings, asset_hashes)
    mode, mode_reason = _choose_mode(ctx, shot, profile, pool, first_kf, last_kf, warnings, blockers)

    if mode == "multi_ref":
        selected = _select_multi_ref(ctx, shot, profile, pool, warnings, blockers)
        dropped = _finalize_selection(selected, pool, "max_refs")
    elif mode == "img2video":
        selected = _select_img2video(ctx, shot, pool, first_kf, warnings)
        dropped = _finalize_selection(selected, pool, "single_image_mode")
    elif mode == "first_last":
        selected = [dict(first_kf, order=1), dict(last_kf, order=2)]
        dropped = _finalize_selection(selected, pool, "first_last_mode")
    elif mode == "text2video":
        selected = []
        dropped = _finalize_selection(selected, pool, "text_only_mode")
    else:
        selected = []
        dropped = _finalize_selection(selected, pool, "no_mode")

    if mode == "img2video" and not selected:
        _issue(blockers, "B_NO_FIRST_FRAME", "单图模式没有可用的首帧参考图")
    if mode == "multi_ref" and not selected:
        _issue(blockers, "B_NO_REFS", "多参考模式没有可用参考图")

    prompt, negative_prompt, negative_inline, mode_instruction = build_prompt(
        ctx, shot, snapshot, profile, mode, selected, warnings
    )
    max_chars = (ctx.project.get("prompt") or {}).get("max_chars")
    if isinstance(max_chars, int) and max_chars > 0 and len(prompt) > max_chars:
        _issue(
            warnings,
            "W_PROMPT_TOO_LONG",
            "提示词 %d 字符，超过项目上限 %d；部分模型可能截断" % (len(prompt), max_chars),
        )

    duration, duration_choice, duration_note = choose_duration(profile, shot.get("duration_sec") or 5)
    if duration_note:
        _issue(warnings, "W_DURATION_ADJUSTED", duration_note)

    dispatch = _build_dispatch(profile, mode, selected, blockers, warnings)

    seed_material = "%s|%s|%s|%d" % (revision, shot_id, provider_id, candidate_index)
    seed = int(sha256_bytes(seed_material.encode("utf-8"))[:8], 16) % 2147483647

    negative_mode = "separate" if profile.get("supports_negative_prompt") else "inline"
    if not negative_prompt:
        negative_mode = "none"

    payload = {
        "schema_version": "1.0",
        "shot_id": shot_id,
        "episode_id": ctx.timeline.get("episode_id"),
        "scene_id": shot.get("scene_id"),
        "provider_id": provider_id,
        "provider": {
            "id": provider_id,
            "display_name": profile.get("display_name"),
            "adapter": dispatch_adapter(profile),
            "preset": profile.get("preset"),
            "enabled": bool(profile.get("enabled", True)),
            "experimental": bool(profile.get("experimental")),
            "modes": list(profile.get("modes") or []),
            "max_refs": profile.get("max_refs"),
            "durations": list(profile.get("durations") or []),
            "ref_semantics": profile.get("ref_semantics"),
            "supports_negative_prompt": bool(profile.get("supports_negative_prompt")),
            "supports_seed": bool(profile.get("supports_seed")),
            "base_url": profile.get("base_url"),
            "workflow": profile.get("workflow"),
            "model": profile.get("model"),
            "image_input": profile.get("image_input"),
            "timeout_sec": profile.get("timeout_sec"),
            "poll_interval_sec": profile.get("poll_interval_sec"),
            "api_key_env": profile.get("api_key_env"),
            "access_key_env": profile.get("access_key_env"),
            "secret_key_env": profile.get("secret_key_env"),
            "ratio_map": profile.get("ratio_map"),
            "send_seed": profile.get("send_seed"),
        },
        "mode": mode,
        "mode_label": MODE_LABELS.get(mode or "", mode),
        "mode_reason": mode_reason,
        "mode_instruction": mode_instruction,
        "duration_sec": duration,
        "requested_duration_sec": shot.get("duration_sec"),
        "duration_choice": duration_choice,
        "aspect_ratio": (ctx.project.get("format") or {}).get("aspect_ratio"),
        "resolution": (ctx.project.get("format") or {}).get("resolution"),
        "fps": (ctx.project.get("format") or {}).get("fps"),
        "seed": seed,
        "seed_supported": bool(profile.get("supports_seed")),
        "candidate_index": candidate_index,
        "prompt": prompt,
        "prompt_chars": len(prompt),
        "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
        "negative_prompt": negative_prompt,
        "negative_sha256": sha256_bytes(negative_prompt.encode("utf-8")) if negative_prompt else "",
        "negative_mode": negative_mode,
        "negative_inline": negative_inline,
        "reference_legend": _reference_legend(selected, mode),
        "references": selected,
        "reference_count": len(selected),
        "dropped_references": dropped,
        "continuity": {
            "from_shot": snapshot.get("from_shot"),
            "notes": snapshot.get("notes") or "",
            "changes": snapshot.get("changes") or {},
            "characters": snapshot.get("characters") or {},
            "scene": snapshot.get("scene") or {},
        },
        "dialogue": shot.get("dialogue") or [],
        "sfx": shot.get("sfx") or [],
        "dispatch": dispatch,
        "warnings": warnings,
        "blockers": blockers,
        "context_revision": revision,
        "short_revision": short_hash(revision),
        "compiled_at": utc_now(),
    }
    payload["variant_sha256"] = sha256_json(
        {key: value for key, value in payload.items() if key not in ("compiled_at", "variant_sha256")}
    )
    return payload


def compile_all(
    ctx: ProjectContext,
    provider_ids: Optional[List[str]] = None,
    *,
    snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    from .continuity import build_state_snapshots

    snapshots = snapshots or build_state_snapshots(ctx)
    ids = list(provider_ids or ctx.provider_order())
    known = ctx.provider_profiles()
    unknown = [pid for pid in ids if pid not in known]
    if unknown:
        raise CompileError("未知 provider：%s" % ", ".join(unknown))
    revision = ctx.context_revision()
    asset_hashes = {asset.get("asset_id"): ctx.asset_hash(asset) for asset in ctx.asset_list() if asset.get("asset_id")}
    compiled = []
    for shot in ctx.shots():
        shot_id = str(shot.get("shot_id") or "")
        snapshot = snapshots.get(shot_id)
        if snapshot is None:
            raise CompileError("镜头 %s 没有连续性快照" % shot_id)
        for pid in ids:
            compiled.append(
                compile_shot(
                    ctx,
                    shot,
                    snapshot,
                    pid,
                    context_revision=revision,
                    asset_hashes=asset_hashes,
                )
            )
    return compiled
