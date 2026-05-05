"""
rub_bot.py — ربات روبیکا: دریافت کد یونیک از کاربر و فوروارد فایل
از rubpy.bot.BotClient استفاده می‌کنه (توکن ربات روبیکا)
"""

import os
import re
import time
from dotenv import load_dotenv

load_dotenv()

RUBIKA_BOT_TOKEN = os.getenv("RUBIKA_BOT_TOKEN", "").strip()

if not RUBIKA_BOT_TOKEN:
    raise RuntimeError("RUBIKA_BOT_TOKEN را در .env تنظیم کن")

import db

# ─── تلاش برای import BotClient از rubpy ─────────────────────────────────────
try:
    from rubpy.bot import BotClient, filters as bot_filters
    _USE_BOTCLIENT = True
    print("✅ rubpy BotClient لود شد.")
except ImportError:
    _USE_BOTCLIENT = False
    print("⚠️  BotClient در نسخه rubpy موجود نیست. از polling دستی استفاده می‌شه.")

# ─── ابزارها ──────────────────────────────────────────────────────────────────

CODE_RE = re.compile(r'^[A-Z0-9]{8}$')


def is_valid_code(text: str) -> bool:
    return bool(CODE_RE.match((text or "").strip().upper()))


def handle_message(sender_id: str, chat_id: str, text: str) -> str:
    """
    پردازش پیام ورودی — برمی‌گرداند متن پاسخ
    sender_id: guid کاربر روبیکا (u0xxx)
    chat_id:   chat_id ربات (b0xxx) برای پاسخ
    text:      متن دریافتی
    """
    text = (text or "").strip()

    if text.startswith("/start"):
        return (
            "سلام! 👋\n\n"
            "من ربات **Tele2Rub** هستم.\n\n"
            "کد ۸ کاراکتری که از ربات تلگرام دریافت کردی رو اینجا بفرست "
            "تا فایلت برات ارسال بشه.\n\n"
            "مثال: `AB12CD34`"
        )

    code = text.upper()

    if not is_valid_code(code):
        return (
            "❓ لطفاً کد ۸ کاراکتری که از ربات تلگرام گرفتی رو بفرست.\n"
            "مثال: `AB12CD34`"
        )

    file_record = db.get_file_by_code(code)
    if not file_record:
        return (
            "❌ کد `" + code + "` پیدا نشد.\n"
            "مطمئن شو کد رو درست وارد کردی."
        )

    if file_record["delivered"]:
        return (
            "⚠️ این فایل قبلاً تحویل داده شده.\n"
            "اگر دریافت نکردی با پشتیبانی تماس بگیر."
        )

    # ثبت در صف فوروارد
    db.push_forward(code, sender_id)

    return (
        f"✅ درخواست دریافت شد!\n\n"
        f"🎫 کد: `{code}`\n"
        f"📄 فایل: `{file_record['file_name']}`\n"
        f"📦 حجم: `{db.pretty_size(file_record['file_size'])}`\n\n"
        f"⏳ فایل در حال آماده‌سازی است. چند لحظه صبر کن..."
    )


# ─── اجرا با BotClient (rubpy) ────────────────────────────────────────────────

def run_with_botclient():
    """اجرا با rubpy BotClient — ربات رسمی روبیکا"""
    app = BotClient(RUBIKA_BOT_TOKEN)

    @app.on_update(bot_filters.private)
    async def on_message(client, update):
        try:
            text      = getattr(update, "text", "") or ""
            sender_id = getattr(update, "sender_id", "") or ""
            chat_id   = getattr(update, "chat_id", "") or ""

            if not sender_id or not chat_id:
                return

            reply = handle_message(sender_id, chat_id, text)
            await update.reply(reply)
        except Exception as e:
            print(f"[rub_bot] خطا در پردازش پیام: {e}")
            try:
                await update.reply("❌ خطای داخلی. دوباره امتحان کن.")
            except Exception:
                pass

    print("✅ ربات روبیکا در حال اجراست...")
    app.run()


# ─── اجرا با polling دستی (fallback) ─────────────────────────────────────────

def run_with_polling():
    """
    اجرا با API مستقیم روبیکا — وقتی BotClient موجود نیست
    از کتابخانه rubika_bot یا requests مستقیم استفاده می‌کنه
    """
    try:
        from rubika_bot import Bot
        _rubika_bot_available = True
    except ImportError:
        _rubika_bot_available = False

    if _rubika_bot_available:
        _run_rubika_bot_lib()
    else:
        _run_manual_polling()


def _run_rubika_bot_lib():
    """با کتابخانه rubika_bot اجرا می‌کنه"""
    from rubika_bot import Bot
    from rubika_bot.requests import send_message, set_webhook

    bot = Bot(RUBIKA_BOT_TOKEN)

    import threading
    import requests as req_lib

    print("✅ ربات روبیکا (rubika_bot lib) در حال اجراست...")

    def poll():
        offset = None
        while True:
            try:
                url = f"https://messengerg2b1.iranlms.ir/v3/{RUBIKA_BOT_TOKEN}/getUpdates"
                payload = {"limit": 10, "timeout": 30}
                if offset:
                    payload["offset"] = offset
                resp = req_lib.post(url, json=payload, timeout=35)
                data = resp.json()
                updates = data.get("data", {}).get("updates", [])
                for upd in updates:
                    offset = upd.get("update_id", offset)
                    msg = upd.get("inline_message") or upd.get("message", {})
                    text      = msg.get("text", "") or ""
                    sender_id = msg.get("sender_id", "") or ""
                    chat_id   = msg.get("chat_id", "") or ""
                    if not chat_id:
                        continue
                    reply = handle_message(sender_id, chat_id, text)
                    send_message(token=RUBIKA_BOT_TOKEN, chat_id=chat_id, text=reply)
            except Exception as e:
                print(f"[rub_bot poll] {e}")
                time.sleep(3)

    poll()


def _run_manual_polling():
    """polling دستی با requests مستقیم"""
    import requests as req_lib

    print("✅ ربات روبیکا (manual polling) در حال اجراست...")
    offset = None

    def send_msg(chat_id: str, text: str):
        try:
            url = f"https://messengerg2b1.iranlms.ir/v3/{RUBIKA_BOT_TOKEN}/sendMessage"
            req_lib.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        except Exception as e:
            print(f"[rub_bot send] {e}")

    while True:
        try:
            url     = f"https://messengerg2b1.iranlms.ir/v3/{RUBIKA_BOT_TOKEN}/getUpdates"
            payload = {"limit": 10, "timeout": 30}
            if offset:
                payload["offset"] = offset
            resp    = req_lib.post(url, json=payload, timeout=35)
            data    = resp.json()
            updates = data.get("data", {}).get("updates", [])

            for upd in updates:
                offset = upd.get("update_id", offset)
                msg       = upd.get("inline_message") or upd.get("message", {})
                text      = msg.get("text", "") or ""
                sender_id = msg.get("sender_id", "") or ""
                chat_id   = msg.get("chat_id", "") or ""
                if not chat_id:
                    continue
                reply = handle_message(sender_id, chat_id, text)
                send_msg(chat_id, reply)

        except Exception as e:
            print(f"[rub_bot] {e}")
            time.sleep(3)


# ─── main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if _USE_BOTCLIENT:
        run_with_botclient()
    else:
        run_with_polling()
