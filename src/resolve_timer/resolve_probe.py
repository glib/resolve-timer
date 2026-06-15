from __future__ import annotations

import json
import platform
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .resolve_adapter import ResolveAdapter, ResolveAdapterError


@dataclass(frozen=True)
class ResolveProbeResult:
    python_version: str
    python_implementation: str
    python_executable: str
    resolve_version: str | None
    project_name: str | None
    timeline_name: str | None
    timeline_item_name: str | None
    timeline_item_start: str | None
    timeline_item_end: str | None
    timeline_item_source_start: str | None
    timeline_item_source_end: str | None
    source_clip_name: str | None
    source_clip_id: str | None
    selected_media_pool_clip_names: tuple[str, ...]
    selected_media_pool_clip_ids: tuple[str, ...]
    selected_media_pool_marker_names: tuple[str, ...]
    timeline_marker_keys: tuple[str, ...]
    timeline_marker_names: tuple[str, ...]
    marker_keys: tuple[str, ...]
    marker_names: tuple[str, ...]
    marker_payload_keys: tuple[str, ...]
    clip_property_keys: tuple[str, ...]
    fps_value: str | None
    selected_filename: str | None
    selected_source_fps: float | None
    selected_marker_count: int | None
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def probe_resolve(resolve: object | None = None) -> ResolveProbeResult:
    adapter = ResolveAdapter(resolve)
    resolve_obj = adapter.resolve
    try:
        project_manager = _call_optional(resolve_obj, "GetProjectManager")
        project = _call_optional(project_manager, "GetCurrentProject") if project_manager else None
        timeline = _call_optional(project, "GetCurrentTimeline") if project else None
        timeline_item = _call_optional(timeline, "GetCurrentVideoItem") if timeline else None
        source_clip = _call_optional(timeline_item, "GetMediaPoolItem") if timeline_item else None
        media_pool = _call_optional(project, "GetMediaPool") if project else None
        selected_media_clips = _call_optional(media_pool, "GetSelectedClips") if media_pool else None
        timeline_marker_map = _call_optional(timeline_item, "GetMarkers") if timeline_item else None
        marker_map = _call_optional(source_clip, "GetMarkers") if source_clip else None
        properties = _call_optional(source_clip, "GetClipProperty") if source_clip else None
        selected = adapter.selected_media_pool_run()
        return ResolveProbeResult(
            python_version=platform.python_version(),
            python_implementation=platform.python_implementation(),
            python_executable=sys.executable,
            resolve_version=_string_or_none(_call_optional(resolve_obj, "GetVersionString")),
            project_name=_string_or_none(_call_optional(project, "GetName")),
            timeline_name=_string_or_none(_call_optional(timeline, "GetName")),
            timeline_item_name=_string_or_none(_call_optional(timeline_item, "GetName")),
            timeline_item_start=_string_or_none(_call_optional(timeline_item, "GetStart")),
            timeline_item_end=_string_or_none(_call_optional(timeline_item, "GetEnd")),
            timeline_item_source_start=_string_or_none(_call_optional(timeline_item, "GetSourceStartFrame")),
            timeline_item_source_end=_string_or_none(_call_optional(timeline_item, "GetSourceEndFrame")),
            source_clip_name=_string_or_none(_call_optional(source_clip, "GetName")),
            source_clip_id=_string_or_none(_call_optional(source_clip, "GetUniqueId")),
            selected_media_pool_clip_names=_clip_values(selected_media_clips, "GetName"),
            selected_media_pool_clip_ids=_clip_values(selected_media_clips, "GetUniqueId"),
            selected_media_pool_marker_names=_selected_clip_marker_names(selected_media_clips),
            timeline_marker_keys=_dict_keys(timeline_marker_map),
            timeline_marker_names=_marker_names(timeline_marker_map),
            marker_keys=_dict_keys(marker_map),
            marker_names=_marker_names(marker_map),
            marker_payload_keys=_first_payload_keys(marker_map),
            clip_property_keys=_dict_keys(properties),
            fps_value=_fps_property(properties),
            selected_filename=selected.filename,
            selected_source_fps=selected.source_fps,
            selected_marker_count=len(selected.source_markers),
        )
    except ResolveAdapterError as exc:
        return ResolveProbeResult(
            python_version=platform.python_version(),
            python_implementation=platform.python_implementation(),
            python_executable=sys.executable,
            resolve_version=_string_or_none(_call_optional(resolve_obj, "GetVersionString")),
            project_name=None,
            timeline_name=None,
            timeline_item_name=None,
            timeline_item_start=None,
            timeline_item_end=None,
            timeline_item_source_start=None,
            timeline_item_source_end=None,
            source_clip_name=None,
            source_clip_id=None,
            selected_media_pool_clip_names=(),
            selected_media_pool_clip_ids=(),
            selected_media_pool_marker_names=(),
            timeline_marker_keys=(),
            timeline_marker_names=(),
            marker_keys=(),
            marker_names=(),
            marker_payload_keys=(),
            clip_property_keys=(),
            fps_value=None,
            selected_filename=None,
            selected_source_fps=None,
            selected_marker_count=None,
            error=str(exc),
        )


def save_probe_result(result: ResolveProbeResult, path: str | Path) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True), encoding="utf-8")


def _call_optional(target: object | None, method_name: str) -> Any:
    if target is None:
        return None
    method = getattr(target, method_name, None)
    if not callable(method):
        return None
    return method()


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _dict_keys(value: Any) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(str(key) for key in value.keys())


def _first_payload_keys(marker_map: Any) -> tuple[str, ...]:
    if not isinstance(marker_map, dict):
        return ()
    for value in marker_map.values():
        if isinstance(value, dict):
            return tuple(str(key) for key in value.keys())
    return ()


def _marker_names(marker_map: Any) -> tuple[str, ...]:
    if not isinstance(marker_map, dict):
        return ()
    names = []
    for value in marker_map.values():
        if not isinstance(value, dict):
            continue
        name = value.get("name") or value.get("Name")
        if name:
            names.append(str(name))
    return tuple(names)


def _fps_property(properties: Any) -> str | None:
    if not isinstance(properties, dict):
        return None
    for key in ("FPS", "Frame Rate", "FrameRate", "fps"):
        value = properties.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _clip_values(clips: Any, method_name: str) -> tuple[str, ...]:
    if not isinstance(clips, (list, tuple)):
        return ()
    values = []
    for clip in clips:
        value = _call_optional(clip, method_name)
        if value not in (None, ""):
            values.append(str(value))
    return tuple(values)


def _selected_clip_marker_names(clips: Any) -> tuple[str, ...]:
    if not isinstance(clips, (list, tuple)):
        return ()
    names = []
    for clip in clips:
        names.extend(_marker_names(_call_optional(clip, "GetMarkers")))
    return tuple(names)
