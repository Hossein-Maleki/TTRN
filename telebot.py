"""
telebot.py — ربات تلگرام Tele2Rub v2
پروفایل، اشتراک، خرید، پنل ادمین، انتقال فایل
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
SETTINGS_FILE = QUEUE_DIR / "settings.json"

for d in [DOWNLOAD_DIR, ARCHIVE_DIR, QUEUE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

if not API_ID or not API_HASH or not BOT_TOKEN:
    raise RuntimeError("API_ID، API_HASH و BOT_TOKEN را در .env تنظیم کن")

app = Client("tel2rub", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# وضعیت موقت کاربران در حافظه
user_state: dict = {}          # {user_id: {"step": str, ...}}
waiting_for_zip_password: dict = {}   # {chat_id: True}


# ─────────────────────────────── ابزارها ─────────────────────────────────────

def safe_filename(name: Optional[str]) -> str:
    name = (name or "file.bin").strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name)
    name = name.rstrip(". ")
    return name[:200] or "file.bin"


def build_filename(message: Message, media_type: str, media) -> str:
    original = getattr(media, "file_name", None)
    if not original:
        uid = getattr(media, "file_unique_id", None) or "file"
        ext = {"document": ".bin", "video": ".mp4", "audio": ".mp3",
               "voice": ".ogg", "photo": ".jpg", "animation": ".mp4",
               "video_note": ".mp4", "sticker": ".webp"}.get(media_type, ".bin")
        original = f"{uid}{ext}"
    original = safe_filename(original)
    p = Path(original)
    return safe_filename(f"{p.stem}_{message.id}{p.suffix or '.bin'}")


def get_media(message: Message):
    for attr in ["document", "video", "audio", "voice", "photo",
                 "animation", "video_note", "sticker"]:
        m = getattr(message, attr, None)
        if m:
            return attr, m
    return None, None


def pretty_size(size) -> str:
    size = float(size or 0)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


def progress_bar(percent: float, length: int = 12) -> str:
    filled = int(length * percent / 100)
    return "█" * filled + "░" * (length - filled)


def eta_text(seconds) -> str:
    if not seconds or seconds <= 0:
        return "نامشخص"
    s = int(seconds)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if h:   return f"{h}h {m}m"
    if m:   return f"{m}m {s}s"
    return f"{s}s"


def load_settings() -> dict:
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"safe_mode": False, "zip_password": ""}


def save_settings(data: dict):
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ─────────────────────────────── صف ──────────────────────────────────────────

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
            if not line.strip():
                continue
            item = json.loads(line)
            if job_id and str(item.get("job_id")) == str(job_id):
                return True
            if message_id and int(item.get("status_message_id", 0)) == message_id:
                return True
    return False


# ─────────────────────────────── کیبوردها ────────────────────────────────────

def main_menu_kb(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("📊 حساب من",       callback_data="menu_account"),
         InlineKeyboardButton("💎 خرید اشتراک",   callback_data="menu_buy")],
        [InlineKeyboardButton("📖 راهنما",         callback_data="menu_help"),
         InlineKeyboardButton("🔒 Safe Mode",      callback_data="menu_safemode")],
    ]
    if user_id in ADMIN_IDS:
        rows.append([InlineKeyboardButton("👑 پنل ادمین", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def plans_kb() -> InlineKeyboardMarkup:
    rows = []
    for p in db.PLANS:
        label = f"{p['name']} — {p['price']:,} تومن / {p['days']} روز"
        rows.append([InlineKeyboardButton(label, callback_data=f"buy_plan_{p['id']}")])
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_back")])
    return InlineKeyboardMarkup(rows)


def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 سفارش‌های در انتظار", callback_data="admin_pending"),
         InlineKeyboardButton("📊 آمار فروش",           callback_data="admin_stats")],
        [InlineKeyboardButton("👥 کاربران",             callback_data="admin_users"),
         InlineKeyboardButton("💳 تنظیم کارت",          callback_data="admin_card")],
        [InlineKeyboardButton("🔙 بازگشت",              callback_data="menu_back")],
    ])


def order_action_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ تایید",  callback_data=f"admin_confirm_{order_id}"),
        InlineKeyboardButton("❌ رد",     callback_data=f"admin_reject_{order_id}"),
    ]])


def safemode_kb(is_on: bool) -> InlineKeyboardMarkup:
    if is_on:
        btn = InlineKeyboardButton("🔓 غیرفعال کردن", callback_data="safemode_off")
    else:
        btn = InlineKeyboardButton("🔒 فعال کردن",    callback_data="safemode_on")
    return InlineKeyboardMarkup([
        [btn],
        [InlineKeyboardButton("🔙 بازگشت",            callback_data="menu_back")],
    ])


# ─────────────────────────────── متن‌های ثابت ────────────────────────────────

HELP_TEXT = (
    "📖 **راهنمای ربات Tele2Rub**\n\n"
    "**روش انتقال فایل:**\n"
    "1️⃣ فایل را در تلگرام برای ربات بفرست\n"
    "2️⃣ کد ۸ کاراکتری دریافت کن\n"
    "3️⃣ کد را در **ربات روبیکا** بفرست تا فایل برات بیاد\n\n"
    "**لینک پست تلگرام در روبیکا:**\n"
    "لینک عمومی: `https://t.me/channel/123`\n"
    "لینک خصوصی: ابتدا لینک جوین، بعد لینک پست\n\n"
    "**جستجو در کانال (در ربات روبیکا):**\n"
    "`/search @channel کلمه`\n\n"
    "**دریافت پست خاص (در ربات روبیکا):**\n"
    "`/getpost @channel 1234`\n\n"
    "**دستورات:**\n"
    "`/del JOB_ID` — حذف از صف\n"
    "`/delall` — پاکسازی کل صف\n\n"
    "**تست رایگان:** ۲۰۰ مگابایت هدیه برای هر کاربر جدید 🎁\n"
    "**فایل‌های پشتیبانی‌شده:** سند، ویدیو، موزیک، ویس، عکس، گیف"
)


def account_text(user_id: int) -> str:
    user = db.get_user(user_id)
    if not user:
        return "پروفایل یافت نشد. لطفاً /start بزن."
    sub   = "✅ فعال" if user["sub_active"] else "❌ ندارد"
    exp   = db.pretty_time(user["sub_expires"]) if user["sub_expires"] else "بدون محدودیت زمانی"
    name  = " ".join(filter(None, [user["first_name"], user["last_name"]])) or "—"
    un    = f"@{user['username']}" if user["username"] else "—"
    return (
        f"👤 **پروفایل کاربر**\n\n"
        f"🆔 آیدی: `{user['telegram_id']}`\n"
        f"📛 نام: {name}\n"
        f"🔗 یوزرنیم: {un}\n"
        f"📅 عضویت: {db.pretty_time(user['joined_at'])}\n\n"
        f"📦 **مصرف کل:** `{db.pretty_size(user['total_bytes'])}`\n\n"
        f"📊 **سهمیه دوره جاری:**\n"
        f"{db.remaining_quota_text(user)}\n\n"
        f"🔑 اشتراک: {sub}\n"
        f"⏳ انقضا: {exp}"
    )


def payment_info_text(plan: dict, tx_code: str) -> str:
    ps = db.get_payment_settings()
    return (
        f"💎 **سفارش اشتراک {plan['name']}**\n\n"
        f"📦 حجم: `{db.pretty_size(plan['size_bytes'])}`\n"
        f"📅 مدت: `{plan['days']} روز`\n"
        f"💰 مبلغ: `{plan['price']:,} تومن`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💳 **شماره کارت:**\n`{ps['card_number']}`\n\n"
        f"👤 **صاحب کارت:** {ps['card_holder']}\n"
        f"🏦 **بانک:** {ps['bank_name']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔑 **کد یونیک تراکنش:**\n`{tx_code}`\n\n"
        f"⚠️ **مهم:** کد یونیک را در توضیحات پرداخت وارد کنید\n\n"
        f"📸 بعد از پرداخت، **رسید** را اینجا بفرست."
    )


# ────────────────────────── هندلر دانلود ─────────────────────────────────────

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
        f"پیشرفت: `{percent:.1f}%`\n"
        f"`{progress_bar(percent)}`\n"
        f"سرعت: `{pretty_size(speed)}/s`\n"
        f"زمان باقی‌مانده: `{eta_text(eta)}`"
    )
    try:
        await status_msg.edit_text(text)
    except Exception:
        pass


# ────────────────────────── ناظر وضعیت ──────────────────────────────────────

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
                if not line.strip():
                    continue
                data    = json.loads(line)
                chat_id = data.get("chat_id")
                msg_id  = data.get("message_id")
                text    = data.get("text", "")
                percent = data.get("percent")
                if not chat_id or not msg_id:
                    continue
                if percent is not None:
                    text += f"\n\n`{progress_bar(float(percent))}` `{float(percent):.1f}%`"
                try:
                    await app.edit_message_text(chat_id, msg_id, text)
                except Exception:
                    pass
        except Exception:
            pass


# ────────────────────────── دستورات اصلی ────────────────────────────────────

@app.on_message(filters.private & filters.command("start"))
async def start_handler(_, message: Message):
    user = message.from_user
    db.upsert_user(user.id, user.username or "", user.first_name or "", user.last_name or "")
    await message.reply_text(
        f"سلام **{user.first_name}** 👋\n\n"
        "به ربات **Tele2Rub** خوش اومدی!\n\n"
        "📌 **امکانات:**\n"
        "• انتقال فایل از تلگرام به روبیکا\n"
        "• دریافت پست‌های عمومی و خصوصی تلگرام در روبیکا\n"
        "• جستجو داخل کانال‌ها\n"
        "• تست رایگان تا **۲۰۰ مگابایت** 🎁\n"
        "• پشتیبانی از عکس، ویدیو، موزیک، ویس، گیف و فایل\n\n"
        "از منوی زیر استفاده کن 👇",
        reply_markup=main_menu_kb(user.id),
    )


@app.on_message(filters.private & filters.command("profile"))
async def profile_cmd(_, message: Message):
    db.upsert_user(message.from_user.id, message.from_user.username or "",
                   message.from_user.first_name or "", message.from_user.last_name or "")
    await message.reply_text(account_text(message.from_user.id))


@app.on_message(filters.private & filters.command("sub"))
async def sub_cmd(_, message: Message):
    user_row = db.get_user(message.from_user.id)
    if not user_row:
        await message.reply_text("ابتدا /start بزن.")
        return
    if user_row["sub_active"]:
        exp = db.pretty_time(user_row["sub_expires"]) if user_row["sub_expires"] else "بدون محدودیت"
        await message.reply_text(f"✅ اشتراک شما فعال است.\n⏳ انقضا: `{exp}`")
    else:
        await message.reply_text("❌ اشتراک فعالی ندارید.\n\nبرای خرید از منوی ربات استفاده کنید.")


# ─────────────────────────── callback queries ────────────────────────────────

@app.on_callback_query()
async def callback_handler(_, cq: CallbackQuery):
    data    = cq.data
    user    = cq.from_user
    user_id = user.id

    db.upsert_user(user_id, user.username or "", user.first_name or "", user.last_name or "")

    # ── بازگشت به منو اصلی
    if data == "menu_back":
        await cq.edit_message_text(
            f"منوی اصلی — {user.first_name} 👋",
            reply_markup=main_menu_kb(user_id),
        )

    # ── حساب من
    elif data == "menu_account":
        await cq.edit_message_text(
            account_text(user_id),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 خرید اشتراک", callback_data="menu_buy")],
                [InlineKeyboardButton("🔙 بازگشت",      callback_data="menu_back")],
            ]),
        )

    # ── خرید اشتراک (انتخاب پلن)
    elif data == "menu_buy":
        text = (
            "💎 **خرید اشتراک**\n\n"
            "یکی از پلن‌های زیر را انتخاب کن:\n\n"
        )
        for p in db.PLANS:
            text += f"• **{p['name']}** — {p['price']:,} تومن / {p['days']} روز\n"
        await cq.edit_message_text(text, reply_markup=plans_kb())

    # ── انتخاب پلن خاص
    elif data.startswith("buy_plan_"):
        plan_id = int(data.split("_")[-1])
        plan    = next((p for p in db.PLANS if p["id"] == plan_id), None)
        if not plan:
            await cq.answer("پلن نامعتبر.", show_alert=True)
            return
        result = db.create_order(user_id, plan_id)
        user_state[user_id] = {
            "step":     "waiting_receipt",
            "order_id": result["order_id"],
            "tx_code":  result["tx_code"],
            "plan":     plan,
        }
        await cq.edit_message_text(
            payment_info_text(plan, result["tx_code"]),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ انصراف", callback_data="cancel_order")]
            ]),
        )

    # ── انصراف از سفارش
    elif data == "cancel_order":
        user_state.pop(user_id, None)
        await cq.edit_message_text(
            "سفارش لغو شد.",
            reply_markup=main_menu_kb(user_id),
        )

    # ── راهنما
    elif data == "menu_help":
        await cq.edit_message_text(
            HELP_TEXT,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_back")]
            ]),
        )

    # ── safe mode
    elif data == "menu_safemode":
        settings = load_settings()
        is_on    = settings.get("safe_mode", False)
        status   = "🔒 فعال" if is_on else "🔓 غیرفعال"
        await cq.edit_message_text(
            f"**Safe Mode** — {status}\n\n"
            "وقتی فعال باشد، فایل‌ها با رمز ZIP ارسال می‌شوند.",
            reply_markup=safemode_kb(is_on),
        )

    elif data == "safemode_on":
        settings = load_settings()
        settings["safe_mode"] = True
        save_settings(settings)
        waiting_for_zip_password[cq.message.chat.id] = True
        await cq.edit_message_text(
            "🔒 Safe Mode فعال شد.\n\nحالا رمز ZIP مورد نظرت رو بفرست:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ انصراف", callback_data="safemode_off")]
            ]),
        )

    elif data == "safemode_off":
        settings = load_settings()
        settings["safe_mode"] = False
        settings["zip_password"] = ""
        save_settings(settings)
        waiting_for_zip_password.pop(cq.message.chat.id, None)
        await cq.edit_message_text(
            "🔓 Safe Mode غیرفعال شد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_back")]
            ]),
        )

    # ── پنل ادمین
    elif data == "admin_panel":
        if user_id not in ADMIN_IDS:
            await cq.answer("دسترسی ندارید.", show_alert=True)
            return
        await cq.edit_message_text("👑 **پنل مدیریت**", reply_markup=admin_panel_kb())

    elif data == "admin_pending":
        if user_id not in ADMIN_IDS:
            return
        orders = db.get_pending_orders()
        if not orders:
            await cq.answer("سفارش در انتظاری وجود ندارد.", show_alert=True)
            return
        for o in orders:
            u = db.get_user(o["telegram_user_id"])
            name = (u["first_name"] if u else "") or str(o["telegram_user_id"])
            text = (
                f"📋 **سفارش #{o['id']}**\n\n"
                f"👤 کاربر: {name} (`{o['telegram_user_id']}`)\n"
                f"💎 پلن: {o['plan_name']}\n"
                f"💰 مبلغ: {o['amount']:,} تومن\n"
                f"🔑 کد تراکنش: `{o['tx_code']}`\n"
                f"📅 تاریخ: {db.pretty_time(o['created_at'])}\n"
            )
            if o["receipt_file_id"]:
                try:
                    await app.send_photo(
                        user_id, o["receipt_file_id"],
                        caption=text,
                        reply_markup=order_action_kb(o["id"]),
                    )
                except Exception:
                    await app.send_message(
                        user_id, text + "\n⚠️ رسید موجود نیست.",
                        reply_markup=order_action_kb(o["id"]),
                    )
            else:
                await app.send_message(
                    user_id, text + "\n⚠️ رسید ارسال نشده.",
                    reply_markup=order_action_kb(o["id"]),
                )
        await cq.answer()

    elif data == "admin_stats":
        if user_id not in ADMIN_IDS:
            return
        stats  = db.get_orders_stats()
        n_users = db.count_users()
        text = (
            f"📊 **آمار کلی**\n\n"
            f"👥 کل کاربران: `{n_users}`\n\n"
            f"🛒 **سفارش‌ها:**\n"
            f"• کل: `{stats['total']}`\n"
            f"• تایید شده: `{stats['confirmed']}`\n"
            f"• در انتظار: `{stats['pending']}`\n\n"
            f"💰 **درآمد تایید شده:** `{stats['revenue']:,} تومن`"
        )
        recent = db.get_recent_orders(10)
        if recent:
            text += "\n\n**۱۰ سفارش اخیر:**\n"
            status_fa = {"pending": "⏳", "confirmed": "✅", "rejected": "❌"}
            for o in recent:
                ico = status_fa.get(o["status"], "❓")
                text += f"{ico} #{o['id']} — {o['plan_name']} — {o['amount']:,}ت — {db.pretty_time(o['created_at'])}\n"
        await cq.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
            ]),
        )

    elif data == "admin_users":
        if user_id not in ADMIN_IDS:
            return
        users  = db.get_all_users(limit=15)
        n_tot  = db.count_users()
        text   = f"👥 **کاربران ({n_tot} نفر) — ۱۵ آخر:**\n\n"
        for u in users:
            sub = "✅" if u["sub_active"] else "❌"
            name = (u["first_name"] or "")[:15] or str(u["telegram_id"])
            text += f"{sub} `{u['telegram_id']}` — {name} — {db.pretty_size(u['total_bytes'])}\n"
        await cq.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
            ]),
        )

    elif data == "admin_card":
        if user_id not in ADMIN_IDS:
            return
        ps = db.get_payment_settings()
        user_state[user_id] = {"step": "admin_edit_card"}
        await cq.edit_message_text(
            f"💳 **اطلاعات فعلی کارت:**\n\n"
            f"شماره: `{ps['card_number']}`\n"
            f"صاحب: {ps['card_holder']}\n"
            f"بانک: {ps['bank_name']}\n\n"
            f"فرمت ارسال:\n`شماره کارت|نام صاحب|نام بانک`\n\n"
            f"مثال:\n`6037-9975-1234-5678|علی احمدی|ملی`",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ انصراف", callback_data="admin_panel")]
            ]),
        )

    elif data.startswith("admin_confirm_"):
        if user_id not in ADMIN_IDS:
            return
        order_id = int(data.split("_")[-1])
        order    = db.confirm_order(order_id)
        if order:
            await cq.edit_message_reply_markup(reply_markup=None)
            await cq.message.reply_text(f"✅ سفارش #{order_id} تایید شد.")
            try:
                await app.send_message(
                    order["telegram_user_id"],
                    f"✅ **پرداخت شما تایید شد!**\n\n"
                    f"💎 پلن: {order['plan_name']}\n"
                    f"📦 حجم: {db.pretty_size(order['plan_size_bytes'])}\n"
                    f"📅 مدت: ۳۰ روز\n\n"
                    f"اشتراک شما فعال شد. از ربات لذت ببرید! 🎉"
                )
            except Exception:
                pass

    elif data.startswith("admin_reject_"):
        if user_id not in ADMIN_IDS:
            return
        order_id = int(data.split("_")[-1])
        order    = db.reject_order(order_id)
        if order:
            await cq.edit_message_reply_markup(reply_markup=None)
            await cq.message.reply_text(f"❌ سفارش #{order_id} رد شد.")
            try:
                await app.send_message(
                    order["telegram_user_id"],
                    f"❌ **پرداخت شما رد شد.**\n\n"
                    f"اگر مشکلی وجود دارد با ادمین تماس بگیرید."
                )
            except Exception:
                pass

    await cq.answer()


# ─────────────────────────── دستورات ادمین ──────────────────────────────────

@app.on_message(filters.private & filters.command("addsub"))
async def addsub_handler(_, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply_text("استفاده: `/addsub USER_ID DAYS [GB]`\nمثال: `/addsub 123456 30 5`")
        return
    try:
        uid   = int(parts[1])
        days  = int(parts[2])
        gb    = float(parts[3]) if len(parts) > 3 else 5
    except ValueError:
        await message.reply_text("فرمت نادرست.")
        return
    quota   = int(gb * 1024**3)
    expires = time.time() + days * 86400
    db.set_subscription(uid, True, expires, quota)
    await message.reply_text(
        f"✅ اشتراک `{gb}` گیگ / {days} روز برای `{uid}` فعال شد."
    )


@app.on_message(filters.private & filters.command("delsub"))
async def delsub_handler(_, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply_text("استفاده: `/delsub USER_ID`")
        return
    uid = int(parts[1])
    db.set_subscription(uid, False)
    await message.reply_text(f"❌ اشتراک کاربر `{uid}` غیرفعال شد.")


@app.on_message(filters.private & filters.command("admin"))
async def admin_cmd(_, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.reply_text("👑 **پنل مدیریت**", reply_markup=admin_panel_kb())


# ─────────────────────────── حذف از صف ──────────────────────────────────────

@app.on_message(filters.private & filters.command("delall"))
async def clear_queue_handler(client, message: Message):
    tasks = queue.all()
    if not tasks:
        await message.reply_text("صف خالی است.")
        return
    for task in tasks:
        mark_deleted(task)
        old = task.get("archive_path") or task.get("path")
        if old:
            try:
                Path(old).unlink(missing_ok=True)
            except Exception:
                pass
        try:
            await client.edit_message_text(
                task["chat_id"], task["status_message_id"], "این مورد از صف حذف شد."
            )
        except Exception:
            pass
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        pass
    queue._cache = None
    queue._mtime = 0
    await message.reply_text("✅ تمام موارد صف پاک شد.")


@app.on_message(filters.private & filters.command("del"))
async def delete_one_handler(client, message: Message):
    parts    = message.text.split(maxsplit=1)
    job_id   = parts[1].strip() if len(parts) > 1 else None
    reply_id = message.reply_to_message.id if message.reply_to_message else None

    tasks = queue.all()
    if not tasks:
        if job_id:
            if was_deleted(job_id=job_id):
                await message.reply_text("قبلاً حذف شده.")
                return
            cancel_job(job_id)
            await message.reply_text("لغو ثبت شد.")
        else:
            await message.reply_text("موردی در صف نیست.")
        return

    removed = queue.remove(job_id=job_id, message_id=reply_id)
    if removed:
        mark_deleted(removed)
        old = removed.get("archive_path") or removed.get("path")
        if old:
            try:
                Path(old).unlink(missing_ok=True)
            except Exception:
                pass
        try:
            await client.edit_message_text(
                removed["chat_id"], removed["status_message_id"], "این مورد از صف حذف شد."
            )
        except Exception:
            pass
        await message.reply_text("✅ از صف حذف شد.")
        return
    if job_id:
        cancel_job(job_id)
        await message.reply_text("دستور لغو ثبت شد.")


# ─────────────────────────── پیام متنی ──────────────────────────────────────

def extract_url(text: str) -> Optional[str]:
    m = re.search(r"https?://\S+", text or "")
    return m.group(0) if m else None


@app.on_message(
    filters.private & filters.text
    & ~filters.command(["start", "profile", "sub", "admin",
                        "del", "delall", "addsub", "delsub"])
)
async def text_handler(_, message: Message):
    user    = message.from_user
    user_id = user.id
    text    = message.text or ""

    db.upsert_user(user_id, user.username or "", user.first_name or "", user.last_name or "")

    # ── رمز ZIP
    if waiting_for_zip_password.get(message.chat.id):
        password = text.strip()
        if not password:
            await message.reply_text("رمز نمی‌تواند خالی باشد.")
            return
        settings = load_settings()
        settings["zip_password"] = password
        save_settings(settings)
        waiting_for_zip_password.pop(message.chat.id, None)
        await message.reply_text("✅ رمز ذخیره شد. فایل‌ها با این رمز ZIP می‌شوند.")
        return

    # ── ویرایش کارت ادمین
    st = user_state.get(user_id, {})
    if st.get("step") == "admin_edit_card" and user_id in ADMIN_IDS:
        parts = text.split("|")
        if len(parts) != 3:
            await message.reply_text("فرمت نادرست. مثال:\n`6037-xxxx-xxxx-xxxx|نام|بانک`")
            return
        db.update_payment_settings(parts[0].strip(), parts[1].strip(), parts[2].strip())
        user_state.pop(user_id, None)
        await message.reply_text("✅ اطلاعات کارت به‌روزرسانی شد.")
        return

    # ── رسید پرداخت (از طریق متن؟ نه — فقط عکس؛ این بخش برای پیام عادی)
    if st.get("step") == "waiting_receipt":
        await message.reply_text("📸 لطفاً **عکس** رسید را بفرست (نه متن).")
        return

    # ── لینک مستقیم
    url = extract_url(text)
    if not url:
        await message.reply_text(
            "دستور نامعتبر. از منو استفاده کن:",
            reply_markup=main_menu_kb(user_id),
        )
        return

    if not db.is_subscribed(user_id) and user_id not in ADMIN_IDS:
        await message.reply_text(
            "⛔ سهمیه شما تمام شده یا اشتراک ندارید.\n\n"
            "برای خرید اشتراک از منو استفاده کن:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 خرید اشتراک", callback_data="menu_buy")]
            ]),
        )
        return

    settings = load_settings()
    status   = await message.reply_text("🔗 لینک دریافت شد. در صف دانلود قرار گرفت...")
    task = {
        "type":              "direct_url",
        "url":               url,
        "chat_id":           message.chat.id,
        "telegram_user_id":  user_id,
        "status_message_id": status.id,
        "safe_mode":         settings.get("safe_mode", False),
        "zip_password":      settings.get("zip_password", ""),
    }
    queue.push(task)
    await status.edit_text(
        f"🔗 **لینک در صف قرار گرفت**\n\n"
        f"شناسه: `{task['job_id']}`\n"
        f"برای حذف: `/del {task['job_id']}`"
    )


# ─────────────────────── دریافت رسید پرداخت (عکس/فایل) ─────────────────────

@app.on_message(filters.private & (filters.photo | filters.document))
async def receipt_or_file_handler(client, message: Message):
    user    = message.from_user
    user_id = user.id
    db.upsert_user(user_id, user.username or "", user.first_name or "", user.last_name or "")

    st = user_state.get(user_id, {})

    # ── رسید سفارش
    if st.get("step") == "waiting_receipt":
        order_id     = st["order_id"]
        receipt_id   = (
            message.photo.file_id if message.photo
            else message.document.file_id
        )
        db.set_order_receipt(order_id, receipt_id)
        user_state.pop(user_id, None)

        await message.reply_text(
            f"✅ رسید دریافت شد!\n\n"
            f"🔑 کد سفارش: `{order_id}`\n"
            f"⏳ در انتظار تایید ادمین...\n\n"
            f"بعد از تایید، اشتراک شما فعال می‌شود."
        )
        # اطلاع‌رسانی به ادمین‌ها
        order = db.get_order(order_id)
        for admin_id in ADMIN_IDS:
            try:
                caption = (
                    f"📋 **سفارش جدید #{order_id}**\n\n"
                    f"👤 کاربر: `{user_id}` ({user.first_name})\n"
                    f"💎 پلن: {order['plan_name']}\n"
                    f"💰 مبلغ: {order['amount']:,} تومن\n"
                    f"🔑 کد: `{order['tx_code']}`"
                )
                await client.send_photo(
                    admin_id, receipt_id, caption=caption,
                    reply_markup=order_action_kb(order_id),
                )
            except Exception:
                pass
        return

    # ── فایل عادی برای انتقال
    if not db.is_subscribed(user_id) and user_id not in ADMIN_IDS:
        await message.reply_text(
            "⛔ سهمیه شما تمام شده یا اشتراک ندارید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 خرید اشتراک", callback_data="menu_buy")]
            ]),
        )
        return

    media_type, media = get_media(message)
    if not media:
        await message.reply_text("فایل قابل پردازش نیست.")
        return

    # بررسی حجم فایل
    file_size_check = getattr(media, "file_size", 0) or 0
    if not db.has_quota(user_id, file_size_check) and user_id not in ADMIN_IDS:
        await message.reply_text(
            "⛔ سهمیه شما برای این فایل کافی نیست.\n\n"
            "برای افزایش سهمیه اشتراک بخرید:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 خرید اشتراک", callback_data="menu_buy")]
            ]),
        )
        return

    download_name = build_filename(message, media_type, media)
    download_path = DOWNLOAD_DIR / download_name
    status_msg    = await message.reply_text("📥 آماده‌سازی برای دانلود از تلگرام...")

    try:
        started_at     = time.time()
        progress_state = {"last_update": 0}

        downloaded = await client.download_media(
            message,
            file_name=str(download_path),
            progress=download_progress,
            progress_args=(status_msg, download_name, started_at, progress_state),
        )

        if not downloaded or not Path(downloaded).exists():
            raise RuntimeError("دانلود ناموفق بود.")

        dl_path   = Path(downloaded)
        file_size = dl_path.stat().st_size

        archive_path = DOWNLOAD_DIR.parent / "archive" / download_name
        shutil.copy2(str(dl_path), str(archive_path))

        unique_code = db.create_file_record(user_id, download_name, file_size, str(archive_path))
        db.add_bytes_used(user_id, file_size)

        settings = load_settings()
        task = {
            "type":              "local_file",
            "path":              str(dl_path),
            "archive_path":      str(archive_path),
            "unique_code":       unique_code,
            "caption":           message.caption or "",
            "chat_id":           message.chat.id,
            "telegram_user_id":  user_id,
            "status_message_id": status_msg.id,
            "file_name":         download_name,
            "file_size":         file_size,
            "safe_mode":         settings.get("safe_mode", False),
            "zip_password":      settings.get("zip_password", ""),
        }
        queue.push(task)

        await status_msg.edit_text(
            f"✅ **فایل در صف قرار گرفت**\n\n"
            f"📄 فایل: `{download_name}`\n"
            f"📦 حجم: `{pretty_size(file_size)}`\n"
            f"🎫 **کد یونیک:** `{unique_code}`\n\n"
            f"این کد را در **ربات روبیکا** بفرست تا فایل ارسال شود.\n\n"
            f"🆔 شناسه صف: `{task['job_id']}`\n"
            f"برای حذف: `/del {task['job_id']}`"
        )

    except Exception as e:
        await status_msg.edit_text(f"❌ خطا: {str(e)}")


# ────────────────────────────── اجرا ─────────────────────────────────────────

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