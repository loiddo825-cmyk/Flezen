import os
import re
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request, HTTPException
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("flezen-bot")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
PUBLIC_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
MAX_SIZE = 45 * 1024 * 1024  # 45 MiB starter limit

FLEZEN_HOSTS = {"flezen.com", "www.flezen.com"}
VIDEO_EXTENSIONS = (".mp4", ".m4v", ".mov", ".webm")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing.")
if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET environment variable is missing.")
if not PUBLIC_URL:
    raise RuntimeError("RENDER_EXTERNAL_URL is missing. Deploy this as a Render Web Service.")

app = FastAPI()
telegram_app = Application.builder().token(BOT_TOKEN).build()


def is_flezen_share_link(url: str) -> bool:
    try:
        p = urlparse(url)
        return (
            p.scheme == "https"
            and p.hostname in FLEZEN_HOSTS
            and p.path.startswith("/s/")
        )
    except Exception:
        return False


def is_direct_video_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return (
            p.scheme == "https"
            and bool(p.hostname)
            and not p.username
            and not p.password
            and p.path.lower().endswith(VIDEO_EXTENSIONS)
        )
    except Exception:
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🎬 Flezen Video Downloader Bot ready!\n\n"
        "Flezen share link bhejo. Agar supported official download source "
        "available hua to usko integrate kiya ja sakta hai.\n\n"
        "Abhi direct HTTPS video-file links (.mp4, .mov, .webm) supported hain. "
        "Flezen share-link extraction abhi configure karna baaki hai."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Use:\n"
        "1) Direct HTTPS video URL bhejo (jaise https://example.com/video.mp4)\n"
        "2) Flezen share links abhi detect hote hain, lekin unka downloader "
        "adapter abhi configured nahi hai.\n\n"
        "Bot sirf un videos ke liye hai jinhe download karne ki permission "
        "aapke paas hai."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text:
        return

    match = re.search(r"https?://[^\s<>]+", message.text)
    if not match:
        await message.reply_text("Ek HTTPS video ya Flezen share link bhejo.")
        return

    url = match.group(0).rstrip(".,);]")
    if is_flezen_share_link(url):
        await message.reply_text(
            "✅ Flezen share link mil gaya.\n\n"
            "Is bot mein Flezen ka official/authorized download adapter abhi "
            "connect nahi hai. Sirf share link se direct video URL nikalna "
            "har site par possible nahi hota. Agar Flezen official API ya "
            "download URL provide karta hai, uske mutabik adapter add karenge."
        )
        return

    if not is_direct_video_url(url):
        await message.reply_text(
            "Abhi direct HTTPS video file URL supported hai (.mp4, .m4v, .mov, .webm)."
        )
        return

    status = await message.reply_text("⏳ Video download ho raha hai...")
    try:
        with tempfile.TemporaryDirectory(prefix="tg-video-") as tmp:
            filepath = Path(tmp) / "video.mp4"
            downloaded = 0

            # Stream with redirects disabled to avoid forwarding arbitrary links.
            async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        await status.edit_text(
                            f"Download failed: HTTP {response.status_code}. "
                            "Link expired ya access restricted ho sakta hai."
                        )
                        return

                    content_type = response.headers.get("content-type", "").lower()
                    if not (
                        content_type.startswith("video/")
                        or content_type == "application/octet-stream"
                    ):
                        await status.edit_text("URL se video file confirm nahi hui.")
                        return

                    content_length = response.headers.get("content-length")
                    if content_length:
                        try:
                            if int(content_length) > MAX_SIZE:
                                await status.edit_text("Video 45 MiB limit se badi hai.")
                                return
                        except ValueError:
                            pass

                    with filepath.open("wb") as output:
                        async for chunk in response.aiter_bytes():
                            downloaded += len(chunk)
                            if downloaded > MAX_SIZE:
                                await status.edit_text("Video 45 MiB limit se badi hai.")
                                return
                            output.write(chunk)

            await status.edit_text("📤 Telegram par bhej raha hoon...")
            with filepath.open("rb") as video:
                await message.reply_document(
                    document=video,
                    filename="video.mp4",
                    caption="✅ Video ready",
                    read_timeout=120,
                    write_timeout=120,
                    connect_timeout=30,
                )
            await status.delete()

    except httpx.HTTPError as exc:
        log.warning("Download error: %s", exc)
        await status.edit_text("Network/download error. Link check karke dobara try karo.")
    except Exception:
        log.exception("Unexpected error while handling video")
        await status.edit_text("Error aaya. Thodi der baad dobara try karo.")


telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("help", help_command))
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


@app.on_event("startup")
async def startup():
    await telegram_app.initialize()
    await telegram_app.start()
    webhook_url = f"{PUBLIC_URL}/telegram/{WEBHOOK_SECRET}"
    await telegram_app.bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=["message"],
        drop_pending_updates=False,
    )
    log.info("Webhook configured: %s/telegram/[secret]", PUBLIC_URL)


@app.on_event("shutdown")
async def shutdown():
    try:
        await telegram_app.bot.delete_webhook(drop_pending_updates=False)
        await telegram_app.stop()
        await telegram_app.shutdown()
    except Exception:
        log.exception("Error during shutdown")


@app.get("/")
async def health():
    return {"ok": True, "service": "flezen-telegram-bot"}


@app.post("/telegram/{path_secret}")
async def telegram_webhook(path_secret: str, request: Request):
    if path_secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    telegram_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if telegram_secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid Telegram secret")

    try:
        payload = await request.json()
        update = Update.de_json(payload, telegram_app.bot)
        await telegram_app.process_update(update)
    except Exception as exc:
        log.exception("Webhook update failed: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid update")

    return {"ok": True}
