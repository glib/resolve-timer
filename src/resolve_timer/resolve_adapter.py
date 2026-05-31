from __future__ import annotations

from dataclasses import dataclass

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
