

import os, re, json, time, asyncio, shutil
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

import db  # ایمپورت ماژول دیتابیس بازنویسی شده

load_dotenv()

# تنظیمات اصلی از فایل .env
API_ID    = int(os.getenv("API_ID", "0"))
API_HASH  = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "0").split(",") if x.strip().isdigit()]

# مسیرهای فایل
BASE_DIR     = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
ARCHIVE_DIR  = BASE_DIR / "archive"
QUEUE_DIR    = BASE_DIR / "queue"
QUEUE_FILE   = QUEUE_DIR / "tasks.jsonl"
STATUS_FILE  = QUEUE_DIR / "status.jsonl"

for d in [DOWNLOAD_DIR, ARCHIVE_DIR, QUEUE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

app = Client("tele2rub_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# دیکشنری‌های وضعیت برای هندل کردن مراحل موقت
awaiting_receipt: dict = {}      # {user_id: order_id}
awaiting_zip_pass: dict = {}     # {user_id: True}

# ═══════════════════════════════════════════════════════════════════════════════
#  ابزارهای کمکی (Helpers)
# ═══════════════════════════════════════════════════════════════════════════════

def progress_bar(pct: float, n=12) -> str:
    """ساخت نوار پیشرفت بصری"""
    filled = int(n * pct / 100)
    return "🔹" * filled + "▫️" * (n - filled)

def pretty_size(size_bytes):
    """تبدیل بایت به فرمت قابل خواندن"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024: return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024

# ═══════════════════════════════════════════════════════════════════════════════
#  کیبوردها (Keyboards)
# ═══════════════════════════════════════════════════════════════════════════════

def main_menu_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 حساب کاربری", callback_data="account"),
         InlineKeyboardButton("💳 خرید حجم / اشتراک", callback_data="buy")],
        [InlineKeyboardButton("🔒 تنظیمات Safe Mode", callback_data="safemode_info")],
        [InlineKeyboardButton("📖 راهنما", callback_data="help"),
         InlineKeyboardButton("💬 پشتیبانی", callback_data="support")]
    ])

def back_home_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back_main")]])

# ═══════════════════════════════════════════════════════════════════════════════
#  هندلرهای دستورات اصلی
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_message(filters.private & filters.command("start"))
async def start_cmd(client, message: Message):
    user = message.from_user
    # ثبت یا آپدیت کاربر در دیتابیس
    db.upsert_user(user.id, user.username, user.first_name, user.last_name)
    
    text = (
        f"سلام **{user.first_name}** عزیز! 👋\n\n"
        "به ربات انتقال فایل **Tele2Rub** خوش آمدی.\n"
        "با این ربات می‌تونی فایل‌های تلگرامی رو با سرعت بالا به روبیکا منتقل کنی.\n\n"
        "🎁 **هدیه ورودی:** ۲۰۰ مگابایت حجم رایگان برای شما فعال شد."
    )
    await message.reply_text(text, reply_markup=main_menu_kb())

@app.on_message(filters.private & filters.command("account"))
async def account_cmd(client, message: Message):
    user_data = db.get_user(message.from_user.id)
    if not user_data: return
    
    used = user_data['bytes_used']
    quota = user_data['bytes_quota']
    rem = max(0, quota - used)
    pct = (used / quota * 100) if quota > 0 else 0
    
    text = (
        "👤 **اطلاعات حساب شما**\n\n"
        f"🆔 آیدی عددی: `{user_data['user_id']}`\n"
        f"📦 سهمیه کل: `{pretty_size(quota)}`\n"
        f"📊 مصرف شده: `{pretty_size(used)}`\n"
        f"🔋 باقی‌مانده: `{pretty_size(rem)}`\n\n"
        f"{progress_bar(pct)} `{pct:.1f}%`"
    )
    await message.reply_text(text, reply_markup=main_menu_kb())

# ═══════════════════════════════════════════════════════════════════════════════
#  هندلر فایل‌های ارسالی (Media Handler)
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_message(filters.private & (filters.document | filters.video | filters.audio))
async def handle_media(client, message: Message):
    user_id = message.from_user.id
    user_data = db.get_user(user_id)
    
    # استخراج اطلاعات فایل
    media = message.document or message.video or message.audio
    file_size = media.file_size
    file_name = media.file_name or "unnamed_file"
    
    # چک کردن سهمیه باقی‌مانده
    if (user_data['bytes_used'] + file_size) > user_data['bytes_quota']:
        await message.reply_text("❌ سهمیه حجم شما کافی نیست. لطفا اشتراک تهیه کنید.", reply_markup=main_menu_kb())
        return

    status_msg = await message.reply_text("⏳ در حال دانلود فایل از تلگرام...")
    
    try:
        # دانلود فایل
        file_path = await message.download(file_name=str(DOWNLOAD_DIR / f"{int(time.time())}_{file_name}"))
        
        # ثبت در دیتابیس و دریافت کد یونیک
        unique_code = db.create_file_record(
            user_id=user_id,
            file_name=file_name,
            file_size=file_size,
            caption=message.caption or ""
        )
        
        # اضافه کردن به صف برای ربات روبیکا (Worker)
        task = {
            "job_id": unique_code,
            "path": file_path,
            "user_id": user_id,
            "status_msg_id": status_msg.id,
            "safe_mode": user_data['safe_mode'],
            "zip_pass": user_data['zip_password']
        }
        
        with open(QUEUE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(task) + "\n")
            
        await status_msg.edit_text(
            f"✅ فایل با موفقیت در صف قرار گرفت.\n\n"
            f"🎫 کد دریافت در روبیکا:\n`{unique_code}`\n\n"
            "این کد را در اکانت روبیکا ارسال کنید."
        )
        
    except Exception as e:
        await status_msg.edit_text(f"❌ خطایی رخ داد: {str(e)}")

# ═══════════════════════════════════════════════════════════════════════════════
#  مدیریت Callback ها
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_callback_query()
async def callback_handler(client, query: CallbackQuery):
    data = query.data
    user_id = query.from_user.id

    if data == "back_main":
        await query.message.edit_text("منوی اصلی ربات:", reply_markup=main_menu_kb())

    elif data == "account":
        # مشابه دستور /account
        user_data = db.get_user(user_id)
        rem = max(0, user_data['bytes_quota'] - user_data['bytes_used'])
        text = f"🔋 باقی‌مانده سهمیه شما: **{pretty_size(rem)}**"
        await query.message.edit_text(text, reply_markup=back_home_kb())

    elif data == "safemode_info":
        user_data = db.get_user(user_id)
        status = "فعال ✅" if user_data['safe_mode'] else "غیرفعال ❌"
        text = (
            f"🔒 **تنظیمات Safe Mode**\n\n"
            f"وضعیت فعلی: {status}\n"
            "در این حالت فایل‌ها قبل از ارسال به روبیکا به صورت ZIP رمزدار در می‌آیند تا از فیلتر شدن جلوگیری شود.\n\n"
            "برای تغییر وضعیت از دستور `/safemode on` یا `/safemode off` استفاده کنید."
        )
        await query.message.edit_text(text, reply_markup=back_home_kb())

    elif data == "support":
        support_id = db.get_setting("support_username", "@Admin")
        await query.message.edit_text(f"💬 برای پشتیبانی به آیدی زیر پیام دهید:\n{support_id}", reply_markup=back_home_kb())

# ═══════════════════════════════════════════════════════════════════════════════
#  بخش ادمین و آمار
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_message(filters.private & filters.command("admin") & filters.user(ADMIN_IDS))
async def admin_panel(client, message: Message):
    stats = db.get_stats()
    text = (
        "📊 **آمار کلی ربات (پنل مدیریت)**\n\n"
        f"👥 تعداد کاربران: {stats['users']}\n"
        f"📁 کل فایل‌های ثبت شده: {stats['files_total']}\n"
        f"✅ فایل‌های تحویل شده: {stats['files_delivered']}\n"
        f"🌐 ترافیک کل مصرفی: {pretty_size(stats['total_traffic'])}\n"
    )
    await message.reply_text(text)

# ═══════════════════════════════════════════════════════════════════════════════
#  اجرای ربات
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Telebot is running...")
    app.run()