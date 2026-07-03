import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from resolve_timer.markers import parse_marker_snapshot
from resolve_timer.models import Course, RawMarker
from resolve_timer.overlay import (
    FusionOverlayUpdater,
    OVERLAY_CANVAS_HEIGHT,
    OVERLAY_CANVAS_WIDTH,
    build_fusion_overlay_rows,
    build_live_timer_expression,
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

    def test_fusion_updater_creates_named_comp_and_timed_nodes(self):
        payload = self._payload()
        timeline_item = FakeTimelineItem()

        result = FusionOverlayUpdater().update_or_create(timeline_item, payload)

        self.assertTrue(result.created)
        self.assertEqual(result.comp_name, "Resolve Timer - course")
        self.assertEqual(timeline_item.names, ["Resolve Timer - course"])
        comp = timeline_item.comps["Resolve Timer - course"]
        self.assertEqual(
            comp.tools["ResolveTimerText"].expressions["StyledText"],
            result.live_expression,
        )
        self.assertEqual(comp.tools["ResolveTimerText"].inputs["GlobalIn"], 0)
        self.assertIs(
            comp.tools["ResolveTimerMerge"].connections["Background"],
            comp.tools["ResolveTimerPanelBorderMerge"],
        )
        self.assertIs(
            comp.tools["MediaOut1"].connections["Input"],
            comp.tools["ResolveTimerOptimalMerge"],
        )
        self.assertEqual(comp.tools["MediaOut1"].inputs["ColorGrade"], "Color")
        self.assertEqual(
            comp.tools["ResolveTimerPanelBackground"].inputs["TopLeftAlpha"],
            0.52,
        )
        self.assertEqual(
            comp.tools["ResolveTimerText"].inputs["Font"],
            "JetBrains Mono",
        )
        self.assertEqual(
            comp.tools["ResolveTimerText"].inputs["Style"],
            "Medium",
        )
        for name in (
            "ResolveTimerPanelBackground",
            "ResolveTimerPanelBorderBackground",
        ):
            self.assertEqual(comp.tools[name].inputs["UseFrameFormatSettings"], 0)
            self.assertEqual(comp.tools[name].inputs["Width"], OVERLAY_CANVAS_WIDTH)
            self.assertEqual(comp.tools[name].inputs["Height"], OVERLAY_CANVAS_HEIGHT)
        for name in (
            "ResolveTimerText",
            "ResolveTimerS1Text",
            "ResolveTimerS1Delta",
            "ResolveTimerS2Text",
            "ResolveTimerS2Delta",
            "ResolveTimerLAPText",
            "ResolveTimerLAPDelta",
            "ResolveTimerBestText",
            "ResolveTimerOptimalText",
        ):
            self.assertEqual(comp.tools[name].inputs["UseFrameFormatSettings"], 0)
            self.assertEqual(comp.tools[name].inputs["Width"], OVERLAY_CANVAS_WIDTH)
            self.assertEqual(comp.tools[name].inputs["Height"], OVERLAY_CANVAS_HEIGHT)
        self.assertEqual(
            comp.tools["ResolveTimerSourceCanvasBackground"].inputs[
                "UseFrameFormatSettings"
            ],
            0,
        )
        self.assertEqual(
            comp.tools["ResolveTimerSourceCanvasBackground"].inputs["Width"],
            OVERLAY_CANVAS_WIDTH,
        )
        self.assertEqual(
            comp.tools["ResolveTimerSourceCanvasBackground"].inputs["Height"],
            OVERLAY_CANVAS_HEIGHT,
        )
        self.assertEqual(
            comp.tools["ResolveTimerSourceCanvasBackground"].inputs["TopLeftAlpha"],
            0.0,
        )
        self.assertIs(
            comp.tools["ResolveTimerSourceCanvasMerge"].connections["Background"],
            comp.tools["ResolveTimerSourceCanvasBackground"],
        )
        self.assertIs(
            comp.tools["ResolveTimerSourceCanvasMerge"].connections["Foreground"],
            comp.tools["MediaIn1"],
        )
        self.assertIs(
            comp.tools["ResolveTimerSourceTransform"].connections["Input"],
            comp.tools["ResolveTimerSourceCanvasMerge"],
        )
        self.assertIs(
            comp.tools["ResolveTimerPanelBlur"].connections["Input"],
            comp.tools["ResolveTimerSourceTransform"],
        )
        self.assertIs(
            comp.tools["ResolveTimerPanelBlurMerge"].connections["Background"],
            comp.tools["ResolveTimerSourceTransform"],
        )
        self.assertIs(
            comp.tools["ResolveTimerPanelBlurMerge"].connections["Foreground"],
            comp.tools["ResolveTimerPanelBlur"],
        )
        self.assertIs(
            comp.tools["ResolveTimerPanelBlurMerge"].connections["EffectMask"],
            comp.tools["ResolveTimerPanelMask"],
        )
        self.assertEqual(
            comp.tools["ResolveTimerPanelBlurMerge"].expressions["Blend"],
            "(time >= 0) and 1 or 0",
        )
        self.assertIs(
            comp.tools["ResolveTimerPanelMerge"].connections["Background"],
            comp.tools["ResolveTimerPanelBlurMerge"],
        )
        self.assertEqual(
            comp.tools["ResolveTimerPanelBlur"].inputs["XBlurSize"],
            12.0,
        )
        self.assertEqual(
            comp.tools["ResolveTimerPanelBorderMask"].inputs["Solid"],
            0,
        )
        self.assertEqual(
            comp.tools["ResolveTimerPanelBorderMask"].inputs["BorderWidth"],
            0.0015,
        )
        panel_mask = comp.tools["ResolveTimerPanelMask"].inputs
        self.assertAlmostEqual(panel_mask["Width"], 0.25)
        self.assertAlmostEqual(panel_mask["Height"], 0.2275)
        self.assertAlmostEqual(
            panel_mask["Center"][2] + (panel_mask["Height"] / 2),
            0.984,
        )
        self.assertAlmostEqual(
            panel_mask["Center"][1] + (panel_mask["Width"] / 2),
            0.991,
        )
        self.assertAlmostEqual(
            comp.tools["ResolveTimerText"].inputs["Size"],
            0.0245,
        )
        self.assertAlmostEqual(
            comp.tools["ResolveTimerText"].inputs["Center"][1],
            0.866,
        )
        self.assertAlmostEqual(
            comp.tools["ResolveTimerS1Text"].inputs["Center"][1],
            0.8345,
        )
        self.assertAlmostEqual(
            comp.tools["ResolveTimerS1Text"].inputs["Size"],
            0.0175,
        )
        self.assertEqual(
            comp.tools["ResolveTimerPanelBorderBackground"].inputs[
                "TopLeftRed"
            ],
            0.72,
        )
        self.assertEqual(
            comp.tools["ResolveTimerPanelBorderBackground"].inputs[
                "TopLeftGreen"
            ],
            0.72,
        )
        self.assertEqual(
            comp.tools["ResolveTimerPanelBorderBackground"].inputs[
                "TopLeftBlue"
            ],
            0.72,
        )
        self.assertEqual(comp.tools["ResolveTimerS1Text"].inputs["GlobalIn"], 100)
        self.assertEqual(comp.tools["ResolveTimerS2Text"].inputs["GlobalIn"], 300)
        self.assertEqual(comp.tools["ResolveTimerLAPText"].inputs["GlobalIn"], 300)
        self.assertEqual(
            comp.tools["ResolveTimerS1Delta"].inputs["Red1"],
            1.0,
        )
        self.assertEqual(
            comp.tools["ResolveTimerS1Delta"].inputs["Green1"],
            0.76,
        )
        self.assertEqual(result.fusion_start_frame, 0)
        self.assertEqual(result.fusion_finish_frame, 300)

    def test_fusion_updater_repositions_existing_generated_tools(self):
        payload = self._payload()
        timeline_item = FakeTimelineItem()
        updater = FusionOverlayUpdater()
        result = updater.update_or_create(timeline_item, payload)
        comp = timeline_item.comps[result.comp_name]
        comp.tools["ResolveTimerText"].attrs["TOOLS_XPos"] = -99
        comp.tools["ResolveTimerText"].attrs["TOOLS_YPos"] = -99
        comp.tools["ResolveTimerS1TextMerge"].attrs["TOOLS_XPos"] = -99
        comp.tools["ResolveTimerS1TextMerge"].attrs["TOOLS_YPos"] = -99

        updater.update_or_create(timeline_item, payload)

        self.assertEqual(comp.tools["ResolveTimerText"].attrs["TOOLS_XPos"], 4)
        self.assertEqual(comp.tools["ResolveTimerText"].attrs["TOOLS_YPos"], -1)
        self.assertEqual(comp.tools["ResolveTimerS1TextMerge"].attrs["TOOLS_XPos"], 7)
        self.assertEqual(comp.tools["ResolveTimerS1TextMerge"].attrs["TOOLS_YPos"], 1)

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

    def test_live_timer_expression_translates_source_frames_and_clamps_finish(self):
        payload = self._payload()

        expression = build_live_timer_expression(payload, source_start_frame=-25)

        self.assertIn("math.min(time, 325) - 25", expression)
        self.assertIn("math.max(0", expression)
        self.assertIn("string.format", expression)
        self.assertNotIn(r"\nS1", expression)

    def test_fusion_rows_reveal_at_sector_crossings_and_color_deltas(self):
        course = Course("course", "Course", 2)
        snapshot = parse_marker_snapshot(
            [RawMarker("Start", 20), RawMarker("S1", 120), RawMarker("Finish", 330)],
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
            sector_reference_seconds=(1.1, 2.0),
            best_lap_seconds=3.2,
            optimal_lap_seconds=3.1,
        )

        rows = build_fusion_overlay_rows(payload, source_start_frame=10)

        self.assertEqual([row.reveal_frame for row in rows], [110, 320, 320])
        self.assertEqual(rows[0].delta_text, "-0.100")
        self.assertEqual(rows[0].delta_color, (0.2, 1.0, 0.45, 1.0))
        self.assertEqual(rows[1].delta_text, "+0.100")
        self.assertEqual(rows[1].delta_color, (1.0, 0.3, 0.25, 1.0))

    def test_fusion_updater_rejects_markers_outside_timeline_source_range(self):
        payload = self._payload()
        timeline_item = FakeTimelineItem(source_start=50, source_end=400)

        with self.assertRaises(RuntimeError) as raised:
            FusionOverlayUpdater().update_or_create(timeline_item, payload)

        self.assertIn("Start marker 0 is before timeline source start 50", str(raised.exception))
        self.assertEqual(timeline_item.add_count, 0)

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
        self.attrs = {}
        self.inputs = {}
        self.expressions = {}
        self.input_objects = {"StyledText": FakeInput(self, "StyledText")}
        self.connections = {}
        self.comp = None

    def SetAttrs(self, attrs):
        self.attrs.update(attrs)
        if "TOOLS_Name" in attrs:
            old_name = self.name
            self.name = attrs["TOOLS_Name"]
            if self.comp is not None:
                self.comp.tools.pop(old_name, None)
                self.comp.tools[self.name] = self
        return True

    def SetInput(self, name, value):
        self.inputs[name] = value
        return True

    def FindInput(self, name):
        if name not in self.input_objects:
            self.input_objects[name] = FakeInput(self, name)
        return self.input_objects[name]

    def ConnectInput(self, name, source):
        self.connections[name] = source
        return True


class FakeInput:
    def __init__(self, tool, name):
        self.tool = tool
        self.name = name

    def SetExpression(self, expression):
        self.tool.expressions[self.name] = expression
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
    def __init__(self, source_start=0, source_end=300):
        self.names = []
        self.comps = {}
        self.add_count = 0
        self.source_start = source_start
        self.source_end = source_end

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

    def GetSourceStartFrame(self):
        return self.source_start

    def GetSourceEndFrame(self):
        return self.source_end


if __name__ == "__main__":
    unittest.main()
