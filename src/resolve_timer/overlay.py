from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
import json
from typing import Any

from .matching import marker_snapshot_hash
from .models import Course, MarkerSnapshot, TimingResult
from .timing import format_delta, format_duration


OVERLAY_CANVAS_WIDTH = 3840
OVERLAY_CANVAS_HEIGHT = 2160


@dataclass(frozen=True)
class OverlayPayload:
    course_id: str
    run_id: str | None
    start_frame: int
    finish_frame: int
    source_fps: float
    marker_frames: dict[str, int]
    sector_reference_seconds: tuple[float | None, ...]
    best_lap_seconds: float | None
    optimal_lap_seconds: float | None
    comparison_mode: str

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["generated_name"] = generated_overlay_name(self)
        data["final_text"] = format_final_overlay_text(self)
        data["rows"] = [
            {
                "label": row.label,
                "seconds": row.duration_seconds,
                "duration": format_duration(row.duration_seconds),
                "delta_seconds": row.delta_seconds,
                "delta": None if row.delta_seconds is None else format_delta(row.delta_seconds),
            }
            for row in final_overlay_rows(self)
        ]
        return data


def generated_overlay_name(payload: OverlayPayload) -> str:
    identity = payload.run_id or marker_snapshot_hash(payload.marker_frames)
    return f"{FusionOverlayUpdater.generated_name_prefix} - {payload.course_id} - {identity}"


@dataclass(frozen=True)
class OverlayTextRow:
    label: str
    duration_seconds: float
    delta_seconds: float | None


@dataclass(frozen=True)
class FusionOverlayRow:
    key: str
    value_text: str
    delta_text: str
    reveal_frame: int
    delta_color: tuple[float, float, float, float]


def final_overlay_rows(payload: OverlayPayload) -> tuple[OverlayTextRow, ...]:
    rows: list[OverlayTextRow] = []
    for sector in range(1, len(payload.sector_reference_seconds) + 1):
        start_marker = "Start" if sector == 1 else f"S{sector - 1}"
        end_marker = "Finish" if sector == len(payload.sector_reference_seconds) else f"S{sector}"
        duration_seconds = (
            payload.marker_frames[end_marker] - payload.marker_frames[start_marker]
        ) / payload.source_fps
        reference_seconds = payload.sector_reference_seconds[sector - 1]
        rows.append(
            OverlayTextRow(
                label=f"S{sector}",
                duration_seconds=duration_seconds,
                delta_seconds=_delta(duration_seconds, reference_seconds),
            )
        )
    lap_seconds = (payload.finish_frame - payload.start_frame) / payload.source_fps
    lap_reference = (
        payload.best_lap_seconds if payload.comparison_mode == "best_lap" else payload.optimal_lap_seconds
    )
    rows.append(OverlayTextRow("LAP", lap_seconds, _delta(lap_seconds, lap_reference)))
    return tuple(rows)


def format_final_overlay_text(payload: OverlayPayload) -> str:
    lines = [f"LIVE        {format_duration((payload.finish_frame - payload.start_frame) / payload.source_fps)}"]
    for row in final_overlay_rows(payload):
        delta = "--.---" if row.delta_seconds is None else format_delta(row.delta_seconds)
        lines.append(f"{row.label:<11} {format_duration(row.duration_seconds):>8}   {delta:>7}")
    if payload.best_lap_seconds is not None:
        lines.append(f"BEST        {format_duration(payload.best_lap_seconds)}")
    if payload.optimal_lap_seconds is not None:
        lines.append(f"OPTIMAL     {format_duration(payload.optimal_lap_seconds)}")
    return "\n".join(lines)


def build_live_timer_expression(
    payload: OverlayPayload,
    source_start_frame: int,
) -> str:
    start_frame, finish_frame = fusion_marker_range(payload, source_start_frame)
    elapsed = (
        f"(math.max(0, math.min(time, {finish_frame}) - {start_frame})"
        f" / {payload.source_fps:.12g})"
    )
    return (
        f"string.format({json.dumps('LIVE        %d:%06.3f')}, "
        f"math.floor({elapsed} / 60), math.fmod({elapsed}, 60))"
    )


