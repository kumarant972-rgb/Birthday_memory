FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Data folder (override with DATA_DIR env var + volume on hosts that support it)
ENV DATA_DIR=/app/data
EXPOSE 8000

CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8000", "--timeout", "300"]
