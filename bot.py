import os
import hashlib
from io import BytesIO

import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import (
    RoundedModuleDrawer, CircleModuleDrawer, SquareModuleDrawer,
    GappedSquareModuleDrawer, HorizontalBarsDrawer, VerticalBarsDrawer,
)

import barcode
from barcode.writer import ImageWriter

from PIL import Image, ImageDraw
import fpdf

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters,
)

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("TOKEN environment variable not set.")

WAITING_LOGO = 1

STYLES = {
    "square":  SquareModuleDrawer(),
    "rounded": RoundedModuleDrawer(),
    "circle":  CircleModuleDrawer(),
    "gapped":  GappedSquareModuleDrawer(),
    "hbars":   HorizontalBarsDrawer(),
    "vbars":   VerticalBarsDrawer(),
}

# fg, bg as hex strings
COLORS = {
    "classic": ("#000000", "#ffffff"),
    "blue":    ("#003f8f", "#e8f0ff"),
    "red":     ("#8f0000", "#fff0f0"),
    "green":   ("#006400", "#f0fff0"),
    "purple":  ("#4b0082", "#f5f0ff"),
    "orange":  ("#b35400", "#fff5e8"),
    "dark":    ("#ffffff", "#222222"),
    "gold":    ("#8b6914", "#fffde8"),
}

store: dict[str, str] = {}


def save(text: str) -> str:
    key = hashlib.md5(text.encode()).hexdigest()[:10]
    store[key] = text
    return key


def load(key: str) -> str:
    return store.get(key, "")


def cap(text: str, n: int = 100) -> str:
    return text if len(text) <= n else text[:n] + "..."


def colorize(img: Image.Image, fg_hex: str, bg_hex: str) -> Image.Image:
    """Replace black pixels with fg color and white pixels with bg color."""
    img = img.convert("RGB")
    fg = tuple(int(fg_hex.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
    bg = tuple(int(bg_hex.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
    pixels = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b = pixels[x, y]
            # dark pixel = module
            if r < 128:
                pixels[x, y] = fg
            else:
                pixels[x, y] = bg
    return img


def build_qr_plain(text: str) -> BytesIO:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=12,
        border=4,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    bio = BytesIO()
    bio.name = "qr.png"
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio


def build_qr_styled(text: str, style: str, color: str, logo: BytesIO | None = None) -> BytesIO:
    fg_hex, bg_hex = COLORS.get(color, ("#000000", "#ffffff"))
    drawer = STYLES.get(style, SquareModuleDrawer())

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=12,
        border=4,
    )
    qr.add_data(text)
    qr.make(fit=True)

    # Generate with shape style but plain black/white first
    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=drawer,
    ).convert("RGB")

    # Now recolor manually — this always works
    img = colorize(img, fg_hex, bg_hex)

    if logo:
        img_rgba = img.convert("RGBA")
        overlay = Image.open(logo).convert("RGBA")
        qw, qh = img_rgba.size
        sz = int(qw * 0.22)
        overlay = overlay.resize((sz, sz), Image.LANCZOS)
        pad = 10
        bg_block = Image.new("RGBA", (sz + pad*2, sz + pad*2), (255, 255, 255, 255))
        px = (qw - bg_block.width) // 2
        py = (qh - bg_block.height) // 2
        img_rgba.paste(bg_block, (px, py))
        img_rgba.paste(overlay, (px + pad, py + pad), overlay)
        img = img_rgba.convert("RGB")

    bio = BytesIO()
    bio.name = "qr.png"
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio


def build_pdf(text: str, style: str, color: str) -> BytesIO:
    import tempfile, os as _os
    qr_bio = build_qr_styled(text, style, color)
    pil = Image.open(qr_bio)
    tmp = BytesIO()
    pil.save(tmp, format="PNG")
    tmp.seek(0)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(tmp.read())
        path = f.name

    pdf = fpdf.FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.image(path, x=55, y=20, w=100)
    _os.unlink(path)
    pdf.set_xy(10, 130)
    pdf.multi_cell(0, 10, cap(text, 120), align="C")

    raw = pdf.output(dest="S")
    if isinstance(raw, str):
        raw = raw.encode("latin-1")
    bio = BytesIO(raw)
    bio.name = "qr.pdf"
    bio.seek(0)
    return bio


def kb_style():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("◼ Square",  callback_data="ST:square"),
            InlineKeyboardButton("● Rounded", callback_data="ST:rounded"),
            InlineKeyboardButton("○ Circle",  callback_data="ST:circle"),
        ],
        [
            InlineKeyboardButton("▦ Gapped",  callback_data="ST:gapped"),
            InlineKeyboardButton("≡ H-Bars",  callback_data="ST:hbars"),
            InlineKeyboardButton("║ V-Bars",  callback_data="ST:vbars"),
        ],
    ])


def kb_color(style: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬛ Classic", callback_data=f"CL:{style}:classic"),
            InlineKeyboardButton("🔵 Blue",    callback_data=f"CL:{style}:blue"),
            InlineKeyboardButton("🔴 Red",     callback_data=f"CL:{style}:red"),
            InlineKeyboardButton("🟢 Green",   callback_data=f"CL:{style}:green"),
        ],
        [
            InlineKeyboardButton("🟣 Purple",  callback_data=f"CL:{style}:purple"),
            InlineKeyboardButton("🟠 Orange",  callback_data=f"CL:{style}:orange"),
            InlineKeyboardButton("🌑 Dark",    callback_data=f"CL:{style}:dark"),
            InlineKeyboardButton("🟡 Gold",    callback_data=f"CL:{style}:gold"),
        ],
    ])


