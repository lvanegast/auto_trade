# Usar la imagen oficial de Python (versión ligera)
FROM python:3.10-slim

# Evitar que Python escriba archivos .pyc y forzar salida sin búfer
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Establecer directorio de trabajo
WORKDIR /app

# Instalar uv para gestionar dependencias rápidamente
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copiar archivos de dependencias
COPY pyproject.toml uv.lock ./

# Instalar dependencias del proyecto usando uv
RUN uv sync --frozen --no-dev

# Copiar el código fuente y el frontend
COPY src/ ./src
COPY web/ ./web
COPY main.py ./

# Exponer el puerto 8080 para FastAPI
EXPOSE 8080

# Comando para arrancar la aplicación
CMD ["uv", "run", "main.py"]