def build_fusion_overlay_rows(
    payload: OverlayPayload,
    source_start_frame: int,
) -> tuple[FusionOverlayRow, ...]:
    rows = []
    timing_rows = final_overlay_rows(payload)
    sector_count = len(payload.sector_reference_seconds)
    for sector, timing_row in enumerate(timing_rows[:-1], start=1):
        end_marker = "Finish" if sector == sector_count else f"S{sector}"
        rows.append(
            FusionOverlayRow(
                key=f"S{sector}",
                value_text=f"S{sector:<10}{format_duration(timing_row.duration_seconds):>8}",
                delta_text=(
                    "--.---"
                    if timing_row.delta_seconds is None
                    else format_delta(timing_row.delta_seconds)
                ),
                reveal_frame=payload.marker_frames[end_marker] - source_start_frame,
                delta_color=_delta_color(timing_row.delta_seconds),
            )
        )
    lap_row = timing_rows[-1]
    rows.append(
        FusionOverlayRow(
            key="LAP",
            value_text=f"LAP        {format_duration(lap_row.duration_seconds):>8}",
            delta_text=(
                "--.---"
                if lap_row.delta_seconds is None
                else format_delta(lap_row.delta_seconds)
            ),
            reveal_frame=payload.finish_frame - source_start_frame,
            delta_color=_delta_color(lap_row.delta_seconds),
        )
    )
    return tuple(rows)


def fusion_marker_range(
    payload: OverlayPayload,
    source_start_frame: int,
) -> tuple[int, int]:
    return (
        payload.start_frame - source_start_frame,
        payload.finish_frame - source_start_frame,
    )


def _delta(duration_seconds: float, reference_seconds: float | None) -> float | None:
    if reference_seconds is None:
        return None
    return duration_seconds - reference_seconds


def _delta_color(
    delta_seconds: float | None,
) -> tuple[float, float, float, float]:
    if delta_seconds is None:
        return (0.72, 0.75, 0.8, 1.0)
    if delta_seconds < 0:
        return (0.2, 1.0, 0.45, 1.0)
    if delta_seconds > 0:
        return (1.0, 0.3, 0.25, 1.0)
    return (1.0, 0.76, 0.18, 1.0)


def build_overlay_payload(
    *,
    course: Course,
    snapshot: MarkerSnapshot,
    current_timing: TimingResult,
    comparison_mode: str,
    run_id: str | None,
    source_fps: float,
    sector_reference_seconds: tuple[float | None, ...],
    best_lap_seconds: float | None,
    optimal_lap_seconds: float | None,
) -> OverlayPayload:
    if comparison_mode not in {"best_lap", "optimal"}:
        raise ValueError("comparison_mode must be best_lap or optimal")
    if len(sector_reference_seconds) != course.sector_count:
        raise ValueError("sector_reference_seconds length must match course sector_count")
    if current_timing.lap_frames != snapshot.frames["Finish"] - snapshot.frames["Start"]:
        raise ValueError("current_timing does not match marker snapshot")
    return OverlayPayload(
        course_id=course.id,
        run_id=run_id,
        start_frame=snapshot.frames["Start"],
        finish_frame=snapshot.frames["Finish"],
        source_fps=source_fps,
        marker_frames=dict(snapshot.frames),
        sector_reference_seconds=sector_reference_seconds,
        best_lap_seconds=best_lap_seconds,
        optimal_lap_seconds=optimal_lap_seconds,
        comparison_mode=comparison_mode,
    )


