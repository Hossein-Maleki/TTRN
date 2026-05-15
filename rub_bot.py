import os
import time
import logging
from dotenv import load_dotenv
from rubpy.bot import BotClient

load_dotenv()

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("rub_bot")

TOKEN = os.getenv("RUBIKA_BOT_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("TOKEN missing")

import db


# ───────────────────────── logic ─────────────────────────

def handle_message(sender_id, chat_id, text):
    text = (text or "").strip()

    if text.startswith("/start"):
        return "👋 ربات فعال است"

    code = text.replace(" ", "").upper()

    if len(code) == 8 and code.isalnum():
        file_record = db.get_file_by_code(code)

        if not file_record:
            return "❌ کد پیدا نشد"

        if file_record.get("delivered"):
            return "⚠️ قبلاً ارسال شده"

        db.push_forward(code, sender_id)

        return f"📦 فایل: {file_record['file_name']} در حال ارسال..."

    return "❓ دستور نامعتبر"


# ───────────────────────── BOT ─────────────────────────

def extract(update):
    msg = getattr(update, "message", None) or update

    text = getattr(msg, "text", "") or ""
    chat_id = getattr(msg, "object_guid", "") or getattr(msg, "chat_id", "")
    sender_id = getattr(msg, "author_object_guid", "") or ""

    return sender_id, chat_id, text


def run():
    app = BotClient(TOKEN)

    log.info("🚀 Bot started (polling mode)")

    offset = None

    while True:
        try:
            updates = app.get_updates(limit=50)

            if not updates:
                time.sleep(1)
                continue

            for update in updates:

                sender_id, chat_id, text = extract(update)

                if not chat_id:
                    continue

                reply = handle_message(sender_id, chat_id, text)

                app.send_message(chat_id, reply)

        except Exception as e:
            log.error(f"error: {e}")
            time.sleep(2)


if __name__ == "__main__":
    run()