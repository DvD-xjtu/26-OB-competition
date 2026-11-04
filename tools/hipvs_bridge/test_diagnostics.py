#!/usr/bin/env python3
"""CPU tests of diagnostic collection; these do not exercise GPU code."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import run_diagnostics as diagnostic


class CollectionTest(unittest.TestCase):
    def test_real_cli_writes_report_and_preserves_absence(self):
        with tempfile.TemporaryDirectory() as name:
            result = subprocess.run([sys.executable, diagnostic.__file__,
                                     "--collect-only", name], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((Path(name) / "report.json").read_text())
            self.assertEqual(report["status"], "collected")
            self.assertEqual(report["logs"]["diagnostic_lines"], [])
            self.assertIn("do not establish", report["logs"]["interpretation"])

    def test_failure_messages_are_collected_and_output_is_bounded(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "build.log").write_text("normal output\nCMake Error: dependency absent\n")
            (root / "seekdb.stdout.log").write_text(
                "[AMD_DIAG] event=build_ok n=10000 dim=128\n" * 200 +
                "[AMD_DIAG] event=search_failed rc=15\n")
            report = diagnostic.collect_logs(root, limit=10)
            self.assertEqual(len(report["diagnostic_lines"]), 10)
            self.assertIn("search_failed", report["diagnostic_lines"][-1]["line"])
            self.assertIn("build.log", report["files_found"])

    def test_does_not_collect_an_external_symlink_or_unrelated_file(self):
        with tempfile.TemporaryDirectory() as name, tempfile.TemporaryDirectory() as other:
            outside = Path(other) / "private"
            outside.write_text("[AMD_DIAG] unrelated secret")
            (Path(name) / "seekdb.stdout.log").symlink_to(outside)
            (Path(name) / "credentials").write_text("not a supported log")
            self.assertEqual(diagnostic.collect_logs(name)["files_found"], [])


if __name__ == "__main__":
    unittest.main()
