from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .overlay import FusionOverlayUpdater, final_overlay_rows
from .resolve_adapter import ResolveAdapter
from .runtime_support import PreferencesError, load_preferences
from .service import SelectedRunInput, TimerService


@dataclass(frozen=True)
class FusionProbeResult:
    success: bool
    error: str | None
    timeline_name: str | None
    timeline_item_name: str | None
    timeline_source_start: int | None
    timeline_source_end: int | None
    selected_clip_name: str | None
    selected_clip_id: str | None
    timeline_clip_id: str | None
    course_id: str | None
    comparison_mode: str | None
    comp_name: str | None
    comp_created: bool | None
    comp_count_before: int | None
    comp_count_after: int | None
    final_text: str | None
    media_out_inputs: dict[str, object] | None
    live_text_samples: dict[str, object] | None
    matching_run_id: str | None
    matching_run_ignored: bool | None
    best_lap_run_id: str | None
    best_lap_seconds: float | None
    lap_delta_seconds: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def run_fusion_probe(
    *,
    database_path: str | Path,
    resolve: object | None = None,
    preferences_path: str | Path | None = None,
    export_path: str | Path | None = None,
    use_current_timeline_item: bool = False,
) -> FusionProbeResult:
    timeline_name = None
    timeline_item_name = None
    timeline_source_start = None
    timeline_source_end = None
    selected_clip_name = None
    selected_clip_id = None
    timeline_clip_id = None
    course_id = None
    comparison_mode = None
    comp_count_before = None
    matching_run_id = None
    matching_run_ignored = None
    best_lap_run_id = None
    best_lap_seconds = None
    lap_delta_seconds = None
    try:
        database_path = Path(database_path)
        preferences_path = (
            Path(preferences_path)
            if preferences_path is not None
            else database_path.with_name("resolve_timer_preferences.json")
        )
        service = TimerService.load(database_path)
        if not service.database.courses:
            raise RuntimeError("timer database has no courses")

        try:
            preferences = load_preferences(preferences_path)
        except PreferencesError:
            preferences = None
        valid_course_ids = {course.id for course in service.database.courses}
        course_id = (
            preferences.course_id
            if preferences is not None and preferences.course_id in valid_course_ids
            else service.database.courses[0].id
        )
        comparison_mode = (
            preferences.comparison_mode if preferences is not None else "best_lap"
        )

        adapter = ResolveAdapter(resolve)
        project_manager = _call_required(adapter.resolve, "GetProjectManager")
        project = _call_required(project_manager, "GetCurrentProject")
        timeline = _call_required(project, "GetCurrentTimeline")
        timeline_name = _optional_text(_call_optional(timeline, "GetName"))
        timeline_item = _call_required(timeline, "GetCurrentVideoItem")
        timeline_item_name = _optional_text(_call_optional(timeline_item, "GetName"))
        timeline_source_start = int(
            _call_required(timeline_item, "GetSourceStartFrame")
        )
        timeline_source_end = int(
            _call_required(timeline_item, "GetSourceEndFrame")
        )
        timeline_media = _call_required(timeline_item, "GetMediaPoolItem")
        timeline_clip_id = _optional_text(_call_optional(timeline_media, "GetUniqueId"))
        if use_current_timeline_item:
            selected = adapter.media_pool_run(timeline_media)
        else:
            selected = adapter.selected_media_pool_run()
            timeline_item = adapter.matching_current_timeline_video_item(selected)
        selected_clip_name = selected.filename
        selected_clip_id = selected.clip_id

        comp_count_before = int(_call_required(timeline_item, "GetFusionCompCount"))
        selected_input = SelectedRunInput(
            course_id=course_id,
            filename=selected.filename,
            source_fps=selected.source_fps,
            markers=selected.source_markers,
            clip_id=selected.clip_id,
        )
        preview = service.preview(selected_input)
        matching_run_id = None if preview.matching_run is None else preview.matching_run.id
        matching_run_ignored = (
            None if preview.matching_run is None else preview.matching_run.ignored
        )
        best_lap_run_id = (
            None if preview.stats.best_lap is None else preview.stats.best_lap.run.id
        )
        best_lap_seconds = (
            None
            if preview.stats.best_lap is None
            else preview.stats.best_lap.timing.lap_seconds
        )
        payload = service.overlay_payload(selected_input, comparison_mode=comparison_mode)
        lap_delta_seconds = final_overlay_rows(payload)[-1].delta_seconds
        update = FusionOverlayUpdater().update_or_create(timeline_item, payload)
        comp_count_after = int(_call_required(timeline_item, "GetFusionCompCount"))
        if export_path is not None:
            comp_names = _call_required(timeline_item, "GetFusionCompNameList")
            comp_index = list(comp_names).index(update.comp_name) + 1
            exported = _call_required(
                timeline_item,
                "ExportFusionComp",
                str(Path(export_path)),
                comp_index,
            )
            if exported is False:
                raise RuntimeError("Resolve could not export the Fusion probe comp")
        return FusionProbeResult(
            success=True,
            error=None,
            timeline_name=timeline_name,
            timeline_item_name=timeline_item_name,
            timeline_source_start=timeline_source_start,
            timeline_source_end=timeline_source_end,
            selected_clip_name=selected_clip_name,
            selected_clip_id=selected_clip_id,
            timeline_clip_id=timeline_clip_id,
            course_id=course_id,
            comparison_mode=comparison_mode,
            comp_name=update.comp_name,
            comp_created=update.created,
            comp_count_before=comp_count_before,
            comp_count_after=comp_count_after,
            final_text=update.final_text,
            media_out_inputs=_tool_input_values(
                _call_optional(
                    _call_required(timeline_item, "GetFusionCompByName", update.comp_name),
                    "FindTool",
                    "MediaOut1",
                )
            ),
            live_text_samples=_live_text_samples(
                _call_required(timeline_item, "GetFusionCompByName", update.comp_name),
                update.fusion_start_frame,
                update.fusion_finish_frame,
            ),
            matching_run_id=matching_run_id,
            matching_run_ignored=matching_run_ignored,
            best_lap_run_id=best_lap_run_id,
            best_lap_seconds=best_lap_seconds,
            lap_delta_seconds=lap_delta_seconds,
        )
    except Exception as exc:
        return FusionProbeResult(
            success=False,
            error=str(exc),
            timeline_name=timeline_name,
            timeline_item_name=timeline_item_name,
            timeline_source_start=timeline_source_start,
            timeline_source_end=timeline_source_end,
            selected_clip_name=selected_clip_name,
            selected_clip_id=selected_clip_id,
            timeline_clip_id=timeline_clip_id,
            course_id=course_id,
            comparison_mode=comparison_mode,
            comp_name=None,
            comp_created=None,
            comp_count_before=comp_count_before,
            comp_count_after=None,
            final_text=None,
            media_out_inputs=None,
            live_text_samples=None,
            matching_run_id=matching_run_id,
            matching_run_ignored=matching_run_ignored,
            best_lap_run_id=best_lap_run_id,
            best_lap_seconds=best_lap_seconds,
            lap_delta_seconds=lap_delta_seconds,
        )


