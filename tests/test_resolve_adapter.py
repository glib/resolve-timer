import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resolve_timer.resolve_adapter import ResolveAdapter, ResolveAdapterError


class FakeResolve:
    def __init__(self, project_manager):
        self.project_manager = project_manager

    def GetProjectManager(self):
        return self.project_manager


class FakeProjectManager:
    def __init__(self, project):
        self.project = project

    def GetCurrentProject(self):
        return self.project


class FakeProject:
    def __init__(self, timeline):
        self.timeline = timeline

    def GetCurrentTimeline(self):
        return self.timeline


class FakeTimeline:
    def __init__(self, item):
        self.item = item

    def GetCurrentVideoItem(self):
        return self.item


class FakeTimelineItem:
    def __init__(self, source_clip):
        self.source_clip = source_clip

    def GetMediaPoolItem(self):
        return self.source_clip

    def GetName(self):
        return "Timeline Item"


class FakeSourceClip:
    def GetMarkers(self):
        return {0: {"name": "Start"}, 100: {"name": "S1"}, 300: {"name": "Finish"}}

    def GetClipProperty(self):
        return {"File Name": "GX010123.MP4", "FPS": "100"}

    def GetUniqueId(self):
        return "clip-1"


class ResolveAdapterTests(unittest.TestCase):
    def test_selected_timeline_run_reads_source_clip_markers(self):
        source_clip = FakeSourceClip()
        timeline_item = FakeTimelineItem(source_clip)
        resolve = FakeResolve(FakeProjectManager(FakeProject(FakeTimeline(timeline_item))))
        adapter = ResolveAdapter(resolve)

        selected = adapter.selected_timeline_run()

        self.assertIs(selected.timeline_item, timeline_item)
        self.assertIs(selected.source_clip, source_clip)
        self.assertEqual(selected.filename, "GX010123.MP4")
        self.assertEqual(selected.source_fps, 100.0)
        self.assertEqual(selected.clip_id, "clip-1")
        self.assertEqual(
            [(marker.name, marker.frame) for marker in selected.source_markers],
            [("Start", 0), ("S1", 100), ("Finish", 300)],
        )

    def test_selected_run_input_converts_adapter_selection_for_service(self):
        source_clip = FakeSourceClip()
        timeline_item = FakeTimelineItem(source_clip)
        resolve = FakeResolve(FakeProjectManager(FakeProject(FakeTimeline(timeline_item))))
        adapter = ResolveAdapter(resolve)

        selected = adapter.selected_run_input("course", run_date="2026-05-31")

        self.assertEqual(selected.course_id, "course")
        self.assertEqual(selected.filename, "GX010123.MP4")
        self.assertEqual(selected.source_fps, 100.0)
        self.assertEqual(selected.clip_id, "clip-1")
        self.assertEqual(selected.run_date, "2026-05-31")

    def test_selected_timeline_run_reports_missing_current_item(self):
        resolve = FakeResolve(FakeProjectManager(FakeProject(FakeTimeline(None))))
        adapter = ResolveAdapter(resolve)

        with self.assertRaises(ResolveAdapterError) as raised:
            adapter.selected_timeline_run()

        self.assertIn("GetCurrentVideoItem returned nothing", str(raised.exception))

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

    def test_markers_from_resolve_map_rejects_non_dictionary_payload(self):
        with self.assertRaises(ResolveAdapterError) as raised:
            ResolveAdapter.markers_from_resolve_map({0: "Start"})

        self.assertIn("marker payload for frame 0 is not a dictionary", str(raised.exception))

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
