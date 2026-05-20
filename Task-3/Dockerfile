# ─────────────────────────────────────────────
# project/Dockerfile
# Builds the Python / Streamlit application image
# ─────────────────────────────────────────────
FROM python:3.11-slim

# System deps (psycopg2-binary needs libpq at runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /Task-3

# Install Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .
# Ensure log directory exists
RUN mkdir -p logs && touch logs/query_logs.json

EXPOSE 8501

# Health-check so Compose knows when the app is ready
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "streamlit_app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true"]
