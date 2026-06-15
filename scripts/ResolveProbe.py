"""DaVinci Resolve API probe for Resolve Timer.

Run inside Resolve's Python environment. It writes `resolve_probe.json` in the
project root.
"""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from resolve_timer.resolve_probe import probe_resolve, save_probe_result


if __name__ == "__main__":
    output_path = PROJECT_ROOT / "resolve_probe.json"
    save_probe_result(probe_resolve(globals().get("resolve")), output_path)
    print(f"Wrote {output_path}")
