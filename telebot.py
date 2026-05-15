"""
telebot.py — ربات تلگرام v۳.۰
بدون باگ، کیبورد کامل، مدیریت فایل، اشتراک و پرداخت
"""

import os
import re
import json
import time
import asyncio
import shutil
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from dotenv import load_dotenv
from pyrogram import Client, filters, idle
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import db

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "0").split(",") if x.strip().isdigit()]

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
ARCHIVE_DIR = BASE_DIR / "archive"
QUEUE_DIR = BASE_DIR / "queue"
QUEUE_FILE = QUEUE_DIR / "tasks.jsonl"
STATUS_FILE = QUEUE_DIR / "status.jsonl"

for d in [DOWNLOAD_DIR, ARCHIVE_DIR, QUEUE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

if not all([API_ID, API_HASH, BOT_TOKEN]):
    raise RuntimeError("❌ API_ID، API_HASH و BOT_TOKEN را در .env تنظیم کن")

app = Client("tele2rub_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# حالت‌های کاربر
awaiting_receipt = {}
awaiting_zip_pass = {}


# ═══════════════════════════════════════════════════════════════════════════════
#  کیبوردها
# ═══════════════════════════════════════════════════════════════════════════════

def main_menu_kb():
    """کیبورد منوی اصلی"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 حساب من", callback_data="account"),
         InlineKeyboardButton("💳 خرید اشتراک", callback_data="buy")],
        [InlineKeyboardButton("📨 ارسال فایل", callback_data="send_file"),
         InlineKeyboardButton("💬 پشتیبانی", callback_data="support")],
        [InlineKeyboardButton("🔒 Safe Mode", callback_data="safemode_info"),
         InlineKeyboardButton("📖 راهنما", callback_data="help")],
    ])


def plans_kb():
    """کیبورد پلن‌های اشتراک"""
    rows = []
    for plan in db.PLANS:
        amt = f"{plan['amount']:,}".replace(",", "،")
        label = f"📦 {plan['name']} | {amt} تومان"
        rows.append([InlineKeyboardButton(label, callback_data=f"plan_{plan['key']}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def back_kb():
    """کیبورد بازگشت"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]])


# ═══════════════════════════════════════════════════════════════════════════════
#  متن‌های پیام
# ═══════════════════════════════════════════════════════════════════════════════

def welcome_text(first_name: str) -> str:
    return (
        f"👋 سلام **{first_name}**!\n\n"
        "خوش اومدی به ربات **Tele2Rub** 🚀\n\n"
        "**📋 امکانات:**\n"
        "• 📤 آپلود فایل از تلگرام به روبیکا\n"
        "• 💳 خرید اشتراک و سهمیه نامحدود\n"
        "• 🔒 رمزگذاری ZIP (Safe Mode)\n"
        "• 📊 مدیریت سهمیه و آمار مصرف\n"
        "• 🎁 ۲۰۰ مگ هدیه برای کاربران جدید\n\n"
        "از دکمه‌های پایین استفاده کن 👇"
    )


def account_text(user) -> str:
    """متن حساب کاربر"""
    remaining = max(0, user["bytes_quota"] - user["bytes_used"])
    pct = min(100, (user["bytes_used"] * 100 / max(user["bytes_quota"], 1)))
    has_paid = db.has_active_paid_plan(user["telegram_id"])
    plan_lbl = user["sub_plan"] if has_paid else "هدیه رایگان"
    
    return (
        f"👤 **حساب شما**\n\n"
        f"🆔 آیدی: `{user['telegram_id']}`\n"
        f"📛 نام: {user['first_name'] or '—'}\n"
        f"🔗 یوزرنیم: @{user['username'] or '—'}\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📦 **سهمیه:**\n"
        f"• پلن: {plan_lbl}\n"
        f"• کل سهمیه: {db.pretty_size(user['bytes_quota'])}\n"
        f"• مصرف شده: {db.pretty_size(user['bytes_used'])}\n"
        f"• باقی‌مانده: {db.pretty_size(remaining)}\n"
        f"• درصد استفاده: {pct:.1f}%\n\n"
        f"📊 کل آپلود: {db.pretty_size(user['total_bytes'])}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  صف فایل‌ها
# ═══════════════════════════════════════════════════════════════════════════════

class QueueManager:
    def __init__(self):
        self._cache = None
        self._mtime = 0

    def all(self):
        """دریافت تمام تسک‌ها"""
        mtime = QUEUE_FILE.stat().st_mtime if QUEUE_FILE.exists() else 0
        if mtime == self._mtime and self._cache is not None:
            return self._cache
        self._cache = []
        if QUEUE_FILE.exists():
            try:
                with open(QUEUE_FILE, encoding="utf-8") as f:
                    self._cache = [json.loads(l) for l in f if l.strip()]
            except Exception:
                self._cache = []
        self._mtime = mtime
        return self._cache

    def push(self, task: dict):
        """اضافه کردن تسک"""
        task.setdefault("job_id", str(int(time.time() * 1000)))
        with open(QUEUE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(task, ensure_ascii=False) + "\n")
        self._cache = None

    def remove(self, job_id=None, message_id=None):
        """حذف تسک"""
        tasks = self.all()
        kept, removed = [], None
        for t in tasks:
            if (job_id and str(t.get("job_id")) == str(job_id)) or \
               (message_id and int(t.get("status_message_id", 0)) == message_id):
                removed = t
            else:
                kept.append(t)
        if removed:
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                f.writelines(json.dumps(t, ensure_ascii=False) + "\n" for t in kept)
            self._cache = None
        return removed


queue = QueueManager()


# ═══════════════════════════════════════════════════════════════════════════════
#  ابزارها
# ═══════════════════════════════════════════════════════════════════════════════

def safe_filename(name: Optional[str]) -> str:
    """تمیزکردن نام فایل"""
    name = (name or "file.bin").strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name)
    return name.rstrip(". ")[:200] or "file.bin"


def get_media(message: Message):
    """دریافت مدیای پیام"""
    for attr in ["document", "video", "audio", "voice", "photo", "animation"]:
        m = getattr(message, attr, None)
        if m:
            return attr, m
    return None, None


# ═══════════════════════════════════════════════════════════════════════════════
#  Callback Handlers
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_callback_query()
async def handle_callback(client: Client, query: CallbackQuery):
    """هندل تمام دکمه‌های inline"""
    data = query.data
    user = query.from_user
    user_id = user.id
    
    # بروزرسانی کاربر
    db.upsert_user(user_id, user.username or "", user.first_name or "", user.last_name or "")
    
    await query.answer()

    # بازگشت به منو اصلی
    if data == "back_main":
        await query.message.edit_text(
            welcome_text(user.first_name or "دوست"),
            reply_markup=main_menu_kb()
        )

    # حساب
    elif data == "account":
        u = db.get_user(user_id)
        if u:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 خرید اشتراک", callback_data="buy"),
                 InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")],
            ])
            await query.message.edit_text(account_text(u), reply_markup=kb)

    # خرید
    elif data == "buy":
        pending = db.get_user_pending_order(user_id)
        if pending:
            await query.message.edit_text(
                f"⚠️ سفارش در انتظار شما:\n\n"
                f"📋 {pending['plan_name']}\n"
                f"💰 {pending['amount']:,} تومان\n"
                f"🎫 کد: `{pending['tx_code']}`\n\n"
                f"رسید پرداخت را ارسال کن.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ لغو سفارش", callback_data=f"cancel_order_{pending['id']}")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")],
                ]),
            )
            awaiting_receipt[user_id] = pending["id"]
            return

        await query.message.edit_text(
            "💳 **خرید اشتراک**\n\nپلن مورد نظر را انتخاب کن:",
            reply_markup=plans_kb(),
        )

    # انتخاب پلن
    elif data.startswith("plan_"):
        plan_key = data[5:]
        plan = next((p for p in db.PLANS if p["key"] == plan_key), None)
        if not plan:
            return
        
        amt = f"{plan['amount']:,}".replace(",", "،")
        await query.message.edit_text(
            f"📋 **تأیید سفارش**\n\n"
            f"📦 {plan['name']}\n"
            f"💰 {amt} تومان\n"
            f"📅 مدت: {plan['days']} روز\n"
            f"🎁 سهمیه: {db.pretty_size(plan['bytes'])}\n\n"
            f"آیا مطمئنی؟",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ تأیید", callback_data=f"confirm_{plan_key}")],
                [InlineKeyboardButton("❌ انصراف", callback_data="buy")],
            ]),
        )

    # تأیید پلن
    elif data.startswith("confirm_"):
        plan_key = data[8:]
        plan = next((p for p in db.PLANS if p["key"] == plan_key), None)
        if not plan:
            return
        
        try:
            tx_code = db.create_order(user_id, plan)
            order = db.get_order(tx_code=tx_code)
            awaiting_receipt[user_id] = order["id"]
            
            card = db.get_setting("card_number", "6037-XXXX-XXXX-XXXX")
            holder = db.get_setting("card_holder", "نام دارنده کارت")
            
            await query.message.edit_text(
                f"💳 **اطلاعات پرداخت**\n\n"
                f"🏦 شماره کارت:\n`{card}`\n\n"
                f"👤 نام دارنده:\n{holder}\n\n"
                f"🎫 **کد پیگیری:**\n`{tx_code}`\n\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"مبلغ {plan['amount']:,} تومان را واریز کن و رسید را اینجا بفرست.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ لغو", callback_data=f"cancel_order_{order['id']}")],
                    [InlineKeyboardButton("🔙 منو", callback_data="back_main")],
                ]),
            )
        except Exception as e:
            await query.message.edit_text(f"❌ خطا: {str(e)}")

    # لغو سفارش
    elif data.startswith("cancel_order_"):
        try:
            order_id = int(data[13:])
            db.reject_order(order_id, "لغو توسط کاربر")
            awaiting_receipt.pop(user_id, None)
            await query.message.edit_text(
                "❌ سفارش لغو شد.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 خرید دوباره", callback_data="buy"),
                     InlineKeyboardButton("🔙 منو", callback_data="back_main")],
                ]),
            )
        except Exception:
            pass

    # راهنما
    elif data == "help":
        await query.message.edit_text(
            f"📖 **راهنای استفاده**\n\n"
            f"۱️⃣ **ارسال فایل:**\n"
            f"فایل را برای ربات بفرست. خودکار آپلود می‌شه.\n\n"
            f"۲️⃣ **دریافت کد یونیک:**\n"
            f"بعد از آپلود، کد ۸ رقمی دریافت می‌کنی.\n\n"
            f"۳️⃣ **دریافت در روبیکا:**\n"
            f"کد را در ربات روبیکا وارد کن.\n\n"
            f"🔒 **Safe Mode:**\n"
            f"`/safemode on` برای رمزگذاری ZIP\n\n"
            f"❓ برای پشتیبانی: /support",
            reply_markup=back_kb(),
        )

    # پشتیبانی
    elif data == "support":
        sup = db.get_setting("support_username", "@admin")
        await query.message.edit_text(
            f"💬 **پشتیبانی**\n\n"
            f"برای کمک، با ما تماس بگیر:\n\n"
            f"{sup}",
            reply_markup=back_kb(),
        )

    # Safe Mode
    elif data == "safemode_info":
        u = db.get_user(user_id)
        if u:
            status = "فعال ✅" if u.get("safe_mode") else "غیرفعال ❌"
            await query.message.edit_text(
                f"🔒 **Safe Mode**\n\n"
                f"وضعیت: {status}\n\n"
                f"فایل‌ها به صورت ZIP رمزدار ارسال می‌شن.\n\n"
                f"برای فعال‌کردن: `/safemode on`\n"
                f"برای غیرفعال: `/safemode off`",
                reply_markup=back_kb(),
            )


