# Resolve Timer Project Plan

## Goal

Build an interactive DaVinci Resolve Studio tool for mountain bike race-run comparison. The tool reads standardized source clip markers, computes sector/lap timing, stores committed historical runs, calculates best lap and optimal lap comparisons, and generates a polished live timer overlay in the top-right of a 16:9 timeline.

## Target Environment

- DaVinci Resolve Studio, latest version.
- Interactive Resolve Python script/tool.
- Project working folder: `F:\Documents\Resolve Timer`.
- Historical run database stored in project folder as editable YAML.
- One rider.
- 16:9 overlays only.

## Marker Convention

Markers must live on a Media Pool source clip. The user selects exactly one
Media Pool clip and refreshes the tool. Timeline selection, source-view state,
and playhead position are ignored for timing and database operations.

Required marker names:

```text
Start
S1
S2
S3
...
Finish
```

Rules:

- One clip equals one run.
- One `Start`, one `Finish`.
- Sector markers are numbered sequentially.
- Sector 1 is `Start` to `S1`.
- Sector 2 is `S1` to `S2`.
- Final sector is last `S#` to `Finish`, and is displayed as the next sector number.
- Lap time is `Finish - Start`.
- Display format: `0:42.318`.
- Delta format: `+1.204` / `-0.532`.

## User Workflow

1. User selects exactly one Media Pool source clip.
2. Opens the Resolve Timer interactive tool.
3. Selects an existing course.
4. Tool reads source clip markers by name.
5. Tool validates marker count/order against selected course.
6. Tool previews segment times, lap time, best lap comparison, and optimal comparison.
7. User chooses an action:
   - Refresh from clip markers.
   - Generate/update overlay.
   - Commit new run to YAML.
   - Update existing committed run from current markers.
   - Manage/delete/ignore bad committed data.

## Important Data Model Decision

Markers are the editable truth for the current clip. YAML is the historical truth for committed runs. The overlay is playback truth after the latest refresh.

Do not store derived sector/lap times in YAML unless needed for debugging. Store marker frame snapshots for committed runs so historical results do not silently change if markers are edited later.

Example YAML shape:

```yaml
schema_version: 1
courses:
  - id: lower_whistler_a_line
    name: Lower Whistler A-Line
    sector_count: 4

runs:
  - id: run_2026_05_31_001
    course_id: lower_whistler_a_line
    date: 2026-05-31
    filename: GX010123.MP4
    source_fps: 59.94
    clip_id: optional_resolve_media_pool_id
    fingerprint: GX010123.MP4:optional_marker_snapshot_hash
    committed: true
    ignored: false
    marker_frames:
      Start: 1042
      S1: 2310
      S2: 3922
      S3: 5180
      Finish: 6508
```

Computed at runtime:

- Sector durations.
- Lap duration.
- Fastest complete lap.
- Optimal lap, as sum of fastest recorded sector durations.
- Deltas.

## Comparison Modes

### Best Lap Mode

Default mode.

- Each sector delta compares against the same sector from the fastest complete lap.
- Lap delta compares against the fastest complete lap.

### Optimal Mode

- Each sector delta compares against the fastest recorded time for that sector.
- Lap delta compares against the theoretical optimal lap.

## Overlay Requirements

Live timing overlay in the top-right corner:

- Timer starts at `Start`.
- Timer stops at `Finish`.
- Overlay remains visible after finish with final values.
- No pre-roll or post-roll.
- Segment times only for sector rows.
- Full lap time shown by the live timer/lap row.
- Dark translucent background.
- White primary text.
- Green negative deltas.
- Red positive deltas.
- Gold/highlight treatment for fastest sectors if useful.

Example display:

```text
LIVE        1:24.382

S1          0:42.318   +0.241
S2          0:53.734   -0.118
S3          --:--.---   --.---
S4          --:--.---   --.---

LAP         --:--.---   --.---
BEST        2:54.821
OPTIMAL     2:52.406
```

Rows fill in as sectors are crossed.

