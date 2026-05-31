from __future__ import annotations

import re
from collections import Counter

from .models import Course, MarkerSnapshot, RawMarker

SECTOR_RE = re.compile(r"^S([1-9][0-9]*)$")


class MarkerValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def expected_marker_names(course: Course) -> list[str]:
    if course.sector_count < 1:
        raise ValueError("sector_count must be at least 1")
    sectors = [f"S{i}" for i in range(1, course.sector_count)]
    return ["Start", *sectors, "Finish"]


def parse_marker_snapshot(markers: list[RawMarker], course: Course) -> MarkerSnapshot:
    """Validate timing markers and return source-local marker frames."""
    expected = expected_marker_names(course)
    expected_set = set(expected)
    timing_markers = [
        marker
        for marker in markers
        if marker.name in {"Start", "Finish"} or SECTOR_RE.match(marker.name)
    ]

    errors: list[str] = []
    names = [marker.name for marker in timing_markers]
    counts = Counter(names)

    for name in expected:
        if counts[name] == 0:
            errors.append(f"missing marker {name}")
        elif counts[name] > 1:
            errors.append(f"duplicate marker {name}")

    for name in sorted(set(names) - expected_set, key=_marker_sort_key):
        errors.append(f"unexpected marker {name}")

    if errors:
        raise MarkerValidationError(errors)

    frames = {marker.name: int(marker.frame) for marker in timing_markers}
    previous_name = expected[0]
    previous_frame = frames[previous_name]
    for name in expected[1:]:
        frame = frames[name]
        if frame <= previous_frame:
            errors.append(
                f"marker {name} frame {frame} must be after {previous_name} frame {previous_frame}"
            )
        previous_name = name
        previous_frame = frame

    if errors:
        raise MarkerValidationError(errors)

    return MarkerSnapshot({name: frames[name] for name in expected})


def _marker_sort_key(name: str) -> tuple[int, int | str]:
    if name == "Start":
        return (0, 0)
    match = SECTOR_RE.match(name)
    if match:
        return (1, int(match.group(1)))
    if name == "Finish":
        return (2, 0)
    return (3, name)
