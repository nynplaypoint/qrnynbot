"""
bot_test.py  —  Pydroid 3 testing version
Install in Pydroid terminal:
  pip install python-telegram-bot==21.9 qrcode[pil] python-barcode pillow fpdf2
"""

import os, hashlib
from io import BytesIO

import qrcode
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import (
    RoundedModuleDrawer, CircleModuleDrawer, SquareModuleDrawer,
    GappedSquareModuleDrawer, HorizontalBarsDrawer, VerticalBarsDrawer,
)
import barcode
from barcode.writer import ImageWriter
from PIL import Image
import fpdf

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
)

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("Set TOKEN env var in Railway.")

# ── data ─────────────────────────────────────────────────────────────
STYLES = {
    "square":  SquareModuleDrawer(),
    "rounded": RoundedModuleDrawer(),
    "circle":  CircleModuleDrawer(),
    "gapped":  GappedSquareModuleDrawer(),
    "hbars":   HorizontalBarsDrawer(),
    "vbars":   VerticalBarsDrawer(),
}
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
store = {}   # key → text
# user_data keys we use:
#   mode        : "qr" | "bar"
#   text        : the string to encode
#   tkey        : store key
#   step        : "style" | "color" | "hex_fg" | "hex_bg" | "logo"
#   style       : chosen style name
#   fg / bg     : hex strings
#   custom_fg   : temp storage while waiting for bg

# ── helpers ───────────────────────────────────────────────────────────
def stash(text):
    k = hashlib.md5(text.encode()).hexdigest()[:10]
    store[k] = text
    return k

def cap(t, n=100):
    return t if len(t) <= n else t[:n] + "..."

def valid_hex(h):
    h = h.lstrip("#")
    return len(h) == 6 and all(c in "0123456789abcdefABCDEF" for c in h)

def to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def recolor(img, fg, bg):
    img = img.convert("RGB")
    fgc, bgc = to_rgb(fg), to_rgb(bg)
    px = img.load()
    for y in range(img.height):
        for x in range(img.width):
            r,g,b = px[x,y]
            px[x,y] = fgc if r < 128 else bgc
    return img

# ── image builders ────────────────────────────────────────────────────
def qr_plain(text):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H,
                       box_size=12, border=4)
    qr.add_data(text); qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    b = BytesIO(); b.name = "qr.png"; img.save(b,"PNG"); b.seek(0); return b

def qr_styled(text, style, fg, bg, logo_b=None):
    dr = STYLES.get(style, SquareModuleDrawer())
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H,
                       box_size=12, border=4)
    qr.add_data(text); qr.make(fit=True)
    img = qr.make_image(image_factory=StyledPilImage,
                        module_drawer=dr).convert("RGB")
    img = recolor(img, fg, bg)
    if logo_b:
        img = img.convert("RGBA")
        logo = Image.open(logo_b).convert("RGBA")
        sz = int(img.width * 0.22); logo = logo.resize((sz,sz), Image.LANCZOS)
        pad=10; blk=Image.new("RGBA",(sz+pad*2,sz+pad*2),(255,255,255,255))
        px=(img.width-blk.width)//2; py=(img.height-blk.height)//2
        img.paste(blk,(px,py)); img.paste(logo,(px+pad,py+pad),logo)
        img=img.convert("RGB")
    b=BytesIO(); b.name="qr.png"; img.save(b,"PNG"); b.seek(0); return b

def bar_plain(text):
    bc=barcode.get("code128",text,writer=ImageWriter())
    b=BytesIO(); b.name="bar.png"
    bc.write(b,options={"write_text":True,"module_height":15.0})
    b.seek(0); return b

def bar_styled(text, fg, bg):
    bc=barcode.get("code128",text,writer=ImageWriter())
    b=BytesIO()
    bc.write(b,options={"write_text":True,"module_height":15.0})
    b.seek(0)
    img=Image.open(b).convert("RGB")
    img=recolor(img,fg,bg)
    out=BytesIO(); out.name="bar.png"; img.save(out,"PNG"); out.seek(0); return out

