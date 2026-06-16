"""Create or update the Resolve Timer Fusion overlay for live API validation.

Before running:
- Put the timeline playhead over the matching timeline video item.

The probe reads the current timeline item's source clip directly. The production
tool still requires an explicit matching Media Pool selection.

The script writes `resolve_fusion_probe.json` in the project root.
"""

import sys
from pathlib import Path


SCRIPT_PATH = Path(
    globals().get("__file__", Path.cwd() / "scripts" / "ResolveFusionProbe.py")
).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
RESOLVE_DEPENDENCIES = PROJECT_ROOT / ".resolve_deps"
RESOLVE_SCRIPTING_MODULES = Path(
    r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules"
)
if str(RESOLVE_SCRIPTING_MODULES) not in sys.path:
    sys.path.insert(0, str(RESOLVE_SCRIPTING_MODULES))
if str(RESOLVE_DEPENDENCIES) not in sys.path:
    sys.path.insert(0, str(RESOLVE_DEPENDENCIES))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from resolve_timer.fusion_probe import run_fusion_probe, save_fusion_probe_result


if __name__ == "__main__":
    output_path = PROJECT_ROOT / "resolve_fusion_probe.json"
    resolve = globals().get("resolve")
    result = run_fusion_probe(
        database_path=PROJECT_ROOT / "timer_db.yaml",
        preferences_path=PROJECT_ROOT / "resolve_timer_preferences.json",
        resolve=resolve,
        export_path=PROJECT_ROOT / "resolve_fusion_probe.comp",
        use_current_timeline_item=True,
    )
    save_fusion_probe_result(result, output_path)
    print(f"Wrote {output_path}")
