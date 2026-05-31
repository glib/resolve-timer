from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import RawMarker


class ResolveAdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class SelectedTimelineRun:
    timeline_item: object
    source_clip: object
    filename: str
    source_fps: float
    source_markers: tuple[RawMarker, ...]
    clip_id: str | None = None


class ResolveAdapter:
    """Boundary for Resolve scripting API calls.

    The exact selected-item, source-marker, and Fusion update APIs need live
    Resolve validation. Keep all direct Resolve API use behind this class.
    """

    def __init__(self, resolve: object | None = None):
        self.resolve = resolve or self._discover_resolve()

    def selected_timeline_run(self) -> SelectedTimelineRun:
        raise NotImplementedError(
            "Selected timeline item to source marker access must be validated in Resolve"
        )

    @staticmethod
    def markers_from_resolve_map(marker_map: dict[Any, dict[str, Any]]) -> tuple[RawMarker, ...]:
        """Convert Resolve's marker dictionary into RawMarker objects.

        Resolve typically returns marker data keyed by frame, with each value
        carrying a `name` field. The adapter keeps all frame keys in the
        source-local domain supplied by Resolve.
        """
        markers: list[RawMarker] = []
        for frame_key, data in marker_map.items():
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
