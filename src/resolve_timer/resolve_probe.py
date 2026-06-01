from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .resolve_adapter import ResolveAdapter, ResolveAdapterError


@dataclass(frozen=True)
class ResolveProbeResult:
    resolve_version: str | None
    project_name: str | None
    timeline_name: str | None
    timeline_item_name: str | None
    source_clip_name: str | None
    source_clip_id: str | None
    marker_keys: tuple[str, ...]
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
        marker_map = _call_optional(source_clip, "GetMarkers") if source_clip else None
        properties = _call_optional(source_clip, "GetClipProperty") if source_clip else None
        selected = adapter.selected_timeline_run()
        return ResolveProbeResult(
            resolve_version=_string_or_none(_call_optional(resolve_obj, "GetVersionString")),
            project_name=_string_or_none(_call_optional(project, "GetName")),
            timeline_name=_string_or_none(_call_optional(timeline, "GetName")),
            timeline_item_name=_string_or_none(_call_optional(timeline_item, "GetName")),
            source_clip_name=_string_or_none(_call_optional(source_clip, "GetName")),
            source_clip_id=_string_or_none(_call_optional(source_clip, "GetUniqueId")),
            marker_keys=_dict_keys(marker_map),
            marker_payload_keys=_first_payload_keys(marker_map),
            clip_property_keys=_dict_keys(properties),
            fps_value=_fps_property(properties),
            selected_filename=selected.filename,
            selected_source_fps=selected.source_fps,
            selected_marker_count=len(selected.source_markers),
        )
    except ResolveAdapterError as exc:
        return ResolveProbeResult(
            resolve_version=_string_or_none(_call_optional(resolve_obj, "GetVersionString")),
            project_name=None,
            timeline_name=None,
            timeline_item_name=None,
            source_clip_name=None,
            source_clip_id=None,
            marker_keys=(),
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


def _fps_property(properties: Any) -> str | None:
    if not isinstance(properties, dict):
        return None
    for key in ("FPS", "Frame Rate", "FrameRate", "fps"):
        value = properties.get(key)
        if value not in (None, ""):
            return str(value)
    return None