def make_pdf(img_b, text):
    import tempfile, os as _os
    # A4 = 210 x 297 mm
    img = Image.open(img_b)
    img_w, img_h = img.size

    # Save to temp file
    tmp = BytesIO(); img.save(tmp, "PNG"); tmp.seek(0)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(tmp.read()); path = f.name

    pdf = fpdf.FPDF(unit="mm", format="A4")
    pdf.add_page()
    pdf.set_margins(10, 10, 10)

    # QR/barcode: max width 170mm, centered, starts at y=20
    max_w = 170
    aspect = img_h / img_w
    draw_w = min(max_w, 170)
    draw_h = draw_w * aspect
    # cap height so footer has room
    if draw_h > 220:
        draw_h = 220
        draw_w = draw_h / aspect
    x = (210 - draw_w) / 2
    pdf.image(path, x=x, y=20, w=draw_w)
    _os.unlink(path)

    # Footer caption at bottom of page, never overlapping
    footer_y = 297 - 18
    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(100, 100, 100)
    pdf.set_xy(10, footer_y)
    caption = cap(text, 100)
    pdf.cell(190, 6, caption, align="C")

    raw = pdf.output(dest="S")
    if isinstance(raw, str): raw = raw.encode("latin-1")
    out = BytesIO(); out.name = "out.pdf"; out.write(raw); out.seek(0)
    return out

# ── keyboards ─────────────────────────────────────────────────────────
def kb_style(mode):
    p = "QS" if mode=="qr" else "BS"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◼ Square",  callback_data=f"{p}:square"),
         InlineKeyboardButton("● Rounded", callback_data=f"{p}:rounded"),
         InlineKeyboardButton("○ Circle",  callback_data=f"{p}:circle")],
        [InlineKeyboardButton("▦ Gapped",  callback_data=f"{p}:gapped"),
         InlineKeyboardButton("≡ H-Bars",  callback_data=f"{p}:hbars"),
         InlineKeyboardButton("║ V-Bars",  callback_data=f"{p}:vbars")],
    ])

def kb_color(mode, style):
    p = "QC" if mode=="qr" else "BC"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⬛ Classic", callback_data=f"{p}:{style}:classic"),
         InlineKeyboardButton("🔵 Blue",    callback_data=f"{p}:{style}:blue"),
         InlineKeyboardButton("🔴 Red",     callback_data=f"{p}:{style}:red"),
         InlineKeyboardButton("🟢 Green",   callback_data=f"{p}:{style}:green")],
        [InlineKeyboardButton("🟣 Purple",  callback_data=f"{p}:{style}:purple"),
         InlineKeyboardButton("🟠 Orange",  callback_data=f"{p}:{style}:orange"),
         InlineKeyboardButton("🌑 Dark",    callback_data=f"{p}:{style}:dark"),
         InlineKeyboardButton("🟡 Gold",    callback_data=f"{p}:{style}:gold")],
        [InlineKeyboardButton("🎨 Custom hex color", callback_data=f"{p}:{style}:custom")],
    ])

def kb_plain_qr_done(tkey):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Download PDF", callback_data=f"PP:qr:{tkey}")],
    ])

def kb_plain_bar_done(tkey):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Download PDF", callback_data=f"PP:bar:{tkey}")],
    ])

def kb_qr_done(style, fg, bg, tkey):
    f=fg.lstrip("#"); b=bg.lstrip("#")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖼 Add Logo", callback_data=f"LG:{style}:{f}:{b}:{tkey}"),
         InlineKeyboardButton("📄 Get PDF",  callback_data=f"PD:qr:{style}:{f}:{b}:{tkey}")],
        [InlineKeyboardButton("🔄 Change Style", callback_data=f"CR:qr:{tkey}")],
    ])

def kb_bar_done(fg, bg, tkey):
    f=fg.lstrip("#"); b=bg.lstrip("#")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Get PDF", callback_data=f"PD:bar:none:{f}:{b}:{tkey}")],
        [InlineKeyboardButton("🔄 Change Style", callback_data=f"CR:bar:{tkey}")],
    ])

# ── send final image ──────────────────────────────────────────────────
async def send_qr(msg, text, style, fg, bg, tkey, queue=None):
    pm = await msg.reply_text("⏳ Generating styled QR...")
    bio = qr_styled(text, style, fg, bg)
    await msg.reply_photo(bio, caption=cap(text),
                          reply_markup=kb_qr_done(style,fg,bg,tkey))
    await pm.delete()
    # process queued items with same style+color
    for qt in (queue or []):
        qtkey=stash(qt)
        pm2=await msg.reply_text(f"⏳ Generating: {cap(qt,40)}")
        bio2=qr_styled(qt,style,fg,bg)
        await msg.reply_photo(bio2,caption=cap(qt),
                              reply_markup=kb_qr_done(style,fg,bg,qtkey))
        await pm2.delete()

