import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
import os
import json
import threading
import http.server

# Opus kütüphanesini dinamik olarak bul ve yükle (ses kanalı için gerekli)
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
import random
from datetime import datetime, timedelta
from banner import build_banner

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=".", intents=intents)
tree = bot.tree

_BOT_DIR = os.path.dirname(os.path.abspath(__file__))
WARNINGS_FILE    = os.path.join(_BOT_DIR, "warnings.json")
LOGS_FILE        = os.path.join(_BOT_DIR, "logs.json")
DELETED_CHANNELS_FILE = os.path.join(_BOT_DIR, "deleted_channels.json")
STATS_FILE       = os.path.join(_BOT_DIR, "stats.json")
CEZA_FILE        = os.path.join(_BOT_DIR, "ceza.json")
MUTE_SAYAC_FILE  = os.path.join(_BOT_DIR, "mute_sayac.json")
AUDIT_LOG_FILE   = os.path.join(_BOT_DIR, "audit_log.json")

OTOMATIK_KARANTINA_ESIK  = 6       # kaç muteden sonra
OTOMATIK_KARANTINA_SURE  = 1440    # dakika (1 gün)

LINK_FILTRE_FILE = os.path.join(_BOT_DIR, "link_filtre.json")

import re as _re
_LINK_PATTERN = _re.compile(
    r"(https?://|www\.|discord\.gg/|discord\.com/invite/)",
    _re.IGNORECASE
)

def load_link_filtre():
    if os.path.exists(LINK_FILTRE_FILE):
        with open(LINK_FILTRE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_link_filtre(data):
    with open(LINK_FILTRE_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_link_filtre(guild_id):
    return load_link_filtre().get(str(guild_id), {"aktif": False, "muaf_roller": [], "muaf_kanallar": []})


# ── LOG HELPERS ────────────────────────────────────────────────────────────────

def load_logs():
    if os.path.exists(LOGS_FILE):
        with open(LOGS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_logs(data):
    with open(LOGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


# Log kanal tipleri ve Discord kanal isimleri
LOG_KANALLARI = {
    "genel": "📋・genel-log",
    "mute":  "🔇・mute-log",
    "kick":  "👢・kick-log",
    "ban":   "🔨・ban-log",
    "warn":  "⚠️・uyari-log",
    "rol":   "🎭・rol-log",
    "puan":  "💰・puan-log",
}


def get_log_channel_id(guild_id, log_type="genel"):
    return load_logs().get(str(guild_id), {}).get(log_type)


def set_log_channel_id(guild_id, log_type, channel_id):
    data = load_logs()
    guild_str = str(guild_id)
    if guild_str not in data:
        data[guild_str] = {}
    data[guild_str][log_type] = channel_id
    save_logs(data)


async def send_log(guild: discord.Guild, embed: discord.Embed, log_type: str = "genel", actor=None):
    # Sunucu sahibinin işlemleri loglanmaz
    if actor is not None and actor.id == guild.owner_id:
        return
    channel_id = get_log_channel_id(guild.id, log_type)
    if not channel_id:
        return
    channel = guild.get_channel(channel_id)
    if channel:
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass


def log_embed(title: str, description: str, color: discord.Color, user=None) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.utcnow())
    if user:
        embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(text="Wonkru Log Sistemi")
    return embed


def load_warnings():
    if os.path.exists(WARNINGS_FILE):
        with open(WARNINGS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_warnings(data):
    with open(WARNINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_user_warnings(guild_id, user_id):
    data = load_warnings()
    return data.get(str(guild_id), {}).get(str(user_id), [])


def add_warning(guild_id, user_id, reason, moderator):
    data = load_warnings()
    guild_str = str(guild_id)
    user_str = str(user_id)
    if guild_str not in data:
        data[guild_str] = {}
    if user_str not in data[guild_str]:
        data[guild_str][user_str] = []
    data[guild_str][user_str].append({
        "reason": reason,
        "moderator": moderator,
        "timestamp": datetime.utcnow().isoformat()
    })
    save_warnings(data)
    return len(data[guild_str][user_str])


def clear_user_warnings(guild_id, user_id):
    data = load_warnings()
    guild_str = str(guild_id)
    user_str = str(user_id)
    if guild_str in data and user_str in data[guild_str]:
        del data[guild_str][user_str]
        save_warnings(data)


# ── MUTE SAYACI ───────────────────────────────────────────────────────────────

def _ms_yukle() -> dict:
    if os.path.exists(MUTE_SAYAC_FILE):
        with open(MUTE_SAYAC_FILE, "r") as f:
            return json.load(f)
    return {}

def _ms_kaydet(data: dict):
    with open(MUTE_SAYAC_FILE, "w") as f:
        json.dump(data, f, indent=2)

def ms_artir(guild_id: int, user_id: int) -> int:
    """Mute sayacını 1 artırır, yeni değeri döndürür."""
    data = _ms_yukle()
    g, u = str(guild_id), str(user_id)
    data.setdefault(g, {})
    data[g][u] = data[g].get(u, 0) + 1
    _ms_kaydet(data)
    return data[g][u]

def ms_al(guild_id: int, user_id: int) -> int:
    return _ms_yukle().get(str(guild_id), {}).get(str(user_id), 0)

def ms_sifirla(guild_id: int, user_id: int):
    data = _ms_yukle()
    g, u = str(guild_id), str(user_id)
    if g in data and u in data[g]:
        data[g][u] = 0
        _ms_kaydet(data)


# ── DENETİM KAYDI ──────────────────────────────────────────────────────────────

def audit_log_yaz(guild_id, user_id, action: str, moderator: str, details: str = "", source: str = "bot"):
    """Denetim kaydına yeni bir eylem satırı ekler."""
    try:
        if os.path.exists(AUDIT_LOG_FILE):
            with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
                kayitlar = json.load(f)
        else:
            kayitlar = []
        kayitlar.append({
            "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            "guildId":   str(guild_id),
            "targetUserId": str(user_id),
            "action":    action,
            "moderator": moderator,
            "details":   details,
            "source":    source,
        })
        # Son 1000 kaydı tut
        kayitlar = kayitlar[-1000:]
        with open(AUDIT_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(kayitlar, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def mod_embed(title, description, color=discord.Color.red()):
    embed = discord.Embed(title=title, description=description, color=color, timestamp=datetime.utcnow())
    embed.set_footer(text="Moderation System")
    return embed


def check_hierarchy(ctx_or_interaction, moderator, target):
    if isinstance(ctx_or_interaction, commands.Context):
        guild = ctx_or_interaction.guild
    else:
        guild = ctx_or_interaction.guild
    if target == moderator:
        return "Kendinize bu işlemi uygulayamazsınız."
    if target.bot:
        return "Botlara bu işlemi uygulayamazsınız."
    if target.top_role >= moderator.top_role and moderator != guild.owner:
        return "Eşit veya üst roldeki birine bu işlemi uygulayamazsınız."
    return None


async def setup_wonkru_log(guild: discord.Guild):
    """WONKRU LOG kategorisini ve tüm log kanallarını otomatik oluşturur."""
    # Eski log kanallarını sil
    for kanal in guild.channels:
        if kanal.name.lower() in [k.lower() for k in ESKI_LOG_KANALLARI]:
            try:
                await kanal.delete(reason="WONKRU LOG kurulumu")
            except discord.Forbidden:
                pass

    # Yetki yapısı: sadece yöneticiler görebilir
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True),
    }
    for role in guild.roles:
        if role.permissions.administrator and not role.managed:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True)

    try:
        # Kategoriyi bul veya en alta oluştur
        kategori = discord.utils.get(guild.categories, name="WONKRU LOG")
        if not kategori:
            max_pos = max((c.position for c in guild.categories), default=0) if guild.categories else 0
            kategori = await guild.create_category(
                name="WONKRU LOG",
                overwrites=overwrites,
                position=max_pos + 1,
                reason="WONKRU LOG otomatik kurulumu"
            )
            print(f"   ✅ {guild.name} → WONKRU LOG kategorisi oluşturuldu")

        # Her log tipi için kanalı bul veya oluştur
        mevcut_isimler = {k.name: k for k in kategori.channels}
        for log_type, kanal_adi in LOG_KANALLARI.items():
            if kanal_adi in mevcut_isimler:
                set_log_channel_id(guild.id, log_type, mevcut_isimler[kanal_adi].id)
            else:
                yeni = await kategori.create_text_channel(name=kanal_adi, reason="WONKRU LOG kurulumu")
                set_log_channel_id(guild.id, log_type, yeni.id)
                print(f"   ✅ {guild.name} → {kanal_adi} kanalı oluşturuldu")
    except discord.Forbidden:
        print(f"   ❌ {guild.name} → WONKRU LOG oluşturulamadı (yetki eksik)")


SES_DURUM_FILE = os.path.join(_BOT_DIR, "ses_durum.json")

def ses_durum_yaz():
    """Bot Command rolüne sahip üyelerin ses kanalı durumunu dosyaya yazar."""
    try:
        result = {}
        for guild in bot.guilds:
            bot_cmd_uyeler = [
                m for m in guild.members
                if not m.bot and (
                    any(r.name.lower() == "bot command" for r in m.roles)
                    or m.guild_permissions.manage_roles
                    or m.guild_permissions.administrator
                )
            ]

            in_voice = {}
            for kanal in guild.voice_channels:
                for m in kanal.members:
                    if m.bot:
                        continue
                    vs = m.voice
                    in_voice[str(m.id)] = {
                        "channelId":   str(kanal.id),
                        "channelName": kanal.name,
                        "muted":       bool(vs and (vs.self_mute or vs.mute)),
                        "deafened":    bool(vs and (vs.self_deaf or vs.deaf)),
                        "streaming":   bool(vs and vs.self_stream),
                        "video":       bool(vs and vs.self_video),
                    }

            sesde, disarida = [], []
            for m in bot_cmd_uyeler:
                entry = {
                    "userId":      str(m.id),
                    "displayName": m.display_name,
                    "username":    str(m),
                    "topRole":     m.top_role.name if m.top_role else "",
                }
                if str(m.id) in in_voice:
                    entry.update(in_voice[str(m.id)])
                    sesde.append(entry)
                else:
                    disarida.append(entry)

            result[str(guild.id)] = {
                "guildName":   guild.name,
                "sesde":       sesde,
                "disarida":    disarida,
                "lastUpdated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            }

        with open(SES_DURUM_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"ses_durum_yaz hatası: {e}")


@bot.event
async def on_ready():
    bot.add_view(StreamPanelView())
    for guild in bot.guilds:
        await tree.sync(guild=guild)
        await setup_wonkru_log(guild)
    await tree.sync()
    if not saatlik_puan_ver.is_running():
        saatlik_puan_ver.start()
    ses_durum_yaz()
    print(f"✅ {bot.user} olarak giriş yapıldı (ID: {bot.user.id}) | PID={os.getpid()}")
    print(f"   {len(bot.guilds)} sunucuda aktif")
    print(f"   Prefix: . | Slash komutlar da aktif")


def bot_komutu_var(ctx):
    """Bot Command rolü olanlar veya manage_roles yetkisi olanlar kullanabilir."""
    if ctx.author.guild_permissions.manage_roles or ctx.author.guild_permissions.administrator:
        return True
    return any(r.name.lower() == "bot command" for r in ctx.author.roles)


@bot.event
async def on_command_error(ctx, error):
    # Local @command.error handler varsa global'i çalıştırma
    if ctx.command is not None:
        try:
            if ctx.command.has_error_handler():
                return
        except Exception:
            if hasattr(ctx.command, 'on_error'):
                return
    if isinstance(error, commands.CheckFailure):
        await ctx.send(embed=mod_embed(
            "❌ Erişim Yok",
            "Bu komutu kullanmak için **Bot Command** rolüne sahip olman gerekiyor.",
            discord.Color.red()
        ))
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=mod_embed("❌ Yetki Yok", "Bu komutu kullanmak için yetkin yok.", discord.Color.orange()))
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send(embed=mod_embed("❌ Bot Yetkisi Eksik", f"Botun şu yetkiye ihtiyacı var: {', '.join(error.missing_permissions)}", discord.Color.orange()))
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(embed=mod_embed("❌ Üye Bulunamadı", "Bu üye bulunamadı. Mention kullan veya ID gir.", discord.Color.orange()))
    elif isinstance(error, commands.MissingRequiredArgument):
        usage_hints = {
            "mute": "`.mute @kullanıcı` — Örnek: `.mute @Ahmet`",
            "unmute": "`.unmute @kullanıcı` — Örnek: `.unmute @Ahmet`",
            "kick": "`.kick @kullanıcı [sebep]` — Örnek: `.kick @Ahmet kural ihlali`",
            "ban": "`.ban @kullanıcı [sebep]` — Örnek: `.ban @Ahmet spam`",
            "warn": "`.warn @kullanıcı [sebep]` — Örnek: `.warn @Ahmet küfür`",
            "warnings": "`.warnings @kullanıcı` — Örnek: `.warnings @Ahmet`",
            "clearwarnings": "`.clearwarnings @kullanıcı` — Örnek: `.clearwarnings @Ahmet`",
            "purge": "`.purge <sayı>` — Örnek: `.purge 10`",
            "role": "`.role @kullanıcı <rol adı>` — Örnek: `.role @Ahmet Moderatör`",
            "slowmode": "`.slowmode <saniye>` — Örnek: `.slowmode 5`",
            "unban": "`.unban <kullanıcı ID>` — Örnek: `.unban 123456789`",
        }
        hint = usage_hints.get(str(ctx.command), f"`{error.param.name}` argümanı eksik.")
        await ctx.send(embed=mod_embed("❌ Eksik Argüman", f"{hint}", discord.Color.orange()))
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=mod_embed("❌ Hatalı Argüman", "Geçersiz değer girdin. Üyeyi mention'la ya da doğru değeri yaz.", discord.Color.orange()))


# ── LOG SİSTEMİ — EVENTS ──────────────────────────────────────────────────────

@bot.event
async def on_member_join(member: discord.Member):
    # Cezalı kontrolü — kayıtta varsa yeniden uygula
    ceza_data = load_ceza()
    ceza_kayit = ceza_data.get(str(member.guild.id), {}).get(str(member.id))
    if ceza_kayit:
        await _ceza_uygula(member, reason="Cezalı üye sunucuya yeniden katıldı")
        ceza_kanal = discord.utils.find(
            lambda c: "karantina" in c.name.lower() and isinstance(c, discord.TextChannel),
            member.guild.channels
        )
        if ceza_kanal:
            try:
                await ceza_kanal.send(
                    embed=mod_embed(
                        "🔒 Cezalı Üye Geri Döndü",
                        f"{member.mention} cezalı olarak sunucuya yeniden katıldı.\n"
                        f"**Sebep:** {ceza_kayit.get('sebep', '?')}\n"
                        f"**Ceza Tarihi:** {ceza_kayit.get('ceza_tarihi', '?')}",
                        discord.Color.red()
                    )
                )
            except Exception:
                pass
        return  # Welcome mesajı gösterme

    # Unregister rolünü otomatik ver
    unregister_rol = discord.utils.find(
        lambda r: r.name.lower() == "unregister", member.guild.roles
    )
    if unregister_rol:
        try:
            await member.add_roles(unregister_rol, reason="Otomatik kayıtsız rolü")
        except Exception:
            pass

    # Welcome mesajı
    welcome_kanal = discord.utils.get(member.guild.text_channels, name="welcome-to-wonkru")
    if welcome_kanal:
        uye_sayisi = member.guild.member_count
        hesap_tarihi = member.created_at.replace(tzinfo=None)
        simdi = datetime.utcnow()
        yil_fark = (simdi - hesap_tarihi).days // 365
        yil_yazi = f"{yil_fark} yıl önce" if yil_fark > 0 else "bu yıl"
        tarih_str = member.created_at.strftime("%-d %B %Y")

        hosgeldin = discord.Embed(
            description=(
                f"**W O N K R U** sunucumuza hoşgeldin, {member.mention}.\n\n"
                f"Seninle beraber sunucumuz **{uye_sayisi}** üye sayısına ulaştı.\n\n"
                f"Hesabın **{yil_yazi}** tarihinde oluşturulmuş. **({tarih_str})**\n\n"
                f"Bizi desteklemek için sunucumuzun tagını (☆) alabilirsiniz."
            ),
            color=discord.Color.gold()
        )
        hosgeldin.set_thumbnail(url=member.display_avatar.url)
        await welcome_kanal.send(embed=hosgeldin)

    # Log
    embed = log_embed(
        "📥 Üye Katıldı",
        f"**{member.mention}** sunucuya katıldı.\n"
        f"**Hesap Oluşturulma:** {member.created_at.strftime('%Y-%m-%d')}\n"
        f"**ID:** `{member.id}`",
        discord.Color.green(),
        user=member
    )
    await send_log(member.guild, embed, "genel")
    audit_log_yaz(
        member.guild.id, member.id, "join", str(member),
        f"Hesap Tarihi: {member.created_at.strftime('%Y-%m-%d')} | ID: {member.id}"
    )


@bot.event
async def on_member_remove(member: discord.Member):
    embed = log_embed(
        "📤 Üye Ayrıldı",
        f"**{member}** sunucudan ayrıldı.\n"
        f"**ID:** `{member.id}`",
        discord.Color.orange(),
        user=member
    )
    await send_log(member.guild, embed, "genel")
    # Kick mı yoksa gönüllü ayrılma mı kontrol et
    action_type = "leave"
    try:
        await asyncio.sleep(0.5)
        async for entry in member.guild.audit_logs(action=discord.AuditLogAction.kick, limit=5):
            if entry.target and entry.target.id == member.id:
                if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 6:
                    action_type = "kick_auto"
                    break
    except Exception:
        pass
    if action_type == "leave":
        audit_log_yaz(member.guild.id, member.id, "leave", str(member), f"ID: {member.id}")


@bot.event
async def on_message_delete(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    embed = log_embed(
        "🗑️ Mesaj Silindi",
        f"**Kanal:** {message.channel.mention}\n"
        f"**Yazar:** {message.author.mention} (`{message.author}`)\n"
        f"**İçerik:** {message.content[:1000] if message.content else '*[Ek/Resim]*'}",
        discord.Color.red(),
        user=message.author
    )
    await send_log(message.guild, embed, "genel")


@bot.event
async def on_message_edit(before: discord.Message, after: discord.Message):
    if before.author.bot or not before.guild or before.content == after.content:
        return
    embed = log_embed(
        "✏️ Mesaj Düzenlendi",
        f"**Kanal:** {before.channel.mention}\n"
        f"**Yazar:** {before.author.mention} (`{before.author}`)\n"
        f"**Önce:** {before.content[:500] if before.content else '-'}\n"
        f"**Sonra:** {after.content[:500] if after.content else '-'}",
        discord.Color.blue(),
        user=before.author
    )
    await send_log(before.guild, embed, "genel")


# ── LOG SİSTEMİ — KOMUTLAR ────────────────────────────────────────────────────

# Silinecek eski log kanalı isimleri
ESKI_LOG_KANALLARI = [
    "burjuva genel log",
    "burjuva ceza log",
]


@bot.command(name="logkurulum")
@commands.has_permissions(administrator=True)
@commands.bot_has_permissions(manage_channels=True)
async def logkurulum(ctx):
    """WONKRU LOG kategorisini ve tüm ayrı log kanallarını oluşturur/günceller."""
    msg = await ctx.send(embed=mod_embed("⚙️ Log Kurulumu", "WONKRU LOG kanalları oluşturuluyor...", discord.Color.blurple()))
    await setup_wonkru_log(ctx.guild)
    satirlar = "\n".join(f"• **{v}**" for v in LOG_KANALLARI.values())
    aciklama = (
        f"✅ **Log kurulumu tamamlandı!**\n\n"
        f"**WONKRU LOG** kategorisi altında şu kanallar oluşturuldu:\n{satirlar}\n\n"
        f"Her işlem türü artık kendi kanalına loglanacak."
    )
    await msg.edit(embed=mod_embed("✅ Log Kurulumu Tamamlandı", aciklama, discord.Color.green()))
    await send_log(ctx.guild, log_embed(
        "🚀 Log Sistemi Aktif",
        f"Log sistemi {ctx.author.mention} tarafından kuruldu.",
        discord.Color.green()
    ), "genel")


@bot.command(name="logkanal")
@commands.has_permissions(administrator=True)
async def logkanal(ctx):
    """Mevcut WONKRU LOG kanallarını listeler."""
    data = load_logs().get(str(ctx.guild.id), {})
    if not data:
        return await ctx.send(embed=mod_embed("📋 Log Kanalları", "Henüz log kanalı ayarlanmamış.\n`.logkurulum` komutunu çalıştır.", discord.Color.orange()))
    satirlar = []
    for log_type, kanal_adi in LOG_KANALLARI.items():
        ch_id = data.get(log_type)
        ch = ctx.guild.get_channel(ch_id) if ch_id else None
        satirlar.append(f"**{kanal_adi}** → {ch.mention if ch else '❌ Bulunamadı'}")
    await ctx.send(embed=mod_embed("📋 Log Kanalları", "\n".join(satirlar), discord.Color.blurple()))


# ── KICK ──────────────────────────────────────────────────────────────────────

@bot.command(name="kick")
@commands.has_permissions(kick_members=True)
@commands.bot_has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason: str = "Sebep belirtilmedi"):
    err = check_hierarchy(ctx, ctx.author, member)
    if err:
        return await ctx.send(embed=mod_embed("❌ Hata", err, discord.Color.orange()))
    try:
        await member.send(embed=mod_embed("👢 Sunucudan Atıldınız", f"**Sunucu:** {ctx.guild.name}\n**Sebep:** {reason}\n**Moderatör:** {ctx.author}", discord.Color.orange()))
    except discord.Forbidden:
        pass
    await member.kick(reason=f"{reason} | Moderatör: {ctx.author}")
    await ctx.send(embed=mod_embed("👢 Üye Atıldı", f"**{member}** atıldı.\n**Sebep:** {reason}\n**Moderatör:** {ctx.author.mention}", discord.Color.orange()))
    await send_log(ctx.guild, log_embed("👢 Üye Atıldı", f"**Üye:** {member} (`{member.id}`)\n**Sebep:** {reason}\n**Moderatör:** {ctx.author.mention}", discord.Color.orange(), user=member), "kick", actor=ctx.author)
    audit_log_yaz(ctx.guild.id, member.id, "kick", str(ctx.author), reason)


@tree.command(name="kick", description="Bir üyeyi sunucudan atar")
@app_commands.describe(member="Atılacak üye", reason="Atılma sebebi")
@app_commands.default_permissions(kick_members=True)
async def slash_kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Sebep belirtilmedi"):
    err = check_hierarchy(interaction, interaction.user, member)
    if err:
        return await interaction.response.send_message(embed=mod_embed("❌ Hata", err, discord.Color.orange()), ephemeral=True)
    try:
        await member.send(embed=mod_embed("👢 Sunucudan Atıldınız", f"**Sunucu:** {interaction.guild.name}\n**Sebep:** {reason}\n**Moderatör:** {interaction.user}", discord.Color.orange()))
    except discord.Forbidden:
        pass
    await member.kick(reason=f"{reason} | Moderatör: {interaction.user}")
    await interaction.response.send_message(embed=mod_embed("👢 Üye Atıldı", f"**{member}** atıldı.\n**Sebep:** {reason}\n**Moderatör:** {interaction.user.mention}", discord.Color.orange()))
    await send_log(interaction.guild, log_embed("👢 Üye Atıldı", f"**Üye:** {member} (`{member.id}`)\n**Sebep:** {reason}\n**Moderatör:** {interaction.user.mention}", discord.Color.orange(), user=member), "kick", actor=interaction.user)


# ── BAN ───────────────────────────────────────────────────────────────────────

@bot.command(name="ban")
@commands.has_permissions(ban_members=True)
@commands.bot_has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason: str = "Sebep belirtilmedi"):
    err = check_hierarchy(ctx, ctx.author, member)
    if err:
        return await ctx.send(embed=mod_embed("❌ Hata", err, discord.Color.orange()))
    try:
        await member.send(embed=mod_embed("🔨 Yasaklandınız", f"**Sunucu:** {ctx.guild.name}\n**Sebep:** {reason}\n**Moderatör:** {ctx.author}"))
    except discord.Forbidden:
        pass
    await member.ban(reason=f"{reason} | Moderatör: {ctx.author}", delete_message_days=1)
    await ctx.send(embed=mod_embed("🔨 Üye Yasaklandı", f"**{member}** yasaklandı.\n**Sebep:** {reason}\n**Moderatör:** {ctx.author.mention}"))
    await send_log(ctx.guild, log_embed("🔨 Üye Yasaklandı", f"**Üye:** {member} (`{member.id}`)\n**Sebep:** {reason}\n**Moderatör:** {ctx.author.mention}", discord.Color.red(), user=member), "ban", actor=ctx.author)
    audit_log_yaz(ctx.guild.id, member.id, "ban", str(ctx.author), reason)


@tree.command(name="ban", description="Bir üyeyi sunucudan yasaklar")
@app_commands.describe(member="Yasaklanacak üye", reason="Yasaklanma sebebi")
@app_commands.default_permissions(ban_members=True)
async def slash_ban(interaction: discord.Interaction, member: discord.Member, reason: str = "Sebep belirtilmedi"):
    err = check_hierarchy(interaction, interaction.user, member)
    if err:
        return await interaction.response.send_message(embed=mod_embed("❌ Hata", err, discord.Color.orange()), ephemeral=True)
    try:
        await member.send(embed=mod_embed("🔨 Yasaklandınız", f"**Sunucu:** {interaction.guild.name}\n**Sebep:** {reason}\n**Moderatör:** {interaction.user}"))
    except discord.Forbidden:
        pass
    await member.ban(reason=f"{reason} | Moderatör: {interaction.user}", delete_message_days=1)
    await interaction.response.send_message(embed=mod_embed("🔨 Üye Yasaklandı", f"**{member}** yasaklandı.\n**Sebep:** {reason}\n**Moderatör:** {interaction.user.mention}"))
    await send_log(interaction.guild, log_embed("🔨 Üye Yasaklandı", f"**Üye:** {member} (`{member.id}`)\n**Sebep:** {reason}\n**Moderatör:** {interaction.user.mention}", discord.Color.red(), user=member), "ban", actor=interaction.user)


# ── UNBAN ─────────────────────────────────────────────────────────────────────

@bot.command(name="unban")
@commands.has_permissions(ban_members=True)
async def unban(ctx, user_id: str):
    if not user_id.isdigit():
        return await ctx.send(embed=mod_embed("❌ Hata", "Geçerli bir kullanıcı ID'si girin.", discord.Color.orange()))
    bans = [entry async for entry in ctx.guild.bans()]
    target = next((e.user for e in bans if e.user.id == int(user_id)), None)
    if target is None:
        return await ctx.send(embed=mod_embed("❌ Bulunamadı", "Bu ID'ye sahip yasaklı kullanıcı yok.", discord.Color.orange()))
    await ctx.guild.unban(target)
    await ctx.send(embed=mod_embed("✅ Yasak Kaldırıldı", f"**{target}** kullanıcısının yasağı kaldırıldı.\n**Moderatör:** {ctx.author.mention}", discord.Color.green()))
    await send_log(ctx.guild, log_embed("✅ Yasak Kaldırıldı", f"**Kullanıcı:** {target} (`{target.id}`)\n**Moderatör:** {ctx.author.mention}", discord.Color.green()), "ban", actor=ctx.author)


@tree.command(name="unban", description="Yasaklı bir kullanıcının yasağını kaldırır")
@app_commands.describe(user_id="Yasağı kaldırılacak kullanıcının ID'si")
@app_commands.default_permissions(ban_members=True)
async def slash_unban(interaction: discord.Interaction, user_id: str):
    if not user_id.isdigit():
        return await interaction.response.send_message(embed=mod_embed("❌ Hata", "Geçerli bir kullanıcı ID'si girin.", discord.Color.orange()), ephemeral=True)
    bans = [entry async for entry in interaction.guild.bans()]
    target = next((e.user for e in bans if e.user.id == int(user_id)), None)
    if target is None:
        return await interaction.response.send_message(embed=mod_embed("❌ Bulunamadı", "Bu ID'ye sahip yasaklı kullanıcı yok.", discord.Color.orange()), ephemeral=True)
    await interaction.guild.unban(target)
    await interaction.response.send_message(embed=mod_embed("✅ Yasak Kaldırıldı", f"**{target}** kullanıcısının yasağı kaldırıldı.\n**Moderatör:** {interaction.user.mention}", discord.Color.green()))
    await send_log(interaction.guild, log_embed("✅ Yasak Kaldırıldı", f"**Kullanıcı:** {target} (`{target.id}`)\n**Moderatör:** {interaction.user.mention}", discord.Color.green()), "ban", actor=interaction.user)


# ── MUTED ROL YARDIMCISI ──────────────────────────────────────────────────────

async def get_or_create_muted_role(guild: discord.Guild) -> discord.Role:
    role = discord.utils.get(guild.roles, name="🔇 Muted")
    if role is None:
        role = await guild.create_role(
            name="🔇 Muted",
            color=discord.Color.dark_grey(),
            reason="Mute sistemi için otomatik oluşturuldu"
        )
        # Tüm text kanallarında mesaj göndermeyi kapat
        for channel in guild.channels:
            try:
                if isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
                    await channel.set_permissions(role, send_messages=False, add_reactions=False)
                elif isinstance(channel, discord.VoiceChannel):
                    await channel.set_permissions(role, speak=False)
            except discord.Forbidden:
                pass
    return role


async def remove_muted_role(member: discord.Member):
    role = discord.utils.get(member.guild.roles, name="🔇 Muted")
    if role and role in member.roles:
        await member.remove_roles(role, reason="Unmute")
    # İsimden [Muted] kaldır
    try:
        if member.nick and "[Muted]" in member.nick:
            new_nick = member.nick.replace(" [Muted]", "").replace("[Muted]", "").strip()
            await member.edit(nick=new_nick if new_nick else None)
    except discord.Forbidden:
        pass


# ── MUTE — İnteraktif Sistem ──────────────────────────────────────────────────

# Ses mute: sebep → sabit süre (dakika)
SES_MUTE_SEBEPLER = [
    ("Ailevi değerlere küfürler",                              15),
    ("Yabancı dillerde konuşmak (uyarıdan sonra)",             15),
    ("Küfür, hakaret, kışkırtma (sözlü uyarıdan sonra)",      15),
    ("Siyasi tartışmalar yapmak",                              30),
    ("Sunucu ismi vermek (uyarıdan sonra)",                    30),
    ("Kişisel sorunları sunucuya yansıtmak",                   30),
    ("Dini/milli değerlerle dalga geçmek, ırkçılık",          60),
    ("Ses kanalında cinsellik içeren konuşma/benzetme",        60),
]

# Chat mute: sebep → sabit süre (dakika)
CHAT_MUTE_SEBEPLER = [
    ("Ailevi değerlere küfürler",                              15),
    ("Yabancı dillerde konuşmak (uyarıdan sonra)",             15),
    ("Küfür, hakaret, kışkırtma (sözlü uyarıdan sonra)",      15),
    ("Metin kanalının amacı dışında kullanım",                 15),
    ("Flood, spam, capslock (kasıtlı değilse uyarı)",          15),
]


async def _uygula_mute(interaction: discord.Interaction, member: discord.Member,
                       mute_type: str, reason_label: str, dakika: int, moderator: discord.Member):
    """Mute mantığını uygular ve log atar."""
    sure_label = f"{dakika} dakika"

    if mute_type == "chat":
        until = discord.utils.utcnow() + timedelta(minutes=dakika)
        await member.timeout(until, reason=f"{reason_label} | Moderatör: {moderator}")
        muted_role = await get_or_create_muted_role(interaction.guild)
        if muted_role and muted_role not in member.roles:
            await member.add_roles(muted_role, reason="Chat Mute")
        try:
            current_nick = member.nick or member.name
            if "[Muted]" not in current_nick:
                new_nick = f"{current_nick} [Muted]"
                if len(new_nick) <= 32:
                    await member.edit(nick=new_nick)
        except discord.Forbidden:
            pass

        # DM — kullanıcıya
        dm_embed = discord.Embed(
            title="🔇  Chat'te Susturuldunuz",
            color=0xE74C3C,
            timestamp=discord.utils.utcnow()
        )
        dm_embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else member.display_avatar.url)
        dm_embed.add_field(name="🏛️ Sunucu",     value=interaction.guild.name,  inline=True)
        dm_embed.add_field(name="⏱️ Süre",        value=f"**{sure_label}**",     inline=True)
        dm_embed.add_field(name="📋 Sebep",        value=reason_label,            inline=False)
        dm_embed.add_field(name="🛡️ Moderatör",   value=str(moderator),          inline=True)
        dm_embed.set_footer(text="Wonkru Moderation")
        try:
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        # Sonuç embed — kanala
        result_embed = discord.Embed(
            title="🔇  Chat Mute Uygulandı",
            color=0xE67E22,
            timestamp=discord.utils.utcnow()
        )
        result_embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        result_embed.set_thumbnail(url=member.display_avatar.url)
        result_embed.add_field(name="👤 Üye",        value=member.mention,          inline=True)
        result_embed.add_field(name="⏱️ Süre",       value=f"**{sure_label}**",     inline=True)
        result_embed.add_field(name="📋 Sebep",       value=reason_label,            inline=False)
        result_embed.add_field(name="🛡️ Moderatör",  value=moderator.mention,       inline=True)
        result_embed.add_field(name="📝 Not",         value="İsmine `[Muted]` eklendi · 🔇 Muted rolü verildi", inline=False)
        result_embed.set_footer(text="Wonkru Moderation System")

        await send_log(interaction.guild, log_embed(
            "🔇 Chat Mute Uygulandı",
            f"**Üye:** {member.mention} (`{member.id}`)\n**Süre:** {sure_label}\n**Sebep:** {reason_label}\n**Moderatör:** {moderator.mention}",
            discord.Color.orange(), user=member
        ), "mute", actor=moderator)
        audit_log_yaz(interaction.guild.id, member.id, "mute", str(moderator), f"Chat Mute | Süre: {sure_label} | Sebep: {reason_label}")

    else:
        await member.edit(mute=True, reason=f"{reason_label} | Moderatör: {moderator}")

        # DM — kullanıcıya
        dm_embed = discord.Embed(
            title="🔇  Ses Kanalında Susturuldunuz",
            color=0xE74C3C,
            timestamp=discord.utils.utcnow()
        )
        dm_embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else member.display_avatar.url)
        dm_embed.add_field(name="🏛️ Sunucu",     value=interaction.guild.name,  inline=True)
        dm_embed.add_field(name="⏱️ Süre",        value=f"**{sure_label}**",     inline=True)
        dm_embed.add_field(name="📋 Sebep",        value=reason_label,            inline=False)
        dm_embed.add_field(name="🛡️ Moderatör",   value=str(moderator),          inline=True)
        dm_embed.set_footer(text="Wonkru Moderation")
        try:
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

        # Sonuç embed — kanala
        result_embed = discord.Embed(
            title="🔇  Ses Mute Uygulandı",
            color=0x992D22,
            timestamp=discord.utils.utcnow()
        )
        result_embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
        result_embed.set_thumbnail(url=member.display_avatar.url)
        result_embed.add_field(name="👤 Üye",        value=member.mention,          inline=True)
        result_embed.add_field(name="⏱️ Süre",       value=f"**{sure_label}**",     inline=True)
        result_embed.add_field(name="📋 Sebep",       value=reason_label,            inline=False)
        result_embed.add_field(name="🛡️ Moderatör",  value=moderator.mention,       inline=True)
        result_embed.add_field(name="📝 Not",         value="`.unmute @üye` ile kaldırılır", inline=False)
        result_embed.set_footer(text="Wonkru Moderation System")

        await send_log(interaction.guild, log_embed(
            "🔊 Ses Mute Uygulandı",
            f"**Üye:** {member.mention} (`{member.id}`)\n**Süre:** {sure_label}\n**Sebep:** {reason_label}\n**Moderatör:** {moderator.mention}",
            discord.Color.orange(), user=member
        ), "mute", actor=moderator)
        audit_log_yaz(interaction.guild.id, member.id, "mute", str(moderator), f"Ses Mute | Süre: {sure_label} | Sebep: {reason_label}")

        # ── Süre dolunca ses mute otomatik kaldır ────────────────────────────
        async def _auto_ses_unmute(m: discord.Member, sn: int):
            await asyncio.sleep(sn)
            try:
                fresh = m.guild.get_member(m.id)
                if fresh and fresh.voice and fresh.voice.mute:
                    await fresh.edit(mute=False, reason="Ses mute süresi doldu — otomatik")
                    await send_log(m.guild, log_embed(
                        "🔊 Ses Mute Otomatik Kaldırıldı",
                        f"**Üye:** {fresh.mention} (`{fresh.id}`)\n**Sebep:** Süre doldu",
                        discord.Color.green(), user=fresh
                    ), "mute")
            except Exception:
                pass
        asyncio.create_task(_auto_ses_unmute(member, dakika * 60))

    await interaction.response.edit_message(embed=result_embed, view=None)
    await asyncio.sleep(2)
    try:
        await interaction.delete_original_response()
    except discord.NotFound:
        pass

    # ── Mute sayacı & otomatik karantina ─────────────────────────────────────
    mute_toplam = ms_artir(interaction.guild.id, member.id)

    if mute_toplam >= OTOMATIK_KARANTINA_ESIK:
        ms_sifirla(interaction.guild.id, member.id)
        sebep_metin = f"Otomatik Karantina: {OTOMATIK_KARANTINA_ESIK} mute eşiğine ulaşıldı"

        # Eski rolleri ceza.json'a kaydet
        ceza_all = load_ceza()
        g_str, u_str = str(interaction.guild.id), str(member.id)
        ceza_all.setdefault(g_str, {})
        korunan_ids = {interaction.guild.default_role.id}
        eski_roller = [r.id for r in member.roles if r.id not in korunan_ids and not r.managed]
        ceza_all[g_str][u_str] = {
            "sebep":       sebep_metin,
            "ceza_tarihi": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            "cezalayan":   str(bot.user),
            "eski_roller": eski_roller,
            "sure_dakika": OTOMATIK_KARANTINA_SURE,
        }
        save_ceza(ceza_all)

        # Karantina uygula (rol + nickname)
        await _ceza_uygula(member, reason=sebep_metin)

        # Discord timeout — 1 gün
        try:
            until = discord.utils.utcnow() + timedelta(minutes=OTOMATIK_KARANTINA_SURE)
            await member.timeout(until, reason=sebep_metin)
        except discord.Forbidden:
            pass

        # DM bildir
        dm_k = discord.Embed(
            title="🔒  Karantinaya Alındınız",
            color=0xE74C3C,
            timestamp=discord.utils.utcnow()
        )
        dm_k.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else member.display_avatar.url)
        dm_k.add_field(name="🏛️ Sunucu",  value=interaction.guild.name,            inline=True)
        dm_k.add_field(name="⏱️ Süre",    value="**1 Gün**",                       inline=True)
        dm_k.add_field(name="📋 Sebep",   value=sebep_metin,                        inline=False)
        dm_k.add_field(name="📊 Mute",    value=f"{OTOMATIK_KARANTINA_ESIK} mute birikti — otomatik karantina tetiklendi", inline=False)
        dm_k.set_footer(text="Wonkru Moderation System")
        try:
            await member.send(embed=dm_k)
        except discord.Forbidden:
            pass

        # Log
        log_k = discord.Embed(
            title="🔒  Otomatik Karantina Uygulandı",
            color=0xE74C3C,
            timestamp=discord.utils.utcnow()
        )
        log_k.set_thumbnail(url=member.display_avatar.url)
        log_k.add_field(name="👤 Üye",     value=f"{member.mention} (`{member.id}`)", inline=True)
        log_k.add_field(name="⏱️ Süre",    value="**1 Gün**",                         inline=True)
        log_k.add_field(name="📊 Sebep",   value=f"{OTOMATIK_KARANTINA_ESIK} mute birikimi",  inline=False)
        log_k.add_field(name="🤖 Uygulayan", value=f"{bot.user.mention}  *(Otomatik)*",        inline=True)
        log_k.set_footer(text="Wonkru Moderation System")
        await send_log(interaction.guild, log_k, "genel")
        audit_log_yaz(interaction.guild.id, member.id, "karantina", str(bot.user), f"Otomatik Karantina: {OTOMATIK_KARANTINA_ESIK} mute birikimi")

    elif mute_toplam in (3, 5):
        # 3. ve 5. mutede uyarı DM'i
        try:
            uyari_dm = discord.Embed(
                title=f"⚠️  Mute Uyarısı — {mute_toplam}/{OTOMATIK_KARANTINA_ESIK} Mute",
                color=0xE67E22,
                timestamp=discord.utils.utcnow()
            )
            uyari_dm.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else member.display_avatar.url)
            uyari_dm.add_field(name="🏛️ Sunucu",  value=interaction.guild.name, inline=True)
            uyari_dm.add_field(name="📊 Durum",   value=f"**{mute_toplam}/{OTOMATIK_KARANTINA_ESIK}** mute",  inline=True)
            kalan = OTOMATIK_KARANTINA_ESIK - mute_toplam
            uyari_dm.add_field(
                name="⚠️ Uyarı",
                value=f"Daha **{kalan} mute** alırsan **1 günlük karantinaya** düşeceksin!",
                inline=False
            )
            uyari_dm.set_footer(text="Wonkru Moderation System")
            await member.send(embed=uyari_dm)
        except discord.Forbidden:
            pass


