import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resolve_timer.database import DatabaseError, TimerDatabase
from resolve_timer.matching import clip_fingerprint, find_matching_run, marker_snapshot_hash
from resolve_timer.models import Course, RunRecord, utc_timestamp
from resolve_timer.stats import compute_course_stats
from resolve_timer.validation import validate_database


def run_record(
    run_id,
    frames,
    *,
    committed=True,
    ignored=False,
    committed_at="2026-05-31T10:00:00Z",
    filename="GX010123.MP4",
    clip_id=None,
):
    fingerprint = clip_fingerprint(filename, frames)
    return RunRecord(
        id=run_id,
        course_id="course",
        date="2026-05-31",
        filename=filename,
        source_fps=100.0,
        marker_frames=frames,
        clip_id=clip_id,
        fingerprint=fingerprint,
        committed=committed,
        ignored=ignored,
        committed_at=committed_at,
    )


class DatabaseStatsMatchingTests(unittest.TestCase):
    def setUp(self):
        self.course = Course("course", "Course", 2)
        self.frames_a = {"Start": 0, "S1": 100, "Finish": 300}
        self.frames_b = {"Start": 0, "S1": 80, "Finish": 280}

    def test_database_round_trip_preserves_schema_and_run_snapshot(self):
        db = TimerDatabase([self.course], [run_record("run_a", self.frames_a)])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timer_db.yaml"
            db.save(path)
            loaded = TimerDatabase.load(path)

        self.assertEqual(loaded.courses[0], self.course)
        self.assertEqual(loaded.runs[0].marker_frames, self.frames_a)
        self.assertEqual(loaded.runs[0].fingerprint, clip_fingerprint("GX010123.MP4", self.frames_a))

    def test_database_save_replaces_target_without_leaving_temp_file(self):
        db = TimerDatabase([self.course], [run_record("run_a", self.frames_a)])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timer_db.yaml"
            db.save(path)

            self.assertTrue(path.exists())
            self.assertFalse((Path(tmp) / "timer_db.yaml.tmp").exists())

    def test_database_save_removes_temp_file_after_write_failure(self):
        db = TimerDatabase([self.course], [run_record("run_a", self.frames_a)])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timer_db.yaml"
            with patch("resolve_timer.database.yaml.safe_dump", side_effect=RuntimeError("boom")):
                with self.assertRaises(DatabaseError):
                    db.save(path)

            self.assertFalse(path.exists())
            self.assertFalse((Path(tmp) / "timer_db.yaml.tmp").exists())

    def test_database_load_rejects_non_mapping_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timer_db.yaml"
            path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

            with self.assertRaises(DatabaseError) as raised:
                TimerDatabase.load(path)

        self.assertIn("must contain a YAML mapping", str(raised.exception))

    def test_database_load_wraps_malformed_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "timer_db.yaml"
            path.write_text("schema_version: [unterminated\n", encoding="utf-8")

            with self.assertRaises(DatabaseError) as raised:
                TimerDatabase.load(path)

        self.assertIn("could not parse database", str(raised.exception))

    def test_stats_use_only_committed_non_ignored_valid_runs(self):
        runs = [
            run_record("run_a", self.frames_a, committed_at="2026-05-31T10:00:00Z"),
            run_record("run_b", self.frames_b, committed=False),
            run_record("run_c", self.frames_b, ignored=True),
            run_record("run_d", {"Start": 0, "Finish": 100}),
        ]

        stats = compute_course_stats(self.course, runs)

        self.assertEqual([item.run.id for item in stats.eligible_runs], ["run_a"])
        self.assertEqual(stats.best_lap.run.id, "run_a")
        self.assertEqual(stats.optimal_seconds, 3.0)

    def test_best_lap_tie_uses_earliest_committed_run(self):
        runs = [
            run_record("late", self.frames_a, committed_at="2026-05-31T11:00:00Z"),
            run_record("early", self.frames_a, committed_at="2026-05-31T10:00:00Z"),
        ]

        stats = compute_course_stats(self.course, runs)

        self.assertEqual(stats.best_lap.run.id, "early")

    def test_fastest_sector_can_mix_runs_for_optimal(self):
        run_a = run_record("run_a", {"Start": 0, "S1": 100, "Finish": 300})
        run_b = run_record("run_b", {"Start": 0, "S1": 80, "Finish": 320})

        stats = compute_course_stats(self.course, [run_a, run_b])

        self.assertEqual([sector.run.id for sector in stats.fastest_sectors], ["run_b", "run_a"])
        self.assertEqual(stats.optimal_seconds, 2.8)

    def test_matching_prefers_clip_id_then_fingerprint(self):
        run_a = run_record("run_a", self.frames_a, clip_id="clip-a")
        run_b = run_record("run_b", self.frames_b, clip_id="clip-b")

        self.assertEqual(
            find_matching_run(
                [run_a, run_b],
                course_id="course",
                filename="GX010123.MP4",
                marker_frames=self.frames_b,
                clip_id="clip-a",
            ).id,
            "run_a",
        )
        self.assertEqual(
            find_matching_run(
                [run_a, run_b],
                course_id="course",
                filename="GX010123.MP4",
                marker_frames=self.frames_b,
            ).id,
            "run_b",
        )
        self.assertEqual(len(marker_snapshot_hash(self.frames_a)), 16)

    def test_matching_falls_back_to_filename_and_exact_marker_frames(self):
        run = run_record("run_a", self.frames_a)
        run.fingerprint = None

        match = find_matching_run(
            [run],
            course_id="course",
            filename="GX010123.MP4",
            marker_frames=self.frames_a,
        )

        self.assertEqual(match.id, "run_a")

    def test_validate_database_reports_consistency_errors(self):
        valid = TimerDatabase([self.course], [run_record("run_a", self.frames_a)])
        self.assertEqual(validate_database(valid), [])

        invalid = TimerDatabase(
            [self.course, Course("course", "Duplicate", 2)],
            [
                run_record("run_a", self.frames_a),
                run_record("run_a", {"Start": 0, "Finish": 100}),
                RunRecord(
                    id="missing_course",
                    course_id="missing",
                    date="2026-05-31",
                    filename="GX010124.MP4",
                    source_fps=100.0,
                    marker_frames=self.frames_a,
                ),
                RunRecord(
                    id="bad_fps",
                    course_id="course",
                    date="2026-05-31",
                    filename="GX010125.MP4",
                    source_fps=0,
                    marker_frames=self.frames_a,
                ),
            ],
        )

        errors = validate_database(invalid)

        self.assertIn("duplicate course id: course", errors)
        self.assertIn("duplicate run id: run_a", errors)
        self.assertIn("run run_a: missing marker S1", errors)
        self.assertIn("run missing_course references missing course missing", errors)
        self.assertIn("run bad_fps source_fps must be greater than 0", errors)

    def test_utc_timestamp_uses_z_suffix(self):
        timestamp = utc_timestamp()

        self.assertTrue(timestamp.endswith("Z"))
        self.assertNotIn("+00:00", timestamp)


if __name__ == "__main__":
    unittest.main()
