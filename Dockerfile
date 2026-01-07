FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install flask requests
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

# Copy source code
COPY src/ /app/

# Create data directory
RUN mkdir -p /app/data && chmod 777 /app/data

EXPOSE 5000

CMD ["python", "app.py"]
