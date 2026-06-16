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
    def __init__(self, selected_clips, timeline=None):
        self.media_pool = FakeMediaPool(selected_clips)
        self.timeline = timeline

    def GetMediaPool(self):
        return self.media_pool

    def GetCurrentTimeline(self):
        return self.timeline


class FakeMediaPool:
    def __init__(self, selected_clips):
        self.selected_clips = selected_clips

    def GetSelectedClips(self):
        return self.selected_clips


class FakeSourceClip:
    def __init__(self, clip_id="clip-1", name="GX010123.MP4"):
        self.clip_id = clip_id
        self.name = name

    def GetMarkers(self):
        return {0: {"name": "Start"}, 100: {"name": "S1"}, 300: {"name": "Finish"}}

    def GetClipProperty(self):
        return {"File Name": self.name, "FPS": "100"}

    def GetUniqueId(self):
        return self.clip_id

    def GetName(self):
        return self.name


class FakeTimeline:
    def __init__(self, item=None, tracks=None, track_count=None):
        self.item = item
        self.tracks = tracks or {}
        self.track_count = track_count
        self.items_in_track_calls = []

    def GetCurrentVideoItem(self):
        return self.item

    def GetTrackCount(self, track_type):
        if track_type != "video":
            raise AssertionError(f"unexpected track type: {track_type}")
        if self.track_count is not None:
            return self.track_count
        return max(self.tracks, default=0)

    def GetItemsInTrack(self, track_type, track_index):
        if track_type != "video":
            raise AssertionError(f"unexpected track type: {track_type}")
        self.items_in_track_calls.append((track_type, track_index))
        return self.tracks.get(track_index)


class FakeTimelineItem:
    def __init__(self, media_pool_item):
        self.media_pool_item = media_pool_item

    def GetMediaPoolItem(self):
        return self.media_pool_item


