from __future__ import annotations

import unittest

from support import TempProjectCase
from cinelock.context_pack import build_pack, load_pack, pack_is_current, variant_file
from cinelock.util import read_json, write_json


class ContextRevisionTest(TempProjectCase):
    def test_validation_has_no_errors(self) -> None:
        from cinelock.validate import validate_context

        result = validate_context(self.ctx)
        self.assertTrue(result.ok, [issue.to_dict() for issue in result.errors])
        self.assertGreater(len(result.warnings), 0)

    def test_timeline_change_changes_revision_and_invalidates_pack(self) -> None:
        pack = self.build()
        self.assertTrue(pack_is_current(self.ctx, pack))

        timeline = read_json(self.project_dir / "timeline.json")
        timeline["title"] = timeline["title"] + " · revised"
        write_json(self.project_dir / "timeline.json", timeline)

        ctx = self.context()
        self.assertNotEqual(ctx.context_revision(), pack["context_revision"])
        self.assertFalse(pack_is_current(ctx, pack))

        new_pack = build_pack(ctx)
        self.assertTrue(pack_is_current(ctx, new_pack))
        self.assertNotEqual(new_pack["context_revision"], pack["context_revision"])

    def test_recorded_hash_edit_does_not_change_revision_but_image_bytes_do(self) -> None:
        bank_path = self.project_dir / "reference_bank.json"
        before = self.ctx.context_revision()

        bank = read_json(bank_path)
        bank["assets"][0]["sha256"] = "0" * 64
        write_json(bank_path, bank)
        self.assertEqual(self.context().context_revision(), before)

        image = self.project_dir / "refs" / "characters" / "linye" / "linye_front_v01.png"
        with image.open("ab") as fh:
            fh.write(b"\0")
        self.assertNotEqual(self.context().context_revision(), before)

    def test_environment_reports_no_node_dependency(self) -> None:
        from cinelock.environment import environment_report

        env = environment_report(self.ctx)
        self.assertFalse(env["node_required"])
        self.assertEqual(env["adapters"], ["comfyui", "handoff", "http_api", "mock"])
        self.assertEqual(len(env["providers"]), len(self.ctx.provider_order()))

    def test_pack_covers_every_shot_and_provider_with_one_revision(self) -> None:
        pack = self.build()
        ctx = self.ctx
        expected = len(ctx.shots()) * len(ctx.provider_order())
        variants = pack["variants"]

        self.assertEqual(pack["stats"]["variant_count"], expected)
        self.assertEqual(len(variants), expected)
        self.assertEqual({v["context_revision"] for v in variants}, {pack["context_revision"]})
        self.assertEqual({v["shot_id"] for v in variants}, {s["shot_id"] for s in ctx.shots()})
        self.assertEqual({v["provider_id"] for v in variants}, set(ctx.provider_order()))
        self.assertGreater(pack["stats"]["total_references"], 0)

    def test_rebuild_removes_stale_variant_files(self) -> None:
        self.build()
        stale = self.project_dir / "context" / "shots" / "E01-001" / "removed_provider.json"
        stale.write_text("{}", encoding="utf-8")
        self.assertTrue(stale.is_file())

        self.build()
        self.assertFalse(stale.exists())

    def test_pack_writes_per_variant_files(self) -> None:
        pack = self.build()
        loaded = load_pack(self.ctx)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["context_revision"], pack["context_revision"])

        for shot_id, provider_id in (("E01-001", "mock"), ("E01-004", "official_kling"), ("E01-005", "handoff")):
            json_path = variant_file(self.ctx, shot_id, provider_id)
            self.assertTrue(json_path.is_file(), json_path)
            self.assertTrue(json_path.with_suffix(".prompt.txt").is_file(), json_path)


if __name__ == "__main__":
    unittest.main()