def kb_actions(style: str, color: str, key: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🖼 Add Logo",     callback_data=f"LG:{style}:{color}:{key}"),
            InlineKeyboardButton("📄 Get PDF",      callback_data=f"PD:{style}:{color}:{key}"),
        ],
        [
            InlineKeyboardButton("🔄 Change Style", callback_data=f"RS:{key}"),
        ],
    ])


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *QR & Barcode Bot*\n\n"
        "Just type any text → instant black & white QR\n\n"
        "Commands:\n"
        "/qr <text> — plain QR\n"
        "/qrc <text> — styled QR (pick shape + color)\n"
        "/bar <text> — barcode\n"
        "/bar t1 | t2 — multiple barcodes",
        parse_mode="Markdown",
    )


async def cmd_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args).strip()
    if not text:
        return await update.message.reply_text("Usage: /qr <text>")
    bio = build_qr_plain(text)
    await update.message.reply_photo(bio, caption=cap(text))


async def cmd_qrc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args).strip()
    if not text:
        return await update.message.reply_text("Usage: /qrc <text>")
    save(text)
    context.user_data["text"] = text
    await update.message.reply_text("🎨 Pick a style:", reply_markup=kb_style())


async def msg_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        return
    bio = build_qr_plain(text)
    await update.message.reply_photo(bio, caption=cap(text))


async def cb_style(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    style = q.data.split(":")[1]
    await q.edit_message_text(
        f"✅ Style: *{style}*\n\nPick a color:",
        parse_mode="Markdown",
        reply_markup=kb_color(style),
    )


async def cb_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Generating...")
    _, style, color = q.data.split(":")
    text = context.user_data.get("text", "")
    if not text:
        return await q.edit_message_text("❌ Session expired. Use /qrc <text> again.")
    key = save(text)
    bio = build_qr_styled(text, style, color)
    await q.message.reply_photo(bio, caption=cap(text), reply_markup=kb_actions(style, color, key))
    await q.delete_message()


async def cb_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Generating PDF...")
    _, style, color, key = q.data.split(":", 3)
    text = load(key)
    if not text:
        return await q.message.reply_text("❌ Session expired. Use /qrc <text> again.")
    bio = build_pdf(text, style, color)
    await q.message.reply_document(bio, caption="📄 QR as PDF")


async def cb_logo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, style, color, key = q.data.split(":", 3)
    context.user_data["logo_style"] = style
    context.user_data["logo_color"] = color
    context.user_data["logo_key"]   = key
    await q.message.reply_text("📎 Send your logo image (PNG recommended):")
    return WAITING_LOGO


async def cb_restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    key = q.data.split(":", 1)[1]
    text = load(key)
    if text:
        context.user_data["text"] = text
    await q.edit_message_text("🎨 Pick a style:", reply_markup=kb_style())


async def logo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    style = context.user_data.get("logo_style", "square")
    color = context.user_data.get("logo_color", "classic")
    key   = context.user_data.get("logo_key", "")
    text  = load(key)
    if not text:
        await update.message.reply_text("❌ Session expired. Use /qrc <text> again.")
        return ConversationHandler.END

    file_obj = (update.message.photo[-1] if update.message.photo else None) or update.message.document
    if not file_obj:
        await update.message.reply_text("Please send an image file.")
        return WAITING_LOGO

    tg_file = await file_obj.get_file()
    logo_bio = BytesIO()
    await tg_file.download_to_memory(logo_bio)
    logo_bio.seek(0)

    bio = build_qr_styled(text, style, color, logo=logo_bio)
    await update.message.reply_photo(bio, caption=cap(text), reply_markup=kb_actions(style, color, key))
    return ConversationHandler.END


async def cmd_bar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /bar <text> or /bar t1 | t2 | t3")
    raw   = " ".join(context.args)
    items = [t.strip() for t in raw.split("|") if t.strip()]
    if len(items) > 1:
        await update.message.reply_text(f"Generating {len(items)} barcodes...")
    for text in items:
        try:
            bc  = barcode.get("code128", text, writer=ImageWriter())
            bio = BytesIO()
            bio.name = "barcode.png"
            bc.write(bio, options={"write_text": True})
            bio.seek(0)
            await update.message.reply_photo(bio, caption=cap(text))
        except Exception as e:
            await update.message.reply_text(f"❌ Failed for '{text}': {e}")


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    logo_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_logo, pattern="^LG:")],
        states={WAITING_LOGO: [MessageHandler(filters.PHOTO | filters.Document.IMAGE, logo_received)]},
        fallbacks=[],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("qr",    cmd_qr))
    app.add_handler(CommandHandler("qrc",   cmd_qrc))
    app.add_handler(CommandHandler("bar",   cmd_bar))
    app.add_handler(logo_conv)
    app.add_handler(CallbackQueryHandler(cb_style,   pattern="^ST:"))
    app.add_handler(CallbackQueryHandler(cb_color,   pattern="^CL:"))
    app.add_handler(CallbackQueryHandler(cb_pdf,     pattern="^PD:"))
    app.add_handler(CallbackQueryHandler(cb_restart, pattern="^RS:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_text))

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
