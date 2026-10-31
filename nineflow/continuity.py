from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from .context import ProjectContext


def initial_states(ctx: ProjectContext) -> Dict[str, Dict[str, Any]]:
    states: Dict[str, Dict[str, Any]] = {}
    for cid, card in ctx.characters().items():
        init = card.get("initial_state") or {}
        states[cid] = {
            "wardrobe_state": init.get("wardrobe_state") or card.get("default_wardrobe_state"),
            "injuries": list(init.get("injuries") or []),
            "props": list(init.get("props") or []),
        }
    return states


def _add_unique(items: List[str], values) -> List[str]:
    out = list(items)
    for value in values or []:
        if value not in out:
            out.append(value)
    return out


def _remove(items: List[str], values) -> List[str]:
    drop = set(values or [])
    return [x for x in items if x not in drop]


def apply_state_delta(state: Dict[str, Any], delta: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "wardrobe_state": state.get("wardrobe_state"),
        "injuries": list(state.get("injuries") or []),
        "props": list(state.get("props") or []),
    }
    if not delta:
        return out
    if delta.get("wardrobe_state"):
        out["wardrobe_state"] = delta["wardrobe_state"]
    out["injuries"] = _remove(out["injuries"], delta.get("remove_injuries"))
    out["injuries"] = _add_unique(out["injuries"], delta.get("add_injuries"))
    out["props"] = _remove(out["props"], delta.get("remove_props"))
    out["props"] = _add_unique(out["props"], delta.get("add_props"))
    return out


def diff_states(before: Optional[Dict[str, Any]], after: Dict[str, Any]) -> List[str]:
    if before is None:
        return ["first appearance"]
    changes: List[str] = []
    if before.get("wardrobe_state") != after.get("wardrobe_state"):
        changes.append(
            "wardrobe %s -> %s" % (before.get("wardrobe_state") or "?", after.get("wardrobe_state") or "?")
        )
    before_inj = list(before.get("injuries") or [])
    after_inj = list(after.get("injuries") or [])
    for item in after_inj:
        if item not in before_inj:
            changes.append("injury + %s" % item)
    for item in before_inj:
        if item not in after_inj:
            changes.append("injury - %s" % item)
    before_props = list(before.get("props") or [])
    after_props = list(after.get("props") or [])
    for item in after_props:
        if item not in before_props:
            changes.append("prop + %s" % item)
    for item in before_props:
        if item not in after_props:
            changes.append("prop - %s" % item)
    if not changes:
        changes.append("state carried")
    return changes


def build_state_snapshots(ctx: ProjectContext) -> Dict[str, Dict[str, Any]]:
    """Walk the timeline once and produce the canonical state snapshot for every shot.

    The timeline is the only place where continuity changes. Every provider compiles
    from these snapshots, so no model gets a different costume/injury/prop state.
    """
    states = initial_states(ctx)
    snapshots: Dict[str, Dict[str, Any]] = {}
    previous_shot_id: Optional[str] = None

    for shot in ctx.shots():
        shot_id = shot.get("shot_id")
        if not shot_id:
            continue
        present_ids = list(shot.get("character_ids") or [])
        before_present = {cid: copy.deepcopy(states[cid]) for cid in present_ids if cid in states}

        delta_map = (shot.get("continuity") or {}).get("state_delta") or {}
        for cid, delta in delta_map.items():
            if cid in states:
                states[cid] = apply_state_delta(states[cid], delta or {})

        after_present = {cid: copy.deepcopy(states[cid]) for cid in present_ids if cid in states}
        expressions = shot.get("expressions") or {}
        character_snapshots = {}
        changes = {}
        for cid, state in after_present.items():
            character_snapshots[cid] = {
                **state,
                "expression": expressions.get(cid) or "neutral",
            }
            changes[cid] = diff_states(before_present.get(cid), state)

        scene = ctx.scene(str(shot.get("scene_id"))) or {}
        from_shot = (shot.get("continuity") or {}).get("from_shot")
        if from_shot is None:
            from_shot = previous_shot_id

        snapshots[str(shot_id)] = {
            "shot_id": shot_id,
            "scene_id": shot.get("scene_id"),
            "from_shot": from_shot,
            "scene": {
                "scene_id": scene.get("scene_id"),
                "label": scene.get("label"),
                "location_en": scene.get("location_en"),
                "time_of_day": scene.get("time_of_day"),
                "lighting_en": scene.get("lighting_en"),
                "composition_en": scene.get("composition_en"),
                "refs": list(scene.get("refs") or []),
            },
            "characters": character_snapshots,
            "changes": changes,
            "notes": (shot.get("continuity") or {}).get("notes") or "",
        }
        previous_shot_id = str(shot_id)

    return snapshots
