import json
import builtins
import importlib
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def GetStart(self):
        return 1000

    def GetEnd(self):
        return 1300

    def GetSourceStartFrame(self):
        return 10

    def GetSourceEndFrame(self):
        return 310

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
        self.assertEqual(result.timeline_item_start, "1000")
        self.assertEqual(result.timeline_item_end, "1300")
        self.assertEqual(result.timeline_item_source_start, "10")
        self.assertEqual(result.timeline_item_source_end, "310")
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

    def test_probe_module_import_does_not_require_yaml(self):
        original_import = builtins.__import__

        def reject_yaml(name, *args, **kwargs):
            if name == "yaml":
                raise ModuleNotFoundError("No module named 'yaml'")
            return original_import(name, *args, **kwargs)

        sys.modules.pop("resolve_timer.resolve_probe", None)
        sys.modules.pop("resolve_timer.resolve_adapter", None)
        with patch("builtins.__import__", side_effect=reject_yaml):
            module = importlib.import_module("resolve_timer.resolve_probe")

        self.assertTrue(hasattr(module, "probe_resolve"))


if __name__ == "__main__":
    unittest.main()