class FusionOverlayUpdater:
    """Create or update the expression-driven overlay Fusion comp."""

    generated_name_prefix = "Resolve Timer"
    font_name = "JetBrains Mono"
    font_style = "Medium"
    text_tool_name = "ResolveTimerText"
    merge_tool_name = "ResolveTimerMerge"
    panel_blur_name = "ResolveTimerPanelBlur"
    panel_blur_merge_name = "ResolveTimerPanelBlurMerge"
    panel_background_name = "ResolveTimerPanelBackground"
    panel_mask_name = "ResolveTimerPanelMask"
    panel_merge_name = "ResolveTimerPanelMerge"
    panel_border_background_name = "ResolveTimerPanelBorderBackground"
    panel_border_mask_name = "ResolveTimerPanelBorderMask"
    panel_border_merge_name = "ResolveTimerPanelBorderMerge"

    def update_or_create(
        self,
        timeline_item: object,
        payload: OverlayPayload,
    ) -> "FusionOverlayUpdateResult":
        source_start_frame = int(
            _call_required(timeline_item, "GetSourceStartFrame")
        )
        source_end_frame = int(_call_required(timeline_item, "GetSourceEndFrame"))
        if payload.start_frame < source_start_frame:
            raise RuntimeError(
                f"Start marker {payload.start_frame} is before timeline source "
                f"start {source_start_frame}"
            )
        if payload.finish_frame > source_end_frame:
            raise RuntimeError(
                f"Finish marker {payload.finish_frame} is after timeline source "
                f"end {source_end_frame}"
            )

        comp_name = self.comp_name(payload.course_id)
        existing_names = _fusion_comp_names(timeline_item)
        created = comp_name not in existing_names
        if created:
            comp = _call_required(timeline_item, "AddFusionComp")
            new_names = _fusion_comp_names(timeline_item)
            added_name = _new_comp_name(existing_names, new_names, comp)
            if added_name != comp_name:
                rename = getattr(timeline_item, "RenameFusionCompByName", None)
                if not callable(rename) or not rename(added_name, comp_name):
                    raise RuntimeError(
                        f"could not rename Fusion comp {added_name!r} to {comp_name!r}"
                    )
                comp = _call_required(timeline_item, "GetFusionCompByName", comp_name)
        else:
            comp = _call_required(timeline_item, "GetFusionCompByName", comp_name)

        fusion_start_frame, fusion_finish_frame = fusion_marker_range(
            payload,
            source_start_frame,
        )
        live_expression = build_live_timer_expression(payload, source_start_frame)
        rows = build_fusion_overlay_rows(payload, source_start_frame)
        summaries = _summary_rows(payload)

        _call_optional(comp, "Lock")
        try:
            text = _find_or_add_tool(comp, self.text_tool_name, "TextPlus", 4, -1)
            merge = _find_or_add_tool(comp, self.merge_tool_name, "Merge", 7, -1)
            panel_background = _find_or_add_tool(
                comp,
                self.panel_background_name,
                "Background",
                1,
                0,
            )
            panel_blur = _find_or_add_tool(
                comp,
                self.panel_blur_name,
                "Blur",
                1,
                -1,
            )
            panel_blur_merge = _find_or_add_tool(
                comp,
                self.panel_blur_merge_name,
                "Merge",
                2,
                -1,
            )
            panel_mask = _find_or_add_tool(
                comp,
                self.panel_mask_name,
                "RectangleMask",
                0,
                0,
            )
            panel_merge = _find_or_add_tool(
                comp,
                self.panel_merge_name,
                "Merge",
                2,
                0,
            )
            panel_border_background = _find_or_add_tool(
                comp,
                self.panel_border_background_name,
                "Background",
                1,
                1,
            )
            panel_border_mask = _find_or_add_tool(
                comp,
                self.panel_border_mask_name,
                "RectangleMask",
                0,
                1,
            )
            panel_border_merge = _find_or_add_tool(
                comp,
                self.panel_border_merge_name,
                "Merge",
                3,
                0,
            )
            media_in = _find_required_tool(comp, ("MediaIn1", "MediaIn"))
            media_out = _find_required_tool(comp, ("MediaOut1", "MediaOut"))
            _set_tool_position(media_in, 0, 0)
            _set_tool_position(media_out, 10, 0)

            layout_scale = 0.7
            panel_top_margin = 0.016
            panel_right_margin = panel_top_margin * (9 / 16)
            panel_width = 0.25
            panel_padding_y = 0.025 * layout_scale
            panel_right = 1.0 - panel_right_margin
            panel_center_x = panel_right - (panel_width / 2)
            top_y = 1.0 - panel_top_margin - panel_padding_y
            live_text_x = panel_center_x
            primary_text_x = panel_center_x - (0.045 * layout_scale)
            delta_text_x = panel_center_x + (0.09 * layout_scale)
            row_gap = 0.055 * layout_scale
            total_rows = 1 + len(rows) + len(summaries)
            bottom_y = top_y - ((total_rows - 1) * row_gap)
            panel_height = min(
                0.82,
                (top_y - bottom_y) + (panel_padding_y * 2),
            )
            panel_center_y = (top_y + bottom_y) / 2

            _configure_panel(
                panel_background,
                panel_mask,
                panel_blur,
                panel_border_background,
                panel_border_mask,
                fusion_start_frame,
                center_x=panel_center_x,
                center_y=panel_center_y,
                width=panel_width,
                height=panel_height,
            )
            _connect_input(panel_blur, "Input", media_in)
            _connect_input(panel_blur_merge, "Background", media_in)
            _connect_input(panel_blur_merge, "Foreground", panel_blur)
            _connect_input(panel_blur_merge, "EffectMask", panel_mask)
            _set_expression(
                panel_blur_merge,
                "Blend",
                f"(time >= {fusion_start_frame}) and 1 or 0",
            )
            _connect_input(panel_background, "EffectMask", panel_mask)
            _connect_input(panel_merge, "Background", panel_blur_merge)
            _connect_input(panel_merge, "Foreground", panel_background)
            _connect_input(
                panel_border_background,
                "EffectMask",
                panel_border_mask,
            )
            _connect_input(panel_border_merge, "Background", panel_merge)
            _connect_input(
                panel_border_merge,
                "Foreground",
                panel_border_background,
            )

            _configure_text(
                text,
                text=None,
                x=live_text_x,
                y=top_y,
                start_frame=fusion_start_frame,
                size=0.035 * layout_scale,
                color=(1.0, 1.0, 1.0, 1.0),
            )
            _set_expression(text, "StyledText", live_expression)
            _connect_input(merge, "Background", panel_border_merge)
            _connect_input(merge, "Foreground", text)

            output = merge
            for index, row in enumerate(rows, start=1):
                y = top_y - (index * row_gap)
                graph_y = index
                row_text = _find_or_add_tool(
                    comp,
                    f"ResolveTimer{row.key}Text",
                    "TextPlus",
                    4,
                    graph_y,
                )
                row_delta = _find_or_add_tool(
                    comp,
                    f"ResolveTimer{row.key}Delta",
                    "TextPlus",
                    5,
                    graph_y,
                )
                row_merge = _find_or_add_tool(
                    comp,
                    f"ResolveTimer{row.key}TextMerge",
                    "Merge",
                    7,
                    graph_y,
                )
                delta_merge = _find_or_add_tool(
                    comp,
                    f"ResolveTimer{row.key}DeltaMerge",
                    "Merge",
                    8,
                    graph_y,
                )
                _configure_text(
                    row_text,
                    text=row.value_text,
                    x=primary_text_x,
                    y=y,
                    start_frame=row.reveal_frame,
                    size=0.025 * layout_scale,
                    color=(1.0, 1.0, 1.0, 1.0),
                )
                _configure_text(
                    row_delta,
                    text=row.delta_text,
                    x=delta_text_x,
                    y=y,
                    start_frame=row.reveal_frame,
                    size=0.025 * layout_scale,
                    color=row.delta_color,
                )
                _connect_input(row_merge, "Background", output)
                _connect_input(row_merge, "Foreground", row_text)
                _connect_input(delta_merge, "Background", row_merge)
                _connect_input(delta_merge, "Foreground", row_delta)
                output = delta_merge

            for summary_index, (key, summary_text) in enumerate(summaries):
                y = top_y - ((1 + len(rows) + summary_index) * row_gap)
                graph_y = len(rows) + summary_index + 1
                summary_tool = _find_or_add_tool(
                    comp,
                    f"ResolveTimer{key}Text",
                    "TextPlus",
                    4,
                    graph_y,
                )
                summary_merge = _find_or_add_tool(
                    comp,
                    f"ResolveTimer{key}Merge",
                    "Merge",
                    7,
                    graph_y,
                )
                _configure_text(
                    summary_tool,
                    text=summary_text,
                    x=primary_text_x,
                    y=y,
                    start_frame=fusion_start_frame,
                    size=0.024 * layout_scale,
                    color=(1.0, 0.76, 0.18, 1.0),
                )
                _connect_input(summary_merge, "Background", output)
                _connect_input(summary_merge, "Foreground", summary_tool)
                output = summary_merge

            _set_input(media_out, "ColorGrade", "Color")
            _connect_input(media_out, "Input", output)
        finally:
            _call_optional(comp, "Unlock")

        return FusionOverlayUpdateResult(
            comp_name=comp_name,
            created=created,
            text_tool_name=self.text_tool_name,
            merge_tool_name=self.merge_tool_name,
            final_text=format_final_overlay_text(payload),
            live_expression=live_expression,
            fusion_start_frame=fusion_start_frame,
            fusion_finish_frame=fusion_finish_frame,
        )

    @classmethod
    def comp_name(cls, course_id: str) -> str:
        return f"{cls.generated_name_prefix} - {course_id}"


