import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import resolve_timer
from resolve_timer.models import Course


class PackageImportTests(unittest.TestCase):
    def test_top_level_exports_pure_core_helpers(self):
        self.assertIs(resolve_timer.Course, Course)
        self.assertTrue(hasattr(resolve_timer, "parse_marker_snapshot"))
        self.assertTrue(hasattr(resolve_timer, "compute_timing"))
        self.assertFalse(hasattr(resolve_timer, "TimerService"))


if __name__ == "__main__":
    unittest.main()
