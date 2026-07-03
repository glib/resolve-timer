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
from resolve_timer.matching import clip_fingerprint
from resolve_timer.models import Course, RawMarker
from resolve_timer.service import SelectedRunInput, TimelineRunCandidate, TimerService


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

    def test_commit_new_run_rejects_duplicate_explicit_run_id(self):
        service = TimerService(TimerDatabase([self.course], []))
        service.commit_new_run(
            self.selected,
            run_id="run_custom",
            committed_at="2026-05-31T10:00:00Z",
        )

        with self.assertRaises(ValueError) as raised:
            service.commit_new_run(
                self.selected,
                run_id="run_custom",
                committed_at="2026-05-31T11:00:00Z",
            )

        self.assertIn("run already exists: run_custom", str(raised.exception))

    def test_update_existing_run_preserves_ignored_state(self):
        service = TimerService(TimerDatabase([self.course], []))
        service.commit_new_run(
            self.selected,
            run_id="run_custom",
            committed_at="2026-05-31T10:00:00Z",
        )
        service.set_ignored("run_custom", True)

        updated = service.update_existing_run(
            self.selected,
            "run_custom",
            committed_at="2026-05-31T11:00:00Z",
        )

        self.assertTrue(updated.ignored)

    def test_update_existing_run_rejects_course_mismatch(self):
        other_course = Course("other", "Other", 2)
        service = TimerService(TimerDatabase([self.course, other_course], []))
        service.commit_new_run(
            self.selected,
            run_id="run_custom",
            committed_at="2026-05-31T10:00:00Z",
        )
        selected_for_other_course = SelectedRunInput(
            course_id="other",
            filename=self.selected.filename,
            source_fps=self.selected.source_fps,
            markers=self.selected.markers,
            clip_id=self.selected.clip_id,
            run_date=self.selected.run_date,
        )

        with self.assertRaises(ValueError) as raised:
            service.update_existing_run(selected_for_other_course, "run_custom")

        self.assertIn("belongs to course course, not other", str(raised.exception))

    def test_preview_summary_delta_shows_only_equal_or_faster_current_run(self):
        service = TimerService(TimerDatabase([self.course], []))
        baseline = SelectedRunInput(
            course_id="course",
            filename="Baseline.MP4",
            source_fps=100.0,
            markers=(
                RawMarker("Start", 0),
                RawMarker("S1", 100),
                RawMarker("Finish", 320),
            ),
            clip_id="baseline",
            run_date="2026-05-31",
        )
        service.commit_new_run(
            baseline,
            run_id="baseline",
            committed_at="2026-05-31T10:00:00Z",
        )
        service.commit_new_run(
            self.selected,
            run_id="current",
            committed_at="2026-05-31T11:00:00Z",
        )

        faster = service.preview(self.selected)
        self.assertAlmostEqual(faster.best_lap_delta, -0.2)
        self.assertAlmostEqual(faster.optimal_lap_delta, -0.2)

        equal_service = TimerService(TimerDatabase([self.course], []))
        equal_service.commit_new_run(
            self.selected,
            run_id="equal_baseline",
            committed_at="2026-05-31T10:00:00Z",
        )
        equal = equal_service.preview(
            SelectedRunInput(
                course_id="course",
                filename="Equal.MP4",
                source_fps=100.0,
                markers=self.markers,
                clip_id="equal",
                run_date="2026-05-31",
            )
        )
        self.assertEqual(equal.best_lap_delta, 0.0)

        slower = service.preview(baseline)
        self.assertIsNone(slower.best_lap_delta)
        self.assertIsNone(slower.optimal_lap_delta)

    def test_timeline_batch_compares_against_prior_batch_runs(self):
        service = TimerService(TimerDatabase([self.course], []))
        service.commit_new_run(
            SelectedRunInput(
                course_id="course",
                filename="Baseline.MP4",
                source_fps=100.0,
                markers=(
                    RawMarker("Start", 0),
                    RawMarker("S1", 100),
                    RawMarker("Finish", 320),
                ),
                clip_id="baseline",
                run_date="2026-05-31",
            ),
            run_id="baseline",
            committed_at="2026-05-31T10:00:00Z",
        )

        result = service.commit_or_update_timeline_runs(
            [
                TimelineRunCandidate(
                    "First.MP4",
                    SelectedRunInput(
                        course_id="course",
                        filename="First.MP4",
                        source_fps=100.0,
                        markers=(
                            RawMarker("Start", 0),
                            RawMarker("S1", 100),
                            RawMarker("Finish", 300),
                        ),
                        clip_id="first",
                        run_date="2026-05-31",
                    ),
                ),
                TimelineRunCandidate(
                    "Second.MP4",
                    SelectedRunInput(
                        course_id="course",
                        filename="Second.MP4",
                        source_fps=100.0,
                        markers=(
                            RawMarker("Start", 0),
                            RawMarker("S1", 95),
                            RawMarker("Finish", 290),
                        ),
                        clip_id="second",
                        run_date="2026-05-31",
                    ),
                ),
                TimelineRunCandidate(
                    "Third.MP4",
                    SelectedRunInput(
                        course_id="course",
                        filename="Third.MP4",
                        source_fps=100.0,
                        markers=(
                            RawMarker("Start", 0),
                            RawMarker("S1", 90),
                            RawMarker("Finish", 280),
                        ),
                        clip_id="third",
                        run_date="2026-05-31",
                    ),
                ),
            ]
        )

        self.assertEqual(result.committed, 3)
        self.assertEqual(result.updated, 0)
        self.assertEqual(result.unchanged, 0)
        self.assertEqual(result.skipped, 0)
        self.assertEqual(result.failed, 0)
        self.assertEqual(
            [item.preview.best_lap_references.lap_seconds for item in result.items],
            [3.2, 3.0, 2.9],
        )
        self.assertEqual(
            [round(item.preview.best_lap_delta, 3) for item in result.items],
            [-0.2, -0.1, -0.1],
        )
        self.assertEqual([run.filename for run in service.database.runs], [
            "Baseline.MP4",
            "First.MP4",
            "Second.MP4",
            "Third.MP4",
        ])
        self.assertFalse(any(run.ignored for run in service.database.runs[1:]))

    def test_timeline_batch_existing_runs_do_not_compare_against_later_timeline_runs(self):
        service = TimerService(TimerDatabase([self.course], []))
        baseline = SelectedRunInput(
            course_id="course",
            filename="Baseline.MP4",
            source_fps=100.0,
            markers=(
                RawMarker("Start", 0),
                RawMarker("S1", 100),
                RawMarker("Finish", 320),
            ),
            clip_id="baseline",
            run_date="2026-05-31",
        )
        first = SelectedRunInput(
            course_id="course",
            filename="First.MP4",
            source_fps=100.0,
            markers=(
                RawMarker("Start", 0),
                RawMarker("S1", 100),
                RawMarker("Finish", 300),
            ),
            clip_id="first",
            run_date="2026-05-31",
        )
        second = SelectedRunInput(
            course_id="course",
            filename="Second.MP4",
            source_fps=100.0,
            markers=(
                RawMarker("Start", 0),
                RawMarker("S1", 95),
                RawMarker("Finish", 290),
            ),
            clip_id="second",
            run_date="2026-05-31",
        )
        third = SelectedRunInput(
            course_id="course",
            filename="Third.MP4",
            source_fps=100.0,
            markers=(
                RawMarker("Start", 0),
                RawMarker("S1", 90),
                RawMarker("Finish", 280),
            ),
            clip_id="third",
            run_date="2026-05-31",
        )
        for run_id, selected in (
            ("baseline", baseline),
            ("first", first),
            ("second", second),
            ("third", third),
        ):
            service.commit_new_run(selected, run_id=run_id)

        result = service.commit_or_update_timeline_runs(
            [
                TimelineRunCandidate("First.MP4", first),
                TimelineRunCandidate("Second.MP4", second),
                TimelineRunCandidate("Third.MP4", third),
            ]
        )

        self.assertEqual(result.unchanged, 3)
        self.assertEqual(
            [item.preview.best_lap_references.lap_seconds for item in result.items],
            [3.2, 3.0, 2.9],
        )

    def test_chronological_overlay_payloads_exclude_later_timeline_runs(self):
        service = TimerService(TimerDatabase([self.course], []))
        baseline = SelectedRunInput(
            course_id="course",
            filename="Baseline.MP4",
            source_fps=100.0,
            markers=(
                RawMarker("Start", 0),
                RawMarker("S1", 100),
                RawMarker("Finish", 320),
            ),
            clip_id="baseline",
            run_date="2026-05-31",
        )
        first = SelectedRunInput(
            course_id="course",
            filename="First.MP4",
            source_fps=100.0,
            markers=(
                RawMarker("Start", 0),
                RawMarker("S1", 100),
                RawMarker("Finish", 300),
            ),
            clip_id="first",
            run_date="2026-05-31",
        )
        second = SelectedRunInput(
            course_id="course",
            filename="Second.MP4",
            source_fps=100.0,
            markers=(
                RawMarker("Start", 0),
                RawMarker("S1", 95),
                RawMarker("Finish", 290),
            ),
            clip_id="second",
            run_date="2026-05-31",
        )
        third = SelectedRunInput(
            course_id="course",
            filename="Third.MP4",
            source_fps=100.0,
            markers=(
                RawMarker("Start", 0),
                RawMarker("S1", 90),
                RawMarker("Finish", 280),
            ),
            clip_id="third",
            run_date="2026-05-31",
        )
        for run_id, selected in (
            ("baseline", baseline),
            ("first", first),
            ("second", second),
            ("third", third),
        ):
            service.commit_new_run(selected, run_id=run_id)

        result = service.chronological_overlay_payloads(
            [
                TimelineRunCandidate("First.MP4", first),
                TimelineRunCandidate("Second.MP4", second),
                TimelineRunCandidate("Third.MP4", third),
            ],
            comparison_mode="best_lap",
        )

        self.assertEqual(result.payload_count, 3)
        self.assertEqual(
            [item.payload.best_lap_seconds for item in result.items],
            [3.2, 3.0, 2.9],
        )

    def test_timeline_batch_handles_unchanged_changed_ignored_and_invalid_runs(self):
        service = TimerService(TimerDatabase([self.course], []))
        unchanged = service.commit_new_run(
            self.selected,
            run_id="unchanged",
            committed_at="2026-05-31T10:00:00Z",
        )
        ignored = service.commit_new_run(
            SelectedRunInput(
                course_id="course",
                filename="Ignored.MP4",
                source_fps=100.0,
                markers=(
                    RawMarker("Start", 0),
                    RawMarker("S1", 100),
                    RawMarker("Finish", 330),
                ),
                clip_id="ignored",
                run_date="2026-05-31",
            ),
            run_id="ignored",
            committed_at="2026-05-31T11:00:00Z",
        )
        service.set_ignored(ignored.id, True)

        result = service.commit_or_update_timeline_runs(
            [
                TimelineRunCandidate("Unchanged.MP4", self.selected),
                TimelineRunCandidate(
                    "Ignored.MP4",
                    SelectedRunInput(
                        course_id="course",
                        filename="Ignored.MP4",
                        source_fps=100.0,
                        markers=(
                            RawMarker("Start", 0),
                            RawMarker("S1", 90),
                            RawMarker("Finish", 310),
                        ),
                        clip_id="ignored",
                        run_date="2026-05-31",
                    ),
                ),
                TimelineRunCandidate(
                    "Bad.MP4",
                    SelectedRunInput(
                        course_id="course",
                        filename="Bad.MP4",
                        source_fps=100.0,
                        markers=(RawMarker("Start", 0), RawMarker("Finish", 300)),
                        clip_id="bad",
                    ),
                ),
                TimelineRunCandidate("NoSource.MP4", skip_reason="no source clip"),
            ]
        )

        self.assertEqual(result.unchanged, 1)
        self.assertEqual(result.updated, 1)
        self.assertEqual(result.skipped, 2)
        self.assertEqual(result.failed, 0)
        self.assertEqual(result.items[0].run_id, unchanged.id)
        updated_ignored = next(run for run in service.database.runs if run.id == ignored.id)
        self.assertTrue(updated_ignored.ignored)
        self.assertEqual(updated_ignored.marker_frames["Finish"], 310)
        self.assertIn("missing marker S1", result.items[2].message)
        self.assertIn("no source clip", result.items[3].message)

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

    def test_add_course_rejects_blank_fields(self):
        service = TimerService(TimerDatabase([], []))

        with self.assertRaises(ValueError):
            service.add_course(" ", "Name", 2)
        with self.assertRaises(ValueError):
            service.add_course("course", " ", 2)

    def test_update_and_delete_unreferenced_course(self):
        other = Course("other", "Other", 2)
        service = TimerService(TimerDatabase([self.course, other], []))

        updated = service.update_course("other", name="Renamed", sector_count=4)
        service.delete_course("other")

        self.assertEqual(updated, Course("other", "Renamed", 4))
        self.assertEqual(service.database.courses, [self.course])

    def test_course_mutations_reject_referenced_sector_change_and_delete(self):
        service = TimerService(TimerDatabase([self.course], []))
        service.commit_new_run(self.selected, run_id="run_custom")

        renamed = service.update_course("course", name="Renamed")

        self.assertEqual(renamed.name, "Renamed")
        with self.assertRaises(ValueError) as sector_change:
            service.update_course("course", sector_count=3)
        with self.assertRaises(ValueError) as delete:
            service.delete_course("course")
        self.assertIn("cannot change sector_count", str(sector_change.exception))
        self.assertIn("cannot delete course course", str(delete.exception))

    def test_normalize_fingerprints_updates_missing_or_stale_values(self):
        service = TimerService(TimerDatabase([self.course], []))
        run = service.commit_new_run(
            self.selected,
            run_id="run_custom",
            committed_at="2026-05-31T10:00:00Z",
        )
        run.fingerprint = None

        count = service.normalize_fingerprints()

        self.assertEqual(count, 1)
        self.assertEqual(run.fingerprint, clip_fingerprint(run.filename, run.marker_frames))

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

    def test_cli_preview_json_from_csv(self):
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
                        "--json",
                    ]
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["course"]["id"], "course")
        self.assertEqual(payload["matching_run_id"], "run_reference")
        self.assertEqual(payload["rows"][-1]["label"], "LAP")
        self.assertEqual(payload["rows"][-1]["delta_seconds"], 0.0)

    def test_cli_reports_validation_errors_without_traceback(self):
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
                        {"name": "Finish", "frame": "300"},
                    ]
                )

            stderr = StringIO()
            with patch("sys.stderr", stderr):
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

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: missing marker S1", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_cli_reports_bad_marker_csv_frame_with_row_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "timer_db.yaml"
            marker_path = tmp_path / "markers.csv"
            TimerDatabase([self.course], []).save(db_path)
            with marker_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["name", "frame"])
                writer.writeheader()
                writer.writerow({"name": "Start", "frame": "abc"})

            stderr = StringIO()
            with patch("sys.stderr", stderr):
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

        self.assertEqual(exit_code, 1)
        self.assertIn("row 2 invalid frame 'abc'", stderr.getvalue())

    def test_cli_reports_missing_marker_csv_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "timer_db.yaml"
            missing_marker_path = tmp_path / "missing.csv"
            TimerDatabase([self.course], []).save(db_path)

            stderr = StringIO()
            with patch("sys.stderr", stderr):
                exit_code = main(
                    [
                        "--db",
                        str(db_path),
                        "preview",
                        "--course",
                        "course",
                        "--markers",
                        str(missing_marker_path),
                        "--filename",
                        "GX010123.MP4",
                        "--fps",
                        "100",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: could not read marker CSV", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_cli_reports_malformed_database_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            db_path.write_text("schema_version: [unterminated\n", encoding="utf-8")

            stderr = StringIO()
            with patch("sys.stderr", stderr):
                exit_code = main(["--db", str(db_path), "courses"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: could not parse database", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_cli_reports_non_mapping_database_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            db_path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

            stderr = StringIO()
            with patch("sys.stderr", stderr):
                exit_code = main(["--db", str(db_path), "courses"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: database", stderr.getvalue())
        self.assertIn("must contain a YAML mapping", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

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

    def test_cli_overlay_text_from_csv(self):
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
                        "overlay-text",
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
        self.assertIn("LIVE        0:03.000", stdout.getvalue())
        self.assertIn("S1          0:01.000    --.---", stdout.getvalue())

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

    def test_cli_stats(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            service = TimerService(TimerDatabase([self.course], []))
            service.commit_new_run(
                self.selected,
                run_id="run_custom",
                committed_at="2026-05-31T10:00:00Z",
            )
            service.save(db_path)

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main(["--db", str(db_path), "stats", "--course", "course"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Course: Course", stdout.getvalue())
        self.assertIn("Eligible runs: 1", stdout.getvalue())
        self.assertIn("Best: 0:03.000 (run_custom)", stdout.getvalue())
        self.assertIn("Optimal: 0:03.000", stdout.getvalue())

    def test_cli_stats_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            service = TimerService(TimerDatabase([self.course], []))
            service.commit_new_run(
                self.selected,
                run_id="run_custom",
                committed_at="2026-05-31T10:00:00Z",
            )
            service.save(db_path)

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main(["--db", str(db_path), "stats", "--course", "course", "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["course_id"], "course")
        self.assertEqual(payload["eligible_run_count"], 1)
        self.assertEqual(payload["best_lap"]["run_id"], "run_custom")
        self.assertEqual(payload["best_lap"]["seconds"], 3.0)
        self.assertEqual([sector["sector"] for sector in payload["fastest_sectors"]], [1, 2])

    def test_cli_summary_card_writes_default_png(self):
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
                exit_code = main(["--db", str(db_path), "summary-card", "--course", "course"])
            files = list(tmp_path.glob("resolve_timer_summary_course_*.png"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(files), 1)
        self.assertIn(f"Wrote {files[0]}", stdout.getvalue())

    def test_cli_summary_card_writes_custom_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "timer_db.yaml"
            output_path = tmp_path / "custom.png"
            TimerDatabase([self.course], []).save(db_path)

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main(
                    [
                        "--db",
                        str(db_path),
                        "summary-card",
                        "--course",
                        "course",
                        "--output",
                        str(output_path),
                    ]
                )
            output_exists = output_path.exists()

        self.assertEqual(exit_code, 0)
        self.assertTrue(output_exists)
        self.assertIn(f"Wrote {output_path}", stdout.getvalue())

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

    def test_cli_commit_rejects_duplicate_run_id(self):
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
                        {"name": "S1", "frame": "100"},
                        {"name": "Finish", "frame": "300"},
                    ]
                )

            stderr = StringIO()
            with patch("sys.stderr", stderr):
                exit_code = main(
                    [
                        "--db",
                        str(db_path),
                        "commit",
                        "--course",
                        "course",
                        "--markers",
                        str(marker_path),
                        "--filename",
                        "GX010123.MP4",
                        "--fps",
                        "100",
                        "--run-id",
                        "run_custom",
                    ]
                )

        self.assertEqual(exit_code, 1)
        self.assertIn("Error: run already exists: run_custom", stderr.getvalue())

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

    def test_cli_normalize_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            service = TimerService(TimerDatabase([self.course], []))
            run = service.commit_new_run(
                self.selected,
                run_id="run_custom",
                committed_at="2026-05-31T10:00:00Z",
            )
            run.fingerprint = None
            service.save(db_path)

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                exit_code = main(["--db", str(db_path), "normalize-db"])

            loaded = TimerDatabase.load(db_path)

        self.assertEqual(exit_code, 0)
        self.assertIn("Updated 1 run fingerprints", stdout.getvalue())
        self.assertEqual(
            loaded.runs[0].fingerprint,
            clip_fingerprint("GX010123.MP4", loaded.runs[0].marker_frames),
        )

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

    def test_cli_update_and_delete_course(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            TimerDatabase(
                [
                    Course("course", "Course", 2),
                    Course("other", "Other", 2),
                ],
                [],
            ).save(db_path)

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                update_exit = main(
                    [
                        "--db",
                        str(db_path),
                        "update-course",
                        "--id",
                        "other",
                        "--name",
                        "Renamed",
                        "--sectors",
                        "4",
                    ]
                )

            stdout = StringIO()
            with patch("sys.stdout", stdout):
                delete_exit = main(
                    [
                        "--db",
                        str(db_path),
                        "delete-course",
                        "--id",
                        "other",
                    ]
                )

            loaded = TimerDatabase.load(db_path)

        self.assertEqual(update_exit, 0)
        self.assertEqual(delete_exit, 0)
        self.assertEqual(loaded.courses, [Course("course", "Course", 2)])

    def test_cli_course_mutations_reject_referenced_course_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "timer_db.yaml"
            service = TimerService(TimerDatabase([self.course], []))
            service.commit_new_run(self.selected, run_id="run_custom")
            service.save(db_path)
            original = db_path.read_text(encoding="utf-8")

            stderr = StringIO()
            with patch("sys.stderr", stderr):
                update_exit = main(
                    [
                        "--db",
                        str(db_path),
                        "update-course",
                        "--id",
                        "course",
                        "--sectors",
                        "3",
                    ]
                )
            update_error = stderr.getvalue()

            stderr = StringIO()
            with patch("sys.stderr", stderr):
                delete_exit = main(
                    [
                        "--db",
                        str(db_path),
                        "delete-course",
                        "--id",
                        "course",
                    ]
                )
            delete_error = stderr.getvalue()
            current = db_path.read_text(encoding="utf-8")

        self.assertEqual(update_exit, 1)
        self.assertEqual(delete_exit, 1)
        self.assertIn("Error: cannot change sector_count", update_error)
        self.assertIn("Error: cannot delete course course", delete_error)
        self.assertNotIn("Traceback", update_error)
        self.assertNotIn("Traceback", delete_error)
        self.assertEqual(current, original)


if __name__ == "__main__":
    unittest.main()
