"""DaVinci Resolve script entrypoint for Resolve Timer.

Copy or symlink this file into Resolve's Scripts folder once the package is on
Resolve Python's import path.
"""

from resolve_timer.ui import run_interactive_tool


if __name__ == "__main__":
    run_interactive_tool()
