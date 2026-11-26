# ==============================================================================
# Salutem Ficha Studio v1.0.0 - Multi-Stage Dockerfile
# Stage 1: Build da SPA React/Vite (Node 22 Alpine)
# Stage 2: Runtime Python 3.13 + OpenJDK 17 Headless (Jasper Daemon JVM)
# ==============================================================================

# ------------------------------------------------------------------------------
# Stage 1: Frontend SPA Builder
# ------------------------------------------------------------------------------
FROM node:22-alpine AS frontend-builder

WORKDIR /build/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ------------------------------------------------------------------------------
# Stage 2: Runtime (FastAPI + Uvicorn + Jasper Daemon JVM)
# ------------------------------------------------------------------------------
# Debian Bookworm garante disponibilidade deterministica de openjdk-17-jre-headless
FROM python:3.13-slim-bookworm AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    openjdk-17-jre-headless \
    fontconfig \
    fonts-dejavu-core \
    fonts-liberation \
    curl \
    libpq5 \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Instalar dependencias Python aproveitando cache de camadas
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Copiar aplicacao backend, recursos (jasper-daemon.jar + 4 subreports .jasper) e metadados
COPY backend/ ./backend/
COPY resources/ ./resources/
COPY pyproject.toml ./

# Copiar bundle SPA compilado no Stage 1
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist

# Criar usuario nao-root 'studio' e diretorio persistente /data
RUN groupadd --system studio \
    && useradd --system --gid studio --create-home --home-dir /home/studio --shell /usr/sbin/nologin studio \
    && mkdir -p /data \
    && chown -R studio:studio /data /app

ENV FICHA_STUDIO_DATA_DIR=/data \
    PYTHONPATH=/app/backend:/app \
    PYTHONUNBUFFERED=1

USER studio

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
