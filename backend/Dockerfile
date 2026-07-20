FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

COPY pyproject.toml ./

RUN uv sync --no-dev

COPY src/ ./src
COPY main.py ./

EXPOSE 8080

CMD ["uv", "run", "main.py"]
