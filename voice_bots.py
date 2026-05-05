import discord
import asyncio
import os
import json
import random
from datetime import datetime, timezone

import ctypes.util, glob as _glob
def _load_opus():
    name = ctypes.util.find_library("opus")
    if name:
        try:
            discord.opus.load_opus(name)
            return
        except Exception:
            pass
    for _p in sorted(_glob.glob("/nix/store/*/lib/libopus.so*")):
        try:
            discord.opus.load_opus(_p)
            return
        except Exception:
            continue
_load_opus()

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "afk_config.json")
STATUS_FILE = os.path.join(BASE_DIR, "afk_status.json")

DEFAULT_CHANNELS = {
    1: 1246832596797755398,
    2: 1246832596797755399,
    3: 1246832597351268494,
    4: 1246832597351268495,
    5: 1246832597351268496,
}


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    bots = []
    for i in range(1, 7):
        token = os.environ.get(f"VOICE_BOT_{i}", "").strip()
        if token:
            bots.append({
                "id": i,
                "token": token,
                "channelId": str(DEFAULT_CHANNELS.get(i, "")),
                "name": f"Wonkru Voice {i}",
                "enabled": True,
            })
    config = {"version": 1, "bots": bots}
    save_config(config)
    return config


def save_config(config: dict) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


bot_statuses: dict[int, dict]       = {}
active_tasks: dict[int, asyncio.Task] = {}
active_clients: dict[int, discord.Client] = {}

# Sadece bir bot aynı anda ses kanalına bağlansın
_voice_lock = asyncio.Lock()


def write_status() -> None:
    data = {
        "bots": list(bot_statuses.values()),
        "lastUpdated": datetime.now(timezone.utc).isoformat(),
    }
    with open(STATUS_FILE, "w") as f:
        json.dump(data, f, indent=2)


