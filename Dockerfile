# Track H — the single operator service (webhook + UI API + guard scheduler).
# Runs on Railway or Render as-is.
FROM python:3.13-slim

WORKDIR /app

COPY system_b/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY system_b ./system_b

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# $PORT is provided by Railway/Render; default 8000 for local `docker run`.
CMD ["sh", "-c", "uvicorn system_b.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
