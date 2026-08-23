from __future__ import annotations

from dataclasses import dataclass

from .capture_time import effective_capture_time, normalize_capture_time
from .markers import MarkerValidationError, parse_marker_snapshot
from .models import Course, RawMarker, RunRecord, TimingResult
from .timing import compute_timing


@dataclass(frozen=True)
class RunTiming:
    run: RunRecord
    timing: TimingResult


@dataclass(frozen=True)
class BestLap:
    run: RunRecord
    timing: TimingResult


@dataclass(frozen=True)
class FastestSector:
    sector: int
    run: RunRecord
    duration_seconds: float
    duration_frames: int


@dataclass(frozen=True)
class CourseStats:
    eligible_runs: tuple[RunTiming, ...]
    best_lap: BestLap | None
    fastest_sectors: tuple[FastestSector, ...]
    optimal_seconds: float | None
    optimal_frames: int | None


def compute_course_stats(
    course: Course,
    runs: list[RunRecord],
    *,
    exclude_run_id: str | None = None,
    as_of_capture_time: str | None = None,
) -> CourseStats:
    as_of = normalize_capture_time(as_of_capture_time)
    eligible: list[RunTiming] = []
    for run in runs:
        if exclude_run_id is not None and run.id == exclude_run_id:
            continue
        if run.course_id != course.id or not run.committed or run.ignored:
            continue
        run_capture_time = effective_capture_time(run.capture_time, run.date)
        if as_of is not None and run_capture_time is not None and run_capture_time >= as_of:
            continue
        try:
            markers = [RawMarker(name, frame) for name, frame in run.marker_frames.items()]
            snapshot = parse_marker_snapshot(markers, course)
            timing = compute_timing(snapshot, course, run.source_fps)
        except (MarkerValidationError, ValueError, KeyError):
            continue
        eligible.append(RunTiming(run=run, timing=timing))

    eligible.sort(key=lambda item: (_run_order_time(item.run), item.run.id))
    best = min(eligible, key=lambda item: item.timing.lap_seconds, default=None)
    fastest: list[FastestSector] = []
    for sector_index in range(course.sector_count):
        sector_candidates = [
            (item, item.timing.sectors[sector_index]) for item in eligible
        ]
        if not sector_candidates:
            continue
        item, sector = min(
            sector_candidates,
            key=lambda pair: (
                pair[1].duration_seconds,
                _run_order_time(pair[0].run),
                pair[0].run.id,
            ),
        )
        fastest.append(
            FastestSector(
                sector=sector.sector,
                run=item.run,
                duration_seconds=sector.duration_seconds,
                duration_frames=sector.duration_frames,
            )
        )

    optimal_seconds = sum(sector.duration_seconds for sector in fastest) if fastest else None
    optimal_frames = sum(sector.duration_frames for sector in fastest) if fastest else None
    return CourseStats(
        eligible_runs=tuple(eligible),
        best_lap=BestLap(best.run, best.timing) if best else None,
        fastest_sectors=tuple(fastest),
        optimal_seconds=optimal_seconds,
        optimal_frames=optimal_frames,
    )


def _run_order_time(run: RunRecord) -> str:
    return effective_capture_time(run.capture_time, run.date) or run.committed_at or run.date or ""
