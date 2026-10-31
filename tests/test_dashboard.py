from __future__ import annotations

import io
import json
import shutil
import threading
import unittest
import urllib.error
import urllib.request
from urllib.parse import quote

from support import CONFIG, TempProjectCase
from nineflow.dashboard import DashboardServer


class DashboardTest(TempProjectCase):
    def setUp(self) -> None:
        super().setUp()
        self.pack = self.build()
        self.server = DashboardServer(("127.0.0.1", 0), self.project_dir, CONFIG)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]
        self.addCleanup(self._stop_server)

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def request(self, path: str, *, method: str = "GET", headers=None, payload=None):
        data = None
        request_headers = dict(headers or {})
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(self.base + path, data=data, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def test_status_and_variant_api(self) -> None:
        status, headers, body = self.request("/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("default-src 'self'", headers.get("Content-Security-Policy", ""))
        payload = json.loads(body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["status"]["revision"], self.pack["context_revision"])

        status, _, body = self.request("/api/variant?shot_id=E01-001&provider_id=mock")
        self.assertEqual(status, 200)
        variant = json.loads(body.decode("utf-8"))["variant"]
        self.assertEqual(variant["context_revision"], self.pack["context_revision"])
        self.assertEqual(variant["references"][0]["role"], "identity")

    def test_post_requires_csrf_header(self) -> None:
        status, _, _ = self.request("/api/build", method="POST", payload={})
        self.assertEqual(status, 403)

        status, _, body = self.request(
            "/api/build",
            method="POST",
            headers={"X-NineFlow": "studio"},
            payload={},
        )
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["revision"], self.pack["context_revision"])

    def test_run_dry_run_through_the_api(self) -> None:
        status, _, body = self.request(
            "/api/run",
            method="POST",
            headers={"X-NineFlow": "studio"},
            payload={"shot_id": "E01-001", "provider_id": "mock", "dry_run": True},
        )
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["job"]["status"], "dry_run")
        self.assertEqual(payload["job"]["context_revision"], self.pack["context_revision"])

        status, _, body = self.request("/api/jobs")
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body.decode("utf-8"))["jobs"]), 1)

    def test_audit_api_verifies_a_job(self) -> None:
        status, _, body = self.request(
            "/api/run",
            method="POST",
            headers={"X-NineFlow": "studio"},
            payload={"shot_id": "E01-001", "provider_id": "mock", "dry_run": True},
        )
        self.assertEqual(status, 200)
        job_id = json.loads(body.decode("utf-8"))["job"]["job_id"]

        status, _, body = self.request("/api/audit?id=" + job_id)
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertTrue(payload["audit"]["ok"])
        self.assertEqual(payload["audit"]["status"], "pass")
        check_ids = {item["id"] for item in payload["audit"]["checks"]}
        self.assertIn("revision_lock", check_ids)
        self.assertIn("continuity_replay", check_ids)
        self.assertIn("outputs", check_ids)

        status, _, _ = self.request("/api/audit")
        self.assertEqual(status, 400)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 ffmpeg 与 ffprobe")
    def test_contact_sheet_api(self) -> None:
        status, _, body = self.request(
            "/api/run",
            method="POST",
            headers={"X-NineFlow": "studio"},
            payload={"shot_id": "E01-001", "provider_id": "mock"},
        )
        self.assertEqual(status, 200)
        job = json.loads(body.decode("utf-8"))["job"]
        self.assertEqual(job["status"], "succeeded", job.get("error"))

        status, _, body = self.request(
            "/api/contact-sheet",
            method="POST",
            headers={"X-NineFlow": "studio"},
            payload={"id": job["job_id"]},
        )
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual((payload["columns"], payload["rows"]), (3, 3))
        self.assertEqual(len(payload["timestamps"]), 9)
        self.assertEqual(payload["path"], "outputs/%s.contact_sheet.png" % job["job_id"])

        status, headers, body = self.request("/files/" + payload["path"])
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("Content-Type"), "image/png")
        from PIL import Image

        with Image.open(io.BytesIO(body)) as image:
            self.assertEqual(image.size, (1920, 1080))

    def test_contact_sheet_requires_a_local_video(self) -> None:
        status, _, body = self.request(
            "/api/run",
            method="POST",
            headers={"X-NineFlow": "studio"},
            payload={"shot_id": "E01-001", "provider_id": "mock", "dry_run": True},
        )
        self.assertEqual(status, 200)
        job_id = json.loads(body.decode("utf-8"))["job"]["job_id"]

        status, _, body = self.request(
            "/api/contact-sheet",
            method="POST",
            headers={"X-NineFlow": "studio"},
            payload={"id": job_id},
        )
        self.assertEqual(status, 400)
        self.assertIn("video", json.loads(body.decode("utf-8"))["error"])

    def test_cross_origin_and_host_spoofing_are_rejected(self) -> None:
        status, _, _ = self.request(
            "/api/build",
            method="POST",
            headers={"X-NineFlow": "studio", "Origin": "http://evil.example"},
            payload={},
        )
        self.assertEqual(status, 403)

        status, _, _ = self.request("/api/status", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_file_endpoint_only_serves_allowlisted_roots_with_range(self) -> None:
        png = "/files/refs/characters/linye/linye_front_v01.png"
        status, headers, body = self.request(png, headers={"Range": "bytes=0-9"})
        self.assertEqual(status, 206)
        self.assertEqual(len(body), 10)
        self.assertTrue(headers.get("Content-Range", "").startswith("bytes 0-9/"))
        self.assertEqual(headers.get("Content-Type"), "image/png")

        status, _, _ = self.request("/files/project.json")
        self.assertEqual(status, 403)

        traversal = "/files/refs/" + quote("../../project.json")
        status, _, _ = self.request(traversal)
        self.assertNotEqual(status, 200)

    def test_unknown_api_is_404(self) -> None:
        status, _, body = self.request("/api/nope")
        self.assertEqual(status, 404)
        self.assertFalse(json.loads(body.decode("utf-8"))["ok"])


if __name__ == "__main__":
    unittest.main()
