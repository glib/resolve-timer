from __future__ import annotations

from .markers import expected_marker_names
from .models import Course, MarkerSnapshot, SectorTiming, TimingResult


def compute_timing(snapshot: MarkerSnapshot, course: Course, source_fps: float) -> TimingResult:
    if source_fps <= 0:
        raise ValueError("source_fps must be greater than 0")

    expected = expected_marker_names(course)
    missing = [name for name in expected if name not in snapshot.frames]
    if missing:
        raise ValueError(f"snapshot missing markers: {', '.join(missing)}")

    sectors: list[SectorTiming] = []
    for sector in range(1, course.sector_count + 1):
        start_marker = "Start" if sector == 1 else f"S{sector - 1}"
        end_marker = "Finish" if sector == course.sector_count else f"S{sector}"
        start_frame = snapshot.frames[start_marker]
        end_frame = snapshot.frames[end_marker]
        duration_frames = end_frame - start_frame
        if duration_frames <= 0:
            raise ValueError(f"sector {sector} duration must be positive")
        sectors.append(
            SectorTiming(
                sector=sector,
                start_marker=start_marker,
                end_marker=end_marker,
                start_frame=start_frame,
                end_frame=end_frame,
                duration_frames=duration_frames,
                duration_seconds=duration_frames / source_fps,
            )
        )

    lap_frames = snapshot.frames["Finish"] - snapshot.frames["Start"]
    if lap_frames <= 0:
        raise ValueError("lap duration must be positive")

    return TimingResult(
        sectors=tuple(sectors),
        lap_frames=lap_frames,
        lap_seconds=lap_frames / source_fps,
    )


def format_duration(seconds: float) -> str:
    if seconds < 0:
        raise ValueError("duration cannot be negative")
    total_ms = int(round(seconds * 1000))
    minutes, remainder = divmod(total_ms, 60_000)
    whole_seconds, milliseconds = divmod(remainder, 1000)
    return f"{minutes}:{whole_seconds:02d}.{milliseconds:03d}"


def format_delta(seconds: float) -> str:
    total_ms = int(round(abs(seconds) * 1000))
    whole_seconds, milliseconds = divmod(total_ms, 1000)
    sign = "-" if seconds < 0 else "+"
    return f"{sign}{whole_seconds}.{milliseconds:03d}"
