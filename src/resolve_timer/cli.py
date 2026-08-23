from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .capture_time import (
    FILENAME_CAPTURE_TIME_SOURCE,
    FILESYSTEM_CREATED_SOURCE,
    capture_date,
    filename_capture_time,
    filesystem_created_time,
)
from .database import DatabaseError, TimerDatabase
from .markers import MarkerValidationError
from .models import RawMarker
from .overlay import format_final_overlay_text
from .service import RunPreview, SelectedRunInput, TimerService
from .stats import CourseStats, compute_course_stats
from .summary_card import default_summary_card_path, render_course_summary_card
from .timing import format_duration
from .ui import format_preview_summary
from .validation import validate_database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="resolve-timer")
    parser.add_argument("--db", default="timer_db.yaml", help="Path to timer YAML database")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_courses = subparsers.add_parser("courses", help="List configured courses")
    list_courses.set_defaults(func=_cmd_courses)

    add_course = subparsers.add_parser("add-course", help="Add a course to the database")
    add_course.add_argument("--id", required=True, dest="course_id")
    add_course.add_argument("--name", required=True)
    add_course.add_argument("--sectors", required=True, type=int)
    add_course.set_defaults(func=_cmd_add_course)

    update_course = subparsers.add_parser("update-course", help="Update course metadata")
    update_course.add_argument("--id", required=True, dest="course_id")
    update_course.add_argument("--name")
    update_course.add_argument("--sectors", type=int)
    update_course.set_defaults(func=_cmd_update_course)

    delete_course = subparsers.add_parser("delete-course", help="Delete a course with no runs")
    delete_course.add_argument("--id", required=True, dest="course_id")
    delete_course.set_defaults(func=_cmd_delete_course)

    validate = subparsers.add_parser("validate-db", help="Validate database consistency")
    validate.set_defaults(func=_cmd_validate_db)

    normalize = subparsers.add_parser("normalize-db", help="Fill derived fields in the database")
    normalize.set_defaults(func=_cmd_normalize_db)

    backfill = subparsers.add_parser(
        "backfill-capture-times",
        help="Fill run capture times from filenames or source media files",
    )
    backfill.add_argument("--media-root", action="append", default=[])
    backfill.add_argument("--dry-run", action="store_true")
    backfill.set_defaults(func=_cmd_backfill_capture_times)

    list_runs = subparsers.add_parser("runs", help="List committed run records")
    list_runs.add_argument("--course", help="Only show runs for this course ID")
    list_runs.set_defaults(func=_cmd_runs)

    stats = subparsers.add_parser("stats", help="Show course timing statistics")
    stats.add_argument("--course", required=True, help="Course ID")
    stats.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    stats.set_defaults(func=_cmd_stats)

    summary_card = subparsers.add_parser("summary-card", help="Export a course summary PNG")
    summary_card.add_argument("--course", required=True, help="Course ID")
    summary_card.add_argument("--output", help="PNG output path")
    summary_card.set_defaults(func=_cmd_summary_card)

    preview = subparsers.add_parser("preview", help="Preview timing from a marker CSV")
    _add_selected_args(preview)
    preview.add_argument("--mode", choices=["best_lap", "optimal"], default="best_lap")
    preview.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    preview.set_defaults(func=_cmd_preview)

    commit = subparsers.add_parser("commit", help="Commit a new run from a marker CSV")
    _add_selected_args(commit)
    commit.add_argument("--run-id")
    commit.set_defaults(func=_cmd_commit)

    update = subparsers.add_parser("update-run", help="Update an existing run from a marker CSV")
    _add_selected_args(update)
    update.add_argument("run_id")
    update.set_defaults(func=_cmd_update_run)

    overlay = subparsers.add_parser("overlay-payload", help="Print overlay payload JSON from a marker CSV")
    _add_selected_args(overlay)
    overlay.add_argument("--mode", choices=["best_lap", "optimal"], default="best_lap")
    overlay.set_defaults(func=_cmd_overlay_payload)

    overlay_text = subparsers.add_parser("overlay-text", help="Print final overlay text preview")
    _add_selected_args(overlay_text)
    overlay_text.add_argument("--mode", choices=["best_lap", "optimal"], default="best_lap")
    overlay_text.set_defaults(func=_cmd_overlay_text)

    ignore = subparsers.add_parser("ignore-run", help="Exclude a run from stats/comparisons")
    ignore.add_argument("run_id")
    ignore.set_defaults(func=_cmd_ignore_run)

    unignore = subparsers.add_parser("unignore-run", help="Include a run in stats/comparisons")
    unignore.add_argument("run_id")
    unignore.set_defaults(func=_cmd_unignore_run)

    delete = subparsers.add_parser("delete-run", help="Delete a run record")
    delete.add_argument("run_id")
    delete.set_defaults(func=_cmd_delete_run)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (DatabaseError, MarkerValidationError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _add_selected_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--course", required=True, help="Course ID")
    parser.add_argument("--markers", required=True, help="CSV with name,frame columns")
    parser.add_argument("--filename", required=True)
    parser.add_argument("--fps", required=True, type=float)
    parser.add_argument("--clip-id")
    parser.add_argument("--date")
    parser.add_argument("--capture-time")
    parser.add_argument("--source-path")


def _cmd_courses(args: argparse.Namespace) -> int:
    database = TimerDatabase.load(args.db)
    for course in database.courses:
        print(f"{course.id}\t{course.name}\t{course.sector_count} sectors")
    return 0


def _cmd_add_course(args: argparse.Namespace) -> int:
    service = TimerService.load(args.db)
    course = service.add_course(args.course_id, args.name, args.sectors)
    service.save(args.db)
    print(f"Added course {course.id}")
    return 0


def _cmd_update_course(args: argparse.Namespace) -> int:
    if args.name is None and args.sectors is None:
        raise ValueError("update-course requires --name or --sectors")
    service = TimerService.load(args.db)
    course = service.update_course(
        args.course_id,
        name=args.name,
        sector_count=args.sectors,
    )
    service.save(args.db)
    print(f"Updated course {course.id}")
    return 0


def _cmd_delete_course(args: argparse.Namespace) -> int:
    service = TimerService.load(args.db)
    service.delete_course(args.course_id)
    service.save(args.db)
    print(f"Deleted course {args.course_id}")
    return 0


def _cmd_validate_db(args: argparse.Namespace) -> int:
    database = TimerDatabase.load(args.db)
    errors = validate_database(database)
    if not errors:
        print("Database OK")
        return 0
    for error in errors:
        print(error)
    return 1


def _cmd_normalize_db(args: argparse.Namespace) -> int:
    service = TimerService.load(args.db)
    count = service.normalize_fingerprints()
    service.save(args.db)
    print(f"Updated {count} run fingerprints")
    return 0


def _cmd_backfill_capture_times(args: argparse.Namespace) -> int:
    database = TimerDatabase.load(args.db)
    media_index = _media_files_by_name([Path(root) for root in args.media_root])
    updated = 0
    unresolved = 0
    duplicates = 0
    for run in database.runs:
        capture_time = filename_capture_time(run.filename)
        capture_time_source = (
            FILENAME_CAPTURE_TIME_SOURCE if capture_time is not None else None
        )
        source_path = None
        if capture_time is None:
            if run.capture_time and run.capture_time_source == FILESYSTEM_CREATED_SOURCE:
                continue
            matches = _matching_media_paths(run.filename, run.source_path, media_index)
            if not matches:
                unresolved += 1
                print(f"{run.id}: no filename timestamp or media file for {run.filename}")
                continue
            if len(matches) > 1:
                duplicates += 1
                print(f"{run.id}: duplicate media files found for {run.filename}")
                continue
            source_path = matches[0]
            capture_time = filesystem_created_time(source_path)
            capture_time_source = FILESYSTEM_CREATED_SOURCE
        if (
            run.capture_time == capture_time
            and run.capture_time_source == capture_time_source
        ):
            continue
        updated += 1
        print(
            f"{run.id}: {run.capture_time or 'missing'} -> {capture_time} "
            f"({capture_time_source})"
        )
        if args.dry_run:
            continue
        run.capture_time = capture_time
        run.capture_time_source = capture_time_source
        if source_path is not None:
            run.source_path = str(source_path)
        run.date = capture_date(capture_time) or run.date
    if updated and not args.dry_run:
        database.save(args.db)
    action = "Would update" if args.dry_run else "Updated"
    print(
        f"{action} {updated} run capture time(s); "
        f"unresolved {unresolved}; duplicates {duplicates}"
    )
    return 0


def _cmd_runs(args: argparse.Namespace) -> int:
    database = TimerDatabase.load(args.db)
    runs = database.runs
    if args.course:
        runs = [run for run in runs if run.course_id == args.course]
    for run in sorted(runs, key=lambda item: (item.course_id, item.date, item.id)):
        flags = _run_flags(run.committed, run.ignored)
        print(f"{run.id}\t{run.course_id}\t{run.date}\t{flags}\t{run.filename}")
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    database = TimerDatabase.load(args.db)
    course = database.course_by_id(args.course)
    stats = compute_course_stats(course, database.runs)
    if args.json:
        print(json.dumps(_stats_to_dict(course.id, stats), indent=2, sort_keys=True))
        return 0
    print(f"Course: {course.name}")
    print(f"Eligible runs: {len(stats.eligible_runs)}")
    if stats.best_lap:
        print(f"Best: {format_duration(stats.best_lap.timing.lap_seconds)} ({stats.best_lap.run.id})")
    else:
        print("Best: --:--.---")
    if stats.optimal_seconds is not None:
        print(f"Optimal: {format_duration(stats.optimal_seconds)}")
    else:
        print("Optimal: --:--.---")
    return 0


def _cmd_summary_card(args: argparse.Namespace) -> int:
    service = TimerService.load(args.db)
    payload = service.course_summary_payload(args.course)
    output = (
        Path(args.output)
        if args.output
        else default_summary_card_path(args.db, args.course)
    )
    written = render_course_summary_card(payload, output)
    print(f"Wrote {written}")
    return 0


def _stats_to_dict(course_id: str, stats: CourseStats) -> dict[str, object]:
    return {
        "course_id": course_id,
        "eligible_run_count": len(stats.eligible_runs),
        "best_lap": None
        if stats.best_lap is None
        else {
            "run_id": stats.best_lap.run.id,
            "seconds": stats.best_lap.timing.lap_seconds,
            "frames": stats.best_lap.timing.lap_frames,
        },
        "optimal": None
        if stats.optimal_seconds is None
        else {
            "seconds": stats.optimal_seconds,
            "frames": stats.optimal_frames,
        },
        "fastest_sectors": [
            {
                "sector": sector.sector,
                "run_id": sector.run.id,
                "seconds": sector.duration_seconds,
                "frames": sector.duration_frames,
            }
            for sector in stats.fastest_sectors
        ],
    }


def _cmd_preview(args: argparse.Namespace) -> int:
    service = TimerService.load(args.db)
    selected = _selected_from_args(args)
    preview = service.preview(selected)
    if args.json:
        print(json.dumps(_preview_to_dict(preview, args.mode), indent=2, sort_keys=True))
        return 0
    print(format_preview_summary(preview, args.mode))
    return 0


def _cmd_commit(args: argparse.Namespace) -> int:
    service = TimerService.load(args.db)
    run = service.commit_new_run(_selected_from_args(args), run_id=args.run_id)
    service.save(args.db)
    print(f"Committed {run.id}")
    return 0


def _preview_to_dict(preview: RunPreview, comparison_mode: str) -> dict[str, object]:
    return {
        "course": preview.course.to_dict(),
        "comparison_mode": comparison_mode,
        "rows": [
            {
                "label": row.label,
                "seconds": row.duration_seconds,
                "reference_seconds": row.reference_seconds,
                "delta_seconds": row.delta_seconds,
            }
            for row in preview.comparison_rows(comparison_mode)
        ],
        "matching_run_id": None if preview.matching_run is None else preview.matching_run.id,
        "has_marker_changes": preview.has_marker_changes,
        "best_lap_seconds": preview.best_lap_references.lap_seconds,
        "best_lap_delta_seconds": preview.best_lap_delta,
        "optimal_seconds": preview.optimal_references.lap_seconds,
        "optimal_delta_seconds": preview.optimal_lap_delta,
    }


def _cmd_update_run(args: argparse.Namespace) -> int:
    service = TimerService.load(args.db)
    run = service.update_existing_run(_selected_from_args(args), args.run_id)
    service.save(args.db)
    print(f"Updated {run.id}")
    return 0


def _cmd_overlay_payload(args: argparse.Namespace) -> int:
    service = TimerService.load(args.db)
    payload = service.overlay_payload(_selected_from_args(args), comparison_mode=args.mode)
    print(json.dumps(payload.to_dict(), indent=2, sort_keys=True))
    return 0


def _cmd_overlay_text(args: argparse.Namespace) -> int:
    service = TimerService.load(args.db)
    payload = service.overlay_payload(_selected_from_args(args), comparison_mode=args.mode)
    print(format_final_overlay_text(payload))
    return 0


def _cmd_ignore_run(args: argparse.Namespace) -> int:
    service = TimerService.load(args.db)
    run = service.set_ignored(args.run_id, True)
    service.save(args.db)
    print(f"Ignored {run.id}")
    return 0


def _cmd_unignore_run(args: argparse.Namespace) -> int:
    service = TimerService.load(args.db)
    run = service.set_ignored(args.run_id, False)
    service.save(args.db)
    print(f"Unignored {run.id}")
    return 0


def _cmd_delete_run(args: argparse.Namespace) -> int:
    service = TimerService.load(args.db)
    service.delete_run(args.run_id)
    service.save(args.db)
    print(f"Deleted {args.run_id}")
    return 0


def _selected_from_args(args: argparse.Namespace) -> SelectedRunInput:
    capture_time = args.capture_time
    capture_time_source = None
    if capture_time:
        capture_time_source = "manual"
    else:
        capture_time = filename_capture_time(args.filename)
        if capture_time:
            capture_time_source = FILENAME_CAPTURE_TIME_SOURCE
    if capture_time is None and args.source_path:
        try:
            capture_time = filesystem_created_time(args.source_path)
        except OSError as exc:
            raise ValueError(f"could not read source file creation time: {exc}") from exc
        capture_time_source = FILESYSTEM_CREATED_SOURCE
    return SelectedRunInput(
        course_id=args.course,
        filename=args.filename,
        source_fps=args.fps,
        markers=tuple(_read_marker_csv(args.markers)),
        clip_id=args.clip_id,
        run_date=args.date,
        capture_time=capture_time,
        capture_time_source=capture_time_source,
        source_path=args.source_path,
    )


def _media_files_by_name(media_roots: list[Path]) -> dict[str, list[Path]]:
    by_name: dict[str, list[Path]] = {}
    for root in media_roots:
        if not root.exists():
            raise ValueError(f"media root not found: {root}")
        if root.is_file():
            by_name.setdefault(root.name, []).append(root)
            continue
        for path in root.rglob("*"):
            if path.is_file():
                by_name.setdefault(path.name, []).append(path)
    return by_name


def _matching_media_paths(
    filename: str,
    source_path: str | None,
    media_index: dict[str, list[Path]],
) -> list[Path]:
    if source_path:
        path = Path(source_path)
        if path.exists() and path.is_file():
            return [path]
    return media_index.get(filename, [])


def _read_marker_csv(path: str | Path) -> list[RawMarker]:
    csv_path = Path(path)
    try:
        handle = csv_path.open("r", newline="", encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"could not read marker CSV {csv_path}: {exc}") from exc
    with handle:
        reader = csv.DictReader(handle)
        missing = {"name", "frame"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"marker CSV missing columns: {', '.join(sorted(missing))}")
        markers: list[RawMarker] = []
        for row_number, row in enumerate(reader, start=2):
            name = (row["name"] or "").strip()
            if not name:
                raise ValueError(f"{csv_path}: row {row_number} missing marker name")
            try:
                frame = int(row["frame"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{csv_path}: row {row_number} invalid frame {row['frame']!r}") from exc
            markers.append(RawMarker(name, frame))
        return markers


def _run_flags(committed: bool, ignored: bool) -> str:
    flags = []
    flags.append("committed" if committed else "uncommitted")
    if ignored:
        flags.append("ignored")
    return ",".join(flags)


if __name__ == "__main__":
    raise SystemExit(main())
