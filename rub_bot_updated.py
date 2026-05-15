"""
rub_bot.py — ربات روبیکا (نسخه ۲.۲ - بهبود یافته)
- دریافت کد ۸ کاراکتری
- فوروارد فایل
"""

import os
import re
import time
import logging
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [rub_bot] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("rub_bot")

load_dotenv()

RUBIKA_BOT_TOKEN = os.getenv("RUBIKA_BOT_TOKEN", "").strip()
if not RUBIKA_BOT_TOKEN:
    raise RuntimeError("RUBIKA_BOT_TOKEN را در .env تنظیم کن")

import db

CODE_RE = re.compile(r"^[A-Z0-9]{8}$")

# ─────────────────────────── پردازش پیام ─────────────────────────────────

def handle_message(sender_id: str, chat_id: str, text: str) -> str:
    """پردازش پیام و برگرداندن جواب"""
    text = (text or "").strip()
    log.info(f"📩 {sender_id[:12]}… | {text[:40]}")

    # /start
    if text.lower().startswith("/start"):
        return (
            "👋 سلام!\n\n"
            "🎫 کد ۸ کاراکتری برای دریافت فایل بفرست.\n\n"
            "مثال: `AB12CD34`"
        )

    # /help
    if text.lower().startswith("/help"):
        return (
            "📖 **راهنما**\n\n"
            "کد یونیک ۸ کاراکتری رو بفرست.\n"
            "فایل برایت ارسال می‌شه."
        )

    # کد یونیک
    code = re.sub(r"\s+", "", text.upper())
    if CODE_RE.match(code):
        file_record = db.get_file_by_code(code)
        if not file_record:
            return f"❌ کد `{code}` پیدا نشد."
        
        if file_record["delivered"]:
            return "⚠️ این فایل قبلاً تحویل داده شده."

        # افزودن به صف فوروارد
        db.push_forward(code, sender_id)
        return (
            f"✅ درخواست دریافت شد!\n\n"
            f"🎫 کد: `{code}`\n"
            f"📄 فایل: `{file_record['file_name']}`\n"
            f"📦 حجم: `{db.pretty_size(file_record['file_size'])}`\n\n"
            "⏳ فایل درحال آماده‌سازی است..."
        )

    return "❓ کد یونیک ۸ کاراکتری بفرست یا /help را استفاده کن."

# ═══════════════════════════════════════════════════════════════════════════

def _extract_update_fields(update) -> tuple:
    """استخراج sender_id، chat_id، text از update"""
    def safe(obj, *keys, default=""):
        for key in keys:
            val = getattr(obj, key, None)
            if val:
                return str(val)
        return default

    text = safe(update, "text", "message_text")
    sender_id = safe(update, "sender_id", "author_object_guid", "from_object_guid")
    chat_id = safe(update, "chat_id", "object_guid")

    # حالت inline_message
    if not chat_id:
        im = getattr(update, "inline_message", None) or getattr(update, "message", None)
        if im:
            text = safe(im, "text", "message_text") or text
            sender_id = safe(im, "sender_id", "author_object_guid") or sender_id
            chat_id = safe(im, "chat_id", "object_guid") or chat_id

    return str(sender_id), str(chat_id), str(text)

# ═══════════════════════════════════════════════════════════════════════════
# روش ۱ — BotClient
# ═══════════════════════════════════════════════════════════════════════════

def run_with_botclient():
    try:
        from rubpy.bot import BotClient
    except ImportError as e:
        log.error(f"rubpy.bot import خطا: {e}")
        return False

    log.info("▶ شروع با BotClient...")
    app = BotClient(RUBIKA_BOT_TOKEN)

    @app.on_update()
    async def on_all(client, update):
        try:
            sender_id, chat_id, text = _extract_update_fields(update)
            if not chat_id:
                return
            
            reply_text = handle_message(sender_id, chat_id, text)
            try:
                await update.reply(reply_text)
            except Exception:
                try:
                    await client.send_message(chat_id, reply_text)
                except Exception as e2:
                    log.error(f"ارسال خطا: {e2}")
        except Exception as e:
            log.error(f"on_update خطا: {e}")

    log.info("✅ ربات روبیکا شروع شد...")
    try:
        app.run()
        return True
    except Exception as e:
        log.error(f"run خطا: {e}")
        return False

# ═══════════════════════════════════════════════════════════════════════════
# روش ۲ — Polling
# ═══════════════════════════════════════════════════════════════════════════

_API_BASES = [
    "https://messengerg2b1.iranlms.ir/v3",
    "https://messengerg2c1.iranlms.ir/v3",
    "https://messengerg2d1.iranlms.ir/v3",
]

def _api_call(method: str, payload: dict, timeout: int = 35) -> dict:
    import requests
    for base in _API_BASES:
        url = f"{base}/{RUBIKA_BOT_TOKEN}/{method}"
        try:
            resp = requests.post(url, json=payload, timeout=timeout)
            data = resp.json()
            if resp.status_code == 200:
                return data
        except requests.exceptions.RequestException:
            continue
    return None

def _send_msg_polling(chat_id: str, text: str):
    result = _api_call("sendMessage", {"chat_id": chat_id, "text": text})
    if not result:
        log.error(f"ارسال به {chat_id} ناموفق")

def run_with_polling():
    log.info("▶ شروع با polling...")
    offset = None

    while True:
        try:
            payload = {"limit": 20, "timeout": 30}
            if offset is not None:
                payload["offset"] = offset + 1

            result = _api_call("getUpdates", payload, timeout=35)
            if not result:
                time.sleep(5)
                continue

            updates = (
                result.get("data", {}).get("updates") or
                result.get("updates") or
                []
            )
            if isinstance(updates, dict):
                updates = [updates]

            for upd in updates:
                uid = upd.get("update_id")
                if uid:
                    try:
                        offset = int(uid)
                    except (ValueError, TypeError):
                        pass

                msg = (
                    upd.get("inline_message") or
                    upd.get("message") or
                    upd
                )
                text = msg.get("text", "") if hasattr(msg, "get") else ""
                sender_id = msg.get("sender_id", "") if hasattr(msg, "get") else ""
                chat_id = msg.get("chat_id", "") if hasattr(msg, "get") else ""

                if not chat_id:
                    continue

                reply_text = handle_message(sender_id, chat_id, text)
                _send_msg_polling(chat_id, reply_text)

        except KeyboardInterrupt:
            log.info("🛑 polling متوقف شد")
            break
        except Exception as e:
            log.error(f"خطا: {e}")
            time.sleep(3)

# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log.info(f"🤖 شروع ربات روبیکا")
    try:
        success = run_with_botclient()
        if not success:
            raise RuntimeError("BotClient ناموفق")
    except Exception as e:
        log.warning(f"BotClient کار نکرد. استفاده از polling...")
        run_with_polling()
