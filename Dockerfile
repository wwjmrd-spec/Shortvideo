FROM python:3.11-slim

# Install system dependencies: ffmpeg (for video processing) and nodejs (for yt-dlp)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    nodejs \
    npm \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Create required directories for media handling
RUN mkdir -p temp downloads editor_uploads

EXPOSE 5555

# Run with Gunicorn using threads for concurrent background video rendering
CMD ["gunicorn", "--bind", "0.0.0.0:5555", "--workers", "1", "--threads", "8", "--timeout", "0", "server:app"]
