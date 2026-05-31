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

Markers live on the source clip, not timeline markers.

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

1. User selects a source clip/timeline item.
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
courses:
  - id: lower_whistler_a_line
    name: Lower Whistler A-Line
    sector_count: 4

runs:
  - id: run_2026_05_31_001
    course_id: lower_whistler_a_line
    date: 2026-05-31
    filename: GX010123.MP4
    clip_id: optional_resolve_media_pool_id
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

- If an overlay exists for the selected clip/course, update it.
- Offer replace/create-new only as explicit options.

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
  - Refresh From Markers
  - Update Overlay
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

- Exact Resolve scripting access path for source clip markers from a selected timeline item needs validation.
- Exact Fusion expression syntax/control wiring needs validation inside Resolve.
- Updating an existing Fusion comp without rebuilding nodes needs proof-of-concept.
- Creating the overlay timeline item/clip at the exact selected source clip position needs Resolve API testing.
- Resolve UI tooling choice needs validation: Python UI Manager, external Python UI, or simple Resolve dialog helpers.

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
