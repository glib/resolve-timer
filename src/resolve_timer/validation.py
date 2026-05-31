from __future__ import annotations

from collections import Counter

from .database import TimerDatabase
from .markers import MarkerValidationError, parse_marker_snapshot
from .models import RawMarker
from .timing import compute_timing


def validate_database(database: TimerDatabase) -> list[str]:
    errors: list[str] = []

    course_ids = [course.id for course in database.courses]
    for course_id, count in Counter(course_ids).items():
        if count > 1:
            errors.append(f"duplicate course id: {course_id}")

    courses_by_id = {course.id: course for course in database.courses}
    for course in database.courses:
        if course.sector_count < 1:
            errors.append(f"course {course.id} sector_count must be at least 1")

    run_ids = [run.id for run in database.runs]
    for run_id, count in Counter(run_ids).items():
        if count > 1:
            errors.append(f"duplicate run id: {run_id}")

    for run in database.runs:
        course = courses_by_id.get(run.course_id)
        if course is None:
            errors.append(f"run {run.id} references missing course {run.course_id}")
            continue
        if run.source_fps <= 0:
            errors.append(f"run {run.id} source_fps must be greater than 0")
            continue
        try:
            markers = [RawMarker(name, frame) for name, frame in run.marker_frames.items()]
            snapshot = parse_marker_snapshot(markers, course)
            compute_timing(snapshot, course, run.source_fps)
        except MarkerValidationError as exc:
            for marker_error in exc.errors:
                errors.append(f"run {run.id}: {marker_error}")
        except ValueError as exc:
            errors.append(f"run {run.id}: {exc}")

    return errors