class SebebSec(discord.ui.Select):
    def __init__(self, member: discord.Member, mute_type: str, moderator: discord.Member):
        self.member = member
        self.mute_type = mute_type
        self.moderator = moderator
        liste = SES_MUTE_SEBEPLER if mute_type == "ses" else CHAT_MUTE_SEBEPLER
        options = [
            discord.SelectOption(
                label=f"{label[:80]}",
                value=str(i),
                description=f"⏱️ {dakika} dakika mute"
            )
            for i, (label, dakika) in enumerate(liste)
        ]
        super().__init__(placeholder="📋 Sebep seçin...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.moderator:
            return await interaction.response.send_message("Bu menüyü sadece komutu kullanan moderatör kullanabilir.", ephemeral=True)
        liste = SES_MUTE_SEBEPLER if self.mute_type == "ses" else CHAT_MUTE_SEBEPLER
        idx = int(self.values[0])
        reason_label, dakika = liste[idx]
        await _uygula_mute(interaction, self.member, self.mute_type, reason_label, dakika, self.moderator)


class SebebView(discord.ui.View):
    def __init__(self, member, mute_type, moderator):
        super().__init__(timeout=60)
        self.add_item(SebebSec(member, mute_type, moderator))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class MuteTurView(discord.ui.View):
    def __init__(self, member: discord.Member, moderator: discord.Member):
        super().__init__(timeout=60)
        self.member = member
        self.moderator = moderator

    @discord.ui.button(label="💬 Chat Mute", style=discord.ButtonStyle.danger)
    async def chat_mute(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.moderator:
            return await interaction.response.send_message("Bu menüyü sadece komutu kullanan moderatör kullanabilir.", ephemeral=True)
        embed = discord.Embed(title="💬  Chat Mute — Sebep Seçin", color=0xE67E22, timestamp=discord.utils.utcnow())
        embed.set_author(name=self.member.display_name, icon_url=self.member.display_avatar.url)
        embed.set_thumbnail(url=self.member.display_avatar.url)
        embed.add_field(name="👤 Üye",   value=self.member.mention, inline=True)
        embed.add_field(name="🆔 ID",    value=f"`{self.member.id}`", inline=True)
        embed.add_field(name="📋 İşlem", value="Aşağıdan mute sebebini seçin", inline=False)
        embed.set_footer(text="Wonkru Moderation System")
        await interaction.response.edit_message(embed=embed, view=SebebView(self.member, "chat", self.moderator))

    @discord.ui.button(label="🔊 Ses Mute", style=discord.ButtonStyle.secondary)
    async def ses_mute(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.moderator:
            return await interaction.response.send_message("Bu menüyü sadece komutu kullanan moderatör kullanabilir.", ephemeral=True)
        if self.member.voice is None:
            return await interaction.response.send_message(
                embed=mod_embed("❌ Hata", f"**{self.member}** şu an bir ses kanalında değil.", discord.Color.orange()),
                ephemeral=True
            )
        embed = discord.Embed(title="🔊  Ses Mute — Sebep Seçin", color=0x992D22, timestamp=discord.utils.utcnow())
        embed.set_author(name=self.member.display_name, icon_url=self.member.display_avatar.url)
        embed.set_thumbnail(url=self.member.display_avatar.url)
        embed.add_field(name="👤 Üye",         value=self.member.mention, inline=True)
        embed.add_field(name="🔊 Ses Kanalı",  value=self.member.voice.channel.name, inline=True)
        embed.add_field(name="📋 İşlem",       value="Aşağıdan mute sebebini seçin", inline=False)
        embed.set_footer(text="Wonkru Moderation System")
        await interaction.response.edit_message(embed=embed, view=SebebView(self.member, "ses", self.moderator))

    @discord.ui.button(label="❌ İptal", style=discord.ButtonStyle.grey)
    async def iptal(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.moderator:
            return await interaction.response.send_message("Bu menüyü sadece komutu kullanan moderatör kullanabilir.", ephemeral=True)
        embed = discord.Embed(title="❌  İptal Edildi", description="Mute işlemi iptal edildi.", color=0x95A5A6, timestamp=discord.utils.utcnow())
        embed.set_footer(text="Wonkru Moderation System")
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


@bot.command(name="mute")
@commands.has_permissions(moderate_members=True)
async def mute(ctx, member: discord.Member):
    err = check_hierarchy(ctx, ctx.author, member)
    if err:
        return await ctx.send(embed=mod_embed("❌ Hata", err, discord.Color.orange()))
    embed = discord.Embed(title="🔇  Mute — Tür Seçin", color=0xE74C3C, timestamp=discord.utils.utcnow())
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="👤 Üye",     value=member.mention,      inline=True)
    embed.add_field(name="🆔 ID",      value=f"`{member.id}`",    inline=True)
    embed.add_field(name="🎭 En Yüksek Rol", value=member.top_role.mention, inline=True)
    embed.add_field(name="📋 İşlem",   value="Aşağıdan mute türünü seçin", inline=False)
    embed.set_footer(text="Wonkru Moderation System")
    await ctx.send(embed=embed, view=MuteTurView(member, ctx.author))


@tree.command(name="mute", description="Bir üyeyi interaktif menüyle susturur")
@app_commands.describe(member="Susturulacak üye")
@app_commands.default_permissions(moderate_members=True)
async def slash_mute(interaction: discord.Interaction, member: discord.Member):
    err = check_hierarchy(interaction, interaction.user, member)
    if err:
        return await interaction.response.send_message(embed=mod_embed("❌ Hata", err, discord.Color.orange()), ephemeral=True)
    embed = discord.Embed(title="🔇  Mute — Tür Seçin", color=0xE74C3C, timestamp=discord.utils.utcnow())
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="👤 Üye",     value=member.mention,      inline=True)
    embed.add_field(name="🆔 ID",      value=f"`{member.id}`",    inline=True)
    embed.add_field(name="🎭 En Yüksek Rol", value=member.top_role.mention, inline=True)
    embed.add_field(name="📋 İşlem",   value="Aşağıdan mute türünü seçin", inline=False)
    embed.set_footer(text="Wonkru Moderation System")
    await interaction.response.send_message(embed=embed, view=MuteTurView(member, interaction.user))


# ── UNMUTE ────────────────────────────────────────────────────────────────────

async def do_unmute(member: discord.Member):
    muted_role = discord.utils.get(member.guild.roles, name="🔇 Muted")
    has_role = muted_role and muted_role in member.roles
    has_timeout = member.timed_out_until is not None
    has_voice_mute = member.voice and member.voice.mute

    if not has_role and not has_timeout and not has_voice_mute:
        return False

    if has_timeout:
        await member.timeout(None)
    if has_role:
        await remove_muted_role(member)
    if has_voice_mute:
        try:
            await member.edit(mute=False)
        except discord.Forbidden:
            pass
    return True


@bot.command(name="unmute")
@commands.has_permissions(moderate_members=True)
@commands.bot_has_permissions(moderate_members=True)
async def unmute(ctx, member: discord.Member):
    success = await do_unmute(member)
    if not success:
        return await ctx.send(embed=mod_embed("❌ Hata", f"**{member}** zaten susturulmuş değil.", discord.Color.orange()))
    await ctx.send(embed=mod_embed("🔊 Susturma Kaldırıldı", f"**{member}** artık konuşabilir.\n🔇 Muted rolü kaldırıldı, ismi eski haline döndü.\n**Moderatör:** {ctx.author.mention}", discord.Color.green()))
    await send_log(ctx.guild, log_embed("🔊 Susturma Kaldırıldı", f"**Üye:** {member.mention} (`{member.id}`)\n**Moderatör:** {ctx.author.mention}", discord.Color.green(), user=member), "mute", actor=ctx.author)
    audit_log_yaz(ctx.guild.id, member.id, "unmute", str(ctx.author))


@tree.command(name="unmute", description="Susturulmuş bir üyenin susturmasını kaldırır")
@app_commands.describe(member="Susturması kaldırılacak üye")
@app_commands.default_permissions(moderate_members=True)
async def slash_unmute(interaction: discord.Interaction, member: discord.Member):
    success = await do_unmute(member)
    if not success:
        return await interaction.response.send_message(embed=mod_embed("❌ Hata", f"**{member}** zaten susturulmuş değil.", discord.Color.orange()), ephemeral=True)
    await interaction.response.send_message(embed=mod_embed("🔊 Susturma Kaldırıldı", f"**{member}** artık konuşabilir.\n🔇 Muted rolü kaldırıldı, ismi eski haline döndü.\n**Moderatör:** {interaction.user.mention}", discord.Color.green()))
    await send_log(interaction.guild, log_embed("🔊 Susturma Kaldırıldı", f"**Üye:** {member.mention} (`{member.id}`)\n**Moderatör:** {interaction.user.mention}", discord.Color.green(), user=member), "mute", actor=interaction.user)


# ── TIMEOUT ───────────────────────────────────────────────────────────────────

TIMEOUT_IZIN_ROLLER = ["kayıt sorumlusu", "kayıt denetleyicisi", "kayıt lideri"]


def sure_parse(metin: str) -> int | None:
    """'30', '30dk', '2s', '1sa', '1d', '1gun' → dakika döndürür. None = geçersiz."""
    metin = metin.lower().strip()
    birimler = {
        "hafta": 10080, "h": 10080,
        "gun": 1440, "gün": 1440, "g": 1440, "d": 1440,
        "saat": 60, "sa": 60, "s": 60,
        "dakika": 1, "dk": 1, "m": 1,
    }
    import re as _re
    eslesme = _re.fullmatch(r"(\d+)\s*([a-züöşçığ]*)", metin)
    if not eslesme:
        return None
    sayi, birim = int(eslesme.group(1)), eslesme.group(2)
    if not birim:
        return sayi  # varsayılan: dakika
    return sayi * birimler.get(birim, 0) or None


TIMEOUT_SEBEPLER = [
    ("Çık Gir Atma",                   "1 Saat",  60),
    ("Küfür Etme / Trol Yapma",        "3 Saat",  180),
    ("Dini/Milli Değerlere Sövme",     "3 Gün",   4320),
]

# Sadece unregister'a uygulayabilen roller
TIMEOUT_SINIRLI_ROLLER = ["kayıt sorumlusu", "kayıt denetleyicisi"]


def moderator_sinirli_mi(moderator: discord.Member) -> bool:
    """Moderatörün sadece unregister'a timeout uygulayabilecek rolü var mı?"""
    roller = [r.name.lower() for r in moderator.roles]
    return any(r in roller for r in TIMEOUT_SINIRLI_ROLLER)


def uye_unregister_mi(uye: discord.Member) -> bool:
    """Üyenin unregister rolü var mı?"""
    return any(r.name.lower() == "unregister" for r in uye.roles)


def has_timeout_role():
    async def predicate(ctx):
        roller = [r.name.lower() for r in ctx.author.roles]
        if any(izin in roller for izin in TIMEOUT_IZIN_ROLLER):
            return True
        raise commands.CheckFailure("timeout_rol_yok")
    return commands.check(predicate)


def dakika_to_label(dakika: int) -> str:
    if dakika >= 1440:
        return f"{dakika // 1440} gün" + (f" {(dakika % 1440) // 60} saat" if (dakika % 1440) >= 60 else "")
    elif dakika >= 60:
        return f"{dakika // 60} saat" + (f" {dakika % 60} dakika" if dakika % 60 else "")
    return f"{dakika} dakika"


async def _uygula_timeout(hedef, uye: discord.Member, moderator, dakika: int,
                          sebep: str, sure_label: str):
    """Timeout uygular, DM gönderir, log atar. hedef = ctx veya interaction."""
    until = discord.utils.utcnow() + timedelta(minutes=dakika)
    try:
        await uye.timeout(until, reason=f"{sebep} | Moderatör: {moderator}")
    except discord.Forbidden:
        err = mod_embed("❌ Yetki Hatası", "Botta bu üyeye timeout uygulama yetkisi yok.", discord.Color.red())
        if hasattr(hedef, "response"):
            return await hedef.response.edit_message(embed=err, view=None)
        return await hedef.send(embed=err)

    try:
        await uye.send(embed=mod_embed(
            "⏱️ Timeout Uygulandı",
            f"**Sunucu:** {uye.guild.name}\n**Süre:** {sure_label}\n**Sebep:** {sebep}\n**Moderatör:** {moderator}",
            discord.Color.orange()
        ))
    except discord.Forbidden:
        pass

    result_embed = mod_embed(
        "⏱️ Timeout Uygulandı",
        f"**Üye:** {uye.mention}\n**Süre:** {sure_label}\n**Sebep:** {sebep}\n**Moderatör:** {moderator.mention}",
        discord.Color.orange()
    )
    await send_log(uye.guild, log_embed(
        "⏱️ Timeout Uygulandı",
        f"**Üye:** {uye.mention} (`{uye.id}`)\n**Süre:** {sure_label}\n**Sebep:** {sebep}\n**Moderatör:** {moderator.mention}",
        discord.Color.orange(), user=uye
    ), "mute", actor=moderator)

    if hasattr(hedef, "response"):
        await hedef.response.edit_message(embed=result_embed, view=None)
    else:
        await hedef.send(embed=result_embed)


class TimeoutSebebSec(discord.ui.Select):
    def __init__(self, uye: discord.Member, moderator: discord.Member):
        self.uye = uye
        self.moderator = moderator
        options = [
            discord.SelectOption(
                label=label,
                value=str(i),
                description=f"⏱️ {sure_label} Timeout"
            )
            for i, (label, sure_label, _) in enumerate(TIMEOUT_SEBEPLER)
        ]
        super().__init__(placeholder="📋 Sebep seçin...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.moderator:
            return await interaction.response.send_message(
                "Bu menüyü sadece komutu kullanan moderatör kullanabilir.", ephemeral=True
            )
        if moderator_sinirli_mi(self.moderator) and not uye_unregister_mi(self.uye):
            return await interaction.response.send_message(
                embed=mod_embed(
                    "❌ Yetersiz Yetki",
                    f"**Kayıt Sorumlusu** ve **Kayıt Denetleyicisi** sadece **Unregister** rolündeki üyelere timeout uygulayabilir.",
                    discord.Color.red()
                ), ephemeral=True
            )
        idx = int(self.values[0])
        sebep, sure_label, dakika = TIMEOUT_SEBEPLER[idx]
        await _uygula_timeout(interaction, self.uye, self.moderator, dakika, sebep, sure_label)


class TimeoutSebebView(discord.ui.View):
    def __init__(self, uye, moderator):
        super().__init__(timeout=60)
        self.add_item(TimeoutSebebSec(uye, moderator))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


@bot.command(name="timeout", aliases=["zaman_asimi", "zamanasimi"])
@has_timeout_role()
async def timeout_cmd(ctx, uye: discord.Member, sure: str = "", *, sebep: str = ""):
    """Üyeye timeout uygular: .timeout @üye [süre] [sebep]"""

    if uye.id == ctx.guild.owner_id:
        return await ctx.send(embed=mod_embed("❌ Hata", "Sunucu sahibine timeout verilemez.", discord.Color.red()))
    if uye.top_role >= ctx.author.top_role:
        return await ctx.send(embed=mod_embed("❌ Yetersiz Yetki", "Kendi rolünden yüksek/eşit birine timeout verilemez.", discord.Color.red()))
    if uye.bot:
        return await ctx.send(embed=mod_embed("❌ Hata", "Botlara timeout verilemez.", discord.Color.red()))

    # Sorumlu/Denetleyici → sadece Unregister'a uygulayabilir
    if moderator_sinirli_mi(ctx.author) and not uye_unregister_mi(uye):
        return await ctx.send(embed=mod_embed(
            "❌ Yetersiz Yetki",
            f"**Kayıt Sorumlusu** ve **Kayıt Denetleyicisi** sadece **Unregister** rolündeki üyelere timeout uygulayabilir.",
            discord.Color.red()
        ))

    # Süre verilmediyse menü göster
    if not sure:
        menu_embed = mod_embed(
            "⏱️ Timeout — Sebep Seçin",
            f"**Üye:** {uye.mention}\n\nAşağıdan sebep seçin. Süre otomatik uygulanır.",
            discord.Color.orange()
        )
        return await ctx.send(embed=menu_embed, view=TimeoutSebebView(uye, ctx.author))

    # Manuel süre + sebep
    dakika = sure_parse(sure)
    if not dakika or dakika <= 0:
        return await ctx.send(embed=mod_embed("❌ Geçersiz Süre", "Geçerli bir süre gir. Örnek: `10`, `30dk`, `2s`, `1g`", discord.Color.orange()))

    MAX_DAKIKA = 28 * 24 * 60
    if dakika > MAX_DAKIKA:
        return await ctx.send(embed=mod_embed("❌ Süre Çok Uzun", "Maksimum timeout süresi **28 gün**dür.", discord.Color.orange()))

    sure_label = dakika_to_label(dakika)
    await _uygula_timeout(ctx, uye, ctx.author, dakika, sebep or "Belirtilmedi", sure_label)


@timeout_cmd.error
async def timeout_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        roller = " / ".join(r.title() for r in TIMEOUT_IZIN_ROLLER)
        return await ctx.send(embed=mod_embed(
            "❌ Yetersiz Yetki",
            f"Bu komutu kullanmak için şu rollerden birine sahip olman gerekiyor:\n**{roller}**",
            discord.Color.red()
        ))
    if isinstance(error, commands.MissingRequiredArgument):
        return await ctx.send(embed=mod_embed(
            "❌ Eksik Bilgi",
            "**Kullanım:** `.timeout @üye` (menü) veya `.timeout @üye 30dk Sebep`",
            discord.Color.orange()
        ))


# ── WARN ──────────────────────────────────────────────────────────────────────

@bot.command(name="warn")
@commands.has_permissions(kick_members=True)
async def warn(ctx, member: discord.Member, *, reason: str = "Sebep belirtilmedi"):
    if member.bot:
        return await ctx.send(embed=mod_embed("❌ Hata", "Botlara uyarı verilemez.", discord.Color.orange()))
    count = add_warning(ctx.guild.id, member.id, reason, str(ctx.author))
    try:
        await member.send(embed=mod_embed("⚠️ Uyarıldınız", f"**Sunucu:** {ctx.guild.name}\n**Sebep:** {reason}\n**Moderatör:** {ctx.author}\n**Toplam:** {count}", discord.Color.yellow()))
    except discord.Forbidden:
        pass
    await ctx.send(embed=mod_embed("⚠️ Uyarı Verildi", f"**{member}** uyarıldı. (Toplam **{count}** uyarı)\n**Sebep:** {reason}\n**Moderatör:** {ctx.author.mention}", discord.Color.yellow()))
    await send_log(ctx.guild, log_embed("⚠️ Uyarı Verildi", f"**Üye:** {member.mention} (`{member.id}`)\n**Sebep:** {reason}\n**Toplam:** {count}\n**Moderatör:** {ctx.author.mention}", discord.Color.yellow(), user=member), "warn", actor=ctx.author)
    audit_log_yaz(ctx.guild.id, member.id, "warn", str(ctx.author), f"{reason} (Toplam: {count})")


@tree.command(name="warn", description="Bir üyeye uyarı verir")
@app_commands.describe(member="Uyarılacak üye", reason="Uyarı sebebi")
@app_commands.default_permissions(kick_members=True)
async def slash_warn(interaction: discord.Interaction, member: discord.Member, reason: str = "Sebep belirtilmedi"):
    if member.bot:
        return await interaction.response.send_message(embed=mod_embed("❌ Hata", "Botlara uyarı verilemez.", discord.Color.orange()), ephemeral=True)
    count = add_warning(interaction.guild.id, member.id, reason, str(interaction.user))
    try:
        await member.send(embed=mod_embed("⚠️ Uyarıldınız", f"**Sunucu:** {interaction.guild.name}\n**Sebep:** {reason}\n**Moderatör:** {interaction.user}\n**Toplam:** {count}", discord.Color.yellow()))
    except discord.Forbidden:
        pass
    await interaction.response.send_message(embed=mod_embed("⚠️ Uyarı Verildi", f"**{member}** uyarıldı. (Toplam **{count}** uyarı)\n**Sebep:** {reason}\n**Moderatör:** {interaction.user.mention}", discord.Color.yellow()))
    await send_log(interaction.guild, log_embed("⚠️ Uyarı Verildi", f"**Üye:** {member.mention} (`{member.id}`)\n**Sebep:** {reason}\n**Toplam:** {count}\n**Moderatör:** {interaction.user.mention}", discord.Color.yellow(), user=member), "warn", actor=interaction.user)


# ── WARNINGS ──────────────────────────────────────────────────────────────────

@bot.command(name="warnings")
@commands.has_permissions(kick_members=True)
async def warnings(ctx, member: discord.Member):
    warns = get_user_warnings(ctx.guild.id, member.id)
    if not warns:
        return await ctx.send(embed=mod_embed("📋 Uyarılar", f"**{member}** hiç uyarı almamış.", discord.Color.green()))
    desc = f"**{member}** — **{len(warns)}** uyarı:\n\n"
    for i, w in enumerate(warns, 1):
        desc += f"**{i}.** {w['reason']} — {w['moderator']} ({w['timestamp'][:10]})\n"
    await ctx.send(embed=mod_embed("📋 Uyarılar", desc, discord.Color.yellow()))


@tree.command(name="warnings", description="Bir üyenin uyarılarını gösterir")
@app_commands.describe(member="Uyarıları görüntülenecek üye")
@app_commands.default_permissions(kick_members=True)
async def slash_warnings(interaction: discord.Interaction, member: discord.Member):
    warns = get_user_warnings(interaction.guild.id, member.id)
    if not warns:
        return await interaction.response.send_message(embed=mod_embed("📋 Uyarılar", f"**{member}** hiç uyarı almamış.", discord.Color.green()))
    desc = f"**{member}** — **{len(warns)}** uyarı:\n\n"
    for i, w in enumerate(warns, 1):
        desc += f"**{i}.** {w['reason']} — {w['moderator']} ({w['timestamp'][:10]})\n"
    await interaction.response.send_message(embed=mod_embed("📋 Uyarılar", desc, discord.Color.yellow()))


# ── CLEARWARNINGS ─────────────────────────────────────────────────────────────

@bot.command(name="clearwarnings")
@commands.has_permissions(kick_members=True)
async def clearwarnings(ctx, member: discord.Member):
    clear_user_warnings(ctx.guild.id, member.id)
    await ctx.send(embed=mod_embed("✅ Uyarılar Temizlendi", f"**{member}** kullanıcısının tüm uyarıları silindi.\n**Moderatör:** {ctx.author.mention}", discord.Color.green()))


@tree.command(name="clearwarnings", description="Bir üyenin tüm uyarılarını temizler")
@app_commands.describe(member="Uyarıları temizlenecek üye")
@app_commands.default_permissions(kick_members=True)
async def slash_clearwarnings(interaction: discord.Interaction, member: discord.Member):
    clear_user_warnings(interaction.guild.id, member.id)
    await interaction.response.send_message(embed=mod_embed("✅ Uyarılar Temizlendi", f"**{member}** kullanıcısının tüm uyarıları silindi.\n**Moderatör:** {interaction.user.mention}", discord.Color.green()))


# ── SİCİL ────────────────────────────────────────────────────────────────────

@bot.command(name="sicil", aliases=["gecmis", "cezalog"])
@commands.has_permissions(kick_members=True)
async def sicil(ctx, *, hedef: str = None):
    """Kullanıcının tüm ceza geçmişini gösterir. Mention, isim veya ID kabul eder."""
    if hedef is None:
        return await ctx.send(embed=mod_embed("❌ Hata", "Kullanım: `.sicil @üye` veya `.sicil <ID>`", discord.Color.red()))

    # Üyeyi bul: mention > ID > isim
    member = None
    user = None
    hedef = hedef.strip()

    if ctx.message.mentions:
        member = ctx.message.mentions[0]
        user = member
    else:
        # ID mi?
        try:
            uid = int(hedef.strip("<@!>"))
            member = ctx.guild.get_member(uid)
            if member is None:
                try:
                    user = await bot.fetch_user(uid)
                except discord.NotFound:
                    pass
            else:
                user = member
        except ValueError:
            # İsimle ara
            member = discord.utils.find(
                lambda m: hedef.lower() in m.display_name.lower() or hedef.lower() in m.name.lower(),
                ctx.guild.members
            )
            user = member

    if user is None and member is None:
        return await ctx.send(embed=mod_embed("❌ Bulunamadı", f"`{hedef}` adında bir kullanıcı bulunamadı.", discord.Color.red()))

    target = member or user
    guild_id = ctx.guild.id
    user_id = target.id

    # ── Veri topla ────────────────────────────────────────────────────────────
    warns = get_user_warnings(guild_id, user_id)

    ceza_data = load_ceza().get(str(guild_id), {}).get(str(user_id))

    ru_data = _ru_yukle().get(str(guild_id), {})
    rol_ihlal = ru_data.get(str(user_id), 0)

    timeout_bitis = None
    is_banned = False
    if member:
        if member.timed_out_until:
            timeout_bitis = member.timed_out_until
        # Ban kontrolü
        try:
            await ctx.guild.fetch_ban(target)
            is_banned = True
        except discord.NotFound:
            pass

    # ── Renk: temiz → yeşil, az → sarı, orta → turuncu, ağır → kırmızı ─────
    toplam_agirlik = len(warns) + (3 if ceza_data else 0) + (3 if is_banned else 0) + (2 if timeout_bitis else 0)
    if toplam_agirlik == 0:
        renk = 0x2ECC71
    elif toplam_agirlik <= 2:
        renk = 0xF1C40F
    elif toplam_agirlik <= 5:
        renk = 0xE67E22
    else:
        renk = 0xE74C3C

    # ── Ana embed ─────────────────────────────────────────────────────────────
    embed = discord.Embed(
        title="📋  Ceza Sicili",
        color=renk,
        timestamp=discord.utils.utcnow()
    )
    embed.set_author(name=str(target), icon_url=target.display_avatar.url)
    embed.set_thumbnail(url=target.display_avatar.url)

    # Kimlik bilgileri
    katilma = f"<t:{int(member.joined_at.timestamp())}:R>" if member and member.joined_at else "—"
    hesap   = f"<t:{int(target.created_at.timestamp())}:R>"
    embed.add_field(name="👤 Kullanıcı",   value=f"{target.mention}\n`{target.id}`",  inline=True)
    embed.add_field(name="📅 Sunucuya Katılma", value=katilma,                         inline=True)
    embed.add_field(name="🗓️ Hesap Açılış", value=hesap,                              inline=True)

    # Ban durumu
    if is_banned:
        embed.add_field(name="🔨 Ban Durumu", value="❌ **BANLI**", inline=True)

    # Aktif Discord timeout
    if timeout_bitis:
        embed.add_field(
            name="⏳ Aktif Timeout",
            value=f"<t:{int(timeout_bitis.timestamp())}:R> bitiyor",
            inline=True
        )

    # Aktif ceza (karantina)
    if ceza_data:
        sure_dk = ceza_data.get("sure_dakika", 0)
        if sure_dk >= 1440:
            sure_str = f"{sure_dk // 1440} Gün"
        elif sure_dk >= 60:
            sure_str = f"{sure_dk // 60} Saat"
        else:
            sure_str = f"{sure_dk} Dakika"
        embed.add_field(
            name="🔒 Aktif Karantina",
            value=(
                f"**Sebep:** {ceza_data.get('sebep', '?')}\n"
                f"**Süre:** {sure_str}\n"
                f"**Tarih:** {ceza_data.get('ceza_tarihi', '?')}\n"
                f"**Cezalayan:** {ceza_data.get('cezalayan', '?')}"
            ),
            inline=False
        )

    # Uyarılar
    warn_sayi = len(warns)
    warn_bar  = "🟥" * min(warn_sayi, 5) + "⬛" * max(0, 5 - warn_sayi)
    embed.add_field(
        name=f"⚠️ Uyarılar ({warn_sayi})",
        value=warn_bar if warn_sayi == 0 else warn_bar + "\n" + "\n".join(
            f"`{i}.` **{w['reason'][:60]}**\n　└ {w['moderator']} • {w['timestamp'][:10]}"
            for i, w in enumerate(warns[-5:], max(1, warn_sayi - 4))
        ),
        inline=False
    )

    # Mute sayacı
    mute_sayi = ms_al(guild_id, user_id)
    mute_bar  = "🟥" * min(mute_sayi, OTOMATIK_KARANTINA_ESIK) + "⬛" * max(0, OTOMATIK_KARANTINA_ESIK - mute_sayi)
    embed.add_field(
        name=f"🔇 Mute Sayacı ({mute_sayi}/{OTOMATIK_KARANTINA_ESIK})",
        value=f"{mute_bar}\n{'⚠️ Bir daha muteyse karantina!' if mute_sayi == OTOMATIK_KARANTINA_ESIK - 1 else f'{OTOMATIK_KARANTINA_ESIK - mute_sayi} mute kaldı'}",
        inline=False
    )

    # Rol ihlal sayacı
    rol_bar = "🟥" * min(rol_ihlal, 3) + "⬛" * (3 - min(rol_ihlal, 3))
    embed.add_field(
        name="🎭 Rol Verme İhlali",
        value=f"{rol_bar}  **{rol_ihlal}/3**",
        inline=True
    )

    # Genel özet
    if toplam_agirlik == 0:
        ozet = "✅ Temiz sicil"
    elif is_banned:
        ozet = "🔨 Sunucudan banlı"
    elif ceza_data:
        ozet = "🔒 Aktif karantinada"
    elif timeout_bitis:
        ozet = "⏳ Timeout altında"
    elif warn_sayi >= 3:
        ozet = "⚠️ Çok uyarı aldı"
    else:
        ozet = "⚠️ Uyarı geçmişi var"

    embed.add_field(name="📊 Genel Durum", value=ozet, inline=True)

    if warn_sayi > 5:
        embed.set_footer(text=f"Son 5 uyarı gösteriliyor • Toplam {warn_sayi} uyarı • Wonkru Moderation")
    else:
        embed.set_footer(text="Wonkru Moderation System")

    await ctx.send(embed=embed)


# ── PURGE ─────────────────────────────────────────────────────────────────────

@bot.command(name="purge", aliases=["sil"])
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True)
async def purge(ctx, miktar: str):
    await ctx.message.delete()

    # .sil all — kanalın tamamını sil
    if miktar.lower() == "all":
        bilgi = await ctx.send(embed=mod_embed("⏳ Siliniyor...", "Tüm mesajlar siliniyor, lütfen bekle...", discord.Color.orange()))
        toplam = 0
        while True:
            # bulk delete 14 günden eski olmayan mesajları siler
            silinen = await ctx.channel.purge(limit=100, before=bilgi)
            toplam += len(silinen)
            if len(silinen) < 100:
                break
        try:
            await bilgi.delete()
        except Exception:
            pass
        msg = await ctx.send(embed=mod_embed("🗑️ Tüm Mesajlar Silindi", f"**{toplam}** mesaj silindi.\n**Moderatör:** {ctx.author.mention}", discord.Color.green()))
        await msg.delete(delay=5)
        return

    # .sil 15 — belirli sayıda sil
    try:
        adet = int(miktar)
    except ValueError:
        return await ctx.send(embed=mod_embed("❌ Hata", "Bir sayı ya da `all` yazın.\n**Örnek:** `.sil 15` · `.sil all`", discord.Color.orange()))

    if adet < 1 or adet > 1000:
        return await ctx.send(embed=mod_embed("❌ Hata", "1 ile 1000 arasında bir sayı girin.", discord.Color.orange()))

    deleted = await ctx.channel.purge(limit=adet)
    msg = await ctx.send(embed=mod_embed("🗑️ Mesajlar Silindi", f"**{len(deleted)}** mesaj silindi.\n**Moderatör:** {ctx.author.mention}", discord.Color.green()))
    await msg.delete(delay=4)


@tree.command(name="purge", description="Kanaldan mesaj siler (maks 100)")
@app_commands.describe(adet="Silinecek mesaj sayısı (1-100)")
@app_commands.default_permissions(manage_messages=True)
async def slash_purge(interaction: discord.Interaction, adet: int):
    if adet < 1 or adet > 100:
        return await interaction.response.send_message(embed=mod_embed("❌ Hata", "1 ile 100 arasında bir sayı girin.", discord.Color.orange()), ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=adet)
    await interaction.followup.send(embed=mod_embed("🗑️ Mesajlar Silindi", f"**{len(deleted)}** mesaj silindi.", discord.Color.green()), ephemeral=True)


# ── TAG KOMUTU ────────────────────────────────────────────────────────────────

@bot.command(name="tag")
async def tag_ekle(ctx, uye: discord.Member = None):
    """Nicke 𖣂 sunucu tagı ekler. Başkasına eklemek için manage_nicknames gerekli."""
    TAG = "𖣂"
    hedef = uye or ctx.author

    if hedef != ctx.author and not ctx.author.guild_permissions.manage_nicknames:
        return await ctx.send(embed=mod_embed(
            "❌ Yetki Gerekli",
            "Başkasının nickine tag eklemek için **Nickname Yönetme** yetkisi gerekli.",
            discord.Color.red()
        ))

    mevcut = hedef.nick or hedef.name
    if mevcut.startswith(TAG):
        return await ctx.send(embed=mod_embed(
            "ℹ️ Zaten Var",
            f"{hedef.mention} zaten `{TAG}` tagına sahip.",
            discord.Color.blurple()
        ))

    yeni_nick = f"{TAG} {mevcut.lstrip()}"
    _nick_isleniyor.add(hedef.id)
    try:
        await hedef.edit(nick=yeni_nick, reason=f"Tag eklendi — {ctx.author}")
    except discord.Forbidden:
        await ctx.send(embed=mod_embed(
            "❌ Hata",
            "Nickname değiştirilemedi (yetki yetersiz).",
            discord.Color.red()
        ))
        _nick_isleniyor.discard(hedef.id)
        return
    finally:
        _nick_isleniyor.discard(hedef.id)

    # Kendi tagını aldıysa → Wonkru Family rolü ver
    rol_mesaji = ""
    if hedef == ctx.author:
        family_rol = discord.utils.find(
            lambda r: "wonkru family" in r.name.lower(),
            ctx.guild.roles
        )
        if family_rol and family_rol not in hedef.roles:
            try:
                await hedef.add_roles(family_rol, reason="Tag alındı → Wonkru Family")
                rol_mesaji = f"\n🎉 **{family_rol.name}** rolü verildi!"
            except discord.Forbidden:
                rol_mesaji = "\n⚠️ Wonkru Family rolü verilemedi (yetki yetersiz)."

    await ctx.send(embed=mod_embed(
        "✅ Tag Eklendi",
        f"{hedef.mention} → `{yeni_nick}`{rol_mesaji}",
        discord.Color.green()
    ))


# ── LİNK FİLTRESİ ─────────────────────────────────────────────────────────────

@bot.group(name="linkfiltre", aliases=["lf"], invoke_without_command=True)
@commands.has_permissions(manage_guild=True)
async def linkfiltre(ctx):
    lf = get_link_filtre(ctx.guild.id)
    durum = "🟢 Açık" if lf.get("aktif") else "🔴 Kapalı"
    muaf_roller = [ctx.guild.get_role(r) for r in lf.get("muaf_roller", []) if ctx.guild.get_role(r)]
    muaf_kanallar = [ctx.guild.get_channel(c) for c in lf.get("muaf_kanallar", []) if ctx.guild.get_channel(c)]
    embed = discord.Embed(title="🔗 Link Filtresi", color=discord.Color.blurple())
    embed.add_field(name="Durum", value=durum, inline=False)
    embed.add_field(name="Muaf Roller", value=" ".join(r.mention for r in muaf_roller) or "Yok", inline=False)
    embed.add_field(name="Muaf Kanallar", value=" ".join(c.mention for c in muaf_kanallar) or "Yok", inline=False)
    embed.set_footer(text="Komutlar: .linkfiltre aç | kapat | rol @rol | kanal #kanal | rolçıkar @rol | kanalçıkar #kanal")
    await ctx.send(embed=embed)

@linkfiltre.command(name="aç", aliases=["ac"])
@commands.has_permissions(manage_guild=True)
async def linkfiltre_ac(ctx):
    data = load_link_filtre()
    gid = str(ctx.guild.id)
    if gid not in data:
        data[gid] = {"aktif": False, "muaf_roller": [], "muaf_kanallar": []}
    data[gid]["aktif"] = True
    save_link_filtre(data)
    await ctx.send(embed=mod_embed("🟢 Link Filtresi Açıldı", "Artık izinsiz linkler otomatik silinecek.", discord.Color.green()))

@linkfiltre.command(name="kapat")
@commands.has_permissions(manage_guild=True)
async def linkfiltre_kapat(ctx):
    data = load_link_filtre()
    gid = str(ctx.guild.id)
    if gid not in data:
        data[gid] = {"aktif": False, "muaf_roller": [], "muaf_kanallar": []}
    data[gid]["aktif"] = False
    save_link_filtre(data)
    await ctx.send(embed=mod_embed("🔴 Link Filtresi Kapatıldı", "Link filtresi devre dışı.", discord.Color.orange()))

@linkfiltre.command(name="rol")
@commands.has_permissions(manage_guild=True)
async def linkfiltre_rol(ctx, rol: discord.Role):
    data = load_link_filtre()
    gid = str(ctx.guild.id)
    if gid not in data:
        data[gid] = {"aktif": False, "muaf_roller": [], "muaf_kanallar": []}
    if rol.id not in data[gid]["muaf_roller"]:
        data[gid]["muaf_roller"].append(rol.id)
    save_link_filtre(data)
    await ctx.send(embed=mod_embed("✅ Muaf Rol Eklendi", f"{rol.mention} artık link gönderebilir.", discord.Color.green()))

@linkfiltre.command(name="rolçıkar", aliases=["rolcikar"])
@commands.has_permissions(manage_guild=True)
async def linkfiltre_rolcikar(ctx, rol: discord.Role):
    data = load_link_filtre()
    gid = str(ctx.guild.id)
    if gid not in data:
        data[gid] = {"aktif": False, "muaf_roller": [], "muaf_kanallar": []}
    data[gid]["muaf_roller"] = [r for r in data[gid]["muaf_roller"] if r != rol.id]
    save_link_filtre(data)
    await ctx.send(embed=mod_embed("✅ Muaf Rol Kaldırıldı", f"{rol.mention} artık link gönderemez.", discord.Color.orange()))

@linkfiltre.command(name="kanal")
@commands.has_permissions(manage_guild=True)
async def linkfiltre_kanal(ctx, kanal: discord.TextChannel):
    data = load_link_filtre()
    gid = str(ctx.guild.id)
    if gid not in data:
        data[gid] = {"aktif": False, "muaf_roller": [], "muaf_kanallar": []}
    if kanal.id not in data[gid]["muaf_kanallar"]:
        data[gid]["muaf_kanallar"].append(kanal.id)
    save_link_filtre(data)
    await ctx.send(embed=mod_embed("✅ Muaf Kanal Eklendi", f"{kanal.mention} kanalında link serbest.", discord.Color.green()))

@linkfiltre.command(name="kanalçıkar", aliases=["kanalcikar"])
@commands.has_permissions(manage_guild=True)
async def linkfiltre_kanalcikar(ctx, kanal: discord.TextChannel):
    data = load_link_filtre()
    gid = str(ctx.guild.id)
    if gid not in data:
        data[gid] = {"aktif": False, "muaf_roller": [], "muaf_kanallar": []}
    data[gid]["muaf_kanallar"] = [c for c in data[gid]["muaf_kanallar"] if c != kanal.id]
    save_link_filtre(data)
    await ctx.send(embed=mod_embed("✅ Muaf Kanal Kaldırıldı", f"{kanal.mention} artık link filtresi kapsamında.", discord.Color.orange()))


# ── USERINFO ──────────────────────────────────────────────────────────────────

@bot.command(name="userinfo")
@commands.has_permissions(kick_members=True)
async def userinfo(ctx, member: discord.Member = None):
    member = member or ctx.author
    warns = get_user_warnings(ctx.guild.id, member.id)
    embed = discord.Embed(title=f"Üye Bilgisi — {member}", color=discord.Color.blurple(), timestamp=datetime.utcnow())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="ID", value=member.id, inline=True)
    embed.add_field(name="Takma Ad", value=member.nick or "Yok", inline=True)
    embed.add_field(name="Bot", value="Evet" if member.bot else "Hayır", inline=True)
    embed.add_field(name="Hesap Oluşturulma", value=member.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.add_field(name="Sunucuya Katılma", value=member.joined_at.strftime("%Y-%m-%d") if member.joined_at else "?", inline=True)
    embed.add_field(name="Uyarı Sayısı", value=str(len(warns)), inline=True)
    roles = [r.mention for r in member.roles if r != ctx.guild.default_role]
    embed.add_field(name=f"Roller ({len(roles)})", value=", ".join(roles) if roles else "Yok", inline=False)
    embed.set_footer(text="Moderation System")
    await ctx.send(embed=embed)


@tree.command(name="userinfo", description="Bir üyenin bilgilerini gösterir")
@app_commands.describe(member="Bilgileri görüntülenecek üye")
@app_commands.default_permissions(kick_members=True)
async def slash_userinfo(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    warns = get_user_warnings(interaction.guild.id, member.id)
    embed = discord.Embed(title=f"Üye Bilgisi — {member}", color=discord.Color.blurple(), timestamp=datetime.utcnow())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="ID", value=member.id, inline=True)
    embed.add_field(name="Takma Ad", value=member.nick or "Yok", inline=True)
    embed.add_field(name="Bot", value="Evet" if member.bot else "Hayır", inline=True)
    embed.add_field(name="Hesap Oluşturulma", value=member.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.add_field(name="Sunucuya Katılma", value=member.joined_at.strftime("%Y-%m-%d") if member.joined_at else "?", inline=True)
    embed.add_field(name="Uyarı Sayısı", value=str(len(warns)), inline=True)
    roles = [r.mention for r in member.roles if r != interaction.guild.default_role]
    embed.add_field(name=f"Roller ({len(roles)})", value=", ".join(roles) if roles else "Yok", inline=False)
    embed.set_footer(text="Moderation System")
    await interaction.response.send_message(embed=embed)


# ── ROLE ──────────────────────────────────────────────────────────────────────

@bot.command(name="role")
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def role(ctx, member: discord.Member, *, rol: str):
    found = discord.utils.find(lambda r: r.name.lower() == rol.lower(), ctx.guild.roles)
    if not found:
        return await ctx.send(embed=mod_embed("❌ Bulunamadı", f"`{rol}` adında bir rol yok.", discord.Color.orange()))
    if found >= ctx.guild.me.top_role:
        return await ctx.send(embed=mod_embed("❌ Yetki Hatası", "Bu rol botun rolünden yüksek.", discord.Color.orange()))
    if found >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        return await ctx.send(embed=mod_embed("❌ Yetki Hatası", "Kendi rolünden yüksek bir rol atayamazsın.", discord.Color.orange()))
    if found in member.roles:
        await member.remove_roles(found)
        await ctx.send(embed=mod_embed("➖ Rol Kaldırıldı", f"**{member}** — **{found.name}** rolü kaldırıldı.\n**Moderatör:** {ctx.author.mention}", discord.Color.orange()))
    else:
        await member.add_roles(found)
        await ctx.send(embed=mod_embed("➕ Rol Verildi", f"**{member}** — **{found.name}** rolü verildi.\n**Moderatör:** {ctx.author.mention}", discord.Color.green()))


@tree.command(name="role", description="Üyeye rol ekler veya kaldırır")
@app_commands.describe(member="Üye", rol="Rol adı")
@app_commands.default_permissions(manage_roles=True)
async def slash_role(interaction: discord.Interaction, member: discord.Member, rol: str):
    found = discord.utils.find(lambda r: r.name.lower() == rol.lower(), interaction.guild.roles)
    if not found:
        return await interaction.response.send_message(embed=mod_embed("❌ Bulunamadı", f"`{rol}` adında bir rol yok.", discord.Color.orange()), ephemeral=True)
    if found >= interaction.guild.me.top_role:
        return await interaction.response.send_message(embed=mod_embed("❌ Yetki Hatası", "Bu rol botun rolünden yüksek.", discord.Color.orange()), ephemeral=True)
    if found >= interaction.user.top_role and interaction.user != interaction.guild.owner:
        return await interaction.response.send_message(embed=mod_embed("❌ Yetki Hatası", "Kendi rolünden yüksek bir rol atayamazsın.", discord.Color.orange()), ephemeral=True)
    if found in member.roles:
        await member.remove_roles(found)
        await interaction.response.send_message(embed=mod_embed("➖ Rol Kaldırıldı", f"**{member}** — **{found.name}** rolü kaldırıldı.\n**Moderatör:** {interaction.user.mention}", discord.Color.orange()))
    else:
        await member.add_roles(found)
        await interaction.response.send_message(embed=mod_embed("➕ Rol Verildi", f"**{member}** — **{found.name}** rolü verildi.\n**Moderatör:** {interaction.user.mention}", discord.Color.green()))


# ── YETKİ ─────────────────────────────────────────────────────────────────────

class YetkiVerSelect(discord.ui.Select):
    def __init__(self, member: discord.Member, moderator: discord.Member, roles: list):
        self.member = member
        self.moderator = moderator
        options = [
            discord.SelectOption(
                label=r.name[:100],
                value=str(r.id),
                description="✅ Zaten sahip" if r in member.roles else None,
                emoji="✅" if r in member.roles else "➕"
            )
            for r in roles[:25]
        ]
        super().__init__(placeholder="🎭 Vermek istediğin rolü seç...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.moderator:
            return await interaction.response.send_message("Bu menüyü sadece komutu kullanan yönetici kullanabilir.", ephemeral=True)
        role = interaction.guild.get_role(int(self.values[0]))
        if role is None:
            return await interaction.response.send_message("Rol bulunamadı.", ephemeral=True)
        if role in self.member.roles:
            return await interaction.response.edit_message(
                embed=mod_embed("⚠️ Zaten Var", f"**{self.member.mention}** zaten **{role.name}** rolüne sahip.", discord.Color.orange()),
                view=None
            )
        await self.member.add_roles(role, reason=f"Yönetici: {self.moderator}")
        await interaction.response.edit_message(
            embed=mod_embed("✅ Rol Verildi", f"**{self.member.mention}** adlı üyeye **{role.name}** rolü verildi.\n**Yönetici:** {self.moderator.mention}", discord.Color.green()),
            view=None
        )
        await send_log(interaction.guild, log_embed("➕ Rol Verildi", f"**Üye:** {self.member.mention} (`{self.member.id}`)\n**Rol:** {role.name}\n**Yönetici:** {self.moderator.mention}", discord.Color.green(), user=self.member), "rol", actor=self.moderator)


class YetkiAlSelect(discord.ui.Select):
    def __init__(self, member: discord.Member, moderator: discord.Member, roles: list):
        self.member = member
        self.moderator = moderator
        options = [
            discord.SelectOption(label=r.name[:100], value=str(r.id), emoji="➖")
            for r in roles[:25]
        ]
        super().__init__(placeholder="🎭 Kaldırmak istediğin rolü seç...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.moderator:
            return await interaction.response.send_message("Bu menüyü sadece komutu kullanan yönetici kullanabilir.", ephemeral=True)
        role = interaction.guild.get_role(int(self.values[0]))
        if role is None:
            return await interaction.response.send_message("Rol bulunamadı.", ephemeral=True)
        await self.member.remove_roles(role, reason=f"Yönetici: {self.moderator}")
        await interaction.response.edit_message(
            embed=mod_embed("➖ Rol Kaldırıldı", f"**{self.member.mention}** adlı üyeden **{role.name}** rolü kaldırıldı.\n**Yönetici:** {self.moderator.mention}", discord.Color.orange()),
            view=None
        )
        await send_log(interaction.guild, log_embed("➖ Rol Kaldırıldı", f"**Üye:** {self.member.mention} (`{self.member.id}`)\n**Rol:** {role.name}\n**Yönetici:** {self.moderator.mention}", discord.Color.orange(), user=self.member), "rol", actor=self.moderator)


class YetkiView(discord.ui.View):
    def __init__(self, select_item):
        super().__init__(timeout=60)
        self.add_item(select_item)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


@bot.group(name="yetki", invoke_without_command=True)
@commands.has_permissions(administrator=True)
async def yetki(ctx):
    embed = mod_embed(
        "📋 Yetki Komutları",
        "**Kullanım:**\n"
        "`.yetki ver @kullanıcı` — Rol ver (menüden seç)\n"
        "`.yetki al @kullanıcı` — Rol kaldır (menüden seç)\n"
        "`.yetki wonkru @kullanıcı <rol>` — Wonkru yetkisi ver\n\n"
        "**Wonkru Roller:** hera · posedion · chole · athena · artemis · dein · best · god · king\n\n"
        "**Örnek:**\n"
        "`.yetki wonkru @Ahmet hera`",
        discord.Color.blurple()
    )
    await ctx.send(embed=embed)


@yetki.command(name="ver")
@commands.has_permissions(administrator=True)
@commands.bot_has_permissions(manage_roles=True)
async def yetki_ver(ctx, member: discord.Member):
    # Botun verebileceği rolleri filtrele (bot rolünden düşük, @everyone hariç)
    assignable = [
        r for r in sorted(ctx.guild.roles, key=lambda x: x.position, reverse=True)
        if r != ctx.guild.default_role
        and r < ctx.guild.me.top_role
        and not r.managed
    ]
    if not assignable:
        return await ctx.send(embed=mod_embed("❌ Hata", "Atanabilecek rol bulunamadı.", discord.Color.orange()))

    embed = mod_embed(
        "🎭 Rol Ver",
        f"**Üye:** {member.mention}\n\nAşağıdan vermek istediğin rolü seç:",
        discord.Color.blurple()
    )
    await ctx.send(embed=embed, view=YetkiView(YetkiVerSelect(member, ctx.author, assignable)))


@yetki.command(name="al")
@commands.has_permissions(administrator=True)
@commands.bot_has_permissions(manage_roles=True)
async def yetki_al(ctx, member: discord.Member):
    # Üyenin sahip olduğu kaldırılabilir rolleri göster
    removable = [
        r for r in sorted(member.roles, key=lambda x: x.position, reverse=True)
        if r != ctx.guild.default_role
        and r < ctx.guild.me.top_role
        and not r.managed
    ]
    if not removable:
        return await ctx.send(embed=mod_embed("❌ Hata", f"**{member.mention}** adlı üyede kaldırılabilecek rol yok.", discord.Color.orange()))

    embed = mod_embed(
        "🎭 Rol Kaldır",
        f"**Üye:** {member.mention}\n\nAşağıdan kaldırmak istediğin rolü seç:",
        discord.Color.orange()
    )
    await ctx.send(embed=embed, view=YetkiView(YetkiAlSelect(member, ctx.author, removable)))


# ── SLOWMODE ──────────────────────────────────────────────────────────────────

@bot.command(name="slowmode")
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def slowmode(ctx, saniye: int):
    if saniye < 0 or saniye > 21600:
        return await ctx.send(embed=mod_embed("❌ Hata", "0 ile 21600 saniye arasında bir değer girin.", discord.Color.orange()))
    await ctx.channel.edit(slowmode_delay=saniye)
    if saniye == 0:
        await ctx.send(embed=mod_embed("✅ Yavaş Mod Kapatıldı", f"{ctx.channel.mention} yavaş modu kapatıldı.\n**Moderatör:** {ctx.author.mention}", discord.Color.green()))
    else:
        await ctx.send(embed=mod_embed("🐢 Yavaş Mod Açıldı", f"{ctx.channel.mention} — **{saniye} saniyelik** yavaş mod.\n**Moderatör:** {ctx.author.mention}", discord.Color.orange()))


@tree.command(name="slowmode", description="Kanal yavaş modunu ayarlar")
@app_commands.describe(saniye="Bekleme süresi (0 = kapat, maks 21600)")
@app_commands.default_permissions(manage_channels=True)
async def slash_slowmode(interaction: discord.Interaction, saniye: int):
    if saniye < 0 or saniye > 21600:
        return await interaction.response.send_message(embed=mod_embed("❌ Hata", "0 ile 21600 saniye arasında bir değer girin.", discord.Color.orange()), ephemeral=True)
    await interaction.channel.edit(slowmode_delay=saniye)
    if saniye == 0:
        await interaction.response.send_message(embed=mod_embed("✅ Yavaş Mod Kapatıldı", f"{interaction.channel.mention} yavaş modu kapatıldı.\n**Moderatör:** {interaction.user.mention}", discord.Color.green()))
    else:
        await interaction.response.send_message(embed=mod_embed("🐢 Yavaş Mod Açıldı", f"{interaction.channel.mention} — **{saniye} saniyelik** yavaş mod.\n**Moderatör:** {interaction.user.mention}", discord.Color.orange()))


# ── LOCK / UNLOCK ─────────────────────────────────────────────────────────────

@bot.command(name="lock")
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def lock(ctx, *, reason: str = "Sebep belirtilmedi"):
    ow = ctx.channel.overwrites_for(ctx.guild.default_role)
    ow.send_messages = False
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=ow)
    await ctx.send(embed=mod_embed("🔒 Kanal Kilitlendi", f"{ctx.channel.mention} kilitlendi.\n**Sebep:** {reason}\n**Moderatör:** {ctx.author.mention}"))


@tree.command(name="lock", description="Kanalı kilitler")
@app_commands.describe(reason="Kilitleme sebebi")
@app_commands.default_permissions(manage_channels=True)
async def slash_lock(interaction: discord.Interaction, reason: str = "Sebep belirtilmedi"):
    ow = interaction.channel.overwrites_for(interaction.guild.default_role)
    ow.send_messages = False
    await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=ow)
    await interaction.response.send_message(embed=mod_embed("🔒 Kanal Kilitlendi", f"{interaction.channel.mention} kilitlendi.\n**Sebep:** {reason}\n**Moderatör:** {interaction.user.mention}"))


@bot.command(name="unlock")
@commands.has_permissions(manage_channels=True)
@commands.bot_has_permissions(manage_channels=True)
async def unlock(ctx):
    ow = ctx.channel.overwrites_for(ctx.guild.default_role)
    ow.send_messages = None
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=ow)
    await ctx.send(embed=mod_embed("🔓 Kanal Açıldı", f"{ctx.channel.mention} artık açık.\n**Moderatör:** {ctx.author.mention}", discord.Color.green()))


@tree.command(name="unlock", description="Kilitli kanalı açar")
@app_commands.default_permissions(manage_channels=True)
async def slash_unlock(interaction: discord.Interaction):
    ow = interaction.channel.overwrites_for(interaction.guild.default_role)
    ow.send_messages = None
    await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=ow)
    await interaction.response.send_message(embed=mod_embed("🔓 Kanal Açıldı", f"{interaction.channel.mention} artık açık.\n**Moderatör:** {interaction.user.mention}", discord.Color.green()))


# ── SERVERINFO ────────────────────────────────────────────────────────────────

@bot.command(name="serverinfo")
async def serverinfo(ctx):
    guild = ctx.guild
    embed = discord.Embed(title=f"Sunucu Bilgisi — {guild.name}", color=discord.Color.blurple(), timestamp=datetime.utcnow())
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="Sunucu ID", value=guild.id, inline=True)
    embed.add_field(name="Sahip", value=guild.owner.mention if guild.owner else "?", inline=True)
    embed.add_field(name="Üye Sayısı", value=guild.member_count, inline=True)
    embed.add_field(name="Kanal Sayısı", value=len(guild.channels), inline=True)
    embed.add_field(name="Rol Sayısı", value=len(guild.roles), inline=True)
    embed.add_field(name="Boost Seviyesi", value=f"Seviye {guild.premium_tier}", inline=True)
    embed.add_field(name="Kuruluş Tarihi", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.set_footer(text="Moderation System")
    await ctx.send(embed=embed)


@tree.command(name="serverinfo", description="Sunucu bilgilerini gösterir")
async def slash_serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"Sunucu Bilgisi — {guild.name}", color=discord.Color.blurple(), timestamp=datetime.utcnow())
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.add_field(name="Sunucu ID", value=guild.id, inline=True)
    embed.add_field(name="Sahip", value=guild.owner.mention if guild.owner else "?", inline=True)
    embed.add_field(name="Üye Sayısı", value=guild.member_count, inline=True)
    embed.add_field(name="Kanal Sayısı", value=len(guild.channels), inline=True)
    embed.add_field(name="Rol Sayısı", value=len(guild.roles), inline=True)
    embed.add_field(name="Boost Seviyesi", value=f"Seviye {guild.premium_tier}", inline=True)
    embed.add_field(name="Kuruluş Tarihi", value=guild.created_at.strftime("%Y-%m-%d"), inline=True)
    embed.set_footer(text="Moderation System")
    await interaction.response.send_message(embed=embed)


