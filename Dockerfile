# Debian-based image — CLIPS (clipspy) requires glibc, Alpine won't work
FROM python:3.14-slim-bookworm

# Install system deps for building clipspy
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Create non-root user
RUN useradd --create-home --shell /bin/bash fathom
USER fathom
WORKDIR /home/fathom/app

# Copy project files
COPY --chown=fathom:fathom pyproject.toml uv.lock ./
COPY --chown=fathom:fathom src/ ./src/

# Install with server extras (no dev dependencies)
RUN uv sync --extra server --no-dev

# Create mount point for rules
RUN mkdir -p /rules
VOLUME ["/rules"]

# Configurable port
ENV PORT=8080
EXPOSE ${PORT}

# Run the REST server
CMD ["uv", "run", "uvicorn", "fathom.integrations.rest:app", "--host", "0.0.0.0", "--port", "8080"]
