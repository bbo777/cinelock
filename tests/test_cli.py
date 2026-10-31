from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest

from support import CONFIG, ROOT, TempProjectCase


class CliTest(TempProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.base = [
            sys.executable,
            str(ROOT / "studio.py"),
            "--project-dir",
            str(self.project_dir),
            "--config-dir",
            str(CONFIG),
        ]
        self.env = dict(os.environ)
        self.env["PYTHONIOENCODING"] = "utf-8"

    def cli(self, *args: str):
        proc = subprocess.run(
            self.base + list(args),
            cwd=str(ROOT),
            env=self.env,
            capture_output=True,
            timeout=120,
        )
        stdout = proc.stdout.decode("utf-8", errors="replace")
        stderr = proc.stderr.decode("utf-8", errors="replace")
        return proc.returncode, stdout, stderr

    def test_validate_build_compile_run_and_jobs(self) -> None:
        code, stdout, stderr = self.cli("validate", "--json")
        self.assertEqual(code, 0, stderr)
        validation = json.loads(stdout)
        self.assertTrue(validation["ok"])

        code, stdout, stderr = self.cli("build", "--json")
        self.assertEqual(code, 0, stderr)
        build = json.loads(stdout)
        expected = len(self.ctx.shots()) * len(self.ctx.provider_order())
        self.assertEqual(build["stats"]["variant_count"], expected)
        revision = build["context_revision"]

        code, stdout, stderr = self.cli("status", "--json")
        self.assertEqual(code, 0, stderr)
        status = json.loads(stdout)
        self.assertTrue(status["pack"]["current"])
        self.assertEqual(status["revision"], revision)

        code, stdout, stderr = self.cli("compile", "--shot", "E01-001", "--provider", "mock", "--json")
        self.assertEqual(code, 0, stderr)
        variant = json.loads(stdout)
        self.assertEqual(variant["context_revision"], revision)
        self.assertEqual(variant["references"][0]["role"], "identity")

        code, stdout, stderr = self.cli(
            "run",
            "--shot",
            "E01-001",
            "--provider",
            "mock",
            "--dry-run",
            "--json",
        )
        self.assertEqual(code, 0, stderr)
        jobs = json.loads(stdout)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["status"], "dry_run")
        job_id = jobs[0]["job_id"]

        code, stdout, stderr = self.cli("jobs", "--json")
        self.assertEqual(code, 0, stderr)
        records = json.loads(stdout)
        self.assertEqual([record["job_id"] for record in records], [job_id])

        code, stdout, stderr = self.cli("job", "--id", job_id, "--json")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(json.loads(stdout)["context_revision"], revision)

        code, stdout, stderr = self.cli("audit", "--id", job_id, "--json")
        self.assertEqual(code, 0, stderr)
        audit = json.loads(stdout)
        self.assertEqual(audit["status"], "pass")
        self.assertEqual(audit["summary"]["fail"], 0)

    def test_compile_unknown_shot_returns_an_error(self) -> None:
        self.assertEqual(self.cli("build", "--json")[0], 0)
        code, _, stderr = self.cli("compile", "--shot", "E01-404", "--json")
        self.assertEqual(code, 2)
        self.assertIn("E01-404", stderr)

    def test_refresh_hashes_repairs_recorded_drift(self) -> None:
        bank_path = self.project_dir / "reference_bank.json"
        bank = json.loads(bank_path.read_text(encoding="utf-8"))
        asset = bank["assets"][0]
        original = asset["sha256"]
        asset["sha256"] = "0" * 64
        bank_path.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding="utf-8")

        code, _, _ = self.cli("validate", "--json")
        self.assertEqual(code, 2)

        code, stdout, stderr = self.cli("refresh-hashes", "--json")
        self.assertEqual(code, 0, stderr)
        report = json.loads(stdout)
        self.assertEqual(report["updated"][0]["asset_id"], asset["asset_id"])
        self.assertEqual(report["updated"][0]["old"], "0" * 64)
        self.assertEqual(report["updated"][0]["new"], original)
        self.assertEqual(report["short_revision"], self.ctx.context_revision()[:12])

        refreshed = json.loads(bank_path.read_text(encoding="utf-8"))
        self.assertEqual(refreshed["assets"][0]["sha256"], original)
        self.assertEqual(self.cli("validate", "--json")[0], 0)

    def test_refresh_hashes_refuses_when_an_asset_is_missing(self) -> None:
        bank_path = self.project_dir / "reference_bank.json"
        bank = json.loads(bank_path.read_text(encoding="utf-8"))
        asset = bank["assets"][0]
        before = bank_path.read_bytes()
        (self.project_dir / asset["path"]).unlink()

        code, stdout, _ = self.cli("refresh-hashes", "--json")
        self.assertEqual(code, 2)
        self.assertIn("未写入任何变化", json.loads(stdout)["error"])
        self.assertEqual(bank_path.read_bytes(), before)

    def test_partial_build_does_not_overwrite_the_shared_pack(self) -> None:
        self.assertEqual(self.cli("build", "--json")[0], 0)
        pack_path = self.project_dir / "context" / "context_pack.json"
        before = pack_path.read_bytes()

        code, stdout, stderr = self.cli("build", "--provider", "mock", "--json")
        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["partial"])
        self.assertFalse(payload["written"])
        self.assertIsNone(payload["pack_path"])
        self.assertEqual(payload["stats"]["provider_count"], 1)
        self.assertEqual(pack_path.read_bytes(), before)

        shared = json.loads(before.decode("utf-8"))
        providers = {variant["provider_id"] for variant in shared["variants"]}
        self.assertIn("handoff", providers)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 ffmpeg 与 ffprobe")
    def test_contact_sheet_from_mock_video(self) -> None:
        self.assertEqual(self.cli("build", "--json")[0], 0)
        code, stdout, stderr = self.cli("run", "--shot", "E01-001", "--provider", "mock", "--json")
        self.assertEqual(code, 0, stderr)
        job = json.loads(stdout)[0]
        self.assertEqual(job["status"], "succeeded", job.get("error"))

        code, stdout, stderr = self.cli("contact-sheet", "--job", job["job_id"], "--json")
        self.assertEqual(code, 0, stderr)
        sheet = json.loads(stdout)
        self.assertEqual((sheet["width"], sheet["height"]), (1920, 1080))
        self.assertEqual((sheet["columns"], sheet["rows"]), (3, 3))
        self.assertEqual(len(sheet["timestamps"]), 9)
        self.assertTrue((self.project_dir / sheet["output"]).is_file())

        code, _, stderr = self.cli("contact-sheet", "--job", "JOB_MISSING", "--json")
        self.assertEqual(code, 2)
        self.assertIn("不存在", stderr)


if __name__ == "__main__":
    unittest.main()