def save_fusion_probe_result(
    result: FusionProbeResult,
    path: str | Path,
) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _call_required(target: object, method_name: str, *args: Any) -> Any:
    method = getattr(target, method_name, None)
    if not callable(method):
        raise RuntimeError(f"Resolve object is missing {method_name}")
    value = method(*args)
    if value is None:
        raise RuntimeError(f"Resolve {method_name} returned nothing")
    return value


def _call_optional(target: object, method_name: str, *args: Any) -> Any:
    if target is None:
        return None
    method = getattr(target, method_name, None)
    if not callable(method):
        return None
    return method(*args)


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _tool_input_values(tool: object | None) -> dict[str, object]:
    if tool is None:
        return {}
    input_list = _call_optional(tool, "GetInputList")
    if not isinstance(input_list, dict):
        return {}
    values = {}
    for key, input_value in input_list.items():
        input_id = _input_id(key, input_value)
        if input_id is None:
            continue
        values[input_id] = _json_value(
            _call_optional(tool, "GetInput", input_id)
        )
    return values


def _input_id(key: object, input_value: object) -> str | None:
    attrs = _call_optional(input_value, "GetAttrs")
    if isinstance(attrs, dict) and attrs.get("INPS_ID"):
        return str(attrs["INPS_ID"])
    if isinstance(key, str):
        return key
    return None


def _json_value(value: Any) -> object:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _live_text_samples(
    comp: object,
    start_frame: int,
    finish_frame: int,
) -> dict[str, object]:
    text = _call_optional(comp, "FindTool", "ResolveTimerText")
    if text is None:
        return {}
    midpoint = start_frame + ((finish_frame - start_frame) // 2)
    frames = {
        "start": start_frame,
        "middle": midpoint,
        "finish": finish_frame,
        "after_finish": finish_frame + 1,
    }
    return {
        label: _json_value(
            _call_optional(text, "GetInput", "StyledText", frame)
        )
        for label, frame in frames.items()
    }
