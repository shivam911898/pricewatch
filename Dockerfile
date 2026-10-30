# PriceWatch - runs the dashboard, the embedded demo store and the scheduler in ONE process.
# Hugging Face Spaces (Docker SDK) expects the app on port 7860; Render/Fly/etc. inject $PORT.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEMO_MODE=1 \
    MPLCONFIGDIR=/tmp/matplotlib

# Hugging Face runs containers as uid 1000, so the app dir (SQLite file + products.yaml) must be writable by that user.
# /data is an optional mount point for a persistent volume in real deployments (see DEPLOY.md).
RUN useradd -m -u 1000 user \
 && mkdir -p /home/user/app /data \
 && chown user:user /home/user/app /data
WORKDIR /home/user/app

COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user:user . .
USER user

EXPOSE 7860
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-7860}"]
