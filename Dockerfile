# ---------------------------------------------------------------------------
#  Deflow — autonomous options desk
#
#  Two-stage build. The first stage exists only to compile Alpaca's official
#  CLI, which is the desk's default order route: it carries its own 429/5xx
#  backoff and idempotent client order ids, and a container without it would
#  silently fall back to raw REST.
# ---------------------------------------------------------------------------

FROM golang:1.24-alpine AS cli
RUN apk add --no-cache git
RUN go install github.com/alpacahq/cli/cmd/alpaca@latest


FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DEFLOW_NO_BOOTSTRAP=1

WORKDIR /app

# uv provides the Alpaca MCP server on demand (uvx). Optional at runtime --
# the desk degrades gracefully without it -- but cheap to include.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY --from=cli /go/bin/alpaca /usr/local/bin/alpaca

# Dependencies first so application edits do not invalidate the layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# The ledger, position book and IV history live here. Mount a volume at this
# path in production: the ledger's hash chain is the artefact that makes P&L
# checkable, and losing it on redeploy destroys exactly that.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# Bind the world (a container's loopback reaches nothing) and take the port
# from the platform. Both default safely for a laptop run.
ENV DEFLOW_HOST=0.0.0.0 \
    PORT=8000
EXPOSE 8000

# Run as a non-root user.
RUN useradd --create-home --uid 10001 deflow && chown -R deflow:deflow /app
USER deflow

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",8000)}/api/health',timeout=5)"

CMD ["python", "main.py"]
