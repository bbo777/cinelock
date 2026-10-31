from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import ROOT  # noqa: F401

from cinelock.media import MediaError, create_contact_sheet, probe_video


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "需要 ffmpeg 与 ffprobe")
class MediaTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinelock-media-")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.video = self.root / "sample.mp4"
        subprocess.run(
            [
                shutil.which("ffmpeg"),
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=640x360:rate=12:duration=3",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(self.video),
            ],
            check=True,
            timeout=120,
        )

    def test_probe_reads_duration_and_resolution(self) -> None:
        probe = probe_video(self.video)
        self.assertTrue(probe["ok"], probe)
        self.assertTrue(probe["available"])
        self.assertAlmostEqual(probe["duration_sec"], 3.0, delta=0.2)
        self.assertEqual((probe["width"], probe["height"]), (640, 360))
        self.assertEqual(probe["codec"], "h264")
        self.assertGreater(probe["size"], 0)

    def test_contact_sheet_is_a_3x3_grid(self) -> None:
        output = self.root / "sheet.png"
        sheet = create_contact_sheet(self.video, output)
        self.assertTrue(output.is_file())
        self.assertEqual((sheet["width"], sheet["height"]), (1920, 1080))
        self.assertEqual((sheet["columns"], sheet["rows"]), (3, 3))
        self.assertEqual(len(sheet["timestamps"]), 9)
        self.assertEqual(sheet["timestamps"], sorted(sheet["timestamps"]))
        self.assertTrue(all(0 < value < 3 for value in sheet["timestamps"]))
        self.assertEqual(sheet["probe"]["width"], 640)

    def test_invalid_video_raises_media_error(self) -> None:
        broken = self.root / "broken.mp4"
        broken.write_bytes(b"not a video")
        probe = probe_video(broken)
        self.assertFalse(probe["ok"])
        self.assertTrue(probe["available"])
        with self.assertRaises(MediaError):
            create_contact_sheet(broken, self.root / "broken.png")

    def test_invalid_grid_is_rejected(self) -> None:
        with self.assertRaises(MediaError):
            create_contact_sheet(self.video, self.root / "bad.png", columns=0, rows=3)


if __name__ == "__main__":
    unittest.main()
