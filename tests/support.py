from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROJECT = ROOT / "examples" / "nine-inning-bottom"
CONFIG = ROOT / "config"

from cinelock.context import ProjectContext, load_context  # noqa: E402
from cinelock.context_pack import build_pack  # noqa: E402


class TempProjectCase(unittest.TestCase):
    """Each test gets a throwaway copy of the demo project."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinelock-test-")
        self.addCleanup(self._tmp.cleanup)
        self.project_dir = Path(self._tmp.name) / "project"
        shutil.copytree(
            PROJECT,
            self.project_dir,
            ignore=shutil.ignore_patterns("context", "jobs", "outputs", "exports", "__pycache__"),
        )
        self.ctx = self.context()

    def context(self) -> ProjectContext:
        return load_context(self.project_dir, CONFIG)

    def build(self) -> dict:
        return build_pack(self.ctx)