## Overlay Implementation Direction

Prefer Fusion/Text+ expressions over frame-by-frame keyframing.

The generated Fusion comp should have stable nodes and expression-driven behavior. The script writes or updates control values such as:

- `start_frame`
- `finish_frame`
- sector marker frames
- reference sector durations for current comparison mode
- best lap duration
- optimal lap duration
- frame rate
- comparison mode

Fusion expressions should derive:

- live lap time from current comp frame
- sector visibility
- sector durations
- deltas
- stopped timer after finish

Important caveat: Fusion expressions probably cannot directly query Resolve source clip markers by name at playback time. Plan for a one-click refresh model:

```text
User edits markers
Tool reads markers
Tool updates overlay control values
Fusion expressions recalculate
```

Do not depend on zero-click live binding between markers and Fusion.

## Overlay Update Strategy

Generated overlays should be identifiable so repeated runs of the tool can update existing overlays instead of stacking duplicates.

Possible identifiers:

- generated clip/item name
- Fusion comp name
- marker/custom data if available

Default behavior:

- `Update Clip Under Playhead` updates the clip under the playhead for the
  selected course.
- `Update All Timeline Clips` scans all current timeline video tracks, updates
  clips with valid source markers for the selected course, and reports skipped
  clips.
- Offer replace/create-new only as explicit options if that becomes necessary.

## Interactive UI Requirements

Polished UI from the beginning.

Suggested sections:

- Course selector.
- Selected clip summary.
- Marker validation.
- Current parsed timing table.
- Comparison mode toggle: Best Lap / Optimal.
- History match status:
  - no committed run for this clip
  - committed run found
  - marker changes detected
- Actions:
  - Refresh Preview
  - Update Clip Under Playhead
  - Update All Timeline Clips
  - Commit New Run
  - Update Existing Run
  - Manage Runs

Database management should support:

- view runs by course
- commit/uncommit or ignore runs
- update run from current markers
- delete bad run
- validate database consistency
- open database file/manual edit path

## Interactive UI Implementation Plan

### V1 Decisions

- Run as an in-Resolve Python UI Manager window.
- Use Resolve's validated CPython 3.14 runtime and injected `resolve`, `fusion`,
  and `bmd` globals.
- Read markers only from the single selected Media Pool source clip.
- Use one repository-local `timer_db.yaml` shared across Resolve projects.
- Keep course creation/editing in YAML/CLI for V1. The UI selects existing
  courses and manages runs.
- Include the complete timing/database UI before enabling the Fusion overlay
  action. Overlay work remains the next independently accepted phase.
- Open one modal dispatcher-backed window per script launch. Prevent duplicate
  windows within the same interpreter session when Resolve permits detection.

### 1. UI Manager Capability Probe

Extend the runtime diagnostic to record whether `fusion.UIManager` and
`bmd.UIDispatcher` are callable. Add a minimal window with one button to validate
event dispatch, close handling, and repeated launches.

Exit gate:

- A modeless or modal window opens reliably from `Workspace > Scripts`.
- Closing the window exits its dispatcher cleanly.
- Running the script again does not leave duplicate event loops or stale
  windows.

### 2. Separate UI State From Resolve Widgets

Introduce `ResolveTimerController` and immutable `ResolveTimerViewState`. The
controller owns:

- database path and loaded `TimerService`
- available courses and selected course ID
- selected Resolve clip snapshot
- marker source (always the selected Media Pool source clip in V1)
- comparison mode
- current preview or validation error
- matching committed run and dirty-marker status
- available and enabled actions
- last operation result

Keep widget construction and event callbacks thin. Unit-test controller
transitions with fake adapters before live Resolve testing.

Controller operations:

- `initialize()`
- `select_course(course_id)`
- `set_comparison_mode(mode)`
- `refresh_selection()`
- `commit_new_run()`
- `update_existing_run()`
- `set_run_ignored(run_id, ignored)`
- `delete_run(run_id)`
- `reload_database()`

