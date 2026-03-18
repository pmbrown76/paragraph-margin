# Stage 1: Build frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.12-slim AS runtime
WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV PYTHONPATH="/app"

# Install Python dependencies (with web extras for FastAPI)
COPY pyproject.toml ./
RUN uv pip install --system -e ".[web]"

# Copy application code
COPY paragraph_margin/ paragraph_margin/
COPY api/ api/
COPY data/ data/

# Copy margin rules from TPM (included via build context or COPY)
# On Railway, set MARGIN_RULES_DIR env var to point to the rules location
COPY config/margin_rules/ config/margin_rules/

# Copy built frontend
COPY --from=frontend-build /app/frontend/dist frontend/dist/

# Copy startup script
COPY start.sh ./
RUN chmod +x start.sh

EXPOSE 8100

CMD ["./start.sh"]
