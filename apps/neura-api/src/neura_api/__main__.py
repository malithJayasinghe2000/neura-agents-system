"""Entrypoint: ``neura-api`` or ``python -m neura_api``."""

from __future__ import annotations

import uvicorn

from neura_core import Environment, get_settings


def main() -> None:
    settings = get_settings()
    reload = settings.env is Environment.DEVELOPMENT
    uvicorn.run(
        "neura_api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=reload,
        # The widget is read **once at import** — deliberately, because a disk
        # read per shopper is pure latency — and uvicorn's reloader watches only
        # `*.py`. So editing `widget.js` changed nothing until someone restarted
        # the process, and a browser kept showing a fix that was already on
        # disk. Measured 2026-08-30: it cost a round of "still not good" on a
        # screenshot of code that had been corrected.
        #
        # Development only. Production behaviour is unchanged, and the file is
        # still read once there.
        reload_includes=["*.py", "*.js", "*.html"] if reload else None,
        log_config=None,  # structlog owns logging
    )


if __name__ == "__main__":
    main()
