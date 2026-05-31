from __future__ import annotations

from pathlib import Path

from .database import TimerDatabase
from .resolve_adapter import ResolveAdapter, ResolveAdapterError
from .service import RunPreview, TimerService
from .timing import format_delta, format_duration


def default_database_path() -> Path:
    return Path.cwd() / "timer_db.yaml"


def preview_selected_clip(
    *,
    database_path: str | Path,
    course_id: str,
    adapter: ResolveAdapter | None = None,
) -> RunPreview:
    service = TimerService.load(database_path)
    resolve_adapter = adapter or ResolveAdapter()
    selected = resolve_adapter.selected_run_input(course_id)
    return service.preview(selected)


def format_preview_summary(preview: RunPreview, comparison_mode: str = "best_lap") -> str:
    lines = [f"Course: {preview.course.name}"]
    for row in preview.comparison_rows(comparison_mode):
        if row.delta_seconds is None:
            lines.append(f"{row.label}: {format_duration(row.duration_seconds)}")
        else:
            lines.append(
                f"{row.label}: {format_duration(row.duration_seconds)} ({format_delta(row.delta_seconds)})"
            )
    if preview.stats.best_lap:
        lines.append(f"Best: {format_duration(preview.stats.best_lap.timing.lap_seconds)}")
    if preview.stats.optimal_seconds is not None:
        lines.append(f"Optimal: {format_duration(preview.stats.optimal_seconds)}")
    if preview.matching_run:
        state = "changed" if preview.has_marker_changes else "matched"
        lines.append(f"History: {state} {preview.matching_run.id}")
    else:
        lines.append("History: no committed run")
    return "\n".join(lines)


def run_interactive_tool(database_path: str | Path | None = None) -> None:
    """Launch the Resolve Timer UI.

    The UI Manager implementation is the next Resolve-validated layer. This
    entrypoint currently verifies the database and Resolve connection boundary.
    """
    db_path = Path(database_path) if database_path else default_database_path()
    TimerDatabase.load(db_path)
    try:
        ResolveAdapter()
    except ResolveAdapterError:
        raise
    raise NotImplementedError(
        "Resolve UI Manager window must be implemented after validating Resolve UI APIs"
    )
