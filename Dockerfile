FROM python:3.13-slim

# AWS Lambda Web Adapter: on Lambda it turns each invocation into an HTTP request to the app on AWS_LWA_PORT.
# Lambda starts it as an extension; other container hosts never run it.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.0.1 /lambda-adapter /opt/extensions/lambda-adapter

ENV AWS_LWA_PORT=8000 \
    AWS_LWA_READINESS_CHECK_PATH=/health \
    PYTHONIOENCODING=utf-8 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Lambda runs the container as its own unprivileged user; other hosts get this one (see USER) instead of root.
# The base image ships the standard library without bytecode, which Python would otherwise compile on every cold start.
RUN useradd --system --uid 10001 --no-create-home app && python -m compileall -q /usr/local/lib/python3.13

# Bytecode is compiled into the image: Lambda's disk is read-only, so Python can't cache .pyc files there and would
# compile every imported module again on each cold start. uv is mounted for this step only, so it isn't part of the image.
COPY requirements.txt .
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.26,source=/uv,target=/bin/uv \
    uv pip install --system --no-cache --compile-bytecode -r requirements.txt

COPY backend/ ./backend/
RUN python -m compileall -q backend

USER 10001

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

CMD ["python", "-m", "backend.app", "serve", "--host", "0.0.0.0", "--port", "8000"]