# ── KANAL SİL ─────────────────────────────────────────────────────────────────

def load_deleted_channels():
    if os.path.exists(DELETED_CHANNELS_FILE):
        with open(DELETED_CHANNELS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_deleted_channels(data):
    with open(DELETED_CHANNELS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def save_kanal_snapshot(guild: discord.Guild, kanal, deleted_by: str):
    """Kanal silinmeden önce tüm bilgilerini kaydeder."""
    data = load_deleted_channels()
    guild_str = str(guild.id)
    if guild_str not in data:
        data[guild_str] = []

    overwrites = []
    for target, overwrite in kanal.overwrites.items():
        allow, deny = overwrite.pair()
        overwrites.append({
            "id": target.id,
            "type": "role" if isinstance(target, discord.Role) else "member",
            "allow": allow.value,
            "deny": deny.value
        })

    snapshot = {
        "name": kanal.name,
        "type": str(kanal.type).split(".")[-1],
        "category_id": kanal.category_id,
        "position": kanal.position,
        "overwrites": overwrites,
        "deleted_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "deleted_by": deleted_by
    }
    if isinstance(kanal, discord.TextChannel):
        snapshot["topic"] = kanal.topic
        snapshot["slowmode"] = kanal.slowmode_delay
        snapshot["nsfw"] = kanal.is_nsfw()
    elif isinstance(kanal, discord.VoiceChannel):
        snapshot["bitrate"] = kanal.bitrate
        snapshot["user_limit"] = kanal.user_limit

    data[guild_str].insert(0, snapshot)
    data[guild_str] = data[guild_str][:50]
    save_deleted_channels(data)


async def restore_kanal(guild: discord.Guild, snapshot: dict):
    """Kaydedilen snapshot'tan kanalı yeniden oluşturur."""
    overwrites = {}
    for ow in snapshot.get("overwrites", []):
        target = guild.get_role(ow["id"]) if ow["type"] == "role" else guild.get_member(ow["id"])
        if target:
            overwrites[target] = discord.PermissionOverwrite.from_pair(
                discord.Permissions(ow["allow"]), discord.Permissions(ow["deny"])
            )

    category = guild.get_channel(snapshot["category_id"]) if snapshot.get("category_id") else None
    ch_type = snapshot["type"]

    if ch_type == "text":
        return await guild.create_text_channel(
            name=snapshot["name"], overwrites=overwrites, category=category,
            position=snapshot.get("position", 0), topic=snapshot.get("topic"),
            slowmode_delay=snapshot.get("slowmode", 0), nsfw=snapshot.get("nsfw", False)
        )
    elif ch_type == "voice":
        return await guild.create_voice_channel(
            name=snapshot["name"], overwrites=overwrites, category=category,
            position=snapshot.get("position", 0),
            bitrate=min(snapshot.get("bitrate", 64000), guild.bitrate_limit),
            user_limit=snapshot.get("user_limit", 0)
        )
    elif ch_type == "category":
        return await guild.create_category(
            name=snapshot["name"], overwrites=overwrites, position=snapshot.get("position", 0)
        )
    elif ch_type in ("stage_voice", "stage"):
        return await guild.create_stage_channel(
            name=snapshot["name"], overwrites=overwrites, category=category,
            position=snapshot.get("position", 0)
        )
    return None


async def _kanal_sil_callback(interaction: discord.Interaction, sahip_id: int, secilen_idler: list):
    """Seçilen kanal ID'lerini siler — her iki Select menüsünden de çağrılır."""
    if interaction.user.id != sahip_id:
        return await interaction.response.send_message("Bu menüyü sadece sunucu sahibi kullanabilir.", ephemeral=True)

    await interaction.response.edit_message(
        embed=mod_embed("⏳ Siliniyor...", f"**{len(secilen_idler)}** öğe siliniyor...", discord.Color.orange()),
        view=None
    )

    silinen, hata = [], []
    for kanal_id in secilen_idler:
        kanal = interaction.guild.get_channel(int(kanal_id))
        if not kanal:
            hata.append(f"ID:{kanal_id}")
            continue
        kanal_adi = kanal.name
        try:
            save_kanal_snapshot(interaction.guild, kanal, str(interaction.user))
            await send_log(interaction.guild, log_embed(
                "🗑️ Kanal Silindi",
                f"**Kanal:** #{kanal_adi}\n**Silen:** {interaction.user.mention}",
                discord.Color.red()
            ), "genel")
            await kanal.delete(reason=f"Sunucu sahibi tarafından silindi: {interaction.user}")
            silinen.append(f"#{kanal_adi}")
        except discord.Forbidden:
            hata.append(f"#{kanal_adi} (yetki yok)")

    aciklama = ""
    if silinen:
        aciklama += f"✅ **Silinen ({len(silinen)}):**\n" + "\n".join(silinen)
    if hata:
        aciklama += f"\n\n❌ **Silinemedi ({len(hata)}):**\n" + "\n".join(hata)

    await interaction.edit_original_response(
        embed=mod_embed("🗑️ İşlem Tamamlandı", aciklama.strip(), discord.Color.green())
    )


class KategoriSilSelect(discord.ui.Select):
    def __init__(self, kategoriler: list, sahip_id: int):
        self.sahip_id = sahip_id
        options = [
            discord.SelectOption(label=k.name[:100], value=str(k.id), emoji="📁", description="Kategori")
            for k in kategoriler[:25]
        ]
        super().__init__(
            placeholder="📁 Kategori seç (birden fazla seçebilirsin)...",
            options=options, min_values=1, max_values=len(options)
        )

    async def callback(self, interaction: discord.Interaction):
        await _kanal_sil_callback(interaction, self.sahip_id, self.values)


class KanalSilSelect(discord.ui.Select):
    def __init__(self, kanallar: list, sahip_id: int):
        self.sahip_id = sahip_id
        options = []
        for k in kanallar[:25]:
            if isinstance(k, discord.TextChannel):
                emoji, tur = "💬", "Metin"
            elif isinstance(k, discord.VoiceChannel):
                emoji, tur = "🔊", "Ses"
            elif isinstance(k, discord.StageChannel):
                emoji, tur = "🎙️", "Sahne"
            else:
                emoji, tur = "📌", "Kanal"
            options.append(discord.SelectOption(
                label=k.name[:100], value=str(k.id), emoji=emoji,
                description=f"{tur} · {k.category.name[:50] if k.category else 'Kategorisiz'}"
            ))
        super().__init__(
            placeholder="💬 Kanal seç (birden fazla seçebilirsin)...",
            options=options, min_values=1, max_values=len(options)
        )

    async def callback(self, interaction: discord.Interaction):
        await _kanal_sil_callback(interaction, self.sahip_id, self.values)


class KanalSilView(discord.ui.View):
    def __init__(self, kategoriler: list, kanallar: list, sahip_id: int, sayfa: int = 0):
        super().__init__(timeout=120)
        self.kategoriler = kategoriler
        self.kanallar = kanallar
        self.sahip_id = sahip_id
        self.sayfa = sayfa
        self._build()

    def _build(self):
        self.clear_items()
        toplam_sayfa = max(1, (len(self.kanallar) + 24) // 25)

        if self.kategoriler:
            self.add_item(KategoriSilSelect(self.kategoriler, self.sahip_id))

        sayfa_kanallar = self.kanallar[self.sayfa * 25:(self.sayfa + 1) * 25]
        if sayfa_kanallar:
            self.add_item(KanalSilSelect(sayfa_kanallar, self.sahip_id))

        if toplam_sayfa > 1:
            onceki = discord.ui.Button(
                label="◀ Önceki", style=discord.ButtonStyle.secondary,
                disabled=(self.sayfa == 0), row=2
            )
            onceki.callback = self._onceki
            self.add_item(onceki)

            sayac = discord.ui.Button(
                label=f"Sayfa {self.sayfa + 1} / {toplam_sayfa}",
                style=discord.ButtonStyle.primary, disabled=True, row=2
            )
            self.add_item(sayac)

            sonraki = discord.ui.Button(
                label="Sonraki ▶", style=discord.ButtonStyle.secondary,
                disabled=(self.sayfa >= toplam_sayfa - 1), row=2
            )
            sonraki.callback = self._sonraki
            self.add_item(sonraki)

    async def _onceki(self, interaction: discord.Interaction):
        if interaction.user.id != self.sahip_id:
            return await interaction.response.send_message("Sadece sunucu sahibi kullanabilir.", ephemeral=True)
        self.sayfa -= 1
        self._build()
        await interaction.response.edit_message(view=self)

    async def _sonraki(self, interaction: discord.Interaction):
        if interaction.user.id != self.sahip_id:
            return await interaction.response.send_message("Sadece sunucu sahibi kullanabilir.", ephemeral=True)
        self.sayfa += 1
        self._build()
        await interaction.response.edit_message(view=self)


@bot.command(name="kanalsil")
async def kanalsil(ctx):
    """Kategorileri ve kanalları ayrı menülerde gösterir. Sadece sunucu sahibi kullanabilir."""
    if ctx.author.id != ctx.guild.owner_id:
        return await ctx.send(embed=mod_embed("❌ Yetkisiz", "Bu komutu sadece **sunucu sahibi** kullanabilir.", discord.Color.red()))

    kategoriler = sorted(
        [k for k in ctx.guild.channels if isinstance(k, discord.CategoryChannel)],
        key=lambda k: k.position
    )
    kanallar = sorted(
        [k for k in ctx.guild.channels if not isinstance(k, discord.CategoryChannel)],
        key=lambda k: k.position
    )

    if not kategoriler and not kanallar:
        return await ctx.send(embed=mod_embed("❌ Hata", "Sunucuda silinecek kanal bulunamadı.", discord.Color.orange()))

    toplam_sayfa = max(1, (len(kanallar) + 24) // 25)
    satirlar = []
    if kategoriler:
        satirlar.append(f"📁 **{len(kategoriler)} kategori** (üst menü)")
    if kanallar:
        satirlar.append(f"💬🔊 **{len(kanallar)} kanal** · Sayfa 1/{toplam_sayfa} (alt menü)")

    view = KanalSilView(kategoriler, kanallar, ctx.author.id)
    await ctx.send(embed=mod_embed("🗑️ Kanal Sil", "\n".join(satirlar), discord.Color.orange()), view=view)


# ── KANAL GERİ YÜKLE ──────────────────────────────────────────────────────────

class KanalIyikleSelect(discord.ui.Select):
    def __init__(self, snapshots: list, sahip_id: int, offset: int = 0):
        self.sahip_id = sahip_id
        self.snapshots = snapshots
        self.offset = offset
        TUR_EMOJI = {"text": "💬", "voice": "🔊", "category": "📁", "stage_voice": "🎙️"}
        options = []
        for i, s in enumerate(snapshots[:25]):
            emoji = TUR_EMOJI.get(s["type"], "📌")
            options.append(discord.SelectOption(
                label=s["name"][:100],
                value=str(offset + i),
                emoji=emoji,
                description=f"{s.get('deleted_at', '?')} · {s.get('deleted_by', '?')[:40]}"
            ))
        super().__init__(placeholder="♻️ Geri yüklenecek kanalı seç...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.sahip_id:
            return await interaction.response.send_message("Bu menüyü sadece sunucu sahibi kullanabilir.", ephemeral=True)
        snapshot = self.snapshots[int(self.values[0]) - self.offset]
        await interaction.response.edit_message(
            embed=mod_embed("⏳ Yükleniyor...", f"**#{snapshot['name']}** kanalı yeniden oluşturuluyor...", discord.Color.blurple()),
            view=None
        )
        try:
            kanal = await restore_kanal(interaction.guild, snapshot)
            mention = kanal.mention if hasattr(kanal, "mention") else f"**#{kanal.name}**"
            await interaction.edit_original_response(
                embed=mod_embed("✅ Kanal Geri Yüklendi", f"{mention} kanalı başarıyla geri yüklendi!\n**İsim:** #{snapshot['name']}\n**Tür:** {snapshot['type']}", discord.Color.green())
            )
        except Exception as e:
            await interaction.edit_original_response(
                embed=mod_embed("❌ Hata", f"Kanal oluşturulamadı:\n`{e}`", discord.Color.red())
            )


class KanalIyikleView(discord.ui.View):
    def __init__(self, snapshots: list, sahip_id: int, sayfa: int = 0):
        super().__init__(timeout=120)
        self.snapshots = snapshots
        self.sahip_id = sahip_id
        self.sayfa = sayfa
        self._build()

    def _build(self):
        self.clear_items()
        toplam_sayfa = max(1, (len(self.snapshots) + 24) // 25)
        sayfa_snap = self.snapshots[self.sayfa * 25:(self.sayfa + 1) * 25]

        if sayfa_snap:
            self.add_item(KanalIyikleSelect(sayfa_snap, self.sahip_id, offset=self.sayfa * 25))

        if toplam_sayfa > 1:
            onceki = discord.ui.Button(
                label="◀ Önceki", style=discord.ButtonStyle.secondary,
                disabled=(self.sayfa == 0), row=1
            )
            onceki.callback = self._onceki
            self.add_item(onceki)

            sayac = discord.ui.Button(
                label=f"Sayfa {self.sayfa + 1} / {toplam_sayfa}",
                style=discord.ButtonStyle.primary, disabled=True, row=1
            )
            self.add_item(sayac)

            sonraki = discord.ui.Button(
                label="Sonraki ▶", style=discord.ButtonStyle.secondary,
                disabled=(self.sayfa >= toplam_sayfa - 1), row=1
            )
            sonraki.callback = self._sonraki
            self.add_item(sonraki)

    async def _onceki(self, interaction: discord.Interaction):
        if interaction.user.id != self.sahip_id:
            return await interaction.response.send_message("Sadece sunucu sahibi kullanabilir.", ephemeral=True)
        self.sayfa -= 1
        self._build()
        await interaction.response.edit_message(view=self)

    async def _sonraki(self, interaction: discord.Interaction):
        if interaction.user.id != self.sahip_id:
            return await interaction.response.send_message("Sadece sunucu sahibi kullanabilir.", ephemeral=True)
        self.sayfa += 1
        self._build()
        await interaction.response.edit_message(view=self)


@bot.command(name="kanalgeri", aliases=["kgeri", "kanaliyikle"])
async def kanaliyikle(ctx):
    """Son silinen kanalları listeler ve seçileni geri yükler. Sadece sunucu sahibi kullanabilir."""
    if ctx.author.id != ctx.guild.owner_id:
        return await ctx.send(embed=mod_embed("❌ Yetkisiz", "Bu komutu sadece **sunucu sahibi** kullanabilir.", discord.Color.red()))

    snapshots = load_deleted_channels().get(str(ctx.guild.id), [])
    if not snapshots:
        return await ctx.send(embed=mod_embed("📦 Geri Yükle", "Henüz silinmiş kanal kaydı yok.\n`.kanalsil` ile silinen kanallar buraya kaydedilir.", discord.Color.orange()))

    toplam_sayfa = max(1, (len(snapshots) + 24) // 25)
    view = KanalIyikleView(snapshots, ctx.author.id)
    await ctx.send(embed=mod_embed(
        "♻️ Kanal Geri Yükle",
        f"**{len(snapshots)}** silinen kanal kaydı · Sayfa 1/{toplam_sayfa}\nGeri yüklemek istediğin kanalı seç:",
        discord.Color.blurple()
    ), view=view)


# ── SES KANALI ────────────────────────────────────────────────────────────────

@bot.command(name="seskat", aliases=["skat", "join"])
@commands.has_permissions(administrator=True)
async def seskat(ctx, kanal: discord.VoiceChannel = None):
    if ctx.voice_client:
        return await ctx.send(embed=mod_embed("⚠️ Zaten Bağlı", f"Bot zaten {ctx.voice_client.channel.mention} kanalında.", discord.Color.orange()))

    hedef = kanal or (ctx.author.voice.channel if ctx.author.voice else None)
    if not hedef:
        return await ctx.send(embed=mod_embed("❌ Hata", "Bir ses kanalında olman gerekiyor ya da kanal belirtmelisin.\n**Örnek:** `.seskat` veya `.seskat Genel`", discord.Color.orange()))

    await hedef.connect()
    await ctx.send(embed=mod_embed("🔊 Ses Kanalına Girildi", f"**{hedef.name}** kanalına bağlandım.", discord.Color.green()))
    await send_log(ctx.guild, log_embed("🔊 Bot Ses Kanalına Girdi", f"**Kanal:** {hedef.name}\n**Yönlendiren:** {ctx.author.mention}", discord.Color.green()), "genel", actor=ctx.author)


@bot.command(name="sesayr", aliases=["sayr", "leave", "dc"])
@commands.has_permissions(administrator=True)
async def sesayr(ctx):
    if not ctx.voice_client:
        return await ctx.send(embed=mod_embed("❌ Hata", "Bot şu an hiçbir ses kanalında değil.", discord.Color.orange()))

    kanal_adi = ctx.voice_client.channel.name
    await ctx.voice_client.disconnect()
    await ctx.send(embed=mod_embed("🔇 Ses Kanalından Ayrıldı", f"**{kanal_adi}** kanalından ayrıldım.", discord.Color.orange()))
    await send_log(ctx.guild, log_embed("🔇 Bot Ses Kanalından Ayrıldı", f"**Kanal:** {kanal_adi}\n**Yönlendiren:** {ctx.author.mention}", discord.Color.orange()), "genel", actor=ctx.author)


@bot.command(name="sestasi", aliases=["stasi", "move"])
@commands.has_permissions(administrator=True)
async def sestasi(ctx, kanal: discord.VoiceChannel):
    if not ctx.voice_client:
        return await ctx.send(embed=mod_embed("❌ Hata", "Bot şu an hiçbir ses kanalında değil. Önce `.seskat` kullan.", discord.Color.orange()))

    eski = ctx.voice_client.channel.name
    await ctx.voice_client.move_to(kanal)
    await ctx.send(embed=mod_embed("🔀 Kanal Değiştirildi", f"**{eski}** → **{kanal.name}** kanalına geçtim.", discord.Color.blurple()))


# ── KAYIT SİSTEMİ ─────────────────────────────────────────────────────────────

KAYIT_REHBER_ROLLER = [
    "kayıt sorumlusu", "kayıt denetleyicisi", "kayıt lideri",
    "register sorumlusu", "register denetleyicisi", "register lider", "register lideri",
    "yönetim", "yönetici", "yönetici kurulu",
]
KAYIT_KANAL_ADI = "kayıt-bilgi"


@bot.command(name="kabak")
@commands.has_permissions(administrator=True)
async def kabak_kur(ctx):
    """Kayıt rehberi kanalı oluşturur ve rehberi gönderir: .kabak"""
    guild = ctx.guild

    # İzin verilecek rolleri bul
    izinli_roller = [
        r for r in guild.roles
        if r.name.lower() in KAYIT_REHBER_ROLLER
    ]

    # Kanal izinleri: @everyone göremez, izinli roller görebilir/yazabilir
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True),
    }
    for rol in izinli_roller:
        overwrites[rol] = discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        )

    # Kanal zaten var mı?
    mevcut = discord.utils.get(guild.text_channels, name=KAYIT_KANAL_ADI)
    if not mevcut:
        mevcut = discord.utils.find(
            lambda c: "kayıt-bilgi" in c.name.lower(), guild.text_channels
        )

    if mevcut:
        kanal = mevcut
        await kanal.edit(overwrites=overwrites, reason=".kabak güncellendi")
    else:
        # WONKRU LOG kategorisinden önce oluştur, ya da en başa
        kategori = discord.utils.find(lambda c: "kayıt" in c.name.lower(), guild.categories)
        kanal = await guild.create_text_channel(
            name=KAYIT_KANAL_ADI,
            overwrites=overwrites,
            category=kategori,
            topic="Kayıt sorumluları için kayıt rehberi.",
            reason=".kabak komutu ile oluşturuldu",
        )

    # Rehber embed'i
    embed = discord.Embed(
        title="✅  Kayıt Nasıl Yapılır?",
        color=discord.Color.green(),
    )
    embed.add_field(
        name="1️⃣  Yeni Gelen Üyeyi Karşıla",
        value=(
            "> \"Hoş geldin, nasılsın?\" gibi hal-hatır sorarak kısa bir sohbet et."
        ),
        inline=False,
    )
    embed.add_field(
        name="2️⃣  Yetkili Olma Hakkında Bilgilendir",
        value=(
            "> \"Yetkili Olmak İster misin?\" diye sor ve ayrıcalıkları anlat:\n\n"
            "• Tag alırsan **renk rollerine** sahip olabilirsin.\n"
            "  *(Chat'te rengin diğer üyelerden farklı olur.)*\n"
            "• **Valinor** rolüne direkt sahip olursun."
        ),
        inline=False,
    )
    embed.add_field(
        name="3️⃣  Tag Durumuna Göre İşlem",
        value=(
            "✅ **Tag aldıysa:**\n> `.taglı <@id>`\n\n"
            "❌ **Tag almak istemezse:**\n> Herhangi bir işlem yapmana gerek yok."
        ),
        inline=False,
    )
    embed.add_field(
        name="4️⃣  İsim / Yaş Alıp Kayıt Et",
        value=(
            "♂️ **Erkek ise:**\n> `.e <@id> isim yaş`\n\n"
            "♀️ **Kız ise:**\n> `.k <@id> isim yaş`"
        ),
        inline=False,
    )
    embed.add_field(
        name="─────────────────────────",
        value=(
            "❗ **Sunucuda kayıtlar bu şekilde yapılmalıdır.**\n"
            "Bu adımları söylemek **zorundasınız**. "
            "Söylemediğiniz tespit edilirse <@&868326037510058024> yetkiniz çekilir."
        ),
        inline=False,
    )
    embed.set_footer(text="Wonkru Kayıt Sistemi")

    await kanal.send(embed=embed)
    await ctx.send(embed=mod_embed(
        "✅ Kabak Oluşturuldu",
        f"Kayıt rehberi kanalı {kanal.mention} olarak ayarlandı ve rehber gönderildi.",
        discord.Color.green()
    ))


@kabak_kur.error
async def kabak_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=mod_embed("❌ Yetki Gerekli", "Bu komutu sadece **Yöneticiler** kullanabilir.", discord.Color.red()))


async def _kayit_yap(ctx, uye: discord.Member, isim: str, yas: str, cinsiyet: str):
    """Ortak kayıt işlemi. cinsiyet: 'erkek' veya 'kız'"""
    if cinsiyet == "erkek":
        rol_adi = "helios"
        renk = discord.Color.blue()
        emoji = "♂️"
    else:
        rol_adi = "luna"
        renk = discord.Color.from_rgb(255, 105, 180)
        emoji = "♀️"

    hedef_rol = discord.utils.find(lambda r: r.name.lower() == rol_adi, ctx.guild.roles)
    kayitsiz_rol = discord.utils.find(lambda r: r.name.lower() == "unregister", ctx.guild.roles)

    if not hedef_rol:
        return await ctx.send(embed=mod_embed("❌ Hata", f"`{rol_adi.capitalize()}` rolü sunucuda bulunamadı.", discord.Color.red()))

    nick = f"𖣂 {isim} | {yas}"
    hatalar = []

    try:
        await uye.edit(nick=nick, reason=f"Kayıt: {ctx.author}")
    except discord.Forbidden:
        hatalar.append("Nickname değiştirilemedi (yetki yetersiz)")

    try:
        await uye.add_roles(hedef_rol, reason=f"Kayıt: {ctx.author}")
    except discord.Forbidden:
        hatalar.append(f"`{hedef_rol.name}` rolü verilemedi")

    if kayitsiz_rol and kayitsiz_rol in uye.roles:
        try:
            await uye.remove_roles(kayitsiz_rol, reason="Kayıt tamamlandı")
        except discord.Forbidden:
            hatalar.append("`unregister` rolü alınamadı")

    # WONKRU PUBLIC kategorisindeki rastgele bir sese taşı
    ses_kanal_adi = None
    public_kat = discord.utils.find(
        lambda c: "wonkru public" in c.name.lower(),
        ctx.guild.categories
    )
    if public_kat:
        ses_kanallar = [c for c in public_kat.channels if isinstance(c, discord.VoiceChannel)]
        if ses_kanallar:
            hedef_ses = random.choice(ses_kanallar)
            try:
                await uye.move_to(hedef_ses, reason="Kayıt sonrası otomatik ses kanalı")
                ses_kanal_adi = hedef_ses.name
            except discord.HTTPException:
                pass  # Üye ses kanalında değilse taşıma başarısız olur, sessizce geç

    ses_satiri = f"\n🔊 **Ses:** {ses_kanal_adi}" if ses_kanal_adi else ""
    hata_satiri = f"\n⚠️ {' · '.join(hatalar)}" if hatalar else ""
    await ctx.send(embed=mod_embed(
        f"{emoji} Kayıt Tamamlandı",
        f"**Üye:** {uye.mention}\n**İsim:** {isim}\n**Yaş:** {yas}\n**Rol:** {hedef_rol.mention}{ses_satiri}{hata_satiri}",
        renk
    ))

    await send_log(ctx.guild, log_embed(
        f"{emoji} Kayıt",
        f"**Üye:** {uye.mention} (`{uye}`)\n**İsim:** {isim}\n**Yaş:** {yas}\n**Cinsiyet:** {cinsiyet.capitalize()}\n**Kaydeden:** {ctx.author.mention}",
        renk,
        user=uye
    ), "genel", actor=ctx.author)

    # Kaydeden kişinin yetkili alım sayacını artır + 50 puan bonus
    try:
        pdata, pud = get_user_puan(ctx.guild.id, ctx.author.id)
        pud["yetkili_alim"] = pud.get("yetkili_alim", 0) + 1
        pud["puan"] = pud.get("puan", 0) + 50
        pud["toplam_kazanilan"] = pud.get("toplam_kazanilan", 0) + 50
        save_puan(pdata)
    except Exception:
        pass

    # wonkru-chat kanalına hoşgeldin mesajı gönder (3 sn sonra silinir)
    try:
        chat_kanal = discord.utils.find(
            lambda c: isinstance(c, discord.TextChannel) and "wonkru-chat" in c.name.lower(),
            ctx.guild.channels
        )
        if chat_kanal:
            cinsiyet_emoji = "♂️" if cinsiyet == "erkek" else "♀️"
            hosgeldin_embed = discord.Embed(
                title=f"✨ Hoşgeldin, {isim}!",
                description=(
                    f"{uye.mention} sunucumuza katıldı! 🎉\n\n"
                    f"{cinsiyet_emoji} **İsim:** {isim}\n"
                    f"🎂 **Yaş:** {yas}\n"
                    f"🏷️ **Rol:** {hedef_rol.mention}"
                ),
                color=renk
            )
            hosgeldin_embed.set_thumbnail(url=uye.display_avatar.url)
            hosgeldin_embed.set_footer(text="WONKRU • Hoş geldin!")
            hosgeldin_embed.timestamp = datetime.utcnow()
            hosgeldin_msg = await chat_kanal.send(embed=hosgeldin_embed)
            await asyncio.sleep(3)
            await hosgeldin_msg.delete()
    except Exception:
        pass


@bot.command(name="e", aliases=["erkek"])
@commands.has_permissions(manage_roles=True)
async def kayit_erkek(ctx, uye: discord.Member, isim: str, yas: str):
    """Erkek kaydı: .e @üye isim yaş"""
    await _kayit_yap(ctx, uye, isim, yas, "erkek")


@bot.command(name="k", aliases=["kiz", "kız"])
@commands.has_permissions(manage_roles=True)
async def kayit_kiz(ctx, uye: discord.Member, isim: str, yas: str):
    """Kız kaydı: .k @üye isim yaş"""
    await _kayit_yap(ctx, uye, isim, yas, "kız")


@bot.command(name="kayıtsız", aliases=["kayitsiz", "unregister"])
@commands.has_permissions(manage_roles=True)
async def kayitsiz_yap(ctx, uye: discord.Member):
    """Üyeyi kayıtsıza atar: .kayıtsız @üye"""
    kayitsiz_rol = discord.utils.find(lambda r: r.name.lower() == "unregister", ctx.guild.roles)
    helios_rol = discord.utils.find(lambda r: r.name.lower() == "helios", ctx.guild.roles)
    luna_rol = discord.utils.find(lambda r: r.name.lower() == "luna", ctx.guild.roles)

    hatalar = []

    # Helios ve Luna rollerini al
    alinacak = [r for r in [helios_rol, luna_rol] if r and r in uye.roles]
    if alinacak:
        try:
            await uye.remove_roles(*alinacak, reason=f"Kayıtsıza alındı: {ctx.author}")
        except discord.Forbidden:
            hatalar.append("Roller alınamadı")

    # Unregister rolü ver
    if kayitsiz_rol:
        try:
            await uye.add_roles(kayitsiz_rol, reason=f"Kayıtsıza alındı: {ctx.author}")
        except discord.Forbidden:
            hatalar.append("`unregister` rolü verilemedi")

    # Nickname sıfırla
    try:
        await uye.edit(nick=None, reason=f"Kayıtsıza alındı: {ctx.author}")
    except discord.Forbidden:
        hatalar.append("Nickname sıfırlanamadı")

    hata_satiri = f"\n⚠️ {' · '.join(hatalar)}" if hatalar else ""
    await ctx.send(embed=mod_embed(
        "🔄 Kayıtsıza Alındı",
        f"**Üye:** {uye.mention}\n**İşlemi Yapan:** {ctx.author.mention}{hata_satiri}",
        discord.Color.orange()
    ))

    await send_log(ctx.guild, log_embed(
        "🔄 Kayıtsıza Alındı",
        f"**Üye:** {uye.mention} (`{uye}`)\n**İşlemi Yapan:** {ctx.author.mention}",
        discord.Color.orange(),
        user=uye
    ), "genel", actor=ctx.author)


@kayitsiz_yap.error
async def kayitsiz_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=mod_embed("❌ Eksik Bilgi", "**Kullanım:** `.kayıtsız @üye`", discord.Color.orange()))
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(embed=mod_embed("❌ Üye Bulunamadı", "Geçerli bir kullanıcı etiketle.", discord.Color.red()))
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=mod_embed("❌ Yetkisiz", "Bu komutu kullanmak için **Rolleri Yönet** yetkisi gerekir.", discord.Color.red()))


@bot.command(name="booster", aliases=["b", "boost", "boosterisim", "boosterismi"])
@commands.has_permissions(manage_nicknames=True)
async def booster_isim(ctx, uye: discord.Member, *, yeni_isim: str):
    """Boost yapmış üyenin ismini özgürce değiştirir: .booster @üye yeni isim"""

    if not uye.premium_since:
        return await ctx.send(embed=mod_embed(
            "❌ Booster Değil",
            f"{uye.mention} sunucuyu boost yapmamış.",
            discord.Color.red()
        ))

    if len(yeni_isim) > 32:
        return await ctx.send(embed=mod_embed(
            "❌ İsim Çok Uzun",
            f"Nick en fazla **32** karakter olabilir. (Şu an: {len(yeni_isim)})",
            discord.Color.orange()
        ))

    try:
        await uye.edit(nick=yeni_isim, reason=f"Booster isim: {ctx.author}")
    except discord.Forbidden:
        return await ctx.send(embed=mod_embed("❌ Yetki Hatası", "Bu üyenin nickini değiştirme yetkim yok.", discord.Color.red()))

    try:
        await uye.send(embed=mod_embed(
            "💎 İsminiz Güncellendi",
            f"**Sunucu:** {ctx.guild.name}\n**Yeni İsim:** {yeni_isim}\n**Yapan:** {ctx.author}",
            discord.Color.purple()
        ))
    except discord.Forbidden:
        pass

    await ctx.send(embed=mod_embed(
        "💎 Booster İsmi Değiştirildi",
        f"**Üye:** {uye.mention}\n**Yeni İsim:** `{yeni_isim}`\n**Yapan:** {ctx.author.mention}",
        discord.Color.purple()
    ))
    await send_log(ctx.guild, log_embed(
        "💎 Booster İsim Değişikliği",
        f"**Üye:** {uye.mention} (`{uye.id}`)\n**Yeni İsim:** `{yeni_isim}`\n**Yapan:** {ctx.author.mention}",
        discord.Color.purple(), user=uye
    ), "genel", actor=ctx.author)


@booster_isim.error
async def booster_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=mod_embed(
            "❌ Eksik Bilgi",
            "**Kullanım:** `.booster @üye yeni isim`\n**Örnek:** `.booster @Bion Bion buba`",
            discord.Color.orange()
        ))
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(embed=mod_embed("❌ Üye Bulunamadı", "Geçerli bir kullanıcı etiketle.", discord.Color.red()))
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=mod_embed("❌ Yetkisiz", "Bu komut için **Nicknames Yönet** yetkisi gerekir.", discord.Color.red()))


