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
# README.md is required by Hatchling (declared as readme in pyproject.toml)
COPY pyproject.toml uv.lock* README.md ./

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
        openjdk-21-jre-headless \
    && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
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

# ── Iceberg JARs for Spark 3.5 ──────────────────────────────────────────────
# Downloaded at build time from Maven Central.
# Worker tasks use spark.table("glue_catalog.db.table") to read Iceberg tables.
# API tasks never run Spark — these JARs add ~60MB but use the same image.
ARG ICEBERG_VERSION=1.5.2

RUN mkdir -p /opt/spark/jars && \
    curl -fsSL -o /opt/spark/jars/iceberg-spark-runtime.jar \
      "https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-spark-runtime-3.5_2.12/${ICEBERG_VERSION}/iceberg-spark-runtime-3.5_2.12-${ICEBERG_VERSION}.jar" && \
    curl -fsSL -o /opt/spark/jars/iceberg-aws-bundle.jar \
      "https://repo1.maven.org/maven2/org/apache/iceberg/iceberg-aws-bundle/${ICEBERG_VERSION}/iceberg-aws-bundle-${ICEBERG_VERSION}.jar"

# Spark config — include Iceberg JARs and minimise logging noise
ENV PYSPARK_SUBMIT_ARGS="--jars /opt/spark/jars/iceberg-spark-runtime.jar,/opt/spark/jars/iceberg-aws-bundle.jar --master local[*] pyspark-shell"
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
