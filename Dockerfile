FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    libopus0 \
    ffmpeg \
    libsodium-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN SODIUM_INSTALL=system pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "-u", "launcher.py"]
