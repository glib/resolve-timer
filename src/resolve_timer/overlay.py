from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass

from .matching import marker_snapshot_hash
from .models import Course, MarkerSnapshot, TimingResult
from .timing import format_delta, format_duration


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
        return data


def generated_overlay_name(payload: OverlayPayload) -> str:
    identity = payload.run_id or marker_snapshot_hash(payload.marker_frames)
    return f"{FusionOverlayUpdater.generated_name_prefix} - {payload.course_id} - {identity}"


@dataclass(frozen=True)
class OverlayTextRow:
    label: str
    duration_seconds: float
    delta_seconds: float | None


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


def _delta(duration_seconds: float, reference_seconds: float | None) -> float | None:
    if reference_seconds is None:
        return None
    return duration_seconds - reference_seconds


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
    """Resolve/Fusion overlay writer.

    This class is intentionally thin until the exact Resolve Fusion API calls are
    validated in Studio. The stable payload shape is ready for those calls.
    """

    generated_name_prefix = "Resolve Timer"

    def update_or_create(self, timeline_item: object, payload: OverlayPayload) -> None:
        raise NotImplementedError(
            "Fusion overlay creation/update must be validated inside DaVinci Resolve Studio"
        )
