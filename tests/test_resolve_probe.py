import json
import tempfile
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resolve_timer.resolve_probe import probe_resolve, save_probe_result


class FakeResolve:
    def GetVersionString(self):
        return "19.1.0"

    def GetProjectManager(self):
        return FakeProjectManager()


class FakeProjectManager:
    def GetCurrentProject(self):
        return FakeProject()


class FakeProject:
    def GetName(self):
        return "Project"

    def GetCurrentTimeline(self):
        return FakeTimeline()


class FakeTimeline:
    def GetName(self):
        return "Timeline"

    def GetCurrentVideoItem(self):
        return FakeTimelineItem()


class FakeTimelineItem:
    def GetName(self):
        return "Timeline Item"

    def GetMediaPoolItem(self):
        return FakeSourceClip()


class FakeSourceClip:
    def GetName(self):
        return "Source Clip"

    def GetUniqueId(self):
        return "clip-1"

    def GetMarkers(self):
        return {0: {"name": "Start", "color": "Blue"}, 100: {"name": "Finish"}}

    def GetClipProperty(self):
        return {"File Name": "GX010123.MP4", "FPS": "100"}


class ResolveProbeTests(unittest.TestCase):
    def test_probe_resolve_captures_selected_clip_shape(self):
        result = probe_resolve(FakeResolve())

        self.assertIsNone(result.error)
        self.assertEqual(result.resolve_version, "19.1.0")
        self.assertEqual(result.project_name, "Project")
        self.assertEqual(result.timeline_name, "Timeline")
        self.assertEqual(result.source_clip_id, "clip-1")
        self.assertEqual(result.marker_keys, ("0", "100"))
        self.assertEqual(result.marker_payload_keys, ("name", "color"))
        self.assertEqual(result.clip_property_keys, ("File Name", "FPS"))
        self.assertEqual(result.selected_filename, "GX010123.MP4")
        self.assertEqual(result.selected_source_fps, 100.0)
        self.assertEqual(result.selected_marker_count, 2)

    def test_save_probe_result_writes_json(self):
        result = probe_resolve(FakeResolve())

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "probe.json"
            save_probe_result(result, path)
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["resolve_version"], "19.1.0")
        self.assertEqual(payload["selected_marker_count"], 2)


if __name__ == "__main__":
    unittest.main()
