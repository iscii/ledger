"""
backstep.config
~~~~~~~~~~~~~~~
Single source of truth for runtime configuration.

DB path priority
----------------
1. BACKSTEP_DB environment variable (absolute or relative path)
2. Default: ./backstep.db relative to cwd, resolved to absolute

The returned path is always absolute. The parent directory is created
automatically if it does not exist.
"""

from __future__ import annotations

import os
from pathlib import Path


def get_db_path() -> Path:
    """Return the absolute Path to the active Backstep database.

    Priority:
      1. ``BACKSTEP_DB`` environment variable (absolute or relative)
      2. ``./backstep.db`` relative to cwd, resolved absolute

    Always returns an absolute path. Creates the parent directory if needed.
    """
    raw = os.environ.get("BACKSTEP_DB")
    if raw:
        path = Path(raw)
    else:
        path = Path("./backstep.db")

    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
