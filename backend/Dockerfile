FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Der Dienst läuft ohne Root-Rechte; /data hält hochgeladene Exporte während des Imports
RUN useradd --system --uid 10001 --no-create-home bodybase \
    && mkdir -p /data/uploads && chown -R bodybase /data
USER bodybase

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--timeout-keep-alive", "75"]
