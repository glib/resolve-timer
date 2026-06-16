# Resolve Timer

DaVinci Resolve Studio timing tool for comparing mountain bike race runs and
building Fusion/Text+ overlays from source clip markers.

The project keeps Resolve-specific code behind small adapter, UI, and overlay
modules. The timing, database, matching, and CLI code can be tested outside
Resolve with the standard Python test runner.

## What It Does

- Reads timing markers from one selected Media Pool clip.
- Previews sector and lap times for a selected course.
- Commits, updates, ignores, unignores, and deletes runs in a YAML database.
- Compares the current run against best lap, optimal lap, or a matching run.
- Creates or updates a Fusion/Text+ overlay on the timeline clip under the
  playhead, or across all valid video clips in the current timeline.

## Marker Rules

Markers are read from the source media, not from the timeline. Timeline
selection and playhead position do not affect the Media Pool timing preview.

For a course with `sector_count: N`, add these source clip markers:

- `Start`
- `S1` through `S(N-1)`
- `Finish`

Timing uses the source clip frame rate:

```text
seconds = frame_delta / source_fps
```

## Install For Resolve

Run these from the project root in PowerShell:

```powershell
.\scripts\Install-ResolveDependencies.ps1
.\scripts\Install-ResolveScripts.ps1
```

Then restart Resolve and run `Resolve Timer` from `Workspace > Scripts`.

The installer creates lightweight Resolve launchers that point back to this
checkout, so code changes are picked up without reinstalling. On first install
it also creates `timer_db.yaml` from `examples/timer_db.yaml`; later installs do
not overwrite your database.

## Using The Resolve Tool

1. Select exactly one marked clip in the Media Pool.
2. Choose a course in Resolve Timer.
3. Use `Refresh Preview` to read markers and calculate timing.
4. Commit a new run, update the matching run, or manage existing runs.
5. Put the timeline playhead over a matching video clip and use `Update Clip
   Under Playhead` to write the overlay.
6. Use `Update All Timeline Clips` to update every valid video clip in the
   current timeline.

The overlay starts at the source `Start` marker, advances using Fusion item
time, and freezes at `Finish`. Sector rows reveal at their marker crossings, and
the lap row reveals at `Finish`.

## Project Files

- `timer_db.yaml`: your local course and run database.
- `resolve_timer_preferences.json`: last selected course and comparison mode.
- `resolve_timer_startup.json`: latest Resolve startup diagnostics.
- `resolve_timer.log`: unexpected startup or controller tracebacks.
- `examples/timer_db.yaml`: starter database template.

Local runtime files are ignored by Git.

## CLI

Install the package in a Python environment, then run:

```powershell
resolve-timer --db examples/timer_db.yaml courses
resolve-timer --db examples/timer_db.yaml validate-db
resolve-timer --db examples/timer_db.yaml normalize-db
resolve-timer --db examples/timer_db.yaml preview --course lower_whistler_a_line --markers examples/markers.csv --filename GX010123.MP4 --fps 59.94
resolve-timer --db examples/timer_db.yaml commit --course lower_whistler_a_line --markers examples/markers.csv --filename GX010123.MP4 --fps 59.94
resolve-timer --db examples/timer_db.yaml runs --course lower_whistler_a_line
resolve-timer --db examples/timer_db.yaml stats --course lower_whistler_a_line
resolve-timer --db examples/timer_db.yaml overlay-text --course lower_whistler_a_line --markers examples/markers.csv --filename GX010123.MP4 --fps 59.94 --mode best_lap
```

Marker CSV files need `name,frame` columns.

## Development

Run the test suite with:

```powershell
python -m unittest discover -s tests
```

`PyYAML` is required for YAML read/write.
