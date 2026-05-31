import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resolve_timer.cli import main
from resolve_timer.database import TimerDatabase
from resolve_timer.validation import validate_database


ROOT = Path(__file__).resolve().parents[1]


class ExampleFixtureTests(unittest.TestCase):
    def test_example_database_validates(self):
        database = TimerDatabase.load(ROOT / "examples" / "timer_db.yaml")

        self.assertEqual(validate_database(database), [])

    def test_example_markers_preview_against_example_database(self):
        stdout = StringIO()
        with patch("sys.stdout", stdout):
            exit_code = main(
                [
                    "--db",
                    str(ROOT / "examples" / "timer_db.yaml"),
                    "preview",
                    "--course",
                    "lower_whistler_a_line",
                    "--markers",
                    str(ROOT / "examples" / "markers.csv"),
                    "--filename",
                    "GX010123.MP4",
                    "--fps",
                    "59.94",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Course: Lower Whistler A-Line", stdout.getvalue())
        self.assertIn("History: matched run_2026_05_31_001", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
