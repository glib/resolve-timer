from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import SCHEMA_VERSION, Course, RunRecord


class DatabaseError(ValueError):
    pass


class TimerDatabase:
    def __init__(self, courses: list[Course] | None = None, runs: list[RunRecord] | None = None):
        self.courses = courses or []
        self.runs = runs or []

    @classmethod
    def load(cls, path: str | Path) -> "TimerDatabase":
        db_path = Path(path)
        if not db_path.exists():
            return cls()
        with db_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        version = raw.get("schema_version")
        if version != SCHEMA_VERSION:
            raise DatabaseError(f"unsupported schema_version {version!r}; expected {SCHEMA_VERSION}")
        return cls(
            courses=[Course.from_dict(item) for item in raw.get("courses", [])],
            runs=[RunRecord.from_dict(item) for item in raw.get("runs", [])],
        )

    def save(self, path: str | Path) -> None:
        db_path = Path(path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = db_path.with_name(f"{db_path.name}.tmp")
        data: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "courses": [course.to_dict() for course in self.courses],
            "runs": [run.to_dict() for run in self.runs],
        }
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(data, handle, sort_keys=False)
            tmp_path.replace(db_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def course_by_id(self, course_id: str) -> Course:
        for course in self.courses:
            if course.id == course_id:
                return course
        raise DatabaseError(f"course not found: {course_id}")

    def upsert_run(self, run: RunRecord) -> None:
        for index, existing in enumerate(self.runs):
            if existing.id == run.id:
                self.runs[index] = run
                return
        self.runs.append(run)
