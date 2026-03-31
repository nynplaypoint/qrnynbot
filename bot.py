import os
import qrcode
import barcode
from barcode.writer import ImageWriter
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import (
    RoundedModuleDrawer, CircleModuleDrawer, SquareModuleDrawer,
    GappedSquareModuleDrawer, HorizontalBarsDrawer, VerticalBarsDrawer
)
from qrcode.image.styles.colormasks import SolidFillColorMask
from io import BytesIO
from PIL import Image
import fpdf
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, ConversationHandler, filters
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

COLOR_PRESETS = {
    "classic": ("000000", "ffffff"),
    "blue":    ("003f8f", "e8f0ff"),
    "red":     ("8f0000", "fff0f0"),
    "green":   ("006400", "f0fff0"),
    "purple":  ("4b0082", "f5f0ff"),
    "orange":  ("b35400", "fff5e8"),
    "dark":    ("ffffff", "222222"),
    "gold":    ("8b6914", "fffde8"),
}

qr_store = {}


def truncate(text: str, limit: int = 100) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def hex_to_rgb(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def store_text(text: str) -> str:
    import hashlib
    key = hashlib.md5(text.encode()).hexdigest()[:8]
    qr_store[key] = text
    return key


def make_qr_image(text: str, style="rounded", color_preset="classic", logo_bytes=None) -> BytesIO:
    fg, bg = COLOR_PRESETS.get(color_preset, ("000000", "ffffff"))
    fg_rgb = hex_to_rgb(fg) + (255,)
    bg_rgb = hex_to_rgb(bg) + (255,)

    drawer = STYLES.get(style, RoundedModuleDrawer())
    color_mask = SolidFillColorMask(back_color=bg_rgb, front_color=fg_rgb)

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=12,
        border=4,
    )
    qr.add_data(text)
    qr.make(fit=True)

    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=drawer,
        color_mask=color_mask,
    ).convert("RGBA")

    if logo_bytes:
        logo = Image.open(logo_bytes).convert("RGBA")
        qr_w, qr_h = img.size
        logo_size = int(qr_w * 0.22)
        logo = logo.resize((logo_size, logo_size), Image.LANCZOS)
        pad = 10
        bg_block = Image.new("RGBA", (logo_size + pad * 2, logo_size + pad * 2), (255, 255, 255, 255))
        pos_x = (qr_w - bg_block.width) // 2
        pos_y = (qr_h - bg_block.height) // 2
        img.paste(bg_block, (pos_x, pos_y))
        img.paste(logo, (pos_x + pad, pos_y + pad), logo)

    bio = BytesIO()
    bio.name = "qr.png"
    img.save(bio, format="PNG")
    bio.seek(0)
    return bio


def make_qr_pdf(text: str, style="rounded", color_preset="classic", logo_bytes=None) -> BytesIO:
    import tempfile, os as _os
    qr_bio = make_qr_image(text, style, color_preset, logo_bytes)
    img = Image.open(qr_bio)
    tmp = BytesIO()
    img.save(tmp, format="PNG")
    tmp.seek(0)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(tmp.read())
        tmp_path = f.name

    pdf = fpdf.FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    pdf.image(tmp_path, x=55, y=20, w=100)
    _os.unlink(tmp_path)

    caption = truncate(text, 120)
    pdf.set_xy(10, 130)
    pdf.multi_cell(0, 10, caption, align="C")

    pdf_bytes = pdf.output(dest="S")
    if isinstance(pdf_bytes, str):
        pdf_bytes = pdf_bytes.encode("latin-1")

    bio = BytesIO(pdf_bytes)
    bio.name = "qr.pdf"
    bio.seek(0)
    return bio


def style_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("◼ Square",  callback_data="style:square:classic"),
            InlineKeyboardButton("● Rounded", callback_data="style:rounded:classic"),
            InlineKeyboardButton("○ Circle",  callback_data="style:circle:classic"),
        ],
        [
            InlineKeyboardButton("▦ Gapped",  callback_data="style:gapped:classic"),
            InlineKeyboardButton("≡ H-Bars",  callback_data="style:hbars:classic"),
            InlineKeyboardButton("║ V-Bars",  callback_data="style:vbars:classic"),
        ],
    ])


def color_keyboard(style: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬛ Classic", callback_data=f"color:{style}:classic"),
            InlineKeyboardButton("🔵 Blue",    callback_data=f"color:{style}:blue"),
            InlineKeyboardButton("🔴 Red",     callback_data=f"color:{style}:red"),
            InlineKeyboardButton("🟢 Green",   callback_data=f"color:{style}:green"),
        ],
        [
            InlineKeyboardButton("🟣 Purple",  callback_data=f"color:{style}:purple"),
            InlineKeyboardButton("🟠 Orange",  callback_data=f"color:{style}:orange"),
            InlineKeyboardButton("🌑 Dark",    callback_data=f"color:{style}:dark"),
            InlineKeyboardButton("🟡 Gold",    callback_data=f"color:{style}:gold"),
        ],
    ])


