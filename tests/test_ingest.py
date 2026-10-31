from __future__ import annotations

import unittest
from unittest.mock import patch

from support import TempProjectCase
from cinelock.audit import audit_job
from cinelock.ingest import IngestError, import_external_artifact
from cinelock.util import resolve_within

PROBE_OK = {
    "ok": True,
    "available": True,
    "duration_sec": 5.0,
    "width": 1920,
    "height": 1080,
    "codec": "h264",
    "format": "mov,mp4,m4a,3gp,3g2,mj2",
    "size": 10,
}


class IngestTest(TempProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.pack = self.build()
        self.source = self.project_dir.parent / "external.mp4"
        self.source.write_bytes(b"fake-video-bytes")

    def import_job(self, **kwargs):
        options = {
            "model": "Kling 2.5",
            "note": "5 refs uploaded",
            "revision": str(self.pack["short_revision"]),
        }
        options.update(kwargs)
        with patch("cinelock.ingest.probe_video", return_value=dict(PROBE_OK)):
            return import_external_artifact(self.ctx, "E01-004", self.source, **options)

    def test_imported_artifact_is_recorded_and_audited(self) -> None:
        job = self.import_job()
        self.assertEqual(job["status"], "succeeded")
        self.assertEqual(job["adapter"], "handoff_import")
        self.assertEqual(job["external"]["model"], "Kling 2.5")
        self.assertNotIn("path", job["external"]["probe"])
        self.assertEqual(len(job["outputs"]), 1)
        output = job["outputs"][0]
        self.assertEqual(output["kind"], "video")
        self.assertEqual(output["origin"], "external")
        self.assertTrue(resolve_within(self.ctx.root, output["path"]).is_file())
        self.assertTrue(any("外部导入" in item for item in job["warnings"]))

        report = audit_job(self.ctx, job)
        self.assertEqual(report["status"], "pass", report["checks"])
        self.assertEqual(report["summary"]["pass"], 13)
        statuses = {item["id"]: item["status"] for item in report["checks"]}
        self.assertEqual(statuses["outputs"], "pass")
        self.assertEqual(statuses["recompile"], "pass")

    def test_revision_mismatch_is_rejected(self) -> None:
        with self.assertRaises(IngestError):
            self.import_job(revision="deadbeefcafe")

    def test_prompt_hash_mismatch_is_rejected(self) -> None:
        with self.assertRaises(IngestError):
            self.import_job(prompt_hash="deadbeefcafe")

    def test_non_video_extension_is_rejected(self) -> None:
        self.source = self.project_dir.parent / "external.txt"
        self.source.write_bytes(b"not a video")
        with self.assertRaises(IngestError):
            self.import_job()

    def test_tampered_imported_output_fails_audit(self) -> None:
        job = self.import_job()
        path = resolve_within(self.ctx.root, job["outputs"][0]["path"])
        with path.open("ab") as fh:
            fh.write(b"tampered")

        report = audit_job(self.ctx, job)
        self.assertEqual(report["status"], "fail")
        statuses = {item["id"]: item["status"] for item in report["checks"]}
        self.assertEqual(statuses["outputs"], "fail")
