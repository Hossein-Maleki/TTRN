 """
telebot.py — ربات تلگرام
نسخه ۲.۱ — پروفایل کاربری، اشتراک، خرید، مدیریت ادمین، منوی inline
"""

import os, re, json, time, asyncio, shutil
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)
from pyrogram import idle

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
CANCEL_FILE  = QUEUE_DIR / "cancelled.jsonl"
DELETED_FILE = QUEUE_DIR / "deleted.jsonl"

for d in [DOWNLOAD_DIR, ARCHIVE_DIR, QUEUE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("API_ID، API_HASH و BOT_TOKEN را در .env تنظیم کن")

app = Client("tel2rub", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# حالت در حال انتظار رسید پرداخت {user_id: order_id}
awaiting_receipt: dict = {}
# حالت در حال انتظار رمز ZIP {user_id: True}
awaiting_zip_pass: dict = {}
# حالت ادمین منتظر توکن کارت / شماره کارت {user_id: field_name}
awaiting_admin_input: dict = {}


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
        [InlineKeyboardButton("🔒 Safe Mode", callback_data="safemode_info")],
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


def cancel_order_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ لغو سفارش", callback_data=f"cancel_order_{order_id}")],
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


queue = QueueManager()


def mark_deleted(task: dict):
    with open(DELETED_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(task, ensure_ascii=False) + "\n")


def cancel_job(job_id: str):
    with open(CANCEL_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"job_id": str(job_id)}, ensure_ascii=False) + "\n")


