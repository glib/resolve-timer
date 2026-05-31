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
        self.assertEqual(
            [(row.label, row.delta_seconds) for row in preview.comparison_rows()],
            [("S1", 0.0), ("S2", 0.0), ("LAP", 0.0)],
        )

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

    def test_add_course_rejects_duplicate_ids(self):
        service = TimerService(TimerDatabase([self.course], []))

        added = service.add_course("new_course", "New Course", 3)

        self.assertEqual(added.sector_count, 3)
        with self.assertRaises(ValueError):
            service.add_course("new_course", "Duplicate", 3)

    def test_cli_preview_from_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "timer_db.yaml"
            marker_path = tmp_path / "markers.csv"
            service = TimerService(TimerDatabase([self.course], []))
            service.commit_new_run(
                self.selected,
                run_id="run_reference",
                committed_at="2026-05-31T10:00:00Z",
            )
            service.save(db_path)
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
                        "--mode",
                        "best_lap",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertIn("S1: 0:01.000 (+0.000)", stdout.getvalue())
        self.assertIn("LAP: 0:03.000 (+0.000)", stdout.getvalue())
        self.assertIn("History: matched run_reference", stdout.getvalue())

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

    def test_cli_run_management_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "timer_db.yaml"
            service = TimerService(TimerDatabase([self.course], []))
            service.commit_new_run(
                self.selected,
                run_id="run_custom",
                committed_at="2026-05-31T10:00:00Z",
            )
            service.save(db_path)

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main(["--db", str(db_path), "runs", "--course", "course"])
            self.assertEqual(exit_code, 0)
            self.assertIn("run_custom\tcourse\t2026-05-31\tcommitted\tGX010123.MP4", stdout.getvalue())

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main(["--db", str(db_path), "ignore-run", "run_custom"])
            self.assertEqual(exit_code, 0)
            self.assertIn("Ignored run_custom", stdout.getvalue())
            self.assertTrue(TimerDatabase.load(db_path).runs[0].ignored)

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main(["--db", str(db_path), "unignore-run", "run_custom"])
            self.assertEqual(exit_code, 0)
            self.assertIn("Unignored run_custom", stdout.getvalue())
            self.assertFalse(TimerDatabase.load(db_path).runs[0].ignored)

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main(["--db", str(db_path), "delete-run", "run_custom"])
            self.assertEqual(exit_code, 0)
            self.assertIn("Deleted run_custom", stdout.getvalue())
            self.assertEqual(TimerDatabase.load(db_path).runs, [])

    def test_cli_update_run_from_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "timer_db.yaml"
            marker_path = tmp_path / "markers.csv"
            service = TimerService(TimerDatabase([self.course], []))
            service.commit_new_run(
                self.selected,
                run_id="run_custom",
                committed_at="2026-05-31T10:00:00Z",
            )
            service.save(db_path)
            with marker_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["name", "frame"])
                writer.writeheader()
                writer.writerows(
                    [
                        {"name": "Start", "frame": "0"},
                        {"name": "S1", "frame": "90"},
                        {"name": "Finish", "frame": "290"},
                    ]
                )

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main(
                    [
                        "--db",
                        str(db_path),
                        "update-run",
                        "--course",
                        "course",
                        "--markers",
                        str(marker_path),
                        "--filename",
                        "GX010123.MP4",
                        "--fps",
                        "100",
                        "run_custom",
                    ]
                )

            loaded = TimerDatabase.load(db_path)

        self.assertEqual(exit_code, 0)
        self.assertIn("Updated run_custom", stdout.getvalue())
        self.assertEqual(loaded.runs[0].marker_frames["S1"], 90)
        self.assertEqual(loaded.runs[0].marker_frames["Finish"], 290)

    def test_cli_validate_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "timer_db.yaml"
            TimerDatabase([self.course], []).save(db_path)

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main(["--db", str(db_path), "validate-db"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Database OK", stdout.getvalue())

    def test_cli_add_course(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main(
                    [
                        "--db",
                        str(db_path),
                        "add-course",
                        "--id",
                        "new_course",
                        "--name",
                        "New Course",
                        "--sectors",
                        "3",
                    ]
                )

            loaded = TimerDatabase.load(db_path)

        self.assertEqual(exit_code, 0)
        self.assertIn("Added course new_course", stdout.getvalue())
        self.assertEqual(loaded.courses[0], Course("new_course", "New Course", 3))


if __name__ == "__main__":
    unittest.main()
