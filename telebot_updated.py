"""
telebot.py — ربات تلگرام (نسخه ۲.۲ - بهبود یافته)
رابط کاربری کامل، مدیریت اشتراک، کیبورد inline جامع
"""

import os, re, json, time, asyncio, shutil
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pyrogram import Client, filters, idle
from pyrogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

import db

load_dotenv()

API_ID    = int(os.getenv("API_ID", "0"))
API_HASH  = os.getenv("API_HASH", "").strip()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "0").split(",") if x.strip().isdigit()]

BASE_DIR     = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
ARCHIVE_DIR  = BASE_DIR / "archive"
QUEUE_DIR    = BASE_DIR / "queue"
QUEUE_FILE   = QUEUE_DIR / "tasks.jsonl"
STATUS_FILE  = QUEUE_DIR / "status.jsonl"

for d in [DOWNLOAD_DIR, ARCHIVE_DIR, QUEUE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("API_ID، API_HASH و BOT_TOKEN را در .env تنظیم کن")

app = Client("tel2rub", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

awaiting_receipt = {}
awaiting_zip_pass = {}

# ═══════════════════════════════════════════════════════════════════════════════
#  ابزارها
# ═══════════════════════════════════════════════════════════════════════════════

def safe_filename(name: Optional[str]) -> str:
    name = (name or "file.bin").strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name)
    name = name.rstrip(". ")
    return name[:200] or "file.bin"

def get_media(message: Message):
    for attr in ["document","video","audio","voice","photo","animation","video_note","sticker"]:
        m = getattr(message, attr, None)
        if m:
            return attr, m
    return None, None

def build_filename(message: Message, media_type: str, media) -> str:
    original = getattr(media, "file_name", None)
    if not original:
        uid = getattr(media, "file_unique_id", None) or "file"
        ext = {"document":".bin","video":".mp4","audio":".mp3","voice":".ogg",
               "photo":".jpg","animation":".mp4","video_note":".mp4","sticker":".webp"}.get(media_type, ".bin")
        original = f"{uid}{ext}"
    original = safe_filename(original)
    p = Path(original)
    return safe_filename(f"{p.stem}_{message.id}{p.suffix or '.bin'}")

def pretty_size(s) -> str:
    return db.pretty_size(s)

def progress_bar(pct: float, n=14) -> str:
    f = int(n * pct / 100)
    return "█" * f + "░" * (n - f)

def eta_text(s) -> str:
    if not s or s <= 0:
        return "نامشخص"
    s = int(s)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h:   return f"{h}h {m}m"
    if m:   return f"{m}m {s}s"
    return f"{s}s"

# ═══════════════════════════════════════════════════════════════════════════════
#  کیبورد‌های inline
# ═══════════════════════════════════════════════════════════════════════════════

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 حساب من", callback_data="account"),
         InlineKeyboardButton("💳 خرید اشتراک", callback_data="buy")],
        [InlineKeyboardButton("📖 راهنما", callback_data="help"),
         InlineKeyboardButton("💬 پشتیبانی", callback_data="support")],
        [InlineKeyboardButton("🔒 Safe Mode", callback_data="safemode_info"),
         InlineKeyboardButton("❌ حذف صف", callback_data="delall")],
    ])

