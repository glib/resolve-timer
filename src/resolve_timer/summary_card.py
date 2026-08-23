from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import Course
from .stats import CourseStats
from .timing import format_duration


DRAW_SIZE = (1920, 1080)
CARD_SIZE = (3840, 2160)


@dataclass(frozen=True)
class SummaryFastestSector:
    sector: int
    duration: str
    run_id: str
    date: str


@dataclass(frozen=True)
class SummaryRun:
    rank: int
    run_id: str
    date: str
    lap: str
    filename: str


@dataclass(frozen=True)
class CourseSummaryPayload:
    course_id: str
    course_name: str
    eligible_run_count: int
    date_range: str
    best_lap: str
    best_lap_run_id: str | None
    best_lap_date: str | None
    optimal_lap: str
    fastest_sectors: tuple[SummaryFastestSector, ...]
    top_runs: tuple[SummaryRun, ...]


def build_course_summary_payload(course: Course, stats: CourseStats) -> CourseSummaryPayload:
    eligible = stats.eligible_runs
    dates = sorted({item.run.date for item in eligible if item.run.date})
    if not dates:
        date_range = "-"
    elif len(dates) == 1:
        date_range = dates[0]
    else:
        date_range = f"{dates[0]} to {dates[-1]}"

    best_lap = stats.best_lap
    top_runs = sorted(
        eligible,
        key=lambda item: (
            item.timing.lap_seconds,
            item.run.date or "",
            item.run.id,
        ),
    )[:5]

    return CourseSummaryPayload(
        course_id=course.id,
        course_name=course.name,
        eligible_run_count=len(eligible),
        date_range=date_range,
        best_lap="--:--.---" if best_lap is None else format_duration(best_lap.timing.lap_seconds),
        best_lap_run_id=None if best_lap is None else best_lap.run.id,
        best_lap_date=None if best_lap is None else best_lap.run.date,
        optimal_lap=(
            "--:--.---"
            if stats.optimal_seconds is None
            else format_duration(stats.optimal_seconds)
        ),
        fastest_sectors=tuple(
            SummaryFastestSector(
                sector=sector.sector,
                duration=format_duration(sector.duration_seconds),
                run_id=sector.run.id,
                date=sector.run.date,
            )
            for sector in stats.fastest_sectors
        ),
        top_runs=tuple(
            SummaryRun(
                rank=index,
                run_id=item.run.id,
                date=item.run.date,
                lap=format_duration(item.timing.lap_seconds),
                filename=item.run.filename,
            )
            for index, item in enumerate(top_runs, start=1)
        ),
    )


def default_summary_card_path(
    database_path: str | Path,
    course_id: str,
    *,
    now: datetime | None = None,
    output_directory: str | Path | None = None,
) -> Path:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    safe_course_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", course_id).strip("._") or "course"
    directory = (
        Path(output_directory)
        if output_directory is not None
        else Path(database_path).parent
    )
    return directory / f"resolve_timer_summary_{safe_course_id}_{stamp}.png"


def render_course_summary_card(payload: CourseSummaryPayload, output_path: str | Path) -> Path:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("Pillow is required to export summary PNGs") from exc

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGB", DRAW_SIZE, "#071014")
    draw = ImageDraw.Draw(image)

    fonts = _fonts(ImageFont)
    palette = {
        "bg2": "#0d1b20",
        "line": "#23414a",
        "text": "#e7f7f5",
        "muted": "#86a7ad",
        "cyan": "#1ff4ff",
        "green": "#79ff8b",
        "amber": "#ffc857",
        "red": "#ff4d6d",
    }

    _draw_grid(draw, palette)
    _draw_header(draw, payload, fonts, palette)
    _draw_metric_boxes(draw, payload, fonts, palette)
    _draw_sector_table(draw, payload, fonts, palette)
    _draw_leaderboard(draw, payload, fonts, palette)

    if payload.eligible_run_count == 0:
        _draw_no_runs(draw, fonts, palette)

    image = image.resize(CARD_SIZE, Image.Resampling.LANCZOS)
    image.save(output, format="PNG")
    return output


def _fonts(image_font):
    def load(size: int, bold: bool = False):
        candidates = (
            "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
            "Arial Bold.ttf" if bold else "Arial.ttf",
        )
        for candidate in candidates:
            try:
                return image_font.truetype(candidate, size=size)
            except OSError:
                continue
        return image_font.load_default()

    return {
        "title": load(74, True),
        "subtitle": load(30),
        "label": load(24, True),
        "metric": load(48, True),
        "body": load(28),
        "body_bold": load(28, True),
        "small": load(22),
        "small_bold": load(22, True),
    }


def _draw_grid(draw, palette) -> None:
    for x in range(0, DRAW_SIZE[0], 120):
        draw.line([(x, 0), (x, DRAW_SIZE[1])], fill="#0b252c", width=1)
    for y in range(0, DRAW_SIZE[1], 90):
        draw.line([(0, y), (DRAW_SIZE[0], y)], fill="#0b252c", width=1)
    draw.rectangle([36, 36, 1884, 1044], outline=palette["line"], width=3)
    draw.line([(60, 160), (1860, 160)], fill=palette["cyan"], width=2)


