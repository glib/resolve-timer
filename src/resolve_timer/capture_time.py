from __future__ import annotations

from datetime import date, datetime, time, timezone, tzinfo
import re
from pathlib import Path
from typing import Any


FILENAME_CAPTURE_TIME_SOURCE = "filename_timestamp"
CAPTURE_TIME_SOURCES = {
    "filesystem_created",
    FILENAME_CAPTURE_TIME_SOURCE,
    "date_fallback",
    "manual",
}
DATE_FALLBACK_SOURCE = "date_fallback"
FILESYSTEM_CREATED_SOURCE = "filesystem_created"
MANUAL_SOURCE = "manual"

_DJI_FILENAME_CAPTURE_TIME = re.compile(
    r"^DJI_(?P<timestamp>\d{14})_\d+_[^.]+(?:\.[^.]+)?$",
    re.IGNORECASE,
)


def normalize_capture_time(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed_date = date.fromisoformat(text)
            parsed = datetime.combine(parsed_date, time.min)
    return _utc_timestamp(parsed)


def capture_time_from_date(run_date: str | None) -> str | None:
    if not run_date:
        return None
    parsed = date.fromisoformat(str(run_date))
    return _utc_timestamp(datetime.combine(parsed, time(23, 59, 59)))


def effective_capture_time(capture_time: str | None, run_date: str | None) -> str | None:
    normalized = normalize_capture_time(capture_time)
    if normalized is not None:
        return normalized
    return capture_time_from_date(run_date)


def capture_date(capture_time: str | None) -> str | None:
    normalized = normalize_capture_time(capture_time)
    if normalized is None:
        return None
    return normalized[:10]


def filesystem_created_time(path: str | Path) -> str:
    stat = Path(path).stat()
    return _utc_timestamp(datetime.fromtimestamp(stat.st_ctime, timezone.utc))


def filename_capture_time(
    filename: str | Path,
    *,
    local_timezone: tzinfo | None = None,
) -> str | None:
    """Return a DJI filename's embedded local capture time as UTC.

    DJI filenames use ``DJI_YYYYMMDDHHMMSS_sequence_type.ext``. Camera time is
    local time, so production uses the computer's local timezone. Tests and
    callers that know the camera timezone can supply it explicitly.
    """
    match = _DJI_FILENAME_CAPTURE_TIME.fullmatch(Path(filename).name)
    if match is None:
        return None
    try:
        parsed = datetime.strptime(match.group("timestamp"), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    if local_timezone is None:
        parsed = parsed.astimezone()
    else:
        parsed = parsed.replace(tzinfo=local_timezone)
    return _utc_timestamp(parsed)


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")
