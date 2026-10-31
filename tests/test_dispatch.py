from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from unittest.mock import patch

from support import TempProjectCase
from nineflow.adapters import quota_flow
from nineflow.context_pack import get_variant
from nineflow.dispatch import DispatchError, execute, execute_many
from nineflow.jobs import ledger_path, list_jobs, load_job

try:
    import PIL  # noqa: F401

    HAVE_PIL = True
except Exception:
    HAVE_PIL = False

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


class DispatchTest(TempProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.pack = self.build()

    def test_mock_dry_run_records_a_job_without_outputs(self) -> None:
        job = execute(self.ctx, "E01-001", "mock", dry_run=True, pack=self.pack)

        self.assertEqual(job["status"], "dry_run")
        self.assertTrue(job["dry_run"])
        self.assertEqual(job["context_revision"], self.pack["context_revision"])
        self.assertEqual(job["outputs"], [])
        self.assertIn("ffmpeg", " ".join(job["command"]))
        self.assertTrue(ledger_path(self.ctx).is_file())

        records = [json.loads(line) for line in ledger_path(self.ctx).read_text(encoding="utf-8").splitlines()]
        self.assertEqual([record["event"] for record in records], ["queued", "running", "dry_run"])
        self.assertEqual(records[-1]["job_id"], job["job_id"])

    @unittest.skipUnless(HAVE_FFMPEG and HAVE_PIL, "mock adapter needs ffmpeg and Pillow")
    def test_mock_generation_produces_video_and_slate(self) -> None:
        job = execute(self.ctx, "E01-001", "mock", dry_run=False, pack=self.pack)

        self.assertEqual(job["status"], "succeeded", job.get("error"))
        kinds = {item["kind"] for item in job["outputs"]}
        self.assertEqual(kinds, {"video", "slate"})
        for item in job["outputs"]:
            self.assertTrue((self.ctx.root / item["path"]).is_file(), item["path"])
            self.assertGreater(item["bytes"], 0)

        probe = job["adapter_meta"].get("probe") or {}
        self.assertAlmostEqual(probe.get("duration_sec", 0), 5.0, places=1)
        self.assertEqual(probe.get("width"), 1920)
        self.assertEqual(probe.get("height"), 1080)

        reloaded = load_job(self.ctx, job["job_id"])
        self.assertEqual(reloaded["status"], "succeeded")
        variant = get_variant(self.pack, "E01-001", "mock")
        self.assertEqual(reloaded["prompt_sha256"], variant["prompt_sha256"])

    def test_handoff_exports_a_complete_package(self) -> None:
        job = execute(self.ctx, "E01-001", "handoff", dry_run=False, pack=self.pack)
        self.assertEqual(job["status"], "succeeded", job.get("error"))

        folder = self.ctx.root / "exports" / "handoff" / job["job_id"]
        self.assertTrue((folder / "prompt.txt").is_file())
        self.assertTrue((folder / "negative.txt").is_file())
        self.assertTrue((folder / "README.md").is_file())
        refs = sorted((folder / "refs").iterdir())
        self.assertEqual(len(refs), 3)

        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["context_revision"], self.pack["context_revision"])
        self.assertEqual(len(manifest["references"]), 3)
        self.assertEqual(manifest["references"][0]["role"], "identity")

    def test_unready_quota_flow_job_is_blocked_before_any_vendor_call(self) -> None:
        job = execute(self.ctx, "E01-001", "qwenwan", dry_run=False, pack=self.pack)

        self.assertEqual(job["status"], "blocked")
        self.assertIn("public_url", job["error"])
        self.assertEqual(job["outputs"], [])

    def _fake_cli(self, payload: dict) -> str:
        script = self.project_dir / "fake_quota_flow.py"
        source = "import json\nDATA = %r\nprint(json.dumps(DATA, ensure_ascii=True))\n" % payload
        script.write_text(source, encoding="utf-8")
        return str(script)

    def _ready_variant(self, provider_id: str = "qwenwan") -> dict:
        variant = json.loads(json.dumps(get_variant(self.pack, "E01-001", "qwenwan")))
        variant["dispatch"] = {
            "adapter": "quota_flow",
            "quota_flow_provider": provider_id,
            "quota_flow_mode": "img2video",
            "requires_public_urls": True,
            "image_urls": ["https://example.com/linye_front_v01.png"],
            "missing_public_urls": [],
            "non_https_public_urls": [],
            "ready": True,
            "block_reasons": [],
        }
        return variant

    def test_cli_dry_run_is_recorded_as_dry_run_not_success(self) -> None:
        payload = {
            "ok": True,
            "rounds": 0,
            "attempts": [{"providerId": "qwenwan", "ok": True}],
            "result": {
                "ok": True,
                "providerId": "qwenwan",
                "traceId": "qwen-dryrun-123",
                "videoUrl": "https://example.com/qwen-dryrun/img2video.mp4",
                "quotaUsed": 1,
                "raw": {"warning": "~/.quota-flow/qwen-auth.json 未配置，已降级为 dry-run。"},
            },
        }
        script = self._fake_cli(payload)
        with patch.object(quota_flow, "_resolve_cli", return_value=([sys.executable, script], [])):
            outcome = quota_flow.run(self.ctx, self._ready_variant(), "JOB_TEST_DRY")

        self.assertEqual(outcome.status, "dry_run")
        self.assertEqual({item["kind"] for item in outcome.outputs}, {"quota_flow_json"})
        joined = " ".join(outcome.warnings)
        self.assertIn("未生成真实视频", joined)
        self.assertIn("仍可能扣减本地额度", joined)
        self.assertIsNone(outcome.error)

    def test_cli_provider_substitution_is_rejected(self) -> None:
        payload = {
            "ok": True,
            "rounds": 0,
            "attempts": [{"providerId": "qwenwan", "ok": True}],
            "result": {
                "ok": True,
                "providerId": "qwenwan",
                "traceId": "qwen-dryrun-456",
                "videoUrl": "https://example.com/qwen-dryrun/img2video.mp4",
                "quotaUsed": 1,
                "raw": {"warning": "dry-run"},
            },
        }
        script = self._fake_cli(payload)
        with patch.dict(os.environ, {"NINEFLOW_QF_ALLOW_PROVIDER_SWITCH": ""}):
            with patch.object(quota_flow, "_resolve_cli", return_value=([sys.executable, script], [])):
                outcome = quota_flow.run(self.ctx, self._ready_variant("yuanbao"), "JOB_TEST_SWAP")

        self.assertEqual(outcome.status, "failed")
        self.assertIn("厂商不一致", outcome.error)
        self.assertEqual({item["kind"] for item in outcome.outputs}, {"quota_flow_json"})

    def test_stale_pack_is_rejected(self) -> None:
        from nineflow.util import read_json, write_json

        project = read_json(self.project_dir / "project.json")
        project["title"] = project["title"] + " · changed"
        write_json(self.project_dir / "project.json", project)
        ctx = self.context()

        with self.assertRaises(DispatchError) as caught:
            execute(ctx, "E01-001", "mock", dry_run=True, pack=self.pack)
        self.assertIn("上下文已变化", str(caught.exception))

        with self.assertRaises(DispatchError):
            execute(ctx, "E01-001", "mock", dry_run=True)

    def test_execute_many_filters_shots_and_providers(self) -> None:
        jobs = execute_many(
            self.ctx,
            shot_ids=["E01-001", "E01-002"],
            provider_ids=["mock"],
            dry_run=True,
            pack=self.pack,
        )
        self.assertEqual([(j["shot_id"], j["provider_id"]) for j in jobs], [("E01-001", "mock"), ("E01-002", "mock")])
        self.assertEqual({j["status"] for j in jobs}, {"dry_run"})
        self.assertEqual(len(list_jobs(self.ctx, limit=10)), 2)

    def test_unknown_variant_is_reported(self) -> None:
        with self.assertRaises(DispatchError):
            execute(self.ctx, "E01-999", "mock", dry_run=True, pack=self.pack)


if __name__ == "__main__":
    unittest.main()
