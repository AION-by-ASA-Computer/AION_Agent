# Legacy single-stage Dockerfile (kept for backward compatibility).
# Per uso produzione: docker/Dockerfile.backend (multi-stage + uv + healthcheck).
FROM python:3.13-slim

# uv: installer Python molto piu' veloce di pip.
ARG UV_VERSION=latest
COPY --from=ghcr.io/astral-sh/uv:${UV_VERSION} /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

WORKDIR /app

# Install system dependencies if needed
# RUN apt-get update && apt-get install -y --no-install-recommends ...

COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

COPY src/ ./src/

CMD ["python", "src/main.py"]