@dataclass(frozen=True)
class FusionOverlayUpdateResult:
    comp_name: str
    created: bool
    text_tool_name: str
    merge_tool_name: str
    final_text: str
    live_expression: str
    fusion_start_frame: int
    fusion_finish_frame: int


def _summary_rows(payload: OverlayPayload) -> tuple[tuple[str, str], ...]:
    rows = []
    if payload.best_lap_seconds is not None:
        rows.append(("Best", f"BEST       {format_duration(payload.best_lap_seconds):>8}"))
    if payload.optimal_lap_seconds is not None:
        rows.append(
            ("Optimal", f"OPTIMAL    {format_duration(payload.optimal_lap_seconds):>8}")
        )
    return tuple(rows)


def _configure_panel(
    background: object,
    mask: object,
    blur: object,
    border_background: object,
    border_mask: object,
    start_frame: int,
    *,
    center_x: float,
    center_y: float,
    width: float,
    height: float,
) -> None:
    _set_input(background, "GlobalIn", start_frame)
    _configure_background_canvas(background)
    _set_input(background, "TopLeftRed", 0.04)
    _set_input(background, "TopLeftGreen", 0.055)
    _set_input(background, "TopLeftBlue", 0.08)
    _set_input(background, "TopLeftAlpha", 0.52)
    _set_input(blur, "Filter", "Fast Gaussian")
    _set_input(blur, "XBlurSize", 12.0)
    _set_input(blur, "YBlurSize", 12.0)
    _set_input(mask, "GlobalIn", start_frame)
    _set_input(mask, "Center", {1: center_x, 2: center_y})
    _set_input(mask, "Width", width)
    _set_input(mask, "Height", height)
    _set_input(mask, "CornerRadius", 0.035)
    _set_input(border_background, "GlobalIn", start_frame)
    _configure_background_canvas(border_background)
    _set_input(border_background, "TopLeftRed", 0.72)
    _set_input(border_background, "TopLeftGreen", 0.72)
    _set_input(border_background, "TopLeftBlue", 0.72)
    _set_input(border_background, "TopLeftAlpha", 0.55)
    _set_input(border_mask, "GlobalIn", start_frame)
    _set_input(border_mask, "Center", {1: center_x, 2: center_y})
    _set_input(border_mask, "Width", width)
    _set_input(border_mask, "Height", height)
    _set_input(border_mask, "CornerRadius", 0.035)
    _set_input(border_mask, "Solid", 0)
    _set_input(border_mask, "BorderWidth", 0.0015)


