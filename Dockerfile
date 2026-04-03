FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends stress-ng \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY keepalive /usr/local/bin/keepalive
COPY keepalive.py .
COPY keepalive_service keepalive_service

RUN chmod +x /usr/local/bin/keepalive

ENV PYTHONUNBUFFERED=1
ENV KEEPALIVE_DOCKERIZED=1

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD ["keepalive", "healthcheck", "--max-age", "120"]

CMD ["keepalive", "run"]
