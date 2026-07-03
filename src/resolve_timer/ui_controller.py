from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .database import TimerDatabase
from .markers import MarkerValidationError, parse_marker_snapshot
from .models import RawMarker
from .overlay import FusionOverlayUpdater
from .resolve_adapter import ResolveAdapter, ResolveAdapterError
from .runtime_support import (
    PreferencesError,
    UserPreferences,
    append_exception_log,
    load_preferences,
    save_preferences,
)
from .service import RunPreview, SelectedRunInput, TimelineRunCandidate, TimerService
from .summary_card import default_summary_card_path, render_course_summary_card
from .timing import compute_timing, format_delta, format_duration


@dataclass(frozen=True)
class TimingRowState:
    label: str
    duration: str
    reference: str
    delta: str


@dataclass(frozen=True)
class RunRowState:
    run_id: str
    date: str
    filename: str
    lap: str
    committed: bool
    ignored: bool
    has_clip_id: bool


@dataclass(frozen=True)
class CourseRowState:
    course_id: str
    name: str
    sector_count: int
    run_count: int


@dataclass(frozen=True)
class ResolveTimerViewState:
    database_path: str
    courses: tuple[tuple[str, str], ...]
    selected_course_id: str | None
    comparison_mode: str
    filename: str
    source_fps: str
    marker_source: str
    marker_count: int
    source_range: str
    timing_rows: tuple[TimingRowState, ...]
    history_status: str
    best_lap: str
    optimal_lap: str
    status: str
    error: str | None
    can_commit: bool
    can_update: bool
    can_toggle_ignored: bool
    can_delete: bool
    can_update_overlay: bool
    can_export_summary: bool
    matching_run_id: str | None


