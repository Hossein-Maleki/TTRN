"""
telebot.py — ربات تلگرام با پروفایل کاربری، اشتراک و کد یونیک
"""

import os
import re
import json
import time
import asyncio
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram import idle

import db

load_dotenv()

API_ID      = int(os.getenv("API_ID", "0"))
API_HASH    = os.getenv("API_HASH", "").strip()
BOT_TOKEN   = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS   = [int(x) for x in os.getenv("ADMIN_IDS", "0").split(",") if x.strip().isdigit()]

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


# ─── ابزارها ──────────────────────────────────────────────────────────────────

def safe_filename(name: Optional[str]) -> str:
    name = (name or "file.bin").strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name)
    name = name.rstrip(". ")
    return name[:200] or "file.bin"


def split_name(filename: str):
    p = Path(filename)
    return p.stem, p.suffix


def get_media(message: Message):
    for attr in ["document", "video", "audio", "voice", "photo",
                 "animation", "video_note", "sticker"]:
        media = getattr(message, attr, None)
        if media:
            return attr, media
    return None, None


def build_filename(message: Message, media_type: str, media) -> str:
    original = getattr(media, "file_name", None)
    if not original:
        uid = getattr(media, "file_unique_id", None) or "file"
        ext = {
            "document": ".bin", "video": ".mp4", "audio": ".mp3",
            "voice": ".ogg", "photo": ".jpg", "animation": ".mp4",
            "video_note": ".mp4", "sticker": ".webp",
        }.get(media_type, ".bin")
        original = f"{uid}{ext}"
    original = safe_filename(original)
    stem, suffix = split_name(original)
    return safe_filename(f"{stem}_{message.id}{suffix or '.bin'}")


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
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def user_profile_text(user: db.sqlite3.Row) -> str:
    sub = "✅ فعال" if user["sub_active"] else "❌ ندارد"
    exp = db.pretty_time(user["sub_expires"]) if user["sub_expires"] else "—"
    total = db.pretty_size(user["total_bytes"])
    joined = db.pretty_time(user["joined_at"])
    name = " ".join(filter(None, [user["first_name"], user["last_name"]])) or "—"
    un   = f"@{user['username']}" if user["username"] else "—"
    return (
        f"👤 **پروفایل کاربر**\n\n"
        f"🆔 آیدی: `{user['telegram_id']}`\n"
        f"📛 نام: {name}\n"
        f"🔗 یوزرنیم: {un}\n"
        f"📅 عضویت: {joined}\n\n"
        f"📦 حجم مصرفی: `{total}`\n"
        f"🔑 اشتراک: {sub}\n"
        f"⏳ انقضا: {exp}"
    )


# ─── صف ───────────────────────────────────────────────────────────────────────

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


# ─── هندلر پیشرفت دانلود ──────────────────────────────────────────────────────

async def download_progress(current, total, status_msg, file_name, started_at, state):
    now = time.time()
    if now - state.get("last_update", 0) < 3 and current < total:
        return
    state["last_update"] = now
    percent = current * 100 / total if total else 0
    elapsed = max(now - started_at, 1)
    speed = current / elapsed
    eta = (total - current) / speed if speed else None
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


# ─── ناظر وضعیت (از rub_worker می‌خونه) ─────────────────────────────────────

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
                data = json.loads(line)
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


# ─── دستورات ──────────────────────────────────────────────────────────────────

@app.on_message(filters.private & filters.command("start"))
async def start_handler(client: Client, message: Message):
    user = message.from_user
    db.upsert_user(user.id, user.username or "", user.first_name or "", user.last_name or "")

    await message.reply_text(
        f"سلام **{user.first_name}** 💙\n\n"
        "به ربات **Tele2Rub** خوش اومدی!\n\n"
        "📌 **کارهایی که می‌تونی بکنی:**\n"
        "• فایل بفرست → توی روبیکا آپلود میشه\n"
        "• لینک مستقیم بفرست → دانلود و آپلود میشه\n"
        "• کد یونیک دریافت کن → در ربات روبیکا فایل بگیر\n\n"
        "📋 **دستورات:**\n"
        "/profile — پروفایل و آمار مصرف\n"
        "/sub — وضعیت اشتراک\n"
        "/del [id] — حذف از صف\n"
        "/delall — پاکسازی کل صف\n"
        "/safemode on|off — رمزگذاری ZIP\n\n"
        "⚠️ حداکثر ۱۰ فایل همزمان ارسال کن."
    )


