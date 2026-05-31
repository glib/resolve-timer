# Resolve Timer

Interactive DaVinci Resolve Studio timing tool for mountain bike race-run comparison.

The core package is pure Python and testable outside Resolve. Resolve-specific access is isolated behind adapter, UI, and overlay modules so API behavior can be validated incrementally inside Resolve Studio.

## Project Shape

- `src/resolve_timer/`: timing, marker validation, YAML database, stats, matching, and Resolve-facing adapters.
- `scripts/ResolveTimer.py`: thin Resolve script entrypoint.
- `tests/`: standard-library `unittest` coverage for pure-Python behavior.
- `examples/timer_db.yaml`: editable starter database.

## Current V1 Decisions

- Marker snapshots use source-local frames.
- User selects a timeline item; source markers are read from the linked source clip.
- Timing uses source FPS decimal math: `seconds = frame_delta / source_fps`.
- For `sector_count: N`, required markers are `Start`, `S1..S(N-1)`, `Finish`.
- Comparisons use committed, non-ignored, course-valid runs only.
- Ties resolve to earliest committed run.
- Generated overlays span from race `Start` to the selected timeline item end and freeze after `Finish`.

## Running Tests

```powershell
python -m unittest discover -s tests
```

`PyYAML` is required for YAML read/write.

## CLI Smoke Tests

```powershell
resolve-timer --db examples/timer_db.yaml courses
resolve-timer --db examples/timer_db.yaml preview --course lower_whistler_a_line --markers markers.csv --filename GX010123.MP4 --fps 59.94
resolve-timer --db examples/timer_db.yaml overlay-payload --course lower_whistler_a_line --markers markers.csv --filename GX010123.MP4 --fps 59.94 --mode best_lap
```

Marker CSV files need `name,frame` columns.