def was_deleted(job_id=None, message_id=None) -> bool:
    if not DELETED_FILE.exists():
        return False
    with open(DELETED_FILE, encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            item = json.loads(line)
            if job_id and str(item.get("job_id")) == str(job_id): return True
            if message_id and int(item.get("status_message_id", 0)) == message_id: return True
    return False


# ═══════════════════════════════════════════════════════════════════════════════
#  پیشرفت دانلود
# ═══════════════════════════════════════════════════════════════════════════════

async def download_progress(current, total, status_msg, file_name, started_at, state):
    now = time.time()
    if now - state.get("last_update", 0) < 3 and current < total:
        return
    state["last_update"] = now
    percent = current * 100 / total if total else 0
    elapsed = max(now - started_at, 1)
    speed   = current / elapsed
    eta     = (total - current) / speed if speed else None
    text = (
        f"📥 **دریافت از تلگرام**\n\n"
        f"فایل: `{file_name}`\n"
        f"حجم: `{pretty_size(total)}`\n"
        f"`{progress_bar(percent)}` `{percent:.1f}%`\n"
        f"سرعت: `{pretty_size(speed)}/s` | مانده: `{eta_text(eta)}`"
    )
    try:
        await status_msg.edit_text(text)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
#  ناظر وضعیت (از rub_worker)
# ═══════════════════════════════════════════════════════════════════════════════

async def status_watcher():
    pos = 0
    while True:
        await asyncio.sleep(1)
        if not STATUS_FILE.exists():
            continue
        try:
            with open(STATUS_FILE, encoding="utf-8") as f:
                f.seek(pos)
                lines = f.readlines()
                pos = f.tell()
            for line in lines:
                if not line.strip(): continue
                data = json.loads(line)
                chat_id = data.get("chat_id")
                msg_id  = data.get("message_id")
                text    = data.get("text", "")
                pct     = data.get("percent")
                if not chat_id or not msg_id: continue
                if pct is not None:
                    text += f"\n\n`{progress_bar(float(pct))}` `{float(pct):.1f}%`"
                try:
                    await app.edit_message_text(chat_id, msg_id, text)
                except Exception:
                    pass
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════════
#  متن‌های ثابت
# ═══════════════════════════════════════════════════════════════════════════════

def welcome_text(first_name: str) -> str:
    return (
        f"سلام **{first_name}** 👋\n\n"
        "به ربات **Tele2Rub** خوش اومدی!\n\n"
        "🚀 **امکانات:**\n"
        "• انتقال فایل از تلگرام به روبیکا\n"
        "• دریافت پست‌های عمومی و خصوصی\n"
        "• جستجو و دریافت پست از کانال‌های تلگرام\n"
        "• دریافت آخرین پست‌های کانال\n"
        "• پشتیبانی از عکس، ویدیو، موزیک، ویس، گیف و فایل\n"
        "• تست رایگان تا ۲۰ مگابایت\n"
        "• هدیه ۲۰۰ مگابایت برای همه کاربران جدید 🎁\n\n"
        "📋 **دستورات سریع:**\n"
        "`/account` — حساب و آمار مصرف\n"
        "`/buy` — خرید اشتراک\n"
        "`/safemode on` — رمزگذاری ZIP\n"
        "`/del [id]` — حذف از صف\n\n"
        "از منوی پایین استفاده کن 👇"
    )


def help_text() -> str:
    return (
        "📖 **راهنمای کامل ربات**\n\n"
        "**ارسال فایل:**\n"
        "فایل، ویدیو، عکس، صدا یا هر مدیا رو برای ربات بفرست.\n"
        "ربات آپلود می‌کنه و کد ۸ رقمی بهت می‌ده.\n\n"
        "**دریافت در روبیکا:**\n"
        "کد ۸ رقمی رو در ربات روبیکا وارد کن.\n\n"
        "**لینک تلگرام:**\n"
        "در ربات روبیکا لینک پست ارسال کن:\n"
        "`https://t.me/channel/1234`\n\n"
        "**کانال خصوصی:**\n"
        "اول لینک دعوت را بفرست:\n"
        "`https://t.me/+invite_code`\n"
        "سپس لینک پست:\n"
        "`https://t.me/c/123456/55`\n\n"
        "**جستجو در کانال:**\n"
        "`/search @channel کلمه`\n\n"
        "**گرفتن پست مشخص:**\n"
        "`/getpost @channel 1234`\n\n"
        "**آخرین پست‌ها:**\n"
        "`/latest @channel`\n\n"
        "**Safe Mode:**\n"
        "فایل رو ZIP رمزدار می‌کنه:\n"
        "`/safemode on` → رمز رو بفرست\n"
        "`/safemode off` → غیرفعال\n\n"
        "**پلن‌های اشتراک:**\n"
        "هر پلن ۳۰ روزه است:\n"
    ) + "\n".join(f"• {db.pretty_size(p['bytes'])} — {p['amount']:,} تومان".replace(",","،") for p in db.PLANS)


def account_text(user) -> str:
    remaining = max(0, user["bytes_quota"] - user["bytes_used"])
    pct       = min(100, user["bytes_used"] * 100 / max(user["bytes_quota"], 1))
    bar       = progress_bar(pct, 16)
    has_paid  = db.has_active_paid_plan(user["telegram_id"])
    plan_lbl  = user["sub_plan"] if has_paid else "هدیه رایگان"
    exp_lbl   = db.pretty_time(user["sub_expires"]) if has_paid else "—"
    safe_ico  = "🔒" if user.get("safe_mode") else "🔓"
    name = " ".join(filter(None, [user["first_name"], user["last_name"]])) or "—"
    un   = f"@{user['username']}" if user["username"] else "—"
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


def payment_text(plan: dict, tx_code: str) -> str:
    amt = f"{plan['amount']:,}".replace(",", "،")
    sz  = pretty_size(plan["bytes"])
    card = db.get_setting("card_number", "—")
    holder = db.get_setting("card_holder", "—")
    return (
        f"💳 **اطلاعات پرداخت**\n\n"
        f"📋 پلن: **{plan['name']} — {sz}**\n"
        f"💰 مبلغ: **{amt} تومان**\n"
        f"⏳ اعتبار: {plan['days']} روز\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🏦 شماره کارت:\n`{card}`\n"
        f"👤 نام دارنده: {holder}\n\n"
        f"🎫 **کد پیگیری تراکنش:**\n"
        f"`{tx_code}`\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"⚠️ **مراحل پرداخت:**\n"
        f"۱. مبلغ را به شماره کارت بالا واریز کن\n"
        f"۲. کد پیگیری را در توضیحات انتقال وارد کن\n"
        f"۳. تصویر رسید را همین‌جا برای ربات بفرست\n\n"
        f"🔔 بعد از تأیید ادمین، اشتراک فعال می‌شه."
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  هندلرهای Callback
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_callback_query()
async def on_callback(client: Client, query: CallbackQuery):
    data    = query.data
    user    = query.from_user
    user_id = user.id
    db.upsert_user(user_id, user.username or "", user.first_name or "", user.last_name or "")

    await query.answer()

    # ─── بازگشت به منوی اصلی ─────────────────────────────────────────────────
    if data == "back_main":
        await query.message.edit_text(
            welcome_text(user.first_name),
            reply_markup=main_menu_kb()
        )

    # ─── حساب من ─────────────────────────────────────────────────────────────
    elif data == "account":
        u = db.get_user(user_id)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("💳 خرید اشتراک", callback_data="buy"),
            InlineKeyboardButton("🔙 بازگشت", callback_data="back_main"),
        ]])
        await query.message.edit_text(account_text(u), reply_markup=kb)

    # ─── خرید اشتراک ─────────────────────────────────────────────────────────
    elif data == "buy":
        pending = db.get_user_pending_order(user_id)
        if pending:
            await query.message.edit_text(
                f"⚠️ یه سفارش در انتظار داری:\n\n"
                f"پلن: **{pending['plan_name']}**\n"
                f"کد: `{pending['tx_code']}`\n\n"
                f"رسید رو ارسال کن یا سفارش رو لغو کن.",
                reply_markup=cancel_order_kb(pending["id"]),
            )
            awaiting_receipt[user_id] = pending["id"]
            return

        await query.message.edit_text(
            "💳 **خرید اشتراک**\n\n"
            "یکی از پلن‌های زیر رو انتخاب کن:\n"
            "همه پلن‌ها ۳۰ روزه هستند و بعد از تأیید رسید فعال می‌شن.",
            reply_markup=plans_kb(),
        )

    # ─── انتخاب پلن ──────────────────────────────────────────────────────────
    elif data.startswith("plan_"):
        plan_key = data[5:]
        plan = next((p for p in db.PLANS if p["key"] == plan_key), None)
        if not plan:
            return
        amt = f"{plan['amount']:,}".replace(",", "،")
        sz  = pretty_size(plan["bytes"])
        await query.message.edit_text(
            f"📋 **تأیید سفارش**\n\n"
            f"پلن: **{plan['name']} ({sz})**\n"
            f"مبلغ: **{amt} تومان**\n"
            f"مدت: {plan['days']} روز\n\n"
            f"آیا مطمئنی؟",
            reply_markup=confirm_plan_kb(plan_key),
        )

    # ─── تأیید و ساخت سفارش ──────────────────────────────────────────────────
    elif data.startswith("confirm_"):
        plan_key = data[8:]
        plan = next((p for p in db.PLANS if p["key"] == plan_key), None)
        if not plan:
            return
        try:
            tx_code = db.create_order(user_id, plan)
        except Exception as e:
            await query.message.edit_text(f"❌ خطا در ثبت سفارش: {e}")
            return

        awaiting_receipt[user_id] = db.get_user_pending_order(user_id)["id"]
        await query.message.edit_text(
            payment_text(plan, tx_code),
            reply_markup=cancel_order_kb(awaiting_receipt[user_id]),
        )

    # ─── لغو سفارش ────────────────────────────────────────────────────────────
    elif data.startswith("cancel_order_"):
        order_id = int(data[13:])
        db.reject_order(order_id, "لغو توسط کاربر")
        awaiting_receipt.pop(user_id, None)
        await query.message.edit_text(
            "❌ سفارش لغو شد.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💳 خرید مجدد", callback_data="buy"),
                InlineKeyboardButton("🔙 منو اصلی", callback_data="back_main"),
            ]]),
        )

    # ─── راهنما ───────────────────────────────────────────────────────────────
    elif data == "help":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]])
        await query.message.edit_text(help_text(), reply_markup=kb)

    # ─── پشتیبانی ─────────────────────────────────────────────────────────────
    elif data == "support":
        sup = db.get_setting("support_username", "@admin")
        kb  = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back_main")]])
        await query.message.edit_text(
            f"💬 **پشتیبانی**\n\n"
            f"برای ارتباط با پشتیبانی:\n{sup}",
            reply_markup=kb,
        )

    # ─── اطلاعات Safe Mode ───────────────────────────────────────────────────
    elif data == "safemode_info":
        u = db.get_user(user_id)
        status = "فعال 🔒" if u.get("safe_mode") else "غیرفعال 🔓"
        await query.message.edit_text(
            f"🔒 **Safe Mode**\n\n"
            f"وضعیت فعلی: {status}\n\n"
            f"با فعال بودن این حالت، فایل‌ها به صورت ZIP رمزدار ارسال می‌شن.\n\n"
            f"برای فعال‌سازی: `/safemode on`\n"
            f"برای غیرفعال: `/safemode off`",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 بازگشت", callback_data="back_main"),
            ]]),
        )


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
    db.upsert_user(message.from_user.id, message.from_user.username or "",
                   message.from_user.first_name or "", message.from_user.last_name or "")
    u = db.get_user(message.from_user.id)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("💳 خرید اشتراک", callback_data="buy"),
        InlineKeyboardButton("🏠 منوی اصلی", callback_data="back_main"),
    ]])
    await message.reply_text(account_text(u), reply_markup=kb)


