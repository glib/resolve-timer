from __future__ import annotations

import argparse
import csv
from pathlib import Path

from .database import TimerDatabase
from .models import RawMarker
from .service import SelectedRunInput, TimerService
from .timing import format_duration


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="resolve-timer")
    parser.add_argument("--db", default="timer_db.yaml", help="Path to timer YAML database")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_courses = subparsers.add_parser("courses", help="List configured courses")
    list_courses.set_defaults(func=_cmd_courses)

    preview = subparsers.add_parser("preview", help="Preview timing from a marker CSV")
    _add_selected_args(preview)
    preview.set_defaults(func=_cmd_preview)

    commit = subparsers.add_parser("commit", help="Commit a new run from a marker CSV")
    _add_selected_args(commit)
    commit.add_argument("--run-id")
    commit.set_defaults(func=_cmd_commit)

    args = parser.parse_args(argv)
    return args.func(args)


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


def _cmd_preview(args: argparse.Namespace) -> int:
    service = TimerService.load(args.db)
    selected = _selected_from_args(args)
    preview = service.preview(selected)
    print(f"Course: {preview.course.name}")
    print(f"Lap: {format_duration(preview.timing.lap_seconds)}")
    for sector in preview.timing.sectors:
        print(f"S{sector.sector}: {format_duration(sector.duration_seconds)}")
    if preview.stats.best_lap:
        print(f"Best: {format_duration(preview.stats.best_lap.timing.lap_seconds)}")
    if preview.stats.optimal_seconds is not None:
        print(f"Optimal: {format_duration(preview.stats.optimal_seconds)}")
    if preview.matching_run:
        state = "changed" if preview.has_marker_changes else "matched"
        print(f"History: {state} {preview.matching_run.id}")
    else:
        print("History: no committed run")
    return 0


def _cmd_commit(args: argparse.Namespace) -> int:
    service = TimerService.load(args.db)
    run = service.commit_new_run(_selected_from_args(args), run_id=args.run_id)
    service.save(args.db)
    print(f"Committed {run.id}")
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
    with Path(path).open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = {"name", "frame"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"marker CSV missing columns: {', '.join(sorted(missing))}")
        return [RawMarker(row["name"], int(row["frame"])) for row in reader]


if __name__ == "__main__":
    raise SystemExit(main())
