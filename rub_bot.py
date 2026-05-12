"""
rub_bot.py — ربات روبیکا
دریافت کد یونیک و ارسال فایل به کاربر

نسخه اصلاح‌شده برای Bot API جدید روبیکا
"""

import os
import re
import time
import json
import requests

from dotenv import load_dotenv

load_dotenv()

RUBIKA_BOT_TOKEN = os.getenv("RUBIKA_BOT_TOKEN", "").strip()

if not RUBIKA_BOT_TOKEN:
    raise RuntimeError("RUBIKA_BOT_TOKEN در .env تنظیم نشده")

import db


# ─────────────────────────────────────────────────────────────
# تنظیمات
# ─────────────────────────────────────────────────────────────

BASE_URL = f"https://botapi.rubika.ir/v3/{RUBIKA_BOT_TOKEN}"

CODE_RE = re.compile(r"^[A-Z0-9]{8}$")

REQUEST_TIMEOUT = 35


# ─────────────────────────────────────────────────────────────
# ابزارها
# ─────────────────────────────────────────────────────────────

def is_valid_code(text: str) -> bool:
    return bool(CODE_RE.match((text or "").strip().upper()))


def send_message(chat_id: str, text: str):
    """
    ارسال پیام به کاربر روبیکا
    """

    url = f"{BASE_URL}/sendMessage"

    payload = {
        "object_guid": chat_id,
        "text": text,
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        data = resp.json()

        if data.get("status") != "OK":
            print("[sendMessage ERROR]")
            print(json.dumps(data, ensure_ascii=False, indent=2))

    except Exception as e:
        print(f"[send_message] {e}")


def handle_message(sender_id: str, chat_id: str, text: str) -> str:
    """
    پردازش پیام دریافتی
    """

    text = (text or "").strip()

    print(f"[MESSAGE] {sender_id} -> {text}")

    # استارت
    if text.lower().startswith("/start"):
        return (
            "سلام 👋\n\n"
            "به ربات انتقال فایل خوش اومدی.\n\n"
            "کد ۸ کاراکتری که از ربات تلگرام گرفتی رو بفرست.\n\n"
            "مثال:\n"
            "`AB12CD34`"
        )

    code = text.upper()

    # اعتبارسنجی کد
    if not is_valid_code(code):
        return (
            "❌ کد نامعتبره.\n\n"
            "لطفاً کد ۸ کاراکتری صحیح ارسال کن.\n\n"
            "مثال:\n"
            "`AB12CD34`"
        )

    # جستجو در دیتابیس
    file_record = db.get_file_by_code(code)

    if not file_record:
        return (
            f"❌ کد `{code}` پیدا نشد.\n\n"
            "مطمئن شو درست واردش کردی."
        )

    # بررسی تحویل قبلی
    if file_record["delivered"]:
        return (
            "⚠️ این فایل قبلاً ارسال شده."
        )

    # ثبت در صف فوروارد
    db.push_forward(code, sender_id)

    return (
        "✅ درخواست ثبت شد.\n\n"
        f"🎫 کد: `{code}`\n"
        f"📄 فایل: `{file_record['file_name']}`\n"
        f"📦 حجم: `{db.pretty_size(file_record['file_size'])}`\n\n"
        "⏳ لطفاً چند لحظه صبر کن..."
    )


# ─────────────────────────────────────────────────────────────
# دریافت آپدیت‌ها
# ─────────────────────────────────────────────────────────────

def get_updates(offset_id=None):

    url = f"{BASE_URL}/getUpdates"

    payload = {
        "limit": 10,
    }

    if offset_id is not None:
        payload["offset_id"] = offset_id

    try:
        resp = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        data = resp.json()

        if data.get("status") != "OK":
            print("[getUpdates ERROR]")
            print(json.dumps(data, ensure_ascii=False, indent=2))
            return []

        return data.get("data", {}).get("updates", [])

    except Exception as e:
        print(f"[get_updates] {e}")
        return []


# ─────────────────────────────────────────────────────────────
# اجرای اصلی
# ─────────────────────────────────────────────────────────────

def main():

    print("✅ ربات روبیکا اجرا شد")

    # تست توکن
    try:
        resp = requests.post(
            f"{BASE_URL}/getMe",
            timeout=20,
        )

        print("[getMe]")
        print(resp.text)

    except Exception as e:
        print(f"[getMe ERROR] {e}")

    offset_id = None

    while True:

        try:

            updates = get_updates(offset_id)

            if not updates:
                time.sleep(1)
                continue

            for upd in updates:

                try:

                    print(json.dumps(
                        upd,
                        ensure_ascii=False,
                        indent=2
                    ))

                    update_id = upd.get("update_id")

                    if update_id is not None:
                        offset_id = update_id + 1

                    # ساختار جدید روبیکا
                    msg = upd.get("new_message", {})

                    if not msg:
                        continue

                    text = msg.get("text", "") or ""

                    sender_id = (
                        msg.get("author_object_guid")
                        or msg.get("sender_object_guid")
                        or ""
                    )

                    chat_id = (
                        msg.get("object_guid")
                        or ""
                    )

                    if not chat_id:
                        continue

                    reply = handle_message(
                        sender_id=sender_id,
                        chat_id=chat_id,
                        text=text,
                    )

                    send_message(chat_id, reply)

                except Exception as e:
                    print(f"[UPDATE ERROR] {e}")

        except Exception as e:

            print(f"[MAIN LOOP ERROR] {e}")

            time.sleep(3)


# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()