class ResolveTimerController:
    def __init__(
        self,
        database_path: str | Path,
        adapter: ResolveAdapter,
        *,
        preferences_path: str | Path | None = None,
        log_path: str | Path | None = None,
        overlay_updater: FusionOverlayUpdater | None = None,
    ):
        self.database_path = Path(database_path)
        self.preferences_path = (
            Path(preferences_path)
            if preferences_path is not None
            else self.database_path.with_name("resolve_timer_preferences.json")
        )
        self.log_path = (
            Path(log_path)
            if log_path is not None
            else self.database_path.with_name("resolve_timer.log")
        )
        self.adapter = adapter
        self.overlay_updater = overlay_updater or FusionOverlayUpdater()
        self.service: TimerService | None = None
        self.selected_course_id: str | None = None
        self.comparison_mode = "best_lap"

    def initialize(self) -> ResolveTimerViewState:
        preference_warning = None
        try:
            preferences = load_preferences(self.preferences_path)
            self.selected_course_id = preferences.course_id
            self.comparison_mode = preferences.comparison_mode
        except PreferencesError as exc:
            preference_warning = str(exc)
        try:
            self.service = TimerService.load(self.database_path)
        except Exception as exc:
            self._log_unexpected("initialize", exc)
            return self._empty_state(
                courses=(),
                status="Startup failed",
                error=str(exc),
            )
        if self.service.database.courses and self.selected_course_id is None:
            self.selected_course_id = self.service.database.courses[0].id
        state = self.refresh_selection()
        if preference_warning:
            return replace(
                state,
                status=f"{state.status}; preferences reset",
                error=preference_warning,
            )
        return state

    def select_course(self, course_id: str) -> ResolveTimerViewState:
        self.selected_course_id = course_id
        return self._persist_preferences(self.refresh_selection())

    def set_comparison_mode(self, mode: str) -> ResolveTimerViewState:
        if mode not in {"best_lap", "optimal"}:
            raise ValueError("comparison mode must be best_lap or optimal")
        self.comparison_mode = mode
        return self._persist_preferences(self.refresh_selection())

    def refresh_selection(self) -> ResolveTimerViewState:
        try:
            service = self._service()
            courses = self._courses(service.database)
            if not courses:
                return self._empty_state(
                    courses=(),
                    status="No courses configured",
                    error="Add a course to timer_db.yaml before using Resolve Timer.",
                )
            if not self.selected_course_id or self.selected_course_id not in {
                course_id for course_id, _ in courses
            }:
                self.selected_course_id = courses[0][0]

            selected = self.adapter.selected_media_pool_run()
            selected_input = self._selected_input(selected)
            try:
                preview = service.preview(selected_input)
            except MarkerValidationError as exc:
                raise MarkerValidationError(
                    [f"selected Media Pool clip {selected.filename}: {error}" for error in exc.errors]
                ) from exc
            return self._preview_state(courses, selected, preview)
        except Exception as exc:
            self._log_unexpected("refresh selection", exc)
            return self._empty_state(
                courses=self._loaded_courses(),
                status="Refresh failed",
                error=str(exc),
            )

    def commit_new_run(self) -> ResolveTimerViewState:
        try:
            service, selected_input, preview = self._mutation_context()
            if preview.matching_run is not None:
                raise ValueError(
                    f"run {preview.matching_run.id} already matches the selected clip"
                )
            run = service.commit_new_run(selected_input)
            service.save(self.database_path)
            self.service = TimerService.load(self.database_path)
            state = self.refresh_selection()
            return _with_status(state, f"Committed {run.id}")
        except Exception as exc:
            return self._mutation_error("Commit failed", exc)

    def update_existing_run(self, expected_run_id: str) -> ResolveTimerViewState:
        try:
            service, selected_input, preview = self._mutation_context()
            matching = preview.matching_run
            if matching is None:
                raise ValueError("no existing run matches the selected clip")
            if matching.id != expected_run_id:
                raise ValueError(
                    f"selected clip now matches {matching.id}, not {expected_run_id}; refresh and retry"
                )
            if not preview.has_marker_changes:
                raise ValueError(f"run {matching.id} has no marker changes")
            run = service.update_existing_run(selected_input, matching.id)
            service.save(self.database_path)
            self.service = TimerService.load(self.database_path)
            state = self.refresh_selection()
            return _with_status(state, f"Updated {run.id}")
        except Exception as exc:
            return self._mutation_error("Update failed", exc)

    def set_run_ignored(self, run_id: str, ignored: bool) -> ResolveTimerViewState:
        try:
            service = TimerService.load(self.database_path)
            self._require_selected_course_run(service.database, run_id)
            service.set_ignored(run_id, ignored)
            service.save(self.database_path)
            self.service = TimerService.load(self.database_path)
            state = self.refresh_selection()
            action = "Ignored" if ignored else "Unignored"
            return _with_status(state, f"{action} {run_id}")
        except Exception as exc:
            return self._mutation_error("Ignore update failed", exc)

    def delete_run(self, run_id: str) -> ResolveTimerViewState:
        try:
            service = TimerService.load(self.database_path)
            self._require_selected_course_run(service.database, run_id)
            service.delete_run(run_id)
            service.save(self.database_path)
            self.service = TimerService.load(self.database_path)
            state = self.refresh_selection()
            return _with_status(state, f"Deleted {run_id}")
        except Exception as exc:
            return self._mutation_error("Delete failed", exc)

    def add_course(self, course_id: str, name: str, sector_count: int) -> ResolveTimerViewState:
        try:
            service = TimerService.load(self.database_path)
            course = service.add_course(course_id, name, sector_count)
            service.save(self.database_path)
            self.service = TimerService.load(self.database_path)
            self.selected_course_id = course.id
            state = self._persist_preferences(self.refresh_selection())
            return _with_status(state, f"Added course {course.id}")
        except Exception as exc:
            return self._mutation_error("Course add failed", exc)

    def update_course(
        self,
        course_id: str,
        *,
        name: str | None = None,
        sector_count: int | None = None,
    ) -> ResolveTimerViewState:
        try:
            service = TimerService.load(self.database_path)
            course = service.update_course(
                course_id,
                name=name,
                sector_count=sector_count,
            )
            service.save(self.database_path)
            self.service = TimerService.load(self.database_path)
            state = self._persist_preferences(self.refresh_selection())
            return _with_status(state, f"Updated course {course.id}")
        except Exception as exc:
            return self._mutation_error("Course update failed", exc)

    def delete_course(self, course_id: str) -> ResolveTimerViewState:
        try:
            service = TimerService.load(self.database_path)
            service.delete_course(course_id)
            service.save(self.database_path)
            self.service = TimerService.load(self.database_path)
            if self.selected_course_id == course_id:
                self.selected_course_id = (
                    self.service.database.courses[0].id
                    if self.service.database.courses
                    else None
                )
            state = self._persist_preferences(self.refresh_selection())
            return _with_status(state, f"Deleted course {course_id}")
        except Exception as exc:
            return self._mutation_error("Course delete failed", exc)

    def update_overlay(self) -> ResolveTimerViewState:
        try:
            service = self._overlay_service()
            timeline_item = self.adapter.current_timeline_video_item()
            selected = self.adapter.timeline_item_media_pool_run(timeline_item)
            result = self._update_timeline_item_overlay(service, timeline_item, selected)
            action = "Created" if result.created else "Updated"
            return self._state_after_overlay_action(
                f"{action} live overlay for {selected.filename}: {result.comp_name}"
            )
        except Exception as exc:
            return self._mutation_error("Overlay update failed", exc)

    def update_all_overlays(self) -> ResolveTimerViewState:
        try:
            service = self._overlay_service()
            timeline_items = _timeline_items_in_order(self.adapter.timeline_video_items())
            if not timeline_items:
                raise ValueError("current timeline has no video clips")

            updated = 0
            skipped: list[str] = []
            candidates: list[TimelineRunCandidate] = []
            ordered_items: list[object] = []
            for index, timeline_item in enumerate(timeline_items, start=1):
                label = f"clip {index}"
                try:
                    selected = self.adapter.timeline_item_media_pool_run(timeline_item)
                    label = selected.filename
                except Exception as exc:
                    self._log_unexpected(f"update all overlays {label}", exc)
                    candidates.append(
                        TimelineRunCandidate(label=label, skip_reason=str(exc))
                    )
                    ordered_items.append(timeline_item)
                    continue
                candidates.append(
                    TimelineRunCandidate(
                        label=label,
                        selected=self._selected_input(selected),
                    )
                )
                ordered_items.append(timeline_item)

            payloads = service.chronological_overlay_payloads(
                candidates,
                comparison_mode=self.comparison_mode,
            )
            for timeline_item, payload_item in zip(ordered_items, payloads.items):
                if payload_item.payload is None:
                    if payload_item.message:
                        skipped.append(payload_item.message)
                    continue
                try:
                    self.overlay_updater.update_or_create(
                        timeline_item,
                        payload_item.payload,
                    )
                    updated += 1
                except Exception as exc:
                    self._log_unexpected(
                        f"update all overlays {payload_item.label}",
                        exc,
                    )
                    skipped.append(f"{payload_item.label}: {exc}")

            if updated == 0:
                return replace(
                    self._state_after_overlay_action("No timeline overlays updated"),
                    error=_skip_summary(skipped),
                )

            status = f"Updated live overlays for {updated} timeline clip(s)"
            if skipped:
                status = f"{status}; skipped {len(skipped)}"
            state = self._state_after_overlay_action(status)
            if skipped:
                return replace(state, error=_skip_summary(skipped))
            return state
        except Exception as exc:
            return self._mutation_error("Overlay update failed", exc)

    def commit_update_timeline_runs(self) -> ResolveTimerViewState:
        try:
            service = TimerService.load(self.database_path)
            if not self.selected_course_id:
                raise ValueError("select a course before committing timeline runs")
            timeline_items = _timeline_items_in_order(self.adapter.timeline_video_items())
            if not timeline_items:
                raise ValueError("current timeline has no video clips")

            candidates: list[TimelineRunCandidate] = []
            for index, timeline_item in enumerate(timeline_items, start=1):
                label = f"clip {index}"
                try:
                    selected = self.adapter.timeline_item_media_pool_run(timeline_item)
                    label = selected.filename
                    candidates.append(
                        TimelineRunCandidate(
                            label=label,
                            selected=self._selected_input(selected),
                        )
                    )
                except Exception as exc:
                    self._log_unexpected(f"timeline run {label}", exc)
                    candidates.append(
                        TimelineRunCandidate(label=label, skip_reason=str(exc))
                    )

            result = service.commit_or_update_timeline_runs(candidates)
            if result.changed:
                service.save(self.database_path)
            self.service = TimerService.load(self.database_path)
            state = self._state_after_overlay_action(_timeline_batch_status(result))
            details = _timeline_batch_details(result)
            if details:
                return replace(state, error=details)
            return state
        except Exception as exc:
            return self._mutation_error("Timeline commit/update failed", exc)

    def export_course_summary_card(self, output_path: str | Path | None = None) -> ResolveTimerViewState:
        try:
            service = TimerService.load(self.database_path)
            if not self.selected_course_id:
                raise ValueError("select a course before exporting a summary")
            payload = service.course_summary_payload(self.selected_course_id)
            output = (
                Path(output_path)
                if output_path is not None
                else default_summary_card_path(self.database_path, self.selected_course_id)
            )
            written = render_course_summary_card(payload, output)
            return self._state_after_overlay_action(f"Exported course summary PNG: {written}")
        except Exception as exc:
            return self._mutation_error("Summary export failed", exc)

    def course_runs(self) -> tuple[RunRowState, ...]:
        service = TimerService.load(self.database_path)
        if not self.selected_course_id:
            return ()
        course = service.database.course_by_id(self.selected_course_id)
        rows = []
        for run in service.database.runs:
            if run.course_id != course.id:
                continue
            try:
                markers = tuple(
                    RawMarker(name, frame) for name, frame in run.marker_frames.items()
                )
                snapshot = parse_marker_snapshot(list(markers), course)
                lap = format_duration(compute_timing(snapshot, course, run.source_fps).lap_seconds)
            except Exception:
                lap = "Invalid"
            rows.append(
                RunRowState(
                    run_id=run.id,
                    date=run.date,
                    filename=run.filename,
                    lap=lap,
                    committed=run.committed,
                    ignored=run.ignored,
                    has_clip_id=bool(run.clip_id),
                )
            )
        return tuple(rows)

    def course_rows(self) -> tuple[CourseRowState, ...]:
        service = TimerService.load(self.database_path)
        return tuple(
            CourseRowState(
                course_id=course.id,
                name=course.name,
                sector_count=course.sector_count,
                run_count=service.course_run_count(course.id),
            )
            for course in service.database.courses
        )

    def _preview_state(
        self,
        courses: tuple[tuple[str, str], ...],
        selected: object,
        preview: RunPreview,
    ) -> ResolveTimerViewState:
        rows = []
        for row in preview.comparison_rows(self.comparison_mode):
            rows.append(
                TimingRowState(
                    label=row.label,
                    duration=format_duration(row.duration_seconds),
                    reference=(
                        "--:--.---"
                        if row.reference_seconds is None
                        else format_duration(row.reference_seconds)
                    ),
                    delta=(
                        "--.---"
                        if row.delta_seconds is None
                        else format_delta(row.delta_seconds)
                    ),
                )
            )

        matching = preview.matching_run
        if matching is None:
            history = "No committed run matches this clip"
        elif preview.has_marker_changes:
            history = f"Marker changes detected for {matching.id}"
        elif matching.ignored:
            history = f"Matched ignored run {matching.id}"
        else:
            history = f"Matched committed run {matching.id}"

        return ResolveTimerViewState(
            database_path=str(self.database_path),
            courses=courses,
            selected_course_id=self.selected_course_id,
            comparison_mode=self.comparison_mode,
            filename=str(getattr(selected, "filename")),
            source_fps=f"{float(getattr(selected, 'source_fps')):g}",
            marker_source=_marker_source_label(str(getattr(selected, "marker_source"))),
            marker_count=len(getattr(selected, "source_markers")),
            source_range="Full source clip",
            timing_rows=tuple(rows),
            history_status=history,
            best_lap=_format_summary_stat(
                None
                if preview.stats.best_lap is None
                else preview.stats.best_lap.timing.lap_seconds,
                preview.best_lap_delta,
            ),
            optimal_lap=_format_summary_stat(
                preview.stats.optimal_seconds,
                preview.optimal_lap_delta,
            ),
            status="Ready",
            error=None,
            can_commit=matching is None,
            can_update=preview.has_marker_changes,
            can_toggle_ignored=matching is not None,
            can_delete=matching is not None,
            can_update_overlay=True,
            can_export_summary=bool(self.selected_course_id),
            matching_run_id=None if matching is None else matching.id,
        )

    def _empty_state(
        self,
        *,
        courses: tuple[tuple[str, str], ...],
        status: str,
        error: str,
    ) -> ResolveTimerViewState:
        return ResolveTimerViewState(
            database_path=str(self.database_path),
            courses=courses,
            selected_course_id=self.selected_course_id,
            comparison_mode=self.comparison_mode,
            filename="No valid selection",
            source_fps="-",
            marker_source="-",
            marker_count=0,
            source_range="-",
            timing_rows=(),
            history_status="-",
            best_lap="--:--.---",
            optimal_lap="--:--.---",
            status=status,
            error=error,
            can_commit=False,
            can_update=False,
            can_toggle_ignored=False,
            can_delete=False,
            can_update_overlay=bool(courses and self.selected_course_id),
            can_export_summary=bool(courses and self.selected_course_id),
            matching_run_id=None,
        )

    def _mutation_context(self):
        service, _selected, selected_input, preview = self._selection_context()
        return service, selected_input, preview

    def _selection_context(self):
        self.service = TimerService.load(self.database_path)
        service = self.service
        if not self.selected_course_id:
            raise ValueError("select a course before modifying runs")
        selected = self.adapter.selected_media_pool_run()
        selected_input = self._selected_input(selected)
        preview = service.preview(selected_input)
        return service, selected, selected_input, preview

    def _overlay_service(self) -> TimerService:
        self.service = TimerService.load(self.database_path)
        if not self.selected_course_id:
            raise ValueError("select a course before updating overlays")
        return self.service

    def _update_timeline_item_overlay(self, service, timeline_item, selected):
        payload = service.overlay_payload(
            self._selected_input(selected),
            comparison_mode=self.comparison_mode,
        )
        return self.overlay_updater.update_or_create(timeline_item, payload)

    def _selected_input(self, selected) -> SelectedRunInput:
        if not self.selected_course_id:
            raise ValueError("select a course before modifying runs")
        return SelectedRunInput(
            course_id=self.selected_course_id,
            filename=selected.filename,
            source_fps=selected.source_fps,
            markers=selected.source_markers,
            clip_id=selected.clip_id,
        )

    def _state_after_overlay_action(self, status: str) -> ResolveTimerViewState:
        state = self.refresh_selection()
        if state.error is not None:
            return replace(state, status=status, error=None)
        return _with_status(state, status)

    def _mutation_error(self, status: str, exc: Exception) -> ResolveTimerViewState:
        self._log_unexpected(status.lower(), exc)
        state = self.refresh_selection()
        return replace(state, status=status, error=str(exc))

    def _persist_preferences(self, state: ResolveTimerViewState) -> ResolveTimerViewState:
        try:
            save_preferences(
                self.preferences_path,
                UserPreferences(
                    course_id=self.selected_course_id,
                    comparison_mode=self.comparison_mode,
                ),
            )
            return state
        except PreferencesError as exc:
            return replace(state, status="Preference save failed", error=str(exc))

    def _log_unexpected(self, context: str, exc: Exception) -> None:
        if isinstance(
            exc,
            (ValueError, MarkerValidationError, ResolveAdapterError, OSError),
        ):
            return
        append_exception_log(self.log_path, context, exc)

    def _require_selected_course_run(self, database: TimerDatabase, run_id: str) -> None:
        if not self.selected_course_id:
            raise ValueError("select a course before modifying runs")
        for run in database.runs:
            if run.id == run_id:
                if run.course_id != self.selected_course_id:
                    raise ValueError(
                        f"run {run_id} belongs to course {run.course_id}, "
                        f"not {self.selected_course_id}"
                    )
                return
        raise ValueError(f"run not found: {run_id}")

    def _service(self) -> TimerService:
        if self.service is None:
            self.service = TimerService.load(self.database_path)
        return self.service

    def _loaded_courses(self) -> tuple[tuple[str, str], ...]:
        if self.service is None:
            return ()
        return self._courses(self.service.database)

    @staticmethod
    def _courses(database: TimerDatabase) -> tuple[tuple[str, str], ...]:
        return tuple((course.id, course.name) for course in database.courses)


