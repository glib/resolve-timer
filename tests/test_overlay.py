import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resolve_timer.markers import parse_marker_snapshot
from resolve_timer.models import Course, RawMarker
from resolve_timer.overlay import build_overlay_payload, generated_overlay_name
from resolve_timer.timing import compute_timing


class OverlayTests(unittest.TestCase):
    def test_generated_overlay_name_uses_run_id_when_available(self):
        course = Course("course", "Course", 2)
        snapshot = parse_marker_snapshot(
            [RawMarker("Start", 0), RawMarker("S1", 100), RawMarker("Finish", 300)],
            course,
        )
        timing = compute_timing(snapshot, course, 100.0)
        payload = build_overlay_payload(
            course=course,
            snapshot=snapshot,
            current_timing=timing,
            comparison_mode="best_lap",
            run_id="run_custom",
            source_fps=100.0,
            sector_reference_seconds=(1.0, 2.0),
            best_lap_seconds=3.0,
            optimal_lap_seconds=3.0,
        )

        self.assertEqual(generated_overlay_name(payload), "Resolve Timer - course - run_custom")
        self.assertEqual(payload.to_dict()["generated_name"], "Resolve Timer - course - run_custom")

    def test_generated_overlay_name_falls_back_to_marker_hash(self):
        course = Course("course", "Course", 2)
        snapshot = parse_marker_snapshot(
            [RawMarker("Start", 0), RawMarker("S1", 100), RawMarker("Finish", 300)],
            course,
        )
        timing = compute_timing(snapshot, course, 100.0)
        payload = build_overlay_payload(
            course=course,
            snapshot=snapshot,
            current_timing=timing,
            comparison_mode="best_lap",
            run_id=None,
            source_fps=100.0,
            sector_reference_seconds=(None, None),
            best_lap_seconds=None,
            optimal_lap_seconds=None,
        )

        self.assertRegex(generated_overlay_name(payload), r"^Resolve Timer - course - [0-9a-f]{16}$")


if __name__ == "__main__":
    unittest.main()
