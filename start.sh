#!/bin/bash

echo "[Wonkru] Ana bot başlatılıyor..."
python -u bot.py 2>&1 &
BOT_PID=$!

echo "[Wonkru] Voice botlar başlatılıyor..."
python -u voice_bots.py 2>&1 &
VOICE_PID=$!

trap "echo '[Wonkru] Durduruluyor...'; kill $BOT_PID $VOICE_PID 2>/dev/null" EXIT SIGTERM SIGINT

wait $BOT_PID $VOICE_PID
