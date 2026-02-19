FROM python:3.12-slim

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

COPY pyproject.toml poetry.lock ./

RUN poetry install --no-root --no-interaction --no-ansi --without dev\
    && rm -rf $POETRY_CACHE_DIR

COPY . .

# default
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
