FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/index.html frontend/vite.config.js ./
COPY frontend/src/ ./src/
RUN npm run build

FROM python:3.11-slim-bookworm AS demo
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements-api.txt requirements-semantic.txt ./
RUN pip install --no-cache-dir -r requirements-api.txt -r requirements-semantic.txt \
    && useradd --create-home --uid 1000 maintainerlens \
    && mkdir -p /app/data /app/.cache \
    && chown maintainerlens:maintainerlens /app/data /app/.cache
COPY app/ ./app/
COPY --from=frontend /build/dist/ ./frontend/dist/
USER maintainerlens
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:7860/api/health', timeout=3).close()"]
CMD ["python", "-m", "uvicorn", "app.web:app", "--host", "0.0.0.0", "--port", "7860"]
