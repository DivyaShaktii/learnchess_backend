FROM python:3.13-slim

# Stockfish powers analysis; espeak-ng supplies Kokoro's English phonemes.
RUN apt-get update && apt-get install -y --no-install-recommends stockfish espeak-ng && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variable for stockfish path
ENV STOCKFISH_PATH=/usr/games/stockfish

# Document the local default. Railway supplies PORT at runtime.
EXPOSE 8000

# Start the application
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
