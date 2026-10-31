from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set

from .context import ASSET_KINDS, ASSET_STATUSES, CANONICAL_MODES, ProjectContext
from .continuity import build_state_snapshots


@dataclass(frozen=True)
class Issue:
    level: str
    code: str
    message: str
    where: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"level": self.level, "code": self.code, "message": self.message, "where": self.where}


@dataclass
class ValidationResult:
    errors: List[Issue] = field(default_factory=list)
    warnings: List[Issue] = field(default_factory=list)
    _seen: Set[tuple] = field(default_factory=set, repr=False)

    @property
    def ok(self) -> bool:
        return not self.errors

    def _add(self, level: str, code: str, message: str, where: str = "") -> None:
        key = (level, code, where, message)
        if key in self._seen:
            return
        self._seen.add(key)
        issue = Issue(level=level, code=code, message=message, where=where)
        if level == "error":
            self.errors.append(issue)
        else:
            self.warnings.append(issue)

    def error(self, code: str, message: str, where: str = "") -> None:
        self._add("error", code, message, where)

    def warning(self, code: str, message: str, where: str = "") -> None:
        self._add("warning", code, message, where)

    def extend(self, other: "ValidationResult") -> None:
        for issue in other.errors:
            self.error(issue.code, issue.message, issue.where)
        for issue in other.warnings:
            self.warning(issue.code, issue.message, issue.where)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": [x.to_dict() for x in self.errors],
            "warnings": [x.to_dict() for x in self.warnings],
        }


