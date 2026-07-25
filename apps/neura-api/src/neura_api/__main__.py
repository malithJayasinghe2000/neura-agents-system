"""Entrypoint: ``neura-api`` or ``python -m neura_api``."""

from __future__ import annotations

import uvicorn

from neura_core import Environment, get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "neura_api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.env is Environment.DEVELOPMENT,
        log_config=None,  # structlog owns logging
    )


if __name__ == "__main__":
    main()
