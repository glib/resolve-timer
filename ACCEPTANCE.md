# Resolve Timer Acceptance Checklist

## Phase 1: Core and CLI Hardening

- Unit tests pass with the project venv.
- CLI expected user/data failures print `Error: ...` without traceback.
- Database load/save failures are wrapped as `DatabaseError`.
- `commit --run-id` rejects duplicate run IDs.
- `update-run` preserves ignored state and rejects course mismatches.
- Top-level `resolve_timer` imports expose pure timing/marker helpers only.

## Phase 2: Resolve API Probe

- Run `scripts/ResolveProbe.py` inside Resolve with exactly one Media Pool clip
  selected.
- Save the generated `resolve_probe.json` artifact with the test notes.
- Confirm selected Media Pool clip, marker payload shape, FPS property, and clip
  identity. Timeline fields are diagnostic only for later overlay placement.
- Record Resolve version/build from the probe output.

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

- UI Manager and UIDispatcher capability probe passes.
- UI opens, closes, and reopens without a stale dispatcher or duplicate window.
- Course can be selected.
- Current clip markers can be refreshed and previewed.
- Selection changes while the window is open are handled by Refresh.
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

Current gate: run `ResolveFusionProbe` twice on the same matching Media Pool and
timeline clip. Confirm static text creation on the first run and deterministic
comp/node reuse on the second run before enabling the main-window action.

Validated in Resolve 21:

- Matching selected Media Pool and timeline clip IDs.
- Static Text+ overlay creation.
- Second-run comp reuse with `comp_created: false`.
- Fusion comp count unchanged on the second run.

Next gate: validate the main-window `Update Overlay` action, then replace the
static final text with expression-driven live timing.

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
