import os
import qrcode
from io import BytesIO
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import barcode
from barcode.writer import ImageWriter

TOKEN = os.getenv("TOKEN") or "YOUR_BOT_TOKEN"

# ---------- QR GENERATOR ----------
async def qr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        return await update.message.reply_text("Usage: /qr text1\\stext2\\stext3")

    texts = [t.strip() for t in text.split("\\s") if t.strip()]

    for t in texts:
        qr = qrcode.QRCode(version=None, box_size=10, border=4)
        qr.add_data(t)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        bio = BytesIO()
        bio.name = "qr.png"
        img.save(bio, "PNG")
        bio.seek(0)
        await update.message.reply_document(bio, caption=t)

# ---------- BARCODE GENERATOR ----------
async def bar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = " ".join(context.args)
    if not text:
        return await update.message.reply_text("Usage: /bar text1\\stext2\\stext3")

    texts = [t.strip() for t in text.split("\\s") if t.strip()]

    for t in texts:
        code128 = barcode.get("code128", t, writer=ImageWriter())
        bio = BytesIO()
        bio.name = "barcode.png"
        code128.write(bio)
        bio.seek(0)
        await update.message.reply_document(bio, caption=t)

# ---------- MAIN ----------
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("qr", qr_command))
app.add_handler(CommandHandler("bar", bar_command))

print("Batch QR + Barcode Bot running...")
app.run_polling()
