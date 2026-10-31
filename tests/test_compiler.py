from __future__ import annotations

import unittest

from support import TempProjectCase
from cinelock.compiler import _build_dispatch
from cinelock.context_pack import build_pack


class CompilerTest(TempProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.pack = self.build()
        self.variants = self.pack["variants"]
        self.profiles = self.ctx.provider_profiles()

    def test_every_variant_respects_provider_capability_and_starts_with_identity(self) -> None:
        for variant in self.variants:
            profile = self.profiles[variant["provider_id"]]
            refs = variant["references"]
            with self.subTest(shot=variant["shot_id"], provider=variant["provider_id"]):
                self.assertIn(variant["mode"], profile["modes"])
                self.assertGreaterEqual(len(refs), 1)
                self.assertLessEqual(len(refs), int(profile["max_refs"]))
                self.assertEqual(variant["reference_count"], len(refs))
                self.assertIn(refs[0]["role"], ("identity", "identity_first_frame"))
                self.assertEqual(refs[0]["asset_id"], "REF_LINYE_FRONT_V01")

    def test_single_reference_providers_use_image_to_video(self) -> None:
        for variant in self.variants:
            profile = self.profiles[variant["provider_id"]]
            if int(profile["max_refs"]) == 1:
                self.assertEqual(variant["mode"], "img2video")
                self.assertIn("Animate from the first-frame still", variant["prompt"])

    def test_prompt_carries_identity_wardrobe_and_injury_state(self) -> None:
        lookup = {(v["shot_id"], v["provider_id"]): v for v in self.variants}
        first = lookup[("E01-001", "mock")]["prompt"]
        dirty = lookup[("E01-002", "mock")]["prompt"]
        injured = lookup[("E01-004", "mock")]["prompt"]

        for prompt in (first, dirty, injured):
            self.assertIn("cinematic 2D anime", prompt)
            self.assertIn("jersey number 7", prompt)
            self.assertIn("scar over the right eyebrow", prompt)
            self.assertIn("Reference images, in order", prompt)

        self.assertIn("Current wardrobe: clean white home jersey", first)
        self.assertIn("Current wardrobe: white home jersey stained with infield dirt and sweat", dirty)
        self.assertIn("Visible injuries: bruise on left cheek", injured)
        self.assertIn("wardrobe home_dirty -> home_injured", injured)

    def test_all_providers_share_the_same_continuity_snapshot(self) -> None:
        by_shot = {}
        for variant in self.variants:
            by_shot.setdefault(variant["shot_id"], []).append(variant)
        for shot_id, variants in by_shot.items():
            snapshots = {repr(variant["continuity"]) for variant in variants}
            self.assertEqual(len(snapshots), 1, shot_id)

    def test_empty_or_non_duplicating_negative_prompt_handling(self) -> None:
        for variant in self.variants:
            self.assertIn(variant["negative_mode"], ("separate", "inline"))
            self.assertTrue(variant["negative_prompt"])
            if variant["negative_mode"] == "inline":
                self.assertIn("Avoid:", variant["prompt"])
            else:
                self.assertNotIn("Avoid:", variant["prompt"])

    def test_duration_is_adapted_to_the_provider(self) -> None:
        for variant in self.variants:
            profile = self.profiles[variant["provider_id"]]
            self.assertIn(variant["duration_sec"], profile["durations"])
            self.assertEqual(variant["requested_duration_sec"], self.ctx.shot(variant["shot_id"])["duration_sec"])
            self.assertIn(variant["duration_choice"], ("exact", "nearest", "truncated", "extended"))

    def test_compilation_is_deterministic(self) -> None:
        second = build_pack(self.ctx, write=False)
        left = [(v["shot_id"], v["provider_id"], v["prompt_sha256"], v["variant_sha256"], v["seed"]) for v in self.variants]
        right = [(v["shot_id"], v["provider_id"], v["prompt_sha256"], v["variant_sha256"], v["seed"]) for v in second["variants"]]
        self.assertEqual(left, right)

    def test_default_matrix_is_platform_agnostic(self) -> None:
        self.assertEqual(
            self.ctx.provider_order(),
            ["mock", "handoff", "comfyui", "official_kling", "official_runway"],
        )
        expected = {
            "mock": "mock",
            "handoff": "handoff",
            "comfyui": "comfyui",
            "official_kling": "http_api",
            "official_runway": "http_api",
        }
        for provider_id, adapter in expected.items():
            self.assertEqual(self.profiles[provider_id]["adapter"], adapter)
        self.assertEqual(self.profiles["comfyui"]["max_refs"], 10)
        self.assertTrue(self.profiles["comfyui"]["experimental"])
        self.assertEqual(set(self.profiles["official_kling"]["modes"]), {"text2video", "img2video", "first_last"})
        self.assertNotIn("cli_provider_id", self.profiles["mock"])

    def test_comfyui_gets_the_same_identity_anchor_and_multi_reference_prompt(self) -> None:
        lookup = {(v["shot_id"], v["provider_id"]): v for v in self.variants}
        variant = lookup[("E01-004", "comfyui")]
        mock_variant = lookup[("E01-004", "mock")]
        self.assertEqual(variant["mode"], "multi_ref")
        self.assertEqual(variant["dispatch"]["adapter"], "comfyui")
        self.assertEqual(variant["dispatch"]["endpoint"], "http://127.0.0.1:8188")
        self.assertGreater(variant["reference_count"], 1)
        self.assertEqual(variant["references"][0]["asset_id"], "REF_LINYE_FRONT_V01")
        self.assertIn("Reference images, in order", variant["prompt"])
        self.assertEqual(
            [ref["asset_id"] for ref in variant["references"]],
            [ref["asset_id"] for ref in mock_variant["references"]],
        )

    def test_official_providers_carry_non_secret_adapter_config(self) -> None:
        lookup = {(v["shot_id"], v["provider_id"]): v for v in self.variants}
        variant = lookup[("E01-001", "official_runway")]
        provider = variant["provider"]
        self.assertEqual(provider["adapter"], "http_api")
        self.assertEqual(provider["preset"], "runway")
        self.assertEqual(provider["base_url"], "https://api.dev.runwayml.com")
        self.assertEqual(provider["api_key_env"], "RUNWAY_API_KEY")
        self.assertNotIn("api_key", provider)
        self.assertEqual(variant["dispatch"]["preset"], "runway")
        self.assertEqual(variant["dispatch"]["requires_env"], ["RUNWAY_API_KEY"])

    def test_unknown_or_disabled_adapter_is_blocked_instead_of_silently_routed(self) -> None:
        blockers = []
        warnings = []
        dispatch = _build_dispatch({"display_name": "Bogus", "adapter": "bogus"}, "text2video", [], blockers, warnings)
        self.assertEqual(dispatch["adapter"], "manual")
        self.assertFalse(dispatch["ready"])
        self.assertIn("B_ADAPTER_UNKNOWN", {item["code"] for item in blockers})

        blockers = []
        warnings = []
        dispatch = _build_dispatch(
            {"display_name": "Off", "adapter": "mock", "enabled": False}, "text2video", [], blockers, warnings
        )
        self.assertFalse(dispatch["ready"])
        self.assertIn("B_PROVIDER_DISABLED", {item["code"] for item in blockers})


if __name__ == "__main__":
    unittest.main()
