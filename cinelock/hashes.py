from __future__ import annotations

import copy
from typing import Any, Dict, List

from .context import ProjectContext
from .util import resolve_within, sha256_file, short_hash, write_json


class HashRefreshError(Exception):
    pass


def refresh_reference_hashes(ctx: ProjectContext) -> Dict[str, Any]:
    bank = copy.deepcopy(ctx.bank_doc)
    assets = bank.get("assets") or []
    if not assets:
        raise HashRefreshError("reference_bank.json 没有 assets，无法刷新哈希")

    updated: List[Dict[str, Any]] = []
    missing: List[Dict[str, str]] = []
    unchanged = 0
    for asset in assets:
        asset_id = str(asset.get("asset_id") or "?")
        relative = asset.get("path")
        if not relative:
            missing.append({"asset_id": asset_id, "path": "", "error": "缺少 path"})
            continue
        try:
            path = resolve_within(ctx.root, str(relative))
        except ValueError as exc:
            missing.append({"asset_id": asset_id, "path": str(relative), "error": str(exc)})
            continue
        if not path.is_file():
            missing.append({"asset_id": asset_id, "path": str(relative), "error": "文件不存在"})
            continue
        digest = sha256_file(path)
        previous = asset.get("sha256")
        if previous == digest:
            unchanged += 1
            continue
        asset["sha256"] = digest
        updated.append(
            {
                "asset_id": asset_id,
                "path": str(relative),
                "old": previous,
                "new": digest,
            }
        )

    if missing:
        raise HashRefreshError(
            "有 %d 个参考图无法刷新，未写入任何变化：%s"
            % (
                len(missing),
                "；".join("%s（%s）" % (item["asset_id"], item["error"]) for item in missing),
            )
        )

    bank_path = ctx.root / "reference_bank.json"
    if updated:
        write_json(bank_path, bank)
        ctx.bank_doc = bank

    return {
        "ok": True,
        "reference_bank": str(bank_path),
        "updated": updated,
        "unchanged": unchanged,
        "missing": [],
        "context_revision": ctx.context_revision(),
        "short_revision": short_hash(ctx.context_revision()),
        "note": "刷新记录哈希不会改变 context_revision；修订由实际文件哈希决定。",
    }
