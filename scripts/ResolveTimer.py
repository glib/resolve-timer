"""DaVinci Resolve script entrypoint for Resolve Timer."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
DEPS_ROOT = PROJECT_ROOT / ".resolve_deps"
if DEPS_ROOT.exists() and str(DEPS_ROOT) not in sys.path:
    sys.path.insert(0, str(DEPS_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from resolve_timer.ui import run_interactive_tool


if __name__ == "__main__":
    run_interactive_tool(
        PROJECT_ROOT / "timer_db.yaml",
        resolve=globals().get("resolve"),
        fusion=globals().get("fusion"),
        bmd=globals().get("bmd"),
    )
