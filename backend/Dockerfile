FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY backend/pyproject.toml ./

RUN uv sync --no-dev

COPY backend/src/ ./src
COPY backend/tests/ ./tests
COPY backend/main.py ./
COPY web/ ./web

EXPOSE 8080

CMD ["uv", "run", "main.py"]
