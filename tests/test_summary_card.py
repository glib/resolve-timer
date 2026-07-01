import tempfile
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image

from resolve_timer.database import TimerDatabase
from resolve_timer.models import Course, RunRecord
from resolve_timer.service import TimerService
from resolve_timer.summary_card import CARD_SIZE, default_summary_card_path, render_course_summary_card


class SummaryCardTests(unittest.TestCase):
    def test_renderer_writes_4k_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            service = TimerService(
                TimerDatabase(
                    [Course("course", "A Very Long Course Name " * 8, 2)],
                    [
                        RunRecord(
                            id="run_001",
                            course_id="course",
                            date="2026-06-01",
                            filename="A Very Long Filename " * 12 + ".MP4",
                            source_fps=100.0,
                            marker_frames={"Start": 0, "S1": 100, "Finish": 300},
                        )
                    ],
                )
            )
            output = Path(tmp) / "summary.png"

            written = render_course_summary_card(service.course_summary_payload("course"), output)

            self.assertEqual(written, output)
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, CARD_SIZE)

    def test_renderer_handles_no_eligible_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            service = TimerService(TimerDatabase([Course("empty", "Empty Course", 2)], []))
            output = Path(tmp) / "empty.png"

            render_course_summary_card(service.course_summary_payload("empty"), output)

            with Image.open(output) as image:
                self.assertEqual(image.size, CARD_SIZE)

    def test_default_output_path_is_beside_database_and_sanitized(self):
        db_path = Path("project") / "timer_db.yaml"
        output = default_summary_card_path(
            db_path,
            "course / one",
            now=__import__("datetime").datetime(2026, 6, 16, 7, 30, 45),
        )

        self.assertEqual(
            output,
            Path("project") / "resolve_timer_summary_course_one_20260616_073045.png",
        )


if __name__ == "__main__":
    unittest.main()