@kayit_erkek.error
@kayit_kiz.error
async def kayit_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=mod_embed(
            "❌ Eksik Bilgi",
            "**Kullanım:**\n`.e @üye isim yaş`\n`.k @üye isim yaş`\n\n**Örnek:** `.e @Ahmet Ahmet 18`",
            discord.Color.orange()
        ))
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(embed=mod_embed("❌ Üye Bulunamadı", "Geçerli bir kullanıcı etiketle.", discord.Color.red()))
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=mod_embed("❌ Yetkisiz", "Bu komutu kullanmak için **Rolleri Yönet** yetkisi gerekir.", discord.Color.red()))


# ── CEZA SİSTEMİ ───────────────────────────────────────────────────────────────

def load_ceza():
    if os.path.exists(CEZA_FILE):
        with open(CEZA_FILE, "r") as f:
            return json.load(f)
    return {}

def save_ceza(data):
    with open(CEZA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# Ceza sebepleri — (label, sure_label, dakika)
CEZA_SEBEPLER = [
    ("Sunucu kötüleme / Mikrofon buğu / Hakaretli nick",         "3 Saat",  180),
    ("Ses kanalına kasıtlı gir-çık (3'ten fazla)",               "3 Saat",  180),
    ("Muteliyken kamera/yayınla hakaret içerikli görüntü",       "3 Saat",  180),
    ("Sorun kanalında abartı küfür/hakaret",                     "6 Saat",  360),
    ("Muteliyken public'te küfürlü yayın/kamera açma",           "6 Saat",  360),
    ("Birisini kanalda takip edip sürekli kışkırtma/küfür",      "6 Saat",  360),
    ("Düzeni bozma, kaos çıkarma (Sadece Yönetici)",             "3 Gün",   4320),
    ("Boostu kötüye kullanma",                                   "3 Gün",   4320),
    ("Dini/milli değerlere kasıtlı küfür",                       "3 Gün",   4320),
    ("Şiddet içerikli ciddi tehdit söylemi",                     "3 Gün",   4320),
]


class CezaSebebSec(discord.ui.Select):
    def __init__(self, uye: discord.Member, moderator: discord.Member):
        self.uye = uye
        self.moderator = moderator
        options = [
            discord.SelectOption(
                label=label[:100],
                value=str(i),
                description=f"⏱️ {sure_label} Karantina"
            )
            for i, (label, sure_label, _) in enumerate(CEZA_SEBEPLER)
        ]
        super().__init__(placeholder="📋 Ceza sebebini seçin...", options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.moderator:
            return await interaction.response.send_message(
                "Bu menüyü sadece komutu kullanan moderatör kullanabilir.", ephemeral=True
            )
        idx = int(self.values[0])
        sebep, sure_label, dakika = CEZA_SEBEPLER[idx]

        # Eski rolleri kaydet
        korunan_ids = {interaction.guild.default_role.id}
        eski_roller = [r.id for r in self.uye.roles if r.id not in korunan_ids and not r.managed]

        data = load_ceza()
        g, u = str(interaction.guild.id), str(self.uye.id)
        if g not in data:
            data[g] = {}
        data[g][u] = {
            "sebep":       sebep,
            "ceza_tarihi": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            "cezalayan":   str(self.moderator),
            "eski_roller": eski_roller,
            "sure_dakika": dakika,
        }
        save_ceza(data)

        await _ceza_uygula(self.uye, reason=f"Ceza: {sebep} | {self.moderator}")

        # Discord timeout da uygula (süre sonunda otomatik kalkar)
        try:
            until = discord.utils.utcnow() + timedelta(minutes=dakika)
            await self.uye.timeout(until, reason=f"{sebep} | {self.moderator}")
        except discord.Forbidden:
            pass

        try:
            await self.uye.send(embed=mod_embed(
                "🔒 Karantinaya Alındınız",
                f"**Sunucu:** {interaction.guild.name}\n**Süre:** {sure_label}\n**Sebep:** {sebep}\n**Cezalayan:** {self.moderator}",
                discord.Color.red()
            ))
        except discord.Forbidden:
            pass

        result_embed = mod_embed(
            "🔒 Ceza Uygulandı",
            f"**Üye:** {self.uye.mention}\n**Sebep:** {sebep}\n**Süre:** {sure_label}\n**Cezalayan:** {self.moderator.mention}",
            discord.Color.red()
        )
        await send_log(interaction.guild, log_embed(
            "🔒 Ceza",
            f"**Üye:** {self.uye.mention} (`{self.uye}`)\n**Sebep:** {sebep}\n**Süre:** {sure_label}\n**Cezalayan:** {self.moderator.mention}",
            discord.Color.red(), user=self.uye
        ), "genel", actor=self.moderator)

        await interaction.response.edit_message(embed=result_embed, view=None)


class CezaSebebView(discord.ui.View):
    def __init__(self, uye, moderator):
        super().__init__(timeout=60)
        self.add_item(CezaSebebSec(uye, moderator))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


async def _ceza_uygula(member: discord.Member, reason: str = "Ceza uygulandı"):
    """Karantina rolü ver, tüm rolleri al, nickname'e | Cezalı ekle."""
    karantina_rol = discord.utils.find(
        lambda r: r.name.lower() == "karantina", member.guild.roles
    )
    unregister_rol = discord.utils.find(
        lambda r: r.name.lower() == "unregister", member.guild.roles
    )

    # Korunacak roller (bot rolleri + @everyone + karantina)
    korunan_ids = {member.guild.default_role.id}
    if karantina_rol:
        korunan_ids.add(karantina_rol.id)

    alinacak = [r for r in member.roles if r.id not in korunan_ids and not r.managed]
    if alinacak:
        try:
            await member.remove_roles(*alinacak, reason=reason)
        except discord.Forbidden:
            pass

    # Unregister varsa onu da al
    if unregister_rol and unregister_rol in member.roles:
        try:
            await member.remove_roles(unregister_rol, reason=reason)
        except discord.Forbidden:
            pass

    # Karantina rolü ver
    if karantina_rol:
        try:
            await member.add_roles(karantina_rol, reason=reason)
        except discord.Forbidden:
            pass

    # Nickname güncelle
    mevcut_nick = member.display_name
    if "| Cezalı" not in mevcut_nick:
        yeni_nick = f"{mevcut_nick} | Cezalı"[:32]
        try:
            await member.edit(nick=yeni_nick, reason=reason)
        except discord.Forbidden:
            pass


@bot.command(name="cezalı", aliases=["cezali", "ceza"])
@commands.has_permissions(manage_roles=True)
async def cezali_yap(ctx, uye: discord.Member, *, sebep: str = ""):
    """Üyeyi karantinaya alır: .cezalı @üye [sebep]"""
    if uye.id == ctx.guild.owner_id:
        return await ctx.send(embed=mod_embed("❌ İşlem Yapılamaz", "Sunucu sahibine ceza verilemez.", discord.Color.red()))
    if uye.top_role >= ctx.author.top_role:
        return await ctx.send(embed=mod_embed("❌ Yetersiz Yetki", "Kendi rolünden yüksek/eşit birine ceza veremezsin.", discord.Color.red()))

    # Sebep girilmediyse menü göster
    if not sebep:
        secim_embed = mod_embed(
            "🔒 Ceza — Sebep Seçin",
            f"**Üye:** {uye.mention}\n\nAşağıdan ceza sebebini seçin. Süre otomatik uygulanır.",
            discord.Color.red()
        )
        return await ctx.send(embed=secim_embed, view=CezaSebebView(uye, ctx.author))

    # Sebep verilmişse direkt uygula
    korunan_ids = {ctx.guild.default_role.id}
    eski_roller = [r.id for r in uye.roles if r.id not in korunan_ids and not r.managed]

    data = load_ceza()
    g, u = str(ctx.guild.id), str(uye.id)
    if g not in data:
        data[g] = {}
    data[g][u] = {
        "sebep":       sebep,
        "ceza_tarihi": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "cezalayan":   str(ctx.author),
        "eski_roller": eski_roller,
    }
    save_ceza(data)

    await _ceza_uygula(uye, reason=f"Ceza: {sebep} | {ctx.author}")

    try:
        await uye.send(embed=mod_embed(
            "🔒 Karantinaya Alındınız",
            f"**Sunucu:** {ctx.guild.name}\n**Sebep:** {sebep}\n**Cezalayan:** {ctx.author}",
            discord.Color.red()
        ))
    except discord.Forbidden:
        pass

    await ctx.send(embed=mod_embed(
        "🔒 Ceza Uygulandı",
        f"**Üye:** {uye.mention}\n**Sebep:** {sebep}\n**Cezalayan:** {ctx.author.mention}",
        discord.Color.red()
    ))
    await send_log(ctx.guild, log_embed(
        "🔒 Ceza",
        f"**Üye:** {uye.mention} (`{uye}`)\n**Sebep:** {sebep}\n**Cezalayan:** {ctx.author.mention}",
        discord.Color.red(), user=uye
    ), "genel", actor=ctx.author)
    audit_log_yaz(ctx.guild.id, uye.id, "karantina", str(ctx.author), sebep)


@bot.command(name="cezakaldır", aliases=["cezakaldir", "cezasız", "cezasiz"])
@commands.has_permissions(manage_roles=True)
async def ceza_kaldir(ctx, uye: discord.Member):
    """Cezayı kaldırır ve eski rolleri geri verir: .cezakaldır @üye"""
    data = load_ceza()
    g, u = str(ctx.guild.id), str(uye.id)

    if g not in data or u not in data[g]:
        return await ctx.send(embed=mod_embed("❌ Kayıt Yok", f"{uye.mention} için aktif ceza kaydı bulunamadı.", discord.Color.orange()))

    kayit = data[g][u]
    eski_roller_ids = kayit.get("eski_roller", [])

    # Karantina rolünü al
    karantina_rol = discord.utils.find(lambda r: r.name.lower() == "karantina", ctx.guild.roles)
    if karantina_rol and karantina_rol in uye.roles:
        try:
            await uye.remove_roles(karantina_rol, reason=f"Ceza kaldırıldı: {ctx.author}")
        except discord.Forbidden:
            pass

    # Eski rolleri geri ver
    geri_roller = []
    for rid in eski_roller_ids:
        rol = ctx.guild.get_role(rid)
        if rol and not rol.managed:
            geri_roller.append(rol)
    if geri_roller:
        try:
            await uye.add_roles(*geri_roller, reason=f"Ceza kaldırıldı: {ctx.author}")
        except discord.Forbidden:
            pass

    # Nickname'den | Cezalı kaldır
    if "| Cezalı" in uye.display_name:
        temiz_nick = uye.display_name.replace(" | Cezalı", "").strip()
        try:
            await uye.edit(nick=temiz_nick or None, reason="Ceza kaldırıldı")
        except discord.Forbidden:
            pass

    del data[g][u]
    save_ceza(data)

    await ctx.send(embed=mod_embed(
        "🔓 Ceza Kaldırıldı",
        f"**Üye:** {uye.mention}\n**Eski roller geri verildi:** {len(geri_roller)} rol\n**Kaldıran:** {ctx.author.mention}",
        discord.Color.green()
    ))
    await send_log(ctx.guild, log_embed(
        "🔓 Ceza Kaldırıldı",
        f"**Üye:** {uye.mention} (`{uye}`)\n**Kaldıran:** {ctx.author.mention}",
        discord.Color.green(), user=uye
    ), "genel", actor=ctx.author)
    audit_log_yaz(ctx.guild.id, uye.id, "ceza_kaldir", str(ctx.author))


@cezali_yap.error
@ceza_kaldir.error
async def ceza_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=mod_embed("❌ Eksik Bilgi", "**Kullanım:**\n`.cezalı @üye sebep`\n`.cezakaldır @üye`", discord.Color.orange()))
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(embed=mod_embed("❌ Üye Bulunamadı", "Geçerli bir kullanıcı etiketle.", discord.Color.red()))
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=mod_embed("❌ Yetkisiz", "Bu komutu kullanmak için **Rolleri Yönet** yetkisi gerekir.", discord.Color.red()))


