import subprocess
import sys
import threading
import os
import signal

def stream(proc):
    for line in iter(proc.stdout.readline, b''):
        sys.stdout.write(line.decode(errors='replace'))
        sys.stdout.flush()

procs = []

def shutdown(signum, frame):
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    sys.exit(0)

signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)

base = os.path.dirname(os.path.abspath(__file__))

print("[Launcher] Voice botlar başlatılıyor...", flush=True)
voice = subprocess.Popen(
    [sys.executable, '-u', os.path.join(base, 'voice_bots.py')],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT
)
procs.append(voice)
threading.Thread(target=stream, args=(voice,), daemon=True).start()

print("[Launcher] Ana bot başlatılıyor...", flush=True)
bot = subprocess.Popen(
    [sys.executable, '-u', os.path.join(base, 'bot.py')],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT
)
procs.append(bot)
threading.Thread(target=stream, args=(bot,), daemon=True).start()

print("[Launcher] Her iki süreç de başlatıldı.", flush=True)
bot.wait()
voice.wait()
