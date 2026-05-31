import tempfile
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resolve_timer.database import TimerDatabase
from resolve_timer.models import Course, RawMarker
from resolve_timer.service import SelectedRunInput
from resolve_timer.ui import preview_selected_clip


class FakeAdapter:
    def selected_run_input(self, course_id):
        return SelectedRunInput(
            course_id=course_id,
            filename="GX010123.MP4",
            source_fps=100.0,
            markers=(
                RawMarker("Start", 0),
                RawMarker("S1", 100),
                RawMarker("Finish", 300),
            ),
            clip_id="clip-1",
        )


class UiTests(unittest.TestCase):
    def test_preview_selected_clip_uses_adapter_and_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase([Course("course", "Course", 2)], []).save(db_path)

            preview = preview_selected_clip(
                database_path=db_path,
                course_id="course",
                adapter=FakeAdapter(),
            )

        self.assertEqual(preview.course.id, "course")
        self.assertEqual(preview.timing.lap_seconds, 3.0)


if __name__ == "__main__":
    unittest.main()