Each operation returns a complete view state. Widget callbacks render that state
and do not independently calculate timing or mutate YAML.

### 3. Minimal Read-Only Window

Build a resizable main window with these sections:

Header:

- course selector
- Best Lap / Optimal comparison selector
- Refresh button

Selected Clip:

- selected Media Pool clip filename
- source FPS
- marker source and count
- full-source scope

Timing table:

- row label
- current duration
- reference duration
- delta
- reference run where applicable

History:

- matching run ID and date
- new / matched / marker changes / ignored status
- best lap and optimal lap summaries

Footer:

- database path
- persistent status/error line
- action buttons

Use standard UI Manager controls and styling only. Do not introduce Qt, Tk, a
webview, or another GUI dependency.

Refresh must reacquire the current Resolve selection and markers. Errors should
be rendered in the window without closing it or printing an unhandled
traceback.

Action enablement:

- `Commit New Run`: enabled only for a valid preview with no matching run.
- `Update Existing Run`: enabled only when a matching run has marker changes.
- `Ignore/Unignore`: enabled only for a matching committed run.
- `Delete`: enabled only for a matching committed run.
- Timeline overlay actions are visually separate from Media Pool preview and
  database actions.

Exit gate:

- The validated five-marker clip displays the same `59.593s` lap and sector
  values as the core service.
- Missing, duplicate, and out-of-order markers produce actionable UI errors.
- Changing the selected Media Pool clip and pressing Refresh updates all fields.

### 4. Database Mutations

Add actions in this order:

1. Commit New Run
2. Update Existing Run
3. Ignore / Unignore Run
4. Delete Run

Require confirmation for update and delete. After every successful mutation,
save the YAML atomically, reload it, recompute stats, and refresh the window.
Disable actions that are invalid for the current match state.

Mutation workflow:

1. Re-read the current Resolve selection immediately before mutation.
2. Validate markers and establish match state again.
3. Apply the mutation to an in-memory database.
4. Write to a temporary sibling file and atomically replace `timer_db.yaml`.
5. Reload and validate the saved database.
6. Rebuild the complete view state.

Commit does not require confirmation because it is enabled only when no matching
run exists. Update and delete require a confirmation dialog naming the run.
Ignore/unignore is immediately reversible and does not require confirmation.

Exit gate:

- A new run survives Resolve restart.
- Marker edits are detected against a matching committed run.
- Updating preserves run identity and ignored state.
- Ignore/unignore immediately changes comparison stats.
- Failed saves leave the previous database intact and show an error.

### 5. Run Management Window

Add a course-filtered run table showing run ID, date, filename, lap time,
ignored state, and marker-match state. Provide ignore/unignore and delete
actions; keep course creation/editing as YAML/CLI work for V1 unless live use
shows it is necessary.

Open run management as a child dialog. Closing it refreshes the main window so
stats and action states cannot remain stale.

Run-table columns:

- run ID
- date
- filename
- lap
- committed
- ignored
- clip ID present

Selection controls the enabled state of Ignore/Unignore and Delete. Deleting
requires confirmation. Database validation errors remain visible in the dialog.

### 6. Error Handling And Lifecycle

Handle these as user-facing states rather than uncaught exceptions:

- no project, timeline, or selected video item
- selected item has no linked media-pool item
- missing, duplicate, unexpected, or out-of-order timing markers
- missing course or invalid database
- PyYAML import failure
- database read/write/replace failure
- Resolve API returning an unexpected type

Unexpected exceptions are written to
`F:\Documents\Resolve Timer\resolve_timer.log` with a traceback and summarized
in the UI. The window remains open where practical.

Window startup:

1. Validate runtime globals and UI Manager support.
2. Load and validate the database.
3. Populate courses.
4. Restore the last selected course and comparison mode from a small local
   preferences file when valid.
5. Refresh the current Resolve selection.

Window shutdown stops the dispatcher and releases window/controller references.
No background thread or polling loop is required in V1.

### 7. Overlay Boundary

