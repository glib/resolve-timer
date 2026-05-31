from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .database import TimerDatabase
from .markers import parse_marker_snapshot
from .matching import clip_fingerprint, find_matching_run
from .models import Course, MarkerSnapshot, RawMarker, RunRecord, TimingResult, utc_timestamp
from .stats import CourseStats, compute_course_stats
from .timing import compute_timing


@dataclass(frozen=True)
class SelectedRunInput:
    course_id: str
    filename: str
    source_fps: float
    markers: tuple[RawMarker, ...]
    clip_id: str | None = None
    run_date: str | None = None


@dataclass(frozen=True)
class ComparisonReferences:
    mode: str
    sector_seconds: tuple[float | None, ...]
    lap_seconds: float | None


@dataclass(frozen=True)
class RunPreview:
    course: Course
    snapshot: MarkerSnapshot
    timing: TimingResult
    stats: CourseStats
    matching_run: RunRecord | None
    best_lap_references: ComparisonReferences
    optimal_references: ComparisonReferences

    @property
    def has_marker_changes(self) -> bool:
        return self.matching_run is not None and self.matching_run.marker_frames != self.snapshot.frames


class TimerService:
    def __init__(self, database: TimerDatabase):
        self.database = database

    @classmethod
    def load(cls, path: str | Path) -> "TimerService":
        return cls(TimerDatabase.load(path))

    def save(self, path: str | Path) -> None:
        self.database.save(path)

    def preview(self, selected: SelectedRunInput) -> RunPreview:
        course = self.database.course_by_id(selected.course_id)
        snapshot = parse_marker_snapshot(list(selected.markers), course)
        timing = compute_timing(snapshot, course, selected.source_fps)
        stats = compute_course_stats(course, self.database.runs)
        matching = find_matching_run(
            self.database.runs,
            course_id=course.id,
            filename=selected.filename,
            marker_frames=snapshot,
            clip_id=selected.clip_id,
        )
        return RunPreview(
            course=course,
            snapshot=snapshot,
            timing=timing,
            stats=stats,
            matching_run=matching,
            best_lap_references=_best_lap_references(course, stats),
            optimal_references=_optimal_references(course, stats),
        )

    def commit_new_run(
        self,
        selected: SelectedRunInput,
        *,
        run_id: str | None = None,
        committed_at: str | None = None,
    ) -> RunRecord:
        preview = self.preview(selected)
        created_at = committed_at or utc_timestamp()
        new_run = RunRecord(
            id=run_id or _next_run_id(self.database.runs, selected.run_date or date.today().isoformat()),
            course_id=preview.course.id,
            date=selected.run_date or date.today().isoformat(),
            filename=selected.filename,
            source_fps=selected.source_fps,
            marker_frames=dict(preview.snapshot.frames),
            clip_id=selected.clip_id,
            fingerprint=clip_fingerprint(selected.filename, preview.snapshot),
            committed=True,
            ignored=False,
            committed_at=created_at,
        )
        self.database.upsert_run(new_run)
        return new_run

    def update_existing_run(
        self,
        selected: SelectedRunInput,
        run_id: str,
        *,
        committed_at: str | None = None,
    ) -> RunRecord:
        preview = self.preview(selected)
        for existing in self.database.runs:
            if existing.id == run_id:
                updated = RunRecord(
                    id=existing.id,
                    course_id=preview.course.id,
                    date=selected.run_date or existing.date,
                    filename=selected.filename,
                    source_fps=selected.source_fps,
                    marker_frames=dict(preview.snapshot.frames),
                    clip_id=selected.clip_id or existing.clip_id,
                    fingerprint=clip_fingerprint(selected.filename, preview.snapshot),
                    committed=True,
                    ignored=False,
                    committed_at=committed_at or utc_timestamp(),
                    metadata=dict(existing.metadata),
                )
                self.database.upsert_run(updated)
                return updated
        raise ValueError(f"run not found: {run_id}")

    def set_ignored(self, run_id: str, ignored: bool) -> RunRecord:
        for existing in self.database.runs:
            if existing.id == run_id:
                existing.ignored = ignored
                return existing
        raise ValueError(f"run not found: {run_id}")

    def delete_run(self, run_id: str) -> None:
        before = len(self.database.runs)
        self.database.runs = [run for run in self.database.runs if run.id != run_id]
        if len(self.database.runs) == before:
            raise ValueError(f"run not found: {run_id}")


def _best_lap_references(course: Course, stats: CourseStats) -> ComparisonReferences:
    if stats.best_lap is None:
        return ComparisonReferences("best_lap", tuple(None for _ in range(course.sector_count)), None)
    return ComparisonReferences(
        "best_lap",
        tuple(sector.duration_seconds for sector in stats.best_lap.timing.sectors),
        stats.best_lap.timing.lap_seconds,
    )


def _optimal_references(course: Course, stats: CourseStats) -> ComparisonReferences:
    by_sector = {sector.sector: sector.duration_seconds for sector in stats.fastest_sectors}
    return ComparisonReferences(
        "optimal",
        tuple(by_sector.get(sector) for sector in range(1, course.sector_count + 1)),
        stats.optimal_seconds,
    )


def _next_run_id(runs: list[RunRecord], run_date: str) -> str:
    stem = "run_" + run_date.replace("-", "_")
    existing_ids = {run.id for run in runs}
    index = 1
    while True:
        candidate = f"{stem}_{index:03d}"
        if candidate not in existing_ids:
            return candidate
        index += 1
