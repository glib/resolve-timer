"""DaVinci Resolve API probe for Resolve Timer.

Run inside Resolve's Python environment. By default it writes
`resolve_probe.json` in the current working directory.
"""

from pathlib import Path

from resolve_timer.resolve_probe import probe_resolve, save_probe_result


if __name__ == "__main__":
    output_path = Path.cwd() / "resolve_probe.json"
    save_probe_result(probe_resolve(), output_path)
    print(f"Wrote {output_path}")