async def run_bot(conf: dict) -> None:
    bot_id      = conf["id"]
    token       = conf["token"]
    channel_id_str = str(conf.get("channelId", ""))
    name        = conf.get("name", f"Bot {bot_id}")

    intents = discord.Intents.default()
    intents.voice_states = True
    client = discord.Client(intents=intents)
    active_clients[bot_id] = client
    _connect_lock = asyncio.Lock()  # Bu bot için bağlantı kilidi

    bot_statuses[bot_id] = {
        "id": bot_id,
        "name": name,
        "connected": False,
        "channelName": None,
        "channelId": channel_id_str,
        "userId": None,
        "userTag": None,
        "error": None,
    }
    write_status()

    async def connect_to_channel():
        if not channel_id_str:
            return
        # Zaten bağlantı denemesi yapılıyorsa atla
        if _connect_lock.locked():
            return
        async with _connect_lock:
            await _do_connect()

    async def _do_connect():
        try:
            channel_id = int(channel_id_str)
        except ValueError:
            return
        kanal = client.get_channel(channel_id)
        if not kanal or not isinstance(kanal, discord.VoiceChannel):
            print(f"[{name}] ❌ Kanal bulunamadı: {channel_id}")
            bot_statuses[bot_id]["connected"] = False
            write_status()
            return
        guild = kanal.guild
        if guild.voice_client and guild.voice_client.channel == kanal:
            bot_statuses[bot_id]["connected"] = True
            bot_statuses[bot_id]["channelName"] = kanal.name
            write_status()
            return
        if guild.voice_client:
            try:
                await guild.voice_client.disconnect(force=True)
            except Exception:
                pass
            await asyncio.sleep(2)

        hata = "Bilinmeyen hata"
        # 5 deneme: 15s, 30s, 60s, 60s bekleme aralıkları
        bekle = [15, 30, 60, 60]
        for deneme in range(1, 6):
            try:
                print(f"[{name}] 🔄 Bağlanmaya çalışılıyor... (deneme {deneme}/5)")
                # reconnect=False: kendi retry'ımız var, discord.py iç retry'ı istemiyoruz
                vc = await asyncio.wait_for(
                    kanal.connect(reconnect=False),
                    timeout=30.0
                )
                await guild.change_voice_state(channel=kanal, self_deaf=True, self_mute=True)
                bot_statuses[bot_id]["connected"]   = True
                bot_statuses[bot_id]["channelName"] = kanal.name
                bot_statuses[bot_id]["error"]       = None
                print(f"[{name}] 🔊 {kanal.name} kanalına bağlandı. (deneme {deneme})")
                write_status()
                return
            except Exception as e:
                hata = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                print(f"[{name}] ⚠️ Deneme {deneme}/5 başarısız: {hata}")
                if guild.voice_client:
                    try:
                        await guild.voice_client.disconnect(force=True)
                    except Exception:
                        pass
                if deneme < 5:
                    bekleme = bekle[deneme - 1]
                    print(f"[{name}] ⏳ {bekleme}s sonra tekrar denenecek...")
                    await asyncio.sleep(bekleme)

        bot_statuses[bot_id]["connected"] = False
        bot_statuses[bot_id]["error"]     = hata
        print(f"[{name}] ❌ 5 denemede de bağlanamadı.")
        write_status()

    async def keepalive():
        await client.wait_until_ready()
        # İlk bağlantıyı bot ID'ye göre geciktir (eş zamanlı çakışma önlemi)
        await asyncio.sleep(bot_id * 8)
        while not client.is_closed():
            await connect_to_channel()
            # 3 dk ± 30 sn rastgele jitter
            await asyncio.sleep(180 + random.randint(-30, 30))

    @client.event
    async def on_ready():
        bot_statuses[bot_id]["userId"]  = str(client.user.id)
        bot_statuses[bot_id]["userTag"] = str(client.user)
        print(f"[{name}] ✅ {client.user} hazır.")
        asyncio.ensure_future(keepalive())

    @client.event
    async def on_voice_state_update(member, before, after):
        if member != client.user:
            return
        try:
            target_id = int(channel_id_str) if channel_id_str else None
        except ValueError:
            return
        # Bot kanaldan tamamen çıkarıldı VEYA hedef kanal dışına taşındı (AFK kanalı dahil)
        moved_away = after.channel is None or (target_id and after.channel.id != target_id)
        if moved_away:
            print(f"[{name}] ⚠️ Hedef kanaldan ayrıldı (AFK veya kick). Yeniden bağlanılıyor...")
            bot_statuses[bot_id]["connected"] = False
            write_status()
            await asyncio.sleep(5)
            await connect_to_channel()

    try:
        await client.start(token)
    except discord.LoginFailure as e:
        print(f"[{name}] ❌ Login başarısız: {e}")
        bot_statuses[bot_id]["error"]     = "Geçersiz token"
        bot_statuses[bot_id]["connected"] = False
    except Exception as e:
        print(f"[{name}] ❌ Hata: {e}")
        bot_statuses[bot_id]["error"]     = str(e)
        bot_statuses[bot_id]["connected"] = False
    finally:
        active_clients.pop(bot_id, None)
        write_status()


async def config_watcher() -> None:
    last_version: int | None = None
    running_ids: set[int]    = set()

    while True:
        try:
            config  = load_config()
            version = config.get("version", 1)

            if version != last_version:
                last_version = version
                enabled = {
                    b["id"]: b
                    for b in config.get("bots", [])
                    if b.get("enabled", True)
                }

                for bot_id in list(running_ids):
                    if bot_id not in enabled:
                        task = active_tasks.pop(bot_id, None)
                        cl   = active_clients.pop(bot_id, None)
                        if cl and not cl.is_closed():
                            try:
                                await cl.close()
                            except Exception:
                                pass
                        if task and not task.done():
                            task.cancel()
                        bot_statuses.pop(bot_id, None)
                        running_ids.discard(bot_id)
                        print(f"[Bot {bot_id}] ⏹ Durduruldu.")

                for bot_id, conf in enabled.items():
                    if bot_id not in running_ids:
                        task = asyncio.ensure_future(run_bot(conf))
                        active_tasks[bot_id] = task
                        running_ids.add(bot_id)
                        print(f"[Bot {bot_id}] ▶ Başlatılıyor: {conf['name']}")

                write_status()
        except Exception as e:
            print(f"[Config Watcher] ❌ Hata: {e}")

        await asyncio.sleep(15)


async def main() -> None:
    asyncio.ensure_future(config_watcher())
    while True:
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())