# ── OTOMATİK SES KANALI (AFK) ──────────────────────────────────────────────────

async def afk_ses_baglan(guild: discord.Guild):
    """Sunucudaki ilk public ses kanalına (Secret olmayan) otomatik bağlanır."""
    if guild.voice_client:
        return
    hedef = discord.utils.find(
        lambda c: isinstance(c, discord.VoiceChannel) and "secret" not in c.name.lower(),
        guild.voice_channels
    )
    if hedef:
        try:
            vc = await hedef.connect()
            await guild.change_voice_state(channel=hedef, self_deaf=True, self_mute=True)
            print(f"🔊 Ses kanalına bağlandı: {hedef.name}")
        except Exception as e:
            print(f"❌ Ses kanalına bağlanılamadı: {e}")


# ── STAT SİSTEMİ ───────────────────────────────────────────────────────────────

def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_stats(data):
    with open(STATS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user_stats(guild_id, user_id):
    data = load_stats()
    g, u = str(guild_id), str(user_id)
    if g not in data:
        data[g] = {}
    if u not in data[g]:
        data[g][u] = {
            "messages": {}, "voice": {}, "voice_join": {},
            "camera": 0, "camera_join": None,
            "stream": 0, "stream_join": None,
        }
    ud = data[g][u]
    for k in ("camera", "stream"):
        ud.setdefault(k, 0)
    for k in ("camera_join", "stream_join"):
        ud.setdefault(k, None)
    return data, ud

def sure_format(sn: float) -> str:
    sn = int(sn)
    if sn <= 0:
        return "0 sn"
    sa, kalan = divmod(sn, 3600)
    dk, sn2 = divmod(kalan, 60)
    if sa:
        return f"{sa} sa {dk} dk"
    if dk:
        return f"{dk} dk {sn2} sn"
    return f"{sn2} sn"

def kat_grupla(guild: discord.Guild, voice_data: dict) -> dict:
    """Ses sürelerini kategori adına göre gruplar."""
    gruplar: dict[str, float] = {}
    for ch_id, sn in voice_data.items():
        kanal = guild.get_channel(int(ch_id))
        if kanal and kanal.category:
            kat_adi = kanal.category.name
        elif kanal:
            kat_adi = "Kategorisiz"
        else:
            kat_adi = "Silinmiş Kanal"
        gruplar[kat_adi] = gruplar.get(kat_adi, 0) + sn
    return gruplar


_islenen_mesajlar: set[int] = set()
_nick_isleniyor: set[int] = set()  # sonsuz döngü önlemi

@bot.event
async def on_message(message: discord.Message):
    global _islenen_mesajlar
    if message.id in _islenen_mesajlar:
        return
    _islenen_mesajlar.add(message.id)
    if len(_islenen_mesajlar) > 2000:
        _islenen_mesajlar = set(list(_islenen_mesajlar)[-1000:])
    if message.author.bot or not message.guild:
        await bot.process_commands(message)
        return

    # ── Link filtresi ──────────────────────────────────────────────────────
    lf = get_link_filtre(message.guild.id)
    if lf.get("aktif") and _LINK_PATTERN.search(message.content):
        member = message.author
        # Yöneticiler ve muaf roller geçer
        izinli = (
            member.guild_permissions.manage_messages
            or any(r.id in lf.get("muaf_roller", []) for r in member.roles)
            or message.channel.id in lf.get("muaf_kanallar", [])
        )
        if not izinli:
            try:
                await message.delete()
            except discord.NotFound:
                pass
            uyari = await message.channel.send(embed=discord.Embed(
                description=f"🔗 {member.mention} bu kanalda link paylaşamazsın!",
                color=discord.Color.red()
            ))
            await asyncio.sleep(5)
            try:
                await uyari.delete()
            except discord.NotFound:
                pass
            await send_log(message.guild, log_embed(
                "🔗 Link Engellendi",
                f"**Üye:** {member.mention} (`{member}`)\n**Kanal:** {message.channel.mention}\n**Mesaj:** {message.content[:200]}",
                discord.Color.red(),
                user=member
            ), "genel")
            return
    # ──────────────────────────────────────────────────────────────────────

    data, user_data = get_user_stats(message.guild.id, message.author.id)
    ch_id = str(message.channel.id)
    user_data["messages"][ch_id] = user_data["messages"].get(ch_id, 0) + 1
    save_stats(data)
    await bot.process_commands(message)


# Botun otomatik olarak mute ettiği kullanıcıları takip eder: {(guild_id, member_id)}
_stream_muted: set[tuple[int, int]] = set()


def kanalda_aktif_streamer_var(kanal: discord.VoiceChannel) -> bool:
    """Kanalda Streamer rolüne sahip ve yayını açık biri var mı?"""
    streamer_rol = discord.utils.find(lambda r: r.name == STREAMER_ROL_ADI, kanal.guild.roles)
    for m in kanal.members:
        if m.bot:
            continue
        vs = m.voice
        if vs and vs.self_stream and streamer_rol and streamer_rol in m.roles:
            return True
    return False


def uye_streamer_mi(member: discord.Member) -> bool:
    streamer_rol = discord.utils.find(lambda r: r.name == STREAMER_ROL_ADI, member.guild.roles)
    return streamer_rol in member.roles if streamer_rol else False


async def stream_mute_guncelle(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    """Stream mute mantığını işler."""
    guild = member.guild

    # ── 1. Biri kanala girdi ────────────────────────────────────────────────
    if after.channel and (before.channel != after.channel):
        kanal = after.channel
        if isinstance(kanal, discord.VoiceChannel) and kanalda_aktif_streamer_var(kanal):
            if not uye_streamer_mi(member) and not member.voice.mute:
                try:
                    await member.edit(mute=True, reason="Aktif yayın var — otomatik mute")
                    _stream_muted.add((guild.id, member.id))
                except discord.Forbidden:
                    pass

    # ── 2. Streamer yayını başlattı ─────────────────────────────────────────
    if not before.self_stream and after.self_stream and after.channel and uye_streamer_mi(member):
        kanal = after.channel
        if isinstance(kanal, discord.VoiceChannel):
            for m in kanal.members:
                if m.bot or m == member or uye_streamer_mi(m):
                    continue
                if not m.voice or m.voice.mute:
                    continue
                try:
                    await m.edit(mute=True, reason="Streamer yayını başlattı — otomatik mute")
                    _stream_muted.add((guild.id, m.id))
                except discord.Forbidden:
                    pass

    # ── 3. Streamer yayını kapattı veya kanaldan ayrıldı ───────────────────
    kanal_kontrol = before.channel if (before.self_stream and not after.self_stream) else None
    if before.channel and not after.channel and uye_streamer_mi(member):
        kanal_kontrol = before.channel

    if kanal_kontrol and isinstance(kanal_kontrol, discord.VoiceChannel):
        # Kanalda başka aktif streamer kalmadı mı?
        if not kanalda_aktif_streamer_var(kanal_kontrol):
            for m in list(kanal_kontrol.members):
                if m.bot:
                    continue
                if (guild.id, m.id) in _stream_muted:
                    try:
                        await m.edit(mute=False, reason="Yayın sona erdi — otomatik unmute")
                        _stream_muted.discard((guild.id, m.id))
                    except discord.Forbidden:
                        pass

    # ── 4. Üye kanaldan ayrıldı — takipten çıkar ───────────────────────────
    if not after.channel:
        _stream_muted.discard((guild.id, member.id))


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot:
        return
    now = datetime.utcnow()
    now_str = now.isoformat()
    data, ud = get_user_stats(member.guild.id, member.id)

    def elapsed(ts_str):
        return max(0, (now - datetime.fromisoformat(ts_str)).total_seconds()) if ts_str else 0

    # ── Ses kanalı takibi ──
    if before.channel:
        ch_id = str(before.channel.id)
        sure = elapsed(ud["voice_join"].get(ch_id))
        if sure:
            ud["voice"][ch_id] = ud["voice"].get(ch_id, 0) + sure
            ud["voice_join"][ch_id] = None

    if after.channel:
        ch_id = str(after.channel.id)
        if not ud["voice_join"].get(ch_id):
            ud["voice_join"][ch_id] = now_str

    # ── Kamera takibi ──
    if before.self_video and not after.self_video:
        ud["camera"] += elapsed(ud["camera_join"])
        ud["camera_join"] = None
    elif not before.self_video and after.self_video and after.channel:
        ud["camera_join"] = now_str

    # ── Stream takibi ──
    if before.self_stream and not after.self_stream:
        ud["stream"] += elapsed(ud["stream_join"])
        ud["stream_join"] = None
    elif not before.self_stream and after.self_stream and after.channel:
        ud["stream_join"] = now_str

    # ── Kanaldan ayrılınca kamera/stream'i de kapat ──
    if before.channel and not after.channel:
        if ud["camera_join"]:
            ud["camera"] += elapsed(ud["camera_join"])
            ud["camera_join"] = None
        if ud["stream_join"]:
            ud["stream"] += elapsed(ud["stream_join"])
            ud["stream_join"] = None

    save_stats(data)
    ses_durum_yaz()

    # ── Stream Mute Sistemi ──────────────────────────────────────────────────
    await stream_mute_guncelle(member, before, after)


# Kategori adını Wonkru'ya özel gruba eşler
KAT_GRUPLARI = {
    "WONKRU PUBLIC":         "Public Kanalları",
    "WONKRU PUBLİC":        "Public Kanalları",
    "WONKRU SECRET":         "Özel Kanallar",
    "WONKRU MUSİC":          "Müzik Kanalları",
    "WONKRU MUSIC":          "Müzik Kanalları",
    "✦ STREAMERS ROOM'S":   "Yayın Kanalları",
    "STREAMERS ROOM":        "Yayın Kanalları",
    "SORUN ÇÖZME":           "Sorun Çözme Kanalları",
    "YETKİLİ KANALLARI":    "Yetkili Kanalları",
    "YETKİLİ ALIM":         "Yetkili Alım Kanalları",
    "✦ KARANTİNA ODALARI":  "Ceza Kanalları",
    "KARANTİNA ODALARI":    "Ceza Kanalları",
    "REGISTER TO SERVER":    "Kayıt Kanalları",
    "BİLGİLENDİRME":        "Bilgilendirme Kanalları",
    "WONKRU LOG":            "Log Kanalları",
}

def kanal_grubu(guild: discord.Guild, ch_id: str) -> str:
    kanal = guild.get_channel(int(ch_id))
    if not kanal:
        return "Silinmiş Kanal"
    # Kanal adında PUBG geçiyorsa ayrı göster
    if "pubg" in kanal.name.lower():
        return "PUBG Kanalları"
    if kanal.category:
        return KAT_GRUPLARI.get(kanal.category.name, kanal.category.name)
    return "Kategorisiz"

def kat_grupla(guild: discord.Guild, voice_data: dict) -> dict:
    gruplar: dict[str, float] = {}
    for ch_id, sn in voice_data.items():
        grup = kanal_grubu(guild, ch_id)
        gruplar[grup] = gruplar.get(grup, 0) + sn
    return gruplar


@bot.command(name="stat", aliases=["istatistik", "stats"])
async def stat(ctx, uye: discord.Member = None):
    uye = uye or ctx.author
    now = datetime.utcnow()
    data, ud = get_user_stats(ctx.guild.id, uye.id)

    def elapsed(ts_str):
        return max(0, (now - datetime.fromisoformat(ts_str)).total_seconds()) if ts_str else 0

    # Anlık ses sürelerini ekle
    voice_anlık = dict(ud["voice"])
    for ch_id, join_str in ud["voice_join"].items():
        if join_str:
            voice_anlık[ch_id] = voice_anlık.get(ch_id, 0) + elapsed(join_str)

    # Anlık kamera/stream sürelerini ekle
    kamera_sure = ud["camera"] + elapsed(ud.get("camera_join"))
    stream_sure  = ud["stream"]  + elapsed(ud.get("stream_join"))

    # Ses durumu
    if uye.voice and uye.voice.channel:
        vs = uye.voice
        ekstralar = []
        if vs.self_video:   ekstralar.append("📷 Kamera")
        if vs.self_stream:  ekstralar.append("🎥 Yayın")
        if vs.self_mute:    ekstralar.append("🔇 Susturulmuş")
        ekstra = f" · {', '.join(ekstralar)}" if ekstralar else ""
        ses_durum = f"🟢 Aktif\n1. **{vs.channel.name}**{ekstra}"
    else:
        ses_durum = "🔴 Pasif\n1. Kullanıcı herhangi bir ses kanalında bulunmuyor."

    # En çok mesaj atılan kanallar (top 3)
    mesajlar = ud["messages"]
    toplam_mesaj = sum(mesajlar.values())
    if mesajlar:
        top3_msg = sorted(mesajlar.items(), key=lambda x: -x[1])[:3]
        msg_satirlari = "\n".join(
            f"{ctx.guild.get_channel(int(cid)).mention if ctx.guild.get_channel(int(cid)) else '#silinmiş'}: **{cnt} mesaj**"
            for cid, cnt in top3_msg
        )
    else:
        msg_satirlari = "Henüz mesaj kaydı yok"

    # Kategoriye göre ses süreleri
    toplam_ses = sum(voice_anlık.values())
    kat_gruplari = kat_grupla(ctx.guild, voice_anlık)

    # Sleeproom kanallarını ayrı grupla
    sleeproom_sure = 0.0
    for ch_id, sn in voice_anlık.items():
        ch = ctx.guild.get_channel(int(ch_id))
        if ch and "sleep" in ch.name.lower():
            sleeproom_sure += sn

    gosterilen = [
        ("Public Kanalları",  kat_gruplari.get("Public Kanalları", 0)),
        ("Yayın Kanalları",   kat_gruplari.get("Yayın Kanalları",  0)),
        ("Sleep Room",        sleeproom_sure),
    ]

    ses_satirlari = "\n".join(f"• **{k}:** {sure_format(v)}" for k, v in gosterilen)
    ses_satirlari += f"\n\n• **Kamera Süresi:** {sure_format(kamera_sure)}"
    ses_satirlari += f"\n• **Yayın (Stream) Süresi:** {sure_format(stream_sure)}"

    # En çok vakit geçirilen ses kanalları (top 3)
    if voice_anlık:
        top3_ses = sorted(voice_anlık.items(), key=lambda x: -x[1])[:3]
        top_ses_str = "\n".join(
            f"• {ctx.guild.get_channel(int(cid)).name if ctx.guild.get_channel(int(cid)) else 'Silinmiş'}: {sure_format(sn)}"
            for cid, sn in top3_ses if sn > 0
        ) or "—"
    else:
        top_ses_str = "—"

    # Tarih bilgileri
    hesap_yas = (now - uye.created_at.replace(tzinfo=None)).days // 365
    hesap_yazi = f"{hesap_yas} yıl önce" if hesap_yas > 0 else "bu yıl"

    embed = discord.Embed(
        description=(
            f"{uye.mention} adlı kullanıcının detaylı istatistik tablosu;\n\n"
            f"**Ses Durum:** {ses_durum}\n\n"
            f"**En Çok Mesaj Attığı Kanal**\n{msg_satirlari}\n\n"
            f"**Ses Kanalı İstatistikleri Aşağıdadır**\n{ses_satirlari}"
        ),
        color=discord.Color.blurple()
    )
    embed.set_author(name=f"{uye} · {uye.display_name}", icon_url=uye.display_avatar.url)
    embed.add_field(
        name="📊 Toplam Bilgiler",
        value=f"🔊 Ses: {sure_format(toplam_ses)}\n💬 Mesaj: {toplam_mesaj}\n🎥 Yayın: {sure_format(stream_sure)}",
        inline=True
    )
    embed.add_field(name="🏆 En Çok Seste", value=top_ses_str, inline=True)
    embed.add_field(
        name="📅 Tarihler",
        value=(
            f"Hesap: {uye.created_at.strftime('%-d %B %Y')} ({hesap_yazi})\n"
            f"Sunucuya Katılım: {uye.joined_at.strftime('%-d %B %Y') if uye.joined_at else '?'}"
        ),
        inline=True
    )
    embed.set_footer(text=f"ID: {uye.id}")
    embed.timestamp = now

    # Banner resmi oluştur
    top_msg_list = []
    for cid, cnt in sorted(mesajlar.items(), key=lambda x: -x[1])[:4]:
        ch = ctx.guild.get_channel(int(cid))
        top_msg_list.append((ch.name if ch else "silinmiş", cnt))

    top_ses_list = []
    for cid, sn in sorted(voice_anlık.items(), key=lambda x: -x[1])[:4]:
        if sn > 0:
            ch = ctx.guild.get_channel(int(cid))
            top_ses_list.append((ch.name if ch else "Silinmiş", sure_format(sn)))

    try:
        buf = await build_banner(
            avatar_url    = str(uye.display_avatar.url),
            display_name  = uye.display_name,
            username      = str(uye),
            joined_at     = uye.joined_at.strftime("%-d %B %Y") if uye.joined_at else "?",
            created_at    = uye.created_at.strftime("%-d %B %Y"),
            toplam_ses    = sure_format(toplam_ses),
            toplam_mesaj  = toplam_mesaj,
            toplam_stream = sure_format(stream_sure),
            top_msg       = top_msg_list,
            top_ses       = top_ses_list,
        )
        embed.set_image(url="attachment://stat_banner.png")
        await ctx.send(embed=embed, file=discord.File(buf, filename="stat_banner.png"))
    except Exception as e:
        embed.set_thumbnail(url=uye.display_avatar.url)
        await ctx.send(embed=embed)


@stat.error
async def stat_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send(embed=mod_embed("❌ Üye Bulunamadı", "Geçerli bir kullanıcı etiketle.", discord.Color.red()))


# ── TOP KOMUTU ──────────────────────────────────────────────────────────────────

TOP_KATEGORI = {
    "ses":   {"emoji": "🔊", "baslik": "Ses Süresi",    "renk": 0x5865F2},
    "mesaj": {"emoji": "💬", "baslik": "Mesaj Sayısı",  "renk": 0x57F287},
    "yayin": {"emoji": "🎥", "baslik": "Yayın Süresi",  "renk": 0xEB459E},
    "kayit": {"emoji": "📷", "baslik": "Kamera Süresi", "renk": 0xFEE75C},
    "puan":  {"emoji": "⭐", "baslik": "Puan",           "renk": 0xF0B232},
}

def _rozet(sira: int) -> str:
    return ["👑", "🥈", "🥉"][sira] if sira < 3 else f"`{sira+1:>2}.`"

def top_listesi_olustur(
    guild: discord.Guild,
    kategori: str,
    now: datetime,
    invoker: discord.Member | None = None,
) -> discord.Embed:
    ayar = TOP_KATEGORI.get(kategori, TOP_KATEGORI["ses"])

    def elapsed(ts_str):
        return max(0, (now - datetime.fromisoformat(ts_str)).total_seconds()) if ts_str else 0

    # ── Skor listesini oluştur ──
    skorlar: list[tuple[discord.Member, float, str]] = []

    if kategori == "puan":
        pdata = load_puan().get(str(guild.id), {})
        for uid, ud in pdata.items():
            member = guild.get_member(int(uid))
            if not member or member.bot:
                continue
            skor = ud.get("puan", 0)
            if skor > 0:
                skorlar.append((member, float(skor), f"{skor:,} puan".replace(",", ".")))
    else:
        sdata = load_stats().get(str(guild.id), {})
        for uid, ud in sdata.items():
            member = guild.get_member(int(uid))
            if not member or member.bot:
                continue
            if kategori == "ses":
                va = dict(ud.get("voice", {}))
                for ch_id, js in ud.get("voice_join", {}).items():
                    if js:
                        va[ch_id] = va.get(ch_id, 0) + elapsed(js)
                skor = sum(va.values())
                deger = sure_format(skor)
            elif kategori == "mesaj":
                skor = float(sum(ud.get("messages", {}).values()))
                deger = f"{int(skor):,} mesaj".replace(",", ".")
            elif kategori == "yayin":
                skor = ud.get("stream", 0) + elapsed(ud.get("stream_join"))
                deger = sure_format(skor)
            elif kategori == "kayit":
                skor = ud.get("camera", 0) + elapsed(ud.get("camera_join"))
                deger = sure_format(skor)
            else:
                continue
            if skor > 0:
                skorlar.append((member, skor, deger))

    skorlar.sort(key=lambda x: -x[1])
    toplam_kisi = len(skorlar)
    top10 = skorlar[:10]
    maksimum = top10[0][1] if top10 else 1

    # ── Embed satırları ──
    satirlar: list[str] = []

    for i, (member, skor, deger) in enumerate(top10):
        rozet = _rozet(i)
        satirlar.append(f"{rozet}  **{member.display_name}** — {deger}")

    # top3 ile geri kalanı ince çizgiyle ayır
    if len(satirlar) > 3:
        satirlar.insert(3, "⎯" * 20)

    aciklama = "\n".join(satirlar) if satirlar else "*Henüz bu kategoride kayıt yok.*"

    embed = discord.Embed(
        title=f"{ayar['emoji']}  {ayar['baslik']} Sıralaması",
        description=aciklama,
        color=ayar["renk"],
        timestamp=now,
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    # ── Footer: invoker'ın kendi sırası ──
    if invoker and not invoker.bot:
        invoker_sira = next(
            (i + 1 for i, (m, _, _) in enumerate(skorlar) if m.id == invoker.id),
            None
        )
        sira_yazi = f"🎯 Sıran: #{invoker_sira}" if invoker_sira else "🎯 Sıran: listede yok"
        embed.set_footer(
            text=f"{sira_yazi}  ·  👥 {toplam_kisi} kişi  ·  {guild.name}",
            icon_url=invoker.display_avatar.url,
        )
    else:
        embed.set_footer(
            text=f"👥 {toplam_kisi} kişi  ·  {guild.name}",
            icon_url=guild.icon.url if guild.icon else None,
        )

    return embed


class TopSelectMenu(discord.ui.Select):
    def __init__(self, invoker: discord.Member):
        self.invoker = invoker
        secenekler = [
            discord.SelectOption(label="Ses Süresi",    value="ses",   emoji="🔊", description="Toplam ses kanalı süresi"),
            discord.SelectOption(label="Mesaj Sayısı",  value="mesaj", emoji="💬", description="Toplam gönderilen mesaj"),
            discord.SelectOption(label="Yayın Süresi",  value="yayin", emoji="🎥", description="Toplam yayın süresi"),
            discord.SelectOption(label="Kamera Süresi", value="kayit", emoji="📷", description="Toplam kamera süresi"),
            discord.SelectOption(label="Puan",          value="puan",  emoji="⭐", description="Mevcut puan sıralaması"),
        ]
        super().__init__(placeholder="📊  Kategori seç...", options=secenekler, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        now   = datetime.utcnow()
        embed = top_listesi_olustur(interaction.guild, self.values[0], now, self.invoker)
        await interaction.response.edit_message(embed=embed, view=self.view)


class TopView(discord.ui.View):
    def __init__(self, invoker: discord.Member):
        super().__init__(timeout=180)
        self.add_item(TopSelectMenu(invoker))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


@bot.command(name="top", aliases=["sıralama", "siralama", "lb", "leaderboard"])
async def top(ctx):
    now   = datetime.utcnow()
    embed = top_listesi_olustur(ctx.guild, "ses", now, ctx.author)
    view  = TopView(ctx.author)
    await ctx.send(embed=embed, view=view)


def kayit_sirala(guild: discord.Guild):
    """points.json'dan yetkili_alim sayısına göre sıralı liste döndürür."""
    data = load_puan()
    guild_data = data.get(str(guild.id), {})
    liste = []
    for uid, ud in guild_data.items():
        member = guild.get_member(int(uid))
        if not member or member.bot:
            continue
        sayi = ud.get("yetkili_alim", 0)
        if sayi > 0:
            liste.append((member, sayi))
    liste.sort(key=lambda x: -x[1])
    return liste


def kayit_toprank_embed(guild: discord.Guild) -> discord.Embed:
    liste = kayit_sirala(guild)[:10]

    madalyalar = {0: "🥇", 1: "🥈", 2: "🥉"}
    en_yuksek = liste[0][1] if liste else 1

    satirlar = []
    for i, (member, sayi) in enumerate(liste):
        madalya = madalyalar.get(i, f"`{i+1:>2}.`")
        dolu = min(int((sayi / en_yuksek) * 8), 8)
        bos  = 8 - dolu
        bar  = "🟩" * dolu + "⬛" * bos
        satirlar.append(
            f"{madalya} **{member.display_name}**\n"
            f"{bar} **{sayi}** kayıt"
        )

    embed = discord.Embed(
        title="🎖️ Kayıt Sıralaması — Top 10",
        description="\n\n".join(satirlar) if satirlar else "Henüz kayıt yapılmamış.",
        color=discord.Color.gold()
    )
    embed.set_footer(text=f"{guild.name} · Toplam {len(kayit_sirala(guild))} kayıt sorumlusu")
    return embed


@bot.command(name="toprank", aliases=["kayitrank", "kayitlider", "kayitsira"])
async def toprank(ctx):
    """En çok kayıt yapan kayıt sorumlularını listeler: .toprank"""
    embed = kayit_toprank_embed(ctx.guild)
    await ctx.send(embed=embed)


# ── PUAN & GÖREV SİSTEMİ ────────────────────────────────────────────────────────

PUAN_FILE  = os.path.join(_BOT_DIR, "points.json")
GOREV_FILE = os.path.join(_BOT_DIR, "gorevler.json")

GOREV_LISTESI = {
    "gunluk_sohbet": {
        "ad": "Günlük Sohbet", "emoji": "💬",
        "aciklama": "20 mesaj at", "tur": "mesaj", "hedef": 20, "puan": 75,
    },
    "aktif_uye": {
        "ad": "Aktif Üye", "emoji": "🏆",
        "aciklama": "50 mesaj at", "tur": "mesaj", "hedef": 50, "puan": 300,
    },
    "ses_tutkunu": {
        "ad": "Ses Tutkunu", "emoji": "🔊",
        "aciklama": "2 saat seste dur", "tur": "ses", "hedef": 7200, "puan": 150,
    },
    "ses_efsanesi": {
        "ad": "Ses Efsanesi", "emoji": "🌟",
        "aciklama": "10 saat seste dur", "tur": "ses", "hedef": 36000, "puan": 500,
    },
    "yayinci": {
        "ad": "Yayıncı Ruhu", "emoji": "🎥",
        "aciklama": "30 dakika yayın aç", "tur": "yayin", "hedef": 1800, "puan": 200,
    },
    "kameraman": {
        "ad": "Kameraman", "emoji": "📷",
        "aciklama": "20 dakika kamera aç", "tur": "kamera", "hedef": 1200, "puan": 100,
    },
}

# Her yetki seviyesine karşılık gelen görev ID'leri
YETKI_GOREVLER = {
    "Hera of Wonkru":    ["gunluk_sohbet"],
    "Posedion of Wonkru": ["ses_tutkunu"],
    "Chole of Wonkru":   ["aktif_uye"],
    "Athena of Wonkru":  [],
    "Artemis of Wonkru": ["ses_efsanesi"],
    "Dein of Wonkru":    ["yayinci"],
    "Best of Wonkru":    [],
    "God of Wonkru":     [],
    "King of Wonkru":    [],
}


def load_puan():
    if os.path.exists(PUAN_FILE):
        with open(PUAN_FILE, "r") as f:
            return json.load(f)
    return {}

def save_puan(data):
    with open(PUAN_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user_puan(guild_id, user_id):
    data = load_puan()
    g, u = str(guild_id), str(user_id)
    data.setdefault(g, {})
    data[g].setdefault(u, {"puan": 0, "toplam_kazanilan": 0, "toplam_harcanan": 0})
    return data, data[g][u]

def puan_sirasi(guild_id, user_id):
    data = load_puan()
    puanlar = sorted(data.get(str(guild_id), {}).items(), key=lambda x: -x[1].get("puan", 0))
    for i, (uid, _) in enumerate(puanlar):
        if uid == str(user_id):
            return i + 1
    return len(puanlar) + 1


def puan_ver_sessiz(guild_id, user_id, miktar: int):
    """ctx gerektirmeden puan ekler."""
    data, ud = get_user_puan(guild_id, user_id)
    ud["puan"] = ud.get("puan", 0) + miktar
    ud["toplam_kazanilan"] = ud.get("toplam_kazanilan", 0) + miktar
    save_puan(data)


def kanal_saatlik_puan(kanal: discord.VoiceChannel) -> int:
    """Ses kanalı türüne göre saatlik puan miktarını döndürür."""
    if not kanal.category:
        return 300  # Kategorisiz → AFK gibi say
    kat = (
        kanal.category.name.upper()
        .replace("İ", "I").replace("Ğ", "G").replace("Ş", "S")
        .replace("Ü", "U").replace("Ö", "O").replace("Ç", "C")
    )
    if "WONKRU PUBLIC" in kat or "WONKRU PUBL" in kat:
        return 750
    if "STREAM" in kat:
        return 750
    if "REGISTER" in kat or "YETKILI ALIM" in kat:
        return 300
    return 300  # AFK ve diğer kanallar


@tasks.loop(hours=1)
async def saatlik_puan_ver():
    """Her saat sesli kanallardaki üyelere puan verir."""
    for guild in bot.guilds:
        for kanal in guild.voice_channels:
            miktar = kanal_saatlik_puan(kanal)
            for uye in kanal.members:
                if uye.bot:
                    continue
                puan_ver_sessiz(guild.id, uye.id, miktar)


def load_gorev():
    if os.path.exists(GOREV_FILE):
        with open(GOREV_FILE, "r") as f:
            return json.load(f)
    return {}

def save_gorev(data):
    with open(GOREV_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_user_gorev(guild_id, user_id):
    data = load_gorev()
    g, u = str(guild_id), str(user_id)
    data.setdefault(g, {})
    data[g].setdefault(u, {"aktif": {}, "tamamlanan": []})
    return data, data[g][u]

def get_current_stat_value(guild_id, user_id, tur, now):
    stats_data = load_stats()
    ud = stats_data.get(str(guild_id), {}).get(str(user_id), {})
    def elapsed(ts_str):
        return max(0, (now - datetime.fromisoformat(ts_str)).total_seconds()) if ts_str else 0
    if tur == "mesaj":
        return sum(ud.get("messages", {}).values())
    elif tur == "ses":
        voice = dict(ud.get("voice", {}))
        for ch_id, join_str in ud.get("voice_join", {}).items():
            if join_str:
                voice[ch_id] = voice.get(ch_id, 0) + elapsed(join_str)
        return sum(voice.values())
    elif tur == "yayin":
        return ud.get("stream", 0) + elapsed(ud.get("stream_join"))
    elif tur == "kamera":
        return ud.get("camera", 0) + elapsed(ud.get("camera_join"))
    return 0

def ilerleme_cubugu(mevcut, hedef, uzunluk=10):
    if hedef <= 0:
        return "🟩" * uzunluk
    dolu = min(int((mevcut / hedef) * uzunluk), uzunluk)
    tam = mevcut >= hedef
    dolu_emoji = "🟩" if tam else "🟥"
    return dolu_emoji * dolu + "⬛" * (uzunluk - dolu)


# .pe — puan ekle
@bot.command(name="pe")
@commands.has_permissions(manage_guild=True)
async def puan_ekle(ctx, uye: discord.Member, miktar: int, *, sebep: str = "Belirtilmedi"):
    if miktar <= 0:
        await ctx.send(embed=mod_embed("❌ Hata", "Miktar 0'dan büyük olmalı.", discord.Color.red()))
        return
    data, ud = get_user_puan(ctx.guild.id, uye.id)
    ud["puan"] += miktar
    ud["toplam_kazanilan"] = ud.get("toplam_kazanilan", 0) + miktar
    save_puan(data)
    embed = discord.Embed(
        title="✅ Puan Eklendi",
        description=f"{uye.mention} kullanıcısına **{miktar} puan** eklendi.\n**Sebep:** {sebep}\n**Güncel Puan:** {ud['puan']}",
        color=discord.Color.green()
    )
    embed.set_footer(text=f"İşlemi yapan: {ctx.author}")
    await ctx.send(embed=embed)
    await send_log(ctx.guild, log_embed(
        "💰 Puan Eklendi",
        f"**Üye:** {uye.mention} (`{uye.id}`)\n**Eklenen:** +{miktar} puan\n**Yeni Bakiye:** {ud['puan']} puan\n**Sebep:** {sebep}\n**Yetkili:** {ctx.author.mention}",
        discord.Color.green(), user=uye
    ), "puan")

@puan_ekle.error
async def puan_ekle_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=mod_embed("❌ Kullanım", "`.pe @kullanıcı miktar [sebep]`", discord.Color.red()))
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=mod_embed("❌ Yetki Yok", "Bu komutu kullanmak için yetkin yok.", discord.Color.red()))


# .pc — puan çıkar
@bot.command(name="pc")
@commands.has_permissions(manage_guild=True)
async def puan_cikar(ctx, uye: discord.Member, miktar: int, *, sebep: str = "Belirtilmedi"):
    if miktar <= 0:
        await ctx.send(embed=mod_embed("❌ Hata", "Miktar 0'dan büyük olmalı.", discord.Color.red()))
        return
    data, ud = get_user_puan(ctx.guild.id, uye.id)
    ud["puan"] = max(0, ud["puan"] - miktar)
    ud["toplam_harcanan"] = ud.get("toplam_harcanan", 0) + miktar
    save_puan(data)
    embed = discord.Embed(
        title="📉 Puan Çıkarıldı",
        description=f"{uye.mention} kullanıcısından **{miktar} puan** çıkarıldı.\n**Sebep:** {sebep}\n**Güncel Puan:** {ud['puan']}",
        color=discord.Color.orange()
    )
    embed.set_footer(text=f"İşlemi yapan: {ctx.author}")
    await ctx.send(embed=embed)
    await send_log(ctx.guild, log_embed(
        "📉 Puan Çıkarıldı",
        f"**Üye:** {uye.mention} (`{uye.id}`)\n**Çıkarılan:** -{miktar} puan\n**Yeni Bakiye:** {ud['puan']} puan\n**Sebep:** {sebep}\n**Yetkili:** {ctx.author.mention}",
        discord.Color.orange(), user=uye
    ), "puan")

@puan_cikar.error
async def puan_cikar_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=mod_embed("❌ Kullanım", "`.pc @kullanıcı miktar [sebep]`", discord.Color.red()))
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=mod_embed("❌ Yetki Yok", "Bu komutu kullanmak için yetkin yok.", discord.Color.red()))


# .p — puan kartı + yetki durumu (birleşik)
@bot.command(name="p", aliases=["puan", "yetkim", "rank", "seviyem", "rolum"])
@commands.check(bot_komutu_var)
async def puan_goster(ctx, uye: discord.Member = None):
    print(f"[DEBUG .p] PID={os.getpid()} msg_id={ctx.message.id} author={ctx.author}", flush=True)
    uye = uye or ctx.author
    now = datetime.utcnow()

    # Puan ve görev
    _, pud = get_user_puan(ctx.guild.id, uye.id)
    _, gud = get_user_gorev(ctx.guild.id, uye.id)
    sira = puan_sirasi(ctx.guild.id, uye.id)
    tamamlanan_gorev = len(gud.get("tamamlanan", []))
    yetkili_alim = pud.get("yetkili_alim", 0)

    # Stats
    sd = load_stats().get(str(ctx.guild.id), {}).get(str(uye.id), {})
    def elapsed(ts_str):
        return max(0, (now - datetime.fromisoformat(ts_str)).total_seconds()) if ts_str else 0
    public_ses, afk_ses = hesapla_ses_sureleri(ctx.guild, sd, now)
    stream_sure = sd.get("stream", 0) + elapsed(sd.get("stream_join"))
    kamera_sure = sd.get("camera", 0) + elapsed(sd.get("camera_join"))
    toplam_mesaj = sum(sd.get("messages", {}).values())

    # Mevcut yetki ve sonraki hedefler
    mevcut_yetki = kullanici_yetki_seviyesi(uye)
    yetki_bilgi = next((y for y in YETKI_LISTESI if y["rol"] == mevcut_yetki), None)

    def bar(mevcut_val, hedef_val, uzunluk=10):
        if hedef_val <= 0:
            return "🟩" * uzunluk
        dolu = min(int((mevcut_val / hedef_val) * uzunluk), uzunluk)
        tam = mevcut_val >= hedef_val
        dolu_emoji = "🟩" if tam else "🟥"
        return dolu_emoji * dolu + "⬛" * (uzunluk - dolu)

    def satir(emoji, ad, mevcut_str, hedef_str, mevcut_val, hedef_val, zorunlu=False):
        b = bar(mevcut_val, hedef_val)
        tam = "✅" if mevcut_val >= hedef_val else "🔴"
        yildiz = " ⭐" if zorunlu else ""
        return f"{tam} **{emoji} {ad}:**\n{b} ( {mevcut_str} / {hedef_str} ){yildiz}"

    # Embed
    embed = discord.Embed(color=discord.Color.blurple())
    embed.set_author(name=f"{uye.display_name} · Profil", icon_url=uye.display_avatar.url)
    embed.set_thumbnail(url=uye.display_avatar.url)

    if yetki_bilgi:
        g_sayi = yetki_bilgi["gorev_sayi"]
        aciklama = (
            f"💰 **{pud['puan']:,} puan** · 🏆 **#{sira}**\n"
            f"📈 {pud.get('toplam_kazanilan', 0):,} kazanıldı · 📉 {pud.get('toplam_harcanan', 0):,} harcandı"
        )
        embed.description = aciklama

        # Yetki satırı — inline alanlar
        embed.add_field(name="🎖️ Mevcut Yetki", value=f"**{mevcut_yetki}**", inline=True)
        embed.add_field(name="⬆️ Sonraki Yetki", value=f"**{yetki_bilgi['sonraki']}**", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        satirlar = []
        satirlar.append(satir("💰", "Puan", f"{pud['puan']:,}", f"{yetki_bilgi['puan']:,}", pud["puan"], yetki_bilgi["puan"], zorunlu=True))
        satirlar.append(satir("🔊", "Public Kanallarında", sure_format(public_ses), sure_format(yetki_bilgi["public_ses"]), public_ses, yetki_bilgi["public_ses"], zorunlu=True))
        h_m = yetki_bilgi["mesaj"]
        if h_m > 0:
            satirlar.append(satir("💬", "Chat Kanalında", str(toplam_mesaj), str(h_m), toplam_mesaj, h_m))
        else:
            satirlar.append(f"✅ **💬 Chat Kanalında:**\n{'🟩' * 10} ( {toplam_mesaj} mesaj )")
        h_afk = yetki_bilgi["afk_ses"]
        if h_afk > 0:
            satirlar.append(satir("😴", "Genel Sohbet (AFK)", sure_format(afk_ses), sure_format(h_afk), afk_ses, h_afk))
        else:
            satirlar.append(f"✅ **😴 Genel Sohbet (AFK):**\n{'🟩' * 10} ( {sure_format(afk_ses)} )")
        satirlar.append(f"{'✅' if stream_sure > 0 else '🔴'} **🎥 Yayın Kanallarında:**\n{bar(stream_sure, 72000)} ( {sure_format(stream_sure)} )")
        satirlar.append(f"{'✅' if kamera_sure > 0 else '🔴'} **📷 Sorumluluk (Kamera):**\n{bar(kamera_sure, 72000)} ( {sure_format(kamera_sure)} )")
        h_ya = yetki_bilgi.get("yetkili_alim", 0)
        if h_ya > 0:
            satirlar.append(satir("🎖️", "Sorumluluk (Kayıt)", str(yetkili_alim), str(h_ya), yetkili_alim, h_ya, zorunlu=True))
        else:
            ok = "✅" if yetkili_alim > 0 else "🔴"
            satirlar.append(f"{ok} **🎖️ Sorumluluk (Kayıt):**\n{bar(yetkili_alim, 10)} ( {yetkili_alim} kayıt )")
        if g_sayi > 0:
            satirlar.append(satir("📋", "Tamamlanan Görev", str(tamamlanan_gorev), str(g_sayi), tamamlanan_gorev, g_sayi, zorunlu=True))
        else:
            satirlar.append(f"✅ **📋 Tamamlanan Görev:**\n{'🟩' * 10} ( {tamamlanan_gorev} görev )")

        if g_sayi > 0:
            satirlar.append(f"\n*⭐ = Zorunlu · En az **{g_sayi}** görev tamamlanmalı*")

        embed.add_field(name="📊 İstatistikler", value="\n".join(satirlar), inline=False)
    else:
        # Maksimum seviye
        aciklama = (
            f"💰 **{pud['puan']:,} puan** · 🏆 **#{sira}**\n"
            f"📈 {pud.get('toplam_kazanilan', 0):,} kazanıldı · 📉 {pud.get('toplam_harcanan', 0):,} harcandı"
        )
        embed.description = aciklama
        embed.add_field(name="🎖️ Mevcut Yetki", value=f"**{mevcut_yetki or 'Rol Yok'}**", inline=True)
        embed.add_field(name="🏆 Durum", value="Maksimum seviye!", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        satirlar = [
            f"✅ **🔊 Public Ses:** {sure_format(public_ses)}",
            f"✅ **💬 Mesaj:** {toplam_mesaj:,}",
            f"✅ **🎥 Yayın:** {sure_format(stream_sure)}",
            f"✅ **😴 AFK Ses:** {sure_format(afk_ses)}",
            f"✅ **📷 Kamera:** {sure_format(kamera_sure)}",
            f"✅ **🎖️ Yetkili Alım:** {yetkili_alim}",
            f"✅ **📋 Görev:** {tamamlanan_gorev}",
        ]
        embed.add_field(name="📊 İstatistikler", value="\n".join(satirlar), inline=False)

    embed.set_footer(text=f"ID: {uye.id} · Hazır olunca .yükselt yaz!")
    embed.timestamp = now
    await ctx.send(embed=embed)


# ── GÖREV SİSTEMİ ───────────────────────────────────────────────────────────────



@bot.group(name="görev", aliases=["gorev"], invoke_without_command=True)
@commands.check(bot_komutu_var)
async def gorev_cmd(ctx):
    now = datetime.utcnow()
    _, gud = get_user_gorev(ctx.guild.id, ctx.author.id)
    aktif = gud.get("aktif", {})
    tamamlanan = gud.get("tamamlanan", [])

    if not aktif:
        embed = discord.Embed(
            title="📋 Görevlerim",
            description="Aktif görevin yok.\nGörev almak için `.görev al` komutunu kullan.",
            color=discord.Color.blurple()
        )
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title=f"📋 {ctx.author.display_name} · Aktif Görevler",
        color=discord.Color.blurple()
    )
    for gid, ginfo in aktif.items():
        gorev = GOREV_LISTESI.get(gid)
        if not gorev:
            continue
        baslangic_deger = ginfo.get("baslangic_deger", 0)
        guncel  = get_current_stat_value(ctx.guild.id, ctx.author.id, gorev["tur"], now)
        ilerleme = max(0, guncel - baslangic_deger)
        hedef   = gorev["hedef"]
        yuzde   = min(100, int((ilerleme / hedef) * 100)) if hedef > 0 else 0
        cubuk   = ilerleme_cubugu(ilerleme, hedef)
        if gorev["tur"] in ("ses", "yayin", "kamera"):
            ilerleme_str = f"{sure_format(ilerleme)} / {sure_format(hedef)}"
        else:
            ilerleme_str = f"{int(ilerleme)} / {hedef}"
        durum = "✅ Tamamlandı! `.görev teslim` yaz" if yuzde >= 100 else f"{cubuk} **{yuzde}%**"
        embed.add_field(
            name=f"{gorev['emoji']} {gorev['ad']} — {gorev['puan']} puan",
            value=f"İlerleme: {ilerleme_str}\n{durum}",
            inline=False
        )
    embed.set_footer(text=f"✅ Tamamlanan: {len(tamamlanan)} | Yeni görev: .görev al")
    await ctx.send(embed=embed)


@gorev_cmd.command(name="al")
@commands.check(bot_komutu_var)
async def gorev_al(ctx):
    now = datetime.utcnow()

    # Kullanıcının mevcut yetki seviyesini bul
    mevcut_yetki = kullanici_yetki_seviyesi(ctx.author)
    if not mevcut_yetki:
        await ctx.send(embed=mod_embed(
            "❌ Yetki Yok",
            "Bir Wonkru yetki rolüne sahip değilsin.",
            discord.Color.red()
        ))
        return

    # Bu yetkiye atanmış görevleri bul
    gorev_ids = YETKI_GOREVLER.get(mevcut_yetki, [])
    if not gorev_ids:
        await ctx.send(embed=mod_embed(
            "📋 Görev Yok",
            f"**{mevcut_yetki}** yetkisi için tanımlı görev bulunmuyor.",
            discord.Color.orange()
        ))
        return

    data, gud = get_user_gorev(ctx.guild.id, ctx.author.id)
    alinan, zaten_aktif, zaten_tamamlandi = [], [], []

    for gid in gorev_ids:
        gorev = GOREV_LISTESI.get(gid)
        if not gorev:
            continue
        if gid in gud.get("aktif", {}):
            zaten_aktif.append(f"{gorev['emoji']} {gorev['ad']}")
        elif gid in gud.get("tamamlanan", []):
            zaten_tamamlandi.append(f"{gorev['emoji']} {gorev['ad']}")
        else:
            baslangic_deger = get_current_stat_value(ctx.guild.id, ctx.author.id, gorev["tur"], now)
            gud.setdefault("aktif", {})[gid] = {
                "baslangic": now.isoformat(),
                "baslangic_deger": baslangic_deger
            }
            alinan.append(gorev)

    save_gorev(data)

    # Hiç yeni görev alınmadıysa
    if not alinan:
        if zaten_tamamlandi and not zaten_aktif:
            await ctx.send(embed=mod_embed(
                "🏆 Görevler Tamamlandı!",
                f"**{mevcut_yetki}** yetkisinin tüm görevlerini zaten tamamladın!\n\nYetki yükseltmek için `.yükselt` komutunu kullan.",
                discord.Color.gold()
            ))
        else:
            satirlar = []
            if zaten_aktif:
                satirlar.append("⏳ **Zaten aktif:** " + " · ".join(zaten_aktif))
            if zaten_tamamlandi:
                satirlar.append("✅ **Tamamlandı:** " + " · ".join(zaten_tamamlandi))
            await ctx.send(embed=mod_embed(
                "📋 Görevler",
                "\n".join(satirlar) or "Görev durumu bilinmiyor.",
                discord.Color.blurple()
            ))
        return

    embed = discord.Embed(
        title=f"📋 {mevcut_yetki} Görevleri Başladı!",
        description=f"Görevlerin otomatik olarak atandı. İlerlemeni `.görev` ile takip et.",
        color=discord.Color.green()
    )
    for g in alinan:
        embed.add_field(
            name=f"{g['emoji']} {g['ad']} — {g['puan']} puan",
            value=g["aciklama"],
            inline=False
        )
    if zaten_aktif:
        embed.add_field(name="⏳ Zaten Aktif", value=" · ".join(zaten_aktif), inline=False)
    if zaten_tamamlandi:
        embed.add_field(name="✅ Önceden Tamamlandı", value=" · ".join(zaten_tamamlandi), inline=False)
    embed.set_footer(text="Tamamlayınca .görev teslim yaz!")
    await ctx.send(embed=embed)


@gorev_cmd.command(name="teslim")
@commands.check(bot_komutu_var)
async def gorev_teslim(ctx):
    now = datetime.utcnow()
    data, gud = get_user_gorev(ctx.guild.id, ctx.author.id)
    aktif = gud.get("aktif", {})
    tamamlananlar = []
    for gid, ginfo in list(aktif.items()):
        gorev = GOREV_LISTESI.get(gid)
        if not gorev:
            continue
        baslangic_deger = ginfo.get("baslangic_deger", 0)
        guncel  = get_current_stat_value(ctx.guild.id, ctx.author.id, gorev["tur"], now)
        ilerleme = max(0, guncel - baslangic_deger)
        if ilerleme >= gorev["hedef"]:
            tamamlananlar.append((gid, gorev))
    if not tamamlananlar:
        await ctx.send(embed=mod_embed("❌ Tamamlanan Görev Yok", "Henüz tamamladığın bir görev yok.\nİlerlemeyi `.görev` ile takip edebilirsin.", discord.Color.orange()))
        return
    toplam_puan = 0
    embed = discord.Embed(title="🎉 Görev Teslimi", color=discord.Color.gold())
    for gid, gorev in tamamlananlar:
        del gud["aktif"][gid]
        gud.setdefault("tamamlanan", []).append(gid)
        pdata, pud = get_user_puan(ctx.guild.id, ctx.author.id)
        pud["puan"] += gorev["puan"]
        pud["toplam_kazanilan"] = pud.get("toplam_kazanilan", 0) + gorev["puan"]
        save_puan(pdata)
        toplam_puan += gorev["puan"]
        embed.add_field(name=f"{gorev['emoji']} {gorev['ad']}", value=f"+{gorev['puan']} puan", inline=True)
    save_gorev(data)
    _, pud2 = get_user_puan(ctx.guild.id, ctx.author.id)
    embed.description = f"{ctx.author.mention} toplam **{toplam_puan} puan** kazandı!\n💰 **Güncel Puan:** {pud2['puan']}"
    await ctx.send(embed=embed)


@gorev_cmd.command(name="sil")
@commands.has_permissions(manage_guild=True)
async def gorev_sil(ctx, uye: discord.Member, gorev_id: str = None):
    """Üyenin aktif veya tamamlanmış görevini siler. Sadece yöneticiler kullanabilir.
    Kullanım: .görev sil @üye [görev_id]
    Görev ID girilmezse tüm görevler sıfırlanır."""
    data, gud = get_user_gorev(ctx.guild.id, uye.id)

    if gorev_id:
        # Belirli görevi sil
        gorev_id = gorev_id.lower().replace("-", "_")
        aktif_silindi = gorev_id in gud.get("aktif", {})
        tamam_silindi = gorev_id in gud.get("tamamlanan", [])

        if not aktif_silindi and not tamam_silindi:
            mevcut_ids = list(gud.get("aktif", {}).keys()) + gud.get("tamamlanan", [])
            id_listesi = "\n".join(f"`{gid}`" for gid in mevcut_ids) or "*(görev yok)*"
            await ctx.send(embed=mod_embed(
                "❌ Görev Bulunamadı",
                f"**{uye.display_name}** için `{gorev_id}` ID'li görev bulunamadı.\n\n**Mevcut görev ID'leri:**\n{id_listesi}",
                discord.Color.red()
            ))
            return

        if aktif_silindi:
            del gud["aktif"][gorev_id]
        if tamam_silindi:
            gud["tamamlanan"].remove(gorev_id)

        save_gorev(data)
        gorev_adi = GOREV_LISTESI.get(gorev_id, {}).get("ad", gorev_id)
        durum = "aktif" if aktif_silindi else "tamamlanmış"
        await ctx.send(embed=mod_embed(
            "🗑️ Görev Silindi",
            f"**{uye.mention}** üyesinin **{gorev_adi}** ({durum}) görevi silindi.",
            discord.Color.orange()
        ))
    else:
        # Tüm görevleri sıfırla
        aktif_sayi = len(gud.get("aktif", {}))
        tamam_sayi = len(gud.get("tamamlanan", []))
        gud["aktif"] = {}
        gud["tamamlanan"] = []
        save_gorev(data)
        await ctx.send(embed=mod_embed(
            "🗑️ Tüm Görevler Sıfırlandı",
            f"**{uye.mention}** üyesinin tüm görevleri temizlendi.\n"
            f"Silinen: **{aktif_sayi}** aktif + **{tamam_sayi}** tamamlanmış",
            discord.Color.orange()
        ))

@gorev_sil.error
async def gorev_sil_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=mod_embed("❌ Yetki Yok", "Bu komutu sadece yöneticiler kullanabilir.", discord.Color.red()))
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(embed=mod_embed("❌ Üye Bulunamadı", "Geçerli bir kullanıcı etiketle.\nÖrnek: `.görev sil @kullanıcı`", discord.Color.red()))


# ── YETKİ YÜKSELTMESİ SİSTEMİ ──────────────────────────────────────────────────

YETKI_LISTESI = [
    {
        "rol": "Hera of Wonkru",
        "sonraki": "Posedion of Wonkru",
        "puan": 2000,
        "public_ses": 3 * 3600,
        "afk_ses": 0,
        "mesaj": 0,
        "gorev_sayi": 1,
    },
    {
        "rol": "Posedion of Wonkru",
        "sonraki": "Chole of Wonkru",
        "puan": 5000,
        "public_ses": 8 * 3600,
        "afk_ses": 0,
        "mesaj": 0,
        "gorev_sayi": 1,
    },
    {
        "rol": "Chole of Wonkru",
        "sonraki": "Athena of Wonkru",
        "puan": 10000,
        "public_ses": 10 * 3600,
        "afk_ses": 5 * 3600,
        "mesaj": 500,
        "gorev_sayi": 1,
    },
    {
        "rol": "Athena of Wonkru",
        "sonraki": "Artemis of Wonkru",
        "puan": 15000,
        "public_ses": 10 * 3600,
        "afk_ses": 5 * 3600,
        "mesaj": 500,
        "gorev_sayi": 0,
    },
    {
        "rol": "Artemis of Wonkru",
        "sonraki": "Dein of Wonkru",
        "puan": 30000,
        "public_ses": 15 * 3600,
        "afk_ses": 30 * 3600,
        "mesaj": 1000,
        "gorev_sayi": 1,
    },
    {
        "rol": "Dein of Wonkru",
        "sonraki": "Best of Wonkru",
        "puan": 48000,
        "public_ses": 15 * 3600,
        "afk_ses": 30 * 3600,
        "mesaj": 500,
        "yetkili_alim": 3,
        "gorev_sayi": 1,
    },
    {
        "rol": "Best of Wonkru",
        "sonraki": "God of Wonkru",
        "puan": 65000,
        "public_ses": 30 * 3600,
        "afk_ses": 20 * 3600,
        "mesaj": 500,
        "yetkili_alim": 3,
        "gorev_sayi": 0,
    },
    {
        "rol": "God of Wonkru",
        "sonraki": "King of Wonkru",
        "puan": 75000,
        "public_ses": 30 * 3600,
        "afk_ses": 30 * 3600,
        "mesaj": 1000,
        "yetkili_alim": 3,
        "gorev_sayi": 0,
    },
]

# Yetki adları sıralı liste olarak (en düşükten en yükseğe)
YETKI_SIRASI = [y["rol"] for y in YETKI_LISTESI] + ["Dein of Wonkru", "Best of Wonkru", "God of Wonkru", "King of Wonkru"]


def hesapla_ses_sureleri(guild: discord.Guild, ud: dict, now: datetime):
    """Kullanıcının public ve AFK (public dışı) ses sürelerini döner (saniye)."""
    voice_anlık = dict(ud.get("voice", {}))
    for ch_id, join_str in ud.get("voice_join", {}).items():
        if join_str:
            gecen = max(0, (now - datetime.fromisoformat(join_str)).total_seconds())
            voice_anlık[ch_id] = voice_anlık.get(ch_id, 0) + gecen

    public_ses = 0.0
    afk_ses = 0.0
    for ch_id, sn in voice_anlık.items():
        kanal = guild.get_channel(int(ch_id))
        if kanal and kanal.category:
            kat = kanal.category.name.upper().replace("İ", "I")
            if "PUBLIC" in kat:
                public_ses += sn
            else:
                afk_ses += sn
        elif kanal:
            afk_ses += sn
    return public_ses, afk_ses


def kullanici_yetki_seviyesi(member: discord.Member):
    """Üyenin en yüksek Wonkru yetki rolünü döner."""
    rol_adlari = {r.name for r in member.roles}
    for yetki in reversed(YETKI_SIRASI):
        if yetki in rol_adlari:
            return yetki
    return None


def yetki_gereksinim_kontrol(guild, member, yetki_bilgi, now):
    """Gereksinimleri kontrol eder. Eksik maddeleri liste olarak döner."""
    stats_data = load_stats()
    ud = stats_data.get(str(guild.id), {}).get(str(member.id), {})
    public_ses, afk_ses = hesapla_ses_sureleri(guild, ud, now)
    toplam_mesaj = sum(ud.get("messages", {}).values())

    _, pud = get_user_puan(guild.id, member.id)
    mevcut_puan = pud.get("puan", 0)
    yetkili_alim = pud.get("yetkili_alim", 0)

    _, gud = get_user_gorev(guild.id, member.id)
    tamamlanan_gorev = len(gud.get("tamamlanan", []))

    eksikler = []

    if mevcut_puan < yetki_bilgi["puan"]:
        eksikler.append(
            f"💰 Puan: **{mevcut_puan:,} / {yetki_bilgi['puan']:,}** "
            f"({yetki_bilgi['puan'] - mevcut_puan:,} eksik)"
        )

    if public_ses < yetki_bilgi["public_ses"]:
        eksikler.append(
            f"🔊 Public Ses: **{sure_format(public_ses)} / {sure_format(yetki_bilgi['public_ses'])}** "
            f"({sure_format(yetki_bilgi['public_ses'] - public_ses)} eksik)"
        )

    if yetki_bilgi["afk_ses"] > 0 and afk_ses < yetki_bilgi["afk_ses"]:
        eksikler.append(
            f"😴 AFK Ses: **{sure_format(afk_ses)} / {sure_format(yetki_bilgi['afk_ses'])}** "
            f"({sure_format(yetki_bilgi['afk_ses'] - afk_ses)} eksik)"
        )

    if yetki_bilgi["mesaj"] > 0 and toplam_mesaj < yetki_bilgi["mesaj"]:
        eksikler.append(
            f"💬 Mesaj: **{toplam_mesaj:,} / {yetki_bilgi['mesaj']:,}** "
            f"({yetki_bilgi['mesaj'] - toplam_mesaj:,} eksik)"
        )

    gerekli_alim = yetki_bilgi.get("yetkili_alim", 0)
    if gerekli_alim > 0 and yetkili_alim < gerekli_alim:
        eksikler.append(
            f"🎖️ Yetkili Alım: **{yetkili_alim} / {gerekli_alim}** "
            f"({gerekli_alim - yetkili_alim} kayıt daha yap)"
        )

    if yetki_bilgi["gorev_sayi"] > 0 and tamamlanan_gorev < yetki_bilgi["gorev_sayi"]:
        eksikler.append(
            f"📋 Tamamlanan Görev: **{tamamlanan_gorev} / {yetki_bilgi['gorev_sayi']}** "
            f"(`.görev al` ile görev al)"
        )

    return eksikler, {
        "puan": mevcut_puan,
        "public_ses": public_ses,
        "afk_ses": afk_ses,
        "mesaj": toplam_mesaj,
        "gorev": tamamlanan_gorev,
        "yetkili_alim": yetkili_alim,
    }


@bot.command(name="yükselt", aliases=["yukselt", "promote", "terfi"])
@commands.check(bot_komutu_var)
async def yukselt(ctx):
    """Mevcut gereksinimleri karşılıyorsa kullanıcıyı bir üst role yükseltir."""
    member = ctx.author
    now = datetime.utcnow()

    mevcut_yetki = kullanici_yetki_seviyesi(member)

    if mevcut_yetki is None:
        await ctx.send(embed=mod_embed(
            "❌ Wonkru Rolü Yok",
            "Önce bir Wonkru rolüne sahip olman gerekiyor.",
            discord.Color.red()
        ))
        return

    # Sonraki yetki bilgisini bul
    yetki_bilgi = next((y for y in YETKI_LISTESI if y["rol"] == mevcut_yetki), None)

    if yetki_bilgi is None:
        await ctx.send(embed=mod_embed(
            "🏆 Zirvedesin!",
            f"**{mevcut_yetki}** rolündesin ve daha yüksek bir rol yok.",
            discord.Color.gold()
        ))
        return

    eksikler, mevcut = yetki_gereksinim_kontrol(ctx.guild, member, yetki_bilgi, now)

    if eksikler:
        embed = discord.Embed(
            title="❌ Henüz Yükseltemezsin",
            description=(
                f"**{yetki_bilgi['rol']}** → **{yetki_bilgi['sonraki']}** için "
                f"şu koşulları sağlaman gerekiyor:\n\n" +
                "\n".join(f"• {e}" for e in eksikler)
            ),
            color=discord.Color.red()
        )
        embed.set_footer(text="İlerlemeyi .yetkim ile takip edebilirsin")
        await ctx.send(embed=embed)
        return

    # Tüm koşullar sağlandı — rol ver
    eski_rol = discord.utils.get(ctx.guild.roles, name=yetki_bilgi["rol"])
    yeni_rol = discord.utils.get(ctx.guild.roles, name=yetki_bilgi["sonraki"])

    if not yeni_rol:
        await ctx.send(embed=mod_embed("❌ Rol Bulunamadı", f"`{yetki_bilgi['sonraki']}` rolü sunucuda bulunamadı.", discord.Color.red()))
        return

    try:
        if eski_rol and eski_rol in member.roles:
            await member.remove_roles(eski_rol, reason="Yetki yükseltme")
        await member.add_roles(yeni_rol, reason="Yetki yükseltme")

        embed = discord.Embed(
            title="🎉 Yetki Yükseltmesi!",
            description=(
                f"{member.mention} tebrikler! 🎊\n\n"
                f"**{yetki_bilgi['rol']}** → **{yetki_bilgi['sonraki']}** rolüne yükseltildin!"
            ),
            color=discord.Color.gold()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Wonkru Yetki Sistemi")
        await ctx.send(embed=embed)

    except discord.Forbidden:
        await ctx.send(embed=mod_embed("❌ Yetki Hatası", "Botun bu rolü verme yetkisi yok.", discord.Color.red()))


# ── YETKİ VER KOMUTU ──────────────────────────────────────────────────────────

# Kısa ad → tam rol adı eşlemesi
YETKI_KISALTMA = {
    "hera":    "Hera of Wonkru",
    "posedion": "Posedion of Wonkru",
    "poséidon": "Posedion of Wonkru",
    "chole":   "Chole of Wonkru",
    "athena":  "Athena of Wonkru",
    "artemis": "Artemis of Wonkru",
    "dein":    "Dein of Wonkru",
    "best":    "Best of Wonkru",
    "god":     "God of Wonkru",
    "king":    "King of Wonkru",
}

YETKİLİ_ALIM_ROL = "YETKİLİ ALİM"


@yetki.command(name="wonkru")
async def yetki_wonkru_ver(ctx, uye: discord.Member, *, rol_adi: str):
    """Üyeye Wonkru yetki rolü verir. Sadece YETKİLİ ALİM rolüne sahip kişiler kullanabilir.
    Kullanım: .yetki @üye <rol>
    Roller: hera, posedion, chole, athena, artemis, dein, best, god, king"""

    # ── 1. YETKİLİ ALİM kontrolü ──────────────────────────────────────────────
    yetkili_alim_rol = discord.utils.find(
        lambda r: r.name.upper() == YETKİLİ_ALIM_ROL.upper(),
        ctx.guild.roles
    )
    kullanici_rolleri = {r.name.upper() for r in ctx.author.roles}
    if not (
        yetkili_alim_rol and yetkili_alim_rol.name.upper() in kullanici_rolleri
        or ctx.author.guild_permissions.administrator
    ):
        await ctx.send(embed=mod_embed(
            "❌ Yetki Yok",
            f"Bu komutu kullanmak için **{YETKİLİ_ALIM_ROL}** rolüne sahip olman gerekiyor.",
            discord.Color.red()
        ))
        return

    # ── 2. Rol adını çözümle ──────────────────────────────────────────────────
    anahtar = rol_adi.strip().lower()
    tam_rol_adi = YETKI_KISALTMA.get(anahtar)

    # Tam ad da yazılmış olabilir (ör. "Hera of Wonkru")
    if not tam_rol_adi:
        for kisaltma, tam in YETKI_KISALTMA.items():
            if anahtar == tam.lower():
                tam_rol_adi = tam
                break

    if not tam_rol_adi:
        liste = "\n".join(f"`{k}` → {v}" for k, v in YETKI_KISALTMA.items())
        await ctx.send(embed=mod_embed(
            "❌ Geçersiz Rol",
            f"Tanınmayan yetki adı: `{rol_adi}`\n\n**Kullanılabilir roller:**\n{liste}",
            discord.Color.red()
        ))
        return

    # ── 3. Hedef rolü sunucuda bul ────────────────────────────────────────────
    yeni_rol = discord.utils.get(ctx.guild.roles, name=tam_rol_adi)
    if not yeni_rol:
        await ctx.send(embed=mod_embed(
            "❌ Rol Bulunamadı",
            f"`{tam_rol_adi}` rolü sunucuda mevcut değil.",
            discord.Color.red()
        ))
        return

    # Bot Command ve Wonkru Family rollerini bul
    bot_command_rol = discord.utils.find(
        lambda r: r.name.lower() == "bot command", ctx.guild.roles
    )
    wonkru_family_rol = discord.utils.find(
        lambda r: "wonkru family" in r.name.lower(), ctx.guild.roles
    )

    # ── 4. DM gönder — başarısız olursa rol verme ─────────────────────────────
    dm_embed = discord.Embed(
        title="🎖️ Wonkru Yetki Verildi!",
        description=(
            f"Tebrikler! **{ctx.guild.name}** sunucusunda sana\n"
            f"**{tam_rol_adi}** yetkisi verildi.\n\n"
            f"Yetkiyi veren: **{ctx.author.display_name}**"
        ),
        color=discord.Color.gold()
    )
    dm_embed.set_footer(text="Wonkru Yetki Sistemi")

    try:
        await uye.send(embed=dm_embed)
    except discord.Forbidden:
        await ctx.send(embed=mod_embed(
            "❌ DM Gönderilemedi",
            f"{uye.mention} kullanıcısının DM'leri kapalı. **Rol verilmedi.**\n"
            f"Kullanıcı DM'lerini açtıktan sonra tekrar dene.",
            discord.Color.red()
        ))
        return
    except discord.HTTPException:
        await ctx.send(embed=mod_embed(
            "❌ DM Hatası",
            f"{uye.mention} kullanıcısına DM gönderilemedi. **Rol verilmedi.**",
            discord.Color.red()
        ))
        return

    # ── 6. Eski Wonkru yetki rollerini kaldır, yeniyi + Bot Command ver ─────
    try:
        alinacak = [
            r for r in uye.roles
            if r.name in YETKI_SIRASI and r.name != tam_rol_adi
        ]
        if alinacak:
            await uye.remove_roles(*alinacak, reason=f"Yetki değişimi: {ctx.author}")

        verilecekler = [yeni_rol]
        if bot_command_rol and bot_command_rol not in uye.roles:
            verilecekler.append(bot_command_rol)
        if wonkru_family_rol and wonkru_family_rol not in uye.roles:
            verilecekler.append(wonkru_family_rol)

        await uye.add_roles(*verilecekler, reason=f"Yetki verildi: {ctx.author}")
    except discord.Forbidden:
        await ctx.send(embed=mod_embed(
            "❌ Bot Yetkisi Yetersiz",
            "Botun bu rolü verme/alma yetkisi yok.",
            discord.Color.red()
        ))
        return

    # ── 7. Onay mesajı ───────────────────────────────────────────────────────
    ekstra = []
    if bot_command_rol:
        ekstra.append("🤖 Bot Command")
    if wonkru_family_rol:
        ekstra.append("👨‍👩‍👧 Wonkru Family")
    ekstra_satir = ("\n**Ek Roller:** " + " · ".join(ekstra)) if ekstra else ""

    onay = discord.Embed(
        title="✅ Yetki Verildi",
        description=(
            f"{uye.mention} kullanıcısına **{tam_rol_adi}** rolü verildi.\n"
            f"📨 DM bildirimi gönderildi.{ekstra_satir}"
        ),
        color=discord.Color.green()
    )
    onay.set_thumbnail(url=uye.display_avatar.url)
    onay.set_footer(text=f"Veren: {ctx.author.display_name}")
    await ctx.send(embed=onay)

    await send_log(ctx.guild, log_embed(
        "🎖️ Yetki Verildi",
        f"**Üye:** {uye.mention} (`{uye}`)\n"
        f"**Verilen Rol:** {tam_rol_adi}\n"
        f"**Ek Roller:** {', '.join(ekstra) if ekstra else 'Yok'}\n"
        f"**Veren:** {ctx.author.mention}",
        discord.Color.gold()
    ), "rol", actor=ctx.author)


@yetki_wonkru_ver.error
async def yetki_wonkru_ver_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send(embed=mod_embed("❌ Üye Bulunamadı", "Geçerli bir kullanıcı etiketle.\nÖrnek: `.yetki wonkru @kullanıcı hera`", discord.Color.red()))
    elif isinstance(error, commands.MissingRequiredArgument):
        liste = " · ".join(YETKI_KISALTMA.keys())
        await ctx.send(embed=mod_embed(
            "❌ Eksik Argüman",
            f"Kullanım: `.yetki wonkru @kullanıcı <rol>`\nRoller: {liste}",
            discord.Color.red()
        ))


# ── YETKİ VER MENÜ KOMUTU ─────────────────────────────────────────────────────

class WonkruRolSelect(discord.ui.Select):
    def __init__(self, hedef: discord.Member, veren: discord.Member):
        self.hedef = hedef
        self.veren = veren
        secenekler = [
            discord.SelectOption(
                label=tam,
                value=tam,
                emoji="🎖️",
                description=f"Hera'dan King'e sıralı"
            )
            for tam in YETKI_KISALTMA.values()
            if list(YETKI_KISALTMA.values()).index(tam) == list(YETKI_KISALTMA.values()).index(tam)
        ]
        # Tekrarları kaldır (posedion iki kez var)
        gorulen = set()
        temiz = []
        for s in secenekler:
            if s.value not in gorulen:
                gorulen.add(s.value)
                temiz.append(s)
        super().__init__(placeholder="🎖️ Hangi yetki rolünü vereceksin?", options=temiz, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.veren:
            await interaction.response.send_message("Bu menü sana ait değil.", ephemeral=True)
            return

        tam_rol_adi = self.values[0]
        guild = interaction.guild
        uye = self.hedef

        # Rolü bul
        yeni_rol = discord.utils.get(guild.roles, name=tam_rol_adi)
        if not yeni_rol:
            await interaction.response.send_message(
                embed=mod_embed("❌ Rol Bulunamadı", f"`{tam_rol_adi}` sunucuda mevcut değil.", discord.Color.red()),
                ephemeral=True
            )
            return

        # Ek rolleri bul
        bot_command_rol = discord.utils.find(lambda r: r.name.lower() == "bot command", guild.roles)
        wonkru_family_rol = discord.utils.find(lambda r: "wonkru family" in r.name.lower(), guild.roles)

        # DM gönder — başarısız olursa ver
        dm_embed = discord.Embed(
            title="🎖️ Wonkru Yetki Verildi!",
            description=(
                f"Tebrikler! **{guild.name}** sunucusunda sana\n"
                f"**{tam_rol_adi}** yetkisi verildi.\n\n"
                f"Yetkiyi veren: **{interaction.user.display_name}**"
            ),
            color=discord.Color.gold()
        )
        dm_embed.set_footer(text="Wonkru Yetki Sistemi")

        try:
            await uye.send(embed=dm_embed)
        except (discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message(
                embed=mod_embed(
                    "❌ DM Gönderilemedi",
                    f"{uye.mention} kullanıcısının DM'leri kapalı. **Rol verilmedi.**",
                    discord.Color.red()
                ),
                ephemeral=True
            )
            return

        # Rolleri ver
        try:
            alinacak = [r for r in uye.roles if r.name in YETKI_SIRASI and r.name != tam_rol_adi]
            if alinacak:
                await uye.remove_roles(*alinacak, reason=f"Yetki değişimi: {interaction.user}")
            verilecekler = [yeni_rol]
            if bot_command_rol and bot_command_rol not in uye.roles:
                verilecekler.append(bot_command_rol)
            if wonkru_family_rol and wonkru_family_rol not in uye.roles:
                verilecekler.append(wonkru_family_rol)
            await uye.add_roles(*verilecekler, reason=f"Yetki verildi: {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=mod_embed("❌ Bot Yetkisi Yetersiz", "Botun bu rolü verme/alma yetkisi yok.", discord.Color.red()),
                ephemeral=True
            )
            return

        ekstra = []
        if bot_command_rol: ekstra.append("🤖 Bot Command")
        if wonkru_family_rol: ekstra.append("👨‍👩‍👧 Wonkru Family")
        ekstra_satir = ("\n**Ek Roller:** " + " · ".join(ekstra)) if ekstra else ""

        onay = discord.Embed(
            title="✅ Yetki Verildi",
            description=(
                f"{uye.mention} kullanıcısına **{tam_rol_adi}** rolü verildi.\n"
                f"📨 DM bildirimi gönderildi.{ekstra_satir}"
            ),
            color=discord.Color.green()
        )
        onay.set_thumbnail(url=uye.display_avatar.url)
        onay.set_footer(text=f"Veren: {interaction.user.display_name}")

        for item in self.view.children:
            item.disabled = True
        await interaction.response.edit_message(view=self.view)
        await interaction.followup.send(embed=onay)

        await send_log(guild, log_embed(
            "🎖️ Yetki Verildi",
            f"**Üye:** {uye.mention} (`{uye}`)\n"
            f"**Verilen Rol:** {tam_rol_adi}\n"
            f"**Ek Roller:** {', '.join(ekstra) if ekstra else 'Yok'}\n"
            f"**Veren:** {interaction.user.mention}",
            discord.Color.gold()
        ), "rol", actor=interaction.user)


class WonkruRolView(discord.ui.View):
    def __init__(self, hedef: discord.Member, veren: discord.Member):
        super().__init__(timeout=60)
        self.add_item(WonkruRolSelect(hedef, veren))


@bot.command(name="yetkiver", aliases=["yv"])
async def yetkiver(ctx, uye: discord.Member):
    """Wonkru yetki rolü ver (menüden seç). YETKİLİ ALİM gerekli."""
    # YETKİLİ ALİM kontrolü
    yetkili_alim_rol = discord.utils.find(
        lambda r: r.name.upper() == YETKİLİ_ALIM_ROL.upper(), ctx.guild.roles
    )
    kullanici_rolleri = {r.name.upper() for r in ctx.author.roles}
    if not (
        (yetkili_alim_rol and yetkili_alim_rol.name.upper() in kullanici_rolleri)
        or ctx.author.guild_permissions.administrator
    ):
        await ctx.send(embed=mod_embed(
            "❌ Yetki Yok",
            f"Bu komutu kullanmak için **{YETKİLİ_ALIM_ROL}** rolüne sahip olman gerekiyor.",
            discord.Color.red()
        ))
        return

    embed = discord.Embed(
        title="🎖️ Wonkru Yetki Ver",
        description=f"**{uye.display_name}** kullanıcısına hangi Wonkru yetkisini vermek istiyorsun?\n\nAşağıdaki menüden seç:",
        color=discord.Color.blurple()
    )
    embed.set_thumbnail(url=uye.display_avatar.url)
    embed.set_footer(text=f"İşlemi yapan: {ctx.author.display_name} · 60 saniye içinde seç")
    await ctx.send(embed=embed, view=WonkruRolView(uye, ctx.author))


@yetkiver.error
async def yetkiver_error(ctx, error):
    if isinstance(error, commands.MemberNotFound):
        await ctx.send(embed=mod_embed("❌ Üye Bulunamadı", "Geçerli bir kullanıcı etiketle.\nÖrnek: `.yetkiver @kullanıcı`", discord.Color.red()))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=mod_embed("❌ Eksik Argüman", "Kullanım: `.yetkiver @kullanıcı`", discord.Color.red()))


# ── YETKİ ÇEK KOMUTU ──────────────────────────────────────────────────────────

@bot.command(name="yçek", aliases=["ycek", "yetkicek", "yetkiçek"])
@commands.has_permissions(manage_roles=True)
@commands.bot_has_permissions(manage_roles=True)
async def yetki_cek(ctx, uye: discord.Member):
    """Üyenin tüm Wonkru yetki rollerini alır.
    Kullanım: .yçek @kullanıcı"""
    alinacak = [r for r in uye.roles if r.name in YETKI_SIRASI]

    if not alinacak:
        await ctx.send(embed=mod_embed(
            "❌ Wonkru Rolü Yok",
            f"{uye.mention} kullanıcısında alınacak Wonkru yetkisi bulunamadı.",
            discord.Color.orange()
        ))
        return

    alinan_isimler = [r.name for r in alinacak]

    try:
        await uye.remove_roles(*alinacak, reason=f"Tüm Wonkru yetkileri alındı: {ctx.author}")
    except discord.Forbidden:
        await ctx.send(embed=mod_embed("❌ Bot Yetkisi Yetersiz", "Botun bu rolleri alma yetkisi yok.", discord.Color.red()))
        return

    embed = discord.Embed(
        title="🚫 Yetki Çekildi",
        description=(
            f"{uye.mention} kullanıcısının tüm Wonkru yetkileri alındı.\n\n"
            f"**Alınan Roller:**\n" + "\n".join(f"• {r}" for r in alinan_isimler)
        ),
        color=discord.Color.red()
    )
    embed.set_thumbnail(url=uye.display_avatar.url)
    embed.set_footer(text=f"İşlemi yapan: {ctx.author.display_name}")
    await ctx.send(embed=embed)

    await send_log(ctx.guild, log_embed(
        "🚫 Wonkru Yetkileri Alındı",
        f"**Üye:** {uye.mention} (`{uye}`)\n"
        f"**Alınan Roller:** {', '.join(alinan_isimler)}\n"
        f"**İşlemi Yapan:** {ctx.author.mention}",
        discord.Color.red()
    ), "rol", actor=ctx.author)


@yetki_cek.error
async def yetki_cek_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send(embed=mod_embed("❌ Yetki Yok", "Bu komutu kullanmak için rol yönetme yetkin olmalı.", discord.Color.red()))
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send(embed=mod_embed("❌ Üye Bulunamadı", "Geçerli bir kullanıcı etiketle.\nÖrnek: `.yçek @kullanıcı`", discord.Color.red()))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=mod_embed("❌ Eksik Argüman", "Kullanım: `.yçek @kullanıcı`", discord.Color.red()))


# ── .BİON — SAHİP KOMUT REHBERİ (SAYFA SAYFA) ────────────────────────────────

BION_SAYFALAR = [
    {
        "baslik": "🛡️ Moderasyon",
        "renk": discord.Color.red(),
        "komutlar": [
            ("`  .kick @kullanıcı [sebep]`",       "Kullanıcıyı sunucudan atar"),
            ("`   .ban @kullanıcı [sebep]`",        "Kullanıcıyı kalıcı yasaklar"),
            ("`         .unban <ID>`",              "Yasağı kaldırır"),
            ("`         .mute @kullanıcı`",         "Kullanıcıyı susturur"),
            ("`       .unmute @kullanıcı`",         "Susturmayı kaldırır"),
            ("`  .warn @kullanıcı [sebep]`",        "Uyarı verir"),
            ("`     .warnings @kullanıcı`",         "Uyarıları listeler"),
            ("`.clearwarnings @kullanıcı`",         "Tüm uyarıları siler"),
            ("`        .purge / .sil <n>`",         "Son n mesajı siler"),
        ],
    },
    {
        "baslik": "⚙️ Sunucu Yönetimi",
        "renk": discord.Color.orange(),
        "komutlar": [
            ("`  .role @kullanıcı <rol>`",   "Rol ver / al"),
            ("`     .slowmode <saniye>`",    "Yavaş mod ayarla"),
            ("`               .lock`",      "Kanalı kilitler"),
            ("`             .unlock`",      "Kanalı açar"),
            ("`    .kanalsil #kanal`",      "Kanal siler (log'a alır)"),
            ("`.kanalgeri / .kgeri`",       "Silinen kanalı geri getirir"),
            ("`  .userinfo [@kullanıcı]`",  "Kullanıcı bilgisi"),
            ("`         .serverinfo`",      "Sunucu bilgisi"),
            ("`   .logkurulum`",            "Log sistemi kurulumu"),
            ("`   .logkanal #kanal`",       "Log kanalı ayarla"),
        ],
    },
    {
        "baslik": "📋 Kayıt Sistemi",
        "renk": discord.Color.green(),
        "komutlar": [
            ("`            .e @kullanıcı`", "Erkek olarak kayıt eder"),
            ("`            .k @kullanıcı`", "Kız olarak kayıt eder"),
            ("`  .kayıtsız @kullanıcı`",   "Kayıtsız rolü verir"),
            ("`   .cezalı @kullanıcı`",    "Kullanıcıyı cezalandırır"),
            ("`.cezakaldır @kullanıcı`",   "Cezayı kaldırır"),
        ],
    },
    {
        "baslik": "🔊 Ses Kanalı",
        "renk": discord.Color.teal(),
        "komutlar": [
            ("`.seskat / .join`",                    "Bota ses kanalına girer"),
            ("`.sesayr / .dc`",                      "Botu ses kanalından çıkarır"),
            ("`.sestasi / .move @kullanıcı #kanal`", "Kullanıcıyı taşır"),
        ],
    },
    {
        "baslik": "💰 Puan & İstatistik",
        "renk": discord.Color.gold(),
        "komutlar": [
            ("`          .p [@kullanıcı]`", "Puan kartı + yetki durumu  *(Bot Command gerekli)*"),
            ("`.top / .lb / .sıralama`",    "Puan sıralaması"),
            ("`   .stat [@kullanıcı]`",     "Detaylı istatistik"),
            ("`    .pe @kullanıcı <n>`",    "Puan ekle  *(Yetkili)*"),
            ("`    .pc @kullanıcı <n>`",    "Puan çıkar  *(Yetkili)*"),
        ],
    },
    {
        "baslik": "📋 Görev Sistemi",
        "renk": discord.Color.purple(),
        "komutlar": [
            ("`              .görev`",              "Aktif görevleri listeler  *(Bot Command gerekli)*"),
            ("`           .görev al`",              "Yeni görev alır  *(Bot Command gerekli)*"),
            ("`       .görev teslim`",              "Görevi teslim eder  *(Bot Command gerekli)*"),
            ("`.görev sil @kullanıcı [ID]`",        "Görevi siler  *(Yetkili)*"),
            ("`            .yükselt`",              "Yetki yükseltme başvurusu  *(Bot Command gerekli)*"),
        ],
    },
    {
        "baslik": "🎖️ Wonkru Yetki Sistemi",
        "renk": discord.Color.blurple(),
        "komutlar": [
            ("`.yetki ver @kullanıcı <rol>`", "Sunucu rolü ver  *(Rol Yönetimi)*"),
            ("`  .yetki al @kullanıcı <rol>`", "Sunucu rolünü al  *(Rol Yönetimi)*"),
            ("`.yetki wonkru @kullanıcı <r>`", "Wonkru yetki ver (yazarak)  *(YETKİLİ ALİM)*"),
            ("`     .yetkiver / .yv @kul`",    "Wonkru yetki ver (menü)  *(YETKİLİ ALİM)*"),
            ("`           .yçek @kullanıcı`",  "Tüm Wonkru yetkilerini al  *(Rol Yönetimi)*"),
        ],
    },
    {
        "baslik": "🔗 Link & Nick Sistemi",
        "renk": discord.Color.from_rgb(220, 80, 80),
        "komutlar": [
            ("`               .tag`",                 "Kendi nickine 𖣂 tagı ekler  *(Herkes)*"),
            ("`        .tag @kullanıcı`",             "Başkasının nickine 𖣂 ekler  *(Nickname Yönetme)*"),
            ("`        .linkfiltre / .lf`",          "Link filtresi durumunu gösterir  *(Sunucu Yönetimi)*"),
            ("`          .linkfiltre aç`",            "Link filtresini aktif eder  *(Sunucu Yönetimi)*"),
            ("`       .linkfiltre kapat`",            "Link filtresini kapatır  *(Sunucu Yönetimi)*"),
            ("`.linkfiltre rol @rol`",                "Belirtilen role link izni verir  *(Sunucu Yönetimi)*"),
            ("`.linkfiltre rolçıkar @rol`",           "Rolün link muaflığını kaldırır  *(Sunucu Yönetimi)*"),
            ("`.linkfiltre kanal #kanal`",            "Kanalda linklere izin verir  *(Sunucu Yönetimi)*"),
            ("`.linkfiltre kanalçıkar #kanal`",       "Kanalın link muaflığını kaldırır  *(Sunucu Yönetimi)*"),
            ("`        🔒 Nick Koruması`",            ""),
            ("`       𖣂 isim | yaş`",                "Kayıt sonrası otomatik tag formatı"),
            ("`        Booster Nick`",                "Booster'lar nick değiştirebilir — 𖣂 tag korunur"),
            ("`       Normal Üye Nick`",              "Normal üyeler kendi nickini değiştiremez, bot geri alır"),
        ],
    },
]


class BionSelect(discord.ui.Select):
    def __init__(self):
        secenekler = [
            discord.SelectOption(
                label=veri["baslik"],
                value=str(i),
                emoji=veri["baslik"].split()[0],
                description=f"{len(veri['komutlar'])} komut"
            )
            for i, veri in enumerate(BION_SAYFALAR)
        ]
        super().__init__(
            placeholder="📖 Kategori seç...",
            options=secenekler,
            min_values=1,
            max_values=1
        )

    async def callback(self, interaction: discord.Interaction):
        self.view.sayfa = int(self.values[0])
        await interaction.response.edit_message(embed=self.view.build_embed(), view=self.view)


class BionView(discord.ui.View):
    def __init__(self, sayfa=0):
        super().__init__(timeout=120)
        self.sayfa = sayfa
        self.add_item(BionSelect())

    def build_embed(self):
        veri = BION_SAYFALAR[self.sayfa]
        embed = discord.Embed(
            title=veri["baslik"],
            color=veri["renk"]
        )
        satirlar = []
        for komut, aciklama in veri["komutlar"]:
            satirlar.append(f"{komut}\n  ↳ {aciklama}")
        embed.description = "\n\n".join(satirlar)
        embed.set_footer(text=f"Sayfa {self.sayfa + 1}/{len(BION_SAYFALAR)} · Sadece sunucu sahibi görebilir")
        return embed


@bot.command(name="bion")
async def bion(ctx):
    """Tüm bot komutlarını sayfa sayfa gösterir. Sadece sunucu sahibi kullanabilir."""
    if ctx.author.id != ctx.guild.owner_id:
        await ctx.send(embed=mod_embed(
            "❌ Yetkisiz",
            "Bu komutu sadece **sunucu sahibi** kullanabilir.",
            discord.Color.red()
        ))
        return
    view = BionView(sayfa=0)
    await ctx.send(embed=view.build_embed(), view=view)


# ══════════════════════════════════════════════════════════════════════════════
# 🚨  ROL UYARI SİSTEMİ  (Manuel rol verme takibi)
# ══════════════════════════════════════════════════════════════════════════════

ROL_UYARI_FILE = os.path.join(_BOT_DIR, "rol_uyari.json")

# Bellek içi: {guild_id: {executor_id: count}}
_rol_uyari_sayac: dict = {}


def _ru_yukle() -> dict:
    if os.path.exists(ROL_UYARI_FILE):
        with open(ROL_UYARI_FILE, "r") as f:
            return json.load(f)
    return {}


def _ru_kaydet(data: dict):
    with open(ROL_UYARI_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _ru_sayac_artir(guild_id: int, user_id: int) -> int:
    """Sayacı 1 artır, yeni değeri döndür. Hem bellekte hem dosyada saklar."""
    g = str(guild_id)
    u = str(user_id)
    data = _ru_yukle()
    data.setdefault(g, {})
    data[g][u] = data[g].get(u, 0) + 1
    _ru_kaydet(data)
    # Bellek de güncelle
    _rol_uyari_sayac.setdefault(guild_id, {})[user_id] = data[g][u]
    return data[g][u]


def _ru_sayac_sifirla(guild_id: int, user_id: int):
    g = str(guild_id)
    u = str(user_id)
    data = _ru_yukle()
    if g in data and u in data[g]:
        data[g][u] = 0
        _ru_kaydet(data)
    _rol_uyari_sayac.setdefault(guild_id, {})[user_id] = 0


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    """Birine manuel rol verildiğinde executor'ü tespit et, uyar veya cezalandır."""
    guild = after.guild

    # ── Timeout süresi dolunca 🔇 Muted rolü ve [Muted] nick'i otomatik temizle ──
    if before.is_timed_out() and not after.is_timed_out():
        muted_role = discord.utils.get(guild.roles, name="🔇 Muted")
        if muted_role and muted_role in after.roles:
            try:
                await after.remove_roles(muted_role, reason="Chat mute süresi doldu — otomatik temizlik")
            except Exception:
                pass
        try:
            if after.nick and "[Muted]" in after.nick:
                new_nick = after.nick.replace(" [Muted]", "").replace("[Muted]", "").strip()
                await after.edit(nick=new_nick if new_nick else None)
        except Exception:
            pass
        try:
            await send_log(guild, log_embed(
                "🔊 Chat Mute Otomatik Kaldırıldı",
                f"**Üye:** {after.mention} (`{after.id}`)\n**Sebep:** Mute süresi doldu",
                discord.Color.green(), user=after
            ), "mute")
        except Exception:
            pass

    # ── Nick değişikliği koruması ─────────────────────────────────────────────
    TAG = "𖣂"
    if before.nick != after.nick and after.id not in _nick_isleniyor:
        await asyncio.sleep(0.4)
        degistiren = None
        try:
            async for entry in guild.audit_logs(
                action=discord.AuditLogAction.member_update, limit=5
            ):
                if entry.target and entry.target.id == after.id:
                    if (discord.utils.utcnow() - entry.created_at).total_seconds() < 6:
                        degistiren = entry.user
                        break
        except (discord.Forbidden, discord.HTTPException):
            pass

        # Bot veya yetkili (manage_nicknames) değiştirdiyse karışma
        bot_degistirdi = degistiren is not None and degistiren.bot
        yetkili_degistirdi = (
            degistiren is not None
            and not degistiren.bot
            and degistiren.id != after.id
        )
        if not bot_degistirdi and not yetkili_degistirdi:
            # Üye kendi nickini değiştirdi
            is_booster = after.premium_since is not None
            yeni_nick = after.nick or ""
            _nick_isleniyor.add(after.id)
            try:
                if is_booster:
                    # İzin var ama 𖣂 tag korunur
                    if not yeni_nick:
                        # Nick silmeye çalıştı → eski nicke döndür
                        await after.edit(nick=before.nick, reason="Booster: nick kaldırılamaz")
                    elif not yeni_nick.startswith(TAG):
                        # Tag kaldırıldı → başa ekle
                        await after.edit(
                            nick=f"{TAG} {yeni_nick.lstrip()}",
                            reason="Booster: sunucu tagı korundu"
                        )
                else:
                    # Normal üye → nick değiştirme izni yok, eski haline döndür
                    await after.edit(nick=before.nick, reason="Nick değiştirme izni yok")
            except (discord.Forbidden, discord.HTTPException):
                pass
            finally:
                _nick_isleniyor.discard(after.id)
    # ──────────────────────────────────────────────────────────────────────────

    # Rol ekleme var mı?
    eklenen_roller = [r for r in after.roles if r not in before.roles]
    if not eklenen_roller:
        return

    # Audit log'dan kimin verdiğini bul
    await asyncio.sleep(0.5)
    executor = None
    try:
        async for entry in guild.audit_logs(
            action=discord.AuditLogAction.member_role_update, limit=5
        ):
            if entry.target and entry.target.id == after.id:
                if (discord.utils.utcnow() - entry.created_at).total_seconds() < 5:
                    executor = entry.user
                    break
    except (discord.Forbidden, discord.HTTPException):
        return

    if executor is None:
        return
    # Bot kendi verdiği rolleri sayma
    if executor.bot:
        return
    # Sunucu sahibi muaf
    if executor.id == guild.owner_id:
        return

    rol_listesi = ", ".join(r.mention for r in eklenen_roller)
    sayi = _ru_sayac_artir(guild.id, executor.id)

    if sayi < 3:
        # 1. veya 2. kez → DM uyarı
        embed = discord.Embed(
            title=f"⚠️  Rol Verme Uyarısı — {sayi}. Uyarı",
            color=0xE67E22,
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=guild.icon.url if guild.icon else after.display_avatar.url)
        embed.add_field(name="🏛️ Sunucu",       value=guild.name,              inline=True)
        embed.add_field(name="⚠️ Uyarı No",     value=f"**{sayi}/3**",         inline=True)
        embed.add_field(name="👤 Alan Üye",      value=str(after),              inline=False)
        embed.add_field(name="🎭 Verilen Rol",   value=rol_listesi,             inline=False)
        embed.add_field(
            name="📋 Açıklama",
            value=(
                "Sunucuda **sağ tıklayarak manuel rol verme** tespit edildi.\n"
                f"{'**Son uyarın!** Bir kez daha yapılırsa rolleriniz alınacak.' if sayi == 2 else 'Lütfen bu işlemi tekrarlama.'}"
            ),
            inline=False
        )
        embed.set_footer(text="Wonkru Moderation System")
        try:
            await executor.send(embed=embed)
        except discord.Forbidden:
            pass

        # Log kanalına da bildir
        log_e = discord.Embed(
            title=f"⚠️ Manuel Rol Verme — {sayi}. Uyarı",
            color=0xE67E22,
            timestamp=discord.utils.utcnow()
        )
        log_e.set_thumbnail(url=executor.display_avatar.url)
        log_e.add_field(name="👤 Veren",       value=f"{executor.mention} (`{executor.id}`)", inline=True)
        log_e.add_field(name="👥 Alan",        value=f"{after.mention} (`{after.id}`)",       inline=True)
        log_e.add_field(name="🎭 Rol",         value=rol_listesi,                             inline=False)
        log_e.add_field(name="⚠️ Uyarı No",   value=f"**{sayi}/3**",                         inline=True)
        log_e.set_footer(text="Wonkru Moderation System")
        await send_log(guild, log_e, "rol")

    else:
        # 3. kez → rollerini al
        _ru_sayac_sifirla(guild.id, executor.id)
        try:
            korunan = [r for r in executor.roles if r.managed or r == guild.default_role]
            await executor.edit(roles=korunan, reason="🚨 Manuel rol verme: 3. ihlal — roller alındı")
        except discord.Forbidden:
            pass

        # DM bildir
        embed = discord.Embed(
            title="🚨  Rolleriniz Alındı!",
            color=0xE74C3C,
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=guild.icon.url if guild.icon else executor.display_avatar.url)
        embed.add_field(name="🏛️ Sunucu",     value=guild.name,    inline=True)
        embed.add_field(name="📋 Sebep",
            value="3 kez **sağ tıklayarak manuel rol verme** tespit edildi. Rolleriniz otomatik olarak alındı.",
            inline=False
        )
        embed.add_field(name="🎭 Son Verilen Rol", value=rol_listesi, inline=False)
        embed.set_footer(text="Wonkru Moderation System")
        try:
            await executor.send(embed=embed)
        except discord.Forbidden:
            pass

        # Log kanalına bildir
        log_e = discord.Embed(
            title="🚨 Manuel Rol Verme — Roller Alındı (3. İhlal)",
            color=0xE74C3C,
            timestamp=discord.utils.utcnow()
        )
        log_e.set_thumbnail(url=executor.display_avatar.url)
        log_e.add_field(name="👤 İhlalci",     value=f"{executor.mention} (`{executor.id}`)", inline=True)
        log_e.add_field(name="👥 Alan",        value=f"{after.mention} (`{after.id}`)",       inline=True)
        log_e.add_field(name="🎭 Son Rol",     value=rol_listesi,                             inline=False)
        log_e.add_field(name="🔨 Uygulama",    value="✅ Tüm roller alındı",                   inline=True)
        log_e.set_footer(text="Wonkru Moderation System")
        await send_log(guild, log_e, "rol")


@bot.command(name="roluyarisifirla", aliases=["rusifirla", "rolsifirla"])
@commands.has_permissions(administrator=True)
async def rol_uyari_sifirla(ctx, uye: discord.Member):
    """Bir üyenin rol uyarı sayacını sıfırlar."""
    _ru_sayac_sifirla(ctx.guild.id, uye.id)
    embed = discord.Embed(
        title="✅ Rol Uyarı Sayacı Sıfırlandı",
        color=0x2ECC71,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="👤 Üye",    value=uye.mention,         inline=True)
    embed.add_field(name="📊 Sayaç", value="0 / 3",              inline=True)
    embed.set_footer(text="Wonkru Moderation System")
    await ctx.send(embed=embed)


@bot.command(name="roluyaridurum", aliases=["rudurum"])
@commands.has_permissions(administrator=True)
async def rol_uyari_durum(ctx, uye: discord.Member):
    """Bir üyenin mevcut rol uyarı sayacını gösterir."""
    data = _ru_yukle()
    sayi = data.get(str(ctx.guild.id), {}).get(str(uye.id), 0)
    embed = discord.Embed(
        title="📊 Rol Uyarı Durumu",
        color=0x3498DB,
        timestamp=discord.utils.utcnow()
    )
    embed.set_thumbnail(url=uye.display_avatar.url)
    embed.add_field(name="👤 Üye",      value=uye.mention,          inline=True)
    embed.add_field(name="⚠️ Uyarı",   value=f"**{sayi} / 3**",    inline=True)
    bar = "🟥" * min(sayi, 3) + "⬛" * (3 - min(sayi, 3))
    embed.add_field(name="📈 Durum",   value=bar,                   inline=False)
    embed.set_footer(text="Wonkru Moderation System")
    await ctx.send(embed=embed)


@bot.command(name="mutesayac", aliases=["msayac", "mutesay"])
@commands.has_permissions(kick_members=True)
async def mute_sayac_cmd(ctx, uye: discord.Member):
    """Bir üyenin mute sayacını gösterir."""
    sayi = ms_al(ctx.guild.id, uye.id)
    bar  = "🟥" * min(sayi, OTOMATIK_KARANTINA_ESIK) + "⬛" * max(0, OTOMATIK_KARANTINA_ESIK - sayi)
    embed = discord.Embed(title="🔇 Mute Sayacı", color=0xE67E22, timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=uye.display_avatar.url)
    embed.add_field(name="👤 Üye",    value=uye.mention,                                   inline=True)
    embed.add_field(name="📊 Sayaç", value=f"**{sayi} / {OTOMATIK_KARANTINA_ESIK}**",     inline=True)
    embed.add_field(name="📈 Bar",   value=bar,                                             inline=False)
    if sayi >= OTOMATIK_KARANTINA_ESIK:
        embed.add_field(name="⚠️ Durum", value="🔒 Karantinaya düşmeli!", inline=False)
    elif sayi == OTOMATIK_KARANTINA_ESIK - 1:
        embed.add_field(name="⚠️ Durum", value="Bir daha muteyse otomatik karantina!", inline=False)
    embed.set_footer(text="Wonkru Moderation System")
    await ctx.send(embed=embed)


@bot.command(name="mutesifirla", aliases=["mssifirla"])
@commands.has_permissions(administrator=True)
async def mute_sifirla_cmd(ctx, uye: discord.Member):
    """Bir üyenin mute sayacını sıfırlar. Sadece adminler kullanabilir."""
    ms_sifirla(ctx.guild.id, uye.id)
    embed = discord.Embed(title="✅ Mute Sayacı Sıfırlandı", color=0x2ECC71, timestamp=discord.utils.utcnow())
    embed.add_field(name="👤 Üye",    value=uye.mention,  inline=True)
    embed.add_field(name="📊 Sayaç", value="0 / 6",       inline=True)
    embed.set_footer(text="Wonkru Moderation System")
    await ctx.send(embed=embed)


# ══════════════════════════════════════════════════════════════════════════════
# 🛡️  NUKE GUARD SİSTEMİ
# ══════════════════════════════════════════════════════════════════════════════

NUKE_GUARD_FILE = os.path.join(_BOT_DIR, "nukeguard.json")

# Bellek içi eylem takibi: {guild_id: {user_id: {eylem: [timestamp, ...]}}}
_nuke_log: dict = {}

# Eşikler: (max_işlem_sayısı, saniye_penceresi)
NUKE_ESIK = {
    "kanal_sil": (3, 30),
    "rol_sil":   (3, 30),
    "ban":       (5, 30),
    "kick":      (5, 30),
    "webhook":   (3, 30),
}

NUKE_EYLEM_ETIKET = {
    "kanal_sil": "⚡ Toplu Kanal Silme",
    "rol_sil":   "🎭 Toplu Rol Silme",
    "ban":       "🔨 Toplu Ban",
    "kick":      "👢 Toplu Kick",
    "webhook":   "🌐 Toplu Webhook",
}


# ── Config yardımcıları ────────────────────────────────────────────────────────

def _ng_yukle():
    if os.path.exists(NUKE_GUARD_FILE):
        with open(NUKE_GUARD_FILE, "r") as f:
            return json.load(f)
    return {}

def _ng_kaydet(data):
    with open(NUKE_GUARD_FILE, "w") as f:
        json.dump(data, f, indent=2)

def ng_aktif_mi(guild_id: int) -> bool:
    return _ng_yukle().get(str(guild_id), {}).get("aktif", True)

def ng_whitelist_al(guild_id: int) -> set:
    return set(_ng_yukle().get(str(guild_id), {}).get("whitelist", []))

def _ng_guncelle(guild_id: int, **kwargs):
    data = _ng_yukle()
    g = str(guild_id)
    if g not in data:
        data[g] = {"aktif": True, "whitelist": []}
    data[g].update(kwargs)
    _ng_kaydet(data)

def ng_whitelist_ekle(guild_id: int, role_id: int):
    data = _ng_yukle()
    g = str(guild_id)
    if g not in data:
        data[g] = {"aktif": True, "whitelist": []}
    if role_id not in data[g]["whitelist"]:
        data[g]["whitelist"].append(role_id)
    _ng_kaydet(data)

def ng_whitelist_cikar(guild_id: int, role_id: int):
    data = _ng_yukle()
    g = str(guild_id)
    if g in data and role_id in data[g].get("whitelist", []):
        data[g]["whitelist"].remove(role_id)
    _ng_kaydet(data)


# ── Eylem takipçisi ────────────────────────────────────────────────────────────

def _ng_eylem_kaydet(guild_id: int, user_id: int, eylem: str) -> int:
    """Eylemi kaydeder, penceredeki toplam sayıyı döndürür."""
    now = datetime.utcnow().timestamp()
    _, pencere = NUKE_ESIK[eylem]
    u = _nuke_log.setdefault(guild_id, {}).setdefault(user_id, {})
    u.setdefault(eylem, []).append(now)
    u[eylem] = [t for t in u[eylem] if now - t <= pencere]
    return len(u[eylem])

def _ng_temizle(guild_id: int, user_id: int):
    _nuke_log.get(guild_id, {}).pop(user_id, None)


# ── Tespit & müdahale ──────────────────────────────────────────────────────────

async def _ng_kontrol(guild: discord.Guild, user: discord.Member | discord.User,
                      eylem: str, hedef_adi: str):
    """Eşik aşıldıysa saldırganı banlar ve log atar."""
    if not ng_aktif_mi(guild.id):
        return
    # Bot kendi işlemleri tetiklemesin
    if guild.me and user.id == guild.me.id:
        return
    # Sunucu sahibi muaf
    if user.id == guild.owner_id:
        return
    # Whitelist'teki rollerden birini taşıyanlar muaf
    whitelist = ng_whitelist_al(guild.id)
    if whitelist and isinstance(user, discord.Member):
        if {r.id for r in user.roles} & whitelist:
            return

    esik_sayi, esik_sure = NUKE_ESIK[eylem]
    sayi = _ng_eylem_kaydet(guild.id, user.id, eylem)
    if sayi < esik_sayi:
        return

    # Eşik aşıldı!
    _ng_temizle(guild.id, user.id)

    ban_success = False
    try:
        if isinstance(user, discord.Member):
            try:
                await user.edit(roles=[], reason="🛡️ Nuke Guard: Roller temizlendi")
            except discord.Forbidden:
                pass
        await guild.ban(
            user,
            reason=f"🛡️ Nuke Guard: {NUKE_EYLEM_ETIKET.get(eylem, eylem)} ({sayi} işlem / {esik_sure}s)",
            delete_message_days=0
        )
        ban_success = True
    except (discord.Forbidden, discord.HTTPException):
        pass

    embed = discord.Embed(
        title="🛡️  NUKE GUARD — Saldırı Tespit Edildi!",
        color=0xFF0000,
        timestamp=datetime.utcnow()
    )
    embed.set_author(name=f"{user} • {user.id}", icon_url=user.display_avatar.url)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="⚠️ Saldırı Türü",   value=NUKE_EYLEM_ETIKET.get(eylem, eylem),            inline=True)
    embed.add_field(name="📊 İşlem Sayısı",   value=f"**{sayi}** / {esik_sure}sn içinde",            inline=True)
    embed.add_field(name="🎯 Son Hedef",       value=hedef_adi,                                       inline=False)
    embed.add_field(name="👤 Saldırgan",       value=f"{user.mention} (`{user.id}`)",                 inline=True)
    embed.add_field(name="🔨 Uygulanan Ceza",  value="✅ Başarıyla banlandı" if ban_success else "❌ Ban uygulanamadı (yetki yok)", inline=True)
    embed.set_footer(text="Wonkru Nuke Guard Sistemi")

    # Genel log kanalına gönder
    channel_id = get_log_channel_id(guild.id, "genel")
    if channel_id:
        ch = guild.get_channel(channel_id)
        if ch:
            try:
                await ch.send(content="@everyone" if ban_success else None, embed=embed)
            except discord.Forbidden:
                pass


# ── Event handler'lar ──────────────────────────────────────────────────────────

@bot.event
async def on_guild_channel_delete(channel):
    guild = channel.guild
    if not ng_aktif_mi(guild.id):
        return
    await asyncio.sleep(0.5)
    try:
        async for entry in guild.audit_logs(action=discord.AuditLogAction.channel_delete, limit=5):
            if entry.target and entry.target.id == channel.id:
                await _ng_kontrol(guild, entry.user, "kanal_sil", f"#{channel.name}")
                return
    except (discord.Forbidden, discord.HTTPException):
        pass


@bot.event
async def on_guild_role_delete(role):
    guild = role.guild
    if not ng_aktif_mi(guild.id):
        return
    await asyncio.sleep(0.5)
    try:
        async for entry in guild.audit_logs(action=discord.AuditLogAction.role_delete, limit=5):
            if entry.target and entry.target.id == role.id:
                await _ng_kontrol(guild, entry.user, "rol_sil", f"@{role.name}")
                return
    except (discord.Forbidden, discord.HTTPException):
        pass


@bot.event
async def on_member_ban(guild, user):
    if not ng_aktif_mi(guild.id):
        return
    await asyncio.sleep(0.5)
    try:
        async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=5):
            if entry.target and entry.target.id == user.id:
                await _ng_kontrol(guild, entry.user, "ban", str(user))
                return
    except (discord.Forbidden, discord.HTTPException):
        pass


@bot.event
async def on_member_remove(member):
    guild = member.guild
    if not ng_aktif_mi(guild.id):
        return
    await asyncio.sleep(0.5)
    try:
        async for entry in guild.audit_logs(action=discord.AuditLogAction.kick, limit=5):
            if entry.target and entry.target.id == member.id:
                if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 5:
                    await _ng_kontrol(guild, entry.user, "kick", str(member))
                return
    except (discord.Forbidden, discord.HTTPException):
        pass


@bot.event
async def on_webhooks_update(channel):
    guild = channel.guild
    if not ng_aktif_mi(guild.id):
        return
    await asyncio.sleep(0.5)
    try:
        async for entry in guild.audit_logs(
            action=discord.AuditLogAction.webhook_create, limit=3
        ):
            if (datetime.utcnow() - entry.created_at.replace(tzinfo=None)).total_seconds() < 5:
                await _ng_kontrol(guild, entry.user, "webhook", f"#{channel.name}")
                return
    except (discord.Forbidden, discord.HTTPException):
        pass


# ── Komutlar ──────────────────────────────────────────────────────────────────

@bot.command(name="nukeguard", aliases=["ng", "ngkoru"])
@commands.has_permissions(administrator=True)
async def nukeguard_cmd(ctx, alt: str = None, *, arg: str = None):
    """Nuke Guard yönetim komutu. Sadece adminler kullanabilir."""
    guild_id = ctx.guild.id

    if alt is None or alt.lower() == "durum":
        aktif = ng_aktif_mi(guild_id)
        wl_ids = ng_whitelist_al(guild_id)
        wl_roller = []
        for rid in wl_ids:
            r = ctx.guild.get_role(rid)
            if r:
                wl_roller.append(r.mention)

        embed = discord.Embed(
            title="🛡️  Nuke Guard — Durum",
            color=0x2ECC71 if aktif else 0x95A5A6,
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="📡 Durum",      value="✅ Aktif" if aktif else "❌ Kapalı",       inline=True)
        embed.add_field(name="🔓 Whitelist",  value=", ".join(wl_roller) if wl_roller else "Boş", inline=False)
        esik_text = "\n".join(
            f"**{NUKE_EYLEM_ETIKET.get(k,k)}:** {v[0]} işlem / {v[1]}sn"
            for k, v in NUKE_ESIK.items()
        )
        embed.add_field(name="📊 Eşikler", value=esik_text, inline=False)
        embed.set_footer(text="Wonkru Nuke Guard • .nukeguard yardım")
        return await ctx.send(embed=embed)

    elif alt.lower() in ("aç", "ac", "aktif", "on"):
        _ng_guncelle(guild_id, aktif=True)
        embed = discord.Embed(title="🛡️ Nuke Guard Aktifleştirildi", color=0x2ECC71, timestamp=datetime.utcnow())
        embed.add_field(name="📡 Durum", value="✅ Sunucu artık Nuke Guard koruması altında", inline=False)
        embed.set_footer(text="Wonkru Nuke Guard Sistemi")
        return await ctx.send(embed=embed)

    elif alt.lower() in ("kapat", "kapa", "off", "deaktif"):
        _ng_guncelle(guild_id, aktif=False)
        embed = discord.Embed(title="⚠️ Nuke Guard Kapatıldı", color=0xE74C3C, timestamp=datetime.utcnow())
        embed.add_field(name="📡 Durum", value="❌ Nuke Guard devre dışı bırakıldı", inline=False)
        embed.set_footer(text="Wonkru Nuke Guard Sistemi")
        return await ctx.send(embed=embed)

    elif alt.lower() in ("whitelist", "wl"):
        if not ctx.message.role_mentions:
            embed = discord.Embed(
                title="❌ Hata",
                description="Kullanım: `.nukeguard whitelist @rol ekle` veya `.nukeguard whitelist @rol çıkar`",
                color=0xE74C3C
            )
            return await ctx.send(embed=embed)
        rol = ctx.message.role_mentions[0]
        islem = (arg or "").replace(rol.name, "").strip().lower() if arg else ""

        if islem in ("ekle", "add", "+"):
            ng_whitelist_ekle(guild_id, rol.id)
            embed = discord.Embed(title="✅ Whitelist'e Eklendi", color=0x2ECC71, timestamp=datetime.utcnow())
            embed.add_field(name="🔓 Rol", value=rol.mention, inline=True)
            embed.add_field(name="📋 Açıklama", value="Bu role sahip üyeler Nuke Guard'dan muaf tutulur", inline=False)
        elif islem in ("çıkar", "cikar", "sil", "remove", "-"):
            ng_whitelist_cikar(guild_id, rol.id)
            embed = discord.Embed(title="🗑️ Whitelist'ten Çıkarıldı", color=0xE67E22, timestamp=datetime.utcnow())
            embed.add_field(name="🔒 Rol", value=rol.mention, inline=True)
        else:
            # Toggle
            wl = ng_whitelist_al(guild_id)
            if rol.id in wl:
                ng_whitelist_cikar(guild_id, rol.id)
                embed = discord.Embed(title="🗑️ Whitelist'ten Çıkarıldı", color=0xE67E22, timestamp=datetime.utcnow())
                embed.add_field(name="🔒 Rol", value=rol.mention, inline=True)
            else:
                ng_whitelist_ekle(guild_id, rol.id)
                embed = discord.Embed(title="✅ Whitelist'e Eklendi", color=0x2ECC71, timestamp=datetime.utcnow())
                embed.add_field(name="🔓 Rol", value=rol.mention, inline=True)
        embed.set_footer(text="Wonkru Nuke Guard Sistemi")
        return await ctx.send(embed=embed)

    elif alt.lower() in ("yardım", "yardim", "help"):
        embed = discord.Embed(title="🛡️ Nuke Guard — Komutlar", color=0x3498DB, timestamp=datetime.utcnow())
        embed.add_field(name="📋 Komutlar", value=(
            "`.nukeguard durum` — Sistem durumunu göster\n"
            "`.nukeguard aç` — Korumayı aktifleştir\n"
            "`.nukeguard kapat` — Korumayı kapat\n"
            "`.nukeguard whitelist @rol` — Rolü whitelist'e ekle/çıkar\n"
            "`.nukeguard whitelist @rol ekle` — Whitelist'e ekle\n"
            "`.nukeguard whitelist @rol çıkar` — Whitelist'ten çıkar"
        ), inline=False)
        embed.add_field(name="⚡ Korunan Eylemler", value=(
            "• 30sn içinde **3+ kanal silme**\n"
            "• 30sn içinde **3+ rol silme**\n"
            "• 30sn içinde **5+ ban**\n"
            "• 30sn içinde **5+ kick**\n"
            "• 30sn içinde **3+ webhook oluşturma**"
        ), inline=False)
        embed.set_footer(text="Wonkru Nuke Guard Sistemi")
        return await ctx.send(embed=embed)

    else:
        await ctx.send(embed=mod_embed("❌ Geçersiz Alt Komut",
            "`.nukeguard yardım` yazarak komutları görebilirsin.", discord.Color.red()))


# ══════════════════════════════════════════════════════════════════════════════
# 📺  STREAM / CAM PANELİ
# ══════════════════════════════════════════════════════════════════════════════

STREAM_ODA_ADI   = "stream-cam"          # Ses/metin kanalı adı (izin ekleme/çıkarma)
STREAMER_ROL_ADI = "Streamer"            # Streamer rolü adı
KAMERA_ROL_ADI   = "Kamera"             # Kamera rolü adı
STREAM_BASVURU_KANAL = "streamer-cam"   # Başvuruların düşeceği kanal adı

STREAM_PANEL_EMBED_DESC = (
    "📺 **Wonkru Stream Panel**\n\n"
    "Stream kanallarımızda bize yardımcı olmak için stream sorumluluğuna başvuru yapabilirsiniz.\n\n"
    "**Başvuru için şartlarımız**\n"
    "• Streamer odalarında çıkan sorunları çözebilme.\n"
    "• Streamer odalarının düzenini sağlamaları ve denetleme yapma.\n"
    "• Streamer desteğe gelen kişilere yardımcı olabilmeleri.\n"
    "• Yapıcağımız etkinliklerde bize destek sağlayıp aktifliği yüksek tutmaları.\n\n"
    "🪶 Streamer başvuruları Streamer Yöneticilerimiz tarafından değerlendirilip "
    "buna uygun olup olmadığınızı kontrol ettikten sonra size dönüş yapılacaktır.\n\n"
    "❗ Streamer rolü almadan önce **#Erişim Yok** kanalını okumayı unutmayınız.\n"
    "❗ Kamera rolü almadan önce **#Erişim Yok** kanalını okumayı unutmayınız.\n\n"
    "Aşağıdaki menüden yapmak istediğiniz işlemi seçiniz."
)


# ── Başvuru Modal ──────────────────────────────────────────────────────────────

class StreamerBasvuruModal(discord.ui.Modal, title="📺 Streamer Sorumlu Başvurusu"):
    yas = discord.ui.TextInput(
        label="Yaşınız",
        placeholder="Örnek: 20",
        max_length=3,
        required=True
    )
    tecrube = discord.ui.TextInput(
        label="Stream / Moderasyon Tecrübeniz",
        style=discord.TextStyle.paragraph,
        placeholder="Daha önce hangi sunucularda görev aldınız?",
        max_length=500,
        required=True
    )
    neden = discord.ui.TextInput(
        label="Neden Streamer Sorumlusu Olmak İstiyorsunuz?",
        style=discord.TextStyle.paragraph,
        placeholder="Kendinizi kısaca tanıtın ve nedeninizi açıklayın.",
        max_length=600,
        required=True
    )
    aktiflik = discord.ui.TextInput(
        label="Günlük Aktiflik Süreniz",
        placeholder="Örnek: Günde 3-4 saat",
        max_length=100,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        guild  = interaction.guild
        uye    = interaction.user

        embed = discord.Embed(
            title="📺 Yeni Streamer Sorumlu Başvurusu",
            color=discord.Color.blue(),
            timestamp=datetime.utcnow()
        )
        embed.set_author(name=str(uye), icon_url=uye.display_avatar.url)
        embed.set_thumbnail(url=uye.display_avatar.url)
        embed.add_field(name="👤 Başvuran", value=uye.mention, inline=True)
        embed.add_field(name="🪪 ID",       value=str(uye.id),  inline=True)
        embed.add_field(name="🎂 Yaş",      value=self.yas.value, inline=True)
        embed.add_field(name="💼 Tecrübe",  value=self.tecrube.value, inline=False)
        embed.add_field(name="❓ Neden?",   value=self.neden.value, inline=False)
        embed.add_field(name="⏰ Aktiflik", value=self.aktiflik.value, inline=False)
        embed.set_footer(text="Streamer Başvuru Sistemi")

        # Log kanalına gönder
        log_kanal = discord.utils.find(
            lambda c: STREAM_BASVURU_KANAL.lower() in c.name.lower(),
            guild.text_channels
        )
        if log_kanal:
            try:
                await log_kanal.send(embed=embed)
            except discord.Forbidden:
                pass

        # Sunucu sahibine DM
        try:
            await guild.owner.send(embed=embed)
        except Exception:
            pass

        # Streamer rolüne sahip üyelere de DM (yönetici)
        streamer_rol = discord.utils.find(lambda r: r.name == STREAMER_ROL_ADI, guild.roles)
        if streamer_rol:
            for m in streamer_rol.members:
                if m != guild.owner:
                    try:
                        await m.send(embed=embed)
                    except Exception:
                        pass

        await interaction.response.send_message(
            embed=mod_embed(
                "✅ Başvurunuz Alındı",
                "Streamer Sorumlu başvurunuz yöneticilere iletildi. En kısa sürede dönüş yapılacaktır.",
                discord.Color.green()
            ),
            ephemeral=True
        )


# ── Yetki kontrol yardımcısı ───────────────────────────────────────────────────

def stream_yetkili_mi(interaction: discord.Interaction) -> bool:
    """Streamer rolü, yönetici veya sunucu sahibi."""
    member = interaction.user
    if member.guild_permissions.administrator or member.id == interaction.guild.owner_id:
        return True
    streamer_rol = discord.utils.find(lambda r: r.name == STREAMER_ROL_ADI, interaction.guild.roles)
    return streamer_rol in member.roles if streamer_rol else False


# ── İzin listesi embed ─────────────────────────────────────────────────────────

async def stream_izin_listesi_embed(guild: discord.Guild) -> discord.Embed:
    """Stream odasındaki özel izinleri listeler."""
    oda = discord.utils.find(
        lambda c: STREAM_ODA_ADI.lower() in c.name.lower(),
        guild.channels
    )
    embed = discord.Embed(title="📋 Stream Odası İzin Listesi", color=discord.Color.blue())
    if not oda:
        embed.description = "❌ Stream odası bulunamadı."
        return embed

    izinler = []
    for target, overwrite in oda.overwrites.items():
        if isinstance(target, discord.Member):
            if overwrite.connect is True or overwrite.speak is True or overwrite.stream is True:
                izinler.append(f"👤 {target.mention} — Konuşma izni var")
    if izinler:
        embed.description = "\n".join(izinler)
    else:
        embed.description = "Özel eklenen kullanıcı yok."
    embed.set_footer(text=f"Kanal: #{oda.name}")
    return embed


# ── Üye Seç Modal (Ekle/Çıkar) ────────────────────────────────────────────────

class StreamUyeEkleModal(discord.ui.Modal, title="Stream Odasına Kullanıcı Ekle"):
    kullanici_id = discord.ui.TextInput(
        label="Kullanıcı ID veya @etiket",
        placeholder="Örnek: 123456789012345678",
        max_length=30,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not stream_yetkili_mi(interaction):
            await interaction.response.send_message(
                embed=mod_embed("❌ Yetkisiz", "Bu işlem için Streamer rolüne sahip olman gerekiyor.", discord.Color.red()),
                ephemeral=True
            )
            return
        guild = interaction.guild
        raw   = self.kullanici_id.value.strip().strip("<@!>")
        try:
            uye = guild.get_member(int(raw)) or await guild.fetch_member(int(raw))
        except Exception:
            await interaction.response.send_message(
                embed=mod_embed("❌ Bulunamadı", "Kullanıcı bulunamadı. Doğru ID girdiğinden emin ol.", discord.Color.red()),
                ephemeral=True
            )
            return

        oda = discord.utils.find(lambda c: STREAM_ODA_ADI.lower() in c.name.lower(), guild.channels)
        if not oda:
            await interaction.response.send_message(
                embed=mod_embed("❌ Kanal Yok", f"`{STREAM_ODA_ADI}` adında kanal bulunamadı.", discord.Color.red()),
                ephemeral=True
            )
            return
        try:
            await oda.set_permissions(uye, connect=True, speak=True, stream=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=mod_embed("❌ Yetki Yetersiz", "Botun bu kanalda izin düzenleme yetkisi yok.", discord.Color.red()),
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            embed=mod_embed("✅ Eklendi", f"{uye.mention} stream odasına eklendi.", discord.Color.green()),
            ephemeral=True
        )
        await send_log(guild, log_embed(
            "📺 Stream Odasına Kullanıcı Eklendi",
            f"**Kullanıcı:** {uye.mention} (`{uye}`)\n**İşlemi Yapan:** {interaction.user.mention}\n**Kanal:** #{oda.name}",
            discord.Color.blue()
        ), "genel", actor=interaction.user)


class StreamUyeCikarModal(discord.ui.Modal, title="Stream Odasından Kullanıcı Çıkar"):
    kullanici_id = discord.ui.TextInput(
        label="Kullanıcı ID veya @etiket",
        placeholder="Örnek: 123456789012345678",
        max_length=30,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        if not stream_yetkili_mi(interaction):
            await interaction.response.send_message(
                embed=mod_embed("❌ Yetkisiz", "Bu işlem için Streamer rolüne sahip olman gerekiyor.", discord.Color.red()),
                ephemeral=True
            )
            return
        guild = interaction.guild
        raw   = self.kullanici_id.value.strip().strip("<@!>")
        try:
            uye = guild.get_member(int(raw)) or await guild.fetch_member(int(raw))
        except Exception:
            await interaction.response.send_message(
                embed=mod_embed("❌ Bulunamadı", "Kullanıcı bulunamadı.", discord.Color.red()),
                ephemeral=True
            )
            return

        oda = discord.utils.find(lambda c: STREAM_ODA_ADI.lower() in c.name.lower(), guild.channels)
        if not oda:
            await interaction.response.send_message(
                embed=mod_embed("❌ Kanal Yok", f"`{STREAM_ODA_ADI}` adında kanal bulunamadı.", discord.Color.red()),
                ephemeral=True
            )
            return
        try:
            await oda.set_permissions(uye, overwrite=None)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=mod_embed("❌ Yetki Yetersiz", "Botun bu kanalda izin düzenleme yetkisi yok.", discord.Color.red()),
                ephemeral=True
            )
            return

        await interaction.response.send_message(
            embed=mod_embed("✅ Çıkarıldı", f"{uye.mention} stream odasından çıkarıldı.", discord.Color.orange()),
            ephemeral=True
        )
        await send_log(guild, log_embed(
            "📺 Stream Odasından Kullanıcı Çıkarıldı",
            f"**Kullanıcı:** {uye.mention} (`{uye}`)\n**İşlemi Yapan:** {interaction.user.mention}\n**Kanal:** #{oda.name}",
            discord.Color.orange()
        ), "genel", actor=interaction.user)


# ── Ana Panel View ─────────────────────────────────────────────────────────────

class StreamPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    # 1. Streamer Sorumlu Başvurusu
    @discord.ui.button(label="Streamer Sorumlu Başvurusu", emoji="👤", style=discord.ButtonStyle.primary, custom_id="stream_basvuru", row=0)
    async def basvuru(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StreamerBasvuruModal())

    # 2. Kamera Rolü
    @discord.ui.button(label="Kamera Rolü", emoji="📷", style=discord.ButtonStyle.primary, custom_id="stream_kamera_rol", row=1)
    async def kamera_rol(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        uye   = interaction.user
        rol   = discord.utils.find(lambda r: r.name == KAMERA_ROL_ADI, guild.roles)
        if not rol:
            await interaction.response.send_message(
                embed=mod_embed("❌ Rol Yok", f"`{KAMERA_ROL_ADI}` rolü sunucuda bulunamadı.", discord.Color.red()),
                ephemeral=True
            )
            return
        if rol in uye.roles:
            await uye.remove_roles(rol, reason="Stream paneli: Kamera rolü bırakıldı")
            await interaction.response.send_message(
                embed=mod_embed("📷 Kamera Rolü Alındı", "Kamera rolün kaldırıldı.", discord.Color.orange()),
                ephemeral=True
            )
        else:
            await uye.add_roles(rol, reason="Stream paneli: Kamera rolü alındı")
            await interaction.response.send_message(
                embed=mod_embed("📷 Kamera Rolü Verildi", "Kamera rolün verildi.", discord.Color.green()),
                ephemeral=True
            )

    # 3. İzin Listesi Yönetim Paneli
    @discord.ui.button(label="İzin Listesi Yönetim Paneli", emoji="📋", style=discord.ButtonStyle.primary, custom_id="stream_izin_listesi", row=1)
    async def izin_listesi(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not stream_yetkili_mi(interaction):
            await interaction.response.send_message(
                embed=mod_embed("❌ Yetkisiz", "Bu işlem için Streamer rolüne sahip olman gerekiyor.", discord.Color.red()),
                ephemeral=True
            )
            return
        embed = await stream_izin_listesi_embed(interaction.guild)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # 4. Streamer Rolü
    @discord.ui.button(label="Streamer Rolü", emoji="🖥️", style=discord.ButtonStyle.primary, custom_id="stream_streamer_rol", row=2)
    async def streamer_rol(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        uye   = interaction.user
        rol   = discord.utils.find(lambda r: r.name == STREAMER_ROL_ADI, guild.roles)
        if not rol:
            await interaction.response.send_message(
                embed=mod_embed("❌ Rol Yok", f"`{STREAMER_ROL_ADI}` rolü sunucuda bulunamadı.", discord.Color.red()),
                ephemeral=True
            )
            return
        if rol in uye.roles:
            await uye.remove_roles(rol, reason="Stream paneli: Streamer rolü bırakıldı")
            await interaction.response.send_message(
                embed=mod_embed("🖥️ Streamer Rolü Alındı", "Streamer rolün kaldırıldı.", discord.Color.orange()),
                ephemeral=True
            )
        else:
            await uye.add_roles(rol, reason="Stream paneli: Streamer rolü alındı")
            await interaction.response.send_message(
                embed=mod_embed("🖥️ Streamer Rolü Verildi", "Streamer rolün verildi.", discord.Color.green()),
                ephemeral=True
            )

    # 5. Stream Odasına Kullanıcı Ekle
    @discord.ui.button(label="Stream Odasına Kullanıcı Ekle", emoji="➕", style=discord.ButtonStyle.primary, custom_id="stream_ekle", row=2)
    async def stream_ekle(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not stream_yetkili_mi(interaction):
            await interaction.response.send_message(
                embed=mod_embed("❌ Yetkisiz", "Bu işlem için Streamer rolüne sahip olman gerekiyor.", discord.Color.red()),
                ephemeral=True
            )
            return
        await interaction.response.send_modal(StreamUyeEkleModal())

    # 6. Stream Odasından Kullanıcı Çıkar
    @discord.ui.button(label="Stream Odasından Kullanıcı Çıkar", emoji="➖", style=discord.ButtonStyle.primary, custom_id="stream_cikar", row=3)
    async def stream_cikar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not stream_yetkili_mi(interaction):
            await interaction.response.send_message(
                embed=mod_embed("❌ Yetkisiz", "Bu işlem için Streamer rolüne sahip olman gerekiyor.", discord.Color.red()),
                ephemeral=True
            )
            return
        await interaction.response.send_modal(StreamUyeCikarModal())


# ── Komut ──────────────────────────────────────────────────────────────────────

@bot.command(name="streamPanel", aliases=["spanel", "streampanel"])
@commands.has_permissions(administrator=True)
async def stream_panel(ctx):
    """Stream/Cam yönetim panelini gönderir. (Sadece yöneticiler)"""
    embed = discord.Embed(
        description=STREAM_PANEL_EMBED_DESC,
        color=discord.Color.from_str("#5865F2")
    )
    embed.set_author(name="📺 Stream & Cam Panel")
    view = StreamPanelView()
    await ctx.message.delete()
    await ctx.send(embed=embed, view=view)


# ── Sağ tık: Sesi Aç ──────────────────────────────────────────────────────────

@tree.context_menu(name="🔊 Sesi Aç")
async def sesi_ac(interaction: discord.Interaction, hedef: discord.Member):
    """Streamer rolü sahipleri sağ tık ile birinin sesini açabilir."""
    if not stream_yetkili_mi(interaction):
        await interaction.response.send_message(
            embed=mod_embed("❌ Yetkisiz", "Bu işlem için **Streamer** rolüne sahip olman gerekiyor.", discord.Color.red()),
            ephemeral=True
        )
        return
    # Kendi sesini açmaya çalışıyor ve yönetici değil
    if hedef.id == interaction.user.id and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message(
            embed=mod_embed("❌ İzin Yok", "Kendi sesini açamazsın. Bunun için yöneticiye başvur.", discord.Color.red()),
            ephemeral=True
        )
        return
    if hedef.bot:
        await interaction.response.send_message(
            embed=mod_embed("❌ Hata", "Botların sesini açamazsın.", discord.Color.red()),
            ephemeral=True
        )
        return
    if not hedef.voice or not hedef.voice.channel:
        await interaction.response.send_message(
            embed=mod_embed("❌ Ses Kanalında Değil", f"{hedef.mention} şu an bir ses kanalında değil.", discord.Color.orange()),
            ephemeral=True
        )
        return
    if not hedef.voice.mute:
        await interaction.response.send_message(
            embed=mod_embed("ℹ️ Zaten Açık", f"{hedef.mention} zaten mute'lu değil.", discord.Color.blurple()),
            ephemeral=True
        )
        return
    try:
        await hedef.edit(mute=False, reason=f"Streamer tarafından unmute: {interaction.user}")
        _stream_muted.discard((interaction.guild.id, hedef.id))
        await interaction.response.send_message(
            embed=mod_embed("🔊 Ses Açıldı", f"{hedef.mention} artık konuşabilir.", discord.Color.green()),
            ephemeral=True
        )
        await send_log(interaction.guild, log_embed(
            "🔊 Stream Unmute",
            f"**Üye:** {hedef.mention} (`{hedef}`)\n**İşlemi Yapan:** {interaction.user.mention}",
            discord.Color.green()
        ), "genel", actor=interaction.user)
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=mod_embed("❌ Yetki Yetersiz", "Botun bu üyeyi unmute etme yetkisi yok.", discord.Color.red()),
            ephemeral=True
        )


# ── Sağ tık: Sesi Kapat ───────────────────────────────────────────────────────

@tree.context_menu(name="🔇 Sesi Kapat")
async def sesi_kapat(interaction: discord.Interaction, hedef: discord.Member):
    """Streamer rolü sahipleri sağ tık ile birinin sesini kapatabilir."""
    if not stream_yetkili_mi(interaction):
        await interaction.response.send_message(
            embed=mod_embed("❌ Yetkisiz", "Bu işlem için **Streamer** rolüne sahip olman gerekiyor.", discord.Color.red()),
            ephemeral=True
        )
        return
    if hedef.bot or uye_streamer_mi(hedef):
        await interaction.response.send_message(
            embed=mod_embed("❌ İzin Yok", "Bot veya Streamer olan birini mute edemezsin.", discord.Color.red()),
            ephemeral=True
        )
        return
    if not hedef.voice or not hedef.voice.channel:
        await interaction.response.send_message(
            embed=mod_embed("❌ Ses Kanalında Değil", f"{hedef.mention} şu an bir ses kanalında değil.", discord.Color.orange()),
            ephemeral=True
        )
        return
    try:
        await hedef.edit(mute=True, reason=f"Streamer tarafından mute: {interaction.user}")
        _stream_muted.add((interaction.guild.id, hedef.id))
        await interaction.response.send_message(
            embed=mod_embed("🔇 Ses Kapatıldı", f"{hedef.mention} susturuldu.", discord.Color.orange()),
            ephemeral=True
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=mod_embed("❌ Yetki Yetersiz", "Botun bu üyeyi mute etme yetkisi yok.", discord.Color.red()),
            ephemeral=True
        )


# ══════════════════════════════════════════════════════════════════════════════

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN ortam değişkeni ayarlanmamış.")

# İki token yapışık gelirse (6 parça) sadece son 3 parçayı (yeni token) kullan
_parts = TOKEN.split(".")
if len(_parts) == 6:
    TOKEN = ".".join(_parts[3:])

# ── Process lock: aynı anda iki bot.py çalışmasını engelle ──────────────────
import fcntl as _fcntl, sys as _sys
_LOCK_PATH = "/tmp/wonkru_main_bot.lock"
_lock_file = open(_LOCK_PATH, "w")
try:
    _fcntl.flock(_lock_file, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
    print(f"[Bot] ✅ Process lock alındı (PID={os.getpid()})", flush=True)
except BlockingIOError:
    print(f"[Bot] ❌ Zaten bir instance çalışıyor — bu process kapatılıyor (PID={os.getpid()})", flush=True)
    _sys.exit(0)
# ─────────────────────────────────────────────────────────────────────────────

# ── Health check HTTP sunucusu (Railway rolling deploy sorununu çözer) ───────
def _start_health_server():
    if not os.environ.get("RAILWAY_ENVIRONMENT"):
        return
    port = int(os.environ.get("PORT", 8080))
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        def log_message(self, *args):
            pass
    server = http.server.HTTPServer(("0.0.0.0", port), _Handler)
    print(f"[Health] HTTP health server başlatıldı → port {port}", flush=True)
    server.serve_forever()

threading.Thread(target=_start_health_server, daemon=True).start()
# ─────────────────────────────────────────────────────────────────────────────

bot.run(TOKEN)
