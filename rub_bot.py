"""
rub_bot.py — ربات روبیکا (نسخه اصلاح‌شده و پایدار)

✔ فقط BotClient رسمی rubpy
✔ حذف کامل polling و endpointهای خراب
✔ هندل امن update
✔ جلوگیری از JSON/attribute crash
✔ سازگار با تغییرات API روبیکا
"""

import os
import re
import logging
from dotenv import load_dotenv

load_dotenv()

from rubpy.bot import BotClient

# ───────────────────────── LOG ─────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [rub_bot] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rub_bot")

# ───────────────────────── TOKEN ─────────────────────────

RUBIKA_BOT_TOKEN = os.getenv("RUBIKA_BOT_TOKEN", "").strip()

if not RUBIKA_BOT_TOKEN:
    raise RuntimeError("❌ RUBIKA_BOT_TOKEN تنظیم نشده")

# ───────────────────────── IMPORTS ─────────────────────────

import db
from tg_userbot import parse_tme_link

# ───────────────────────── REGEX ─────────────────────────

CODE_RE        = re.compile(r"^[A-Z0-9]{8}$")
TME_URL_RE     = re.compile(r"https?://t\.me/\S+")
JOIN_URL_RE    = re.compile(r"https?://t\.me/\+\S+")
SEARCH_CMD_RE  = re.compile(r"^/search\s+(@\S+)\s+(.+)$", re.IGNORECASE)
GETPOST_CMD_RE = re.compile(r"^/getpost\s+(@\S+)\s+(\d+)$", re.IGNORECASE)
LATEST_CMD_RE  = re.compile(r"^/latest\s+(@\S+)(?:\s+(\d+))?$", re.IGNORECASE)

# ───────────────────────── HANDLER ─────────────────────────

def handle_message(sender_id: str, chat_id: str, text: str) -> str:
    text = (text or "").strip()

    if text.startswith("/start"):
        return "👋 ربات فعال است"

    if text.startswith("/help"):
        return "📖 راهنما: /start /search /getpost /latest + کد ۸ رقمی"

    # ── CODE
    code = text.replace(" ", "").upper()
    if CODE_RE.match(code):
        file_record = db.get_file_by_code(code)

        if not file_record:
            return "❌ کد پیدا نشد"

        if file_record.get("delivered"):
            return "⚠️ قبلاً ارسال شده"

        db.push_forward(code, sender_id)

        return f"📦 فایل: {file_record['file_name']} در حال ارسال..."

    return "❓ دستور نامعتبر"


# ───────────────────────── SAFE UPDATE PARSER ─────────────────────────

def extract(update):
    """
    استخراج امن اطلاعات از انواع update در rubpy
    """

    text = getattr(update, "text", None) or getattr(update, "message_text", "") or ""

    sender_id = (
        getattr(update, "sender_id", None)
        or getattr(update, "author_object_guid", None)
        or getattr(update, "from_object_guid", None)
        or ""
    )

    chat_id = (
        getattr(update, "chat_id", None)
        or getattr(update, "object_guid", None)
        or ""
    )

    return str(sender_id), str(chat_id), str(text)


# ───────────────────────── BOT ─────────────────────────

app = BotClient(RUBIKA_BOT_TOKEN)


@app.on_message()
async def on_message(client, update):
    try:
        sender_id, chat_id, text = extract(update)

        log.info(f"📩 پیام: {text[:50]}")

        if not chat_id:
            log.warning("chat_id خالی")
            return

        reply = handle_message(sender_id, chat_id, text)

        await client.send_message(chat_id, reply)

    except Exception as e:
        log.error(f"handler error: {e}", exc_info=True)

        try:
            await client.send_message(chat_id, "❌ خطای داخلی")
        except:
            pass


# ───────────────────────── RUN ─────────────────────────

if __name__ == "__main__":
    log.info("🚀 ربات روبیکا در حال اجرا (BotClient)...")
    app.run()