class ResolveAdapterTests(unittest.TestCase):
    def test_selected_media_pool_run_reads_source_clip_markers(self):
        source_clip = FakeSourceClip()
        resolve = FakeResolve(FakeProjectManager(FakeProject([source_clip])))
        adapter = ResolveAdapter(resolve)

        selected = adapter.selected_media_pool_run()

        self.assertIs(selected.source_clip, source_clip)
        self.assertEqual(selected.filename, "GX010123.MP4")
        self.assertEqual(selected.source_fps, 100.0)
        self.assertEqual(selected.clip_id, "clip-1")
        self.assertEqual(selected.marker_source, "source_clip")
        self.assertEqual(
            [(marker.name, marker.frame) for marker in selected.source_markers],
            [("Start", 0), ("S1", 100), ("Finish", 300)],
        )

    def test_media_pool_run_reads_an_explicit_source_clip(self):
        source_clip = FakeSourceClip("clip-explicit", "Explicit.MP4")
        adapter = ResolveAdapter(
            FakeResolve(FakeProjectManager(FakeProject([])))
        )

        selected = adapter.media_pool_run(source_clip)

        self.assertIs(selected.source_clip, source_clip)
        self.assertEqual(selected.filename, "Explicit.MP4")
        self.assertEqual(selected.clip_id, "clip-explicit")

    def test_selected_run_input_converts_adapter_selection_for_service(self):
        source_clip = FakeSourceClip()
        resolve = FakeResolve(FakeProjectManager(FakeProject([source_clip])))
        adapter = ResolveAdapter(resolve)

        selected = adapter.selected_run_input("course", run_date="2026-05-31")

        self.assertEqual(selected.course_id, "course")
        self.assertEqual(selected.filename, "GX010123.MP4")
        self.assertEqual(selected.source_fps, 100.0)
        self.assertEqual(selected.clip_id, "clip-1")
        self.assertEqual(selected.run_date, "2026-05-31")

    def test_selected_media_pool_run_requires_one_selected_clip(self):
        resolve = FakeResolve(FakeProjectManager(FakeProject([])))
        adapter = ResolveAdapter(resolve)

        with self.assertRaises(ResolveAdapterError) as raised:
            adapter.selected_media_pool_run()

        self.assertIn("Select exactly one Media Pool clip", str(raised.exception))

    def test_selected_media_pool_run_rejects_multiple_selected_clips(self):
        resolve = FakeResolve(
            FakeProjectManager(FakeProject([FakeSourceClip(), FakeSourceClip()]))
        )

        with self.assertRaises(ResolveAdapterError) as raised:
            ResolveAdapter(resolve).selected_media_pool_run()

        self.assertIn("reports 2 selected", str(raised.exception))

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

    def test_current_timeline_item_source_can_build_media_pool_run(self):
        source_clip = FakeSourceClip("timeline-clip", "Timeline.MP4")
        timeline_item = FakeTimelineItem(source_clip)
        project = FakeProject([], FakeTimeline(timeline_item))
        adapter = ResolveAdapter(FakeResolve(FakeProjectManager(project)))

        current_item = adapter.current_timeline_video_item()
        selected = adapter.timeline_item_media_pool_run(current_item)

        self.assertIs(current_item, timeline_item)
        self.assertIs(selected.source_clip, source_clip)
        self.assertEqual(selected.filename, "Timeline.MP4")
        self.assertEqual(selected.source_fps, 100.0)
        self.assertEqual(selected.clip_id, "timeline-clip")
        self.assertEqual(
            [(marker.name, marker.frame) for marker in selected.source_markers],
            [("Start", 0), ("S1", 100), ("Finish", 300)],
        )

    def test_timeline_item_media_pool_run_requires_media_pool_item(self):
        project = FakeProject([], FakeTimeline(FakeTimelineItem(None)))
        adapter = ResolveAdapter(FakeResolve(FakeProjectManager(project)))

        with self.assertRaises(ResolveAdapterError) as raised:
            adapter.timeline_item_media_pool_run(adapter.current_timeline_video_item())

        self.assertIn("GetMediaPoolItem returned nothing", str(raised.exception))

    def test_timeline_video_items_enumerates_all_video_tracks(self):
        first = FakeTimelineItem(FakeSourceClip("clip-1"))
        second = FakeTimelineItem(FakeSourceClip("clip-2"))
        third = FakeTimelineItem(FakeSourceClip("clip-3"))
        timeline = FakeTimeline(
            tracks={
                1: {1: first, 2: second},
                2: {},
                4: {1: third},
            },
            track_count=4,
        )
        project = FakeProject([], timeline)
        adapter = ResolveAdapter(FakeResolve(FakeProjectManager(project)))

        items = adapter.timeline_video_items()

        self.assertEqual(items, (first, second, third))
        self.assertEqual(
            timeline.items_in_track_calls,
            [("video", 1), ("video", 2), ("video", 3), ("video", 4)],
        )

    def test_timeline_video_items_returns_empty_without_current_timeline(self):
        adapter = ResolveAdapter(FakeResolve(FakeProjectManager(FakeProject([]))))

        self.assertEqual(adapter.timeline_video_items(), ())

    def test_timeline_video_items_returns_empty_for_zero_video_tracks(self):
        project = FakeProject([], FakeTimeline(track_count=0))
        adapter = ResolveAdapter(FakeResolve(FakeProjectManager(project)))

        self.assertEqual(adapter.timeline_video_items(), ())

    def test_matching_current_timeline_video_item_accepts_same_clip_id(self):
        source_clip = FakeSourceClip()
        timeline_item = FakeTimelineItem(source_clip)
        project = FakeProject([source_clip], FakeTimeline(timeline_item))
        adapter = ResolveAdapter(FakeResolve(FakeProjectManager(project)))
        selected = adapter.selected_media_pool_run()

        result = adapter.matching_current_timeline_video_item(selected)

        self.assertIs(result, timeline_item)

    def test_matching_current_timeline_video_item_rejects_other_clip(self):
        source_clip = FakeSourceClip("clip-1")
        timeline_item = FakeTimelineItem(FakeSourceClip("clip-2"))
        project = FakeProject([source_clip], FakeTimeline(timeline_item))
        adapter = ResolveAdapter(FakeResolve(FakeProjectManager(project)))
        selected = adapter.selected_media_pool_run()

        with self.assertRaises(ResolveAdapterError) as raised:
            adapter.matching_current_timeline_video_item(selected)

        self.assertIn("does not match", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
