import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resolve_timer.markers import MarkerValidationError, parse_marker_snapshot
from resolve_timer.models import Course, RawMarker
from resolve_timer.timing import compute_timing, format_delta, format_duration


class MarkerTimingTests(unittest.TestCase):
    def setUp(self):
        self.course = Course("course", "Course", 4)

    def test_valid_four_sector_course_requires_three_sector_markers(self):
        snapshot = parse_marker_snapshot(
            [
                RawMarker("Start", 100),
                RawMarker("S1", 200),
                RawMarker("S2", 350),
                RawMarker("S3", 500),
                RawMarker("Finish", 700),
            ],
            self.course,
        )

        timing = compute_timing(snapshot, self.course, 100.0)

        self.assertEqual([sector.duration_frames for sector in timing.sectors], [100, 150, 150, 200])
        self.assertEqual(timing.lap_frames, 600)
        self.assertEqual(format_duration(timing.lap_seconds), "0:06.000")

    def test_missing_start_is_validation_error(self):
        with self.assertRaises(MarkerValidationError) as raised:
            parse_marker_snapshot(
                [
                    RawMarker("S1", 200),
                    RawMarker("S2", 350),
                    RawMarker("S3", 500),
                    RawMarker("Finish", 700),
                ],
                self.course,
            )

        self.assertIn("missing marker Start", raised.exception.errors)

    def test_duplicate_marker_is_validation_error(self):
        with self.assertRaises(MarkerValidationError) as raised:
            parse_marker_snapshot(
                [
                    RawMarker("Start", 100),
                    RawMarker("S1", 200),
                    RawMarker("S1", 210),
                    RawMarker("S2", 350),
                    RawMarker("S3", 500),
                    RawMarker("Finish", 700),
                ],
                self.course,
            )

        self.assertIn("duplicate marker S1", raised.exception.errors)

    def test_extra_sector_marker_is_validation_error(self):
        with self.assertRaises(MarkerValidationError) as raised:
            parse_marker_snapshot(
                [
                    RawMarker("Start", 100),
                    RawMarker("S1", 200),
                    RawMarker("S2", 350),
                    RawMarker("S3", 500),
                    RawMarker("S4", 650),
                    RawMarker("Finish", 700),
                ],
                self.course,
            )

        self.assertIn("unexpected marker S4", raised.exception.errors)

    def test_out_of_order_marker_is_validation_error(self):
        with self.assertRaises(MarkerValidationError) as raised:
            parse_marker_snapshot(
                [
                    RawMarker("Start", 100),
                    RawMarker("S1", 200),
                    RawMarker("S2", 190),
                    RawMarker("S3", 500),
                    RawMarker("Finish", 700),
                ],
                self.course,
            )

        self.assertIn("marker S2 frame 190 must be after S1 frame 200", raised.exception.errors)

    def test_fractional_fps_decimal_math_and_delta_formatting(self):
        snapshot = parse_marker_snapshot(
            [
                RawMarker("Start", 0),
                RawMarker("S1", 30),
                RawMarker("S2", 60),
                RawMarker("S3", 90),
                RawMarker("Finish", 120),
            ],
            self.course,
        )

        timing = compute_timing(snapshot, self.course, 29.97)

        self.assertEqual(format_duration(timing.lap_seconds), "0:04.004")
        self.assertEqual(format_delta(1.204), "+1.204")
        self.assertEqual(format_delta(-0.532), "-0.532")
        self.assertEqual(format_delta(0.0), "+0.000")


if __name__ == "__main__":
    unittest.main()
