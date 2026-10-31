from __future__ import annotations

import unittest

from support import TempProjectCase
from nineflow.continuity import apply_state_delta, build_state_snapshots


class ContinuityTest(TempProjectCase):
    def test_wardrobe_and_injury_evolve_in_shot_order(self) -> None:
        snapshots = build_state_snapshots(self.ctx)
        first = snapshots["E01-001"]["characters"]["CH_LINYE_01"]
        second = snapshots["E01-002"]["characters"]["CH_LINYE_01"]
        third = snapshots["E01-003"]["characters"]["CH_LINYE_01"]
        fourth = snapshots["E01-004"]["characters"]["CH_LINYE_01"]
        fifth = snapshots["E01-005"]["characters"]["CH_LINYE_01"]

        self.assertEqual(first["wardrobe_state"], "home_clean")
        self.assertEqual(second["wardrobe_state"], "home_dirty")
        self.assertEqual(third["wardrobe_state"], "home_dirty")
        self.assertEqual(fourth["wardrobe_state"], "home_injured")
        self.assertEqual(
            fourth["injuries"],
            ["bruise on left cheek", "small cut on lower lip"],
        )
        self.assertEqual(fifth["injuries"], fourth["injuries"])

    def test_changes_are_derived_from_the_previous_shot(self) -> None:
        snapshots = build_state_snapshots(self.ctx)
        self.assertIn(
            "wardrobe home_clean -> home_dirty",
            snapshots["E01-002"]["changes"]["CH_LINYE_01"],
        )
        self.assertIn(
            "injury + bruise on left cheek",
            snapshots["E01-004"]["changes"]["CH_LINYE_01"],
        )
        self.assertEqual(snapshots["E01-002"]["from_shot"], "E01-001")
        self.assertEqual(snapshots["E01-003"]["changes"]["CH_LINYE_01"], ["state carried"])

    def test_apply_state_delta_adds_and_removes(self) -> None:
        state = {
            "wardrobe_state": "home_clean",
            "injuries": [],
            "props": ["bat"],
            "expressions": {},
        }
        updated = apply_state_delta(
            state,
            {
                "wardrobe_state": "home_dirty",
                "add_injuries": ["bruise_left_cheek"],
                "add_props": ["gloves"],
            },
        )
        self.assertEqual(updated["wardrobe_state"], "home_dirty")
        self.assertEqual(updated["injuries"], ["bruise_left_cheek"])
        self.assertEqual(updated["props"], ["bat", "gloves"])

        cleaned = apply_state_delta(
            updated,
            {"remove_injuries": ["bruise_left_cheek"], "remove_props": ["bat"]},
        )
        self.assertEqual(cleaned["injuries"], [])
        self.assertEqual(cleaned["props"], ["gloves"])
        self.assertEqual(updated["injuries"], ["bruise_left_cheek"])


if __name__ == "__main__":
    unittest.main()
