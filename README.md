# Resolve Timer

DaVinci Resolve Studio timing tool for mountain bike race-run comparison.

The core package is pure Python and testable outside Resolve. Resolve-specific access is isolated behind adapter, UI, and overlay modules so API behavior can be validated incrementally inside Resolve Studio.

The current implementation includes a tested core, CLI workflow, and in-Resolve
timing/database UI. The UI and Fusion overlay writer are still under live
Resolve validation.

## Project Shape

- `src/resolve_timer/`: timing, marker validation, YAML database, stats, matching, and Resolve-facing adapters.
- `scripts/ResolveTimer.py`: thin Resolve script entrypoint.
- `tests/`: standard-library `unittest` coverage for pure-Python behavior.
- `examples/timer_db.yaml`: editable starter database.

## Current V1 Decisions

- Marker snapshots use source-local frames.
- User selects exactly one clip in the Media Pool.
- Markers, filename, FPS, and clip identity are read directly from that selected
  Media Pool clip.
- Timeline selection and playhead position do not affect timing preview.
- Timing uses source FPS decimal math: `seconds = frame_delta / source_fps`.
- For `sector_count: N`, required markers are `Start`, `S1..S(N-1)`, `Finish`.
- Comparisons use committed, non-ignored, course-valid runs only.
- Ties resolve to earliest committed run.
- Overlay placement and target timeline selection will be validated separately
  during the Fusion overlay phase.

## Running Tests

```powershell
python -m unittest discover -s tests
```

`PyYAML` is required for YAML read/write.

## Resolve API Probe

Before implementing or debugging the in-Resolve UI/overlay path, run
`scripts/ResolveProbe.py` from Resolve's Python environment with exactly one
Media Pool clip selected. It writes `resolve_probe.json` with Resolve version,
Media Pool selection, marker, FPS, and timeline diagnostic fields.

See `ACCEPTANCE.md` for the phase gates and manual Resolve validation matrix.

## Durable Resolve Installation (Windows)

The entrypoint scripts add this checkout's `src` directory to Resolve's Python
path, so the package does not need to be installed into Resolve's Python
environment. Resolve runtime dependencies are installed into an isolated,
project-local directory. Install them and the lightweight launchers with:

```powershell
.\scripts\Install-ResolveDependencies.ps1
.\scripts\Install-ResolveScripts.ps1
```

The launchers expose only `.resolve_deps` and this checkout's `src` directory to
Resolve. They do not depend on globally installed packages or the development
virtual environment.

Then restart Resolve. Resolve may flatten the special `Utility` directory in its
menu rather than displaying a `Utility` submenu. With a timeline clip selected,
find `Resolve Timer` under `Workspace > Scripts` and run `ResolveProbe`.

The probe writes `resolve_probe.json` in this project directory. The launchers
execute the scripts in this checkout, so edits are available immediately; no
recopy is required. On first install, the installer also creates `timer_db.yaml`
from the example. Later installs do not overwrite that data.

`ResolveTimer` opens the Phase 3 workflow for live validation. It supports
selection refresh, timing previews, commit/update, ignore/unignore, delete, and
course-filtered run management. `Update Overlay` now creates or updates the
Fusion/Text+ overlay on the matching timeline item.

The tool also maintains three project-local runtime files:

- `resolve_timer_preferences.json`: last selected course and comparison mode.
- `resolve_timer_startup.json`: Python, Resolve, and path diagnostics from the
  latest launch.
- `resolve_timer.log`: tracebacks for unexpected startup or controller errors.

These files are separate from `timer_db.yaml` and are ignored by Git.

## Fusion Static Overlay Probe

Before enabling `Update Overlay` in the main window, validate the static
Fusion/Text+ path:

1. Select exactly one Media Pool clip with valid timing markers.
2. Put the timeline playhead over the matching video item.
3. Run `ResolveFusionProbe` from `Workspace > Scripts`.

The probe refuses to modify the timeline when the selected Media Pool clip and
current timeline item do not match. On success it creates or updates one Fusion
comp named `Resolve Timer - <course_id>` on the timeline item, preserves the
existing MediaIn/MediaOut flow, and adds named Text+ and Merge tools. Results are
written to `resolve_fusion_probe.json`.

Run the probe a second time on the same item. The second result should report
`"comp_created": false` and leave the Fusion comp count unchanged.

This deterministic path has been validated in Resolve 21. The main window uses
the same updater and clip-identity guard. The live timer starts at the source
`Start` marker, advances using Fusion item time, and freezes at `Finish`.
Sector rows reveal at their marker crossings, the lap row reveals at `Finish`,
and the overlay uses aligned monospace text on a blurred translucent panel with
a light border and comparison-aware delta colors. This path has been visually
validated with committed comparison data on the Resolve 21 test timeline.

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
