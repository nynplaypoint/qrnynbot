import os
import qrcode
import barcode
from barcode.writer import ImageWriter
from io import BytesIO
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("TOKEN environment variable not set.")


# ---------- /start ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to QR & Barcode Bot!\n\n"
        "Commands:\n"
        "/qr <text> — Generate a QR code\n"
        "/qr <text1> | <text2> — Generate multiple QR codes\n\n"
        "/bar <text> — Generate a barcode\n"
        "/bar <text1> | <text2> — Generate multiple barcodes"
    )


# ---------- /qr ----------
async def qr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "Usage:\n/qr Hello World\n/qr Text1 | Text2 | Text3"
        )

    raw = " ".join(context.args)
    items = [t.strip() for t in raw.split("|") if t.strip()]

    await update.message.reply_text(f"Generating {len(items)} QR code(s)...")

    for text in items:
        try:
            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=10,
                border=4,
            )
            qr.add_data(text)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            bio = BytesIO()
            bio.name = "qr.png"
            img.save(bio, format="PNG")
            bio.seek(0)

            await update.message.reply_photo(bio, caption=f"QR: {text}")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed for '{text}': {e}")


# ---------- /bar ----------
async def bar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text(
            "Usage:\n/bar HelloWorld\n/bar Text1 | Text2 | Text3"
        )

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

            await update.message.reply_photo(bio, caption=f"Barcode: {text}")
        except Exception as e:
            await update.message.reply_text(f"❌ Failed for '{text}': {e}")


# ---------- main ----------
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("qr", qr_command))
    app.add_handler(CommandHandler("bar", bar_command))
    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
