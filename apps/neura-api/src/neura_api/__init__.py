"""neura-api — the deployable.

FastAPI application plus (later) the worker entrypoint. One process, per
ADR-0002; the package boundaries below it mean extracting a service later is a
deployment change rather than a redesign.
"""

from neura_api.main import app, create_app

__all__ = ["app", "create_app"]
