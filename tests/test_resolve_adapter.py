import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resolve_timer.resolve_adapter import ResolveAdapter, ResolveAdapterError


class ResolveAdapterTests(unittest.TestCase):
    def test_markers_from_resolve_map_uses_marker_name_and_frame_key(self):
        markers = ResolveAdapter.markers_from_resolve_map(
            {
                300: {"name": "Finish"},
                "0": {"name": "Start"},
                100.0: {"Name": "S1"},
                50: {"color": "Blue"},
            }
        )

        self.assertEqual([(marker.name, marker.frame) for marker in markers], [
            ("Start", 0),
            ("S1", 100),
            ("Finish", 300),
        ])

    def test_source_fps_from_properties_accepts_common_keys_and_fraction(self):
        self.assertEqual(ResolveAdapter.source_fps_from_properties({"FPS": "59.94"}), 59.94)
        self.assertAlmostEqual(
            ResolveAdapter.source_fps_from_properties({"Frame Rate": "30000/1001"}),
            29.97002997002997,
        )

    def test_invalid_fps_raises_adapter_error(self):
        with self.assertRaises(ResolveAdapterError):
            ResolveAdapter.source_fps_from_properties({"FPS": "0"})
        with self.assertRaises(ResolveAdapterError):
            ResolveAdapter.source_fps_from_properties({"FPS": "not-a-rate"})
        with self.assertRaises(ResolveAdapterError):
            ResolveAdapter.source_fps_from_properties({"FPS": "30000/0"})


if __name__ == "__main__":
    unittest.main()
