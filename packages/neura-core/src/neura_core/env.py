"""Load ``.env`` into the process environment.

Several places read configuration with ``os.getenv`` — role maps, pricing, the
eval judge. None of that sees a ``.env`` file unless something loads it first,
which is a genuinely confusing failure: the file is right there and correct, and
the program behaves as though it is empty.

So every entrypoint calls :func:`load_env` before reading configuration.

**Real environment variables always win.** In production there is no ``.env``;
values come from the platform, a secrets manager, or CI. A ``.env`` that could
override those would be a way to accidentally ship development settings.

**And the FIRST occurrence of a key wins, not the last** — a consequence of the
rule above, since after the first assignment the key is in ``os.environ`` and
the second is skipped like any pre-set value. That is surprising: most people
expect a later line to override an earlier one, the way a shell script would.

Found on 2026-08-27 with two ``CLOUD_LLM_BASE_URL`` blocks in one file, one
pointing at Gemini and one at OpenRouter. The first won, the second read as
though it were live, and the model names underneath it belonged to the provider
that had lost — so the reasoner role was configured to send one vendor's model
name to another vendor's endpoint. Nothing reported it until a call failed.
Duplicates are now named at load time.
"""

from __future__ import annotations

import os
from pathlib import Path

from neura_core.logging import get_logger

log = get_logger(__name__)

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

    seen: set[str] = set()
    duplicates: list[str] = []

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

        if key in seen:
            duplicates.append(key)
        seen.add(key)

        if override or key not in os.environ:
            os.environ[key] = value

    if duplicates:
        # Warned, not raised. A duplicate is usually a half-finished edit rather
        # than a broken deploy, and refusing to start would be a worse failure
        # than the one being prevented. But it must not be silent: the value in
        # force is the one further UP the file, which is the opposite of what
        # somebody appending a new block believes they have just done.
        log.warning(
            "env_duplicate_keys",
            file=str(env_file),
            keys=sorted(set(duplicates)),
            detail="the FIRST occurrence of each is in force; later lines were ignored",
        )

    _loaded = True
    return env_file


def reset_for_testing() -> None:
    """Allow tests to re-run loading. Not for production use."""
    global _loaded
    _loaded = False