async def send_bar(msg, text, fg, bg, tkey, queue=None):
    pm = await msg.reply_text("⏳ Generating styled barcode...")
    bio = bar_styled(text, fg, bg)
    await msg.reply_photo(bio, caption=cap(text),
                          reply_markup=kb_bar_done(fg,bg,tkey))
    await pm.delete()
    for qt in (queue or []):
        qtkey=stash(qt)
        pm2=await msg.reply_text(f"⏳ Generating: {cap(qt,40)}")
        bio2=bar_styled(qt,fg,bg)
        await msg.reply_photo(bio2,caption=cap(qt),
                              reply_markup=kb_bar_done(fg,bg,qtkey))
        await pm2.delete()

# ── commands ──────────────────────────────────────────────────────────
async def cmd_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "👋 *QR & Barcode Bot*\n\n"
        "Type any text → instant QR\n\n"
        "/qr <text> — plain QR\n"
        "/qrc <text> — styled QR (shape+color+logo+PDF)\n"
        "/bar <text> — plain barcode\n"
        "/bar t1|t2 — multiple barcodes\n"
        "/barc <text> — styled barcode (color+PDF)\n"
        "/help — show all commands",
        parse_mode="Markdown")

async def cmd_help(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "📖 *Help — QR & Barcode Bot*\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🔲 *QR Codes*\n"
        "• Type any text → plain black & white QR\n"
        "• `/qr hello` → plain QR\n"
        "• `/qr a|b|c` → multiple QRs at once\n"
        "• `/qrc hello` → styled QR\n"
        "  ↳ pick shape (square/rounded/circle...)\n"
        "  ↳ pick color preset or custom hex\n"
        "  ↳ add logo image to center\n"
        "  ↳ download as PDF\n"
        "  ↳ change style anytime\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "▌ *Barcodes*\n"
        "• `/bar hello` → plain barcode\n"
        "• `/bar a|b|c` → multiple barcodes\n"
        "• `/barc hello` → styled barcode\n"
        "  ↳ pick shape + color or custom hex\n"
        "  ↳ download as PDF\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🎨 *Custom hex color*\n"
        "Use `/qrc` or `/barc` → pick *Custom hex*\n"
        "Then type your hex codes:\n"
        "  Foreground: `ff0000` (red)\n"
        "  Background: `ffffff` (white)\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📄 All QR and barcodes support PDF download!",
        parse_mode="Markdown")

async def cmd_qr(u: Update, c: ContextTypes.DEFAULT_TYPE):
    raw=" ".join(c.args).strip()
    if not raw: return await u.message.reply_text("Usage: /qr <text> or /qr t1|t2|t3")
    items=[t.strip() for t in raw.split("|") if t.strip()]
    if len(items) > 1:
        await u.message.reply_text(f"⏳ Generating {len(items)} QR codes...")
    for text in items:
        try:
            tkey=stash(text)
            await u.message.reply_photo(qr_plain(text), caption=cap(text),
                                        reply_markup=kb_plain_qr_done(tkey))
        except Exception as e:
            await u.message.reply_text(f"❌ Failed for '{text}': {e}")

async def cmd_qrc(u: Update, c: ContextTypes.DEFAULT_TYPE):
    raw=" ".join(c.args).strip()
    if not raw: return await u.message.reply_text("Usage: /qrc <text> or /qrc t1|t2|t3")
    items=[t.strip() for t in raw.split("|") if t.strip()]
    # store all items; first item is "current", rest queued
    tkey=stash(items[0])
    c.user_data.update({
        "mode":"qr","text":items[0],"tkey":tkey,"step":"style",
        "queue":items[1:],  # remaining items to process with same style/color
    })
    count=f" ({len(items)} items)" if len(items)>1 else ""
    await u.message.reply_text(f"🎨 Pick a *style*{count}:", parse_mode="Markdown",
                                reply_markup=kb_style("qr"))

