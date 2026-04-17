FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    POETRY_VERSION=1.8.5 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONPATH="/app"

ENV PATH="$POETRY_HOME/bin:$PATH" \
    POETRY_CACHE_DIR="/opt/poetry_cache"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://install.python-poetry.org | python3 -

WORKDIR /app

COPY src/pyproject.toml src/poetry.lock ./

# ── production image ──────────────────────────────────────────────────────────
FROM base AS prod
RUN poetry install --no-root --no-interaction --no-ansi --without dev\
    && rm -rf $POETRY_CACHE_DIR

COPY src/ /app/src/

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ── development image (includes dev deps: watchfiles, pytest, mypy …) ─────────
FROM base AS dev
RUN poetry install --no-root --no-interaction --no-ansi \
    && rm -rf $POETRY_CACHE_DIR

COPY src/ /app/src/

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
