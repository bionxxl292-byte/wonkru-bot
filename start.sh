#!/bin/bash

echo "[Wonkru] === BAŞLATILIYOR ==="

echo "[Wonkru] Voice botlar başlatılıyor..."
python3 -u voice_bots.py &
VOICE_PID=$!
echo "[Wonkru] Voice PID: $VOICE_PID"

echo "[Wonkru] Ana bot başlatılıyor..."
python3 -u bot.py &
BOT_PID=$!
echo "[Wonkru] Bot PID: $BOT_PID"

trap "kill $VOICE_PID $BOT_PID 2>/dev/null" EXIT SIGTERM SIGINT

wait $VOICE_PID $BOT_PID