async def cmd_bar(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if not c.args: return await u.message.reply_text("Usage: /bar <text> or /bar t1|t2")
    items=[t.strip() for t in " ".join(c.args).split("|") if t.strip()]
    if len(items) > 1:
        await u.message.reply_text(f"⏳ Generating {len(items)} barcodes...")
    for text in items:
        try:
            tkey=stash(text)
            await u.message.reply_photo(bar_plain(text), caption=cap(text),
                                        reply_markup=kb_plain_bar_done(tkey))
        except Exception as e:
            await u.message.reply_text(f"❌ {e}")

async def cmd_barc(u: Update, c: ContextTypes.DEFAULT_TYPE):
    raw=" ".join(c.args).strip()
    if not raw: return await u.message.reply_text("Usage: /barc <text> or /barc t1|t2|t3")
    items=[t.strip() for t in raw.split("|") if t.strip()]
    tkey=stash(items[0])
    c.user_data.update({
        "mode":"bar","text":items[0],"tkey":tkey,"step":"style",
        "queue":items[1:],
    })
    count=f" ({len(items)} items)" if len(items)>1 else ""
    await u.message.reply_text(f"🎨 Pick a *style*{count}:", parse_mode="Markdown",
                                reply_markup=kb_style("bar"))

async def msg_handler(u: Update, c: ContextTypes.DEFAULT_TYPE):
    text=u.message.text.strip()
    if not text: return
    step=c.user_data.get("step","")

    # ── waiting for custom hex foreground ──
    if step == "hex_fg":
        if not valid_hex(text):
            return await u.message.reply_text("❌ Invalid hex. Send like: ff0000 or #ff0000")
        c.user_data["custom_fg"]="#"+text.lstrip("#")
        c.user_data["step"]="hex_bg"
        return await u.message.reply_text(
            "✅ Foreground set!\n\nNow send the *background* hex color:\nExample: `ffffff`",
            parse_mode="Markdown")

    # ── waiting for custom hex background ──
    if step == "hex_bg":
        if not valid_hex(text):
            return await u.message.reply_text("❌ Invalid hex. Send like: ffffff or #ffffff")
        fg=c.user_data.get("custom_fg","#000000")
        bg="#"+text.lstrip("#")
        mode=c.user_data.get("mode","qr")
        ud_text=c.user_data.get("text","")
        tkey=c.user_data.get("tkey","")
        style=c.user_data.get("style","square")
        queue=c.user_data.get("queue",[])
        c.user_data["step"]=""; c.user_data["fg"]=fg; c.user_data["bg"]=bg
        if mode=="qr":
            await send_qr(u.message, ud_text, style, fg, bg, tkey, queue)
        else:
            await send_bar(u.message, ud_text, fg, bg, tkey, queue)
        return

    # ── waiting for logo ──
    if step == "logo":
        return await u.message.reply_text("Please send an *image* file for the logo.",
                                          parse_mode="Markdown")

    # ── default: plain QR ──
    pm = await u.message.reply_text("⏳ Generating QR code...")
    tkey=stash(text)
    await u.message.reply_photo(qr_plain(text), caption=cap(text),
                                reply_markup=kb_plain_qr_done(tkey))
    await pm.delete()

async def photo_handler(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if c.user_data.get("step") != "logo":
        return
    style=c.user_data.get("style","square")
    fg=c.user_data.get("fg","#000000")
    bg=c.user_data.get("bg","#ffffff")
    tkey=c.user_data.get("tkey","")
    text=store.get(tkey,"")
    if not text:
        return await u.message.reply_text("❌ Session expired. Use /qrc again.")
    file_obj=(u.message.photo[-1] if u.message.photo else None) or u.message.document
    tf=await file_obj.get_file()
    lb=BytesIO(); await tf.download_to_memory(lb); lb.seek(0)
    bio=qr_styled(text,style,fg,bg,logo_b=lb)
    c.user_data["step"]=""
    await u.message.reply_photo(bio, caption=cap(text),
                                 reply_markup=kb_qr_done(style,fg,bg,tkey))

# ── callback handlers ─────────────────────────────────────────────────
async def cb_handler(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q=u.callback_query
    await q.answer()
    d=q.data
    ud=c.user_data

    # ── style picked (QS: or BS:) ──
    if d.startswith("QS:") or d.startswith("BS:"):
        mode="qr" if d.startswith("QS") else "bar"
        style=d.split(":")[1]
        ud["style"]=style; ud["mode"]=mode; ud["step"]="color"
        try:
            await q.edit_message_text(f"✅ Style: *{style}*\n\nNow pick a color:",
                                       parse_mode="Markdown",
                                       reply_markup=kb_color(mode,style))
        except Exception:
            await q.message.reply_text(f"✅ Style: *{style}*\n\nNow pick a color:",
                                        parse_mode="Markdown",
                                        reply_markup=kb_color(mode,style))
        return

    # ── color picked (QC: or BC:) ──
    if d.startswith("QC:") or d.startswith("BC:"):
        mode="qr" if d.startswith("QC") else "bar"
        parts=d.split(":",2); style=parts[1]; color=parts[2]
        ud["style"]=style; ud["mode"]=mode

        if color=="custom":
            ud["step"]="hex_fg"
            await q.edit_message_text(
                "🎨 *Custom color*\n\n"
                "Step 1 — Send your *foreground* color as hex:\n"
                "Example: `000000` for black or `ff0000` for red",
                parse_mode="Markdown")
            return

        fg,bg=COLORS.get(color,("#000000","#ffffff"))
        ud["fg"]=fg; ud["bg"]=bg; ud["step"]=""
        text=ud.get("text",""); tkey=ud.get("tkey","")
        queue=ud.get("queue",[])
        if not text:
            await q.edit_message_text("❌ Session expired. Send /qrc or /barc again.")
            return
        await q.delete_message()
        if mode=="qr":
            await send_qr(q.message, text, style, fg, bg, tkey, queue)
        else:
            await send_bar(q.message, text, fg, bg, tkey, queue)
        return

    # ── change style (CR:mode:tkey) ──
    if d.startswith("CR:"):
        parts=d.split(":",2); mode=parts[1]; tkey=parts[2]
        text=store.get(tkey,"")
        if text:
            ud["text"]=text; ud["tkey"]=tkey; ud["mode"]=mode; ud["step"]="style"
        await q.message.reply_text("🎨 Pick a *style*:", parse_mode="Markdown",
                                   reply_markup=kb_style(mode))
        return

    # ── plain PDF (PP:kind:tkey) ──
    if d.startswith("PP:"):
        parts=d.split(":",2); kind=parts[1]; tkey=parts[2]
        text=store.get(tkey,"")
        if not text:
            await q.message.reply_text("❌ Session expired.")
            return
        await q.answer("Generating PDF...")
        if kind=="qr":
            img_b=qr_plain(text)
        else:
            img_b=bar_plain(text)
        pdf_b=make_pdf(img_b,text)
        await q.message.reply_document(pdf_b, caption="📄 Your PDF")
        return

    # ── get PDF (PD:kind:style:fg:bg:tkey) ──
    if d.startswith("PD:"):
        parts=d.split(":",5)
        kind=parts[1]; style=parts[2]; fg="#"+parts[3]; bg="#"+parts[4]; tkey=parts[5]
        text=store.get(tkey,"")
        if not text:
            await q.message.reply_text("❌ Session expired.")
            return
        await q.answer("Generating PDF...")
        if kind=="qr":
            img_b=qr_styled(text,style,fg,bg)
        else:
            img_b=bar_styled(text,fg,bg)
        pdf_b=make_pdf(img_b,text)
        await q.message.reply_document(pdf_b, caption="📄 Your PDF")
        return

    # ── add logo (LG:style:fg:bg:tkey) ──
    if d.startswith("LG:"):
        parts=d.split(":",4)
        style=parts[1]; fg="#"+parts[2]; bg="#"+parts[3]; tkey=parts[4]
        ud["style"]=style; ud["fg"]=fg; ud["bg"]=bg; ud["tkey"]=tkey; ud["step"]="logo"
        await q.message.reply_text("📎 Send your logo image (PNG recommended):")
        return

# ── main ──────────────────────────────────────────────────────────────
def main():
    app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("qr",    cmd_qr))
    app.add_handler(CommandHandler("qrc",   cmd_qrc))
    app.add_handler(CommandHandler("bar",   cmd_bar))
    app.add_handler(CommandHandler("barc",  cmd_barc))
    app.add_handler(CallbackQueryHandler(cb_handler))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    print("Bot running...")
    app.run_polling()

if __name__=="__main__":
    main()
