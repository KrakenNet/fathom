# syntax=docker/dockerfile:1

# CLIPS (clipspy) links against glibc, so this is a Debian image and not Alpine.
#
# Both images are pinned by digest, not by tag: a floating tag re-bases the
# runtime under the image without any change to this file, which defeats the
# point of shipping a policy engine people are meant to be able to attest.
# Bump these deliberately; `docker pull <tag>` then
# `docker image inspect <tag> --format '{{index .RepoDigests 0}}'` prints the
# replacement.
ARG PYTHON_IMAGE=python:3.13-slim-bookworm@sha256:00faa2debb87529f9f0764e9491d8ba400a3678976616c3bd7cb193745ac20d1
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1


# Named stage rather than `COPY --from=${UV_IMAGE}`: BuildKit resolves a stage
# name there, but does not reliably expand a build arg.
FROM ${UV_IMAGE} AS uvbin


FROM ${PYTHON_IMAGE} AS builder

COPY --from=uvbin /uv /bin/uv

# Byte-compile on install so the runtime stage never pays first-import cost;
# copy rather than hardlink because the cache mount and /app are separate
# filesystems.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# `uv sync` parses the ENTIRE workspace -- dev group included -- before
# `--no-dev` gets to exclude anything, so the fathom-studio member's manifest
# has to exist or the build dies with "`fathom-studio` references a workspace
# in `tool.uv.sources`, but is not a workspace member". Its sources are not
# needed and deliberately are not copied: Studio is not part of the server
# image. `packages/fathom-studio/README.md` comes along because that
# manifest's `readme` field names it.
COPY pyproject.toml uv.lock README.md ./
COPY packages/fathom-studio/pyproject.toml packages/fathom-studio/README.md ./packages/fathom-studio/

# Dependencies first, in their own layer, so editing src/ does not re-resolve
# them. `--frozen` makes the build fail rather than silently re-lock, which is
# what keeps the image reproducible from uv.lock.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra server --no-install-project

COPY src/ ./src/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra server


FROM ${PYTHON_IMAGE} AS runtime

# No compiler in the runtime image: clipspy publishes manylinux wheels for
# every Python this project supports, so nothing is built from source here.

# Root does the two things root must do -- create the user, and create the
# mount point under / -- before the image drops privileges. The previous
# Dockerfile ran `mkdir -p /rules` after `USER fathom` and could only have
# worked with a writable /, which this image does not have.
RUN useradd --create-home --shell /bin/bash fathom \
    && mkdir -p /rules \
    && chown fathom:fathom /rules

# Same path as the builder: a uv virtualenv records its own absolute location,
# so moving it between stages would break every console script inside it.
COPY --from=builder --chown=fathom:fathom /app /app

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

USER fathom
WORKDIR /app

VOLUME ["/rules"]
EXPOSE 8080

# `sh -c` so ${PORT} is expanded at run time -- the previous CMD advertised a
# configurable PORT and then hard-coded 8080, so setting it did nothing. `exec`
# keeps uvicorn as PID 1 and therefore still signal-addressable.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["sh", "-c", "python -c \"import os,sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8080') + '/health', timeout=4).status == 200 else 1)\""]

CMD ["sh", "-c", "exec uvicorn fathom.integrations.rest:app --host 0.0.0.0 --port ${PORT}"]
