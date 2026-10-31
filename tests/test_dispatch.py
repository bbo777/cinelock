from __future__ import annotations

import json
import os
import shutil
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from support import TempProjectCase
from cinelock.context_pack import get_variant
from cinelock.dispatch import DispatchError, execute, execute_many
from cinelock.jobs import ledger_path, list_jobs, load_job

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

    def test_handoff_can_bundle_a_zip(self) -> None:
        job = execute(
            self.ctx,
            "E01-001",
            "handoff",
            dry_run=False,
            pack=self.pack,
            options={"bundle": "zip"},
        )
        self.assertEqual(job["status"], "succeeded", job.get("error"))
        bundle = next(item for item in job["outputs"] if item["kind"] == "zip")
        zip_path = self.ctx.root / bundle["path"]
        self.assertTrue(zip_path.is_file())
        self.assertGreater(bundle["bytes"], 0)

        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
        self.assertTrue(any(name.endswith("/manifest.json") for name in names))
        self.assertTrue(any("/refs/" in name for name in names))

    def test_comfyui_dry_run_returns_a_plan_without_network(self) -> None:
        job = execute(self.ctx, "E01-001", "comfyui", dry_run=True, pack=self.pack)

        self.assertEqual(job["status"], "dry_run", job.get("error"))
        self.assertTrue(job["plan"])
        self.assertEqual(job["outputs"], [])
        self.assertEqual(job["adapter_meta"]["base_url"], "http://127.0.0.1:8188")
        self.assertTrue(job["adapter_meta"]["workflow_sha256"])

    def test_comfyui_missing_workflow_fails_clearly(self) -> None:
        job = execute(
            self.ctx,
            "E01-001",
            "comfyui",
            dry_run=False,
            pack=self.pack,
            options={"workflow": "missing-workflow.json"},
        )
        self.assertEqual(job["status"], "failed")
        self.assertIn("工作流不存在", job["error"])

    def test_comfyui_generation_uploads_submits_polls_and_downloads(self) -> None:
        submitted = {}

        class Handler(BaseHTTPRequestHandler):
            def _json(self, payload) -> None:
                data = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                if self.path.startswith("/upload/image"):
                    self._json({"name": "cinelock-ref.png", "subfolder": "cinelock", "type": "input"})
                elif self.path.startswith("/prompt"):
                    submitted.update(json.loads(body.decode("utf-8")))
                    self._json({"prompt_id": "p1"})
                else:
                    self._json({})

            def do_GET(self) -> None:
                if self.path.startswith("/history/p1"):
                    self._json(
                        {
                            "p1": {
                                "status": {"status_str": "success", "completed": True},
                                "outputs": {
                                    "7": {
                                        "gifs": [
                                            {
                                                "filename": "cinelock_E01-001.mp4",
                                                "subfolder": "",
                                                "type": "output",
                                            }
                                        ]
                                    }
                                },
                            }
                        }
                    )
                elif self.path.startswith("/view"):
                    data = b"not-a-real-mp4"
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                else:
                    self._json({})

            def log_message(self, *args) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        base_url = "http://127.0.0.1:%d" % server.server_address[1]
        job = execute(
            self.ctx,
            "E01-001",
            "comfyui",
            dry_run=False,
            pack=self.pack,
            options={"base_url": base_url, "timeout_sec": 20, "poll_interval_sec": 0.01},
        )

        self.assertEqual(job["status"], "succeeded", job.get("error"))
        self.assertEqual(job["adapter_meta"]["prompt_id"], "p1")
        self.assertEqual(job["adapter_meta"]["base_url"], base_url)
        videos = [item for item in job["outputs"] if item["kind"] == "video"]
        self.assertEqual(len(videos), 1)
        self.assertTrue((self.ctx.root / videos[0]["path"]).is_file())
        self.assertTrue(videos[0]["sha256"])
        self.assertTrue(any("不是可解析视频" in item for item in job["warnings"]))
        self.assertNotIn("__CINELOCK_", json.dumps(submitted.get("prompt") or {}))

    def test_official_api_without_credentials_fails_clearly(self) -> None:
        with patch.dict(os.environ, {"KLING_ACCESS_KEY": "", "KLING_SECRET_KEY": ""}):
            job = execute(self.ctx, "E01-001", "official_kling", dry_run=False, pack=self.pack)

        self.assertEqual(job["status"], "failed")
        self.assertIn("KLING_ACCESS_KEY", job["error"])
        self.assertEqual(job["outputs"], [])

    def test_stale_pack_is_rejected(self) -> None:
        from cinelock.util import read_json, write_json

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
