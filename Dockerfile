FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY src/requirements.txt /app/requirements.txt
RUN pip install -r requirements.txt
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Copy source code
COPY src/ /app/

# Create data directory
RUN mkdir -p /app/data && chmod 777 /app/data

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "wsgi:app"]
