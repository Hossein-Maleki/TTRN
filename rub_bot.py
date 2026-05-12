import os
import re
import time
import requests
from dotenv import load_dotenv

# ایمپورت دیتابیس پروژه شما
import db

load_dotenv()

RUBIKA_BOT_TOKEN = os.getenv("RUBIKA_BOT_TOKEN", "").strip()
API_BASE_URL = f"https://messengerg2b1.iranlms.ir/v3/{RUBIKA_BOT_TOKEN}"

if not RUBIKA_BOT_TOKEN:
    raise RuntimeError("⚠️ RUBIKA_BOT_TOKEN را در فایل .env تنظیم نکرده‌اید.")

# ─── ابزارها و منطق بیزینس ──────────────────────────────────────────────────────

CODE_RE = re.compile(r'^[A-Z0-9]{8}$')

def is_valid_code(text: str) -> bool:
    return bool(CODE_RE.match((text or "").strip().upper()))

def handle_message(sender_id: str, chat_id: str, text: str) -> str:
    """پردازش کد یونیک و ثبت در صف فوروارد دیتابیس"""
    text = (text or "").strip()

    if text.lower().startswith("/start"):
        return (
            "سلام! خوش آمدید 👋\n\n"
            "من ربات انتقال فایل هستم. کد ۸ کاراکتری که از تلگرام دریافت کردید را اینجا بفرستید.\n\n"
            "مثال: `AB12CD34`"
        )

    code = text.upper()
    if not is_valid_code(code):
        return "❓ لطفاً فقط کد ۸ کاراکتری معتبر را ارسال کنید.\nمثال: `AB12CD34`"

    file_record = db.get_file_by_code(code)
    if not file_record:
        return f"❌ متأسفم، کد `{code}` در سیستم پیدا نشد."

    if file_record.get("delivered"):
        return "⚠️ این فایل قبلاً تحویل داده شده است."

    # ثبت در صف فوروارد (توسط فایل rub_worker پردازش خواهد شد)
    db.push_forward(code, sender_id)

    return (
        f"✅ درخواست با موفقیت ثبت شد!\n\n"
        f"📄 فایل: {file_record['file_name']}\n"
        f"📦 حجم: {db.pretty_size(file_record['file_size'])}\n\n"
        f"⏳ سیستم در حال فوروارد فایل برای شماست. لطفاً شکیبا باشید..."
    )

# ─── ارتباط با API روبیکا ──────────────────────────────────────────────────────

def send_message(chat_id, text):
    """ارسال پیام متنی به کاربر"""
    url = f"{API_BASE_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown" # روبیکا از مارک‌داون پشتیبانی می‌کند
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"❌ Error sending message: {e}")

def run_bot():
    """اجرای بدنه اصلی ربات با استفاده از Long Polling استاندارد"""
    print("🚀 ربات روبیکا با موفقیت اجرا شد و آماده دریافت پیام است...")
    offset = None

    while True:
        try:
            url = f"{API_BASE_URL}/getUpdates"
            # استفاده از timeout بالا برای Long Polling جهت بهینه‌سازی مصرف سرور
            payload = {"limit": 10, "timeout": 25}
            if offset:
                payload["offset"] = offset + 1

            response = requests.post(url, json=payload, timeout=30)
            
            if response.status_code != 200:
                print(f"⚠️ Server returned status {response.status_code}. Retrying...")
                time.sleep(5)
                continue

            data = response.json()
            # طبق داکیومنت بات، لیست آپدیت‌ها در کلید result قرار دارد
            updates = data.get("result", [])

            for update in updates:
                # به‌روزرسانی Offset برای جلوگیری از دریافت مجدد پیام‌های قبلی
                offset = update.get("update_id", offset)

                # استخراج اطلاعات پیام (پشتیبانی از پیام‌های معمولی و اینلاین)
                message = update.get("message") or update.get("inline_message")
                if not message:
                    continue

                # استخراج فیلدها طبق ساختار استاندارد بات
                text = message.get("text", "")
                chat_id = message.get("chat", {}).get("id")
                sender_id = message.get("from", {}).get("id")

                if not chat_id or not text:
                    continue

                # پردازش و پاسخ
                reply_text = handle_message(str(sender_id), str(chat_id), text)
                send_message(chat_id, reply_text)

        except requests.exceptions.RequestException as e:
            print(f"📡 Network Error: {e}")
            time.sleep(5)
        except Exception as e:
            print(f"🔥 Unexpected Error: {e}")
            time.sleep(3)

if __name__ == "__main__":
    run_bot()