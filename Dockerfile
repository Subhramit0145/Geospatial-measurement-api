# syntax=docker/dockerfile:1
FROM python:3.11-slim

LABEL maintainer="Candidate" \
      description="Production container for Geospatial Measurement API"

WORKDIR /app

# Ensure Python output is sent directly to terminal without buffering
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UPLOAD_DIR=/app/uploads \
    DATABASE_URL=sqlite:////app/geo_api.db

# Install minimal OS dependencies for network health checking & building
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for optimal Docker layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application modules and test sample data
COPY app/ ./app
COPY scripts/ ./scripts
COPY sample_data/ ./sample_data
COPY .env.example .env

# Prepare upload and data directories
RUN mkdir -p /app/uploads

EXPOSE 8000

# Docker healthcheck endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Launch high-concurrency multi-worker ASGI server
ENV WORKERS=4 \
    LIMIT_CONCURRENCY=2000 \
    BACKLOG=4096 \
    TIMEOUT_KEEP_ALIVE=30

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${WORKERS} --limit-concurrency ${LIMIT_CONCURRENCY} --backlog ${BACKLOG} --timeout-keep-alive ${TIMEOUT_KEEP_ALIVE}"]

