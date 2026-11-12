# The Brain's MCP server image (wi-brain-mcp-server; docs: packages/brain/docs/mcp.md). Built from this repo and
# versioned with it (the build argument BRAIN_VERSION, the engine's version, becomes the image's version label):
#
#   docker build -f packages/brain/container/Dockerfile --build-arg BRAIN_VERSION=<version> -t brain-mcp:<version> .
#
# from the repo's root, or through compose.yaml beside this file. No secret in the image: the machine's token is a
# secret the compose file mounts. It runs as a user that is not root, binds the container's addresses (the compose file
# publishes the port on 127.0.0.1 only) and requires the token on every request. Building it starts nothing; running it
# as a service is the owner's decision.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ARG BRAIN_VERSION=dev
LABEL org.opencontainers.image.title="brain-mcp" \
      org.opencontainers.image.description="The Brain as an MCP server (rules, decisions, procedures, graph tools)" \
      org.opencontainers.image.version="${BRAIN_VERSION}" \
      org.opencontainers.image.source="https://github.com/RoJLD/brain" \
      org.opencontainers.image.licenses="BUSL-1.1"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# git: the brain commands read the personal brain's checkout through it
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/brain
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY packages/brain ./packages/brain
# the graph engine from this same checkout, then the brain package without fetching its pinned engine tag again
RUN pip install . "pyyaml>=6" "tomli>=2; python_version < '3.11'" \
    && pip install --no-deps ./packages/brain \
    && rm -rf /opt/brain/packages/brain/tests

# /brain: the personal brain's checkout, mounted read-only; git trusts it although another user owns it
# BRAIN_HOME (/var/lib/brain), owned by the user: a named volume mounted there starts with this ownership
RUN useradd --system --uid 10001 --user-group --no-create-home --home-dir /var/lib/brain brain \
    && install -d -o 10001 -g 10001 -m 0700 /var/lib/brain \
    && git config --system --add safe.directory /brain
USER 10001:10001

ENV BRAIN_IPC_TOKEN_FILE=/run/secrets/brain-ipc-token \
    BRAIN_HOME=/var/lib/brain \
    HOME=/var/lib/brain \
    BRAIN_MCP_CONTAINER=1

EXPOSE 8791
ENTRYPOINT ["brain", "--root", "/brain", "mcp", "serve", "--http", "--host", "0.0.0.0", "--port", "8791"]