def _dicts(items: Iterable[Any]) -> List[Dict[str, Any]]:
    return [x for x in items if isinstance(x, dict)]


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_list_of_str(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def _check_asset_ref(
    ctx: ProjectContext,
    result: ValidationResult,
    asset_id: Any,
    where: str,
    *,
    expect_character: Optional[str] = None,
    expect_kind: Optional[str] = None,
    required: bool = True,
) -> None:
    if not _nonempty_str(asset_id):
        if required:
            result.error("E_ASSET_REF_EMPTY", "参考图引用为空", where)
        return
    asset = ctx.asset(str(asset_id))
    if asset is None:
        result.error("E_ASSET_REF_UNKNOWN", "引用了不存在的 asset_id：%s" % asset_id, where)
        return
    kind = asset.get("kind")
    if expect_kind and kind != expect_kind:
        result.warning(
            "W_ASSET_KIND",
            "asset %s 的类型是 %s，预期 %s" % (asset_id, kind, expect_kind),
            where,
        )
    if expect_character and asset.get("character_id") != expect_character:
        result.error(
            "E_ASSET_CHARACTER_MISMATCH",
            "asset %s 属于 %s，不属于 %s" % (asset_id, asset.get("character_id"), expect_character),
            where,
        )


def _validate_project(ctx: ProjectContext, result: ValidationResult) -> None:
    project = ctx.project
    where = "project"
    if not _nonempty_str(project.get("project_id")):
        result.error("E_PROJECT_ID", "project_id 不能为空", where)
    if not _nonempty_str(project.get("title")):
        result.warning("W_PROJECT_TITLE", "title 为空", where)
    if str(project.get("schema_version")) != "1.0":
        result.warning("W_SCHEMA_VERSION", "project schema_version 不是 1.0", where)

    fmt = project.get("format") or {}
    if not _nonempty_str(fmt.get("aspect_ratio")):
        result.error("E_FORMAT", "format.aspect_ratio 不能为空", where)
    if not _nonempty_str(fmt.get("resolution")):
        result.warning("W_FORMAT", "format.resolution 为空", where)
    duration_range = fmt.get("shot_duration_range_sec")
    if not (isinstance(duration_range, list) and len(duration_range) == 2 and all(isinstance(x, (int, float)) for x in duration_range)):
        result.warning("W_SHOT_RANGE", "format.shot_duration_range_sec 应为两个数字", where)

    style = project.get("style") or {}
    for key in ("anchor", "quality_suffix", "negative_base"):
        if not _nonempty_str(style.get(key)):
            result.error("E_STYLE", "style.%s 不能为空" % key, where)
    for asset_id in style.get("style_refs") or []:
        _check_asset_ref(ctx, result, asset_id, "project.style", expect_kind="style")

    prompt = project.get("prompt") or {}
    if prompt.get("language") not in ("en", "zh"):
        result.warning("W_PROMPT_LANG", "prompt.language 建议为 en 或 zh", where)
    max_chars = prompt.get("max_chars")
    if not isinstance(max_chars, int) or max_chars < 400:
        result.warning("W_PROMPT_MAX", "prompt.max_chars 建议 >= 400", where)

    defaults = project.get("defaults") or {}
    profiles = ctx.provider_profiles()
    default_provider = defaults.get("provider")
    if default_provider not in profiles:
        result.error("E_DEFAULT_PROVIDER", "defaults.provider 不存在：%s" % default_provider, where)
    for pid in defaults.get("fallback") or []:
        if pid not in profiles:
            result.error("E_FALLBACK_PROVIDER", "defaults.fallback 包含不存在的 provider：%s" % pid, where)
    candidates = defaults.get("candidates_per_shot")
    if not isinstance(candidates, int) or candidates < 1:
        result.warning("W_CANDIDATES", "defaults.candidates_per_shot 建议 >= 1", where)


def _validate_providers(ctx: ProjectContext, result: ValidationResult) -> None:
    profiles = ctx.provider_profiles()
    if not profiles:
        result.error("E_PROVIDERS_EMPTY", "没有任何 provider 配置", "config/providers.json")
        return
    for pid, profile in profiles.items():
        where = "provider:%s" % pid
        if not _nonempty_str(profile.get("display_name")):
            result.warning("W_PROVIDER_NAME", "缺少 display_name", where)
        modes = profile.get("modes")
        if not isinstance(modes, list) or not modes:
            result.error("E_PROVIDER_MODES", "modes 不能为空", where)
        else:
            for mode in modes:
                if mode not in CANONICAL_MODES:
                    result.error("E_PROVIDER_MODE", "未知生成模式：%s" % mode, where)
        max_refs = profile.get("max_refs")
        if not isinstance(max_refs, int) or max_refs < 1:
            result.error("E_PROVIDER_REFS", "max_refs 必须是 >=1 的整数", where)
        durations = profile.get("durations")
        if not isinstance(durations, list) or not durations or not all(isinstance(x, (int, float)) and x > 0 for x in durations):
            result.error("E_PROVIDER_DURATIONS", "durations 必须是非空正数数组", where)
        if profile.get("kind", "").startswith("quota_flow"):
            if not profile.get("cli_provider_id"):
                result.warning("W_PROVIDER_CLI_ID", "Quota-Flow 适配器需要 cli_provider_id", where)
            for mode in modes or []:
                if not isinstance(profile.get("cli_mode_map"), dict):
                    result.warning("W_PROVIDER_CLI_MAP", "cli_mode_map 缺失", where)
                    break
                if mode not in (profile.get("cli_mode_map") or {}):
                    result.warning("W_PROVIDER_CLI_MAP", "cli_mode_map 未覆盖 %s" % mode, where)


def _validate_bank(ctx: ProjectContext, result: ValidationResult) -> None:
    assets = ctx.asset_list()
    if not assets:
        result.error("E_BANK_EMPTY", "参考图库为空", "reference_bank.json")
        return
    seen: Set[str] = set()
    public_url_missing = 0
    for asset in _dicts(assets):
        aid = asset.get("asset_id")
        where = "asset:%s" % (aid or "?")
        if not _nonempty_str(aid):
            result.error("E_ASSET_ID", "asset_id 不能为空", "reference_bank.json")
            continue
        if aid in seen:
            result.error("E_ASSET_DUPLICATE", "asset_id 重复：%s" % aid, where)
        seen.add(aid)
        kind = asset.get("kind")
        if kind not in ASSET_KINDS:
            result.error("E_ASSET_KIND", "未知 kind：%s" % kind, where)
        status = asset.get("status")
        if status not in ASSET_STATUSES:
            result.error("E_ASSET_STATUS", "未知 status：%s" % status, where)
        elif status == "draft":
            result.warning("W_ASSET_DRAFT", "参考图仍是 draft（占位/未审）", where)
        if kind == "character":
            cid = asset.get("character_id")
            if not _nonempty_str(cid):
                result.error("E_ASSET_CHARACTER", "character 类型缺少 character_id", where)
            elif cid not in ctx.characters():
                result.error("E_ASSET_CHARACTER", "character_id 不存在：%s" % cid, where)
        if kind == "scene":
            sid = asset.get("scene_id")
            if not _nonempty_str(sid):
                result.error("E_ASSET_SCENE", "scene 类型缺少 scene_id", where)
            elif sid not in ctx.scenes():
                result.error("E_ASSET_SCENE", "scene_id 不存在：%s" % sid, where)

        try:
            path = ctx.asset_file(asset)
        except (ValueError, Exception) as exc:
            result.error("E_ASSET_PATH", "路径非法：%s" % exc, where)
            continue
        if not path.is_file():
            result.error("E_ASSET_FILE", "参考图文件不存在：%s" % asset.get("path"), where)
            continue
        recorded = asset.get("sha256")
        computed = ctx.asset_hash(asset)
        if not recorded:
            result.warning(
                "W_ASSET_HASH_MISSING",
                "未记录 sha256，建议运行 `python studio.py refresh-hashes`",
                where,
            )
        elif computed != recorded:
            result.error(
                "E_ASSET_HASH",
                "sha256 不匹配：文件已变化。运行 `python studio.py refresh-hashes` 并重新 build。",
                where,
            )
        width = asset.get("width")
        height = asset.get("height")
        if not (isinstance(width, int) and width > 0 and isinstance(height, int) and height > 0):
            result.warning("W_ASSET_DIMENSIONS", "width/height 缺失或非法", where)
        url = asset.get("public_url")
        if not url:
            public_url_missing += 1
        elif not isinstance(url, str) or not url.startswith(("http://", "https://")):
            result.error("E_ASSET_PUBLIC_URL", "public_url 必须是 http(s) URL", where)
        elif not url.startswith("https://"):
            result.warning("W_ASSET_PUBLIC_URL_HTTP", "API 型厂商通常要求 https", where)

    if public_url_missing:
        result.warning(
            "W_PUBLIC_URL_MISSING",
            "%d 张参考图没有 public_url；Quota-Flow 的真实生成需要公网 https URL，mock/handoff 不受影响" % public_url_missing,
            "reference_bank.json",
        )


def _validate_characters(ctx: ProjectContext, result: ValidationResult) -> None:
    characters = ctx.characters()
    if not characters:
        result.error("E_CHARACTERS_EMPTY", "角色卡为空", "characters.json")
        return
    for cid, card in characters.items():
        where = "character:%s" % cid
        if not _nonempty_str(card.get("name")):
            result.error("E_CHARACTER_NAME", "name 不能为空", where)
        if not _nonempty_str(card.get("descriptor_en")):
            result.error("E_CHARACTER_DESCRIPTOR", "descriptor_en 不能为空", where)
        if not _is_list_of_str(card.get("invariants_en")) or not card.get("invariants_en"):
            result.error("E_CHARACTER_INVARIANTS", "invariants_en 必须是非空字符串数组", where)
        if not _is_list_of_str(card.get("negative_en")):
            result.warning("W_CHARACTER_NEGATIVE", "negative_en 建议是非空字符串数组", where)
        status = card.get("status")
        if status not in ASSET_STATUSES:
            result.warning("W_CHARACTER_STATUS", "未知角色状态：%s" % status, where)
        elif status == "draft":
            result.warning("W_CHARACTER_DRAFT", "角色卡仍是 draft", where)
        if card.get("is_placeholder"):
            result.warning("W_CHARACTER_PLACEHOLDER", "角色是占位角色，正式设定到位后替换", where)

        wardrobe = card.get("wardrobe_states") or {}
        default_wardrobe = card.get("default_wardrobe_state")
        if default_wardrobe not in wardrobe:
            result.error("E_WARDROBE_DEFAULT", "default_wardrobe_state 不存在：%s" % default_wardrobe, where)
        for state_name, state in wardrobe.items():
            if not isinstance(state, dict):
                result.error("E_WARDROBE_STATE", "wardrobe state 必须是对象：%s" % state_name, where)
                continue
            if not _nonempty_str(state.get("descriptor_en")):
                result.error("E_WARDROBE_DESCRIPTOR", "wardrobe state %s 缺少 descriptor_en" % state_name, where)
            refs = state.get("refs") or []
            if not _is_list_of_str(refs):
                result.error("E_WARDROBE_REFS", "wardrobe state %s 的 refs 必须是字符串数组" % state_name, where)
                continue
            for asset_id in refs:
                _check_asset_ref(ctx, result, asset_id, where, expect_character=cid, expect_kind="character")

        expression_refs = card.get("expression_refs") or {}
        for expression, refs in expression_refs.items():
            if not _is_list_of_str(refs):
                result.error("E_EXPRESSION_REFS", "expression_refs.%s 必须是字符串数组" % expression, where)
                continue
            for asset_id in refs:
                _check_asset_ref(ctx, result, asset_id, where, expect_character=cid, expect_kind="character")

        refs = card.get("refs") or {}
        identity = refs.get("identity_anchor") or []
        if not _is_list_of_str(identity) or not identity:
            result.error("E_CHARACTER_IDENTITY", "refs.identity_anchor 不能为空", where)
        for key, values in refs.items():
            if not _is_list_of_str(values):
                result.error("E_CHARACTER_REFS", "refs.%s 必须是字符串数组" % key, where)
                continue
            for asset_id in values:
                _check_asset_ref(ctx, result, asset_id, where, expect_character=cid, expect_kind="character")

        initial = card.get("initial_state") or {}
        init_wardrobe = initial.get("wardrobe_state") or default_wardrobe
        if init_wardrobe not in wardrobe:
            result.error("E_INITIAL_STATE", "initial_state.wardrobe_state 不存在：%s" % init_wardrobe, where)
        if not _is_list_of_str(initial.get("injuries")):
            result.warning("W_INITIAL_STATE", "initial_state.injuries 建议是字符串数组", where)
        if not _is_list_of_str(initial.get("props")):
            result.warning("W_INITIAL_STATE", "initial_state.props 建议是字符串数组", where)


def _validate_timeline(ctx: ProjectContext, result: ValidationResult) -> None:
    timeline = ctx.timeline
    if str(timeline.get("schema_version")) != "1.0":
        result.warning("W_SCHEMA_VERSION", "timeline schema_version 不是 1.0", "timeline.json")
    if not _nonempty_str(timeline.get("episode_id")):
        result.error("E_EPISODE_ID", "episode_id 不能为空", "timeline.json")

    scenes = ctx.scenes()
    if not scenes:
        result.error("E_SCENES_EMPTY", "没有场景", "timeline.json")
    for sid, scene in scenes.items():
        where = "scene:%s" % sid
        if not _nonempty_str(scene.get("lighting_en")):
            result.warning("W_SCENE_LIGHTING", "lighting_en 为空，提示词会缺少光照锚点", where)
        if not _nonempty_str(scene.get("location_en")):
            result.warning("W_SCENE_LOCATION", "location_en 为空", where)
        refs = scene.get("refs") or []
        if not _is_list_of_str(refs):
            result.error("E_SCENE_REFS", "refs 必须是字符串数组", where)
            refs = []
        if not refs:
            result.warning("W_SCENE_REFS_EMPTY", "场景没有参考图，多参考模型会缺少场景锚点", where)
        for asset_id in refs:
            _check_asset_ref(ctx, result, asset_id, where, expect_kind="scene")

    shots = ctx.shots()
    if not shots:
        result.error("E_SHOTS_EMPTY", "时间线没有镜头", "timeline.json")
        return
    seen_shots: Set[str] = set()
    seen_lines: Set[str] = set()
    shot_index: Dict[str, int] = {}
    for idx, shot in enumerate(shots):
        sid = shot.get("shot_id")
        if not _nonempty_str(sid):
            result.error("E_SHOT_ID", "shot_id 不能为空", "timeline.json")
            continue
        shot_index[str(sid)] = idx
    for idx, shot in enumerate(shots):
        sid = shot.get("shot_id")
        if not _nonempty_str(sid):
            continue
        where = "shot:%s" % sid
        if sid in seen_shots:
            result.error("E_SHOT_DUPLICATE", "shot_id 重复：%s" % sid, where)
        seen_shots.add(sid)
        if shot.get("scene_id") not in scenes:
            result.error("E_SHOT_SCENE", "scene_id 不存在：%s" % shot.get("scene_id"), where)
        duration = shot.get("duration_sec")
        if not isinstance(duration, (int, float)) or duration <= 0:
            result.error("E_SHOT_DURATION", "duration_sec 必须是正数", where)
        else:
            rng = (ctx.project.get("format") or {}).get("shot_duration_range_sec") or [0, 999]
            if isinstance(rng, list) and len(rng) == 2 and not (rng[0] <= duration <= rng[1]):
                result.warning(
                    "W_SHOT_DURATION_RANGE",
                    "duration_sec=%s 超出项目建议范围 %s-%s" % (duration, rng[0], rng[1]),
                    where,
                )
        if not _nonempty_str(shot.get("action_en")):
            result.error("E_SHOT_ACTION", "action_en 不能为空", where)
        for key, map_key in (("shot_size", "shot_size"), ("camera_move", "camera")):
            value = shot.get(key)
            if not _nonempty_str(value):
                result.error("E_SHOT_FIELD", "%s 不能为空" % key, where)
            else:
                mapping = ctx.prompt_maps.get(map_key) or {}
                if value not in mapping:
                    result.warning("W_PROMPT_MAP", "%s 未在 prompt_maps 中映射：%s" % (key, value), where)

        character_ids = shot.get("character_ids")
        if not isinstance(character_ids, list):
            result.error("E_SHOT_CHARACTERS", "character_ids 必须是数组", where)
            character_ids = []
        for cid in character_ids:
            if cid not in ctx.characters():
                result.error("E_SHOT_CHARACTER", "角色不存在：%s" % cid, where)
        expressions = shot.get("expressions") or {}
        if expressions and not isinstance(expressions, dict):
            result.error("E_SHOT_EXPRESSIONS", "expressions 必须是对象", where)
            expressions = {}
        for cid, expression in (expressions or {}).items():
            if cid not in character_ids:
                result.error("E_SHOT_EXPRESSION_CHARACTER", "expressions 中的角色未出现在本镜：%s" % cid, where)
                continue
            card = ctx.character(cid) or {}
            refs = (card.get("expression_refs") or {}).get(expression) or []
            if not refs:
                result.warning(
                    "W_EXPRESSION_REF_MISSING",
                    "%s 的表情 %s 没有参考图，仅靠文字描述" % (cid, expression),
                    where,
                )

        continuity = shot.get("continuity") or {}
        if not isinstance(continuity, dict):
            result.error("E_SHOT_CONTINUITY", "continuity 必须是对象", where)
            continuity = {}
        from_shot = continuity.get("from_shot")
        if from_shot is not None:
            if from_shot not in shot_index:
                result.error("E_CONTINUITY_FROM", "from_shot 不存在：%s" % from_shot, where)
            elif shot_index[from_shot] >= idx:
                result.error("E_CONTINUITY_ORDER", "from_shot 必须早于当前镜头：%s" % from_shot, where)
        delta_map = continuity.get("state_delta") or {}
        if not isinstance(delta_map, dict):
            result.error("E_STATE_DELTA", "state_delta 必须是对象", where)
            delta_map = {}
        for cid, delta in delta_map.items():
            if cid not in character_ids:
                result.error("E_STATE_DELTA_CHARACTER", "state_delta 的角色未出现在本镜：%s" % cid, where)
                continue
            if not isinstance(delta, dict):
                result.error("E_STATE_DELTA", "state_delta.%s 必须是对象" % cid, where)
                continue
            card = ctx.character(cid) or {}
            wardrobe = card.get("wardrobe_states") or {}
            target = delta.get("wardrobe_state")
            if target and target not in wardrobe:
                result.error("E_STATE_DELTA_WARDROBE", "%s 的 wardrobe_state 不存在：%s" % (cid, target), where)
            for key in ("add_injuries", "remove_injuries", "add_props", "remove_props"):
                if key in delta and not _is_list_of_str(delta.get(key)):
                    result.error("E_STATE_DELTA_LIST", "%s.%s 必须是字符串数组" % (cid, key), where)

        keyframes = shot.get("keyframes") or {}
        if keyframes and not isinstance(keyframes, dict):
            result.error("E_KEYFRAMES", "keyframes 必须是对象", where)
            keyframes = {}
        for key in ("first", "last"):
            asset_id = (keyframes or {}).get(key)
            if asset_id:
                _check_asset_ref(ctx, result, asset_id, where, expect_kind="keyframe")

        overrides = shot.get("reference_overrides") or []
        if not _is_list_of_str(overrides):
            result.error("E_OVERRIDES", "reference_overrides 必须是字符串数组", where)
            overrides = []
        for asset_id in overrides:
            _check_asset_ref(ctx, result, asset_id, where)

        mode_hint = shot.get("mode_hint", "auto")
        if mode_hint != "auto" and mode_hint not in CANONICAL_MODES:
            result.error("E_MODE_HINT", "未知 mode_hint：%s" % mode_hint, where)

        for line in shot.get("dialogue") or []:
            if not isinstance(line, dict):
                result.error("E_DIALOGUE", "dialogue 每项必须是对象", where)
                continue
            line_id = line.get("line_id")
            if line_id in seen_lines:
                result.error("E_LINE_DUPLICATE", "line_id 重复：%s" % line_id, where)
            seen_lines.add(line_id)
            if line.get("character_id") not in character_ids:
                result.warning("W_LINE_CHARACTER", "台词角色不在本镜：%s" % line.get("character_id"), where)

    # State-driven checks: current wardrobe state must have at least one existing ref.
    snapshots = build_state_snapshots(ctx)
    for sid, snap in snapshots.items():
        where = "shot:%s" % sid
        for cid, state in (snap.get("characters") or {}).items():
            card = ctx.character(cid) or {}
            state_name = state.get("wardrobe_state")
            wardrobe = card.get("wardrobe_states") or {}
            if state_name not in wardrobe:
                result.error("E_SNAPSHOT_WARDROBE", "%s 在 %s 的 wardrobe state 不存在：%s" % (cid, sid, state_name), where)
                continue
            refs = wardrobe.get(state_name, {}).get("refs") or []
            if not refs:
                result.error("E_SNAPSHOT_REFS", "%s 当前服装状态 %s 没有参考图" % (cid, state_name), where)


def _validate_orphans(ctx: ProjectContext, result: ValidationResult) -> None:
    used: Set[str] = set()
    for card in ctx.character_list():
        for values in (card.get("refs") or {}).values():
            used.update(values or [])
        for state in (card.get("wardrobe_states") or {}).values():
            used.update((state or {}).get("refs") or [])
        for values in (card.get("expression_refs") or {}).values():
            used.update(values or [])
    for scene in ctx.scene_list():
        used.update(scene.get("refs") or [])
    for shot in ctx.shots():
        used.update((shot.get("reference_overrides") or []))
        used.update((shot.get("keyframes") or {}).values() if isinstance(shot.get("keyframes"), dict) else [])
    used.update((ctx.project.get("style") or {}).get("style_refs") or [])
    for asset in ctx.asset_list():
        aid = asset.get("asset_id")
        if aid and aid not in used:
            result.warning("W_ASSET_ORPHAN", "参考图没有被任何角色/场景/镜头引用", "asset:%s" % aid)


def validate_context(ctx: ProjectContext) -> ValidationResult:
    result = ValidationResult()
    _validate_project(ctx, result)
    _validate_providers(ctx, result)
    _validate_bank(ctx, result)
    _validate_characters(ctx, result)
    _validate_timeline(ctx, result)
    _validate_orphans(ctx, result)
    return result