Overlay actions call a dedicated `FusionOverlayUpdater`. The UI must not
contain Fusion node-building logic. Static Text+ creation, deterministic
lookup/update, and expression-driven timing have been validated separately.

### 8. Resolve 21 Compatibility

The deployed code must remain compatible with Resolve's observed runtime:

- DaVinci Resolve Studio `21.0.0.48`
- `fuscript.exe`
- CPython `3.14.5`
- Python prefix:
  `C:\Users\lgilb\AppData\Local\Python\pythoncore-3.14-64`
- injected `resolve` object passed through the generated launcher
- injected `fusion` and `bmd` objects passed through the generated launcher

Keep Resolve-runtime dependencies minimal. PyYAML availability must be checked
at startup with an actionable error if missing.

### 9. Verification

Automated:

- controller state and action tests with fake Resolve/UI boundaries
- database mutation and failed-save tests
- existing core suite

Manual in Resolve:

- repeated open/close/reopen
- selection changes while the window is open
- all marker validation failures
- commit, update, ignore, unignore, and delete
- Resolve restart and database persistence
- 29.97 first, then the FPS matrix in `ACCEPTANCE.md`

### 10. Delivery Sequence

1. Runtime/UI Manager capability probe.
2. Controller, view state, and fake-boundary tests.
3. Read-only main window.
4. Live Resolve validation of refresh and marker errors.
5. Commit and update actions.
6. Ignore/unignore and delete actions.
7. Run management dialog.
8. Preferences, logging, and startup diagnostics.
9. Full Phase 3 acceptance pass.
10. Begin Overlay V1 only after Phase 3 is accepted.

## Implementation Milestones

1. Scaffold Python project structure.
2. Implement marker parser and validation from a selected Resolve clip/media pool item.
3. Implement timing engine.
4. Implement YAML database read/write and derived stats.
5. Implement interactive UI.
6. Implement static overlay generation proof-of-concept.
7. Replace/upgrade overlay with expression-driven live Fusion/Text+ comp.
8. Implement overlay refresh/update detection.
9. Add database management UI.
10. Test against real Resolve clips and marker edits.

## Open Technical Risks

- UI Manager availability and event-loop behavior under the Scripts menu needs
  a live capability probe.
- Exact Fusion expression syntax/control wiring needs validation inside Resolve.
- Updating an existing Fusion comp without rebuilding nodes needs proof-of-concept.
- Creating the overlay timeline item/clip at the exact selected source clip position needs Resolve API testing.
- PyYAML availability in Resolve's bundled Python needs explicit startup
  validation.

## Next Session Suggested First Steps

1. Fix Git safe-directory issue if needed:

```powershell
git config --global --add safe.directory 'F:/Documents/Resolve Timer'
```

2. Create initial repo files:

```text
README.md
src/resolve_timer/
tests/
examples/
```

3. Decide Python packaging style.
4. Build pure-Python timing/YAML modules first so they can be tested outside Resolve.
5. Add Resolve adapter layer second, keeping Resolve API calls isolated.

## Current Implementation Status

The current implementation has a tested pure-Python core, CLI workflows, YAML
database management, Resolve adapter boundary tests with fakes, and overlay
payload/text previews. Resolve 21 live testing has validated selected timeline
Media Pool selection, source FPS, source-clip markers, and UI Manager. The
Phase 3 UI now includes timing preview, commit/update, ignore/unignore, delete,
course management, course-filtered run management, persisted course/comparison
preferences, startup diagnostics, and unexpected-error logging. Course IDs are
stable after creation; course names can be edited; sector-count edits and
deletion are blocked once runs reference the course. The complete Phase 3
workflow is accepted for the validated clip. Overlay V1 now has deterministic
Fusion comp reuse, an expression-driven live timer, marker-timed sector and lap
rows, comparison-aware delta colors, and a blurred translucent panel. Visual
playback with committed comparison data is accepted for the validated Resolve
21 clip. Overlay regeneration is now timeline-driven: current clip under the
playhead or all current timeline video clips with valid selected-course markers.
