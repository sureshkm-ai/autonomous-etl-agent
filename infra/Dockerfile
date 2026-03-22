# ═══════════════════════════════════════════════════════════════════════════════
# Autonomous ETL Agent — Multi-stage Dockerfile
# Stage 1 (builder): install dependencies via UV
# Stage 2 (runtime): lean production image
# ═══════════════════════════════════════════════════════════════════════════════

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifests first (layer cache optimisation)
COPY pyproject.toml uv.lock README.md ./

# Install production dependencies into an isolated virtual environment
RUN uv sync --frozen --no-dev --no-install-project

# Copy source code
COPY src/ ./src/

# Install the project itself
RUN uv sync --frozen --no-dev

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Install Java (required for PySpark)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        openjdk-21-jre-headless \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Resolve JAVA_HOME dynamically so the same image works on amd64 and arm64
RUN JAVA_BIN=$(readlink -f /usr/bin/java) && \
    echo "export JAVA_HOME=${JAVA_BIN%/bin/java}" >> /etc/environment
ENV JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Create non-root user for security
RUN groupadd -r etlagent && useradd -r -g etlagent etlagent

WORKDIR /app

# Copy installed packages and source from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Copy config and other runtime files
COPY config/ ./config/

# Give the non-root user ownership of everything in /app
RUN chown -R etlagent:etlagent /app

# Ensure the venv is on PATH
ENV PATH="/app/.venv/bin:${PATH}"
ENV PYTHONPATH="/app/src"

# Run as non-root
USER etlagent

EXPOSE 8000

# Health check — confirms the API is responding
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

CMD ["uvicorn", "etl_agent.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
