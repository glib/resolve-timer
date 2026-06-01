# Resolve Timer Acceptance Checklist

## Phase 1: Core and CLI Hardening

- Unit tests pass with the project venv.
- CLI expected user/data failures print `Error: ...` without traceback.
- Database load/save failures are wrapped as `DatabaseError`.
- `commit --run-id` rejects duplicate run IDs.
- `update-run` preserves ignored state and rejects course mismatches.
- Top-level `resolve_timer` imports expose pure timing/marker helpers only.

## Phase 2: Resolve API Probe

- Run `scripts/ResolveProbe.py` inside Resolve with a selected timeline item.
- Save the generated `resolve_probe.json` artifact with the test notes.
- Confirm selected timeline item, source media pool item, marker payload shape,
  FPS property, clip identity, and source-vs-timeline frame fields.
- Record Resolve version/build from the probe output.

## Phase 3: Minimal Resolve Workflow

- Course can be selected.
- Current clip markers can be refreshed and previewed.
- New runs can be committed.
- Existing run markers can be updated without changing course or ignored state.
- DB path is visible to the user.
- Stats and run-management actions are reachable.

## Phase 4: Overlay V1

- Repeated overlay updates do not create duplicate generated overlays.
- Overlay identity is deterministic for a course/run or marker snapshot.
- Static/final overlay text matches CLI `overlay-text` output.
- Live overlay starts at `Start`, reveals sector rows at marker crossings, and
  freezes after `Finish`.
- Best-lap and optimal comparison modes display correct deltas.

## Manual Resolve Matrix

- At least one 23.976/24/29.97/59.94/60 FPS source where available.
- Missing `Start`, missing `Finish`, duplicate sector marker, and out-of-order
  marker cases.
- Marker edits after a committed run.
- Ignored run excluded from stats and overlay comparisons.
- Re-running overlay update on the same clip/course.