def plans_kb() -> InlineKeyboardMarkup:
    rows = []
    for plan in db.PLANS:
        amt = f"{plan['amount']:,}".replace(",", "،")
        label = f"{plan['name']}  |  {amt} تومان"
        rows.append([InlineKeyboardButton(label, callback_data=f"plan_{plan['key']}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)

def confirm_plan_kb(plan_key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تأیید و پرداخت", callback_data=f"confirm_{plan_key}"),
         InlineKeyboardButton("❌ انصراف", callback_data="buy")],
    ])

# ═══════════════════════════════════════════════════════════════════════════════
#  صف
# ═══════════════════════════════════════════════════════════════════════════════

class QueueManager:
    def __init__(self):
        self._cache = None
        self._mtime = 0

    def all(self):
        mtime = QUEUE_FILE.stat().st_mtime if QUEUE_FILE.exists() else 0
        if mtime == self._mtime and self._cache is not None:
            return self._cache
        self._cache = []
        if QUEUE_FILE.exists():
            with open(QUEUE_FILE, encoding="utf-8") as f:
                self._cache = [json.loads(l) for l in f if l.strip()]
        self._mtime = mtime
        return self._cache

    def push(self, task: dict):
        task.setdefault("job_id", str(int(time.time() * 1000)))
        with open(QUEUE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(task, ensure_ascii=False) + "\n")
        self._cache = None

    def remove(self, job_id=None, message_id=None):
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

    def clear(self):
        with open(QUEUE_FILE, "w", encoding="utf-8") as f:
            pass
        self._cache = None

queue = QueueManager()

# ═══════════════════════════════════════════════════════════════════════════════
#  متن‌های ثابت
# ═══════════════════════════════════════════════════════════════════════════════

def welcome_text(first_name: str) -> str:
    return (
        f"سلام **{first_name}** 👋\n\n"
        "به ربات **Tele2Rub** خوش اومدی!\n\n"
        "🚀 **امکانات:**\n"
        "• انتقال فایل از تلگرام به روبیکا\n"
        "• دریافت فایل‌های عمومی و خصوصی\n"
        "• پشتیبانی از تمام نوع‌های مدیا\n"
        "• تست رایگان ۲۰۰ مگابایت\n"
        "• اشتراک‌های مختلف با قیمت مناسب\n\n"
        "📋 **دستورات سریع:**\n"
        "`/account` — حساب و آمار\n"
        "`/buy` — خرید اشتراک\n"
        "`/safemode on` — فعال‌سازی رمزگذاری\n"
        "`/del [id]` — حذف از صف\n\n"
        "از منوی پایین استفاده کن 👇"
    )

def account_text(user) -> str:
    remaining = max(0, user["bytes_quota"] - user["bytes_used"])
    pct = min(100, user["bytes_used"] * 100 / max(user["bytes_quota"], 1))
    bar = progress_bar(pct, 16)
    has_paid = db.has_active_paid_plan(user["telegram_id"])
    plan_lbl = user["sub_plan"] if has_paid else "هدیه رایگان"
    exp_lbl = db.pretty_time(user["sub_expires"]) if has_paid else "—"
    safe_ico = "🔒" if user.get("safe_mode") else "🔓"
    name = " ".join(filter(None, [user["first_name"], user["last_name"]])) or "—"
    un = f"@{user['username']}" if user["username"] else "—"
    return (
        f"👤 **حساب من**\n\n"
        f"🆔 آیدی: `{user['telegram_id']}`\n"
        f"📛 نام: {name}\n"
        f"🔗 یوزرنیم: {un}\n"
        f"📅 عضویت: {db.pretty_time(user['joined_at'])}\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📦 **مصرف سهمیه**\n"
        f"• پلن فعال: {plan_lbl}\n"
        f"• انقضا: {exp_lbl}\n"
        f"• سهمیه کل: {pretty_size(user['bytes_quota'])}\n"
        f"• مصرف شده: {pretty_size(user['bytes_used'])}\n"
        f"• باقی‌مانده: {pretty_size(remaining)}\n"
        f"`{bar}` `{pct:.1f}%`\n\n"
        f"📊 کل آپلود: {pretty_size(user['total_bytes'])}\n"
        f"{safe_ico} Safe Mode: {'فعال' if user.get('safe_mode') else 'غیرفعال'}"
    )

def help_text() -> str:
    return (
        "📖 **راهنمای کامل**\n\n"
        "**۱. ارسال فایل:**\n"
        "هر فایل، ویدیو یا عکسی رو برای ربات بفرست.\n"
        "ربات آپلود می‌کنه و کد ۸ رقمی بهت می‌ده.\n\n"
        "**۲. دریافت در روبیکا:**\n"
        "کد رو در ربات روبیکا وارد کن.\n\n"
        "**۳. Safe Mode (رمزگذاری):**\n"
        "با `/safemode on` فعال‌سازی کن.\n"
        "فایل‌ها به صورت ZIP رمزدار ارسال می‌شن.\n\n"
        "**۴. مدیریت صف:**\n"
        "`/del [شناسه]` — حذف یک فایل\n"
        "`/delall` — خالی کردن کل صف\n\n"
        "**۵. اشتراک:**\n"
        "برای فایل‌های بزرگ‌تر، اشتراک بخرید."
    )

# ═══════════════════════════════════════════════════════════════════════════════
#  کال‌بک‌ها
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_callback_query()
async def on_callback(client: Client, query: CallbackQuery):
    data = query.data
    user = query.from_user
    user_id = user.id
    db.upsert_user(user_id, user.username or "", user.first_name or "", user.last_name or "")
    await query.answer()

    if data == "back_main":
        await query.message.edit_text(welcome_text(user.first_name), reply_markup=main_menu_kb())

    elif data == "account":
        u = db.get_user(user_id)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("💳 خرید اشتراک", callback_data="buy"),
            InlineKeyboardButton("🔙 بازگشت", callback_data="back_main"),
        ]])
        await query.message.edit_text(account_text(u), reply_markup=kb)

    elif data == "buy":
        pending = db.get_user_pending_order(user_id)
        if pending:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ لغو سفارش", callback_data=f"cancel_order_{pending['id']}"),
                InlineKeyboardButton("🔙 بازگشت", callback_data="back_main"),
            ]])
            await query.message.edit_text(
                f"⚠️ سفارش در انتظار:\n\n"
                f"پلن: **{pending['plan_name']}**\n"
                f"کد: `{pending['tx_code']}`\n\n"
                f"رسید پرداخت رو ارسال کن.",
                reply_markup=kb,
            )
            awaiting_receipt[user_id] = pending["id"]
            return

        await query.message.edit_text(
            "💳 **خرید اشتراک**\n\n"
            "یکی از پلن‌های زیر را انتخاب کن:",
            reply_markup=plans_kb(),
        )

    elif data.startswith("plan_"):
        plan_key = data[5:]
        plan = next((p for p in db.PLANS if p["key"] == plan_key), None)
        if not plan:
            return
        amt = f"{plan['amount']:,}".replace(",", "،")
        sz = pretty_size(plan["bytes"])
        await query.message.edit_text(
            f"📋 **تأیید سفارش**\n\n"
            f"پلن: **{plan['name']} ({sz})**\n"
            f"مبلغ: **{amt} تومان**\n"
            f"مدت: {plan['days']} روز\n\n"
            f"آیا مطمئنی؟",
            reply_markup=confirm_plan_kb(plan_key),
        )

    elif data.startswith("confirm_"):
        plan_key = data[8:]
        plan = next((p for p in db.PLANS if p["key"] == plan_key), None)
        if not plan:
            return
        try:
            tx_code = db.create_order(user_id, plan)
        except Exception as e:
            await query.message.edit_text(f"❌ خطا: {e}")
            return

        order = db.get_user_pending_order(user_id)
        awaiting_receipt[user_id] = order["id"]

        card = db.get_setting("card_number", "6037-XXXX-XXXX-XXXX")
        holder = db.get_setting("card_holder", "نام دارنده")
        amt = f"{plan['amount']:,}".replace(",", "،")

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ لغو", callback_data=f"cancel_order_{order['id']}"),
            InlineKeyboardButton("🔙 بازگشت", callback_data="back_main"),
        ]])

        text = (
            f"💳 **اطلاعات پرداخت**\n\n"
            f"📋 پلن: **{plan['name']}**\n"
            f"💰 مبلغ: **{amt} تومان**\n\n"
            f"🏦 شماره کارت:\n`{card}`\n"
            f"👤 نام دارنده: {holder}\n\n"
            f"🎫 کد پیگیری:\n`{tx_code}`\n\n"
            f"۱. مبلغ را به شماره کارت واریز کن\n"
            f"۲. رسید (عکس یا متن) رو برای ربات بفرست\n\n"
            f"⏳ بعد از تأیید، اشتراک فعال می‌شه."
        )
        await query.message.edit_text(text, reply_markup=kb)

    elif data.startswith("cancel_order_"):
        order_id = int(data[13:])
        db.reject_order(order_id, "لغو توسط کاربر")
        awaiting_receipt.pop(user_id, None)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("💳 خرید مجدد", callback_data="buy")]])
        await query.message.edit_text("❌ سفارش لغو شد.", reply_markup=kb)

    elif data == "help":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]])
        await query.message.edit_text(help_text(), reply_markup=kb)

    elif data == "support":
        sup = db.get_setting("support_username", "@admin")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]])
        await query.message.edit_text(f"💬 **پشتیبانی**\n\n{sup}", reply_markup=kb)

    elif data == "safemode_info":
        u = db.get_user(user_id)
        status = "فعال 🔒" if u.get("safe_mode") else "غیرفعال 🔓"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]])
        await query.message.edit_text(
            f"🔒 **Safe Mode**\n\n"
            f"وضعیت: {status}\n\n"
            f"فایل‌ها به صورت ZIP رمزدار ارسال می‌شن.\n\n"
            f"`/safemode on` — فعال‌سازی\n"
            f"`/safemode off` — غیرفعال",
            reply_markup=kb,
        )

    elif data == "delall":
        tasks = queue.all()
        if not tasks:
            await query.answer("صف خالی است!", show_alert=True)
            return
        queue.clear()
        await query.message.edit_text("✅ صف پاک شد.", reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 بازگشت", callback_data="back_main"),
        ]]))

