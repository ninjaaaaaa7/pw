# ---------- Stage 1: build the static Next.js UI ----------
FROM node:20-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build          # -> /ui/out (static export)

# ---------- Stage 2: slim Python runtime serving API + UI ----------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STATIC_DIR=/app/static \
    ALLOWED_ORIGINS=""

# Run as an unprivileged user.
RUN useradd --create-home --uid 1000 appuser
WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=ui /ui/out ./static

USER appuser
# Hosts inject PORT (Render, Cloud Run, Railway); Hugging Face uses 7860.
ENV PORT=7860
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ['PORT']).status==200 else 1)"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