@app.on_message(filters.private & filters.command("profile"))
async def profile_handler(client: Client, message: Message):
    await account_handler(client, message)


@app.on_message(filters.private & filters.command("buy"))
async def buy_handler(client: Client, message: Message):
    user_id = message.from_user.id
    db.upsert_user(user_id, message.from_user.username or "",
                   message.from_user.first_name or "", message.from_user.last_name or "")
    pending = db.get_user_pending_order(user_id)
    if pending:
        awaiting_receipt[user_id] = pending["id"]
        await message.reply_text(
            f"⚠️ سفارش قبلی در انتظار:\n\nپلن: **{pending['plan_name']}**\nکد: `{pending['tx_code']}`\n\nرسید پرداخت را بفرست.",
            reply_markup=cancel_order_kb(pending["id"]),
        )
        return
    await message.reply_text(
        "💳 **خرید اشتراک** — پلن مورد نظر را انتخاب کن:",
        reply_markup=plans_kb(),
    )


@app.on_message(filters.private & filters.command("sub"))
async def sub_handler(client: Client, message: Message):
    u = db.get_user(message.from_user.id)
    if not u:
        await message.reply_text("ابتدا /start بزن.")
        return
    has_paid = db.has_active_paid_plan(message.from_user.id)
    remaining = max(0, u["bytes_quota"] - u["bytes_used"])
    if has_paid:
        await message.reply_text(
            f"✅ پلن فعال: **{u['sub_plan']}**\n"
            f"⏳ انقضا: `{db.pretty_time(u['sub_expires'])}`\n"
            f"📦 باقی‌مانده: `{pretty_size(remaining)}`"
        )
    else:
        await message.reply_text(
            f"📦 هدیه رایگان: `{pretty_size(remaining)}` باقی‌مانده\n\n"
            f"برای خرید اشتراک: /buy",
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
        await message.reply_text("🔒 Safe Mode فعال شد.\n\nرمز ZIP مورد نظرت رو بفرست:")
    elif action == "off":
        db.update_safe_mode(user_id, False)
        awaiting_zip_pass.pop(user_id, None)
        await message.reply_text("🔓 Safe Mode غیرفعال شد.")
    else:
        await message.reply_text("دستور نادرست. استفاده: `/safemode on` یا `/safemode off`")


# ═══════════════════════════════════════════════════════════════════════════════
#  دستورات ادمین
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_message(filters.private & filters.command("orders"))
async def orders_handler(client: Client, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split()
    status = parts[1] if len(parts) > 1 else "pending"
    if status not in ("pending", "approved", "rejected", "all"):
        status = "pending"
    orders = db.get_orders_by_status(None if status == "all" else status, limit=15)
    if not orders:
        await message.reply_text(f"📋 هیچ سفارشی با وضعیت `{status}` وجود ندارد.")
        return
    lines = [f"📋 **سفارش‌ها — {status}** ({len(orders)} مورد)\n"]
    for o in orders:
        icon = {"pending": "🟡", "approved": "✅", "rejected": "❌"}.get(o["status"], "⚪")
        name = o["first_name"] or str(o["telegram_id"])
        receipt = "✅" if o["receipt_file_id"] else "❌"
        lines.append(
            f"{icon} **#{o['id']}** | {name} (`{o['telegram_id']}`)\n"
            f"   پلن: {o['plan_name']} | {o['amount']:,} تومان | رسید: {receipt}\n"
            f"   کد: `{o['tx_code']}` | تاریخ: {db.pretty_time(o['created_at'])}\n"
            f"   `/approve {o['id']}` | `/reject {o['id']} علت`\n"
        )
    await message.reply_text("\n".join(lines))


@app.on_message(filters.private & filters.command("approve"))
async def approve_handler(client: Client, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        await message.reply_text("استفاده: `/approve ORDER_ID [یادداشت]`")
        return
    try:
        order_id = int(parts[1])
        note = parts[2] if len(parts) > 2 else ""
    except ValueError:
        await message.reply_text("فرمت نادرست.")
        return

    order = db.get_order(order_id=order_id)
    if not order:
        await message.reply_text("❌ سفارش پیدا نشد.")
        return
    if db.approve_order(order_id, note):
        await message.reply_text(f"✅ سفارش #{order_id} تأیید شد و اشتراک فعال گردید.")
        # اطلاع‌رسانی به کاربر
        try:
            u = db.get_user(order["telegram_id"])
            await client.send_message(
                order["telegram_id"],
                f"🎉 **اشتراک شما فعال شد!**\n\n"
                f"📋 پلن: **{order['plan_name']}**\n"
                f"📦 سهمیه: {pretty_size(order['plan_bytes'])}\n"
                f"⏳ انقضا: {db.pretty_time(u['sub_expires'])}\n\n"
                f"✨ از ربات لذت ببر!",
            )
        except Exception:
            pass
    else:
        await message.reply_text("❌ تأیید ناموفق (شاید قبلاً بررسی شده).")


@app.on_message(filters.private & filters.command("stats"))
async def stats_handler(client: Client, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    s = db.get_stats()
    await message.reply_text(
        f"📊 **آمار کامل ربات**\n\n"
        f"👥 کاربران: {s['total_users']:,}\n"
        f"✅ اشتراک فعال: {s['active_subs']:,}\n"
        f"📁 فایل‌های آپلودشده: {s['total_files']:,}\n"
        f"✅ تحویل‌داده‌شده: {s['delivered']:,}\n"
        f"📦 کل انتقال: {pretty_size(s['total_bytes'])}\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💰 **فروش**\n"
        f"• سفارش‌های تأییدشده: {s['approved_count']:,}\n"
        f"• درآمد کل: {s['total_revenue']:,} تومان\n"
        f"• درآمد امروز: {s['today_revenue']:,} تومان\n"
        f"• سفارش‌های معلق: {s['pending_orders']:,}\n\n"
        f"🔔 برای مشاهده سفارش‌ها: `/orders`"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  حذف از صف
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_message(filters.private & filters.command("delall"))
async def clear_queue_handler(client: Client, message: Message):
    tasks = queue.all()
    if not tasks:
        await message.reply_text("صف خالی است.")
        return
    for task in tasks:
        mark_deleted(task)
        for path_key in ("archive_path", "path"):
            old = task.get(path_key)
            if old:
                try: Path(old).unlink(missing_ok=True)
                except Exception: pass
        try:
            await client.edit_message_text(task["chat_id"], task["status_message_id"], "این مورد از صف حذف شد.")
        except Exception:
            pass
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        pass
    queue._cache = None
    queue._mtime = 0
    await message.reply_text("✅ کل صف پاک شد.")


@app.on_message(filters.private & filters.command("del"))
async def delete_one_handler(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    job_id = parts[1].strip() if len(parts) > 1 else None
    reply_msg_id = message.reply_to_message.id if message.reply_to_message else None

    tasks = queue.all()
    if not tasks:
        if job_id:
            if was_deleted(job_id=job_id):
                await message.reply_text("قبلاً حذف شده.")
                return
            cancel_job(job_id)
            await message.reply_text("لغو ثبت شد.")
        else:
            await message.reply_text("صف خالی است.")
        return

    removed = queue.remove(job_id=job_id, message_id=reply_msg_id)
    if removed:
        mark_deleted(removed)
        for pk in ("archive_path", "path"):
            old = removed.get(pk)
            if old:
                try: Path(old).unlink(missing_ok=True)
                except Exception: pass
        try:
            await client.edit_message_text(removed["chat_id"], removed["status_message_id"], "از صف حذف شد.")
        except Exception:
            pass
        await message.reply_text("✅ از صف حذف شد.")
        return
    if job_id:
        cancel_job(job_id)
        await message.reply_text("دستور لغو ثبت شد.")


# ═══════════════════════════════════════════════════════════════════════════════
#  هندلر رسید پرداخت (عکس)
# ═══════════════════════════════════════════════════════════════════════════════

@app.on_message(filters.private & filters.photo)
async def photo_handler(client: Client, message: Message):
    user_id = message.from_user.id
    db.upsert_user(user_id, message.from_user.username or "",
                   message.from_user.first_name or "", message.from_user.last_name or "")

    # اگر در انتظار رسید هستیم
    if user_id in awaiting_receipt:
        order_id = awaiting_receipt[user_id]
        photo_id = message.photo.file_id
        order = db.get_order(order_id=order_id)
        if not order or order["status"] != "pending":
            awaiting_receipt.pop(user_id, None)
            await message.reply_text("⚠️ سفارشی در انتظار یافت نشد.")
            return

        db.set_order_receipt(order_id, photo_id)
        awaiting_receipt.pop(user_id, None)

        await message.reply_text(
            f"✅ **رسید ثبت شد!**\n\n"
            f"سفارش #{order_id} در انتظار تأیید ادمین است.\n"
            f"کد پیگیری: `{order['tx_code']}`\n\n"
            f"معمولاً ظرف چند ساعت بررسی می‌شه. 🙏"
        )

        # اطلاع‌رسانی به ادمین
        for admin_id in ADMIN_IDS:
            try:
                u = db.get_user(user_id)
                name = u["first_name"] or str(user_id)
                await client.send_photo(
                    admin_id, photo_id,
                    caption=(
                        f"🔔 **رسید پرداخت جدید!**\n\n"
                        f"#️⃣ سفارش: #{order_id}\n"
                        f"👤 کاربر: {name} (`{user_id}`)\n"
                        f"📋 پلن: {order['plan_name']}\n"
                        f"💰 مبلغ: {order['amount']:,} تومان\n"
                        f"🎫 کد: `{order['tx_code']}`\n\n"
                        f"✅ `/approve {order_id}`\n"
                        f"❌ `/reject {order_id} علت`"
                    ),
                )
            except Exception:
                pass
        return

    await message.reply_text("❓ عکسی دریافت شد اما نمی‌دانم چیکار کنم!\nبرای رسید پرداخت، ابتدا /buy را بزن.")


# ═══════════════════════════════════════════════════════════════════════════════
#  هندلر متن (لینک / رمز ZIP)
# ═══════════════════════════════════════════════════════════════════════════════

def extract_url(text: str) -> Optional[str]:
    m = re.search(r"https?://\S+", text or "")
    return m.group(0) if m else None


@app.on_message(
    filters.private & filters.text
    & ~filters.command(["start","account","profile","sub","buy","safemode",
                        "del","delall","addsub","delsub","orders","order",
                        "approve","reject","stats","users","setcard","setholder","setsupport"])
)
async def text_handler(client: Client, message: Message):
    user = message.from_user
    db.upsert_user(user.id, user.username or "", user.first_name or "", user.last_name or "")
    text = (message.text or "").strip()

    # رمز ZIP در انتظار
    if awaiting_zip_pass.get(user.id):
        if not text:
            await message.reply_text("رمز نمی‌تواند خالی باشد.")
            return
        db.update_safe_mode(user.id, True, text)
        awaiting_zip_pass.pop(user.id, None)
        await message.reply_text("✅ Safe Mode فعال شد و رمز ذخیره گردید.")
        return

    # لینک مستقیم
    url = extract_url(text)
    if not url:
        return

    ok, reason = db.check_quota(user.id, 0)  # بررسی اینکه اصلاً سهمیه دارد
    if not ok and "تمام" in reason:
        await message.reply_text(reason, reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("💳 خرید اشتراک", callback_data="buy"),
        ]]))
        return

    u = db.get_user(user.id)
    status = await message.reply_text("🔗 لینک دریافت شد. در صف دانلود قرار گرفت...")
    task = {
        "type":              "direct_url",
        "url":               url,
        "chat_id":           message.chat.id,
        "telegram_user_id":  user.id,
        "status_message_id": status.id,
        "safe_mode":         bool(u.get("safe_mode")),
        "zip_password":      u.get("zip_password", ""),
    }
    queue.push(task)
    await status.edit_text(
        f"🔗 **لینک در صف**\n\n"
        f"شناسه: `{task['job_id']}`\n"
        f"برای حذف: `/del {task['job_id']}`"
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  هندلر مدیا (فایل‌ها)
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

    status = await message.reply_text("📥 آماده‌سازی برای دانلود از تلگرام...")
    try:
        started_at     = time.time()
        progress_state = {"last_update": 0}
        downloaded = await client.download_media(
            message,
            file_name=str(download_path),
            progress=download_progress,
            progress_args=(status, download_name, started_at, progress_state),
        )
        if not downloaded:
            raise RuntimeError("دانلود ناموفق بود.")
        dl_path = Path(downloaded)
        if not dl_path.exists():
            raise RuntimeError("فایل دانلود شده پیدا نشد.")

        real_size = dl_path.stat().st_size
        # بررسی مجدد با حجم واقعی
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
            "type":              "local_file",
            "path":              str(dl_path),
            "archive_path":      str(archive_path),
            "unique_code":       unique_code,
            "caption":           message.caption or "",
            "chat_id":           message.chat.id,
            "telegram_user_id":  user.id,
            "status_message_id": status.id,
            "file_name":         download_name,
            "file_size":         real_size,
            "safe_mode":         bool(u.get("safe_mode")),
            "zip_password":      u.get("zip_password", ""),
        }
        queue.push(task)

        remaining = max(0, u["bytes_quota"] - u["bytes_used"])
        rub_username = db.get_setting("bot_username", "@YourRubikaBot")
        await status.edit_text(
            f"✅ **فایل در صف آپلود روبیکا**\n\n"
            f"📄 `{download_name}`\n"
            f"📦 {pretty_size(real_size)}\n"
            f"🎫 کد: `{unique_code}`\n\n"
            f"🤖 در ربات روبیکا ({rub_username}) این کد را وارد کن\n\n"
            f"📊 سهمیه باقی: {pretty_size(remaining)}\n"
            f"🆔 صف: `{task['job_id']}` | `/del {task['job_id']}`"
        )
    except Exception as e:
        await status.edit_text(f"❌ خطا: {str(e)}")


# ═══════════════════════════════════════════════════════════════════════════════
#  اجرا
# ═══════════════════════════════════════════════════════════════════════════════

def clear_old_status():
    try:
        STATUS_FILE.unlink(missing_ok=True)
    except Exception:
        pass


if __name__ == "__main__":
    clear_old_status()
    app.start()
    app.loop.create_task(status_watcher())
    idle()
    app.stop()