# ═══════════════════════════════════════════════════════════════════════════════
#  Command Handlers
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_message(filters.private & filters.command("start"))
async def cmd_start(client: Client, message: Message):
    """دستور /start"""
    user = message.from_user
    db.upsert_user(user.id, user.username or "", user.first_name or "", user.last_name or "")
    await message.reply_text(
        welcome_text(user.first_name or "دوست"),
        reply_markup=main_menu_kb()
    )


@app.on_message(filters.private & filters.command("account"))
async def cmd_account(client: Client, message: Message):
    """دستور /account"""
    user = message.from_user
    db.upsert_user(user.id, user.username or "", user.first_name or "", user.last_name or "")
    u = db.get_user(user.id)
    if u:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💳 خرید اشتراک", callback_data="buy"),
             InlineKeyboardButton("🔙 منو", callback_data="back_main")],
        ])
        await message.reply_text(account_text(u), reply_markup=kb)


@app.on_message(filters.private & filters.command("buy"))
async def cmd_buy(client: Client, message: Message):
    """دستور /buy"""
    user_id = message.from_user.id
    db.upsert_user(user_id, message.from_user.username or "", message.from_user.first_name or "", "")
    
    pending = db.get_user_pending_order(user_id)
    if pending:
        await message.reply_text(
            f"⚠️ سفارش در انتظار:\n\n"
            f"📋 {pending['plan_name']}\n"
            f"🎫 `{pending['tx_code']}`\n\n"
            f"رسید پرداخت را بفرست.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ لغو", callback_data=f"cancel_order_{pending['id']}")],
            ]),
        )
        awaiting_receipt[user_id] = pending["id"]
    else:
        await message.reply_text(
            "💳 **خرید اشتراک**",
            reply_markup=plans_kb(),
        )


