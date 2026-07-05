FROM docker.io/library/python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tradingbot/ tradingbot/
COPY config.yaml .

ENV BOT_DATA_DIR=/data
VOLUME /data

CMD ["python", "-u", "-m", "tradingbot", "run"]
