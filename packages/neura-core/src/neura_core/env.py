"""Load ``.env`` into the process environment.

Several places read configuration with ``os.getenv`` — role maps, pricing, the
eval judge. None of that sees a ``.env`` file unless something loads it first,
which is a genuinely confusing failure: the file is right there and correct, and
the program behaves as though it is empty.

So every entrypoint calls :func:`load_env` before reading configuration.

**Real environment variables always win.** In production there is no ``.env``;
values come from the platform, a secrets manager, or CI. A ``.env`` that could
override those would be a way to accidentally ship development settings.
"""

from __future__ import annotations

import os
from pathlib import Path

_loaded = False


def find_env_file(start: Path | None = None) -> Path | None:
    """Walk upward looking for ``.env``.

    Walking up means commands work from any subdirectory, not only the repo root.
    """
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
        # Stop at the repository boundary rather than escaping into $HOME.
        if (directory / ".git").exists():
            break
    return None


def load_env(*, override: bool = False) -> Path | None:
    """Load ``.env`` into ``os.environ``. Idempotent.

    Returns the file loaded, or ``None`` if there was none — which is the normal
    case in production and not an error.
    """
    global _loaded
    if _loaded and not override:
        return None

    env_file = find_env_file()
    if env_file is None:
        _loaded = True
        return None

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()

        # Strip surrounding quotes, then drop a trailing inline comment. Only
        # for unquoted values — a '#' inside quotes is part of the value.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        elif "#" in value:
            value = value.split("#", 1)[0].strip()

        if override or key not in os.environ:
            os.environ[key] = value

    _loaded = True
    return env_file


def reset_for_testing() -> None:
    """Allow tests to re-run loading. Not for production use."""
    global _loaded
    _loaded = False
