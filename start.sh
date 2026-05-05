#!/bin/bash
set -e

echo "[Wonkru] Ana bot başlatılıyor..."
python bot.py &
BOT_PID=$!

echo "[Wonkru] Voice botlar başlatılıyor..."
python voice_bots.py &
VOICE_PID=$!

trap "echo '[Wonkru] Durduruluyor...'; kill $BOT_PID $VOICE_PID 2>/dev/null" EXIT SIGTERM SIGINT

wait $BOT_PID $VOICE_PID
