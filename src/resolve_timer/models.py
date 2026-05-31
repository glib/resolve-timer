from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


SCHEMA_VERSION = 1


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
    clip_id: str | None = None
    fingerprint: str | None = None
    committed: bool = True
    ignored: bool = False
    committed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunRecord":
        return cls(
            id=str(data["id"]),
            course_id=str(data["course_id"]),
            date=str(data.get("date") or date.today().isoformat()),
            filename=str(data.get("filename") or ""),
            source_fps=float(data["source_fps"]),
            marker_frames={str(k): int(v) for k, v in data["marker_frames"].items()},
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
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
