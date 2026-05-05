"""Stat banner resmi oluşturucu — Pillow tabanlı"""
import io
import aiohttp
from PIL import Image, ImageDraw, ImageFont

FONT_BOLD    = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

BG     = (30,  31,  34)
PANEL  = (43,  45,  49)
ACCENT = (88,  101, 242)
WHITE  = (255, 255, 255)
GRAY   = (163, 166, 170)
GOLD   = (255, 202,  57)
GREEN  = ( 87, 242, 135)
LINE   = (60,  62,  66)

W, H = 1200, 310

def font(size, bold=False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)

def rounded_rect(draw, xy, radius, color):
    draw.rounded_rectangle(xy, radius=radius, fill=color)

def circle_mask(size):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
    return mask

async def fetch_avatar(url: str, size: int) -> Image.Image:
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            data = await r.read()
    av = Image.open(io.BytesIO(data)).convert("RGBA").resize((size, size), Image.LANCZOS)
    mask = circle_mask(size)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(av, (0, 0), mask)
    return out

async def build_banner(
    avatar_url: str,
    display_name: str,
    username: str,
    joined_at: str,
    created_at: str,
    toplam_ses: str,
    toplam_mesaj: int,
    toplam_stream: str,
    top_msg: list[tuple[str, int]],
    top_ses: list[tuple[str, str]],
) -> io.BytesIO:

    img  = Image.new("RGBA", (W, H), BG)
    draw = ImageDraw.Draw(img)

    PAD = 20
    AV  = 96

    # ── Avatar ─────────────────────────────────────────────────────────
    try:
        av_img = await fetch_avatar(avatar_url, AV)
        img.paste(av_img, (PAD, PAD), av_img)
    except Exception:
        draw.ellipse([PAD, PAD, PAD + AV, PAD + AV], fill=ACCENT)

    # Blurple sol kenar çizgisi
    draw.rectangle([0, 0, 5, H], fill=ACCENT)

    # ── İsim & Tarihler ────────────────────────────────────────────────
    tx = PAD + AV + 16
    draw.text((tx, PAD),      display_name,          font=font(22, True), fill=WHITE)
    draw.text((tx, PAD + 30), f"@{username}",        font=font(14),       fill=GRAY)
    draw.line([(tx, PAD + 54), (tx + 190, PAD + 54)], fill=LINE, width=1)
    draw.text((tx, PAD + 62), f"Hesap:    {created_at}", font=font(13), fill=GRAY)
    draw.text((tx, PAD + 82), f"Katılım: {joined_at}",  font=font(13), fill=GRAY)

    # ── Toplam Bilgiler paneli ─────────────────────────────────────────
    MX, MY, MW = 305, PAD, 240
    MH = H - PAD * 2
    rounded_rect(draw, [MX, MY, MX + MW, MY + MH], 10, PANEL)
    draw.text((MX + 14, MY + 14), "Toplam Bilgiler", font=font(14, True), fill=WHITE)
    draw.line([(MX + 10, MY + 36), (MX + MW - 10, MY + 36)], fill=LINE, width=1)

    rows = [
        ("🔊 Ses Süresi",  toplam_ses,         ACCENT),
        ("💬 Mesaj Sayısı", str(toplam_mesaj),  WHITE),
        ("🎥 Yayın Süresi", toplam_stream,      GOLD),
    ]
    for i, (lbl, val, col) in enumerate(rows):
        y = MY + 46 + i * 70
        draw.text((MX + 14, y),      lbl, font=font(12),       fill=GRAY)
        draw.text((MX + 14, y + 18), val, font=font(24, True), fill=col)

    # ── En Çok Mesaj paneli ────────────────────────────────────────────
    R1X, R1Y, R1W = 560, PAD, 295
    R1H = H - PAD * 2
    rounded_rect(draw, [R1X, R1Y, R1X + R1W, R1Y + R1H], 10, PANEL)
    draw.text((R1X + 14, R1Y + 14), "En Çok Mesaj Atılan Kanallar", font=font(14, True), fill=WHITE)
    draw.line([(R1X + 10, R1Y + 36), (R1X + R1W - 10, R1Y + 36)], fill=LINE, width=1)

    for i, (kanal, sayi) in enumerate(top_msg[:4]):
        y = R1Y + 46 + i * 54
        draw.text((R1X + 14, y),      f"#{kanal}"[:30],  font=font(13, True), fill=WHITE)
        draw.text((R1X + 14, y + 20), f"{sayi} mesaj",   font=font(12),       fill=GRAY)

    # ── En Çok Seste Vakit paneli ──────────────────────────────────────
    R2X, R2Y, R2W = 868, PAD, 312
    R2H = H - PAD * 2
    rounded_rect(draw, [R2X, R2Y, R2X + R2W, R2Y + R2H], 10, PANEL)
    draw.text((R2X + 14, R2Y + 14), "En Çok Seste Vakit Geçirilen", font=font(14, True), fill=WHITE)
    draw.line([(R2X + 10, R2Y + 36), (R2X + R2W - 10, R2Y + 36)], fill=LINE, width=1)

    for i, (kanal, sure) in enumerate(top_ses[:4]):
        y = R2Y + 46 + i * 54
        draw.text((R2X + 14, y),      kanal[:30], font=font(13, True), fill=WHITE)
        draw.text((R2X + 14, y + 20), sure,       font=font(12),       fill=GREEN)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG", quality=95)
    buf.seek(0)
    return buf
