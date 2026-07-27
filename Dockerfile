# ════════════════════════════════════════════════════════════════
# CS2 Instant Alert — Multi-Stage Dockerfile
# Works with both docker-compose (context: ..) and Fly.io (context: .)
# ════════════════════════════════════════════════════════════════

# ─── Stage 1: Builder ───
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy dependency definition
COPY pyproject.toml ./

# Install Python dependencies into /build/venv
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel && \
    /opt/venv/bin/pip install --no-cache-dir .


# ─── Stage 2: Runtime ───
FROM python:3.12-slim AS runtime

# Runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY app/ ./app/
COPY alembic.ini ./
COPY config/ ./config/

# Create directories
RUN mkdir -p /app/logs && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Add venv to PATH
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD curl -f http://localhost:8000/api/ready || exit 1

EXPOSE 8000

# Apply schema migrations before accepting traffic.
CMD ["/bin/sh", "-c", "python -m alembic upgrade head && exec python -m app.main"]
