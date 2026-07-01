from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .database import TimerDatabase
from .markers import MarkerValidationError, parse_marker_snapshot
from .matching import clip_fingerprint, find_matching_run
from .models import Course, MarkerSnapshot, RawMarker, RunRecord, TimingResult, utc_timestamp
from .overlay import OverlayPayload, build_overlay_payload
from .stats import CourseStats, compute_course_stats
from .summary_card import CourseSummaryPayload, build_course_summary_payload
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
class TimelineRunCandidate:
    label: str
    selected: SelectedRunInput | None = None
    skip_reason: str | None = None


@dataclass(frozen=True)
class TimelineBatchItem:
    label: str
    action: str
    message: str
    run_id: str | None = None
    preview: RunPreview | None = None


@dataclass(frozen=True)
class TimelineBatchResult:
    committed: int
    updated: int
    unchanged: int
    skipped: int
    failed: int
    items: tuple[TimelineBatchItem, ...]

    @property
    def changed(self) -> int:
        return self.committed + self.updated


@dataclass(frozen=True)
class ComparisonReferences:
    mode: str
    sector_seconds: tuple[float | None, ...]
    lap_seconds: float | None


@dataclass(frozen=True)
class ComparisonRow:
    label: str
    duration_seconds: float
    reference_seconds: float | None
    delta_seconds: float | None


@dataclass(frozen=True)
class RunPreview:
    course: Course
    snapshot: MarkerSnapshot
    timing: TimingResult
    stats: CourseStats
    matching_run: RunRecord | None
    best_lap_references: ComparisonReferences
    optimal_references: ComparisonReferences
    best_lap_delta: float | None
    optimal_lap_delta: float | None

    @property
    def has_marker_changes(self) -> bool:
        return self.matching_run is not None and self.matching_run.marker_frames != self.snapshot.frames

    def comparison_rows(self, comparison_mode: str = "best_lap") -> tuple[ComparisonRow, ...]:
        references = _references_for_mode(self, comparison_mode)
        rows: list[ComparisonRow] = []
        for sector, reference_seconds in zip(self.timing.sectors, references.sector_seconds):
            rows.append(
                ComparisonRow(
                    label=f"S{sector.sector}",
                    duration_seconds=sector.duration_seconds,
                    reference_seconds=reference_seconds,
                    delta_seconds=_delta(sector.duration_seconds, reference_seconds),
                )
            )
        rows.append(
            ComparisonRow(
                label="LAP",
                duration_seconds=self.timing.lap_seconds,
                reference_seconds=references.lap_seconds,
                delta_seconds=_delta(self.timing.lap_seconds, references.lap_seconds),
            )
        )
        return tuple(rows)