def _configure_text(
    tool: object,
    *,
    text: str | None,
    x: float,
    y: float,
    start_frame: int,
    size: float,
    color: tuple[float, float, float, float],
) -> None:
    _set_input(tool, "Font", FusionOverlayUpdater.font_name)
    _set_input(tool, "Style", FusionOverlayUpdater.font_style)
    _set_input(tool, "Width", OVERLAY_CANVAS_WIDTH)
    _set_input(tool, "Height", OVERLAY_CANVAS_HEIGHT)
    _set_input(tool, "Size", size)
    _set_input(tool, "Center", {1: x, 2: y})
    _set_input(tool, "GlobalIn", start_frame)
    _set_input(tool, "Red1", color[0])
    _set_input(tool, "Green1", color[1])
    _set_input(tool, "Blue1", color[2])
    _set_input(tool, "Alpha1", color[3])
    if text is not None:
        _set_input(tool, "StyledText", text)


def _configure_background_canvas(tool: object) -> None:
    _set_input(tool, "UseFrameFormatSettings", 0)
    _set_input(tool, "Width", OVERLAY_CANVAS_WIDTH)
    _set_input(tool, "Height", OVERLAY_CANVAS_HEIGHT)


def _fusion_comp_names(timeline_item: object) -> tuple[str, ...]:
    method = getattr(timeline_item, "GetFusionCompNameList", None)
    if not callable(method):
        raise RuntimeError("timeline item does not expose GetFusionCompNameList")
    names = method()
    if names is None:
        return ()
    if isinstance(names, dict):
        values = names.values()
    elif isinstance(names, (list, tuple)):
        values = names
    else:
        raise RuntimeError("GetFusionCompNameList returned an unexpected value")
    return tuple(str(name) for name in values)