@app.on_message(filters.private & filters.command("profile"))
async def profile_handler(client: Client, message: Message):
    user_row = db.get_user(message.from_user.id)
    if not user_row:
        db.upsert_user(
            message.from_user.id,
            message.from_user.username or "",
            message.from_user.first_name or "",
            message.from_user.last_name or "",
        )
        user_row = db.get_user(message.from_user.id)
    await message.reply_text(user_profile_text(user_row))


@app.on_message(filters.private & filters.command("sub"))
async def sub_handler(client: Client, message: Message):
    user_row = db.get_user(message.from_user.id)
    if not user_row:
        await message.reply_text("ابتدا /start بزن.")
        return
    if user_row["sub_active"]:
        exp = db.pretty_time(user_row["sub_expires"])
        await message.reply_text(
            f"✅ اشتراک شما **فعال** است.\n⏳ انقضا: `{exp}`"
        )
    else:
        await message.reply_text(
            "❌ اشتراک فعالی ندارید.\n\n"
            "برای دریافت اشتراک با ادمین تماس بگیرید."
        )


# ─── دستورات ادمین ───────────────────────────────────────────────────────────

@app.on_message(filters.private & filters.command("addsub"))
async def addsub_handler(client: Client, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    # /addsub USER_ID DAYS
    parts = message.text.split()
    if len(parts) < 3:
        await message.reply_text("استفاده: `/addsub USER_ID DAYS`")
        return
    try:
        uid  = int(parts[1])
        days = int(parts[2])
    except ValueError:
        await message.reply_text("فرمت نادرست.")
        return
    expires = time.time() + days * 86400
    db.set_subscription(uid, True, expires)
    await message.reply_text(
        f"✅ اشتراک {days} روزه برای کاربر `{uid}` فعال شد."
    )


@app.on_message(filters.private & filters.command("delsub"))
async def delsub_handler(client: Client, message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = message.text.split()
    if len(parts) < 2:
        await message.reply_text("استفاده: `/delsub USER_ID`")
        return
    uid = int(parts[1])
    db.set_subscription(uid, False)
    await message.reply_text(f"❌ اشتراک کاربر `{uid}` غیرفعال شد.")


# ─── حذف از صف ────────────────────────────────────────────────────────────────

@app.on_message(filters.private & filters.command("delall"))
async def clear_queue_handler(client: Client, message: Message):
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
            await message.reply_text("موردی در صف نیست.")
        return

    removed = queue.remove(job_id=job_id, message_id=reply_msg_id)
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


# ─── وضعیت safe mode (ذخیره محلی) ───────────────────────────────────────────

SETTINGS_FILE = QUEUE_DIR / "settings.json"
waiting_for_zip_password: dict = {}   # {chat_id: True}


def load_settings() -> dict:
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"safe_mode": False, "zip_password": ""}


def save_settings(data: dict):
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@app.on_message(filters.private & filters.command("safemode"))
async def safemode_handler(client: Client, message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply_text("استفاده: `/safemode on` یا `/safemode off`")
        return
    action = args[1].strip().lower()
    settings = load_settings()
    if action == "on":
        settings["safe_mode"] = True
        save_settings(settings)
        waiting_for_zip_password[message.chat.id] = True
        await message.reply_text(
            "🔒 Safe Mode فعال شد.\n\nرمز ZIP مورد نظرت رو بفرست:"
        )
    elif action == "off":
        settings["safe_mode"] = False
        settings["zip_password"] = ""
        save_settings(settings)
        waiting_for_zip_password.pop(message.chat.id, None)
        await message.reply_text("🔓 Safe Mode غیرفعال شد.")
    else:
        await message.reply_text("دستور نامعتبر.")


# ─── پیام متنی (لینک یا رمز ZIP) ─────────────────────────────────────────────

def extract_url(text: str) -> Optional[str]:
    m = re.search(r"https?://\S+", text or "")
    return m.group(0) if m else None


@app.on_message(
    filters.private & filters.text
    & ~filters.command(["start", "profile", "sub", "safemode",
                        "del", "delall", "addsub", "delsub"])
)
async def text_handler(client: Client, message: Message):
    user = message.from_user
    db.upsert_user(user.id, user.username or "", user.first_name or "", user.last_name or "")

    text = message.text or ""

    # رمز ZIP
    if waiting_for_zip_password.get(message.chat.id):
        password = text.strip()
        if not password:
            await message.reply_text("رمز نمی‌تواند خالی باشد.")
            return
        settings = load_settings()
        settings["zip_password"] = password
        save_settings(settings)
        waiting_for_zip_password.pop(message.chat.id, None)
        await message.reply_text("✅ رمز ذخیره شد.")
        return

    # لینک مستقیم
    url = extract_url(text)
    if not url:
        return

    if not db.is_subscribed(user.id) and user.id not in ADMIN_IDS:
        await message.reply_text(
            "⛔ برای استفاده از این ربات اشتراک فعال نیاز داری.\n"
            "با ادمین تماس بگیر."
        )
        return

    settings = load_settings()
    status = await message.reply_text("🔗 لینک دریافت شد. در صف دانلود قرار گرفت...")

    task = {
        "type":              "direct_url",
        "url":               url,
        "chat_id":           message.chat.id,
        "telegram_user_id":  user.id,
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


# ─── دریافت فایل ──────────────────────────────────────────────────────────────

@app.on_message(
    filters.private
    & (filters.document | filters.video | filters.audio | filters.voice
       | filters.photo | filters.animation | filters.video_note | filters.sticker)
)
async def media_handler(client: Client, message: Message):
    user = message.from_user
    db.upsert_user(user.id, user.username or "", user.first_name or "", user.last_name or "")

    if not db.is_subscribed(user.id) and user.id not in ADMIN_IDS:
        await message.reply_text(
            "⛔ برای استفاده از این ربات اشتراک فعال نیاز داری.\n"
            "با ادمین تماس بگیر."
        )
        return

    media_type, media = get_media(message)
    if not media:
        await message.reply_text("فایل قابل پردازش نیست.")
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

        file_size = dl_path.stat().st_size

        # کپی به archive برای استفاده ربات روبیکا
        archive_path = ARCHIVE_DIR / download_name
        import shutil
        shutil.copy2(str(dl_path), str(archive_path))

        # ثبت در دیتابیس و دریافت کد یونیک
        unique_code = db.create_file_record(
            telegram_user_id=user.id,
            file_name=download_name,
            file_size=file_size,
            archive_path=str(archive_path),
        )
        db.add_bytes_used(user.id, file_size)

        settings = load_settings()
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
            "file_size":         file_size,
            "safe_mode":         settings.get("safe_mode", False),
            "zip_password":      settings.get("zip_password", ""),
        }
        queue.push(task)

        await status.edit_text(
            f"✅ **فایل در صف قرار گرفت**\n\n"
            f"📄 فایل: `{download_name}`\n"
            f"📦 حجم: `{pretty_size(file_size)}`\n"
            f"🎫 کد یونیک: `{unique_code}`\n\n"
            f"این کد رو در **ربات روبیکا** وارد کن تا فایل برات ارسال بشه.\n\n"
            f"🆔 شناسه صف: `{task['job_id']}`\n"
            f"برای حذف: `/del {task['job_id']}`"
        )

    except Exception as e:
        await status.edit_text(f"❌ خطا: {str(e)}")


# ─── اجرا ─────────────────────────────────────────────────────────────────────

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
