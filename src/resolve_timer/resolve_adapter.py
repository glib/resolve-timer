from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .capture_time import (
    FILENAME_CAPTURE_TIME_SOURCE,
    FILESYSTEM_CREATED_SOURCE,
    filename_capture_time,
    filesystem_created_time,
)
from .models import RawMarker


class ResolveAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class SelectedMediaPoolRun:
    source_clip: object
    filename: str
    source_fps: float
    source_markers: tuple[RawMarker, ...]
    marker_source: str
    clip_id: str | None = None
    capture_time: str | None = None
    capture_time_source: str | None = None
    source_path: str | None = None


class ResolveAdapter:
    """Boundary for Resolve scripting API calls.

    The exact selected-item, source-marker, and Fusion update APIs need live
    Resolve validation. Keep all direct Resolve API use behind this class.
    """

    def __init__(self, resolve: object | None = None):
        self.resolve = resolve or self._discover_resolve()

    def selected_media_pool_run(self) -> SelectedMediaPoolRun:
        project_manager = _call_required(self.resolve, "GetProjectManager")
        project = _call_required(project_manager, "GetCurrentProject")
        media_pool = _call_required(project, "GetMediaPool")
        selected_clips = _call_required(media_pool, "GetSelectedClips")
        if not isinstance(selected_clips, (list, tuple)):
            raise ResolveAdapterError("Resolve GetSelectedClips did not return a list")
        if len(selected_clips) != 1:
            raise ResolveAdapterError(
                f"Select exactly one Media Pool clip; Resolve reports {len(selected_clips)} selected"
            )
        return self.media_pool_run(selected_clips[0])

    def media_pool_run(self, source_clip: object) -> SelectedMediaPoolRun:
        source_marker_map = _call_required(source_clip, "GetMarkers")
        if not isinstance(source_marker_map, dict):
            raise ResolveAdapterError("source clip markers are not a dictionary")
        properties = _call_required(source_clip, "GetClipProperty")
        if not isinstance(properties, dict):
            raise ResolveAdapterError("source clip properties are not a dictionary")
        filename = _first_property(properties, ("File Name", "Filename", "Name"))
        if filename is None:
            filename = str(_call_optional(source_clip, "GetName") or "")
        if not filename:
            raise ResolveAdapterError("source clip filename property not found")
        clip_id = _optional_text(_call_optional(source_clip, "GetUniqueId"))
        source_path = _source_path_from_properties(properties, filename)
        capture_time = filename_capture_time(filename)
        capture_time_source = (
            FILENAME_CAPTURE_TIME_SOURCE if capture_time is not None else None
        )
        if capture_time is None and source_path:
            try:
                capture_time = filesystem_created_time(source_path)
                capture_time_source = FILESYSTEM_CREATED_SOURCE
            except OSError:
                capture_time = None
                capture_time_source = None
        return SelectedMediaPoolRun(
            source_clip=source_clip,
            filename=filename,
            source_fps=self.source_fps_from_properties(properties),
            source_markers=self.markers_from_resolve_map(source_marker_map),
            marker_source="source_clip",
            clip_id=clip_id,
            capture_time=capture_time,
            capture_time_source=capture_time_source,
            source_path=source_path,
        )

    def current_timeline_video_item(self) -> object:
        timeline = self._current_timeline()
        return _call_required(timeline, "GetCurrentVideoItem")

    def timeline_item_media_pool_run(
        self,
        timeline_item: object,
    ) -> SelectedMediaPoolRun:
        source_clip = _call_required(timeline_item, "GetMediaPoolItem")
        return self.media_pool_run(source_clip)

    def timeline_video_items(self) -> tuple[object, ...]:
        project = self._current_project()
        timeline = _call_existing(project, "GetCurrentTimeline")
        if timeline is None:
            return ()
        track_count = _call_required(timeline, "GetTrackCount", "video")
        try:
            video_track_count = int(track_count)
        except (TypeError, ValueError) as exc:
            raise ResolveAdapterError(
                f"Resolve GetTrackCount returned invalid video track count: {track_count!r}"
            ) from exc
        if video_track_count < 0:
            raise ResolveAdapterError(
                f"Resolve GetTrackCount returned invalid video track count: {track_count!r}"
            )

        timeline_items: list[object] = []
        for track_index in range(1, video_track_count + 1):
            track_items = _call_existing(
                timeline,
                "GetItemsInTrack",
                "video",
                track_index,
            )
            if not track_items:
                continue
            if not isinstance(track_items, dict):
                raise ResolveAdapterError(
                    "Resolve GetItemsInTrack did not return a dictionary"
                )
            timeline_items.extend(
                item for item in track_items.values() if item is not None
            )
        return tuple(timeline_items)

    def selected_run_input(self, course_id: str, run_date: str | None = None):
        from .service import SelectedRunInput

        selected = self.selected_media_pool_run()
        return SelectedRunInput(
            course_id=course_id,
            filename=selected.filename,
            source_fps=selected.source_fps,
            markers=selected.source_markers,
            clip_id=selected.clip_id,
            run_date=run_date,
            capture_time=selected.capture_time,
            capture_time_source=selected.capture_time_source,
            source_path=selected.source_path,
        )

    def matching_current_timeline_video_item(
        self,
        selected: SelectedMediaPoolRun,
    ) -> object:
        timeline_item = self.current_timeline_video_item()
        timeline_media = _call_required(timeline_item, "GetMediaPoolItem")
        timeline_clip_id = _optional_text(_call_optional(timeline_media, "GetUniqueId"))
        if selected.clip_id and timeline_clip_id:
            matches = selected.clip_id == timeline_clip_id
        else:
            timeline_name = _optional_text(_call_optional(timeline_media, "GetName"))
            matches = timeline_name == selected.filename
        if not matches:
            raise ResolveAdapterError(
                "selected Media Pool clip does not match the current timeline video item"
        )
        return timeline_item

    def _current_project(self) -> object:
        project_manager = _call_required(self.resolve, "GetProjectManager")
        return _call_required(project_manager, "GetCurrentProject")

    def _current_timeline(self) -> object:
        return _call_required(self._current_project(), "GetCurrentTimeline")

    @staticmethod
    def markers_from_resolve_map(marker_map: dict[Any, Any]) -> tuple[RawMarker, ...]:
        """Convert Resolve's marker dictionary into RawMarker objects.

        Resolve typically returns marker data keyed by frame, with each value
        carrying a `name` field. The adapter keeps all frame keys in the
        source-local domain supplied by Resolve.
        """
        markers: list[RawMarker] = []
        for frame_key, data in marker_map.items():
            if not isinstance(data, dict):
                raise ResolveAdapterError(
                    f"marker payload for frame {frame_key!r} is not a dictionary"
                )
            name = data.get("name") or data.get("Name")
            if not name:
                continue
            markers.append(RawMarker(str(name), _coerce_frame(frame_key)))
        return tuple(sorted(markers, key=lambda marker: marker.frame))

    @staticmethod
    def source_fps_from_properties(properties: dict[str, Any]) -> float:
        for key in ("FPS", "Frame Rate", "FrameRate", "fps"):
            value = properties.get(key)
            if value not in (None, ""):
                return _parse_fps(value)
        raise ResolveAdapterError("source clip FPS property not found")

    @staticmethod
    def _discover_resolve() -> object:
        try:
            import DaVinciResolveScript as dvr_script  # type: ignore
        except ImportError as exc:
            raise ResolveAdapterError(
                "DaVinciResolveScript is unavailable. Run this from Resolve's Python environment."
            ) from exc
        resolve = dvr_script.scriptapp("Resolve")
        if resolve is None:
            raise ResolveAdapterError("Could not connect to DaVinci Resolve")
        return resolve