def _draw_header(draw, payload, fonts, palette) -> None:
    _fit_text(draw, (70, 52), payload.course_name, fonts["title"], palette["text"], 1380)
    _fit_text(
        draw,
        (72, 126),
        f"COURSE ID  {payload.course_id}",
        fonts["subtitle"],
        palette["cyan"],
        1000,
    )
    _fit_text(
        draw,
        (1390, 84),
        "RESOLVE TIMER SUMMARY",
        fonts["label"],
        palette["muted"],
        430,
        anchor="ra",
    )


def _draw_metric_boxes(draw, payload, fonts, palette) -> None:
    boxes = [
        ("ELIGIBLE RUNS", str(payload.eligible_run_count), palette["cyan"]),
        ("DATE RANGE", payload.date_range, palette["amber"]),
        ("BEST LAP", payload.best_lap, palette["green"]),
        ("OPTIMAL LAP", payload.optimal_lap, palette["red"]),
    ]
    x = 70
    for label, value, color in boxes:
        draw.rectangle([x, 205, x + 410, 355], fill=palette["bg2"], outline=palette["line"], width=2)
        _fit_text(draw, (x + 24, 226), label, fonts["label"], palette["muted"], 360)
        _fit_text(draw, (x + 24, 266), value, fonts["metric"], color, 360)
        x += 445
    if payload.best_lap_run_id:
        _fit_text(
            draw,
            (980, 333),
            f"{payload.best_lap_run_id}  {payload.best_lap_date}",
            fonts["small"],
            palette["muted"],
            360,
        )


def _draw_sector_table(draw, payload, fonts, palette) -> None:
    left, top, right, bottom = 70, 410, 830, 960
    draw.rectangle([left, top, right, bottom], fill=palette["bg2"], outline=palette["line"], width=2)
    _fit_text(draw, (left + 24, top + 22), "FASTEST SECTORS", fonts["label"], palette["cyan"], 360)
    headers = ("SECTOR", "TIME", "RUN", "DATE")
    xs = (left + 24, left + 160, left + 310, left + 555)
    y = top + 82
    for header, x in zip(headers, xs):
        _fit_text(draw, (x, y), header, fonts["small_bold"], palette["muted"], 170)
    y += 38
    draw.line([(left + 24, y), (right - 24, y)], fill=palette["line"], width=2)
    y += 22
    for sector in payload.fastest_sectors:
        values = (f"S{sector.sector}", sector.duration, sector.run_id, sector.date)
        for value, x, width in zip(values, xs, (100, 120, 215, 170)):
            _fit_text(draw, (x, y), value, fonts["body"], palette["text"], width)
        y += 50
        if y > bottom - 46:
            break


def _draw_leaderboard(draw, payload, fonts, palette) -> None:
    left, top, right, bottom = 880, 410, 1850, 960
    draw.rectangle([left, top, right, bottom], fill=palette["bg2"], outline=palette["line"], width=2)
    _fit_text(draw, (left + 24, top + 22), "TOP 5 RUNS", fonts["label"], palette["cyan"], 260)
    headers = ("#", "RUN", "DATE", "LAP", "FILENAME")
    xs = (left + 24, left + 78, left + 300, left + 500, left + 665)
    widths = (42, 190, 170, 135, 260)
    y = top + 82
    for header, x, width in zip(headers, xs, widths):
        _fit_text(draw, (x, y), header, fonts["small_bold"], palette["muted"], width)
    y += 38
    draw.line([(left + 24, y), (right - 24, y)], fill=palette["line"], width=2)
    y += 22
    for run in payload.top_runs:
        color = palette["green"] if run.rank == 1 else palette["text"]
        values = (str(run.rank), run.run_id, run.date, run.lap, run.filename)
        for value, x, width in zip(values, xs, widths):
            _fit_text(draw, (x, y), value, fonts["body"], color, width)
        y += 68


def _draw_no_runs(draw, fonts, palette) -> None:
    text = "NO ELIGIBLE RUNS"
    detail = "Committed, non-ignored runs with valid timing will appear here."
    draw.rectangle([370, 520, 1550, 680], fill="#10262c", outline=palette["amber"], width=2)
    _fit_text(draw, (960, 558), text, fonts["metric"], palette["amber"], 900, anchor="ma")
    _fit_text(draw, (960, 625), detail, fonts["body"], palette["muted"], 980, anchor="ma")


def _fit_text(draw, xy, text: str, font, fill: str, max_width: int, *, anchor: str | None = None) -> None:
    value = _ellipsize(draw, str(text), font, max_width)
    draw.text(xy, value, font=font, fill=fill, anchor=anchor)


def _ellipsize(draw, text: str, font, max_width: int) -> str:
    if _text_width(draw, text, font) <= max_width:
        return text
    ellipsis = "..."
    available = max(0, max_width - _text_width(draw, ellipsis, font))
    result = ""
    for char in text:
        if _text_width(draw, result + char, font) > available:
            break
        result += char
    return result.rstrip() + ellipsis


def _text_width(draw, text: str, font) -> int:
    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
    return right - left