# ═══════════════════════════════════════════════════════════════════════════════
#  دستورات کاربر
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_message(filters.private & filters.command("start"))
async def start_handler(client: Client, message: Message):
    user = message.from_user
    db.upsert_user(user.id, user.username or "", user.first_name or "", user.last_name or "")
    await message.reply_text(welcome_text(user.first_name), reply_markup=main_menu_kb())

@app.on_message(filters.private & filters.command("account"))
async def account_handler(client: Client, message: Message):
    u = db.get_user(message.from_user.id)
    if not u:
        await message.reply_text("ابتدا /start بزن.")
        return
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("💳 خرید", callback_data="buy"),
        InlineKeyboardButton("🏠 منو", callback_data="back_main"),
    ]])
    await message.reply_text(account_text(u), reply_markup=kb)

@app.on_message(filters.private & filters.command("sub"))
async def sub_handler(client: Client, message: Message):
    u = db.get_user(message.from_user.id)
    if not u:
        await message.reply_text("ابتدا /start بزن.")
        return
    remaining = max(0, u["bytes_quota"] - u["bytes_used"])
    if db.has_active_paid_plan(message.from_user.id):
        await message.reply_text(
            f"✅ پلن: **{u['sub_plan']}**\n"
            f"⏳ انقضا: `{db.pretty_time(u['sub_expires'])}`\n"
            f"📦 باقی: `{pretty_size(remaining)}`"
        )
    else:
        await message.reply_text(
            f"📦 هدیه رایگان: `{pretty_size(remaining)}` باقی\n\n"
            f"برای خرید: /buy",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💳 خرید اشتراک", callback_data="buy"),
            ]]),
        )