def action_keyboard(style: str, color: str, key: str):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🖼 Add Logo", callback_data=f"logo:{style}:{color}:{key}"),
            InlineKeyboardButton("📄 Get PDF",  callback_data=f"pdf:{style}:{color}:{key}"),
        ],
        [
            InlineKeyboardButton("🔄 Change Style", callback_data=f"restart:{key}"),
        ],
    ])


# ---------- /start ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *QR & Barcode Bot*\n\n"
        "Just *type any text* to generate a QR code!\n\n"
        "Commands:\n"
        "/qr <text> — QR code with designer options\n"
        "/bar <text> — Barcode\n"
        "/bar t1 | t2 | t3 — Multiple barcodes\n\n"
        "✨ Supports: styles, colors, logo overlay, PDF export",
        parse_mode="Markdown"
    )


# ---------- plain text → QR ----------
async def text_to_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text:
        return
    store_text(text)
    context.user_data["last_text"] = text
    await update.message.reply_text(
        "🎨 Pick a *style*:",
        parse_mode="Markdown",
        reply_markup=style_keyboard()
    )


# ---------- /qr ----------
async def qr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /qr <text>")
    text = " ".join(context.args)
    store_text(text)
    context.user_data["last_text"] = text
    await update.message.reply_text(
        "🎨 Pick a *style*:",
        parse_mode="Markdown",
        reply_markup=style_keyboard()
    )


# ---------- callbacks ----------
async def style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, style, _ = query.data.split(":", 2)
    await query.edit_message_text(
        f"✅ Style: *{style}*\n\nNow pick a color:",
        parse_mode="Markdown",
        reply_markup=color_keyboard(style)
    )


async def color_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Generating...")
    _, style, color = query.data.split(":", 2)

    text = context.user_data.get("last_text", "")
    if not text:
        return await query.edit_message_text("❌ Text expired. Send your text again.")

    key = store_text(text)
    bio = make_qr_image(text, style, color)
    await query.message.reply_photo(
        bio,
        caption=truncate(text),
        reply_markup=action_keyboard(style, color, key)
    )
    await query.delete_message()


async def pdf_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Generating PDF...")
    _, style, color, key = query.data.split(":", 3)
    text = qr_store.get(key, "")
    if not text:
        return await query.message.reply_text("❌ Text expired. Send your text again.")
    bio = make_qr_pdf(text, style, color)
    await query.message.reply_document(bio, caption="📄 Your QR as PDF")


async def logo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, style, color, key = query.data.split(":", 3)
    context.user_data["logo_style"] = style
    context.user_data["logo_color"] = color
    context.user_data["logo_key"]   = key
    await query.message.reply_text("📎 Send your logo image (PNG, square recommended):")
    return WAITING_LOGO


async def restart_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    text = qr_store.get(key, "")
    if text:
        context.user_data["last_text"] = text
    await query.edit_message_text(
        "🎨 Pick a *style*:",
        parse_mode="Markdown",
        reply_markup=style_keyboard()
    )


async def logo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    style = context.user_data.get("logo_style", "rounded")
    color = context.user_data.get("logo_color", "classic")
    key   = context.user_data.get("logo_key", "")
    text  = qr_store.get(key, "")

    if not text:
        await update.message.reply_text("❌ Text expired. Send your text again.")
        return ConversationHandler.END

    file_obj = (update.message.photo[-1] if update.message.photo else None) or update.message.document
    if not file_obj:
        await update.message.reply_text("Please send an image.")
        return WAITING_LOGO

    tg_file = await file_obj.get_file()
    logo_bio = BytesIO()
    await tg_file.download_to_memory(logo_bio)
    logo_bio.seek(0)

    bio = make_qr_image(text, style, color, logo_bytes=logo_bio)
    await update.message.reply_photo(
        bio,
        caption=truncate(text),
        reply_markup=action_keyboard(style, color, key)
    )
    return ConversationHandler.END


# ---------- /bar ----------
async def bar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /bar <text> or /bar t1 | t2 | t3")
    raw = " ".join(context.args)
    items = [t.strip() for t in raw.split("|") if t.strip()]
    await update.message.reply_text(f"Generating {len(items)} barcode(s)...")
    for text in items:
        try:
            code128 = barcode.get("code128", text, writer=ImageWriter())
            bio = BytesIO()
            bio.name = "barcode.png"
            code128.write(bio, options={"write_text": True})
            bio.seek(0)
            await update.message.reply_photo(bio, caption=truncate(text))
        except Exception as e:
            await update.message.reply_text(f"❌ Failed for '{text}': {e}")


# ---------- main ----------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    logo_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(logo_callback, pattern="^logo:")],
        states={WAITING_LOGO: [MessageHandler(filters.PHOTO | filters.Document.IMAGE, logo_received)]},
        fallbacks=[],
        per_message=False,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("qr", qr_command))
    app.add_handler(CommandHandler("bar", bar_command))
    app.add_handler(logo_conv)
    app.add_handler(CallbackQueryHandler(style_callback,   pattern="^style:"))
    app.add_handler(CallbackQueryHandler(color_callback,   pattern="^color:"))
    app.add_handler(CallbackQueryHandler(pdf_callback,     pattern="^pdf:"))
    app.add_handler(CallbackQueryHandler(restart_callback, pattern="^restart:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_to_qr))

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
