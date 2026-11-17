# The API, with its job runner inside it (ADR-0002, ADR-0079).
#
#   docker build -f infra/docker/api.Dockerfile -t neura-api .
#
# Python 3.12 on purpose (CLAUDE.md §5). The whole workspace is installed, as
# `uv run neura-api` installs it on a laptop: the agents are found through their
# entry points, so an agent left out of the image is an agent that silently is
# not there. Migrations run from the same image (`alembic upgrade head`).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    NEURA_API_HOST=0.0.0.0 \
    NEURA_API_PORT=8010

WORKDIR /app

# The lock file first, so a code change does not reinstall every dependency.
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
COPY apps/neura-api/ apps/neura-api/
COPY agents/ agents/
COPY evals/ evals/
RUN uv sync --frozen --no-dev

COPY alembic.ini ./
COPY infra/migrations/ infra/migrations/

# Never as root: nothing in the process needs it.
RUN useradd --create-home --uid 10001 neura && chown -R neura /app
USER neura

EXPOSE 8010
CMD ["neura-api"]