def _coerce_frame(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    try:
        parsed = float(text)
    except ValueError as exc:
        raise ResolveAdapterError(f"invalid marker frame key: {value!r}") from exc
    if not parsed.is_integer():
        raise ResolveAdapterError(f"marker frame key is not an integer frame: {value!r}")
    return int(parsed)


def _parse_fps(value: Any) -> float:
    try:
        if isinstance(value, (int, float)):
            fps = float(value)
        else:
            text = str(value).strip()
            if "/" in text:
                numerator, denominator = text.split("/", 1)
                fps = float(numerator) / float(denominator)
            else:
                fps = float(text)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ResolveAdapterError(f"invalid FPS value: {value!r}") from exc
    if fps <= 0:
        raise ResolveAdapterError(f"invalid FPS value: {value!r}")
    return fps


def _call_required(target: object, method_name: str, *args: Any) -> Any:
    value = _call_existing(target, method_name, *args)
    if value is None:
        raise ResolveAdapterError(f"Resolve {method_name} returned nothing")
    return value


def _call_existing(target: object, method_name: str, *args: Any) -> Any:
    method = getattr(target, method_name, None)
    if not callable(method):
        raise ResolveAdapterError(f"Resolve object is missing {method_name}")
    return method(*args)


def _call_optional(target: object, method_name: str, *args: Any) -> Any:
    method = getattr(target, method_name, None)
    if not callable(method):
        return None
    return method(*args)


def _first_property(properties: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = properties.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _source_path_from_properties(properties: dict[str, Any], filename: str) -> str | None:
    direct = _first_property(
        properties,
        (
            "File Path",
            "FilePath",
            "Full Path",
            "FullPath",
            "Path",
            "Source Path",
        ),
    )
    if direct:
        return direct
    directory = _first_property(
        properties,
        (
            "Directory",
            "File Directory",
            "Folder",
            "Source Directory",
        ),
    )
    if directory:
        return str(Path(directory) / filename)
    return None


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
