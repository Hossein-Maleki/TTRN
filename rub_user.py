import os
import json
import asyncio
import re
from pathlib import Path
from dotenv import load_dotenv
from rubpy import Client, filters
from rubpy.types import Updates

import db  # متصل به دیتابیس بازنویسی شده

load_dotenv()

# تنظیمات اصلی از .env
SESSION = os.getenv("RUBIKA_SESSION", "session_name").strip()
STORAGE_CHANNEL_GUID = os.getenv("RUBIKA_CHANNEL_GUID", "").strip()

BASE_DIR = Path(__file__).resolve().parent
QUEUE_FILE = BASE_DIR / "queue" / "tasks.jsonl"
STATUS_FILE = BASE_DIR / "queue" / "status.jsonl"

# الگوی شناسایی کد ۸ رقمی (فقط اعداد و حروف بزرگ)
CODE_PATTERN = re.compile(r"^[A-Z0-9]{8}$")

# مقداردهی اولیه کلاینت روبیکا (Userbot)
app = Client(SESSION)

def update_tg_status(task: dict, text: str):
    """ارسال وضعیت پیشرفت به ربات تلگرام از طریق فایل وضعیت"""
    payload = {
        "chat_id": task.get("chat_id"),
        "message_id": task.get("status_msg_id"),
        "text": text
    }
    with open(STATUS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")

# ═══════════════════════════════════════════════════════════════════════════════
#  بخش اول: پردازشگر صف آپلود (Background Task)
# ═══════════════════════════════════════════════════════════════════════════════

async def upload_worker():
    """وظیفه آپلود فایل‌ها در کانال ذخیره‌سازی و ثبت آیدی پیام"""
    print("🚀 ورکر آپلود روبیکا فعال شد.")
    while True:
        await asyncio.sleep(2)
        
        if not QUEUE_FILE.exists():
            continue
            
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        if not lines:
            continue
            
        # برداشتن اولین تسک از صف
        task_raw = lines[0].strip()
        if not task_raw: continue
        task = json.loads(task_raw)
        
        # حذف تسک پردازش شده از فایل
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines[1:])
            
        try:
            file_path = task['path']
            unique_code = task['job_id']
            
            update_tg_status(task, "📤 در حال آپلود فایل در سرورهای روبیکا...")
            
            # آپلود فایل در کانال ذخیره‌سازی
            # نکته: در Userbot از send_file یا send_document استفاده می‌شود
            send_result = await app.send_document(
                STORAGE_CHANNEL_GUID,
                file_path,
                caption=f"📂 File: {task['file_name']}\n🎫 Code: {unique_code}"
            )
            
            # استخراج Message ID برای فوروارد بعدی
            # در rubpy معمولاً در آبجکت پیام بازگشتی موجود است
            msg_id = send_result.message_id
            
            # آپدیت دیتابیس: ثبت GUID کانال و آیدی پیام
            db.update_rubika_info(unique_code, STORAGE_CHANNEL_GUID, msg_id)
            
            update_tg_status(task, f"✅ آپلود کامل شد.\n🎫 کد دریافت: `{unique_code}`")
            print(f"✨ فایل {unique_code} با موفقیت آپلود و ثبت شد.")
            
            # حذف فایل محلی برای آزاد سازی فضا
            if os.path.exists(file_path):
                os.remove(file_path)
                
        except Exception as e:
            print(f"❌ خطا در ورکر آپلود: {e}")
            update_tg_status(task, f"❌ خطای آپلود در روبیکا: {str(e)}")

# ═══════════════════════════════════════════════════════════════════════════════
#  بخش دوم: هندلر پیام‌های دریافتی (تحویل فایل با کد)
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_message(filters.is_private)
async def on_code_received(client: Client, message):
    text = (message.text or "").strip().upper()
    
    # اگر کاربر کد ۸ رقمی فرستاد
    if CODE_PATTERN.match(text):
        file_data = db.get_file_by_code(text)
        
        if not file_data:
            await message.reply("❌ متأسفم، این کد در سیستم یافت نشد.")
            return
            
        if file_data['status'] == 'pending':
            await message.reply("⏳ فایل شما هنوز در حال آپلود است. لطفا دقایقی دیگر تلاش کنید.")
            return
            
        try:
            # مکانیزم اصلی: فوروارد فایل از کانال ذخیره‌سازی به پی‌وی کاربر
            await client.forward_messages(
                from_object_guid=file_data['rubika_channel_guid'],
                message_ids=[int(file_data['rubika_message_id'])],
                to_object_guid=message.author_guid
            )
            
            # ثبت وضعیت تحویل در دیتابیس
            db.mark_delivered(text)
            print(f"✅ فایل با کد {text} به کاربر تحویل داده شد.")
            
        except Exception as e:
            await message.reply("❌ خطا در ارسال فایل. لطفا به پشتیبانی اطلاع دهید.")
            print(f"❌ خطا در فوروارد فایل: {e}")
    
    elif text == "/START":
        await message.reply("سلام! خوش آمدید.\nلطفاً کد ۸ رقمی دریافت فایل را اینجا ارسال کنید.")

# ═══════════════════════════════════════════════════════════════════════════════
#  اجرای همزمان ورکر و کلاینت
# ═══════════════════════════════════════════════════════════════════════════════

async def main():
    # اجرای ورکر آپلود در پس‌زمینه
    asyncio.create_task(upload_worker())
    
    # شروع به کار اکانت برای دریافت پیام‌ها
    print("🤖 اکانت روبیکا آماده دریافت کدهاست...")
    await app.run_until_disconnected()

if __name__ == "__main__":
    try:
        app.run(main())
    except KeyboardInterrupt:
        pass