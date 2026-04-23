import qrcode
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter


# Lob 6x4" at 300 DPI with 0.125" bleed = 1875 x 1275 px
CARD_W, CARD_H = 1875, 1275
BLEED = 38  # pixels

BRAND_NAME = "AQUA DREAM POOLS"
BRAND_PHONE = "(888) 734-7665"
BRAND_WEB = "aquadreampools.com"
BRAND_COLOR = (0, 180, 255)        # cyan-blue
BRAND_DARK = (5, 12, 35)           # near-black navy
BRAND_GOLD = (212, 175, 55)        # gold accent


def _font(size, bold=False):
    try:
        path = (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        )
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


class PostcardAgent:

    def generate_qr(self, url: str, output_path: str, size: int = 220) -> str:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color=BRAND_DARK, back_color="white").convert("RGB")
        img = img.resize((size, size), Image.LANCZOS)
        img.save(output_path)
        return output_path

    def design_front(self, render_path: str, qr_path: str, landing_url: str, address: str, output_path: str) -> str:
        card = Image.new("RGB", (CARD_W, CARD_H), BRAND_DARK)

        # ── Render image: full card background with dark gradient ────────────
        render = Image.open(render_path).convert("RGB").resize((CARD_W, CARD_H), Image.LANCZOS)
        card.paste(render, (0, 0))

        # Dark gradient overlay: strong at bottom, subtle at top
        grad = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
        draw_g = ImageDraw.Draw(grad)
        for y in range(CARD_H):
            # Bottom 55% → heavy dark; top stays lighter
            progress = max(0, (y - int(CARD_H * 0.35)) / (CARD_H * 0.65))
            alpha = int(220 * (progress ** 1.4))
            draw_g.line([(0, y), (CARD_W, y)], fill=(5, 12, 35, alpha))
        card.paste(Image.alpha_composite(render.convert("RGBA"), grad).convert("RGB"), (0, 0))

        draw = ImageDraw.Draw(card)
        cx = CARD_W // 2

        # ── TOP BAR: logo ────────────────────────────────────────────────────
        bar_h = 90
        bar = Image.new("RGBA", (CARD_W, bar_h), (5, 12, 35, 210))
        card.paste(Image.alpha_composite(card.crop((0, 0, CARD_W, bar_h)).convert("RGBA"), bar).convert("RGB"), (0, 0))

        # Wave icon (simple tilde mark) + brand name
        draw.text((56, 18), "≋", fill=BRAND_COLOR, font=_font(52, bold=True))
        draw.text((118, 22), BRAND_NAME, fill=(255, 255, 255), font=_font(38, bold=True))
        draw.text((118, 62), "Licensed • Insured • 5-Star Rated", fill=(180, 200, 220), font=_font(22))

        # ── BOTTOM PANEL: address + CTA + QR ────────────────────────────────
        panel_top = int(CARD_H * 0.60)
        panel_h = CARD_H - panel_top

        # "YOUR POOL IS WAITING" headline
        y = panel_top + 20
        draw.text((cx, y), "YOUR POOL IS WAITING,", fill=(255, 255, 255), font=_font(58, bold=True), anchor="mt")
        y += 70

        # Address in cyan
        address_short = address.split(",")[0].upper()
        draw.text((cx, y), address_short, fill=BRAND_COLOR, font=_font(48, bold=True), anchor="mt")
        y += 60

        # Divider line
        line_y = y + 10
        draw.line([(120, line_y), (CARD_W - 120, line_y)], fill=BRAND_GOLD, width=2)
        y = line_y + 24

        # Price teaser + CTA
        draw.text((cx - 200, y), "From $415/mo  •  Free Quote", fill=(220, 235, 255), font=_font(30), anchor="lt")
        y += 46

        # Bottom row: phone left, QR right
        phone_y = y + 10
        draw.text((120, phone_y), "📞  " + BRAND_PHONE, fill=(255, 255, 255), font=_font(34, bold=True))
        draw.text((120, phone_y + 44), BRAND_WEB, fill=(130, 180, 210), font=_font(26))

        # QR code — right side
        qr_size = 200
        qr_img = Image.open(qr_path).convert("RGBA")
        # White rounded background for QR
        qr_bg = Image.new("RGB", (qr_size + 16, qr_size + 36), (255, 255, 255))
        qr_bg.paste(qr_img.convert("RGB").resize((qr_size, qr_size), Image.LANCZOS), (8, 4))
        qr_draw = ImageDraw.Draw(qr_bg)
        qr_draw.text((qr_size // 2 + 8, qr_size + 10), "SCAN ME", fill=BRAND_DARK,
                     font=_font(18, bold=True), anchor="mt")
        qr_x = CARD_W - qr_size - 80
        qr_y = CARD_H - qr_size - 60
        card.paste(qr_bg, (qr_x, qr_y))

        # ── GOLD ACCENT BAR at very bottom ───────────────────────────────────
        draw.rectangle([0, CARD_H - 10, CARD_W, CARD_H], fill=BRAND_GOLD)

        card.save(output_path, "JPEG", quality=98, dpi=(300, 300))
        return output_path

    def design_back(self, address: str, output_path: str) -> str:
        card = Image.new("RGB", (CARD_W, CARD_H), (250, 252, 255))
        draw = ImageDraw.Draw(card)

        # Left half: message
        mid = CARD_W // 2

        # Brand header block
        draw.rectangle([0, 0, mid - 1, 110], fill=BRAND_DARK)
        draw.text((56, 18), "≋", fill=BRAND_COLOR, font=_font(52, bold=True))
        draw.text((118, 22), BRAND_NAME, fill=(255, 255, 255), font=_font(32, bold=True))
        draw.text((118, 62), BRAND_PHONE, fill=BRAND_COLOR, font=_font(26))

        # Message body
        lines = [
            ("We scanned your neighborhood", 30),
            ("and noticed your home at", 30),
            (address.split(",")[0], 32, True),
            ("could look even better", 30),
            ("with a backyard pool.", 30),
            ("", 16),
            ("Scan the QR code on the", 26),
            ("other side to see YOUR", 26),
            ("home with a pool — and", 26),
            ("get a FREE custom quote.", 26),
            ("", 16),
            ("No obligation. 24hr response.", 24),
        ]
        y = 140
        for item in lines:
            text = item[0]
            size = item[1]
            bold = len(item) > 2 and item[2]
            color = BRAND_COLOR if bold else (30, 40, 60)
            draw.text((56, y), text, fill=color, font=_font(size, bold=bold))
            y += size + 10

        # Gold accent
        draw.rectangle([0, CARD_H - 10, mid - 1, CARD_H], fill=BRAND_GOLD)

        # Vertical divider
        draw.line([(mid, 30), (mid, CARD_H - 30)], fill=(200, 210, 225), width=2)

        # Right half: standard USPS address area
        draw.text((mid + 40, 50), "RETURN SERVICE REQUESTED", fill=(150, 160, 175), font=_font(20))

        # Stamp box
        stamp_x, stamp_y = CARD_W - 200, 40
        draw.rectangle([stamp_x, stamp_y, stamp_x + 140, stamp_y + 110],
                       outline=(180, 190, 205), width=2)
        draw.text((stamp_x + 70, stamp_y + 55), "STAMP", fill=(200, 210, 220),
                  font=_font(22, bold=True), anchor="mm")

        # Address lines
        draw.text((mid + 40, 240), "TO:", fill=(120, 130, 145), font=_font(24, bold=True))
        for i in range(3):
            ly = 290 + i * 60
            draw.line([(mid + 40, ly), (CARD_W - 60, ly)], fill=(190, 200, 215), width=1)

        # Indicia / barcode placeholder
        draw.rectangle([mid + 40, CARD_H - 120, CARD_W - 60, CARD_H - 40],
                       outline=(200, 210, 225), width=1)
        draw.text((mid + (mid // 2), CARD_H - 80), "PRESORTED STANDARD", fill=(180, 190, 205),
                  font=_font(18), anchor="mm")

        card.save(output_path, "JPEG", quality=98, dpi=(300, 300))
        return output_path
