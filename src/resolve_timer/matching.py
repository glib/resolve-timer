from __future__ import annotations

import hashlib
import json

from .models import MarkerSnapshot, RunRecord


def marker_snapshot_hash(marker_frames: dict[str, int] | MarkerSnapshot) -> str:
    frames = marker_frames.frames if isinstance(marker_frames, MarkerSnapshot) else marker_frames
    payload = json.dumps(dict(sorted(frames.items())), separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def clip_fingerprint(filename: str, marker_frames: dict[str, int] | MarkerSnapshot) -> str:
    marker_hash = marker_snapshot_hash(marker_frames)
    return f"{filename}:{marker_hash}"


def find_matching_run(
    runs: list[RunRecord],
    *,
    course_id: str,
    filename: str,
    marker_frames: dict[str, int] | MarkerSnapshot,
    clip_id: str | None = None,
) -> RunRecord | None:
    course_runs = [run for run in runs if run.course_id == course_id]
    if clip_id:
        by_clip = [run for run in course_runs if run.clip_id == clip_id]
        if by_clip:
            return _earliest(by_clip)

    fingerprint = clip_fingerprint(filename, marker_frames)
    by_fingerprint = [run for run in course_runs if run.fingerprint == fingerprint]
    if by_fingerprint:
        return _earliest(by_fingerprint)
    return None


def _earliest(runs: list[RunRecord]) -> RunRecord:
    return sorted(runs, key=lambda run: (run.committed_at or run.date or "", run.id))[0]
