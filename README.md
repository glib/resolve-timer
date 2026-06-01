# Resolve Timer

DaVinci Resolve Studio timing tool for mountain bike race-run comparison.

The core package is pure Python and testable outside Resolve. Resolve-specific access is isolated behind adapter, UI, and overlay modules so API behavior can be validated incrementally inside Resolve Studio.

The current implementation is a tested core and CLI workflow. The in-Resolve interactive UI and Fusion overlay writer are still under live Resolve validation.

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

## Resolve API Probe

Before implementing or debugging the in-Resolve UI/overlay path, run
`scripts/ResolveProbe.py` from Resolve's Python environment with a timeline item
selected. It writes `resolve_probe.json` with Resolve version, selected item,
source clip, marker, FPS, and frame-domain fields. Use that artifact to validate
the adapter assumptions before changing Fusion or UI code.

## CLI Smoke Tests

```powershell
resolve-timer --db examples/timer_db.yaml courses
resolve-timer --db examples/timer_db.yaml add-course --id lower_whistler_a_line --name "Lower Whistler A-Line" --sectors 4
resolve-timer --db examples/timer_db.yaml validate-db
resolve-timer --db examples/timer_db.yaml normalize-db
resolve-timer --db examples/timer_db.yaml preview --course lower_whistler_a_line --markers markers.csv --filename GX010123.MP4 --fps 59.94
resolve-timer --db examples/timer_db.yaml preview --course lower_whistler_a_line --markers markers.csv --filename GX010123.MP4 --fps 59.94 --json
resolve-timer --db examples/timer_db.yaml commit --course lower_whistler_a_line --markers markers.csv --filename GX010123.MP4 --fps 59.94
resolve-timer --db examples/timer_db.yaml update-run --course lower_whistler_a_line --markers markers.csv --filename GX010123.MP4 --fps 59.94 run_2026_05_31_001
resolve-timer --db examples/timer_db.yaml runs --course lower_whistler_a_line
resolve-timer --db examples/timer_db.yaml stats --course lower_whistler_a_line
resolve-timer --db examples/timer_db.yaml stats --course lower_whistler_a_line --json
resolve-timer --db examples/timer_db.yaml ignore-run run_2026_05_31_001
resolve-timer --db examples/timer_db.yaml unignore-run run_2026_05_31_001
resolve-timer --db examples/timer_db.yaml overlay-payload --course lower_whistler_a_line --markers markers.csv --filename GX010123.MP4 --fps 59.94 --mode best_lap
resolve-timer --db examples/timer_db.yaml overlay-text --course lower_whistler_a_line --markers markers.csv --filename GX010123.MP4 --fps 59.94 --mode best_lap
```

Marker CSV files need `name,frame` columns.
