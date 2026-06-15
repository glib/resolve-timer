from __future__ import annotations

import json
import platform
import sys
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class PreferencesError(ValueError):
    pass


@dataclass(frozen=True)
class UserPreferences:
    course_id: str | None = None
    comparison_mode: str = "best_lap"


def load_preferences(path: str | Path) -> UserPreferences:
    preferences_path = Path(path)
    if not preferences_path.exists():
        return UserPreferences()
    try:
        raw = json.loads(preferences_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreferencesError(
            f"could not read preferences {preferences_path}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise PreferencesError(f"preferences {preferences_path} must contain an object")
    course_id = raw.get("course_id")
    if course_id is not None and not isinstance(course_id, str):
        raise PreferencesError("preference course_id must be a string or null")
    comparison_mode = raw.get("comparison_mode", "best_lap")
    if comparison_mode not in {"best_lap", "optimal"}:
        raise PreferencesError(
            "preference comparison_mode must be best_lap or optimal"
        )
    return UserPreferences(course_id=course_id, comparison_mode=comparison_mode)


def save_preferences(path: str | Path, preferences: UserPreferences) -> None:
    preferences_path = Path(path)
    preferences_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = preferences_path.with_name(f"{preferences_path.name}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(asdict(preferences), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(preferences_path)
    except Exception as exc:
        temporary_path.unlink(missing_ok=True)
        raise PreferencesError(
            f"could not write preferences {preferences_path}: {exc}"
        ) from exc


def append_exception_log(
    path: str | Path,
    context: str,
    exc: BaseException,
) -> None:
    log_path = Path(path)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{timestamp}] {context}: {type(exc).__name__}: {exc}\n")
            handle.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
            handle.write("\n")
    except OSError:
        pass


def write_startup_diagnostics(
    path: str | Path,
    *,
    database_path: str | Path,
    preferences_path: str | Path,
    log_path: str | Path,
    resolve: object | None,
    fusion: object | None,
    bmd: object | None,
) -> None:
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "database_path": str(Path(database_path).resolve()),
        "preferences_path": str(Path(preferences_path).resolve()),
        "log_path": str(Path(log_path).resolve()),
        "resolve_injected": resolve is not None,
        "fusion_injected": fusion is not None,
        "bmd_injected": bmd is not None,
        "resolve_version": _resolve_version(resolve),
    }
    _write_json_atomically(path, report)


def _resolve_version(resolve: object | None) -> Any:
    if resolve is None:
        return None
    for method_name in ("GetVersionString", "GetVersion"):
        method = getattr(resolve, method_name, None)
        if callable(method):
            try:
                return method()
            except Exception:
                return None
    return None


def _write_json_atomically(path: str | Path, data: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f"{output_path.name}.tmp")
    try:
        temporary_path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(output_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