def _new_comp_name(
    existing_names: tuple[str, ...],
    new_names: tuple[str, ...],
    comp: object,
) -> str:
    added = [name for name in new_names if name not in existing_names]
    if len(added) == 1:
        return added[0]
    attrs = _call_optional(comp, "GetAttrs")
    if isinstance(attrs, dict) and attrs.get("COMPS_Name"):
        return str(attrs["COMPS_Name"])
    raise RuntimeError("could not identify the newly added Fusion comp")


def _find_or_add_tool(
    comp: object,
    name: str,
    tool_type: str,
    x: int,
    y: int,
) -> object:
    tool = _call_optional(comp, "FindTool", name)
    if tool is not None:
        _set_tool_position(tool, x, y)
        return tool
    add_tool = getattr(comp, "AddTool", None)
    if not callable(add_tool):
        raise RuntimeError("Fusion comp does not expose AddTool")
    tool = add_tool(tool_type, x, y)
    if tool is None:
        raise RuntimeError(f"Fusion could not add {tool_type}")
    set_attrs = getattr(tool, "SetAttrs", None)
    if not callable(set_attrs):
        raise RuntimeError(f"Fusion could not name {tool_type} tool {name}")
    if set_attrs({"TOOLS_Name": name}) is False:
        raise RuntimeError(f"Fusion could not name {tool_type} tool {name}")
    _set_tool_position(tool, x, y)
    return tool


def _set_tool_position(tool: object, x: int, y: int) -> None:
    set_attrs = getattr(tool, "SetAttrs", None)
    if not callable(set_attrs):
        return
    if set_attrs({"TOOLS_XPos": x, "TOOLS_YPos": y}) is False:
        raise RuntimeError(f"Fusion could not position tool at {x}, {y}")


def _find_required_tool(comp: object, names: tuple[str, ...]) -> object:
    for name in names:
        tool = _call_optional(comp, "FindTool", name)
        if tool is not None:
            return tool
    raise RuntimeError(f"Fusion comp is missing required tool: {' or '.join(names)}")


def _set_input(tool: object, name: str, value: Any) -> None:
    method = getattr(tool, "SetInput", None)
    if not callable(method):
        raise RuntimeError(f"Fusion tool does not expose SetInput for {name}")
    result = method(name, value)
    if result is False:
        raise RuntimeError(f"Fusion rejected input {name}")


def _set_expression(tool: object, name: str, expression: str) -> None:
    method = getattr(tool, "SetExpression", None)
    if callable(method):
        if method(name, expression) is False:
            raise RuntimeError(f"Fusion rejected expression for {name}")
        return

    input_value = _call_optional(tool, "FindInput", name)
    if input_value is None:
        input_value = getattr(tool, name, None)
    input_method = getattr(input_value, "SetExpression", None)
    if not callable(input_method):
        raise RuntimeError(
            f"Fusion input {name} does not expose SetExpression"
        )
    if input_method(expression) is False:
        raise RuntimeError(f"Fusion rejected expression for {name}")


def _connect_input(tool: object, name: str, source: object) -> None:
    method = getattr(tool, "ConnectInput", None)
    if not callable(method):
        raise RuntimeError(f"Fusion tool does not expose ConnectInput for {name}")
    if method(name, source) is False:
        raise RuntimeError(f"Fusion could not connect input {name}")


def _call_required(target: object, method_name: str, *args: Any) -> Any:
    method = getattr(target, method_name, None)
    if not callable(method):
        raise RuntimeError(f"object does not expose {method_name}")
    value = method(*args)
    if value is None:
        raise RuntimeError(f"{method_name} returned nothing")
    return value


def _call_optional(target: object, method_name: str, *args: Any) -> Any:
    method = getattr(target, method_name, None)
    if not callable(method):
        return None
    return method(*args)
