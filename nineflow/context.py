from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__
from .util import read_json, resolve_within, sha256_file, sha256_json

APP_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = APP_ROOT / "config"
DEFAULT_PROJECT_DIR = APP_ROOT / "projects" / "nine-inning-bottom"

# Files whose behavior shapes prompts or continuity snapshots. Hashing them into
# context_revision makes a compiler/state-machine change invalidate every pack.
ENGINE_FILES = ("context.py", "compiler.py", "continuity.py")

CANONICAL_MODES = {"text2video", "img2video", "multi_ref", "first_last"}
ASSET_STATUSES = {"draft", "approved", "locked"}
ASSET_KINDS = {"character", "scene", "prop", "style", "keyframe"}


class ContextError(Exception):
    pass


@dataclass
class ProjectContext:
    root: Path
    config_dir: Path
    project: Dict[str, Any]
    characters_doc: Dict[str, Any]
    bank_doc: Dict[str, Any]
    timeline: Dict[str, Any]
    providers_doc: Dict[str, Any]
    prompt_maps: Dict[str, Any]

    # ---------- basic accessors ----------

    @property
    def project_id(self) -> str:
        return str(self.project.get("project_id") or self.root.name)

    @property
    def title(self) -> str:
        return str(self.project.get("title") or self.project_id)

    def character_list(self) -> List[Dict[str, Any]]:
        return list(self.characters_doc.get("characters") or [])

    def characters(self) -> Dict[str, Dict[str, Any]]:
        return {c["character_id"]: c for c in self.character_list() if c.get("character_id")}

    def character(self, character_id: str) -> Optional[Dict[str, Any]]:
        return self.characters().get(character_id)

    def asset_list(self) -> List[Dict[str, Any]]:
        return list(self.bank_doc.get("assets") or [])

    def assets(self) -> Dict[str, Dict[str, Any]]:
        return {a["asset_id"]: a for a in self.asset_list() if a.get("asset_id")}

    def asset(self, asset_id: str) -> Optional[Dict[str, Any]]:
        return self.assets().get(asset_id)

    def scene_list(self) -> List[Dict[str, Any]]:
        return list(self.timeline.get("scenes") or [])

    def scenes(self) -> Dict[str, Dict[str, Any]]:
        return {s["scene_id"]: s for s in self.scene_list() if s.get("scene_id")}

    def scene(self, scene_id: str) -> Optional[Dict[str, Any]]:
        return self.scenes().get(scene_id)

    def shots(self) -> List[Dict[str, Any]]:
        return list(self.timeline.get("shots") or [])

    def shot(self, shot_id: str) -> Optional[Dict[str, Any]]:
        for shot in self.shots():
            if shot.get("shot_id") == shot_id:
                return shot
        return None

    def provider_profiles(self) -> Dict[str, Dict[str, Any]]:
        base = dict(self.providers_doc.get("providers") or {})
        overrides = self.project.get("provider_overrides") or {}
        merged: Dict[str, Dict[str, Any]] = {}
        for pid, profile in base.items():
            item = dict(profile)
            if pid in overrides:
                item.update(overrides[pid] or {})
            merged[pid] = item
        for pid, profile in overrides.items():
            if pid not in merged:
                merged[pid] = dict(profile)
        return merged

    def provider(self, provider_id: str) -> Optional[Dict[str, Any]]:
        return self.provider_profiles().get(provider_id)

    def provider_order(self) -> List[str]:
        profiles = self.provider_profiles()
        order = [p for p in (self.providers_doc.get("ui_order") or []) if p in profiles]
        for pid, profile in profiles.items():
            if pid in order:
                continue
            if profile.get("enabled", True) is False:
                continue
            order.append(pid)
        return order

    # ---------- files and identity ----------

    def asset_file(self, asset: Dict[str, Any]) -> Path:
        rel = asset.get("path")
        if not rel:
            raise ContextError("asset %s 缺少 path" % asset.get("asset_id"))
        return resolve_within(self.root, str(rel))

    def asset_hash(self, asset: Dict[str, Any]) -> Optional[str]:
        try:
            path = self.asset_file(asset)
        except (ValueError, ContextError):
            return None
        if not path.is_file():
            return None
        return sha256_file(path)

    def normalized_bank(self) -> Dict[str, Any]:
        """Bank copy used for revision: recorded sha256 is replaced by the actual file hash.

        This means refreshing the recorded hashes does not change the context revision,
        while replacing an image file does.
        """
        bank = copy.deepcopy(self.bank_doc)
        for asset in bank.get("assets") or []:
            asset["sha256"] = self.asset_hash(asset) or ""
        return bank

    def engine_fingerprint(self) -> Dict[str, Any]:
        base = Path(__file__).resolve().parent
        files = {}
        for name in ENGINE_FILES:
            path = base / name
            files[name] = sha256_file(path) if path.is_file() else "missing"
        return {"nineflow_version": __version__, "files": files}

    def source_hashes(self) -> Dict[str, Any]:
        assets = {}
        for asset in self.asset_list():
            aid = asset.get("asset_id")
            if not aid:
                continue
            assets[aid] = self.asset_hash(asset) or "missing"
        return {
            "project": sha256_json(self.project),
            "characters": sha256_json(self.characters_doc),
            "reference_bank": sha256_json(self.normalized_bank()),
            "timeline": sha256_json(self.timeline),
            "providers": sha256_json(self.provider_profiles()),
            "prompt_maps": sha256_json(self.prompt_maps),
            "assets": assets,
            "engine": self.engine_fingerprint(),
        }

    def context_revision(self) -> str:
        return sha256_json(self.source_hashes())


def _load_json_required(path: Path, label: str) -> Dict[str, Any]:
    if not path.is_file():
        raise ContextError("缺少 %s：%s" % (label, path))
    try:
        data = read_json(path)
    except Exception as exc:
        raise ContextError("%s 不是合法 JSON：%s（%s）" % (label, path, exc))
    if not isinstance(data, dict):
        raise ContextError("%s 顶层必须是对象：%s" % (label, path))
    return data


def load_context(project_dir: Optional[Path] = None, config_dir: Optional[Path] = None) -> ProjectContext:
    project_root = Path(project_dir or DEFAULT_PROJECT_DIR).resolve()
    cfg_root = Path(config_dir or DEFAULT_CONFIG_DIR).resolve()
    if not project_root.is_dir():
        raise ContextError("项目目录不存在：%s" % project_root)
    project = _load_json_required(project_root / "project.json", "project.json")
    characters = _load_json_required(project_root / str(project.get("characters_file") or "characters.json"), "characters.json")
    bank = _load_json_required(project_root / str(project.get("reference_bank_file") or "reference_bank.json"), "reference_bank.json")
    timeline = _load_json_required(project_root / str(project.get("timeline_file") or "timeline.json"), "timeline.json")
    providers = _load_json_required(cfg_root / "providers.json", "config/providers.json")
    prompt_maps = _load_json_required(cfg_root / "prompt_maps.json", "config/prompt_maps.json")
    return ProjectContext(
        root=project_root,
        config_dir=cfg_root,
        project=project,
        characters_doc=characters,
        bank_doc=bank,
        timeline=timeline,
        providers_doc=providers,
        prompt_maps=prompt_maps,
    )
