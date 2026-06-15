"""Report the Python runtime used by DaVinci Resolve menu scripts."""

import json
import platform
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "resolve_runtime.json"

report = {
    "python_version": platform.python_version(),
    "python_version_info": list(sys.version_info),
    "python_implementation": platform.python_implementation(),
    "python_executable": sys.executable,
    "python_prefix": sys.prefix,
    "python_base_prefix": getattr(sys, "base_prefix", None),
    "sys_version": sys.version,
    "resolve_injected": globals().get("resolve") is not None,
    "fusion_injected": globals().get("fusion") is not None,
    "bmd_injected": globals().get("bmd") is not None,
}

OUTPUT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

print("Resolve Timer runtime diagnostic")
for key, value in report.items():
    print(f"{key}: {value}")
print(f"Wrote {OUTPUT_PATH}")
