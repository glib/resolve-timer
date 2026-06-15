import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resolve_timer.markers import parse_marker_snapshot
from resolve_timer.models import Course, RawMarker
from resolve_timer.overlay import (
    FusionOverlayUpdater,
    build_overlay_payload,
    final_overlay_rows,
    format_final_overlay_text,
    generated_overlay_name,
)
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
        self.assertIn("final_text", payload.to_dict())
        self.assertEqual(payload.to_dict()["rows"][-1]["label"], "LAP")
        self.assertEqual(payload.to_dict()["rows"][-1]["duration"], "0:03.000")

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

    def test_final_overlay_text_formats_sector_and_lap_deltas(self):
        course = Course("course", "Course", 2)
        snapshot = parse_marker_snapshot(
            [RawMarker("Start", 0), RawMarker("S1", 100), RawMarker("Finish", 310)],
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
            optimal_lap_seconds=2.9,
        )

        rows = final_overlay_rows(payload)
        text = format_final_overlay_text(payload)

        self.assertEqual([(row.label, row.delta_seconds) for row in rows], [
            ("S1", 0.0),
            ("S2", 0.10000000000000009),
            ("LAP", 0.10000000000000009),
        ])
        self.assertIn("LIVE        0:03.100", text)
        self.assertIn("S2          0:02.100    +0.100", text)
        self.assertIn("BEST        0:03.000", text)
        self.assertIn("OPTIMAL     0:02.900", text)

    def test_fusion_updater_creates_named_comp_and_static_nodes(self):
        payload = self._payload()
        timeline_item = FakeTimelineItem()

        result = FusionOverlayUpdater().update_or_create(timeline_item, payload)

        self.assertTrue(result.created)
        self.assertEqual(result.comp_name, "Resolve Timer - course")
        self.assertEqual(timeline_item.names, ["Resolve Timer - course"])
        comp = timeline_item.comps["Resolve Timer - course"]
        self.assertEqual(comp.tools["ResolveTimerText"].inputs["StyledText"], result.final_text)
        self.assertIs(
            comp.tools["ResolveTimerMerge"].connections["Background"],
            comp.tools["MediaIn1"],
        )
        self.assertIs(
            comp.tools["MediaOut1"].connections["Input"],
            comp.tools["ResolveTimerMerge"],
        )
        self.assertEqual(comp.tools["MediaOut1"].inputs["ColorGrade"], "Color")

    def test_fusion_updater_reuses_existing_comp_and_nodes(self):
        payload = self._payload()
        timeline_item = FakeTimelineItem()
        updater = FusionOverlayUpdater()
        first = updater.update_or_create(timeline_item, payload)
        text_tool = timeline_item.comps[first.comp_name].tools["ResolveTimerText"]

        second = updater.update_or_create(timeline_item, payload)

        self.assertFalse(second.created)
        self.assertEqual(timeline_item.add_count, 1)
        self.assertIs(
            timeline_item.comps[second.comp_name].tools["ResolveTimerText"],
            text_tool,
        )

    @staticmethod
    def _payload():
        course = Course("course", "Course", 2)
        snapshot = parse_marker_snapshot(
            [RawMarker("Start", 0), RawMarker("S1", 100), RawMarker("Finish", 300)],
            course,
        )
        timing = compute_timing(snapshot, course, 100.0)
        return build_overlay_payload(
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


class FakeTool:
    def __init__(self, name):
        self.name = name
        self.inputs = {}
        self.connections = {}
        self.comp = None

    def SetAttrs(self, attrs):
        old_name = self.name
        self.name = attrs["TOOLS_Name"]
        if self.comp is not None:
            self.comp.tools.pop(old_name, None)
            self.comp.tools[self.name] = self
        return True

    def SetInput(self, name, value):
        self.inputs[name] = value
        return True

    def ConnectInput(self, name, source):
        self.connections[name] = source
        return True


class FakeComp:
    def __init__(self, name):
        self.name = name
        self.tools = {
            "MediaIn1": FakeTool("MediaIn1"),
            "MediaOut1": FakeTool("MediaOut1"),
        }
        for tool in self.tools.values():
            tool.comp = self

    def Lock(self):
        return None

    def Unlock(self):
        return None

    def FindTool(self, name):
        return self.tools.get(name)

    def AddTool(self, tool_type, _x, _y):
        tool = FakeTool(tool_type)
        tool.comp = self
        self.tools[tool_type] = tool
        return tool

    def GetAttrs(self):
        return {"COMPS_Name": self.name}


class FakeTimelineItem:
    def __init__(self):
        self.names = []
        self.comps = {}
        self.add_count = 0

    def GetFusionCompNameList(self):
        return list(self.names)

    def AddFusionComp(self):
        self.add_count += 1
        name = f"Composition {self.add_count}"
        comp = FakeComp(name)
        self.names.append(name)
        self.comps[name] = comp
        return comp

    def RenameFusionCompByName(self, old_name, new_name):
        comp = self.comps.pop(old_name)
        comp.name = new_name
        self.comps[new_name] = comp
        self.names[self.names.index(old_name)] = new_name
        return True

    def GetFusionCompByName(self, name):
        return self.comps.get(name)


if __name__ == "__main__":
    unittest.main()