@app.on_message(filters.private & filters.command("safemode"))
async def cmd_safemode(client: Client, message: Message):
    """دستور /safemode"""
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    
    if len(args) < 2:
        await message.reply_text("استفاده: `/safemode on` یا `/safemode off`")
        return
    
    action = args[1].strip().lower()
    if action == "on":
        awaiting_zip_pass[user_id] = True
        await message.reply_text("🔒 رمز ZIP را بفرست:")
    elif action == "off":
        db.update_safe_mode(user_id, False)
        await message.reply_text("🔓 Safe Mode غیرفعال شد.")
    else:
        await message.reply_text("دستور نادرست!")


@app.on_message(filters.private & filters.command("stats"))
async def cmd_stats(client: Client, message: Message):
    """دستور /stats برای ادمین"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    stats = db.get_stats()
    await message.reply_text(
        f"📊 **آمار سیستم**\n\n"
        f"👥 کاربران: {stats['total_users']:,}\n"
        f"✅ اشتراک فعال: {stats['active_subs']:,}\n"
        f"📁 فایل‌های آپلود: {stats['total_files']:,}\n"
        f"✅ تحویل‌داده: {stats['delivered']:,}\n"
        f"📦 کل انتقال: {db.pretty_size(stats['total_bytes'])}\n\n"
        f"💰 درآمد کل: {stats['total_revenue']:,} تومان\n"
        f"📈 درآمد امروز: {stats['today_revenue']:,} تومان"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  فایل‌های دریافتی
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_message(filters.private & filters.photo)
async def handle_photo(client: Client, message: Message):
    """دریافت عکس (رسید پرداخت)"""
    user_id = message.from_user.id
    db.upsert_user(user_id, message.from_user.username or "", message.from_user.first_name or "", "")
    
    if user_id not in awaiting_receipt:
        return
    
    order_id = awaiting_receipt[user_id]
    order = db.get_order(order_id=order_id)
    
    if not order or order["status"] != "pending":
        awaiting_receipt.pop(user_id, None)
        await message.reply_text("❌ سفارشی یافت نشد.")
        return
    
    db.set_order_receipt(order_id, message.photo.file_id)
    awaiting_receipt.pop(user_id, None)
    
    await message.reply_text(
        f"✅ **رسید ثبت شد!**\n\n"
        f"کد: `{order['tx_code']}`\n"
        f"در حالی انتظار تأیید ادمین...\n"
        f"معمولاً ۱-۲ ساعت طول می‌کشه."
    )


@app.on_message(
    filters.private &
    (filters.document | filters.video | filters.audio | filters.voice | filters.animation)
)
async def handle_media(client: Client, message: Message):
    """دریافت فایل‌ها"""
    user = message.from_user
    user_id = user.id
    
    db.upsert_user(user_id, user.username or "", user.first_name or "", user.last_name or "")
    
    media_type, media = get_media(message)
    if not media:
        await message.reply_text("❌ فایل قابل پردازش نیست.")
        return
    
    file_size = getattr(media, "file_size", 0) or 0
    ok, reason = db.check_quota(user_id, file_size)
    
    if not ok:
        await message.reply_text(
            reason,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 خرید اشتراک", callback_data="buy")],
            ]),
        )
        return
    
    # دانلود
    status = await message.reply_text("📥 در حال دانلود...")
    
    try:
        file_path = await client.download_media(message, file_name=str(DOWNLOAD_DIR / safe_filename(media.file_name or "file")))
        if not file_path:
            raise RuntimeError("دانلود ناموفق")
        
        local_path = Path(file_path)
        real_size = local_path.stat().st_size
        
        # بررسی مجدد
        ok2, reason2 = db.check_quota(user_id, real_size)
        if not ok2:
            local_path.unlink(missing_ok=True)
            await status.edit_text(reason2)
            return
        
        # کپی به archive
        archive_path = ARCHIVE_DIR / local_path.name
        shutil.copy2(str(local_path), str(archive_path))
        
        # ایجاد رکورد
        unique_code = db.create_file_record(user_id, local_path.name, real_size, str(archive_path))
        db.add_bytes_used(user_id, real_size)
        
        # اضافه به صف
        task = {
            "type": "local_file",
            "path": str(local_path),
            "archive_path": str(archive_path),
            "unique_code": unique_code,
            "chat_id": message.chat.id,
            "telegram_user_id": user_id,
            "status_message_id": status.id,
            "file_name": local_path.name,
            "file_size": real_size,
        }
        queue.push(task)
        
        u = db.get_user(user_id)
        remaining = max(0, u["bytes_quota"] - u["bytes_used"])
        
        await status.edit_text(
            f"✅ **فایل در صف آپلود**\n\n"
            f"📄 {local_path.name}\n"
            f"📦 {db.pretty_size(real_size)}\n\n"
            f"🎫 **کد یونیک:** `{unique_code}`\n\n"
            f"این کد را در ربات روبیکا وارد کن.\n\n"
            f"📊 سهمیه باقی: {db.pretty_size(remaining)}"
        )
        
    except Exception as e:
        await status.edit_text(f"❌ خطا: {str(e)}")


@app.on_message(filters.private & filters.text & ~filters.command())
async def handle_text(client: Client, message: Message):
    """دریافت متن (رمز ZIP)"""
    user_id = message.from_user.id
    text = (message.text or "").strip()
    
    if awaiting_zip_pass.get(user_id):
        if not text or len(text) < 4:
            await message.reply_text("❌ رمز باید حداقل ۴ کاراکتر باشد.")
            return
        
        db.update_safe_mode(user_id, True, text)
        awaiting_zip_pass.pop(user_id, None)
        await message.reply_text("✅ Safe Mode فعال شد و رمز ذخیره گردید.")


# ═══════════════════════════════════════════════════════════════════════════════
#  اجرا
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("▶ شروع ربات تلگرام...")
    db.init_db()
    app.start()
    idle()
    app.stop()