def _marker_source_label(value: str) -> str:
    if value == "source_clip":
        return "Media Pool source clip"
    return value


def _with_status(state: ResolveTimerViewState, status: str) -> ResolveTimerViewState:
    return replace(state, status=status)


def _format_summary_stat(seconds: float | None, delta_seconds: float | None) -> str:
    if seconds is None:
        return "--:--.---"
    value = format_duration(seconds)
    if delta_seconds is not None:
        value = f"{value} ({format_delta(delta_seconds)})"
    return value


def _timeline_items_in_order(timeline_items: tuple[object, ...]) -> tuple[object, ...]:
    starts = [_timeline_item_start(item) for item in timeline_items]
    if starts and all(start is not None for start in starts):
        return tuple(
            item
            for _start, _index, item in sorted(
                (start, index, item)
                for index, (start, item) in enumerate(zip(starts, timeline_items))
            )
        )
    return timeline_items


def _timeline_item_start(timeline_item: object) -> int | None:
    method = getattr(timeline_item, "GetStart", None)
    if not callable(method):
        return None
    try:
        return int(method())
    except (TypeError, ValueError):
        return None


def _timeline_batch_status(result) -> str:
    return (
        "Timeline runs: "
        f"committed {result.committed}, "
        f"updated {result.updated}, "
        f"unchanged {result.unchanged}, "
        f"skipped {result.skipped}, "
        f"failed {result.failed}"
    )


def _timeline_batch_details(result) -> str | None:
    messages = [
        item.message
        for item in result.items
        if item.action in {"skipped", "failed"}
    ]
    if not messages:
        return None
    shown = messages[:8]
    suffix = "" if len(messages) <= len(shown) else f"\n... and {len(messages) - len(shown)} more"
    return "Timeline run issues:\n" + "\n".join(shown) + suffix


def _skip_summary(skipped: list[str]) -> str | None:
    if not skipped:
        return None
    shown = skipped[:5]
    suffix = "" if len(skipped) <= len(shown) else f"\n... and {len(skipped) - len(shown)} more"
    return "Skipped timeline clips:\n" + "\n".join(shown) + suffix
