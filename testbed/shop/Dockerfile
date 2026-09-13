FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r /app/requirements.txt

COPY app /app/app
COPY tools /app/tools

ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/data/shop.db \
    SQLITE_BUSY_TIMEOUT_MS=150

RUN mkdir -p /data

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
