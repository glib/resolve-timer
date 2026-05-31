from __future__ import annotations

from pathlib import Path

from .database import TimerDatabase
from .resolve_adapter import ResolveAdapter, ResolveAdapterError


def default_database_path() -> Path:
    return Path.cwd() / "timer_db.yaml"


def run_interactive_tool(database_path: str | Path | None = None) -> None:
    """Launch the Resolve Timer UI.

    The UI Manager implementation is the next Resolve-validated layer. This
    entrypoint currently verifies the database and Resolve connection boundary.
    """
    db_path = Path(database_path) if database_path else default_database_path()
    TimerDatabase.load(db_path)
    try:
        ResolveAdapter()
    except ResolveAdapterError:
        raise
    raise NotImplementedError(
        "Resolve UI Manager window must be implemented after validating Resolve UI APIs"
    )
