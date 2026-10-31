from __future__ import annotations

import copy
import unittest

from support import TempProjectCase
from nineflow.audit import audit_job
from nineflow.dispatch import execute
from nineflow.util import resolve_within


class AuditTest(TempProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.pack = self.build()

    def statuses(self, report):
        return {item["id"]: item["status"] for item in report["checks"]}

    def test_fresh_dry_run_job_passes_every_check(self) -> None:
        job = execute(self.ctx, "E01-001", "mock", dry_run=True, pack=self.pack)

        self.assertIn("engine", job["provenance"]["source_hashes"])
        self.assertEqual(job["provenance"]["source_hashes_sha256"], job["context_revision"])
        report = audit_job(self.ctx, job)

        self.assertEqual(report["status"], "pass", report["checks"])
        self.assertFalse(report["legacy"])
        self.assertEqual(report["scope"], "artifact_integrity")
        self.assertEqual(report["artifact_status"], "pass")
        self.assertEqual(report["job_status"], "dry_run")
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["verdict"]["overall"], "pass")
        self.assertEqual(report["verdict"]["current_context"], "current")
        statuses = self.statuses(report)
        self.assertEqual(statuses["revision_lock"], "pass")
        self.assertEqual(statuses["snapshot_integrity"], "pass")
        self.assertEqual(statuses["continuity_replay"], "pass")
        self.assertEqual(statuses["recompile"], "pass")
        self.assertEqual(statuses["prompt_integrity"], "pass")
        self.assertEqual(statuses["references"], "pass")
        self.assertEqual(statuses["continuity_coverage"], "pass")
        self.assertEqual(statuses["reference_projection"], "pass")
        self.assertEqual(statuses["outputs"], "skip")

    def test_handoff_artifacts_are_verified(self) -> None:
        job = execute(self.ctx, "E01-001", "handoff", dry_run=False, pack=self.pack)
        self.assertEqual(job["status"], "succeeded", job.get("error"))

        report = audit_job(self.ctx, job)
        self.assertEqual(report["status"], "pass", report["checks"])
        self.assertEqual(self.statuses(report)["outputs"], "pass")

    def test_tampered_snapshot_fails(self) -> None:
        job = execute(self.ctx, "E01-001", "mock", dry_run=True, pack=self.pack)
        tampered = copy.deepcopy(job)
        tampered["provenance"]["context_snapshot"]["characters"]["CH_LINYE_01"]["wardrobe_state"] = "home_injured"

        report = audit_job(self.ctx, tampered)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(self.statuses(report)["snapshot_integrity"], "fail")

    def test_tampered_source_hashes_fail_the_revision_lock(self) -> None:
        job = execute(self.ctx, "E01-001", "mock", dry_run=True, pack=self.pack)
        tampered = copy.deepcopy(job)
        tampered["provenance"]["source_hashes"]["timeline"] = "0" * 64

        report = audit_job(self.ctx, tampered)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(self.statuses(report)["revision_lock"], "fail")

    def test_tampered_output_fails(self) -> None:
        job = execute(self.ctx, "E01-001", "handoff", dry_run=False, pack=self.pack)
        prompt_output = next(item for item in job["outputs"] if item["kind"] == "prompt")
        path = resolve_within(self.ctx.root, prompt_output["path"])
        with path.open("ab") as fh:
            fh.write(b"\nTAMPERED\n")

        report = audit_job(self.ctx, job)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(self.statuses(report)["outputs"], "fail")

    def test_tampered_reference_fails(self) -> None:
        job = execute(self.ctx, "E01-001", "mock", dry_run=True, pack=self.pack)
        reference = job["references"][0]
        path = resolve_within(self.ctx.root, reference["path"])
        with path.open("ab") as fh:
            fh.write(b"\0")

        report = audit_job(self.ctx, job)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(self.statuses(report)["references"], "fail")

    def test_historical_revision_warns_but_does_not_fail(self) -> None:
        job = execute(self.ctx, "E01-001", "mock", dry_run=True, pack=self.pack)

        project = self.context().project
        project["title"] = project["title"] + " · audit drift"
        from nineflow.util import write_json

        write_json(self.project_dir / "project.json", project)
        ctx = self.context()

        report = audit_job(ctx, job)
        self.assertEqual(report["status"], "warn")
        self.assertEqual(report["verdict"]["current_context"], "historical")
        self.assertEqual(report["verdict"]["overall"], "warn")
        statuses = self.statuses(report)
        self.assertEqual(statuses["current_revision"], "warn")
        self.assertEqual(statuses["recompile"], "skip")
        self.assertEqual(statuses["revision_lock"], "pass")

    def test_job_status_is_reported_separately_from_artifact_integrity(self) -> None:
        job = execute(self.ctx, "E01-001", "mock", dry_run=True, pack=self.pack)
        tampered = copy.deepcopy(job)
        tampered["status"] = "failed"
        tampered["error"] = "模拟厂商失败"

        report = audit_job(self.ctx, tampered)
        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["ok"])
        self.assertEqual(report["job_status"], "failed")
        self.assertFalse(report["verdict"]["job_ok"])
        self.assertEqual(report["verdict"]["overall"], "warn")

    def test_legacy_job_is_warned_not_crashed(self) -> None:
        job = execute(self.ctx, "E01-001", "mock", dry_run=True, pack=self.pack)
        legacy = copy.deepcopy(job)
        legacy.pop("provenance")
        legacy["schema_version"] = "1.0"

        report = audit_job(self.ctx, legacy)
        self.assertEqual(report["status"], "warn")
        self.assertTrue(report["legacy"])
        statuses = self.statuses(report)
        self.assertEqual(statuses["provenance"], "warn")
        self.assertEqual(statuses["revision_lock"], "skip")
        self.assertEqual(statuses["snapshot_integrity"], "skip")
        self.assertEqual(statuses["prompt_integrity"], "pass")


if __name__ == "__main__":
    unittest.main()
