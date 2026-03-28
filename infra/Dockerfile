# =============================================================================
# Multi-stage Dockerfile — one image, two entry points:
#   API mode    : uvicorn etl_agent.api.main:app  (default CMD)
#   Worker mode : python -m etl_agent.worker       (override CMD in ECS task def)
#
# Stages:
#   builder  — install Python deps with uv into /app/.venv
#   runtime  — minimal image, copy venv + source only
# =============================================================================

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Install uv (fast pip alternative used by the project)
RUN pip install --no-cache-dir uv==0.4.29

WORKDIR /app

# Copy dependency manifests first for better layer caching
COPY pyproject.toml uv.lock* ./

# Install production dependencies into a venv
RUN uv venv .venv && \
    uv sync --frozen --no-dev

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Install runtime OS packages:
#   curl      — health check in ECS
#   openjdk   — PySpark (worker only, but same image for both roles)
#   procps    — useful for debugging in ECS Exec
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        procps \
        openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH="$JAVA_HOME/bin:$PATH"

# Non-root user for security
RUN groupadd --gid 1001 appgroup && \
    useradd --uid 1001 --gid appgroup --no-create-home appuser

WORKDIR /app

# Copy venv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application source
COPY src/ ./src/

# Activate venv
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"

# Reduce Python noise
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Spark config — minimise logging noise from the Spark worker
ENV PYSPARK_SUBMIT_ARGS="--master local[*] pyspark-shell"
ENV SPARK_LOCAL_HOSTNAME="localhost"

# Capture the git SHA at build time for traceability
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}

# Health check — used by ECS to detect unhealthy API tasks.
# Worker tasks have no HTTP server; health is inferred from the process being alive.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

USER appuser

# ── Default: API mode ────────────────────────────────────────────────────────
# Override CMD in ECS worker task definition with:
#   ["python", "-m", "etl_agent.worker"]
CMD ["uvicorn", "etl_agent.api.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--log-level", "info", \
     "--access-log"]

EXPOSE 8000
