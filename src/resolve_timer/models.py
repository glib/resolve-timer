from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from .capture_time import (
    DATE_FALLBACK_SOURCE,
    capture_time_from_date,
    normalize_capture_time,
)


SCHEMA_VERSION = 2


@dataclass(frozen=True)
class Course:
    id: str
    name: str
    sector_count: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Course":
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            sector_count=int(data["sector_count"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "sector_count": self.sector_count}


@dataclass(frozen=True)
class RawMarker:
    name: str
    frame: int


@dataclass(frozen=True)
class MarkerSnapshot:
    frames: dict[str, int]

    def ordered_items(self) -> list[tuple[str, int]]:
        return sorted(self.frames.items(), key=lambda item: item[1])


@dataclass(frozen=True)
class SectorTiming:
    sector: int
    start_marker: str
    end_marker: str
    start_frame: int
    end_frame: int
    duration_frames: int
    duration_seconds: float


@dataclass(frozen=True)
class TimingResult:
    sectors: tuple[SectorTiming, ...]
    lap_frames: int
    lap_seconds: float


@dataclass
class RunRecord:
    id: str
    course_id: str
    date: str
    filename: str
    source_fps: float
    marker_frames: dict[str, int]
    capture_time: str | None = None
    capture_time_source: str | None = None
    source_path: str | None = None
    clip_id: str | None = None
    fingerprint: str | None = None
    committed: bool = True
    ignored: bool = False
    committed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunRecord":
        run_date = str(data.get("date") or date.today().isoformat())
        capture_time = normalize_capture_time(data.get("capture_time"))
        capture_time_source = data.get("capture_time_source")
        if capture_time is None:
            capture_time = capture_time_from_date(run_date)
            capture_time_source = capture_time_source or DATE_FALLBACK_SOURCE
        return cls(
            id=str(data["id"]),
            course_id=str(data["course_id"]),
            date=run_date,
            filename=str(data.get("filename") or ""),
            source_fps=float(data["source_fps"]),
            marker_frames={str(k): int(v) for k, v in data["marker_frames"].items()},
            capture_time=capture_time,
            capture_time_source=(
                None if capture_time_source in (None, "") else str(capture_time_source)
            ),
            source_path=(
                None if data.get("source_path") in (None, "") else str(data.get("source_path"))
            ),
            clip_id=data.get("clip_id"),
            fingerprint=data.get("fingerprint"),
            committed=bool(data.get("committed", True)),
            ignored=bool(data.get("ignored", False)),
            committed_at=data.get("committed_at"),
            metadata=dict(data.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "course_id": self.course_id,
            "date": self.date,
            "filename": self.filename,
            "source_fps": self.source_fps,
            "committed": self.committed,
            "ignored": self.ignored,
            "marker_frames": dict(sorted(self.marker_frames.items())),
        }
        if self.capture_time:
            data["capture_time"] = self.capture_time
        if self.capture_time_source:
            data["capture_time_source"] = self.capture_time_source
        if self.source_path:
            data["source_path"] = self.source_path
        if self.clip_id:
            data["clip_id"] = self.clip_id
        if self.fingerprint:
            data["fingerprint"] = self.fingerprint
        if self.committed_at:
            data["committed_at"] = self.committed_at
        if self.metadata:
            data["metadata"] = self.metadata
        return data


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
