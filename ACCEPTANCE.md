# Resolve Timer Acceptance Checklist

## Phase 1: Core and CLI Hardening

- Unit tests pass with the project venv.
- CLI expected user/data failures print `Error: ...` without traceback.
- Database load/save failures are wrapped as `DatabaseError`.
- `commit --run-id` rejects duplicate run IDs.
- `update-run` preserves ignored state and rejects course mismatches.
- Top-level `resolve_timer` imports expose pure timing/marker helpers only.

## Phase 2: Resolve API Baseline

- Confirm selected Media Pool clip access, marker payload shape, FPS property,
  and clip identity in the supported Resolve version.
- Record Resolve version/build with the manual validation notes.

Validated baseline:

- Resolve Studio `21.0.0.48`
- Resolve `fuscript.exe`, CPython `3.14.5`
- Resolve uses the installed Python prefix
  `C:\Users\lgilb\AppData\Local\Python\pythoncore-3.14-64`
- `resolve`, `fusion`, and `bmd` globals are injected into menu scripts
- exactly one selected Media Pool clip is required
- source FPS available as `FPS`
- selected Media Pool clip marker keys are read in the source-frame domain
- timeline selection and playhead position are ignored

## Phase 3: Minimal Resolve Workflow

Automated coverage is complete. Live Resolve validation has confirmed window
layout, open/close/reopen, timing preview, run actions, run management, and
preference restoration. The full FPS and malformed-marker matrix remains an
ongoing manual compatibility check.

- UI opens, closes, and reopens without a stale dispatcher or duplicate window.
- Course can be selected.
- Courses can be added, renamed, and deleted when no runs reference them.
- Sector-count edits and course deletion are blocked when runs reference the
  course.
- Current clip markers can be refreshed and previewed.
- Selection changes while the window is open are handled by Refresh Media Pool
  Preview.
- Validation failures are displayed without terminating the script.
- Selected Media Pool clip marker origin is identified in the UI.
- Timing table matches the tested core service output.
- New runs can be committed.
- Existing run markers can be updated without changing course or ignored state.
- Action buttons are disabled when their preconditions are not met.
- Update and delete require confirmation.
- Ignore/unignore is reversible and immediately recomputes statistics.
- Database writes are atomic and failed writes preserve the prior file.
- Unexpected failures are logged with a traceback and summarized in the UI.
- DB path is visible to the user.
- Stats and run-management actions are reachable.
- Window preferences survive restart without affecting the timing database.

## Phase 4: Overlay V1

Validated in Resolve 21:

- Reading source markers from the current timeline item's Media Pool source
  clip.
- Static Text+ overlay creation.
- Second-run comp reuse with `comp_created: false`.
- Fusion comp count unchanged on the second run.
- Overlay updates use the production Fusion writer.

Expression-driven timer validated:

- Source markers are translated with
  `fusion_frame = source_frame - timeline_source_start`.
- Text+ starts at the translated `Start` frame.
- Start evaluates to `0:00.000`.
- Mid-run advances from Fusion `time`.
- Finish freezes at the final lap value.
- Frames after Finish retain the same final value.
- Sector Text+ nodes begin at their translated marker crossings.
- Final-sector and lap Text+ nodes begin at the translated `Finish` frame.
- The blurred translucent panel, light border, monospace text, and per-row
  merge chain survive comp export.
- Re-running the updater leaves the Fusion comp count unchanged.

Visual playback layout and committed comparison-data deltas accepted on the
validated Resolve 21 clip.

- Repeated overlay updates do not create duplicate generated overlays.
- Overlay identity is deterministic for a course/run or marker snapshot.
- Static/final overlay text matches CLI `overlay-text` output.
- Live overlay starts at `Start`, reveals sector rows at marker crossings, and
  freezes after `Finish`.
- Best-lap and optimal comparison modes display correct deltas.
- `Update Clip Under Playhead` uses the clip under the playhead without
  requiring a Media Pool selection.
- `Update All Timeline Clips` scans video tracks, updates valid timeline clips,
  skips invalid clips, and reports counts without writing to the timing
  database.

## Manual Resolve Matrix

- At least one 23.976/24/29.97/59.94/60 FPS source where available.
- Missing `Start`, missing `Finish`, duplicate sector marker, and out-of-order
  marker cases.
- Marker edits after a committed run.
- Ignored run excluded from stats and overlay comparisons.
- Re-running overlay update on the same clip/course.
