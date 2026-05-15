"""
rub_worker.py — ورکر روبیکا (نسخه ۲.۲ - بهبود یافته)
- آپلود فایل در کانال
- ذخیره message_id
- فوروارد از کانال به کاربر
"""

import os, re, json, time, threading, shutil, asyncio
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from rubpy import Client as RubikaClient
import requests
import pyzipper
from urllib.parse import urlparse

import db

load_dotenv()

SESSION = os.getenv("RUBIKA_SESSION", "rubika_session").strip()
RUBIKA_CHANNEL_GUID = os.getenv("RUBIKA_CHANNEL_GUID", "").strip()

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
ARCHIVE_DIR = BASE_DIR / "archive"
QUEUE_DIR = BASE_DIR / "queue"
QUEUE_FILE = QUEUE_DIR / "tasks.jsonl"
STATUS_FILE = QUEUE_DIR / "status.jsonl"
FAILED_FILE = QUEUE_DIR / "failed.jsonl"

for d in [DOWNLOAD_DIR, ARCHIVE_DIR, QUEUE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ───────────────────────── ابزارها ────────────────────────────────────────

def safe_filename(name: Optional[str]) -> str:
    name = (name or "file").strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", name)
    return name[:200] or "file"

def pretty_size(size) -> str:
    return db.pretty_size(size)

def push_status(task: dict, text: str, percent: float = None):
    payload = {
        "chat_id": task.get("chat_id"),
        "message_id": task.get("status_message_id"),
        "text": text,
        "percent": percent,
        "time": time.time(),
    }
    with open(STATUS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")

# ───────────────────────── ربات روبیکا ────────────────────────────────────

def has_rubika_session() -> bool:
    for suffix in ["", ".session", ".sqlite"]:
        if Path(f"{SESSION}{suffix}").exists():
            return True
    return False

def ensure_session():
    if has_rubika_session():
        print(f"✅ فایل session {SESSION} یافت شد.")
        return
    print(f"⚠️  session {SESSION} یافت نشد. درحال ساخت...")
    client = RubikaClient(name=SESSION)
    try:
        client.start()
        print("✅ session ساخته شد.")
    finally:
        try:
            client.disconnect()
        except Exception:
            pass

def send_to_channel_sync(file_path: str, caption: str) -> dict:
    """آپلود فایل در کانال روبیکا"""
    client = RubikaClient(name=SESSION)
    try:
        client.start()
        result = client.send_document(RUBIKA_CHANNEL_GUID, file_path, caption=caption or "")
        return result or {}
    except Exception as e:
        raise RuntimeError(f"خطا در آپلود: {str(e)}")
    finally:
        try:
            client.disconnect()
        except Exception:
            pass

def send_file_to_user_sync(user_guid: str, file_path: str, caption: str):
    """ارسال فایل مستقیم به کاربر"""
    client = RubikaClient(name=SESSION)
    try:
        client.start()
        client.send_document(user_guid, file_path, caption=caption or "")
    except Exception as e:
        raise RuntimeError(f"خطا در ارسال: {str(e)}")
    finally:
        try:
            client.disconnect()
        except Exception:
            pass

# ───────────────────────── ZIP رمزدار ────────────────────────────────────

def make_zip(file_path: Path, password: str) -> Path:
    zip_path = file_path.with_suffix(file_path.suffix + ".zip")
    with pyzipper.AESZipFile(zip_path, "w", compression=pyzipper.ZIP_STORED,
                             encryption=pyzipper.WZ_AES) as zf:
        zf.setpassword(password.encode("utf-8"))
        zf.write(file_path, arcname=file_path.name)
    return zip_path

# ───────────────────────── پردازش تسک ────────────────────────────────────

def process_task(task: dict):
    """پردازش آپلود فایل"""
    task_type = task.get("type")
    caption = task.get("caption", "")
    safe_mode = task.get("safe_mode", False)
    zip_password = task.get("zip_password", "")
    unique_code = task.get("unique_code")
    
    if task_type == "local_file":
        local_path = Path(task.get("path", ""))
        if not local_path.exists():
            raise RuntimeError("فایل محلی پیدا نشد.")
    else:
        raise RuntimeError("نوع تسک نامعلوم.")

    # رمزگذاری ZIP اگر فعال است
    if safe_mode and zip_password:
        push_status(task, "🔒 درحال رمزگذاری...")
        try:
            zipped = make_zip(local_path, zip_password)
            send_path = zipped
        except Exception as e:
            raise RuntimeError(f"خطا در رمزگذاری: {str(e)}")
    else:
        send_path = local_path

    # آپلود در کانال
    push_status(task, "🔼 درحال آپلود در روبیکا...")
    try:
        result = send_to_channel_sync(str(send_path), caption)
        message_id = str(result.get("message_id", "") if result else "")
    except Exception as e:
        push_status(task, f"❌ خطا: {str(e)}")
        raise

    # بروزرسانی دیتابیس
    if unique_code:
        db.update_rubika_info(unique_code, RUBIKA_CHANNEL_GUID, message_id)

    push_status(
        task,
        f"✅ **فایل آپلود شد!**\n\n"
        f"🎫 کد: `{unique_code or '—'}`\n\n"
        f"اکنون این کد را در ربات روبیکا وارد کن تا فایل برایت ارسال شود."
    )

# ───────────────────────── صف فوروارد ────────────────────────────────────

def process_forward_queue():
    """ارسال فایل از کانال به کاربر روبیکا"""
    while True:
        time.sleep(1)
        try:
            fwd = db.pop_forward()
            if not fwd:
                continue

            unique_code = fwd.get("unique_code")
            rubika_user_id = fwd.get("rubika_user_id")

            if not unique_code or not rubika_user_id:
                db.fail_forward(fwd["id"], "اطلاعات ناقص")
                continue

            # دریافت فایل از دیتابیس
            file_record = db.get_file_by_code(unique_code)
            if not file_record:
                db.fail_forward(fwd["id"], "فایل پیدا نشد")
                continue

            archive_path = file_record["archive_path"]
            if not archive_path or not Path(archive_path).exists():
                db.fail_forward(fwd["id"], "فایل موجود نیست")
                continue

            # ارسال به کاربر
            cap = f"📥 فایل\n📄 {file_record['file_name']}\n📦 {db.pretty_size(file_record['file_size'])}"
            send_file_to_user_sync(rubika_user_id, archive_path, cap)
            
            db.complete_forward(fwd["id"])
            db.mark_delivered(unique_code)
            print(f"✅ فایل {unique_code} برای {rubika_user_id[:12]}… ارسال شد")

        except Exception as e:
            if fwd:
                db.fail_forward(fwd["id"], str(e))
            print(f"❌ خطا در فوروارد: {e}")

# ───────────────────────── صف اصلی ────────────────────────────────────────

def pop_first_task():
    if not QUEUE_FILE.exists():
        return None
    with open(QUEUE_FILE, encoding="utf-8") as f:
        lines = [l for l in f if l.strip()]
    if not lines:
        return None
    first = lines[0]
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines[1:])
    return json.loads(first)

def append_failed(task: dict, error: str):
    with open(FAILED_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"task": task, "error": error}, ensure_ascii=False) + "\n")

# ───────────────────────── اجرا ────────────────────────────────────────────

def worker_loop():
    ensure_session()
    print("✅ ورکر روبیکا شروع به کار کرد.")

    # صف فوروارد
    threading.Thread(target=process_forward_queue, daemon=True).start()

    # صف اصلی
    while True:
        task = pop_first_task()
        if not task:
            time.sleep(0.5)
            continue

        try:
            print(f"📋 پردازش تسک: {task.get('file_name', 'نامعلوم')}")
            process_task(task)
        except Exception as e:
            print(f"❌ خطا: {e}")
            append_failed(task, str(e))
            push_status(task, f"❌ خطا: {str(e)}")

if __name__ == "__main__":
    worker_loop()
