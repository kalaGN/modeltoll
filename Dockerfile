# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    LAYA_RUNTIME=external
WORKDIR /app
COPY requirements-api.txt ./
RUN pip install --no-cache-dir --only-binary=:all: -r requirements-api.txt \
    && groupadd --gid 10001 laya \
    && useradd --uid 10001 --gid laya --no-create-home --shell /usr/sbin/nologin laya
COPY backend/app ./backend/app
COPY backend/migrations ./backend/migrations
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
