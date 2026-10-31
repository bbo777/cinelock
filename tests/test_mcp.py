from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from support import CONFIG, ROOT, TempProjectCase
from cinelock.context_pack import load_pack, pack_is_current
from cinelock.mcp_server import McpServer


class McpServerTest(TempProjectCase):
    def call(self, name: str, arguments=None) -> dict:
        response = McpServer(self.ctx).handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
        self.assertIsNotNone(response)
        return response["result"]

    def payload(self, result: dict) -> dict:
        self.assertFalse(result.get("isError"), result)
        return json.loads(result["content"][0]["text"])

    def test_initialize_and_tool_catalog(self) -> None:
        server = McpServer(self.ctx)
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "clientInfo": {"name": "test", "version": "1"},
                },
            }
        )
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2025-06-18")
        self.assertEqual(result["serverInfo"]["name"], "cinelock")

        listed = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = listed["result"]["tools"]
        self.assertEqual(
            {tool["name"] for tool in tools},
            {
                "cinelock_status",
                "cinelock_validate",
                "cinelock_variant",
                "cinelock_audit",
                "cinelock_jobs",
                "cinelock_build",
                "cinelock_contact_sheet",
            },
        )
        for tool in tools:
            self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_status_and_variant_are_read_only(self) -> None:
        status = self.payload(self.call("cinelock_status"))
        self.assertEqual(status["context_revision"], self.ctx.context_revision())
        self.assertEqual(status["shot_count"], len(self.ctx.shots()))
        self.assertEqual(status["provider_count"], len(self.ctx.provider_order()))
        self.assertFalse(status["pack"]["exists"])

        variant = self.payload(
            self.call(
                "cinelock_variant",
                {"shot_id": "E01-001", "provider_id": "mock", "include_prompt": False},
            )
        )
        self.assertEqual(variant["context_revision"], self.ctx.context_revision())
        self.assertNotIn("prompt", variant)
        self.assertGreater(variant["reference_count"], 0)
        self.assertEqual(variant["references"][0]["role"], "identity")

        with_prompt = self.payload(
            self.call(
                "cinelock_variant",
                {"shot_id": "E01-001", "provider_id": "mock"},
            )
        )
        self.assertTrue(with_prompt["prompt"])

        self.assertFalse((self.project_dir / "context" / "context_pack.json").exists())

    def test_build_preview_does_not_write_shared_pack(self) -> None:
        preview = self.payload(self.call("cinelock_build"))
        self.assertFalse(preview["written"])
        self.assertIsNone(preview["pack_path"])
        self.assertFalse((self.project_dir / "context" / "context_pack.json").exists())

        written = self.payload(self.call("cinelock_build", {"write": True}))
        self.assertTrue(written["written"])
        self.assertTrue((self.project_dir / "context" / "context_pack.json").is_file())
        self.assertTrue(pack_is_current(self.context(), load_pack(self.context())))

        conflict = self.call("cinelock_build", {"write": True, "provider_id": "mock"})
        self.assertTrue(conflict["isError"])

    def test_tool_errors_are_returned_as_results(self) -> None:
        missing = self.call(
            "cinelock_variant", {"shot_id": "NOPE", "provider_id": "mock"}
        )
        self.assertTrue(missing["isError"])

        unknown = self.call("cinelock_nope")
        self.assertTrue(unknown["isError"])

        audit = self.call("cinelock_audit", {"job_id": "JOB_NOPE"})
        self.assertTrue(audit["isError"])

    def test_audit_and_jobs_tools_use_real_ledger(self) -> None:
        self.payload(self.call("cinelock_build", {"write": True}))
        base = [
            sys.executable,
            str(ROOT / "studio.py"),
            "--project-dir",
            str(self.project_dir),
            "--config-dir",
            str(CONFIG),
        ]
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            base + ["run", "--shot", "E01-001", "--provider", "mock", "--dry-run", "--json"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", errors="replace"))
        job_id = json.loads(proc.stdout.decode("utf-8"))[0]["job_id"]

        report = self.payload(self.call("cinelock_audit", {"job_id": job_id}))
        self.assertTrue(report["ok"])
        self.assertEqual(report["job_status"], "dry_run")
        self.assertTrue(report["dry_run"])
        self.assertEqual(len(report["checks"]), 13)

        jobs = self.payload(self.call("cinelock_jobs", {"limit": 5}))
        self.assertEqual(jobs["count"], 1)
        self.assertEqual(jobs["jobs"][0]["job_id"], job_id)

    def test_stdio_roundtrip(self) -> None:
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "cinelock_status", "arguments": {}},
            },
        ]
        payload = "\n".join(json.dumps(item, ensure_ascii=False) for item in requests) + "\n"
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "studio.py"),
                "--project-dir",
                str(self.project_dir),
                "--config-dir",
                str(CONFIG),
                "mcp",
            ],
            input=payload,
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0]["id"], 1)
        self.assertEqual(lines[1]["id"], 2)
        self.assertEqual(lines[2]["id"], 3)
        status = json.loads(lines[2]["result"]["content"][0]["text"])
        self.assertEqual(status["context_revision"], self.ctx.context_revision())


if __name__ == "__main__":
    unittest.main()