class TimerService:
    def __init__(self, database: TimerDatabase):
        self.database = database

    @classmethod
    def load(cls, path: str | Path) -> "TimerService":
        return cls(TimerDatabase.load(path))

    def save(self, path: str | Path) -> None:
        self.database.save(path)

    def add_course(self, course_id: str, name: str, sector_count: int) -> Course:
        course_id = _clean_required("course_id", course_id)
        name = _clean_required("name", name)
        if sector_count < 1:
            raise ValueError("sector_count must be at least 1")
        for existing in self.database.courses:
            if existing.id == course_id:
                raise ValueError(f"course already exists: {course_id}")
        course = Course(course_id, name, sector_count)
        self.database.courses.append(course)
        return course

    def update_course(
        self,
        course_id: str,
        *,
        name: str | None = None,
        sector_count: int | None = None,
    ) -> Course:
        course_index, existing = self._course_index_and_record(course_id)
        updated_name = existing.name if name is None else _clean_required("name", name)
        updated_sector_count = existing.sector_count if sector_count is None else int(sector_count)
        if updated_sector_count < 1:
            raise ValueError("sector_count must be at least 1")
        if updated_sector_count != existing.sector_count and self.course_run_count(course_id) > 0:
            raise ValueError(
                f"cannot change sector_count for course {course_id}; committed runs exist"
            )
        updated = Course(existing.id, updated_name, updated_sector_count)
        self.database.courses[course_index] = updated
        return updated

    def delete_course(self, course_id: str) -> None:
        course_index, _existing = self._course_index_and_record(course_id)
        run_count = self.course_run_count(course_id)
        if run_count > 0:
            raise ValueError(f"cannot delete course {course_id}; {run_count} run(s) exist")
        del self.database.courses[course_index]

    def course_run_count(self, course_id: str) -> int:
        return sum(1 for run in self.database.runs if run.course_id == course_id)

    def _course_index_and_record(self, course_id: str) -> tuple[int, Course]:
        for index, course in enumerate(self.database.courses):
            if course.id == course_id:
                return index, course
        raise ValueError(f"course not found: {course_id}")

    def normalize_fingerprints(self) -> int:
        updated = 0
        for run in self.database.runs:
            fingerprint = clip_fingerprint(run.filename, run.marker_frames)
            if run.fingerprint != fingerprint:
                run.fingerprint = fingerprint
                updated += 1
        return updated

    def preview(
        self,
        selected: SelectedRunInput,
        *,
        stats_runs: list[RunRecord] | None = None,
    ) -> RunPreview:
        course = self.database.course_by_id(selected.course_id)
        snapshot = parse_marker_snapshot(list(selected.markers), course)
        timing = compute_timing(snapshot, course, selected.source_fps)
        stats_source = self.database.runs if stats_runs is None else stats_runs
        stats = compute_course_stats(course, stats_source)
        matching = find_matching_run(
            self.database.runs,
            course_id=course.id,
            filename=selected.filename,
            marker_frames=snapshot,
            clip_id=selected.clip_id,
        )
        baseline_stats = compute_course_stats(
            course,
            stats_source,
            exclude_run_id=None if matching is None else matching.id,
        )
        baseline_best = (
            None
            if baseline_stats.best_lap is None
            else baseline_stats.best_lap.timing.lap_seconds
        )
        return RunPreview(
            course=course,
            snapshot=snapshot,
            timing=timing,
            stats=stats,
            matching_run=matching,
            best_lap_references=_best_lap_references(course, stats),
            optimal_references=_optimal_references(course, stats),
            best_lap_delta=_summary_delta(timing.lap_seconds, baseline_best),
            optimal_lap_delta=_summary_delta(
                timing.lap_seconds,
                baseline_stats.optimal_seconds,
            ),
        )

    def commit_new_run(
        self,
        selected: SelectedRunInput,
        *,
        run_id: str | None = None,
        committed_at: str | None = None,
    ) -> RunRecord:
        if run_id and any(run.id == run_id for run in self.database.runs):
            raise ValueError(f"run already exists: {run_id}")
        preview = self.preview(selected)
        new_run = self._new_run_from_preview(
            selected,
            preview,
            run_id=run_id,
            committed_at=committed_at,
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
                if existing.course_id != preview.course.id:
                    raise ValueError(
                        f"run {run_id} belongs to course {existing.course_id}, not {preview.course.id}"
                    )
                updated = self._updated_run_from_preview(
                    selected,
                    preview,
                    existing,
                    committed_at=committed_at,
                )
                self.database.upsert_run(updated)
                return updated
        raise ValueError(f"run not found: {run_id}")

    def commit_or_update_timeline_runs(
        self,
        candidates: list[TimelineRunCandidate],
    ) -> TimelineBatchResult:
        baseline_runs = list(self.database.runs)
        items: list[TimelineBatchItem] = []
        for candidate in candidates:
            label = candidate.label
            if candidate.selected is None:
                reason = candidate.skip_reason or "no source clip"
                items.append(
                    TimelineBatchItem(
                        label=label,
                        action="skipped",
                        message=f"{label}: {reason}",
                    )
                )
                continue

            selected = candidate.selected
            label = label or selected.filename
            try:
                preview = self.preview(selected, stats_runs=baseline_runs)
                matching = preview.matching_run
                if matching is None:
                    run = self._new_run_from_preview(selected, preview)
                    self.database.upsert_run(run)
                    _upsert_run(baseline_runs, run)
                    items.append(
                        TimelineBatchItem(
                            label=label,
                            action="committed",
                            message=f"{label}: committed {run.id}",
                            run_id=run.id,
                            preview=preview,
                        )
                    )
                elif preview.has_marker_changes:
                    run = self._updated_run_from_preview(selected, preview, matching)
                    self.database.upsert_run(run)
                    _upsert_run(baseline_runs, run)
                    items.append(
                        TimelineBatchItem(
                            label=label,
                            action="updated",
                            message=f"{label}: updated {run.id}",
                            run_id=run.id,
                            preview=preview,
                        )
                    )
                else:
                    items.append(
                        TimelineBatchItem(
                            label=label,
                            action="unchanged",
                            message=f"{label}: unchanged {matching.id}",
                            run_id=matching.id,
                            preview=preview,
                        )
                    )
            except (MarkerValidationError, ValueError) as exc:
                items.append(
                    TimelineBatchItem(
                        label=label,
                        action="skipped",
                        message=f"{label}: {exc}",
                    )
                )
            except Exception as exc:
                items.append(
                    TimelineBatchItem(
                        label=label,
                        action="failed",
                        message=f"{label}: {exc}",
                    )
                )
        return _timeline_batch_result(items)

    def _new_run_from_preview(
        self,
        selected: SelectedRunInput,
        preview: RunPreview,
        *,
        run_id: str | None = None,
        committed_at: str | None = None,
    ) -> RunRecord:
        created_at = committed_at or utc_timestamp()
        return RunRecord(
            id=run_id or _next_run_id(
                self.database.runs,
                selected.run_date or date.today().isoformat(),
            ),
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

    def _updated_run_from_preview(
        self,
        selected: SelectedRunInput,
        preview: RunPreview,
        existing: RunRecord,
        *,
        committed_at: str | None = None,
    ) -> RunRecord:
        return RunRecord(
            id=existing.id,
            course_id=existing.course_id,
            date=selected.run_date or existing.date,
            filename=selected.filename,
            source_fps=selected.source_fps,
            marker_frames=dict(preview.snapshot.frames),
            clip_id=selected.clip_id or existing.clip_id,
            fingerprint=clip_fingerprint(selected.filename, preview.snapshot),
            committed=True,
            ignored=existing.ignored,
            committed_at=committed_at or utc_timestamp(),
            metadata=dict(existing.metadata),
        )

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

    def overlay_payload(
        self,
        selected: SelectedRunInput,
        *,
        comparison_mode: str = "best_lap",
    ) -> OverlayPayload:
        preview = self.preview(selected)
        references = _references_for_mode(preview, comparison_mode)
        return build_overlay_payload(
            course=preview.course,
            snapshot=preview.snapshot,
            current_timing=preview.timing,
            comparison_mode=references.mode,
            run_id=preview.matching_run.id if preview.matching_run else None,
            source_fps=selected.source_fps,
            sector_reference_seconds=references.sector_seconds,
            best_lap_seconds=preview.best_lap_references.lap_seconds,
            optimal_lap_seconds=preview.optimal_references.lap_seconds,
        )

    def course_summary_payload(self, course_id: str) -> CourseSummaryPayload:
        course = self.database.course_by_id(course_id)
        stats = compute_course_stats(course, self.database.runs)
        return build_course_summary_payload(course, stats)


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


def _references_for_mode(preview: RunPreview, comparison_mode: str) -> ComparisonReferences:
    if comparison_mode == "best_lap":
        return preview.best_lap_references
    if comparison_mode == "optimal":
        return preview.optimal_references
    raise ValueError("comparison_mode must be best_lap or optimal")


def _delta(duration_seconds: float, reference_seconds: float | None) -> float | None:
    if reference_seconds is None:
        return None
    return duration_seconds - reference_seconds


def _summary_delta(duration_seconds: float, reference_seconds: float | None) -> float | None:
    if reference_seconds is None or duration_seconds > reference_seconds:
        return None
    return duration_seconds - reference_seconds


def _upsert_run(runs: list[RunRecord], run: RunRecord) -> None:
    for index, existing in enumerate(runs):
        if existing.id == run.id:
            runs[index] = run
            return
    runs.append(run)


def _timeline_batch_result(items: list[TimelineBatchItem]) -> TimelineBatchResult:
    return TimelineBatchResult(
        committed=sum(1 for item in items if item.action == "committed"),
        updated=sum(1 for item in items if item.action == "updated"),
        unchanged=sum(1 for item in items if item.action == "unchanged"),
        skipped=sum(1 for item in items if item.action == "skipped"),
        failed=sum(1 for item in items if item.action == "failed"),
        items=tuple(items),
    )


def _clean_required(field: str, value: str) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise ValueError(f"{field} is required")
    return cleaned


def _next_run_id(runs: list[RunRecord], run_date: str) -> str:
    stem = "run_" + run_date.replace("-", "_")
    existing_ids = {run.id for run in runs}
    index = 1
    while True:
        candidate = f"{stem}_{index:03d}"
        if candidate not in existing_ids:
            return candidate
        index += 1
