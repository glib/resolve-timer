from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .database import DatabaseError, TimerDatabase
from .markers import MarkerValidationError
from .models import RawMarker
from .overlay import format_final_overlay_text
from .service import SelectedRunInput, TimerService
from .stats import compute_course_stats
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

    validate = subparsers.add_parser("validate-db", help="Validate database consistency")
    validate.set_defaults(func=_cmd_validate_db)

    normalize = subparsers.add_parser("normalize-db", help="Fill derived fields in the database")
    normalize.set_defaults(func=_cmd_normalize_db)

    list_runs = subparsers.add_parser("runs", help="List committed run records")
    list_runs.add_argument("--course", help="Only show runs for this course ID")
    list_runs.set_defaults(func=_cmd_runs)

    stats = subparsers.add_parser("stats", help="Show course timing statistics")
    stats.add_argument("--course", required=True, help="Course ID")
    stats.set_defaults(func=_cmd_stats)

    preview = subparsers.add_parser("preview", help="Preview timing from a marker CSV")
    _add_selected_args(preview)
    preview.add_argument("--mode", choices=["best_lap", "optimal"], default="best_lap")
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


def _cmd_preview(args: argparse.Namespace) -> int:
    service = TimerService.load(args.db)
    selected = _selected_from_args(args)
    preview = service.preview(selected)
    print(format_preview_summary(preview, args.mode))
    return 0


def _cmd_commit(args: argparse.Namespace) -> int:
    service = TimerService.load(args.db)
    run = service.commit_new_run(_selected_from_args(args), run_id=args.run_id)
    service.save(args.db)
    print(f"Committed {run.id}")
    return 0


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
    return SelectedRunInput(
        course_id=args.course,
        filename=args.filename,
        source_fps=args.fps,
        markers=tuple(_read_marker_csv(args.markers)),
        clip_id=args.clip_id,
        run_date=args.date,
    )


def _read_marker_csv(path: str | Path) -> list[RawMarker]:
    csv_path = Path(path)
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
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
