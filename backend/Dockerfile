FROM python:3.11-slim

# Install system dependencies: FFmpeg for video audio, Tesseract for OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-eng \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and migrations
COPY . .

# Create uploads directory
RUN mkdir -p storage/uploads

EXPOSE 8000

# Run alembic migrations and start uvicorn
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
