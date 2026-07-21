FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Ho_Chi_Minh

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

# config.yaml và credentials.json được mount từ ngoài vào (xem docker-compose.yml)
CMD ["python", "-m", "src.bot"]
