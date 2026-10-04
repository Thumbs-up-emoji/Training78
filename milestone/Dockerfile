# Cloud Run and Docker Compose image for the existing secured FastAPI boundary.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY requirements-milestone5.txt ./
RUN pip install --no-cache-dir -r requirements-milestone5.txt

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn entrypoints.milestone6_production_api:app --host 0.0.0.0 --port ${PORT:-8000}"]