FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY backend/pyproject.toml ./

RUN uv sync --no-dev

COPY backend/src/ ./src
COPY backend/scripts/ ./scripts
COPY backend/tests/ ./tests
COPY backend/main.py ./
COPY web/ ./web
COPY backend/entrypoint.sh ./entrypoint.sh
COPY backend/monitor-entrypoint.sh ./monitor-entrypoint.sh

RUN chmod +x /app/entrypoint.sh /app/monitor-entrypoint.sh

EXPOSE 8080

CMD ["/app/entrypoint.sh"]
