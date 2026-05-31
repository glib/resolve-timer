import csv
import json
import tempfile
import sys
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resolve_timer.cli import main
from resolve_timer.database import TimerDatabase
from resolve_timer.models import Course, RawMarker
from resolve_timer.service import SelectedRunInput, TimerService


class ServiceCliTests(unittest.TestCase):
    def setUp(self):
        self.course = Course("course", "Course", 2)
        self.markers = (
            RawMarker("Start", 0),
            RawMarker("S1", 100),
            RawMarker("Finish", 300),
        )
        self.selected = SelectedRunInput(
            course_id="course",
            filename="GX010123.MP4",
            source_fps=100.0,
            markers=self.markers,
            clip_id="clip-1",
            run_date="2026-05-31",
        )

    def test_commit_preview_update_ignore_delete_workflow(self):
        service = TimerService(TimerDatabase([self.course], []))

        preview = service.preview(self.selected)
        self.assertIsNone(preview.matching_run)
        self.assertEqual(preview.best_lap_references.sector_seconds, (None, None))

        committed = service.commit_new_run(
            self.selected,
            run_id="run_custom",
            committed_at="2026-05-31T10:00:00Z",
        )
        self.assertEqual(committed.id, "run_custom")

        preview = service.preview(self.selected)
        self.assertEqual(preview.matching_run.id, "run_custom")
        self.assertFalse(preview.has_marker_changes)
        self.assertEqual(preview.best_lap_references.lap_seconds, 3.0)

        payload = service.overlay_payload(self.selected)
        self.assertEqual(payload.run_id, "run_custom")
        self.assertEqual(payload.comparison_mode, "best_lap")
        self.assertEqual(payload.start_frame, 0)
        self.assertEqual(payload.finish_frame, 300)
        self.assertEqual(payload.sector_reference_seconds, (1.0, 2.0))

        changed = SelectedRunInput(
            course_id="course",
            filename="GX010123.MP4",
            source_fps=100.0,
            markers=(
                RawMarker("Start", 0),
                RawMarker("S1", 90),
                RawMarker("Finish", 290),
            ),
            clip_id="clip-1",
            run_date="2026-05-31",
        )
        changed_preview = service.preview(changed)
        self.assertTrue(changed_preview.has_marker_changes)

        updated = service.update_existing_run(
            changed,
            "run_custom",
            committed_at="2026-05-31T11:00:00Z",
        )
        self.assertEqual(updated.marker_frames["Finish"], 290)
        self.assertFalse(updated.ignored)

        ignored = service.set_ignored("run_custom", True)
        self.assertTrue(ignored.ignored)

        service.delete_run("run_custom")
        self.assertEqual(service.database.runs, [])

    def test_commit_generates_incrementing_run_id(self):
        service = TimerService(TimerDatabase([self.course], []))

        first = service.commit_new_run(self.selected, committed_at="2026-05-31T10:00:00Z")
        second = service.commit_new_run(self.selected, committed_at="2026-05-31T11:00:00Z")

        self.assertEqual(first.id, "run_2026_05_31_001")
        self.assertEqual(second.id, "run_2026_05_31_002")

    def test_cli_preview_from_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "timer_db.yaml"
            marker_path = tmp_path / "markers.csv"
            TimerDatabase([self.course], []).save(db_path)
            with marker_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["name", "frame"])
                writer.writeheader()
                writer.writerows(
                    [
                        {"name": "Start", "frame": "0"},
                        {"name": "S1", "frame": "100"},
                        {"name": "Finish", "frame": "300"},
                    ]
                )

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main(
                    [
                        "--db",
                        str(db_path),
                        "preview",
                        "--course",
                        "course",
                        "--markers",
                        str(marker_path),
                        "--filename",
                        "GX010123.MP4",
                        "--fps",
                        "100",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("Lap: 0:03.000", stdout.getvalue())
        self.assertIn("History: no committed run", stdout.getvalue())

    def test_cli_overlay_payload_from_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "timer_db.yaml"
            marker_path = tmp_path / "markers.csv"
            TimerDatabase([self.course], []).save(db_path)
            with marker_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["name", "frame"])
                writer.writeheader()
                writer.writerows(
                    [
                        {"name": "Start", "frame": "0"},
                        {"name": "S1", "frame": "100"},
                        {"name": "Finish", "frame": "300"},
                    ]
                )

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main(
                    [
                        "--db",
                        str(db_path),
                        "overlay-payload",
                        "--course",
                        "course",
                        "--markers",
                        str(marker_path),
                        "--filename",
                        "GX010123.MP4",
                        "--fps",
                        "100",
                        "--mode",
                        "optimal",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["course_id"], "course")
        self.assertEqual(payload["comparison_mode"], "optimal")
        self.assertEqual(payload["marker_frames"]["Finish"], 300)
        self.assertEqual(payload["sector_reference_seconds"], [None, None])


if __name__ == "__main__":
    unittest.main()