@app.on_message(filters.private & filters.command("safemode"))
async def safemode_handler(client: Client, message: Message):
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("استفاده: `/safemode on` یا `/safemode off`")
        return
    action = args[1].strip().lower()
    if action == "on":
        awaiting_zip_pass[user_id] = True
        await message.reply_text("🔒 رمز ZIP رو بفرست:")
    elif action == "off":
        db.update_safe_mode(user_id, False)
        awaiting_zip_pass.pop(user_id, None)
        await message.reply_text("🔓 Safe Mode غیرفعال شد.")
    else:
        await message.reply_text("دستور نادرست.")

@app.on_message(filters.private & filters.command("del"))
async def delete_handler(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    job_id = parts[1].strip() if len(parts) > 1 else None
    tasks = queue.all()
    if not tasks:
        await message.reply_text("صف خالی است.")
        return
    removed = queue.remove(job_id=job_id)
    if removed:
        await message.reply_text("✅ از صف حذف شد.")
    else:
        await message.reply_text("❌ پیدا نشد.")

@app.on_message(filters.private & filters.command("delall"))
async def delall_handler(client: Client, message: Message):
    queue.clear()
    await message.reply_text("✅ صف خالی شد.")

# ═══════════════════════════════════════════════════════════════════════════════
#  دستورات ادمین
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_message(filters.private & filters.command("stats"))
async def stats_handler(client: Client, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    s = db.get_stats()
    await message.reply_text(
        f"📊 **آمار**\n\n"
        f"👥 کاربران: {s['total_users']:,}\n"
        f"✅ اشتراک فعال: {s['active_subs']:,}\n"
        f"📁 فایل‌ها: {s['total_files']:,}\n"
        f"✅ تحویل‌شده: {s['delivered']:,}\n"
        f"📦 کل انتقال: {pretty_size(s['total_bytes'])}\n\n"
        f"💰 **فروش**\n"
        f"• تأییدشده: {s['approved_count']:,}\n"
        f"• درآمد: {s['total_revenue']:,} تومان\n"
        f"• امروز: {s['today_revenue']:,} تومان"
    )

@app.on_message(filters.private & filters.command("approve"))
async def approve_handler(client: Client, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply_text("استفاده: `/approve ORDER_ID`")
        return
    try:
        order_id = int(parts[1])
    except ValueError:
        await message.reply_text("فرمت نادرست.")
        return
    order = db.get_order(order_id=order_id)
    if not order:
        await message.reply_text("❌ سفارش پیدا نشد.")
        return
    if db.approve_order(order_id):
        await message.reply_text(f"✅ سفارش #{order_id} تأیید شد.")
        try:
            await client.send_message(
                order["telegram_id"],
                f"🎉 اشتراک شما فعال شد!\n\n"
                f"📋 پلن: **{order['plan_name']}**\n"
                f"📦 سهمیه: {pretty_size(order['plan_bytes'])}\n"
                f"⏳ مدت: {order['plan_days']} روز"
            )
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════════════════
#  رسید پرداخت (عکس)
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_message(filters.private & filters.photo)
async def photo_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in awaiting_receipt:
        await message.reply_text("❓ در حال حاضر تمام سفارش‌ها تأیید شده‌اند.")
        return
    order_id = awaiting_receipt[user_id]
    db.set_order_receipt(order_id, message.photo.file_id)
    awaiting_receipt.pop(user_id, None)
    await message.reply_text("✅ رسید ثبت شد.\n⏳ منتظر تأیید ادمین...")
    for admin_id in ADMIN_IDS:
        try:
            await client.send_photo(
                admin_id, message.photo.file_id,
                caption=f"🔔 رسید جدید برای سفارش #{order_id}"
            )
        except Exception:
            pass

# ═══════════════════════════════════════════════════════════════════════════════
#  رمز ZIP
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_message(filters.private & filters.text & ~filters.command())
async def text_handler(client: Client, message: Message):
    user = message.from_user
    db.upsert_user(user.id, user.username or "", user.first_name or "", user.last_name or "")
    
    if awaiting_zip_pass.get(user.id):
        text = (message.text or "").strip()
        if not text:
            await message.reply_text("رمز نمی‌تواند خالی باشد.")
            return
        db.update_safe_mode(user.id, True, text)
        awaiting_zip_pass.pop(user.id, None)
        await message.reply_text("✅ Safe Mode فعال شد.")

# ═══════════════════════════════════════════════════════════════════════════════
#  مدیا (فایل‌ها)
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_message(
    filters.private &
    (filters.document | filters.video | filters.audio | filters.voice |
     filters.animation | filters.video_note | filters.sticker)
)
async def media_handler(client: Client, message: Message):
    user = message.from_user
    db.upsert_user(user.id, user.username or "", user.first_name or "", user.last_name or "")

    media_type, media = get_media(message)
    if not media:
        await message.reply_text("فایل قابل پردازش نیست.")
        return

    file_size = getattr(media, "file_size", 0) or 0
    ok, reason = db.check_quota(user.id, file_size)
    if not ok:
        await message.reply_text(reason, reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("💳 خرید اشتراک", callback_data="buy"),
        ]]))
        return

    download_name = build_filename(message, media_type, media)
    download_path = DOWNLOAD_DIR / download_name
    status = await message.reply_text("📥 درحال دانلود...")

    try:
        downloaded = await client.download_media(message, file_name=str(download_path))
        if not downloaded:
            raise RuntimeError("دانلود ناموفق.")
        
        dl_path = Path(downloaded)
        real_size = dl_path.stat().st_size
        
        ok2, reason2 = db.check_quota(user.id, real_size)
        if not ok2:
            dl_path.unlink(missing_ok=True)
            await status.edit_text(reason2)
            return

        archive_path = ARCHIVE_DIR / download_name
        shutil.copy2(str(dl_path), str(archive_path))

        unique_code = db.create_file_record(
            telegram_user_id=user.id,
            file_name=download_name,
            file_size=real_size,
            archive_path=str(archive_path),
        )
        db.add_bytes_used(user.id, real_size)

        u = db.get_user(user.id)
        task = {
            "type": "local_file",
            "path": str(dl_path),
            "archive_path": str(archive_path),
            "unique_code": unique_code,
            "caption": message.caption or "",
            "chat_id": message.chat.id,
            "telegram_user_id": user.id,
            "status_message_id": status.id,
            "file_name": download_name,
            "file_size": real_size,
            "safe_mode": bool(u.get("safe_mode")),
            "zip_password": u.get("zip_password", ""),
        }
        queue.push(task)

        remaining = max(0, u["bytes_quota"] - u["bytes_used"])
        rub_bot = db.get_setting("bot_username", "@YourRubikaBot")
        await status.edit_text(
            f"✅ **در صف آپلود**\n\n"
            f"📄 `{download_name}`\n"
            f"📦 {pretty_size(real_size)}\n"
            f"🎫 کد: **`{unique_code}`**\n\n"
            f"🤖 در {rub_bot} این کد رو بفرست\n\n"
            f"📊 باقی: {pretty_size(remaining)}\n"
            f"ID: `{task['job_id']}`"
        )
    except Exception as e:
        await status.edit_text(f"❌ خطا: {str(e)}")

# ═══════════════════════════════════════════════════════════════════════════════
#  اجرا
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app.start()
    idle()
    app.stop()
